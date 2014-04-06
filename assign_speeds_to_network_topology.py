#!/usr/bin/env python2

import os
import re
import sys
from optparse import OptionParser

import osgeo.ogr
from osgeo import ogr

from create_gtfs_from_basicinfo import settings, SEG_FREE_SPEED_FIELD, \
    SEG_PEAK_SPEED_FIELD

def ensure_speed_field_exists(route_segments_lyr, speed_field_name):
    speed_field_exists = False
    lyr_defn = route_segments_lyr.GetLayerDefn()
    for field_i in range(lyr_defn.GetFieldCount()):
        if lyr_defn.GetFieldDefn(field_i).GetName() == speed_field_name:
            break;
    if field_i < lyr_defn.GetFieldCount():
        f_defn = lyr_defn.GetFieldDefn(field_i)
        # Check type etc is correct
        f_type_code = f_defn.GetType()
        f_type = f_defn.GetFieldTypeName(f_type_code)
        f_width = f_defn.GetWidth()
        f_precision = f_defn.GetPrecision()

        if f_type == 'Real' and f_width >= 24 and f_precision >= 15:
            speed_field_exists = True
        else:    
            print "Error: field '%s' exists, but badly defined - deleting, "\
                "will re-create." % (speed_field_name)
            route_segments_lyr.DeleteField(field_i)
            speed_field_exists = False

    if speed_field_exists == False:
        print "Creating new field '%s'." % speed_field_name
        f_defn = ogr.FieldDefn(speed_field_name, ogr.OFTReal)
        f_defn.SetWidth(24)
        f_defn.SetPrecision(15)
        route_segments_lyr.CreateField(f_defn)  

def assign_free_speeds(route_segments_shp, mode_config):
    route_segments_lyr = route_segments_shp.GetLayer(0)
    ensure_speed_field_exists(route_segments_lyr, SEG_FREE_SPEED_FIELD)
    free_speed = mode_config['avespeed']
    for seg_num, route_segment in enumerate(route_segments_lyr):
        route_segment.SetField(SEG_FREE_SPEED_FIELD, free_speed)
        # This SetFeature() call is necessary to actually write the change
        # back to the layer itself.
        route_segments_lyr.SetFeature(route_segment)
        # Memory mgt
        route_segment.Destroy()    
    route_segments_lyr.ResetReading()
    return

def assign_peak_speeds_portion_free_speed(route_segments_shp, mode_config):
    PEAK_RATIO = 0.5
    route_segments_lyr = route_segments_shp.GetLayer(0)
    ensure_speed_field_exists(route_segments_lyr, SEG_PEAK_SPEED_FIELD)
    free_speed = mode_config['avespeed']
    peak_speed = free_speed * PEAK_RATIO
    for seg_num, route_segment in enumerate(route_segments_lyr):
        route_segment.SetField(SEG_PEAK_SPEED_FIELD, peak_speed)
        # This SetFeature() call is necessary to actually write the change
        # back to the layer itself.
        route_segments_lyr.SetFeature(route_segment)
        # Memory mgt
        route_segment.Destroy()    
    route_segments_lyr.ResetReading()
    return

def assign_peak_speeds_bus_la_distance_based(route_segments_shp, mode_config):
    print "Error: Not written yet!!!"
    sys.exit(1)
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
            % (settings.keys()))
    if options.service not in settings:
        parser.print_help()
        parser.error("Service option requested '%s' not in allowed set, of %s" \
            % (options.service, settings.keys()))
        
    mode_config = settings[options.service]

    # Open in write-able mode, hence the 1 below.
    route_segments_shp = osgeo.ogr.Open(options.inputsegments, 1)    
    assign_free_speeds(route_segments_shp, mode_config)
    assign_peak_speeds_portion_free_speed(route_segments_shp, mode_config)
    # Close the shape files - includes making sure it writes
    route_segments_shp.Destroy()
    route_segments_shp = None
