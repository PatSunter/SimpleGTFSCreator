#!/usr/bin/env python2
import os
import os.path
import sys
import inspect
from optparse import OptionParser
import math
import csv

import osgeo.ogr
from osgeo import ogr, osr

import parser_utils
import mode_timetable_info as m_t_info
import topology_shapefile_data_model as tp_model
import route_geom_ops
import motorway_calcs

DEFAULT_FILLER_DIST = 500
MAX_FILLER_DIST = 100000

DELETE_EXISTING = True

ROUTE_START_END_NAME = "ROUTE_START_END"
TRANSFER_SELF_NAME = "TRANSFER_SELF"
FILLER_NAME = "FILLERS"

BUFFER_DIST_SELF_ROUTE_TRANSFER = 30.0
CROSSING_ANGLE_FACTOR = 0.01
MIN_DIST_TO_PLACE_ISECT_STOPS = 100.0

class TransferNetworkDef:
    def __init__(self, shp_fname, tfer_range, stop_min_dist, stop_typ_name,
            skip_on_mway):
        self.shp_fname = shp_fname
        self.tfer_range = tfer_range
        self.stop_min_dist = stop_min_dist
        self.stop_typ_name = stop_typ_name
        self.skip_on_mway = skip_on_mway

def add_route_start_end_stops(stops_lyr, input_routes_lyr, stops_multipoint):
    src_srs = input_routes_lyr.GetSpatialRef()
    print "Adding route start and end stops...."
    for ii, route in enumerate(input_routes_lyr):
        route_geom = route.GetGeometryRef()
        #print "For route '%s':" % route.GetField(0)
        start_pt = ogr.Geometry(ogr.wkbPoint)
        start_pt.AddPoint(*route_geom.GetPoint(0))
        end_pt = ogr.Geometry(ogr.wkbPoint)
        end_pt.AddPoint(*route_geom.GetPoint(route_geom.GetPointCount()-1))
        start_end_pts = [start_pt, end_pt]
        for ii, pt in enumerate(start_end_pts):
            dist_existing = route_geom_ops.get_min_dist_from_existing_stops(pt,
                stops_multipoint)
            #print "(Calc dist from existing for start/end pt %d as %.1f)" %\
            #    (ii, dist_existing)
            if dist_existing < route_geom_ops.SAME_POINT:
                #print "...not adding stop at stop at route start/end as "\
                #    "there is a stop here already."
                pass
            else:
                stop_id = tp_model.add_stop(stops_lyr, stops_multipoint,
                    ROUTE_START_END_NAME, pt, src_srs)
                #print "...Adding stop at route start/end"
    input_routes_lyr.ResetReading()
    print "...done adding start and end stops."
    return

def first_good_intersect_point(line_geom, other_line_geom,
        start_from_end=False):
    # Multi-pronged approach:
    # Best case is that one of the early points, within BUFFER_DIST * 3,
    #  is very near line.
    # Else, just return the closest within buffer_dist *3
    line_geom_2 = line_geom.Clone()
    line_geom_2.Segmentize(route_geom_ops.VERY_NEAR_ROUTE/2.0)
    pts_list = line_geom_2.GetPoints()
    nearest_dist = sys.maxint
    nearest_index = 0

    if start_from_end:
        pts_list = list(reversed(pts_list))
    first_pt = ogr.Geometry(ogr.wkbPoint)
    first_pt.AddPoint(*pts_list[0])
    for ii, pt_coords in enumerate(pts_list):
        new_pt = ogr.Geometry(ogr.wkbPoint)
        new_pt.AddPoint(*pt_coords)
        dist_from_first_pt = new_pt.Distance(first_pt)
        if dist_from_first_pt > 3 * BUFFER_DIST_SELF_ROUTE_TRANSFER:
            return pts_list[nearest_index]
        dist_from_other = new_pt.Distance(other_line_geom) 
        if dist_from_other < nearest_dist:
            nearest_dist = dist_from_other
            nearest_index = ii
        if dist_from_other < route_geom_ops.VERY_NEAR_ROUTE:
            return pt_coords
    return None

