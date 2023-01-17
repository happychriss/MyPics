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

from config import db_PicasaFolder,db_Albums,db_Photos,db_JobControl, pp_Photos, pp_Albums,local_engine,pp_engine
from config import CLIENT_SECRET_FILE,TAKEOUT_PATH,S10_BACKUP_PATH,PICASA_BACKUP_PATH,GOOGLE_DOWNLOAD_RESULTS_PATH,COPY_TARGET_FOLDER_PATH
from config import GOOGLE_TAKEOUT_REWORK_TEXT
from config import STR_REFRESH_PICS_META_FROM_GOOGLE,STR_REFRESH_PHOTOS_FILE_PATH,STR_COPY_TO_TARGET_FOLDERS,STR_PHOTO_PRISM_CREATE_ALBUM

from Step1_RefreshMetaData import refresh_album_metadata

load_dotenv()
logging.basicConfig()
logging.getLogger("sqlalchemy.engine").setLevel(logging.ERROR)


# ****************   Steps ***********************************
REFRESH_ALBUM_META_FROM_GOOGLE = True  # Loop over all albums from Google and update metadata in local DB

REFRESH_PHOTOS_FILE_PATH = False  # Try to match all downloaded photos from Google with a file at the local PC to get full exif-information
REFRESH_MISSING_PHOTOS_FROM_GOOGLE = False  # All photos without source (could not be matched in previous step) will download information from Google
REFRESH_ALBUM_COVER = False  # Loop over all albums in local DB and refresh the album-cover from Google metatdata
COPY_TO_TARGET_FOLDERS = False
PHOTO_PRISM_CREATE_ALBUM = False
PHOTO_PRISM_UPDATE_COVER = False
REFRESH_PICASA_FOLDER_DB = False



