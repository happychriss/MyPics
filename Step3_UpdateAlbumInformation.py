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
from config import SERVER,SESSION_API,ALBUM_API,FILE_API,FOTO_API

def update_photo_prism_album():

    print("\n\n**** Create or update albums with Photos in Photoprism**")

    ## Authenticate with Photo Prism Server
    s = requests.Session()

    r = s.post(SERVER + SESSION_API, json={'username': os.getenv('PP_API_USER'), 'password': os.getenv('PP_API_PWD')})
    auth_session_id = r.json()['id']
    s.headers.update({"X-Session-ID": auth_session_id})

    ## Loop over all Albums
    session = Session(local_engine)

    # Update all files with changed albums or changed Photos
    stmt_get_update_albums = select(db_Photos.album_id).join(db_Albums, db_Albums.id==db_Photos.album_id).where((db_Albums.album_status == 'U') | (db_Photos.photo_status == 'P')).distinct()
    for db_Album_id in session.scalars(stmt_get_update_albums):

        db_Album=session.execute(select(db_Albums).where(db_Albums.id == db_Album_id)).first()[0]
        print("Album: "+db_Album.title)
        # create album
        album_uid = s.post(SERVER + ALBUM_API, json={'Title': db_Album.title, 'Description': db_Album.title}).json()['UID']
        json_photo = {'photos': []}
        db_Album.pp_uid = album_uid

        photo_upload_stmt = select(db_Photos).where(db_Photos.album_id == db_Album.id).where(db_Photos.photo_status=='P').order_by(db_Photos.photo_seq)
        for db_photo in session.scalars(photo_upload_stmt):
            print("   Photo: " + db_photo.filename)
            # get uid from hash (photo was loaded before to PhotoPrism)
            foto_uid = s.get(SERVER + FILE_API + "/" + db_photo.hash).json()['PhotoUID']
            pp_photo=s.get(SERVER + FOTO_API + "/" + foto_uid).json()



            json_photo['photos'].append(foto_uid)

        r = s.post(SERVER + ALBUM_API + "/" + album_uid + "/photos", json=json_photo)

        if r.status_code == 200:
            print("** OK **")
        else:
            print("************** ERROR: " + str(r.status_code) + " for Album: " + db_Album.title)

    session.commit()
    session.close()

def update_photo_prism_cover():
    print("\n\n**** Update Cover Photo in PhotoPrism**")
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