def get_isect_points_of_interest(isect_line, other_route_geom):
    isect_point_cnt = isect_line.GetPointCount()
    isect_pts_interest = []
    if isect_line.Length() < \
        (2 * BUFFER_DIST_SELF_ROUTE_TRANSFER) * CROSSING_ANGLE_FACTOR:
        # This is a short crossover intersection. (The angle factor is
        # to do with routes that cross at an angle rather than
        # perpendicular.
        # In this case, just use centroid of where the orig route crosses
        # the buffer
        isect_pts_interest = [isect_line.Centroid().GetPoint(0)]
    else:
        # This is a longer line intersect section, meaning the two
        # routes run parallel for a while. So in this case, we want
        # to get the start and the end parts of the parallel running,
        # and move from buffer to actual lines where possible.
        isect_line_pts = isect_line.GetPoints()
        first_pt_isect = isect_line_pts[0]
        # Now get closest point on actual other route to this pt.
        first_pt = first_good_intersect_point(isect_line, other_route_geom)
        if first_pt == None:
            # If lines never actually get really close, just fall-back
            # to the first point that intersects the buffer
            first_pt = first_pt_isect
        isect_pts_interest.append(first_pt)
        if isect_point_cnt > 1:
            end_pt_isect = isect_line_pts[-1]
            end_pt = first_good_intersect_point(isect_line,
                other_route_geom, start_from_end=True)
            if end_pt == None:
                # If lines never actually get really close, just fall-back
                # to the first point that intersects the buffer
                end_pt = end_pt_isect
            isect_pts_interest.append(end_pt)
    return isect_pts_interest

def add_valid_intersection_stops(pt_coords, stops_lyr,
        stops_multipoint, mways_buffer_geom, route_geom_transform,
        route_geom, other_route_geom):
    stops_added_cnt = 0
    #print "Detected isect_self point at (%f, %f)" % pt_coords
    new_pt = ogr.Geometry(ogr.wkbPoint)
    new_pt.AddPoint(*pt_coords)

    if mways_buffer_geom and motorway_calcs.stop_on_motorway(new_pt,
            route_geom, mways_buffer_geom, route_geom_transform):
        # Skipping this point if on a motorway.
        #print "...but skipping since on a motorway."
        new_pt.Destroy()
        return 0

    min_dist_on_both_routes = sys.maxint
    min_dist_on_route = route_geom_ops.get_stops_already_on_route_within_dist(
        new_pt, route_geom, stops_multipoint, 
        MIN_DIST_TO_PLACE_ISECT_STOPS)
    for exist_stop_geom, dist_new in min_dist_on_route: 
        dist_other = exist_stop_geom.Distance(other_route_geom)
        # Use the buffer tfer dist, not
        # STOP_ON_ROUTE_CHECK_DIST, since given other
        # algorithm improvements, we're confident transfer
        # stops will be added to other routes within this range.
        if dist_other < BUFFER_DIST_SELF_ROUTE_TRANSFER:
            min_dist_on_both_routes = dist_new
            break
        else:
            #print "...(A close point on route wasn't within %.1fm "\
            #    "of other route - %.1fm to new, %.1fm to other)" \
            #    % (BUFFER_DIST_SELF_ROUTE_TRANSFER, dist_new, \
            #        dist_other)
            new_pt.Destroy()
            return 0

    #print "(Dist from existing on route = %.1f)" % \
    #    min_dist_on_both_routes
    if min_dist_on_both_routes < MIN_DIST_TO_PLACE_ISECT_STOPS:
        #print "...but there is already a stop within "\
        #"%.1fm on this route and other route, so skipping." \
        #    % min_dist_on_both_routes
        new_pt.Destroy()
        return 0

    dist_self = new_pt.Distance(route_geom)
    dist_other = new_pt.Distance(other_route_geom)    
    assert (dist_self < route_geom_ops.STOP_ON_ROUTE_CHECK_DIST)

    if (dist_other <= route_geom_ops.STOP_ON_ROUTE_CHECK_DIST):
        if mways_buffer_geom and motorway_calcs.stop_on_motorway(new_pt,
                other_route_geom, mways_buffer_geom,
                route_geom_transform):
            #print "...but skipping since isect loc is a motorway "\
            #    "on other route."
            new_pt.Destroy()
            return 0
        src_srs = route_geom.GetSpatialReference()
        stop_id = tp_model.add_stop(stops_lyr, stops_multipoint,
            TRANSFER_SELF_NAME, new_pt, src_srs)
        stops_added_cnt = 1
        new_pt.Destroy()
        #print "...and adding a stop here: B%d." % stop_id
    else:
        # In this case, we possibly need to add stops on both
        # routes, so they both get picked up in later segmenting
        # algorithm.
        new_pt_buffer = new_pt.Buffer(
            BUFFER_DIST_SELF_ROUTE_TRANSFER*2)
        other_route_in_range = other_route_geom.Intersection(
            new_pt_buffer)
        new_pt_other = route_geom_ops.get_nearest_point_on_route_within_buf(
            new_pt, other_route_geom, other_route_in_range)
        assert new_pt_other is not None
        if mways_buffer_geom and motorway_calcs.stop_on_motorway(new_pt_other,
                other_route_geom, mways_buffer_geom,
                route_geom_transform):
            #print "...but skipping since isect loc is a motorway "\
            #    "on other route."
            new_pt.Destroy()
            new_pt_other.Destroy()
            return 0
        src_srs = route_geom.GetSpatialReference()
        stop_id_1 = tp_model.add_stop(stops_lyr, stops_multipoint,
            TRANSFER_SELF_NAME, new_pt, src_srs)
        stop_id_2 = tp_model.add_stop(stops_lyr, stops_multipoint,
            TRANSFER_SELF_NAME, new_pt_other, src_srs)
        stops_added_cnt = 2
        new_pt.Destroy()
        new_pt_other.Destroy()
        #print "...and adding a stop here: B%d." % stop_id
        #print "...also adding a stop on other route, as dist "\
        #    "%.1f is > %.1f" % (dist_other, \
        #    route_geom_ops.STOP_ON_ROUTE_CHECK_DIST)
        #print "...Stop IDs were B%d and B%d" % \
        #   (stop_id_1, stop_id_2)
    return stops_added_cnt

