from dotenv import load_dotenv

import logging

from config import get_archives_by_source_format, get_archive_by_source

from Step1_RefreshPhotoArchive import refresh_photo_archive_for_source, refresh_from_google
from Step2_RefreshAlbums import refresh_albums_from_google,refresh_albums_from_folders
from Step3_MatchPhotos import match_google_photos
from Step5_EnhancePhotosMeta import enhance_photo_meta
import json



load_dotenv()
logging.basicConfig()
logging.getLogger("sqlalchemy.engine").setLevel(logging.ERROR)


# ***********************************************************
# Logic:
# 1) All photos taken with camera are stored in photo_archive
#    photo_archive can be populated from several sources: takeout, picasa, phone
# 2) Metadata for all Albums and Photos is downloaded in google_album and google_photo
# 3) Matching - for each photo in google_photos search in the photo archive for a matching photo
#    google_photo is updated with the matching file_path as copy from photo_archive
# 4) All photos that could not be matched are downloaded from Google photos (worst case)
#
# Result each photo in google_photos has a file-path pointing to the picture with most metadata information

# ****************   Steps ***********************************

# Populate Photo Archive
STEP1_REFRESH_ARCHIVE_TAKEOUT= False
STEP1_REFRESH_ARCHIVE_PICASA = False
STEP1_REFRESH_ARCHIVE_PHONES= False
STEP1_REFRESH_ARCHIVE_CUSTOM = False #Phone

STEP2a_REFRESH_ALBUMS_FROM_GOOGLE = False  # Loop over all albums from Google and update metadata in local DB
STEP2b_REFRESH_ALBUMS_FROM_FOLDERS = False # Loop over all Folders and build albums

STEP3_MATCH_PHOTOS = True

STEP4_REFRESH_MISSING_GOOGLE=False # photos not matched will be refreshed from Google
STEP5_ENHANCE_PHOTOS_META=False

STEP_PP_94_UPLOAD_PHOTOS = False
STEP_PP_95_UPDATE_ALBUM_INFO = False


def main():


### Refresh the Photo-Archive

    if STEP1_REFRESH_ARCHIVE_TAKEOUT:
        refresh_photo_archive_for_source('Takeout')

    if STEP1_REFRESH_ARCHIVE_PICASA:
        refresh_photo_archive_for_source('Picasa')

    if STEP1_REFRESH_ARCHIVE_PHONES:
        refresh_photo_archive_for_source('S10')
        refresh_photo_archive_for_source('S7')
        refresh_photo_archive_for_source('Sony')
        refresh_photo_archive_for_source('Asus')
#        refresh_photo_archive('ID-Pixel7')

#### Refresh the Albums and Photos

    if STEP2a_REFRESH_ALBUMS_FROM_GOOGLE:
        refresh_albums_from_google()

    if STEP2b_REFRESH_ALBUMS_FROM_FOLDERS:
         refresh_albums_from_folders('Picasa')  # uses photo_archive from picasa

    if STEP3_MATCH_PHOTOS:
        match_google_photos()

    if STEP4_REFRESH_MISSING_GOOGLE:
        for archive in get_archives_by_source_format('Google'):
           refresh_from_google(archive)

    if STEP5_ENHANCE_PHOTOS_META:
        enhance_photo_meta()

    ################# Sourcecode for PhotoPrism


    # Step-2: Download missing files from Google and prepare files to PhotoPrism import (copy to import folder)
    if STEP_PP_94_UPLOAD_PHOTOS:
        upload_photos_to_pp()

    # Step-3: Loads all files in a folder and stores filename and path in tmp table (only when new folder structure)




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
    if STEP_PP_95_UPDATE_ALBUM_INFO:
        update_photo_prism_album()



# ---------------------- Support functions



# Press the green button in the gutter to run the script.
if __name__ == '__main__':
    main()

# See PyCharm help at https://www.jetbrains.com/help/pycharm/
