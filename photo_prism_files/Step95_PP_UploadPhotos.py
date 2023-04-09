import hashlib
import os
from dotenv import load_dotenv
from gphotospy import authorize
from gphotospy.album import *
from gphotospy.media import Media, MediaItem
from sqlalchemy import create_engine, select, update
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
from config import db_PhotoArchive,db_Albums,db_Photos,db_JobControl, pp_Photos, pp_Albums,local_engine,pp_engine,picasa_pics
from config import CLIENT_SECRET_FILE,TAKEOUT_PATH,S10_BACKUP_PATH,PICASA_BACKUP_PATH,GOOGLE_DOWNLOAD_RESULTS_PATH,COPY_TARGET_FOLDER_PATH
from config import GOOGLE_TAKEOUT_REWORK_TEXT
from config import STR_REFRESH_PICS_META_FROM_GOOGLE,STR_REFRESH_PHOTOS_FILE_PATH,STR_COPY_TO_TARGET_FOLDERS,STR_PHOTO_PRISM_CREATE_ALBUM
from config import  album_manager, media_manager


# Photos are uploaded to PhotoPrism by copy to a target folder
def upload_photos_to_pp():

    print("\n\n**** Refresh - Pull missing photos from Google")
    session = Session(local_engine)
    photo_no_backup_source_stmt = select(db_Photos).where(db_Photos.google_api_status == 'U')
    for db_photo in session.scalars(photo_no_backup_source_stmt):
        g_photo = media_manager.get(db_photo.google_id)
        g_media = MediaItem(g_photo)

        download_path = os.path.join(GOOGLE_DOWNLOAD_RESULTS_PATH, "IDG_" + str(db_photo.id) + "_" + sanitize_filename(db_photo.filename).replace(" ", "_"))
        with open(download_path, 'wb') as output:
            output.write(g_media.raw_download())

        db_photo.filepath = download_path
        db_photo.backup_source = "Google"
        db_photo.google_api_status=None
        session.add(db_photo)
        print("    Wrote: " + db_photo.filename)

    session.commit()
    session.close()

    # Step-7: Build Target Folder Structure for Import into PhotoPrism from Database, based on Album/Photo Structure

    print("\n\n**** Copy to PhotPrism Target Folder and set Hash")
    print("Target Folder: "+ COPY_TARGET_FOLDER_PATH)
    session = Session(local_engine)

    photo_no_backup_source_stmt = select(db_Photos).where(db_Photos.photo_status == 'U')
    for db_photo in session.scalars(photo_no_backup_source_stmt):

        db_album=session.execute(select(db_Albums).where(db_photo.album_id == db_Albums.id)).first()[0]

        directory_target_path = os.path.join(COPY_TARGET_FOLDER_PATH, target_album_filename(db_album.title, db_album.id))
        if not exists(directory_target_path):
            os.mkdir(directory_target_path)
            print("New Directory: " + directory_target_path)

        target_filename=target_photo_filename(db_photo)
        target_path = os.path.join(directory_target_path, target_filename)
        if not exists(target_path):
            print("Title: " + db_album.title + "(" + str(db_album.id) + ")\t\t"+target_path)
            copyfile(db_photo.filepath, target_path)
            os.utime(target_path, (db_photo.created.timestamp(), db_photo.created.timestamp()))

        db_photo.hash = get_sha1hash(db_photo.filepath)
        db_photo.photo_status='P'
        session.add(db_photo)

    session.commit()
    session.close()

# def refresh_pp_cover(b_all_albums):
#     print("** Refresh Album Cover Information**")
#     session = Session(local_engine)
#     session = Session(local_engine)
#
#     if b_all_albums:
#         albums_cover_change_stm = select(db_Albums).where(db_Albums.album_seq != None)
#     else:
#         albums_cover_change_stm = select(db_Albums).where(db_Albums.cover_change_status == 'U').where(db_Albums.album_seq != None)
#
#     for db_Album in session.scalars(albums_cover_change_stm):
#
#         cover_photo_stmt = select(db_Photos).where(db_Photos.album_id == db_Album.id).where(db_Photos.filename == db_Album.cover_filename)
#         cover_photo = session.execute(cover_photo_stmt).first()
#
#         if cover_photo is not None:
#             my_cover_photo = cover_photo[0]
#             db_Album.cover_path = target_photo_filename(db_Album.id, my_cover_photo.id, my_cover_photo.filename)
#             db_Album.cover_photo_id = my_cover_photo.id
#             session.add(db_Album)
#         else:
#             print("Cover not found for Title: " + db_Album.title)
#
#     session.commit()
#     session.close()

def target_album_filename(album_title, album_id):
    return sanitize_filename(album_title) + "-" + str(album_id)

def target_photo_filename(db_photo):
    return db_photo.created.strftime("%Y%m%d") + "_" + str(db_photo.id) + "_" + str(pathlib.Path(db_photo.filename))

def get_sha1hash(file):
    BLOCK_SIZE = 65536  # The size of each read from the file

    file_hash = hashlib.sha1()  # Create the hash object, can use something other than `.sha256()` if you wish
    with open(file, 'rb') as f:  # Open the file to read it's bytes
        fb = f.read(BLOCK_SIZE)  # Read from the file. Take in the amount declared above
        while len(fb) > 0:  # While there is still data being read from the file
            file_hash.update(fb)  # Update the hash
            fb = f.read(BLOCK_SIZE)  # Read the next block from the file

    return file_hash.hexdigest()  # Get the hexadecimal digest of the hash
