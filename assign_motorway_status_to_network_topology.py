#!/usr/bin/env python2

import os
import os.path
import sys
import inspect
from optparse import OptionParser

import osgeo.ogr
from osgeo import ogr, osr

import topology_shapefile_data_model as tp_model
import route_geom_ops
import mode_timetable_info as m_t_info
import motorway_calcs

def record_if_on_motorway(route_segment, route_segments_lyr,
        mways_buffer_geom, route_seg_transform, mode_config):
    if motorway_calcs.segment_on_motorway(route_segment, mways_buffer_geom,
            route_seg_transform, mode_config):
        value = 1
    else:
        value = 0
    route_segment.SetField(tp_model.ON_MOTORWAY_FIELD, value)
    route_segments_lyr.SetFeature(route_segment)
    return value

def assign_mway_status(route_segments_shp, mways_shp, mode_config):
    route_segments_lyr = route_segments_shp.GetLayer(0)
    segs_total = route_segments_lyr.GetFeatureCount()
    motorway_calcs.ensure_motorway_field_exists(route_segments_lyr)

    target_srs = osr.SpatialReference()
    target_srs.ImportFromEPSG(route_geom_ops.COMPARISON_EPSG)

    mways_lyr = mways_shp.GetLayer(0)
    mways_buffer_geom = motorway_calcs.create_motorways_buffer(mways_lyr,
        target_srs, mode_config['on_motorway_seg_check_dist'])
    route_segs_srs = route_segments_lyr.GetSpatialRef()
    route_seg_transform = osr.CoordinateTransformation(route_segs_srs, target_srs)

    print "Assigning motorway status to all %d route segments:" % \
        (segs_total)
    one_tenth = segs_total / 10.0
    segs_since_print = 0
    mway_segs_cnt = 0
    dist_total = 0
    mway_dist_total = 0
    for seg_num, route_segment in enumerate(route_segments_lyr):
        route_geom_clone = route_segment.GetGeometryRef().Clone()
        route_geom_clone.Transform(route_seg_transform)
        seg_length = route_geom_clone.Length()
        dist_total += seg_length
        if segs_since_print / one_tenth > 1:
            print "...assigning to segment number %d ..." % (seg_num)
            segs_since_print = 0
        else:
            segs_since_print += 1
        mway_status = record_if_on_motorway(route_segment, route_segments_lyr,
            mways_buffer_geom, route_seg_transform, mode_config)
        if mway_status:
            mway_segs_cnt += 1
            mway_dist_total += seg_length
        # Memory mgt
        route_geom_clone.Destroy()
        route_segment.Destroy()    
    if segs_total == 0:
        mway_percent = 0
        mway_dist_percent = 0
    else:
        mway_percent = mway_segs_cnt / float(segs_total) * 100
        mway_dist_percent = mway_dist_total / float(dist_total) * 100
    print "...finished assigning motorway status to segments: "\
        "%d detected as mways, out of %d total "\
        "(%.1f%% of total segs, %.1f%% of total seg distance)" %\
        (mway_segs_cnt, segs_total, mway_percent, mway_dist_percent)
    route_segments_lyr.ResetReading()
    return

if __name__ == "__main__":
    allowedServs = ', '.join(sorted(["'%s'" % key for key in \
        m_t_info.settings.keys()]))
    parser = OptionParser()
    parser.add_option('--segments', dest='inputsegments',
        help='Shapefile of line segments.')
    parser.add_option('--motorways', dest='motorways', help="Shapefile of "\
        "motorway sections (exported from OpenStreetMap)")
    parser.add_option('--service', dest='service',
        help="Should be one of %s" % allowedServs)
    (options, args) = parser.parse_args()

    if options.inputsegments is None:
        parser.print_help()
        parser.error("No segments shapefile path given.")
    if options.motorways is None:
        parser.print_help()
        parser.error("No motorway sections shapefile given.")
    if options.service is None:
        parser.print_help()
        parser.error("No service option requested. Should be one of %s" \
            % (allowedServs))
    if options.service not in m_t_info.settings:
        parser.print_help()
        parser.error("Service option requested '%s' not in allowed set, of %s" \
            % (options.service, allowedServs))

    mode_config = m_t_info.settings[options.service]

    # Open in write-able mode, hence the 1 below.
    segs_fname = os.path.expanduser(options.inputsegments)
    route_segments_shp = osgeo.ogr.Open(segs_fname, 1)    
    if route_segments_shp is None:
        print "Error, route segments shape file given, %s , failed to open." \
            % (options.inputsegments)
        sys.exit(1)

    mways_fname = os.path.expanduser(options.motorways)
    mways_shp = osgeo.ogr.Open(mways_fname, 1)
    if mways_shp is None:
        print "Error, motorways shape file given, %s , failed to open." \
            % (options.motorways)
        sys.exit(1)

    assign_mway_status(route_segments_shp, mways_shp, mode_config)

    # Close the shape files - includes making sure it writes
    mways_shp.Destroy()
    mways_shp = None
    route_segments_shp.Destroy()
    route_segments_shp = None
