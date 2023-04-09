import hashlib
import os
from dotenv import load_dotenv
from gphotospy import authorize
from gphotospy.album import *
from gphotospy.media import Media, MediaItem
from sqlalchemy import create_engine, select, update, func, union, literal, union_all
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.inspection import inspect
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.ext.automap import automap_base
import sqlalchemy as sa
from datetime import datetime, timedelta
import logging
import time
from pathvalidate import sanitize_filename
from shutil import copyfile
import pathlib
from os.path import exists
import requests
import command
import glob
from dateutil import parser
import exifread

from config import get_albums_first_photo
from config import db_PhotoArchive, db_Albums, db_Photos, db_JobControl,  local_engine,  picasa_pics, ALBUM_SOURCE_FOLDER, SOURCE_FORMAT_GOOGLE, \
    ALBUM_SOURCE_GOOGLE, get_archive_by_source
from config import CLIENT_SECRET_FILE,TAKEOUT_PATH,S10_BACKUP_PATH,PICASA_BACKUP_PATH,GOOGLE_DOWNLOAD_RESULTS_PATH,COPY_TARGET_FOLDER_PATH
from config import GOOGLE_TAKEOUT_REWORK_TEXT
from config import SOURCE_FORMAT_TAKEOUT, SOURCE_FORMAT_FOLDER
from config import STR_REFRESH_PICS_META_FROM_GOOGLE,STR_REFRESH_PHOTOS_FILE_PATH,STR_COPY_TO_TARGET_FOLDERS,STR_PHOTO_PRISM_CREATE_ALBUM
from config import Archive
from config import json_my_pics_config,get_source_format,get_archives_by_source_format
import json

from config import TAKEOUT_MATCH_FORCE


## the main function, to match the photos in photo-archive with photos from album
def match_google_photos():
    print("\n\n** Match Google Photos **")
    session = Session(local_engine)

    # Get list of archives sorted by prio to be searched for matching photos for Google (album_source = Google)
    matching = json_my_pics_config['matching_algo']
    matching_sorted=sorted(matching, key=lambda x: x["prio"], reverse=True)

    archives=json_my_pics_config["archives"]
    takeout_sources = [d['source_name'] for d in archives if d.get("source_format") == SOURCE_FORMAT_TAKEOUT]

    for db_album in session.scalars(select(db_Albums).filter(db_Albums.album_source == ALBUM_SOURCE_GOOGLE,db_Albums.id!=399)):
        title=db_album.title.strip()
        print("Title: " + title)
        for db_photo in session.scalars(select(db_Photos).where(db_Photos.album_id==db_album.id).where(db_Photos.photo_status!='D')):

            #only need to try new match for photos not from takeout
            if TAKEOUT_MATCH_FORCE or (get_source_format(db_photo.source) != SOURCE_FORMAT_TAKEOUT):

                old_backup_source=db_photo.source
                old_filepath = db_photo.filepath
                if match_photo_path(session, db_album, db_photo,
                                    matching_sorted,
                                    takeout_sources):

                    if old_backup_source != db_photo.source or old_filepath != db_photo.filepath:
                        str_action = 'New-Match:'
                    else:
                        str_action='Old-Match:'
                else:
                    str_action='No-Match:'
            else:
                str_action = 'No-Action:'

            print(str_action +"\t\tSource: " + (db_photo.source or  "No Source") +
                  "\t\tMatching: " + (db_photo.photo_status or "None") + "\t\tName: " + db_photo.filename + "\t\tCamera: " + (db_photo.camera or "None"))

            session.add(db_photo)

        session.commit()

        cover_photo_stmt = select(db_Photos).where(db_Photos.album_id == db_album.id).where(db_Photos.filename == db_album.cover_filename)
        cover_photo = session.execute(cover_photo_stmt).first()

        #update album-created at based on photo-dates
        first_album_photo=get_albums_first_photo(session, db_album)
        db_album.taken_at=first_album_photo.taken_at

        if cover_photo is not None:
            my_cover_photo = cover_photo[0]
            db_album.cover_photo_id = my_cover_photo.id
            session.add(db_album)
            print("Cover Foto found :-)")
        else:
            db_album.cover_photo_id=first_album_photo.id
            print("Cover Foto not found :-(")

        session.add(db_album)
        session.commit()
        print("********************")

    session.close()


