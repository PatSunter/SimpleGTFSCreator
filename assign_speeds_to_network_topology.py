#!/usr/bin/env python2

import os
import os.path
import re
import sys
from optparse import OptionParser

import osgeo.ogr
from osgeo import ogr, osr

import mode_timetable_info as m_t_info
import topology_shapefile_data_model as tp_model

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

def assign_speeds(route_segments_shp, mode_config, speed_func, speed_field_name):
    route_segments_lyr = route_segments_shp.GetLayer(0)
    ensure_speed_field_exists(route_segments_lyr, speed_field_name)
    for seg_num, route_segment in enumerate(route_segments_lyr):
        if seg_num % 100 == 0:
            print "Assigning distance-based speed to segment number %d" % (seg_num)
        speed = speed_func(route_segment, mode_config)
        route_segment.SetField(speed_field_name, speed)
        # This SetFeature() call is necessary to actually write the change
        # back to the layer itself.
        route_segments_lyr.SetFeature(route_segment)
        # Memory mgt
        route_segment.Destroy()    
    route_segments_lyr.ResetReading()
    return


def assign_free_speeds_constant(route_segments_shp, mode_config):
    route_segments_lyr = route_segments_shp.GetLayer(0)
    ensure_speed_field_exists(route_segments_lyr, tp_model.SEG_FREE_SPEED_FIELD)
    free_speed = mode_config['avespeed']
    for seg_num, route_segment in enumerate(route_segments_lyr):
        route_segment.SetField(tp_model.SEG_FREE_SPEED_FIELD, free_speed)
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
    ensure_speed_field_exists(route_segments_lyr, tp_model.SEG_PEAK_SPEED_FIELD)
    free_speed = mode_config['avespeed']
    peak_speed = free_speed * PEAK_RATIO
    for seg_num, route_segment in enumerate(route_segments_lyr):
        route_segment.SetField(tp_model.SEG_PEAK_SPEED_FIELD, peak_speed)
        # This SetFeature() call is necessary to actually write the change
        # back to the layer itself.
        route_segments_lyr.SetFeature(route_segment)
        # Memory mgt
        route_segment.Destroy()    
    route_segments_lyr.ResetReading()
    return

# Lat, long of Melbourne's origin in EPSG:4326 (WGS 84 on WGS 84 datum)
# Cnr of Bourke & Swanston
#ORIGIN_LAT_LON = (-37.81348, 144.96558) 
# As provided by Laurent in function - works out at N-E corner of CBD grid
#ORIGIN_LAT_LON = (-37.809176, 144.970653)
# As calculated by converting allnodes.csv[0] from EPSG:28355 to EPSG:4326
ORIGIN_LAT_LON = (-37.81081208860423, 144.969328103266179)

def peak_speed_func(Z_km):
    """Formula used as provided by Laurent Allieres, 7 Nov 2013."""
    peak_speed = (230 + 15 * Z_km - 0.13 * Z_km**2) * 60/1000.0 * (2/3.0) \
        + 5.0/(Z_km/50.0+1)
    return peak_speed    

def calc_peak_speed_melb_bus(route_segment):
    # We are going to reproject everything into a metre-based coord system
    #  to do the distance calculation.
    # Chose EPSG:28355 ("GDA94 / MGA zone 55") as an appropriate projected
    # Coordinate system, in meters, for the Melbourne region.
    #  (see http://spatialreference.org/ref/epsg/gda94-mga-zone-55/)
    target_srs = osr.SpatialReference()
    target_srs.ImportFromEPSG(28355)

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
    route_segments_lyr = route_segments_shp.GetLayer(0)
    ensure_speed_field_exists(route_segments_lyr, tp_model.SEG_PEAK_SPEED_FIELD)
    free_speed = mode_config['avespeed']
    for seg_num, route_segment in enumerate(route_segments_lyr):
        if seg_num % 100 == 0:
            print "Assigning distance-based speed to segment number %d" % (seg_num)
        peak_speed = calc_peak_speed_melb_bus(route_segment)
        route_segment.SetField(tp_model.SEG_PEAK_SPEED_FIELD, peak_speed)
        # This SetFeature() call is necessary to actually write the change
        # back to the layer itself.
        route_segments_lyr.SetFeature(route_segment)
        # Memory mgt
        route_segment.Destroy()    
    route_segments_lyr.ResetReading()
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
    assign_free_speeds_constant(route_segments_shp, mode_config)
    #assign_peak_speeds_portion_free_speed(route_segments_shp, mode_config)
    assign_peak_speeds_bus_melb_distance_based(route_segments_shp, mode_config)
    # Close the shape files - includes making sure it writes
    route_segments_shp.Destroy()
    route_segments_shp = None