def add_key_intersection_points_as_stops(isect_line, stops_lyr,
        stops_multipoint, mways_buffer_geom, route_geom_transform,
        route_geom, other_route_geom):
    stops_added_cnt = 0
    isect_point_cnt = isect_line.GetPointCount()
    if isect_point_cnt > 0:
        isect_pts_interest = get_isect_points_of_interest(isect_line,
            other_route_geom)
        for pt_coords in isect_pts_interest:
            stops_added_cnt += add_valid_intersection_stops(pt_coords,
                stops_lyr, stops_multipoint,
                mways_buffer_geom, route_geom_transform,
                route_geom, other_route_geom)
    return stops_added_cnt

def add_self_transfer_stops(stops_lyr, input_routes_lyr,
        mways_buffer_geom, route_geom_transform, stops_multipoint):
    print "Adding 'self-transfer' stops at intersections between routes...."
    self_transfer_stops_total = 0
    for ii, route in enumerate(input_routes_lyr):
        rname = route.GetField(0)
        print "...adding self-transfer stops from route %s...." % rname
        route_geom = route.GetGeometryRef()
        route_isect_stops_total = 0
        for jj in range(ii+1, input_routes_lyr.GetFeatureCount()):
            other_route = input_routes_lyr.GetFeature(jj)
            #print "Testing for intersection pts on routes '%s' and '%s' "\
            #    % (route.GetField(0), other_route.GetField(0))
            # Put a buffer around 2nd route before we do the intersect
            # (to deal with fact routes were manually drawn into GIS,
            # may not actually be co-incident even though nominally 
            # running parallel on the same route for a section)
            other_route_geom = other_route.GetGeometryRef() 
            other_route_buffer_geom = other_route_geom.Buffer(
                BUFFER_DIST_SELF_ROUTE_TRANSFER)
            # calculate intersects between route and buffered
            route_isect = route_geom.Intersection(other_route_buffer_geom)
            isect_type = route_isect.GetGeometryName()
            if route_isect.GetGeometryCount() == 0:
                if route_isect.GetPointCount() > 0:
                    added_cnt = add_key_intersection_points_as_stops(
                        route_isect,
                        stops_lyr, stops_multipoint,
                        mways_buffer_geom, route_geom_transform,
                        route_geom, other_route_geom)
                    route_isect_stops_total += added_cnt
            else:
                for line in route_isect:
                    added_cnt = add_key_intersection_points_as_stops(line,
                        stops_lyr, stops_multipoint,
                        mways_buffer_geom, route_geom_transform,
                        route_geom, other_route_geom)
                    route_isect_stops_total += added_cnt
        print "...added %d self-transfer stops for route %s." % \
            (route_isect_stops_total, rname)
        self_transfer_stops_total += route_isect_stops_total
    input_routes_lyr.ResetReading()
    print "...done adding self-transfer stops (a total of %d).\n" % \
        self_transfer_stops_total
    return
 
