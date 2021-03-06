#!/usr/bin/env python2
import os
import os.path
import re
import sys
import inspect
import operator
from optparse import OptionParser

import osgeo.ogr
from osgeo import ogr, osr

import parser_utils
import topology_shapefile_data_model as tp_model
import route_geom_ops
import lineargeom

# All of these distances are in meters. Will project into
# chosen EPSG for testing, so set it appropriate to your region.
ON_POINT_CHECK_DIST = 0.01

def get_route_num_from_feature(route):
    rname = route.GetField(tp_model.ROUTE_NAME_FIELD)
    if rname[0] == 'R' and len(rname) <= 4:
        r_key = int(rname[1:])
    else:    
        r_key = rname
    return r_key

def calc_distance(route, stops):
    """Calculate the linear distance along a route, between two stops."""
    route_geom = route.GetGeometryRef()
    stop_geoms = [stop.GetGeometryRef() for stop in stops]

    stop_coords = []
    for ii, stop_geom in enumerate(stop_geoms):
        stop_coords.append(*stop_geom.GetPoints())
    #print "Stop coords are: %s" % (stop_coords)

    target_srs = osr.SpatialReference()
    target_srs.ImportFromEPSG(route_geom_ops.COMPARISON_EPSG)

    stop_points_tform = []
    stop_coords_tform = []
    src_srs = stop_geoms[0].GetSpatialReference()
    transform = osr.CoordinateTransformation(src_srs, target_srs)
    for ii, coord in enumerate(stop_coords):
        stop_points_tform.append(ogr.Geometry(ogr.wkbPoint))
        stop_points_tform[-1].AddPoint(*coord)
        stop_points_tform[-1].Transform(transform)
        stop_coords_tform.append(stop_points_tform[-1].GetPoint())

    route_coords = route_geom.GetPoints()
    src_srs = route_geom.GetSpatialReference()
    transform = osr.CoordinateTransformation(src_srs, target_srs)
    route_coords_tform = []
    for ii, coord in enumerate(route_coords):
        pt = ogr.Geometry(ogr.wkbPoint)
        pt.AddPoint(*coord)
        pt.Transform(transform)
        route_coords_tform.append(pt.GetPoints()[0])

    on_sections = [None, None]
    min_dist_to_sec = [1e30, 1e30]
    num_route_coords = len(route_coords_tform)    
    for ver_ii, route_coord in enumerate(route_coords_tform):
        if ver_ii != num_route_coords-1:
            next_seg = ogr.Geometry(ogr.wkbLineString)
            next_seg.AddPoint(*route_coords_tform[ver_ii])
            next_seg.AddPoint(*route_coords_tform[ver_ii+1])
            for stop_ii, stop_point in enumerate(stop_points_tform):
                if on_sections[stop_ii] is None:
                    dist = next_seg.Distance(stop_point)
                    if dist < min_dist_to_sec[stop_ii]:
                        min_dist_to_sec[stop_ii] = dist
                    if dist <= route_geom_ops.STOP_ON_ROUTE_CHECK_DIST:
                        on_sections[stop_ii] = (ver_ii, ver_ii+1)
        if None not in on_sections:
            #Finish early if we can.
            break

    #print "On sections were %s, %s" % tuple(on_sections)

    for ii, on_sec in enumerate(on_sections):
        if on_sec == None:
            stop_id = stops[ii].GetField(tp_model.STOP_ID_FIELD)
            route_id = route.GetField(tp_model.ROUTE_NAME_FIELD)
            print "Error:- stop %s, at coords %s, not found to be on any "\
                "section of route %s. Minimum dist to sec. was %.2f" % \
                (stop_id, stop_coords[ii], route_id, min_dist_to_sec[ii])
            return -1

    if on_sections[0] > on_sections[1]:
        on_sections.reverse()
        min_dist_to_sec.reverse()
        stop_coords.reverse()
        stop_coords_tform.reverse()
        stop_points_tform.reverse()

    subline = ogr.Geometry(ogr.wkbLineString)
    subline.AssignSpatialReference(target_srs)

    if on_sections[0] == on_sections[1]:
        #Both stops are on the same section. So subline is just between two
        #stops
        subline.AddPoint(*stop_coords_tform[0])
        subline.AddPoint(*stop_coords_tform[1])
    else:
        first_pt = ogr.Geometry(ogr.wkbPoint)
        first_pt.AddPoint(*route_coords_tform[on_sections[0][0]])
        if first_pt.Distance(stop_points_tform[0]) > ON_POINT_CHECK_DIST: 
            #print "Starting subline at lower stop"
            subline.AddPoint(*stop_coords_tform[0])
        else:    
            #print "Starting subline at vertex %d" % on_sections[0][0]
            subline.AddPoint(*route_coords_tform[on_sections[0][0]])
        # now, add all intervening points.
        for pt_ii in range(on_sections[0][0]+1, on_sections[1][0]+1):
            #print "Adding to subline vertex %d" % pt_ii
            subline.AddPoint(*route_coords_tform[pt_ii])
        last_sec_start_pt = ogr.Geometry(ogr.wkbPoint)
        last_sec_start_pt.AddPoint(*route_coords_tform[on_sections[1][0]])
        last_pt = ogr.Geometry(ogr.wkbPoint)
        last_pt.AddPoint(*route_coords_tform[on_sections[1][1]])
        dist_last_sec_start = last_sec_start_pt.Distance(stop_points_tform[1])
        if dist_last_sec_start <= ON_POINT_CHECK_DIST:
            # We don't need to add any more for last section.
            pass
        elif last_pt.Distance(stop_points_tform[1]) > ON_POINT_CHECK_DIST: 
            #print "Finishing subline at upper stop"
            subline.AddPoint(*stop_coords_tform[1])
        else:    
            #print "Finishing subline at vertex %d" % on_sections[1][1]
            subline.AddPoint(*route_coords_tform[on_sections[1][1]])
            
    #print subline.GetPoints()
    #length = subline.Length()
    #print "Length was %d meters." % round(length)
    length = lineargeom.calc_length_along_line_haversine(subline)
    return length

