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
    shapefile = osgeo.ogr.Open(segments_shp_fname)
    if shapefile is None:
        print "Error, route segments shape file given, %s , failed to open." \
            % (input_segments_fname)
        sys.exit(1) 

    segs_lyr = shapefile.GetLayer(0)
    all_segs_by_route = route_segs.get_routes_and_segments(segs_lyr)
    print "(A total of %d routes.)" % len(all_segs_by_route)
    r_ids_ordered = sorted(all_segs_by_route.keys())
    route_segs_ordered, route_dirs = route_segs.order_all_route_segments(
        all_segs_by_route, mode_config, r_ids_ordered)

    route_defs = []
    for r_id in r_ids_ordered:
        # Haven't yet implemented ability to create route long names
        r_short_name = tp_model.route_name_from_id(r_id)
        r_long_name = None
        rdef = route_segs.Route_Def(r_id, r_short_name, r_long_name,
            route_dirs[r_id],
            map(operator.attrgetter('seg_id'), route_segs_ordered[r_id]))
        route_defs.append(rdef)
    route_segs.write_route_defs(output_fname, route_defs)
    shapefile.Destroy()
    return

if __name__ == "__main__":    
    allowedServs = ', '.join(sorted(["'%s'" % key for key in \
        m_t_info.settings.keys()]))
    parser = OptionParser()
    parser.add_option('--input_shp', dest='input_shp',
        help='Shape file containing bus segments, which list routes in each'\
            ' segment.')
    parser.add_option('--output_csv', dest='output_csv',
        help='Output file name you want to store CSV of route segments in'\
            ' (suggest should end in .csv)')
    parser.add_option('--service', dest='service',
        help="Should be one of %s" % allowedServs)
    parser.set_defaults(output_csv='route_defs.csv')        
    (options, args) = parser.parse_args()

    if options.input_shp is None:
        parser.print_help()
        parser.error("No input shape file path containing route infos given.")
    if options.service is None:
        parser.print_help()
        parser.error("No service option requested. Should be one of %s" \
            % (allowedServs))
    if options.service not in m_t_info.settings:
        parser.print_help()
        parser.error("Service option requested '%s' not in allowed set, of %s" \
            % (options.service, allowedServs))

    mode_config = m_t_info.settings[options.service]

    process_all_routes_from_segments(options.input_shp, options.output_csv,
        mode_config)
