import hashlib
import os

from dateutil.tz import tzlocal
from dotenv import load_dotenv

from gphotospy.album import *
from gphotospy.media import Media, MediaItem
from sqlalchemy import create_engine, select, update, func
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.inspection import inspect
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.ext.automap import automap_base
import sqlalchemy as sa
from datetime import datetime,  timedelta
import logging
import time
from pathvalidate import sanitize_filename
from shutil import copyfile
import pathlib
from pathlib import Path
from os.path import exists
import requests
import command
import glob
import json
from dateutil import parser
import exifread
import configparser
import mimetypes

from exif_gps import get_exif_location
from PIL import Image

from config import db_PhotoArchive,db_Albums,db_Photos,db_JobControl, local_engine,TAKEOUT_IGNORE
from config import GOOGLE_TAKEOUT_REWORK_TEXT
from config import  album_manager, media_manager
from config import get_archive_by_source, Archive

from Step3_MatchPhotos import copy_archive_to_photos

def refresh_photo_archive_for_source(id):
    archive=get_archive_by_source(id)
    if archive.source_format=='SOURCE_PHONE':
        refresh_from_phone(archive)
    elif archive.source_format=='SOURCE_TAKEOUT':
        refresh_from_takeout(archive)
    elif archive.source_format=='SOURCE_PICASA':
        refresh_from_picasa(archive)
    else: raise ValueError(f"No source found with ID '{id}'")

########################################################################################
# Read from Google-Takeout ------------------------------------------
# - files have exif-information,
# - read created date from json,
# - prefer "reworked files"
# - get image dimensions from file
# - check for duplicated files - need to be careful here

def refresh_from_takeout(archive:Archive):
    print("\n***** Refresh Takeout for source: "+archive.source_name + " path: " + archive.path)
    session = Session(local_engine)

    for path, subdirs, files in os.walk(archive.path):

        print("\n"+os.path.basename(path))
        if os.path.basename(path).startswith(TAKEOUT_IGNORE):
            print("\t !!! IGNORED as in Takeout Ignore")
            continue

        for name in files:

            if (pathlib.Path(name).suffix != '.json') and (GOOGLE_TAKEOUT_REWORK_TEXT not in name):

                # If we find "rework files - take those - not that json part is not from reworked files
                filepath = os.path.join(path, name)

                my_rework_file = pathlib.Path(name).stem + GOOGLE_TAKEOUT_REWORK_TEXT
                my_rework_path = os.path.join(path,my_rework_file)
                json_file_path = filepath

                if os.path.isfile(my_rework_path+'.JPG') :
                    filepath=os.path.join(path,my_rework_file+'.JPG')

                if os.path.isfile(my_rework_path+'.jpg') :
                    filepath=os.path.join(path,my_rework_file+'.jpg')

                album_name = os.path.basename(os.path.normpath(path))
                db_check_photo = \
                    session.execute(
                        select(db_PhotoArchive).where(db_PhotoArchive.filename == name).where(db_PhotoArchive.album_name == album_name).where(db_PhotoArchive.source == archive.source_name)).first()


                if db_check_photo is None:
                    taken_at=None
                    b_taken_at_local_time=None

                    try:
                        orientation=None

                        # Try to get exif, when available
                        try:
                            tags = exifread.process_file(open(filepath, 'rb'))
                            if tags:
                                orientation = tags.get('Image Orientation', None)
                                if orientation:
                                    orientation = orientation.values[0]

                                if 'EXIF DateTimeOriginal' in tags:
                                    taken_at = datetime.strptime(str((tags['EXIF DateTimeOriginal'])), '%Y:%m:%d %H:%M:%S')
                                    b_taken_at_local_time = True

                        except Exception as e:
                            print("\nExif-Exception:" + str(e) + "\t" + filepath)

                        # Read fom Takeout- Config Json
                        f = open(json_file_path + '.json')
                        data = json.load(f)
                        #  taken_at = parser.parse(data['photoTakenTime']['formatted']).astimezone(tzlocal())
                        if not taken_at:
                            taken_at= parser.parse(data['photoTakenTime']['formatted'],dayfirst=True).astimezone(tzlocal())
                            b_taken_at_local_time = False

                        im = Image.open(filepath)
                        width, height = im.size

                        lat=float(data['geoDataExif']['latitude'])
                        lng=float(data['geoDataExif']['longitude'])
                        if (lat==0.0) and (lng==0.0):
                            lat = float(data['geoData']['latitude'])
                            lng = float(data['geoData']['longitude'])

                        new_entry = db_PhotoArchive(filename=name,
                                                    filepath=os.path.relpath(filepath, archive.path),
                                                    source=archive.source_name,
                                                    taken_at=taken_at,
                                                    taken_at_local_time=b_taken_at_local_time,
                                                    created_at=datetime.now(),
                                                    album_name=album_name,
                                                    photo_lat=lat,
                                                    photo_lng=lng,
                                                    photo_width=width,
                                                    photo_height=height,
                                                    photo_orientation=orientation,
                                                    media_type= mimetypes.guess_type(filepath)[0])
                        session.add(new_entry)

                    except (OSError, IOError) as e:
                        print("\tWarning - json not found: " + filepath)

                else:
                    print("\tDuplicate: "+ filepath)

        session.commit()

    print("DONE")

