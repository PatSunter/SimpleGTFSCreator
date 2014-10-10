#!/usr/bin/env python2

import os
from optparse import OptionParser
import osgeo.ogr
from osgeo import ogr
import sys

import route_segs

def process_all_routes_from_segments(segments_shp_fname, output_fname):
    if not os.path.exists(segments_shp_fname):
        print "Error, route segments shape file given, %s , doesn't exist." \
            % segments_shp_fname
        sys.exit(1) 
    shapefile = osgeo.ogr.Open(segments_shp_fname)
    if shapefile is None:
        print "Error, route segments shape file given, %s , failed to open." \
            % (input_segments_fname)
        sys.exit(1) 

    segs_lyr = shapefile.GetLayer(0)
    all_segs_by_route = route_segs.get_routes_and_segments(segs_lyr)
    print "(A total of %d routes.)" % len(all_segs_by_route)
    rnames_sorted = route_segs.get_route_names_sorted(all_segs_by_route.keys())
    route_segs_ordered, route_dirs = route_segs.order_all_route_segments(
        all_segs_by_route, rnames_sorted)
    route_segs.write_route_defs(output_fname, rnames_sorted, route_dirs,
        route_segs_ordered)

    shapefile.Destroy()
    return

if __name__ == "__main__":    
    parser = OptionParser()
    parser.add_option('--input_shp', dest='input_shp',
        help='Shape file containing bus segments, which list routes in each'\
            ' segment.')
    parser.add_option('--output_csv', dest='output_csv',
        help='Output file name you want to store CSV of route segments in'\
            ' (suggest should end in .csv)')
    parser.set_defaults(output_csv='route_defs.csv')        
    (options, args) = parser.parse_args()

    if options.input_shp is None:
        parser.print_help()
        parser.error("No input shape file path containing route infos given.")

    process_all_routes_from_segments(options.input_shp, options.output_csv)
