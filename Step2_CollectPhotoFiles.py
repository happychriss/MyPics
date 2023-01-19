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
from config import db_PicasaFolder,db_Albums,db_Photos,db_JobControl, pp_Photos, pp_Albums,local_engine,pp_engine,picasa_pics
from config import CLIENT_SECRET_FILE,TAKEOUT_PATH,S10_BACKUP_PATH,PICASA_BACKUP_PATH,GOOGLE_DOWNLOAD_RESULTS_PATH,COPY_TARGET_FOLDER_PATH
from config import GOOGLE_TAKEOUT_REWORK_TEXT
from config import STR_REFRESH_PICS_META_FROM_GOOGLE,STR_REFRESH_PHOTOS_FILE_PATH,STR_COPY_TO_TARGET_FOLDERS,STR_PHOTO_PRISM_CREATE_ALBUM
from config import  album_manager, media_manager


def collect_photo_files():

    print("\n\n**** Refresh - Pull missing photos from Google")
    session = Session(local_engine)
    photo_no_backup_source_stmt = select(db_Photos).where(db_Photos.google_api_status == 'U')
    for db_photo in session.scalars(photo_no_backup_source_stmt):
        g_photo = media_manager.get(db_photo.media_id)
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

    print("\n\n**** Copy to PhotPrism Target Folder: ")
    print("Target Folder: "+ COPY_TARGET_FOLDER_PATH)
    session = Session(local_engine)

    photo_no_backup_source_stmt = select(db_Photos).where(db_Photos.pp_upload_status == 'U')
    for db_photo in session.scalars(photo_no_backup_source_stmt):
        db_album=session.execute(select(db_Albums).where(db_photo.album_id == db_Albums.id)).first()[0]


        directory_target_path = os.path.join(COPY_TARGET_FOLDER_PATH, target_album_filename(db_album.title, db_album.id))
        if not exists(directory_target_path):
            os.mkdir(directory_target_path)
            print("New Directory: " + directory_target_path)

        target_path = os.path.join(directory_target_path, target_photo_filename(db_album.id, db_photo.id, db_photo.filename))
        if not exists(target_path):
            print("Title: " + db_album.title + "(" + str(db_album.id) + ")\t\t"+target_path)
            copyfile(db_photo.filepath, target_path)


def target_photo_filename(album_id, photo_id, filename):
    return str(album_id) + "_" + str(photo_id) + pathlib.Path(filename).suffix

def target_album_filename(album_title, album_id):
    return sanitize_filename(album_title) + "_" + str(album_id)