def add_nearest_point_on_route_as_stop(route_sec_within_range,
        stops_lyr, stops_multipoint, 
        mways_buffer_geom, route_geom_transform,
        route_geom, other_s_geom, other_s_buf,
        stop_typ_name, stop_min_dist):
    route_geom_srs = route_geom.GetSpatialReference()
    closest_pt_g = route_geom_ops.get_nearest_point_on_route_within_buf(
        other_s_geom, route_geom, route_sec_within_range)
    # Check results of above, to be sure
    assert closest_pt_g is not None        
    dist_to_route = closest_pt_g.Distance(route_sec_within_range)
    assert dist_to_route < route_geom_ops.VERY_NEAR_ROUTE
    #print "...found closest point at %.2f, %.2f" % \
    #    closest_pt_g.GetPoints()[0][:2]
    # Now, need to check if there are other stops already added on this
    # line, within min dist to place stops.
    min_dist_on_route = route_geom_ops.get_stops_already_on_route_within_dist(
        closest_pt_g, route_geom, stops_multipoint, 
        stop_min_dist)
    if min_dist_on_route == []:
        min_dist_on_line = sys.maxint
        #print "...(calculated no other stops within dist.)"
    else:
        min_dist_on_line = min_dist_on_route[0][1]
        #print "...(calculated min dist to other stop on route as %.2f)" % \
        #    min_dist_on_line    

    if min_dist_on_line >= stop_min_dist:
        if mways_buffer_geom and motorway_calcs.stop_on_motorway(
                closest_pt_g, route_geom, mways_buffer_geom,
                route_geom_transform):
            #print "...but skipping since closest point is on a motorway "\
            #    "on nearby route."
            pass
        else:
            stop_id = tp_model.add_stop(stops_lyr, stops_multipoint,
                stop_typ_name, closest_pt_g, route_geom_srs)
            #print "...added stop B%d." % stop_id
    else:
        #print "...not adding stop, since is < %.1fm (min dist this mode) "\
        #    "to existing stop on this line." % stop_min_dist
        pass
    return

def save_tfer_info(shp_file_name, route, route_sec_within_range, other_stop):
    """A helper func. to save debugging info to disk."""                
    driver = ogr.GetDriverByName("ESRI Shapefile")
    if os.path.exists(shp_file_name):
        os.unlink(shp_file_name)
    segs_shp_file = driver.CreateDataSource(shp_file_name)
    layer = segs_shp_file.CreateLayer("tfers", 
        input_routes_lyr.GetSpatialRef(),
        ogr.wkbLineString)
    field = ogr.FieldDefn("station", ogr.OFTString)
    field.SetWidth(256)
    layer.CreateField(field)
    field = ogr.FieldDefn("route", ogr.OFTString)
    field.SetWidth(24)
    layer.CreateField(field)
    feat = ogr.Feature(layer.GetLayerDefn())
    feat.SetGeometry(route_sec_within_range)
    feat.SetField("station",
        other_stop.GetField("Name"))
    feat.SetField("route", route.GetField(0))
    layer.CreateFeature(feat)
    feat.Destroy()
    segs_shp_file.Destroy()

