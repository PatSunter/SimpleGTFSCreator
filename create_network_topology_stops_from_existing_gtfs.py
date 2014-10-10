#!/usr/bin/env python2
import os
import os.path
import sys
import inspect
from optparse import OptionParser

import osgeo.ogr
from osgeo import ogr, osr

import transitfeed

import parser_utils
import topology_shapefile_data_model as tp_model

DELETE_EXISTING = True

# GTFS stop coordinates are geographic lat-lons
GTFS_STOPS_EPSG = 4326

def add_all_stops_from_gtfs(input_schedule, stops_lyr, stops_multipoint):
    print "Adding all stops from GTFS file."
    gtfs_srs = osr.SpatialReference()
    gtfs_srs.ImportFromEPSG(GTFS_STOPS_EPSG)

    stop_count = 0
    for row_ii, stop in enumerate(input_schedule.stops.itervalues()):
        stop_pt = ogr.Geometry(ogr.wkbPoint)
        stop_pt.AddPoint(stop.stop_lon, stop.stop_lat)
        stop_id = tp_model.add_stop(stops_lyr, stops_multipoint,
            tp_model.STOP_TYPE_FROM_EXISTING_GTFS, stop_pt, gtfs_srs)
        stop_count += 1    
    print "...done adding the %d stops." % stop_count
    return

def main():
    parser = OptionParser()
    parser.add_option('--input_gtfs', dest='inputgtfs',
        help='GTFS zip file to read from. Should end in .zip')
    parser.add_option('--stops', dest='outputstops',
        help='Shapefile of line stops to create.')
    (options, args) = parser.parse_args()

    if options.inputgtfs is None:
        parser.print_help()
        parser.error("No input GTFS file path given.")
    if options.outputstops is None:
        parser.print_help()
        parser.error("No output stops shapefile path given.")

    gtfs_input_fname = options.inputgtfs

    if not os.path.exists(gtfs_input_fname):
        print "Error:- gtfs input file name given doesn't exist (%s)." \
            % gtfs_input_fname
    # The shape files we're going to create :- don't check
    #  existence, just read names.
    stops_shp_file_name = os.path.expanduser(options.outputstops)

    accumulator = transitfeed.SimpleProblemAccumulator()
    problemReporter = transitfeed.ProblemReporter(accumulator)

    loader = transitfeed.Loader(gtfs_input_fname, problems=problemReporter)
    print "Loading input schedule from file %s ..." % gtfs_input_fname
    input_schedule = loader.Load()
    print "... done."

    stops_shp_file, stops_lyr = tp_model.create_stops_shp_file(
        stops_shp_file_name, delete_existing=DELETE_EXISTING)
    stops_multipoint = ogr.Geometry(ogr.wkbMultiPoint)
    add_all_stops_from_gtfs(input_schedule, stops_lyr, stops_multipoint)

    # Cleanup
    input_schedule = None
    stops_shp_file.Destroy()
    return

if __name__ == "__main__":
    main()