# ----
### Core logic to find the best matching photos based on priority:

# Prio-1: Takeout, as it also contains photos that have been reworked
# Prio-2: Handy Photos, as they contain full exif information with geo-location
# Prio-3: Picasa photos, some of those pictures also have exif
# Prio-4: Downloaded photos form google-album (removed geo-location by google)


def copy_archive_to_photos(db_my_photo, db_my_archive):
    db_my_photo.filepath = db_my_archive.filepath
    db_my_photo.source = db_my_archive.source
    db_my_photo.photo_lat = db_my_archive.photo_lat
    db_my_photo.photo_lng = db_my_archive.photo_lng
    db_my_photo.photo_status = 'M'
    db_my_photo.photo_width = db_my_archive.photo_width
    db_my_photo.photo_height = db_my_archive.photo_height
    db_my_photo.photo_orientation = db_my_archive.photo_orientation
    db_my_photo.media_type= db_my_archive.media_type
    db_my_photo.photo_archive_id=db_my_archive.id
    if not db_my_photo.camera:
        db_my_photo.camera=db_my_archive.camera
    return


# This is the key functions - that tries to find the best matching photos from the photos-archive for the album photos
# photo exists already from google-album - try to match it from photo_archive
def match_photo_path(session,
                     db_album, db_photo,
                     matching_sorted,
                     takeout_sources):

    special_char_map = {ord('ä'): '_', ord('ü'): '_', ord('ö'): '_', ord('ß'): '_'}

    # Check for a good source - based on best information, Sequence of checks is based on information quality provided

    album_name_for_takeout=db_album.title.translate(special_char_map)

    # check in all takeout sources for filename and matching album - this is the best matching
    # dont change order, sqlalchemy union does not return header
    stmt_query=session.query(literal('ALBUM').label('matching_type'),db_PhotoArchive.id, db_PhotoArchive.source,db_PhotoArchive.filepath)

    stmt_by_archive_album = session.query(literal('ALBUM').label('matching_type'),db_PhotoArchive.id, db_PhotoArchive.source,db_PhotoArchive.filepath).\
        where(db_PhotoArchive.filename == db_photo.filename).\
        where(func.trim(db_PhotoArchive.album_name) == func.trim(album_name_for_takeout)).\
        where(db_PhotoArchive.source.in_(takeout_sources))

    # check in all sources for filename and time matching - also pretty good
    stmt_by_timestamp= session.query(literal('TIME').label('matching_type'),db_PhotoArchive.id, db_PhotoArchive.source,db_PhotoArchive.filepath).\
        where(func.trim(db_PhotoArchive.filename) == func.trim(db_photo.filename)).\
        where(db_PhotoArchive.taken_at >= db_photo.taken_at - timedelta(hours=24)).\
        where(db_PhotoArchive.taken_at <= db_photo.taken_at + timedelta(hours=24))

    stmt_matching_archive=union_all(stmt_by_archive_album,stmt_by_timestamp)

    db_photo_archives=session.execute(stmt_matching_archive).fetchall()

    # Loop through all archives by prio to find match with highest prio

    for match in matching_sorted:
        for db_archive_arr in db_photo_archives:
            db_archive_source_format=get_source_format(db_archive_arr[2])
            if match['source_format']==db_archive_source_format and match['matching_type']==db_archive_arr[0]:
                db_archive=session.query(db_PhotoArchive).get(db_archive_arr[1])
                copy_archive_to_photos(db_photo, db_archive)
                # all non-takeout sources try to guess the date from exif in local time
                db_photo.taken_at = db_archive.taken_at
                db_photo.taken_at_local_time=db_archive.taken_at_local_time
                db_photo.photo_status=match['id']
                return True

    # Nothing found - need to use Google  ----------------------------------------

    db_photo.photo_status = 'U'
    return False