def add_other_network_transfer_stops(stops_lyr, input_routes_lyr,
        mways_buffer_geom, route_geom_transform,
        transfer_network_defs, stops_multipoint):
    print "Checking for need to add transfer stops near other networks"
    for isect_nw_def in transfer_network_defs:
        print "Checking in network defined in shpfile %s" % \
            isect_nw_def.shp_fname
        tfer_nw_stop_shp = osgeo.ogr.Open(isect_nw_def.shp_fname, 0)
        if tfer_nw_stop_shp is None:
            print "Error, input transfer network stop shape file given, "\
                "%s , failed to open." \
                % (isect_nw_def.shp_fname)
            sys.exit(1)
        tfer_nw_stop_lyr = tfer_nw_stop_shp.GetLayer(0)    
        stop_typ_name = isect_nw_def.stop_typ_name

        src_srs = tfer_nw_stop_lyr.GetSpatialRef()
        target_srs = input_routes_lyr.GetSpatialRef()

        if isect_nw_def.skip_on_mway == True:
            print "(Disabling adding stops onto motorway sections for "\
                "this mode.)"
            mways_buffer_geom_this_mode = mways_buffer_geom
            route_geom_transform_this_mode = route_geom_transform
        else:
            print "(Enabling adding stops onto motorway sections for "\
                "this mode.)"
            # Override these motorway overrides in this function.
            mways_buffer_geom_this_mode = None
            route_geom_transform_this_mode = None

        total_stops_tfer_nw = tfer_nw_stop_lyr.GetFeatureCount()
        for ii, other_stop in enumerate(tfer_nw_stop_lyr):
            #print "Checking for routes within %.1fm of stop %d(%s)" % \
            #    (isect_nw_def.tfer_range, ii, other_stop.GetField("Name"))
            other_s_geom = other_stop.GetGeometryRef()
            # Now need to transform into this coord system.
            transform = osr.CoordinateTransformation(src_srs, target_srs)
            other_s_geom.Transform(transform)
            other_s_buf = other_s_geom.Buffer(isect_nw_def.tfer_range)
            for route in input_routes_lyr:
                route_geom = route.GetGeometryRef()
                route_sec_within_range = route_geom.Intersection(
                    other_s_buf)
                #if other_stop.GetField("Name") == "Name_of_interest"\
                #        and route.GetField(0) == "R1":
                    #save_tfer_info("tfers.shp", route,
                    #    route_sec_within_range, other_stop)

                if route_sec_within_range.GetGeometryCount() == 0 \
                        and route_sec_within_range.GetPointCount() > 0:
                    #print "...sections of route %s within range..." %\
                    #    route.GetField(0)    
                    add_nearest_point_on_route_as_stop(
                        route_sec_within_range,
                        stops_lyr, stops_multipoint,
                        mways_buffer_geom_this_mode, 
                        route_geom_transform_this_mode,
                        route_geom, other_s_geom, other_s_buf, 
                        stop_typ_name,
                        isect_nw_def.stop_min_dist)
                elif route_sec_within_range.GetGeometryCount() > 0:
                    # multiple polylines. Operate on each.
                    #print "...sections of route %s within range..." %\
                    #    route.GetField(0)    
                    for line in route_sec_within_range:
                        add_nearest_point_on_route_as_stop(line,
                            stops_lyr, stops_multipoint,
                            mways_buffer_geom_this_mode, 
                            route_geom_transform_this_mode,
                            route_geom, other_s_geom, other_s_buf,
                            stop_typ_name,
                            isect_nw_def.stop_min_dist)
            input_routes_lyr.ResetReading()
        tfer_nw_stop_shp.Destroy()
        print "...finished adding tfer stops for this shapefile "\
            "(with type %s)" % (stop_typ_name)
    return

