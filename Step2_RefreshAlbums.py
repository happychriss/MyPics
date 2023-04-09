import hashlib
import os
from dotenv import load_dotenv
from gphotospy import authorize
from gphotospy.album import *
from gphotospy.media import Media, MediaItem
from sqlalchemy import create_engine, select, update, func,desc
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.inspection import inspect
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.ext.automap import automap_base
import sqlalchemy as sa
from datetime import datetime
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
import  config

from config import db_PhotoArchive, db_Albums, db_Photos, db_JobControl, local_engine, picasa_pics
from config import CLIENT_SECRET_FILE, TAKEOUT_PATH, S10_BACKUP_PATH, PICASA_BACKUP_PATH, GOOGLE_DOWNLOAD_RESULTS_PATH, COPY_TARGET_FOLDER_PATH
from config import GOOGLE_TAKEOUT_REWORK_TEXT
from config import STR_REFRESH_PICS_META_FROM_GOOGLE, STR_REFRESH_PHOTOS_FILE_PATH, STR_COPY_TO_TARGET_FOLDERS, STR_PHOTO_PRISM_CREATE_ALBUM
from Step3_MatchPhotos import copy_archive_to_photos
from config import get_archive_by_source, Archive,ALBUM_SOURCE_GOOGLE
import json

# Instead of building album from Google, look at folder in photo_archive database as baseline
# No matching is needed, photos are added 1:1 to album, for picasa album, only photos with "star" are added


def refresh_albums_from_folders(source):
    archive=get_archive_by_source(source)

    print("\n\n** Refresh Albums from Folder for Source: "+archive.source_name)

    session = Session(local_engine)

    album_titles = session.query(db_PhotoArchive.album_name.distinct()).\
        filter(db_PhotoArchive.source == archive.source_name,db_PhotoArchive.media_type=='image/jpeg').all()

    for album_title_tmp in album_titles:
        album_title=album_title_tmp[0]

        db_album = session.execute(select(db_Albums).filter(db_Albums.title == album_title).
                                   filter(db_Albums.album_source == archive.album_source)).scalar()
        if not db_album:

            print("   New: \t" + album_title)
            db_album = db_Albums(title=album_title, album_status=None, album_source=archive.album_source, google_id=0)
        else:
            print("   Old: \t" + album_title)

        session.add(db_album)

        # loop over all photos in archive with this title and add as photo to album

        stm_find_photos_star = select(db_PhotoArchive).filter(db_PhotoArchive.album_name == album_title,
                                                         db_PhotoArchive.source == archive.source_name,
                                                         db_PhotoArchive.b_picasa_star == True).order_by(db_PhotoArchive.taken_at)

        stm_find_photos_no_star = select(db_PhotoArchive).filter(db_PhotoArchive.album_name == album_title,
                                                         db_PhotoArchive.source == archive.source_name).order_by(db_PhotoArchive.taken_at)

        if archive.source_format== config.SOURCE_FORMAT_PICASA:
            stm_find_photos=stm_find_photos_star
            if session.execute(stm_find_photos).scalar() is  None:
                stm_find_photos =stm_find_photos_no_star
        else:
            stm_find_photos =stm_find_photos_no_star

        photo_seq=1
        for db_my_archive in session.scalars(stm_find_photos):

            #check if already added
            photo_find_stmt = select(db_Photos).filter(db_Photos.album_id == db_album.id,db_Photos.photo_archive_id == db_my_archive.id)

            if not session.execute(photo_find_stmt).scalar():

                db_my_photo = db_Photos(
                    filename=db_my_archive.filename,
                    created_at= datetime.now(),
                    album_id=db_album.id,
                    photo_seq=photo_seq
                )

                copy_archive_to_photos(db_my_photo, db_my_archive)
                db_my_photo.taken_at = db_my_archive.taken_at
                db_my_photo.taken_at_local_time =db_my_archive.taken_at_local_time ##assuming from folder local time is correct

                session.add(db_my_photo)

                photo_seq=photo_seq+1
                print('.', end='')
            else:
                print('d', end='')
        session.commit()

        # Update Album Information
        db_tmp_album= session.query(db_Albums).get(db_album.id)
        first_album_photo= config.get_albums_first_photo(session, db_album)

        db_tmp_album.cover_filename=first_album_photo.filename
        db_tmp_album.cover_photo_id=first_album_photo.id
        db_tmp_album.taken_at=first_album_photo.taken_at
        db_tmp_album.created_at=datetime.now()
        db_tmp_album.photos_count = session.execute(select(func.count()).filter(db_Photos.album_id == db_album.id)).scalar()
        session.add(db_tmp_album)

        session.commit()

    # Update Album_seq will not be updated for folders

    session.commit()
    session.close()

