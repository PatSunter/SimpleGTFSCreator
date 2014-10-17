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
import topology_shapefile_data_model as tp_model
import motorway_calcs
import route_geom_ops

def ensure_speed_field_exists(route_segments_lyr, speed_field_name):
    tp_model.ensure_field_exists(route_segments_lyr, speed_field_name,
        ogr.OFTReal, 24, 15)

def assign_speed_to_seg(route_segments_lyr, route_segment, speed_field_name, speed):
    route_segment.SetField(speed_field_name, speed)
    # This SetFeature() call is necessary to actually write the change
    # back to the layer itself.
    route_segments_lyr.SetFeature(route_segment)

def assign_speeds(route_segments_shp, mode_config, speed_func, speed_field_name):
    route_segments_lyr = route_segments_shp.GetLayer(0)
    ensure_speed_field_exists(route_segments_lyr, speed_field_name)

    segs_total = route_segments_lyr.GetFeatureCount()
    print "Assigning speed to all %d route segments:" % segs_total
    one_tenth = segs_total / 10.0
    segs_since_print = 0
    for seg_num, route_segment in enumerate(route_segments_lyr):
        if segs_since_print / one_tenth > 1:
            print "...assigning to segment number %d ..." % (seg_num)
            segs_since_print = 0
        else:
            segs_since_print += 1
        speed = speed_func(route_segment, mode_config)
        assign_speed_to_seg(route_segments_lyr, route_segment,
            speed_field_name, speed)
        route_segment.Destroy()    
    print "...finished assigning speeds to segments."    
    route_segments_lyr.ResetReading()
    return

def constant_speed_max(route_segment, mode_config):    
    """Just return constant average speed defined for this mode."""
    return mode_config['avespeed']

def constant_speed_max_peak(route_segment, mode_config):
    """Just return constant average speed defined for this mode, peak hours"""
    return mode_config['avespeed-peak']

def assign_free_speeds_constant(route_segments_shp, mode_config):
    print "In %s()." % inspect.stack()[0][3]
    assign_speeds(route_segments_shp, mode_config, constant_speed_max,
        tp_model.SEG_FREE_SPEED_FIELD)
    return

def assign_peak_speeds_constant(route_segments_shp, mode_config):
    print "In %s()." % inspect.stack()[0][3]
    assign_speeds(route_segments_shp, mode_config, constant_speed_max_peak,
        tp_model.SEG_PEAK_SPEED_FIELD)
    return

PEAK_RATIO = 0.5
def ratio_max_speed(route_segment, mode_config):    
    return mode_config['avespeed'] * PEAK_RATIO

def assign_peak_speeds_portion_free_speed(route_segments_shp, mode_config):
    print "In %s()." % inspect.stack()[0][3]
    assign_speeds(route_segments_shp, mode_config, ratio_max_speed,
        tp_model.SEG_PEAK_SPEED_FIELD)
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

def assign_free_speeds_constant_motorway_check(route_segments_shp, mode_config):
    print "In %s()." % inspect.stack()[0][3]
    route_segments_lyr = route_segments_shp.GetLayer(0)
    motorway_calcs.ensure_motorway_field_exists(route_segments_lyr)
    assign_speeds(route_segments_shp, mode_config,
        constant_speed_offpeak_mway_check, tp_model.SEG_FREE_SPEED_FIELD)
    return

def assign_peak_speeds_bus_melb_distance_based_mway_check(route_segments_shp, mode_config):
    print "In %s()." % inspect.stack()[0][3]
    route_segments_lyr = route_segments_shp.GetLayer(0)
    motorway_calcs.ensure_motorway_field_exists(route_segments_lyr)
    assign_speeds(route_segments_shp, mode_config,
        buses_peak_with_mway_check, tp_model.SEG_PEAK_SPEED_FIELD)
    return

# Lat, long of Melbourne's origin in EPSG:4326 (WGS 84 on WGS 84 datum)
# Cnr of Bourke & Swanston
#ORIGIN_LAT_LON = (-37.81348, 144.96558) 
# As provided by Laurent in function - works out at N-E corner of CBD grid
#ORIGIN_LAT_LON = (-37.809176, 144.970653)
# As calculated by converting allnodes.csv[0] from EPSG:28355 to EPSG:4326
ORIGIN_LAT_LON = (-37.81081208860423, 144.969328103266179)

def peak_speed_func(Z_km):
    """Formula used as provided by Laurent Allieres, 7 Nov 2013.
    Modified by Pat S, 2014/10/17, to cut off dist from city centre at max
    50km - otherwise strange values result."""
    Z_km = min(Z_km, 50)
    peak_speed = (230 + 15 * Z_km - 0.13 * Z_km**2) * 60/1000.0 * (2/3.0) \
        + 5.0/(Z_km/50.0+1)
    return peak_speed

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
    origin.AddPoint(ORIGIN_LAT_LON[1], ORIGIN_LAT_LON[0]) # Func takes lon,lat
    origin_srs = osr.SpatialReference()
    origin_srs.ImportFromEPSG(4326)
    transform_origin = osr.CoordinateTransformation(origin_srs, target_srs)
    origin.Transform(transform_origin)
    
    Z = origin.Distance(seg_midpoint)
    Z_km = Z / 1000.0
    V = peak_speed_func(Z_km)
    return V

def assign_peak_speeds_bus_melb_distance_based(route_segments_shp, mode_config):
    print "In %s()." % inspect.stack()[0][3]
    assign_speeds(route_segments_shp, mode_config, calc_peak_speed_melb_bus,
        tp_model.SEG_PEAK_SPEED_FIELD)
    return

if __name__ == "__main__":
    parser = OptionParser()
    parser.add_option('--segments', dest='inputsegments', help='Shapefile of line segments.')
    parser.add_option('--service', dest='service', help="Should be 'train', 'tram' or 'bus'.")
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
        
    mode_config = m_t_info.settings[options.service]

    # Open in write-able mode, hence the 1 below.
    fname = os.path.expanduser(options.inputsegments)
    route_segments_shp = osgeo.ogr.Open(fname, 1)    
    if route_segments_shp is None:
        print "Error, route segments shape file given, %s , failed to open." \
            % (options.inputsegments)
        sys.exit(1)    

    #assign_free_speeds_constant(route_segments_shp, mode_config)
    #assign_peak_speeds_constant(route_segments_shp, mode_config)

    #assign_peak_speeds_bus_melb_distance_based(route_segments_shp, mode_config)

    # These two functions require you've first update the motorway status ...
    assign_free_speeds_constant_motorway_check(route_segments_shp, mode_config)
    assign_peak_speeds_bus_melb_distance_based_mway_check(route_segments_shp, mode_config)

    # Close the shape files - includes making sure it writes
    route_segments_shp.Destroy()
    route_segments_shp = None