def add_filler_stops(stops_lyr, input_routes_lyr, mways_buffer_geom,
        route_geom_transform, filler_dist, filler_stop_type, stops_multipoint):
    """Note: if motorways_lyr is None, it will be ignored. Otherwise it will
    be used to check and ignore adding filler stops on motorways."""    
    print "\nAdding Filler stops at max dist %.1fm:" % filler_dist
    src_srs = input_routes_lyr.GetSpatialRef()
    
    for ii, route in enumerate(input_routes_lyr):
        rname = route.GetField(0)
        route_geom = route.GetGeometryRef()
        route_length_total = route_geom.Length()
        print "Adding Filler stops for route %s (%.1fm length)" % \
            (rname, route_length_total)
        # First, get the stops of interest along route, we need to 'walk'
        route_buffer = route_geom.Buffer(
            route_geom_ops.STOP_ON_ROUTE_CHECK_DIST)
        stops_near_route = stops_multipoint.Intersection(route_buffer)
        # In cases of just one point, this will return a Point, rather than
        # Multipoint. So need to convert for latter parts of alg.
        if stops_near_route.GetGeometryName() == "POINT":
            assert stops_near_route.GetPointCount() == 1
            near_route_multipoint = ogr.Geometry(ogr.wkbMultiPoint)
            near_route_multipoint.AddGeometry(stops_near_route)
            stops_near_route.Destroy()
            stops_near_route = near_route_multipoint
        rem_stop_is = range(stops_near_route.GetGeometryCount())
        # Now walk the route, adding fillers when needed
        start_coord = route_geom.GetPoint(0)
        current_loc = start_coord
        end_coord = route_geom.GetPoint(route_geom.GetPointCount()-1)
        end_vertex = ogr.Geometry(ogr.wkbPoint)
        end_vertex.AddPoint(*end_coord)

        route_length_processed = 0
        line_remains = True
        stops_found = 0
        filler_stops_added = 0
        filler_stops_skipped_on_motorways = 0
        last_stop_i_along_route = None
        next_stop_i_along_route = None
        while line_remains is True:
            next_stop_on_route_isect, stop_ii, dist_to_next = \
                route_geom_ops.get_next_stop_and_dist(route_geom, current_loc,
                    stops_near_route, rem_stop_is)
            if next_stop_on_route_isect is not None:
                rem_stop_is.remove(stop_ii)
                stops_found += 1
                next_stop_i_along_route = stops_found-1
            filler_incs = int(math.floor(dist_to_next / filler_dist))
            if filler_incs > 0:
                walk_dist_to_filler = dist_to_next / float(filler_incs+1)
                #print "..adding %03d filler stops between stops %02s and "\
                #    "%02s (route section length %.1fm, filler dist %.1fm)" %\
                #    (filler_incs, last_stop_i_along_route, \
                #     next_stop_i_along_route, dist_to_next, \
                #     walk_dist_to_filler)
                for ii in range(1, filler_incs+1):
                    current_loc = route_geom_ops.move_dist_along_route(
                        route_geom, current_loc, walk_dist_to_filler)
                    filler_geom = ogr.Geometry(ogr.wkbPoint)
                    filler_geom.AddPoint(*current_loc)
                    if mways_buffer_geom:
                        if motorway_calcs.stop_on_motorway(filler_geom,
                                route_geom, mways_buffer_geom,
                                route_geom_transform):
                            filler_stops_skipped_on_motorways += 1
                            #print "..mway skip filler stop at %.1f, %.1f" %\
                            #    (current_loc[0], current_loc[1])
                            continue
                    #print "..adding filler stop at %.1f, %.1f" %\
                    #    (current_loc[0], current_loc[1])
                    stop_id = tp_model.add_stop(stops_lyr, stops_multipoint,
                        filler_stop_type, filler_geom, src_srs)
                    filler_stops_added += 1    
            # Walk ahead.
            current_loc = next_stop_on_route_isect
            last_stop_i_along_route = next_stop_i_along_route
            route_length_processed += dist_to_next
            route_remaining = route_length_total - route_length_processed
            if (next_stop_on_route_isect is None or len(rem_stop_is) == 0) \
                and (route_remaining < route_geom_ops.SAME_POINT):
                # We've added fillers to the last section, so all done.
                assert len(rem_stop_is) == 0
                line_remains = False
                break
        if stops_found < 1:
            print "*WARNING*: while adding filler stops to route '%s', only "\
                "found %d existing stops. Normally expect to process at "\
                "least 1 (a start-end stop for a looped route.)"\
                % (rname, stops_found)
        route_buffer.Destroy()
        stops_near_route.Destroy()
        end_vertex.Destroy()
        print "..added %d filler stops between the %d existing stops "\
            "detected for this route." % (filler_stops_added, stops_found)
        if mways_buffer_geom:
            print "..(%d potential filler stops skipped due to detected as "\
                "being on motorways.)" % (filler_stops_skipped_on_motorways)
    input_routes_lyr.ResetReading()
    return

