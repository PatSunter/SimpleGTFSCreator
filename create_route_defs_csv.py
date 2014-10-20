#!/usr/bin/env python2

import os
from optparse import OptionParser
import sys
import operator

import osgeo.ogr
from osgeo import ogr

import route_segs
import topology_shapefile_data_model as tp_model
import mode_timetable_info as m_t_info

def process_all_routes_from_segments(segments_shp_fname, output_fname,
        mode_config):
    if not os.path.exists(segments_shp_fname):
        print "Error, route segments shape file given, %s , doesn't exist." \
            % segments_shp_fname
        sys.exit(1) 
    segs_shp_file = osgeo.ogr.Open(segments_shp_fname)
    if segs_shp_file is None:
        print "Error, route segments shape file given, %s , failed to open." \
            % (input_segments_fname)
        sys.exit(1) 

    segs_lyr = segs_shp_file.GetLayer(0)
    all_segs_by_route = route_segs.get_routes_and_segments(segs_lyr)
    segs_shp_file.Destroy()
    print "(Read from segs file a total of %d routes.)" \
        % len(all_segs_by_route)

    r_ids_ordered = sorted(all_segs_by_route.keys())
    route_segs_ordered = route_segs.order_all_route_segments(
        all_segs_by_route, r_ids_ordered)
    route_dirs = route_segs.create_basic_route_dir_names(
        route_segs_ordered, mode_config)
    route_defs = route_segs.create_route_defs_list_from_route_segs(
        route_segs_ordered, route_dirs, mode_config, r_ids_ordered)
    route_segs.write_route_defs(output_fname, route_defs)
    return

if __name__ == "__main__":    
    allowedServs = ', '.join(sorted(["'%s'" % key for key in \
        m_t_info.settings.keys()]))
    parser = OptionParser()
    parser.add_option('--segments', dest='segments',
        help='Shape file containing network segments, which list routes in '
            'each segment.')
    parser.add_option('--output_csv', dest='output_csv',
        help='Output file name you want to store CSV of route segments in'\
            ' (suggest should end in .csv)')
    parser.add_option('--service', dest='service',
        help="Should be one of %s" % allowedServs)
    parser.set_defaults(output_csv='route_defs.csv')        
    (options, args) = parser.parse_args()

    if options.segments is None:
        parser.print_help()
        parser.error("No input shape file path containing route segs given.")
    if options.service is None:
        parser.print_help()
        parser.error("No service option requested. Should be one of %s" \
            % (allowedServs))
    if options.service not in m_t_info.settings:
        parser.print_help()
        parser.error("Service option requested '%s' not in allowed set, of %s" \
            % (options.service, allowedServs))

    mode_config = m_t_info.settings[options.service]

    process_all_routes_from_segments(options.segments, options.output_csv,
        mode_config)