# Refresh from Phone Folders ------------------------------------------
# - check for exif, if not take file time stamp
# - check for duplicates

def refresh_from_phone(archive:Archive):
    print("\n***** Refresh Phone - Source: "+archive.source_name + " path: " + archive.path)
    session = Session(local_engine)

    for path, subdirs, files in os.walk(archive.path):

        print("\nFolder:"+os.path.basename(path))
        for name in files:
            create_archive_entry_from_file(session, archive.source_name, name, path, None, archive.path)

# Refresh from Phone Folders ------------------------------------------
# - run full dirs, last folder is album
# - read picasa.ini to flag "starred" photos

def refresh_from_picasa(archive):
    print("***** Refresh Picasa: " + archive.path)
    session = Session(local_engine)
    config = configparser.ConfigParser()

    for path, subdirs, files in os.walk(archive.path):
        print("\n"+os.path.basename(path))

        ini_path = os.path.join(path, ".picasa.ini")
        config.read(ini_path)

        for name in files:
            create_archive_entry_from_file(session, archive.source_name, name, path, config.has_option(name, 'star'), archive.path)

# all photos that could not be matched, need to be downloaded from Google
# this routine runs after matching!
# 1) check for google_api_status == 'U'
# 2) download from Google
# 3) extract exif information
# 4) create new entry in photo_archive
# 5) Copy archive to photos (not so nice, but efficient)


def refresh_from_google(archive:Archive):
    print("\n\n**** Refresh - Pull missing photos from Google into: " + archive.path)
    session = Session(local_engine)
    photo_no_backup_source_stmt = select(db_Photos).where(db_Photos.photo_status == 'U')
    for db_photo in session.scalars(photo_no_backup_source_stmt):

        ## Full path in archive based on Google  media-id
        file_name=db_photo.google_id+os.path.splitext(db_photo.filename)[1]
        full_path_filename = os.path.join(archive.path, file_name)

        if not os.path.isfile(full_path_filename):
            print("\tNotFound: "+full_path_filename)
            g_photo = media_manager.get(db_photo.google_id)
            g_media = MediaItem(g_photo)

#            download_path = os.path.join(archive.path, "IDG_" + str(db_photo.id) + "_" + sanitize_filename(db_photo.filename).replace(" ", "_"))
            with open(full_path_filename, 'wb') as output:
                output.write(g_media.raw_download())
        else:
            print("\tFound: "+full_path_filename)

        db_photo_archive=create_archive_entry_from_file(session, archive.source_name, file_name, archive.path, None, archive.path)

        ## Create automatically the photo entry
        if db_photo_archive:
            copy_archive_to_photos(db_photo, db_photo_archive)
            db_photo.taken_at=db_photo_archive.taken_at
            db_photo.taken_at_local_time=False # pictures refreshed from Google have no local time, ignore any timestamp
            db_photo.photo_status = 'M'
        else:
            print("Error: Google Photo not downloaded or matched: "+db_photo.filename)

        session.add(db_photo)
        session.commit()

    session.close()