# Required format of the transfer network CSV file:
# 0: Path to network shape file
# 1: radial distance (m) from each stop to use for testing whether
# stops need to be added to the new network you're creating.
# I.E. 350 m means "make sure that within 350m of each stop on this
# existing network, stops are added to the new network.
# 2: Distance to check if there's an existing stop already added (m) -
# and if so, avoid.
# 3: Textual Name in the resulting shapefile you want to enter for
# 4: string stating if these transfer stops should be ignored if transfer
#   point is on a motorway

def read_transfer_network_info(transfer_network_csv_fname):
    csv_file = open(transfer_network_csv_fname, 'r')
    if csv_file is None:
        print "Error, transfer network CSV file given, %s , failed to open." \
            % (csv_file_name)
        sys.exit(1)
    reader = csv.reader(csv_file, delimiter=',', quotechar="'") 
    # skip headings
    reader.next()
    transfer_networks_def = []
    for ii, row in enumerate(reader):
        nw_def_entry = row
        tf_nw_def = TransferNetworkDef(nw_def_entry[0], int(nw_def_entry[1]),
            int(nw_def_entry[2]), nw_def_entry[3],
            parser_utils.str2bool(nw_def_entry[4]))
        transfer_networks_def.append(tf_nw_def) 
    return transfer_networks_def

def create_stops(input_routes_lyr, motorways_lyr, stops_shp_file_name,
        transfer_networks_def, filler_dist):
    stops_shp_file, stops_lyr = tp_model.create_stops_shp_file(
        stops_shp_file_name, delete_existing=DELETE_EXISTING)
    # We'll use this multipoint for calculating distances more easily
    # Actually populating this is handled in tp_model addStop().
    stops_multipoint = ogr.Geometry(ogr.wkbMultiPoint)

    mways_buffer_geom = None
    route_geom_transform = None
    if motorways_lyr:
        src_srs = input_routes_lyr.GetSpatialRef()
        target_srs = osr.SpatialReference()
        target_srs.ImportFromEPSG(route_geom_ops.COMPARISON_EPSG)
        route_geom_transform = osr.CoordinateTransformation(src_srs, target_srs)
        mways_buffer_geom = motorway_calcs.create_motorways_buffer(
            motorways_lyr, target_srs)
    add_route_start_end_stops(stops_lyr, input_routes_lyr, stops_multipoint)
    add_self_transfer_stops(stops_lyr, input_routes_lyr,
        mways_buffer_geom, route_geom_transform, stops_multipoint)
    add_other_network_transfer_stops(stops_lyr, input_routes_lyr,
        mways_buffer_geom, route_geom_transform,
        transfer_networks_def, stops_multipoint)
    add_filler_stops(stops_lyr, input_routes_lyr, mways_buffer_geom,
        route_geom_transform, filler_dist, FILLER_NAME, stops_multipoint)
    stops_shp_file.Destroy()
    return