# running to catch up with any change in google-album
def refresh_albums_from_google():
    service = authorize.init(CLIENT_SECRET_FILE)
    album_manager = Album(service)
    media_manager = Media(service)
    album_iterator = album_manager.list()

    # *************************************************************************************
    # Step-1: Read all Albums meta information from Google Photos
    #         Album_Status: N = New Album
    #         Album_Status: U = Album information updated
    # *************************************************************************************

    print("\n\n** Refresh Albums from Google **")
    session = Session(local_engine)
    session.execute(update(db_Albums).values(album_seq=None))

    album_seq = 1
    for album in album_iterator:

        # check if album already exits

        album_find_stmt = select(db_Albums).filter(db_Albums.google_id == album['id'],db_Albums.album_source==ALBUM_SOURCE_GOOGLE)

        coverFileName = media_manager.get(album['coverPhotoMediaItemId'])['filename']

        if not session.execute(album_find_stmt).first():
            print("   New: \t" + album.get("title"))
            my_album = db_Albums(google_id=album.get('id'),
                                 title=album.get("title"),
                                 cover_filename=coverFileName,
                                 photos_count=album.get("mediaItemsCount"),
                                 album_status='U',
                                 album_seq=album_seq,
                                 album_source=ALBUM_SOURCE_GOOGLE,
                                 created_at=datetime.now())

            session.add(my_album)

        else:

            my_album = session.execute(album_find_stmt).first()[0]
            if ((my_album.title != album.get("title")) or
                    (my_album.photos_count != int(album.get("mediaItemsCount"))) or
                    (my_album.cover_filename != coverFileName)):

                my_album.album_status = 'U'

                if my_album.cover_filename != coverFileName:
                    my_album.cover_change_status = 'U'

                print("   Updated" + " (" + (my_album.cover_change_status or "N") + "):\t" + album.get("title"))
            else:
                print("   NoChange: \t" + album.get("title"))

            my_album.album_seq = album_seq
            my_album.title = album.get("title")
            my_album.photos_count = album.get("mediaItemsCount")
            my_album.cover_filename = coverFileName
            my_album.updated_at=datetime.now()

            session.add(my_album)

        album_seq = album_seq + 1

    session.commit()
    session.close()

    # *************************************************************************************
    # Step2: Read all pics meta information from Google Photos based on downloaded albums
    #        Photo_Status: U - photos was updated and needs to be matched
    #        Creates Photo_Seq according to downloaded order from Google Photos
    # *************************************************************************************

    print("\n\n** Refresh Fotos **")
    session = Session(local_engine)

    session.execute(update(db_Photos).values(photo_seq=None))

#    for db_Album in session.scalars(select(db_Albums).where(db_Albums.album_status != 'D')):
    for db_Album in session.scalars(select(db_Albums).filter(db_Albums.album_status == 'U', db_Albums.album_source == ALBUM_SOURCE_GOOGLE)):
        #if db_Album.title!='Test03': continue
        print("Title: " + db_Album.title)
        photo_iterator = media_manager.search_album(db_Album.google_id)
        photo_seq = 1

        db_Album.album_status = None
        session.add(db_Album)

        for photo in photo_iterator:
            album_id = db_Album.id

            # check if foto is already existing
            foto_find_stmt = select(db_Photos).where(db_Photos.album_id == album_id).where(db_Photos.google_id == photo['id'])
            if not session.execute(foto_find_stmt).first():

                media_type = photo.get('mediaMetadata').get('photo')

                camera = None
                if media_type:
                    camera = media_type.get('cameraModel')

                db_photo = db_Photos(
                    album_id=db_Album.id,
                    google_id=photo['id'],
                    filename=photo['filename'],
                    media_type=photo['mimeType'],
                    camera=camera,
                    photo_seq=photo_seq,
                    photo_status='U',
                    taken_at=datetime.strptime(photo['mediaMetadata']['creationTime'], "%Y-%m-%dT%H:%M:%SZ"),
                    taken_at_local_time=False,
                    created_at=datetime.now())


                print("\tNew:"+db_photo.filename)

            else:
                db_photo = session.execute(foto_find_stmt).first()[0]
                db_photo.photo_seq = photo_seq
                db_photo.photo_status = 'U' # we allways try to match all photos, might be improved in future

            session.add(db_photo)
            photo_seq = photo_seq + 1

    # Delete 'deleted' albums and photos - not having a sequence anymore
    sq = select(db_Albums.id).where(db_Albums.album_seq == None)
    session.execute(update(db_Photos).where(db_Photos.album_id.in_(sq)).values(photo_status='D').execution_options(synchronize_session="fetch"))

    session.execute(update(db_Albums).where(db_Albums.album_seq == None).values(album_status='D'))
    session.commit()
    session.close()
