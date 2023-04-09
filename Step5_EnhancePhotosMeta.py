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
import array as arr

from config import db_PhotoArchive,db_Albums,db_Photos,db_JobControl, local_engine,picasa_pics
from config import CLIENT_SECRET_FILE,TAKEOUT_PATH,S10_BACKUP_PATH,PICASA_BACKUP_PATH,GOOGLE_DOWNLOAD_RESULTS_PATH,COPY_TARGET_FOLDER_PATH
from config import GOOGLE_TAKEOUT_REWORK_TEXT
from config import STR_REFRESH_PICS_META_FROM_GOOGLE,STR_REFRESH_PHOTOS_FILE_PATH,STR_COPY_TO_TARGET_FOLDERS,STR_PHOTO_PRISM_CREATE_ALBUM
from config import Archive
import googlemaps
from private_constants import MAPS_API_KEY
import json

def enhance_photo_meta():
    gmaps = googlemaps.Client(key=MAPS_API_KEY)

    print("\n\n** Enhance Photos **")
    session = Session(local_engine)

    for db_album in session.scalars(select(db_Albums)):

        print("Title: " + db_album.title)
        if db_album.title.startswith('Dies und Das - 2023'):
            address = None
            for db_photo in session.scalars(select(db_Photos).where(db_Photos.album_id==db_album.id).where(db_Photos.photo_status!='D')):

                # Geolocation
                if db_photo.photo_lat is not None:
                    reverse_geocode_result = gmaps.reverse_geocode(
                        (db_photo.photo_lat, db_photo.photo_lng)
                    )
                    result_type_list = ["airport", "lodging","point_of_interest","park","establishment","natural_feature", "premise" , "administrative_area_level_3",
                                   "administrative_area_level_4"]


                    b_break=False
#                    print("--------------------------------")
                    for result_type in result_type_list:
#                        print("ResultType: "+result_type)
                        for adr_component in reverse_geocode_result:
                            types=adr_component['types']
 #                           print("    "+str(types))
                            if result_type in types:
                                address=str((adr_component['formatted_address']))
                                b_break=True
                                break
                        if b_break:break

                    if address:
                        str_result="\t"+db_photo.filename+"\t\t\t"+address
                        db_photo.location=address
                        session.add(db_photo)
                    else:
                        str_result="\t"+db_photo.filename + "\t\t\t>>>> No GeoCode Result"
                else:
                    str_result="\t"+db_photo.filename + "\t\t\t>>>>No GeoCode"

                # Timezone ------------------------------------------------------------------------------------
                location = str(db_photo.photo_lat)+","+str(db_photo.photo_lng)
                timestamp = db_photo.taken_at.timestamp()

                params = {
                    'location': location,
                    'timestamp': timestamp,
                    'key': MAPS_API_KEY
                }

                url='https://maps.googleapis.com/maps/api/timezone/json'
                response = requests.get(url, params=params)
                timezone_data = json.loads(response.text)

                if timezone_data['status'] == 'OK':
                    full_delta=timezone_data['dstOffset']+timezone_data['rawOffset']
                    db_photo.created_local_time=datetime.fromtimestamp(db_photo.created_at.timestamp()+full_delta)
                    str_result = str_result + "\t\t" + str(full_delta)
                else:
                    str_result = str_result + "\t\tERROR Time Conversion"

                print(str_result)

    session.commit()
    session.close()
