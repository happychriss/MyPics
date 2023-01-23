import hashlib
import os
from dotenv import load_dotenv

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

from config import db_PicasaFolder,db_Albums,db_Photos,db_JobControl, pp_Photos, pp_Albums,local_engine,pp_engine
from config import CLIENT_SECRET_FILE,TAKEOUT_PATH,S10_BACKUP_PATH,PICASA_BACKUP_PATH,GOOGLE_DOWNLOAD_RESULTS_PATH,COPY_TARGET_FOLDER_PATH
from config import GOOGLE_TAKEOUT_REWORK_TEXT
from config import STR_REFRESH_PICS_META_FROM_GOOGLE,STR_REFRESH_PHOTOS_FILE_PATH,STR_COPY_TO_TARGET_FOLDERS,STR_PHOTO_PRISM_CREATE_ALBUM
from config import  album_manager, media_manager

from Step1_RefreshMetaData import refresh_album_metadata
from Step2_UploadPhotos import  upload_photos_to_pp
from Step3_UpdateAlbumInformation import update_photo_prism_album

load_dotenv()
logging.basicConfig()
logging.getLogger("sqlalchemy.engine").setLevel(logging.ERROR)


# ****************   Steps ***********************************
STEP1_REFRESH_METADATA = False  # Loop over all albums from Google and update metadata in local DB
STEP2_UPLOAD_PHOTOS = False
STEP3_UPDATE_ALBUM_INFO = True

REFRESH_PHOTOS_FILE_PATH = False  # Try to match all downloaded photos from Google with a file at the local PC to get full exif-information
REFRESH_MISSING_PHOTOS_FROM_GOOGLE = False  # All photos without source (could not be matched in previous step) will download information from Google
REFRESH_ALBUM_COVER = False  # Loop over all albums in local DB and refresh the album-cover from Google metatdata
COPY_TO_TARGET_FOLDERS = False

PHOTO_PRISM_UPDATE_COVER = False
REFRESH_PICASA_FOLDER_DB = False



def main():
    # Step-1: Read all Albums meta information from Google Photos
    if STEP1_REFRESH_METADATA:
        refresh_album_metadata()

    # Step-2: Download missing files from Google and prepare files to PhotoPrism import (copy to import folder)
    if STEP2_UPLOAD_PHOTOS:
        upload_photos_to_pp()

    # Step-3: Loads all files in a folder and stores filename and path in tmp table (only when new folder structure)

    if REFRESH_PICASA_FOLDER_DB:
        print("Refresh Picasa: Loading File list")
        session = Session(local_engine)

        for path, subdirs, files in os.walk(PICASA_BACKUP_PATH):

            for name in files:
                new_entry = db_PicasaFolder(file_name=name, file_path=os.path.join(path, name))
                session.add(new_entry)
                session.commit()
        print("DONE")


    # # Step-6: Based on album meta information from Google tries to find the cover photo ID and updates in album
    # if REFRESH_ALBUM_COVER:
    #     print("** Refresh Album Cover Information**")
    #     session = Session(local_engine)
    #     for db_Album in session.scalars(select(db_Albums)):
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


    # Step-8: Create the Album in Photoprism from local database information
    if STEP3_UPDATE_ALBUM_INFO:
        update_photo_prism_album()



# ---------------------- Support functions



# Press the green button in the gutter to run the script.
if __name__ == '__main__':
    main()

# See PyCharm help at https://www.jetbrains.com/help/pycharm/
