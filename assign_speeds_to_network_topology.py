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

def constant_speed_max(route_segment, mode_config):    
    """Just return constant average speed defined for this mode."""
    return mode_config['avespeed']

def constant_speed_max_peak(route_segment, mode_config):
    """Just return constant average speed defined for this mode, peak hours"""
    return mode_config['avespeed-peak']

PEAK_RATIO = 0.5
def ratio_max_speed(route_segment, mode_config):    
    return mode_config['avespeed'] * PEAK_RATIO

def check_mways_status_exists(route_segments_lyr, mode_config):
    motorway_calcs.ensure_motorway_field_exists(route_segments_lyr)
    return

def constant_speed_offpeak_mway_check(route_segment, mode_config):    
    """First check if segment is on a motorway. Then assign relevant speed."""
    if 'on_motorway' in mode_config:
        mode_config_bus = mode_config
        mode_config_bus_mway = mode_config['on_motorway']
    else:
        mode_config_bus_mway = mode_config
        mode_config_bus = mode_config['on_street']

    if motorway_calcs.is_on_motorway(route_segment):
        speed = constant_speed_max(route_segment, mode_config_bus_mway)
    else:
        speed = constant_speed_max(route_segment, mode_config_bus)
    return speed    

def buses_peak_with_mway_check(route_segment, mode_config):
    """First check if segment is on a motorway. Then assign relevant speed."""
    if 'on_motorway' in mode_config:
        mode_config_bus = mode_config
        mode_config_bus_mway = mode_config['on_motorway']
    else:
        mode_config_bus_mway = mode_config
        mode_config_bus = mode_config['on_street']

    if motorway_calcs.is_on_motorway(route_segment):
        speed = constant_speed_max_peak(route_segment, mode_config_bus_mway)
    else:
        # Apply congestion if on street network
        speed = calc_peak_speed_melb_bus(route_segment, mode_config_bus)
    return speed

def calc_peak_speed_melb_bus(route_segment, mode_config):
    assert mode_config['system'] == 'Bus'

    target_srs = osr.SpatialReference()
    target_srs.ImportFromEPSG(route_geom_ops.COMPARISON_EPSG)

    seg_geom = route_segment.GetGeometryRef()
    segment_srs = seg_geom.GetSpatialReference()
    # Get the midpoint, as we'll consider this the point to use as 'distance'
    # from CBD
    if seg_geom.GetPoint(0) == seg_geom.GetPoint(1):
        # A special case for segments of zero length. Shouldn't really exist,
        # but have been produced in some cases.
        seg_midpoint = ogr.Geometry(ogr.wkbPoint)
        seg_midpoint.AddPoint(*seg_geom.GetPoint(0))
    else:
        seg_midpoint = seg_geom.Centroid()
    transform_seg = osr.CoordinateTransformation(segment_srs, target_srs)
    seg_midpoint.Transform(transform_seg)

    origin = ogr.Geometry(ogr.wkbPoint)
    origin_coords = speed_funcs_location_based.MELB_ORIGIN_LAT_LON
    origin.AddPoint(origin_coords[1], origin_coords[0]) # Func takes lon,lat
    origin_srs = osr.SpatialReference()
    origin_srs.ImportFromEPSG(4326)
    transform_origin = osr.CoordinateTransformation(origin_srs, target_srs)
    origin.Transform(transform_origin)
    
    Z = origin.Distance(seg_midpoint)
    Z_km = Z / 1000.0
    V = speed_funcs_location_based.peak_speed_func(Z_km)
    return V

SPEED_FUNC_SETS_REGISTER = {
    "constant_peak_offpeak": (None, constant_speed_max, \
        constant_speed_max_peak),
    "peak_speed_dist_based": (None, constant_speed_max, \
        calc_peak_speed_melb_bus), 
    "peak_speed_dist_based_mways_check": (check_mways_status_exists, 
        constant_speed_offpeak_mway_check,
        buses_peak_with_mway_check),
    }

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
            or options.speed_funcs not in SPEED_FUNC_SETS_REGISTER.keys():
        parser.print_help()
        parser.error("No speed_funcs option requested or bad option given. "
            "Allowed choice of speed_funcs is %s" \
            % (sorted(SPEED_FUNC_SETS_REGISTER.keys())))
        
    mode_config = m_t_info.settings[options.service]
    check_func, offpeak_func, peak_func = \
        SPEED_FUNC_SETS_REGISTER[options.speed_funcs]

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
