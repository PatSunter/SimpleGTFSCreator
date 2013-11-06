SimpleGTFSCreator
=================

Python library and scripts to help create a simple GTFS schedule from GIS files and minimal speed &amp; headway information.

At the moment this is a very first version that will only be able to create a
network of constant frequency.

Later on we'd like to add the ability to vary frequency (or possibly capacity)
via route.

Dependent libraries:
--------------------

 * GDAL's OGR :- for working with GIS data files.
 * pyproj :- for calculating distances etc between segments.
