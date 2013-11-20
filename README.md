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

To create a simple GTFS schedule consisting of a single route, with 4 stops:

  ./create_gtfs_from_basicinfo.py --routedefs=sample_input/Craig-routes.csv --segments=sample_input/Craig-Line-Test.shp --stops=sample_input/Craig-stops-clip.shp --service=train --output=output/google_transit.zip 
     
Input files:
------------

Routes CSV file definition
^^^^^^^^^^^^^^^^^^^^^^^^^^

Format for CSV file is:-
 ';' as a delimiter

Sections are:
name - name of the route
dir1 - name of primary direction of route (e.g. 'City')
dir2 - name of secondary direction of route (e.g. 'Craigieburn')
segments - list of segments that make up the route, with , between each,
  e.g. '0,1,2'