def main():
    if   REFRESH_MISSING_PHOTOS_FROM_GOOGLE or PHOTO_PRISM_CREATE_ALBUM:
        service = authorize.init(CLIENT_SECRET_FILE)
        album_manager = Album(service)
        media_manager = Media(service)
        print("Getting a list of albums...")
        album_iterator = album_manager.list()

    # *************************************************************************************
    # Step-1: Read all Albums meta information from Google Photos
    # *************************************************************************************

    if REFRESH_ALBUM_META_FROM_GOOGLE:
        refresh_album_metadata()

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

    # Step-4: Search all pics in Albums and tries to find the matching filepath from different sources (Takeout, Picasa, Folder)
    if REFRESH_PHOTOS_FILE_PATH:
        print("** Refresh Filepath**")
        session = Session(local_engine)
        last_file_path_refresh_date = session.execute(select(db_JobControl).where(db_JobControl.step == STR_REFRESH_PHOTOS_FILE_PATH)).first()[0].last_run_at
        for db_Album in session.scalars(select(db_Albums).where(db_Albums.updated_at > last_file_path_refresh_date)):
            print("Title: " + db_Album.title + " ****************")

            #            photo_stmt = select(db_Photos).where(db_Photos.album_id == db_Album.id).where(db_Photos.backup_source == None)
            photo_stmt = select(db_Photos).where(db_Photos.album_id == db_Album.id)
            for photo in session.scalars(photo_stmt):
                backup_source, filepath = photo_find_path(db_Album.title, photo.filename, photo.created, picasa_pics)
                if backup_source != photo.backup_source or filepath != photo.filepath:
                    photo.updated_at = datetime.now()
                    photo.backup_source=backup_source
                    photo.filepath = filepath
                    session.add(photo)

        session.execute(update(db_JobControl).where(db_JobControl.step == STR_REFRESH_PHOTOS_FILE_PATH).values(last_run_at=datetime.now()))
        session.commit()
        session.close()

    # Step-5: For all photos without backup_source (not found in previous steps) - download from Google
    if REFRESH_MISSING_PHOTOS_FROM_GOOGLE:
        print("****** Refresh - Pull missing photos from Google")
        session = Session(local_engine)
        for db_Album in session.scalars(select(db_Albums)):
            print("Title: " + db_Album.title + " ****************")
            db_album_id = db_Album.id
            photo_no_backup_source_stmt = select(db_Photos).where(db_Photos.album_id == db_album_id).where(db_Photos.backup_source == 'Google')
            for db_photo in session.scalars(photo_no_backup_source_stmt):
                g_photo = media_manager.get(db_photo.media_id)
                g_media = MediaItem(g_photo)

                download_path = os.path.join(GOOGLE_DOWNLOAD_RESULTS_PATH, "IDG_" + str(db_photo.id) + "_" + sanitize_filename(db_photo.filename).replace(" ", "_"))
                with open(download_path, 'wb') as output:
                    output.write(g_media.raw_download())

                db_photo.filepath = download_path
                db_photo.backup_source = "Google"
                session.add(db_photo)
                print("    Wrote: " + db_photo.filename)

        session.commit()
        session.close()

    # Step-6: Based on album meta information from Google tries to find the cover photo ID and updates in album
    if REFRESH_ALBUM_COVER:
        print("** Refresh Album Cover Information**")
        session = Session(local_engine)
        for db_Album in session.scalars(select(db_Albums)):
            cover_photo_stmt = select(db_Photos).where(db_Photos.album_id == db_Album.id).where(db_Photos.filename == db_Album.cover_filename)
            cover_photo = session.execute(cover_photo_stmt).first()

            if cover_photo is not None:
                my_cover_photo = cover_photo[0]
                db_Album.cover_path = target_photo_filename(db_Album.id, my_cover_photo.id, my_cover_photo.filename)
                db_Album.cover_photo_id = my_cover_photo.id
                session.add(db_Album)
            else:
                print("Cover not found for Title: " + db_Album.title)

        session.commit()
        session.close()

    # Step-7: Build Target Folder Structure for Import into PhotoPrism from Database, based on Album/Photo Structure
    if COPY_TO_TARGET_FOLDERS:
        print("Copy to target folder: " + COPY_TARGET_FOLDER_PATH)
        session = Session(local_engine)
        last_copy_target_date = session.execute(select(db_JobControl).where(db_JobControl.step == STR_COPY_TO_TARGET_FOLDERS)).first()[0].last_run_at
        for db_Album in session.scalars(select(db_Albums).where(db_Albums.updated_at > last_copy_target_date).order_by(db_Albums.album_seq)):
            print("Title: " + db_Album.title + " ****************")
            directory_target_path = os.path.join(COPY_TARGET_FOLDER_PATH, target_album_filename(db_Album.title, db_Album.id))
            if not exists(directory_target_path):
                os.mkdir(directory_target_path)
                print("New Directory: " + directory_target_path)

            photo_no_backup_source_stmt = select(db_Photos).where(db_Photos.album_id == db_Album.id).where(db_Photos.updated_at>last_copy_target_date)
            for db_photo in session.scalars(photo_no_backup_source_stmt):
                target_path = os.path.join(directory_target_path, target_photo_filename(db_Album.id, db_photo.id, db_photo.filename))
                if not exists(target_path):
                    print("    File: " + target_path)
                    copyfile(db_photo.filepath, target_path)

    # Step-8: Create the Album in Photoprism from local database information
    if PHOTO_PRISM_CREATE_ALBUM:
        print("** Create Albums with Photos in Photoprism**")

        server = "http://zo:2342"
        sessionAPI = "/api/v1/session"
        albumAPI = "/api/v1/albums"
        fileAPI = "/api/v1/files"
        fotoAPI = "/api/v1/photos"

        ## Authenticate with Photo Prism Server
        s = requests.Session()

        r = s.post(server + sessionAPI, json={'username': os.getenv('PP_API_USER'), 'password': os.getenv('PP_API_PWD')})
        auth_session_id = r.json()['id']
        s.headers.update({"X-Session-ID": auth_session_id})

        ## Loop over all Albums
        session = Session(local_engine)
        last_photo_prism_album_update = session.execute(select(db_JobControl).where(db_JobControl.step == STR_PHOTO_PRISM_CREATE_ALBUM)).first()[0].last_run_at

        stmt_get_update_albums = select(db_Photos.album_id).join(db_Albums, db_Albums.id==db_Photos.album_id).where((db_Albums.updated_at > last_photo_prism_album_update) | (db_Photos.updated_at > last_photo_prism_album_update)).distinct()
        for db_Album_id in session.scalars(stmt_get_update_albums):

            db_Album=session.execute(select(db_Albums).where(db_Albums.id == db_Album_id)).first()[0]
            print("Album: "+db_Album.title)
            # create album
            album_uid = s.post(server + albumAPI, json={'Title': db_Album.title, 'Description': db_Album.title}).json()['UID']
            json_photo = {'photos': []}
            db_Album.pp_uid = album_uid

            photo_upload_stmt = select(db_Photos).where(db_Photos.album_id == db_Album.id).where(db_Photos.backup_source != None).order_by(db_Photos.photo_seq)
            for db_photo in session.scalars(photo_upload_stmt):
                print("   Photo: " + db_photo.filename)
                # get uid (photo was loaded before to PhotoPrism
                photo_hash = get_sha1hash(db_photo.filepath)
                foto_uid = s.get(server + fileAPI + "/" + photo_hash).json()['PhotoUID']
                json_photo['photos'].append(foto_uid)

            r = s.post(server + albumAPI + "/" + album_uid + "/photos", json=json_photo)

            if r.status_code == 200:
                print("** OK **")
            else:
                print("************** ERROR: " + str(r.status_code) + "for Album: " + db_Album.title)

        session.commit()
        session.close()

    # Step - 9: Update the cover photo by direct updating PhotoPrism database
    if PHOTO_PRISM_UPDATE_COVER:
        print("** Update Cover Photo in PhotoPrism**")
        session = Session()

        for db_Album in session.scalars(select(db_Albums)):
            # find matching Album in PP

            pp_uid = str.encode(db_Album.pp_uid)
            pp_album_find_stmt = select(pp_Albums).where(pp_Albums.album_uid == pp_uid)
            pp_Album = session.execute(pp_album_find_stmt).first()[0]

            # Calculate hash of the cover photo
            cover_photo_stmt = select(db_Photos).where(db_Photos.id == db_Album.cover_photo_id)
            cover_photo = session.execute(cover_photo_stmt).first()[0]
            cover_hash = get_sha1hash(cover_photo.filepath)

            # Update the PP album
            pp_Album.thumb = str.encode(cover_hash)
            pp_Album.album_order = str.encode('added')

        session.commit()
        session.close()


def get_sha1hash(file):
    BLOCK_SIZE = 65536  # The size of each read from the file

    file_hash = hashlib.sha1()  # Create the hash object, can use something other than `.sha256()` if you wish
    with open(file, 'rb') as f:  # Open the file to read it's bytes
        fb = f.read(BLOCK_SIZE)  # Read from the file. Take in the amount declared above
        while len(fb) > 0:  # While there is still data being read from the file
            file_hash.update(fb)  # Update the hash
            fb = f.read(BLOCK_SIZE)  # Read the next block from the file

    return file_hash.hexdigest()  # Get the hexadecimal digest of the hash


def target_photo_filename(album_id, photo_id, filename):
    return str(album_id) + "_" + str(photo_id) + pathlib.Path(filename).suffix


def target_album_filename(album_title, album_id):
    return sanitize_filename(album_title) + "_" + str(album_id)


# ---------------------- Support functions



# Press the green button in the gutter to run the script.
if __name__ == '__main__':
    main()

# See PyCharm help at https://www.jetbrains.com/help/pycharm/
