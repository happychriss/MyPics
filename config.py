from sqlalchemy import create_engine, select, update
from sqlalchemy.ext.automap import automap_base
import logging
import os
from dotenv import load_dotenv
from gphotospy.album import *
from gphotospy.media import Media, MediaItem
from sqlalchemy.orm import relationship
import json
import yaml
from sqlalchemy import Column, Integer, String, ForeignKey, DateTime
from sqlalchemy.orm import relationship
from sqlalchemy.ext.declarative import declarative_base

# Photo Archive can get the date from different source types
SOURCE_FORMAT_TAKEOUT= 'SOURCE_TAKEOUT'
SOURCE_FORMAT_PHONE= 'SOURCE_PHONE' # will scan for new files, based on time-stamp of file
SOURCE_FORMAT_PICASA= 'SOURCE_PICASA' # will search for stars and always scan the full album- scanning twice will double entries
SOURCE_FORMAT_GOOGLE ='SOURCE_GOOGLE' # files not found are downloaded from Google
SOURCE_FORMAT_FOLDER = 'SOURCE_FOLDER' # data is not coming from goolge album, but it moving folders into archive

# Albums can get the information from Google or via a Folder
ALBUM_SOURCE_GOOGLE= 'GOOGLE'
ALBUM_SOURCE_FOLDER= 'FOLDER'

TAKEOUT_MATCH_FORCE=True

YAML_CONFIG_PATH='my_pics_config.yaml'

class Archive:
    def __init__(self, id:str, source_name: str, source_format: str, path: str, prio: int, album_source: str):
        self.id = id
        self.source_name = source_name
        self.source_format = source_format
        self.path = path
        self.prio = prio
        self.album_source= album_source

with open(YAML_CONFIG_PATH, "r") as f:
    yaml_data = yaml.safe_load(f)
json_string = json.dumps(yaml_data)
json_my_pics_config = json.loads(json_string)

#with open(JSON_CONFIG_PATH) as f:
#    json_my_pics_config = json.load(f)

# class Archive:
#     def __init__(self, **kwargs):
#         for key, value in kwargs.items():
#             setattr(self, key, value)

def get_archive_by_source(source_name):

    for archive in json_my_pics_config['archives']:
        if archive['source_name'] == source_name:
            return Archive(**archive)

    raise ValueError(f"No archive found with source_name '{source_name}'")


def get_archives_by_source_format(source_format):

    return filter(lambda x: x['source_format'] == source_format, json_my_pics_config['archives'])

def get_source_format(source_name):
    for archive in json_my_pics_config["archives"]:
        if archive["source_name"] == source_name:
            # Return the corresponding source format if found
            return archive["source_format"]

def get_albums_first_photo(session,my_db_album):
    return session.execute(select(db_Photos).filter(db_Photos.album_id == my_db_album.id).order_by(db_Photos.taken_at)).scalar()


TAKEOUT_IGNORE='xxPhotos from'


### Authentifcation to Google Photo API
CLIENT_SECRET_FILE = "gphoto_ouath.json"
GOOGLE_TAKEOUT_REWORK_TEXT = '-bearbeitet'


TAKEOUT_PATH = "/media/DATEN/BACKUP/google_takeout_12_2022/"
S10_BACKUP_PATH = "/media/DATEN/BACKUP/photos_s10_backup/Camera"
PICASA_BACKUP_PATH = "/media/DATEN/DATA/MyPics"
GOOGLE_DOWNLOAD_RESULTS_PATH = "/media/DATEN/BACKUP/google_photo_api_download"

#user development and new group photoprism created, developmen and cneuhaus are part of this group, group has write access to that folder
#sudo mount -t cifs -o credentials=~/.smbcredentials,uid=1001,gid=1001 //zo/photoprism_import //home/development/PhotoPrism_Import_Donald
COPY_TARGET_FOLDER_PATH ='//home/development/PhotoPrism_Import_Donald'
#COPY_TARGET_FOLDER_PATH ='//home/development/tmp'
#old path on SSD:  '/media/development/SSD_EXTERNAL_500/PhotoPrism'

STR_REFRESH_PICS_META_FROM_GOOGLE = 'REFRESH_PHOTO_META_FROM_GOOGLE'
STR_REFRESH_PHOTOS_FILE_PATH = 'REFRESH_PHOTOS_FILE_PATH'
STR_COPY_TO_TARGET_FOLDERS='COPY_TO_TARGET_FOLDERS'
STR_PHOTO_PRISM_CREATE_ALBUM='PHOTO_PRISM_CREATE_ALBUM'



### Databases #################################################
load_dotenv()

local_engine = create_engine('postgresql://'+os.getenv("MY_PICS_DB_USER")+":"+os.getenv("MY_PICS_DB_PWD")+'@localhost:5432/MyPics', echo=False, future=True)
Base_Local = automap_base(bind=local_engine)

#pp_engine = create_engine('mariadb+mariadbconnector://'+os.getenv("PP_DB_USER")+":"+os.getenv("PP_DB_PWD")+'@zo:3306/photoprism')
#Base_PP = automap_base(bind=pp_engine)
Base_Local.prepare(autoload_with=local_engine)
#Base_PP.prepare(autoload_with=pp_engine)


## Local Database #################################################
db_PhotoArchive = Base_Local.classes.photo_archive
db_Albums = Base_Local.classes.albums
db_Photos = Base_Local.classes.photos
#db_Albums.db_Photos = relationship("photos", back_populates="albums", foreign_keys="photos.album_id")
#db_Photos.db_Album = relationship("albums", back_populates="photos", primaryjoin="albums.id == photos.album_id")
db_JobControl = Base_Local.classes.google_job_control

## Photoprism Database #################################################
#pp_Photos = Base_PP.classes.photos
#pp_Albums = Base_PP.classes.albums
picasa_pics = {}

## Google Photo Api #################################################

from gphotospy import authorize
service = authorize.init(CLIENT_SECRET_FILE)
album_manager = Album(service)
media_manager = Media(service)
