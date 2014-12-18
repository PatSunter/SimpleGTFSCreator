#!/usr/bin/env python2

import os
import os.path
import re
import sys
import inspect
from optparse import OptionParser

import osgeo.ogr
from osgeo import ogr, osr

import mode_timetable_info as m_t_info
import motorway_calcs
import route_geom_ops
import seg_speed_models
import speed_funcs_location_based

if __name__ == "__main__":
    parser = OptionParser()
    parser.add_option('--segments', dest='inputsegments', help="Shapefile of "\
        "line segments.")
    parser.add_option('--service', dest='service', help="Should be 'train', "\
        "'tram' or 'bus'.")
    parser.add_option('--speed_funcs', dest='speed_funcs', help="Name in "\
        "register of speed functions to use.")
    (options, args) = parser.parse_args()

    if options.inputsegments is None:
        parser.print_help()
        parser.error("No segments shapefile path given.")
    if options.service is None:
        parser.print_help()
        parser.error("No service option requested. Should be one of %s" \
            % (m_t_info.settings.keys()))
    if options.service not in m_t_info.settings:
        parser.print_help()
        parser.error("Service option requested '%s' not in allowed set, of %s" \
            % (options.service, m_t_info.settings.keys()))
    if options.speed_funcs is None \
            or options.speed_funcs not in \
                seg_speed_models.SPEED_FUNC_SETS_REGISTER.keys():
        parser.print_help()
        parser.error("No speed_funcs option requested or bad option given. "
            "Allowed choice of speed_funcs is %s" \
            % (sorted(seg_speed_models.SPEED_FUNC_SETS_REGISTER.keys())))
        
    mode_config = m_t_info.settings[options.service]
    check_func, offpeak_func, peak_func = \
        seg_speed_models.SPEED_FUNC_SETS_REGISTER[options.speed_funcs]

    # Open in write-able mode, hence the 1 below.
    fname = os.path.expanduser(options.inputsegments)
    route_segments_shp = osgeo.ogr.Open(fname, 1)    
    if route_segments_shp is None:
        print "Error, route segments shape file given, %s , failed to open." \
            % (options.inputsegments)
        sys.exit(1)    
    route_segments_lyr = route_segments_shp.GetLayer(0)

    print "About to assign speeds to segments per functions defined in "\
        "Register under name '%s'" % options.speed_funcs
    speed_model = seg_speed_models.PerSegmentPeakOffPeakSpeedModel()
    speed_model.assign_speeds_to_all_segments(route_segments_lyr, mode_config,
        check_func, offpeak_func, peak_func)

    # Close the shape files - includes making sure it writes
    route_segments_shp.Destroy()
    route_segments_shp = None