def create_archive_entry_from_file(session, source, my_file_name, path, b_picasa_star, root_path):

    my_file_path = os.path.join(path, my_file_name)
    mt = mimetypes.guess_type(my_file_path)[0]
    new_entry = None

    if mt is not None:
        mimes = mimetypes.guess_type(my_file_path)[0].split('/')[0]

        if mimes in ['audio', 'video', 'image']:

            # Extract exif data or from file date

            taken_at=None
            b_taken_at_local_time=False
            width=None
            height=None
            lat=0
            lng=0
            orientation=None
            camera=None

            try:
                tags = exifread.process_file(open(my_file_path, 'rb'))
                if tags:
                    if 'EXIF DateTimeOriginal' in tags:
                        taken_at = datetime.strptime(str((tags['EXIF DateTimeOriginal'])), '%Y:%m:%d %H:%M:%S')
                        b_taken_at_local_time=True

                    width_tag = tags.get('Image ImageWidth')
                    height_tag = tags.get('Image ImageLength')
                    if width_tag and height_tag:
                        # Print the image dimensions
                        width = int(width_tag.values[0])
                        height = int(height_tag.values[0])
                    else:
                        width_tag = tags.get('EXIF ExifImageWidth')
                        height_tag = tags.get('EXIF ExifImageLength')
                        if width_tag and height_tag:
                            # Print the image dimensions
                            width = int(width_tag.values[0])
                            height = int(height_tag.values[0])

                    model_tag=tags.get('Image Model')
                    if model_tag:
                        camera=str(model_tag)

                    orientation = tags.get('Image Orientation', None)
                    if orientation:
                        orientation = orientation.values[0]

                    lat,lng=get_exif_location(tags)
            except Exception as e:
                print("\nExif-Exception:"+ str(e) +"\t"+ my_file_path)
            finally:
                if taken_at is None:
                    ti_m = os.path.getmtime(my_file_path)
                    taken_at = datetime.fromtimestamp(ti_m)  # takes time to write the file
                    b_taken_at_local_time=True

                if width is None or height is None:
                    print('#', end='')
                    try:
                        im = Image.open(my_file_path)
                        width, height = im.size
                    except Exception as e:
                        print("\nPil-Exception:" + str(e) + "\t" + my_file_path)

            ##                      print("   File: "+str(date_created)+"\t date_created \t"+my_file_path)

            # create entry in table photo_archive

            album_name = os.path.basename(os.path.normpath(path))
            db_check_photo = \
            session.execute(select(db_PhotoArchive).where(db_PhotoArchive.filename == my_file_name).where(db_PhotoArchive.album_name == album_name).where(db_PhotoArchive.source == source)).first()

            if db_check_photo is not None:
#                print("\tDuplicate:\t " + my_file_path)
                print('d', end='')
            else:
                new_entry = db_PhotoArchive(filename=my_file_name,
                                            filepath=os.path.relpath(my_file_path, root_path),
                                            source=source,
                                            album_name=album_name,
                                            b_picasa_star=b_picasa_star,
                                            created_at=datetime.now(),
                                            taken_at=taken_at,
                                            taken_at_local_time=b_taken_at_local_time,
                                            photo_lat=lat,
                                            photo_lng=lng,
                                            photo_width=width,
                                            photo_height=height,
                                            photo_orientation=orientation,
                                            camera=camera,
                                            media_type=mt)
                session.add(new_entry)
#                print("\tAdd:\t " + my_file_path)
                print('.', end='')
                session.commit()
    return new_entry