def main():
    allowedServs = ', '.join(sorted(["'%s'" % key for key in \
        m_t_info.settings.keys()]))
    parser = OptionParser()
    parser.add_option('--routes', dest='inputroutes',
        help='Shapefile of line routes.')
    parser.add_option('--stops', dest='outputstops',
        help='Shapefile of line stops to create.')
    parser.add_option('--transfers', dest='inputtransfers',
        help='CSV File specifying transfer network info.')
    parser.add_option('--filler_dist', dest='filler_dist',
        help="Max distance used (m) in calc. when to add filler stops.")
    parser.add_option('--skip_stops_on_mways', dest='skip_stops_on_mways',
        help="Skip creation of new stops when on motorways?")
    parser.add_option('--motorways', dest='motorways', help="Shapefile of "\
        "motorway sections (exported from OpenStreetMap) - needed if you "\
        "want to skip filler stop creation on motorways.")
    parser.set_defaults(filler_dist=str(DEFAULT_FILLER_DIST))
    parser.set_defaults(skip_stops_on_mways="true")
    (options, args) = parser.parse_args()

    if options.inputroutes is None:
        parser.print_help()
        parser.error("No routes shapefile path given.")
    if options.outputstops is None:
        parser.print_help()
        parser.error("No stops shapefile path given.")
    if options.inputtransfers is None:
        parser.print_help()
        parser.error("No transfers CSV file path given.")

    try:
        filler_dist = float(options.filler_dist)
    except ValueError:
        parser.print_help()
        parser.error("Invalid filler_dist option specified (%s). filler_dist "\
            "must be a float between 0 and %d meters." % \
            (options.filler_dist, MAX_FILLER_DIST))
    if filler_dist < 0 or filler_dist > MAX_FILLER_DIST:
        parser.print_help()
        parser.error("Invalid filler_dist option specified (%s). filler_dist "\
            "must be between 0 and %d meters." % \
            (options.filler_dist, MAX_FILLER_DIST))

    mways_shp = None
    mways_lyr = None
    skip_stops_on_mways = parser_utils.str2bool(options.skip_stops_on_mways)
    if skip_stops_on_mways:
        if options.motorways is None:
            print "Warning: skip_stops_on_mways option enabled, but no "\
                "motorway sections shape file provided. So ignoring "\
                "this option."
            pass
        else:
            mways_fname = os.path.expanduser(options.motorways)
            mways_shp = osgeo.ogr.Open(mways_fname, 0)
            if mways_shp is None:
                print "Error, motorway sections shape file given, %s, "\
                    "failed to open." % (options.motorways)
                sys.exit(1)
            mways_lyr = mways_shp.GetLayer(0)

    routes_fname = os.path.expanduser(options.inputroutes)
    input_routes_shp = osgeo.ogr.Open(routes_fname, 0)
    if input_routes_shp is None:
        print "Error, input routes shape file given, %s , failed to open." \
            % (options.inputroutes)
        sys.exit(1)
    input_routes_lyr = input_routes_shp.GetLayer(0)    

    # The other shape files we're going to create :- so don't check
    #  existence, just read names.
    stops_fname = os.path.expanduser(options.outputstops)

    tfer_network_csv_fname = os.path.expanduser(options.inputtransfers)
    tfer_networks_def = read_transfer_network_info(tfer_network_csv_fname)
    print "Transfer network defs read from file %s were:" % \
        (tfer_network_csv_fname)
    for tfer_nw_def in tfer_networks_def:
        print "File '%s': range %d, min dist %d, output type '%s', "\
            "skip_mways: %s" % \
            (tfer_nw_def.shp_fname, tfer_nw_def.tfer_range, \
             tfer_nw_def.stop_min_dist, tfer_nw_def.stop_typ_name,\
             tfer_nw_def.skip_on_mway)

    create_stops(input_routes_lyr, mways_lyr, stops_fname,
        tfer_networks_def, filler_dist)
    # Cleanup
    input_routes_shp.Destroy()
    if mways_shp:
        mways_shp.Destroy()
    return

if __name__ == "__main__":
    main()