def get_route(route_lyr, route_num):
    found_route = None
    for route in route_lyr:
        if route.GetField(tp_model.ROUTE_NAME_FIELD) == route_num:
            found_route = route
            break
    route_lyr.ResetReading()
    return found_route

def get_stops(stops_lyr, stop_ids):
    stops = []
    for stop_id in stop_ids:
        stop_to_add = None
        for stop_ii, stop in enumerate(stops_lyr):
            if stop.GetField(tp_model.STOP_ID_FIELD) == stop_id:
                #print "Found stop %d, at %d thru stops list" \
                #   % (stop_id, stop_ii)
                stop_to_add = stop
                break
        stops.append(stop_to_add)
        stops_lyr.ResetReading()
    return stops

def calc_single_route_segment_length(route, stops):
    return calc_distance(route, stops)
    
def calc_all_route_segment_lengths(route, segments_lyr, stops_lyr,
        update=False):
    route_num = route.GetField(tp_model.ROUTE_NAME_FIELD)
    print "Calculating segment lengths for route %s" % (route_num)

    # First we will sub-select stops, only based on those around route
    route_geom = route.GetGeometryRef()
    # Use a safety factor in buffer, for stops maybe right on margin
    #  especially as we're transforming into stops layer EPSG.
    route_buffer = route_geom.Buffer(route_geom_ops.STOP_ON_ROUTE_CHECK_DIST*1.5)
    routes_srs = route_geom.GetSpatialReference()
    stops_srs = stops_lyr.GetSpatialRef()
    transform = osr.CoordinateTransformation(routes_srs, stops_srs)
    route_buffer.Transform(transform)
    stops_lyr.SetSpatialFilter(route_buffer)

    for segment in segments_lyr:
        seg_id = segment.GetField(tp_model.SEG_ID_FIELD)
        rlist = segment.GetField(tp_model.SEG_ROUTE_LIST_FIELD).split(',')
        if route_num in rlist:
            s_id_a = int(segment.GetField(tp_model.SEG_STOP_1_NAME_FIELD)[1:])
            s_id_b = int(segment.GetField(tp_model.SEG_STOP_2_NAME_FIELD)[1:])
            stop_ids = [s_id_a, s_id_b]
            stops = get_stops(stops_lyr, stop_ids)
            missing_stop = False
            for s_i, stop in enumerate(stops):
                if stop is None:
                    print "Error in segment %s: can't find stop %d in "\
                        "set of buffered stops around route. "\
                        "Skipping." % (seg_id, stop_ids[s_i])
                    missing_stop = True    
            if missing_stop: continue
            length = calc_single_route_segment_length(route, stops)
            prev_length = segment.GetField(tp_model.SEG_ROUTE_DIST_FIELD)
            rnd_length = round(length)
            if prev_length > 0:
                length_change_ratio = abs(rnd_length-prev_length)/prev_length 
            else:
                length_change_ratio = 0

            if prev_length == None or (prev_length == 0 and rnd_length >= 1) or \
                    length_change_ratio > 0.01:
                print "Calculating length of segment %s (b/w stops %s - %s):"\
                    % (seg_id, s_id_a, s_id_b)
                print "Rounded length calculated as %.1f m "\
                    "(Prev stored: %.1f m)" % \
                    (rnd_length, prev_length)
            if update == True:
                segment.SetField(tp_model.SEG_ROUTE_DIST_FIELD, round(length))
                # This call necessary to actually save updated value to layer
                segments_lyr.SetFeature(segment)
            segment.Destroy()    
    segments_lyr.ResetReading()
    stops_lyr.SetSpatialFilter(None)
    return

