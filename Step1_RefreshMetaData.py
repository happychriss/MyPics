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


def refresh_album_metadata():
    TEST_BREAK=2
    TEST_ALBUM=1034

    service = authorize.init(CLIENT_SECRET_FILE)
    album_manager = Album(service)
    media_manager = Media(service)
    album_iterator = album_manager.list()

    # *************************************************************************************
    # Step-1: Read all Albums meta information from Google Photos
    # *************************************************************************************

    print("\n\n** Refresh Album **")
    session = Session(local_engine)
    session.execute(update(db_Albums).values(album_seq=None))

    album_seq = 1
    for album in album_iterator:

        # check if album already exits
        album_find_stmt = select(db_Albums).where(db_Albums.album_id == album['id'])
        coverFileName = media_manager.get(album['coverPhotoMediaItemId'])['filename']

        if not session.execute(album_find_stmt).first():
            print("   New: \t" + album.get("title"))
            my_album = db_Albums(album_id=album.get('id'),
                                 title=album.get("title"),
                                 cover_filename=coverFileName,
                                 photos_count=album.get("mediaItemsCount"),
                                 updated_at=datetime.now(),
                                 change_status='N',
                                 album_seq=album_seq)

            session.add(my_album)

        else:

            my_album = session.execute(album_find_stmt).first()[0]
            if ((my_album.title != album.get("title")) or
                    (my_album.photos_count != int(album.get("mediaItemsCount"))) or
                    (my_album.cover_filename != coverFileName) or
                    (my_album.id==TEST_ALBUM)):
                my_album.change_status = 'U'
                print("   Updated: \t" + album.get("title"))
            else:
                print("   NoChange: \t" + album.get("title"))
                my_album.change_status = None

            my_album.album_seq = album_seq
            my_album.title = album.get("title")
            my_album.photos_count = album.get("mediaItemsCount")
            my_album.cover_filename = coverFileName

            session.add(my_album)

        album_seq = album_seq + 1

        if album_seq>TEST_BREAK: break

    session.commit()
    session.close()

    # *************************************************************************************
    # Step2: Read all pics meta information from Google Photos based on downloaded albums
    # *************************************************************************************

    print("\n\n** Refresh Fotos **")
    session = Session(local_engine)

    session.execute(update(db_Photos).values(photo_seq=None))

    for db_Album in session.scalars(select(db_Albums).where(db_Albums.change_status != None)):
        print("Title: " + db_Album.title)
        photo_iterator = media_manager.search_album(db_Album.album_id)
        photo_seq = 1

        db_Album.change_status = None
        session.add(db_Album)

        for photo in photo_iterator:
            album_id = db_Album.id
            # check if foto is already existing
            foto_find_stmt = select(db_Photos).where(db_Photos.album_id == album_id).where(db_Photos.media_id == photo['id'])
            if not session.execute(foto_find_stmt).first():

                media_type = photo.get('mediaMetadata').get('photo')

                camera = None
                if media_type:
                    camera = media_type.get('cameraModel')

                db_photo = db_Photos(
                    album_id=db_Album.id,
                    media_id=photo['id'],
                    filename=photo['filename'],
                    mime_type=photo['mimeType'],
                    camera=camera,
                    photo_seq=photo_seq,
                    updated_at=datetime.now(),
                    pp_upload_status='U',
                    created=datetime.strptime(photo['mediaMetadata']['creationTime'], "%Y-%m-%dT%H:%M:%SZ"))

                backup_source, filepath = photo_find_path(db_Album.title, db_photo.filename, db_photo.created, picasa_pics)
                if backup_source=='Google':
                    db_photo.google_api_status='U'

                db_photo.backup_source = backup_source
                db_photo.filepath = filepath
                str_action='NEW'
            else:
                db_photo = session.execute(foto_find_stmt).first()[0]
                db_photo.photo_seq = photo_seq

                backup_source, filepath = photo_find_path(db_Album.title, db_photo.filename, db_photo.created, picasa_pics)

                if backup_source != db_photo.backup_source or filepath != db_photo.filepath:
                    db_photo.updated_at = datetime.now()
                    db_photo.backup_source = backup_source
                    db_photo.pp_upload_status='U'

                    # Filepath comes from existing files or will be determined later via Google api call
                    if db_photo.filepath is None and backup_source == 'Google':
                        db_photo.google_api_status = 'U'
                    else:
                        db_photo.filepath = filepath

                str_action='OLD'

            print(str_action+" "+ (db_photo.backup_source or  "No Source") + "\t API: "+(db_photo.google_api_status or "N") +
                  " PP: "+(db_photo.pp_upload_status or "N")+ "\t" + db_photo.filename)

            session.add(db_photo)
            photo_seq = photo_seq + 1

    session.execute(update(db_JobControl).where(db_JobControl.step == STR_REFRESH_PICS_META_FROM_GOOGLE).values(last_run_at=datetime.now()))
    session.commit()
    session.close()



def photo_find_path(db_album_title, photo_filename, photo_created, picasa_pics):
    # Takeout
    search_dir = os.path.join(TAKEOUT_PATH, db_album_title.strip())
    search_file_path = os.path.join(search_dir, photo_filename)
    backup_source = 'Google'
    filepath = None
    rework_flag = ''

    # Search for files that have been manually adjusted, in german 'bearbeitet'

    rework_search_file_path = os.path.join(search_dir, pathlib.Path(photo_filename).stem + GOOGLE_TAKEOUT_REWORK_TEXT + '.jpg')

    takeout_rework_files = glob.glob(rework_search_file_path)
    if len(takeout_rework_files) == 1:
        filepath = takeout_rework_files[0]
        backup_source = 'Takeout'
        rework_flag = 'Rework'
    elif os.path.exists(search_file_path):
        filepath = search_file_path
        backup_source = 'Takeout'

    else:
        # S10 Backup
        search_file_path = os.path.join(S10_BACKUP_PATH, photo_filename)
        if os.path.exists(search_file_path):
            filepath = search_file_path
            backup_source = 'S10'
        else:
            # Picasa Backup
            session = Session(local_engine)
            picasa_stmt = select(db_PicasaFolder).where(db_PicasaFolder.file_name == photo_filename)
            for picasa in session.scalars(picasa_stmt):

                ti_m = os.path.getmtime(picasa.file_path)
                pic_file_created = datetime.fromtimestamp(ti_m)

                if pic_file_created.year != photo_created.year or pic_file_created.month != photo_created.month:
                    print("   Date does not match")
                else:
                    filepath = picasa.file_path
                    backup_source = 'Picasa'

            session.close()


#    print("   " + photo_filename + "\t" + (str_backup_source or "None")+ "\t " + rework_flag)
    return backup_source, filepath
