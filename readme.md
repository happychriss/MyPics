
# MyPics: Google Photos Export to PhotoPrism
#### Transfer Your Google Photo Albums to PhotoPrism with MyPics: A Tool that preserves Metadata and Album Structure

## What am I doing?

I've written a set of Python scripts that will automatically replicate your Google Photo albums into PhotoPrism, ensuring that all location information and album information (order, cover) is retained.
This can run on a small Linux server and automatically synchronize your Google albums into PhotoPrism albums.

### What is PhotoPrism?
PhotoPrism® is an AI-Powered Photos App for the Decentralized Web.It makes use of the latest technologies to tag and find pictures automatically without getting in your way. You can run it at home, on a private server, or in the cloud. 
(https://photoprism.app/)

## Why did I do it?

I created this tool because I have a love/hate relationship with Google Photos. 

**I love** its organization and sharing capabilities, b

**I hate**  the restrictions enforced by Google that come with exporting full sets of information and regaining ownership:

* Google Takeout export is a nightmare (only all albums - hug file) and does only include albums that are not shared
* Google Photo API does remove all location information
* Google Photo API does only export the orginal photos, anything that has been adjusted with Google Photo Editor can not be exported

## How did I to it?

I wanted to make sure I get all Metadata and Album information from Google, to reproduce the Album in PhotoPrism as much as possible by using multiple photo sources:

* Google Takeout (location information, reworked items, album information)
* Photos copied from Mobile Phone (with location information, but no album, no rework)
* Picasa Pictures (location information, no album information)

A Python script reads album and photo information from Google Photos, stores it in a local database,
finds the data source with the most metadata for each photo,
and copies the photos to the PhotoPrism import folder in the correct order and with aligned names and dates.

In a 2nd step it creates the albums in PhotoPrism based on metadata including the correct order of the photos on the album and keeping the cover photos.

## Status
MyPics is a work in progress, but it may save you time and hassle of manually transferring your Google Photo albums to PhotoPrism.

(text finetuned with friendly help of ChatGPT)