def calc_all_route_segment_lengths_all_routes(route_lyr, segments_lyr,
        stops_lyr, update=False):
    # This dict allows going thru routes in sorted order, convenient for user.
    sorted_route_list = sorted(route_lyr, key=get_route_num_from_feature)
    for route in sorted_route_list:
        calc_all_route_segment_lengths(route, segments_lyr, stops_lyr,
            update)
        route.Destroy()    

def testing():    
    fname = os.path.expanduser('/Users/pds_phd/Dropbox/PhD-TechnicalProjectWork/OSSTIP_BZE/Melbourne_GIS_NetworkDataWork/BZE_New_Network/QGISnetwork/in/shp/network-self-snapped-reworked-patextend-201405.shp')
    route_shape = osgeo.ogr.Open(fname, 0) 
    stops_fname = '/Users/pds_phd/Dropbox/PhD-TechnicalProjectWork/OSSTIP_BZE/Melbourne_GIS_NetworkDataWork/BZE_New_Network/bus-nodes-segments-13_dec-motorway-stops-removed/bus-nodes.shp'
    stops_shape = osgeo.ogr.Open(stops_fname, 0) 
    segments_fname = '/Users/pds_phd/Dropbox/PhD-TechnicalProjectWork/OSSTIP_BZE/Melbourne_GIS_NetworkDataWork/BZE_New_Network/bus-nodes-segments-13_dec-motorway-stops-removed/bus-edges.shp'
    segments_shape = osgeo.ogr.Open(segments_fname, 1) 
    route_lyr = route_shape.GetLayer(0)
    stops_lyr = stops_shape.GetLayer(0)
    segments_lyr = segments_shape.GetLayer(0)

    #route_num = 'R93'
    route_num = 'R110'
    #stop_ids = [2361, 151]
    #stop_ids = [231, 230]
    stop_ids = [585, 605]

    route = get_route(route_lyr, route_num)
    assert route is not None
    #stops = get_stops(stops_lyr, stop_ids)
    assert None not in stops
    #print "Calculating length for route %s, stop ids %d and %d" % \
    #    (route_num, stop_ids[0], stop_ids[1])
    #length = calc_single_route_segment_length(route, stops)
    #print "Rounded length calculated as %.1f m" % \
    #    (round(length))
    calc_all_route_segment_lengths(route, segments_lyr, stops_lyr,
        update=False)

    route_shape.Destroy()
    route_shape = None
    segments_shape.Destroy()
    segments_shape = None
    stops_shape.Destroy()
    stops_shape = None

if __name__ == "__main__":
    #testing()
    #sys.exit(0)

    parser = OptionParser()
    parser.add_option('--routes', dest='inputroutes',
        help='Shapefile of line routes.')
    parser.add_option('--segments', dest='inputsegments',
        help='Shapefile of line segments.')
    parser.add_option('--stops', dest='inputstops',
        help='Shapefile of line stops.')
    parser.add_option('--update', dest='update',    
        help='Should we actually update the length values?')
    parser.add_option('--route', dest='route',    
        help='Only calculate/update for given route name.')
    parser.set_defaults(update='false')
    (options, args) = parser.parse_args()

    if options.inputroutes is None:
        parser.print_help()
        parser.error("No routes shapefile path given.")
    if options.inputsegments is None:
        parser.print_help()
        parser.error("No segments shapefile path given.")
    if options.inputstops is None:
        parser.print_help()
        parser.error("No stops shapefile path given.")

    update_choice = parser_utils.str2bool(options.update)
    route_num_choice = options.route

    # Open segments in write-able mode, hence the 1 below. Others read-only
    fname = os.path.expanduser(options.inputsegments)
    route_segments_shp = osgeo.ogr.Open(fname, 1)    
    if route_segments_shp is None:
        print "Error, route segments shape file given, %s , failed to open." \
            % (options.inputsegments)
        sys.exit(1)    
    fname = os.path.expanduser(options.inputroutes)
    routes_shp = osgeo.ogr.Open(fname, 0)
    if routes_shp is None:
        print "Error, routes shape file given, %s , failed to open." \
            % (options.inputroutes)
        sys.exit(1)    
    fname = os.path.expanduser(options.inputstops)
    stops_shp = osgeo.ogr.Open(fname, 0)
    if stops_shp is None:
        print "Error, stops shape file given, %s , failed to open." \
            % (options.inputstops)
        sys.exit(1)    

    routes_lyr = routes_shp.GetLayer(0)
    stops_lyr = stops_shp.GetLayer(0)
    segments_lyr = route_segments_shp.GetLayer(0)

    if route_num_choice is not None:
        route = get_route(routes_lyr, route_num_choice)
        assert route is not None
        calc_all_route_segment_lengths(route, segments_lyr, stops_lyr,
            update=update_choice)
    else:    
        calc_all_route_segment_lengths_all_routes(routes_lyr, segments_lyr,
            stops_lyr, update=update_choice)

    # Close the shape files - includes making sure it writes
    route_segments_shp.Destroy()
    route_segments_shp = None
    routes_shp.Destroy()
    routes_shp = None
    stops_shp.Destroy()
    stops_shp = None
