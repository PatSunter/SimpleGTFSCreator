SimpleGTFSCreator
=================

Python library and scripts to help create a simple GTFS schedule from GIS files
and minimal speed and headway information.

Dependent libraries:
--------------------

 * GDAL's OGR :- for working with GIS data files.
 * pyproj :- for calculating distances etc between segments.

Sample usage:
-------------

./create_gtfs_from_basicinfo.py --output=output/google_transit.zip --segments=sample_input/Craig-Line-Test.shp --stops=sample_input/Craig-stops-clip.shp --service=train
 
