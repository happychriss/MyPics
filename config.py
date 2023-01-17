from sqlalchemy import create_engine, select, update
from sqlalchemy.ext.automap import automap_base
import logging
import os
from dotenv import load_dotenv

GOOGLE_TAKEOUT_REWORK_TEXT = '*bearbeitet*'

CLIENT_SECRET_FILE = "gphoto_ouath.json"
TAKEOUT_PATH = "/media/development/DATEN/BACKUP/google_takeout_12_2022/"
S10_BACKUP_PATH = "/media/development/DATEN/BACKUP/photos_s10_backup/Camera"
PICASA_BACKUP_PATH = "/media/development/DATEN/DATA/MyPics"
GOOGLE_DOWNLOAD_RESULTS_PATH = "/media/development/DATEN/BACKUP/google_photo_api_download"

#user development and new group photoprism created, developmen and cneuhaus are part of this group, group has write access to that folder
#sudo mount -t cifs -o credentials=~/.smbcredentials,uid=1001,gid=1001 //zo/photoprism_import //home/development/PhotoPrism_Import_Donald
COPY_TARGET_FOLDER_PATH ='//home/development/PhotoPrism_Import_Donald'
#old path on SSD:  '/media/development/SSD_EXTERNAL_500/PhotoPrism'


load_dotenv()

local_engine = create_engine('postgresql://'+os.getenv("MY_PICS_DB_USER")+":"+os.getenv("MY_PICS_DB_PWD")+'@localhost:5432/MyPics', echo=False, future=True)
pp_engine = create_engine('mariadb+mariadbconnector://'+os.getenv("PP_DB_USER")+":"+os.getenv("PP_DB_PWD")+'@zo:3306/photoprism')
Base_Local = automap_base(bind=local_engine)
Base_PP = automap_base(bind=pp_engine)
Base_Local.prepare(autoload_with=local_engine)
Base_PP.prepare(autoload_with=pp_engine)

## Local Database
db_PicasaFolder = Base_Local.classes.tmp_picasa_folders
db_Albums = Base_Local.classes.google_albums
db_Photos = Base_Local.classes.google_photos
db_JobControl = Base_Local.classes.google_job_control

## Photoprism Database
pp_Photos = Base_PP.classes.photos
pp_Albums = Base_PP.classes.albums
picasa_pics = {}

STR_REFRESH_PICS_META_FROM_GOOGLE = 'REFRESH_PHOTO_META_FROM_GOOGLE'
STR_REFRESH_PHOTOS_FILE_PATH = 'REFRESH_PHOTOS_FILE_PATH'
STR_COPY_TO_TARGET_FOLDERS='COPY_TO_TARGET_FOLDERS'
STR_PHOTO_PRISM_CREATE_ALBUM='PHOTO_PRISM_CREATE_ALBUM'
