#!/usr/bin/env python2
import os
import os.path
import re
import sys
import inspect
import operator
from optparse import OptionParser
import math

import osgeo.ogr
from osgeo import ogr, osr

import project_onto_line as lineargeom
import topology_shapefile_data_model as tp_model

class TransferNetworkDef:
    def __init__(self, shp_fname, tfer_range, stop_min_dist, stop_typ_name):
        # 0: Path to network shape file
        # 1: radial distance (m) from each stop to use for testing whether
        # stops need to be added to the new network you're creating.
        # I.E. 350 m means "make sure that within 350m of each stop on this
        # existing network, stops are added to the new network.
        # 2: Distance to check if there's an existing stop already added (m) -
        # and if so, avoid.
        # 3: Textual Name in the resulting shapefile you want to enter for
        self.shp_fname = shp_fname
        self.tfer_range = tfer_range
        self.stop_min_dist = stop_min_dist
        self.stop_typ_name = stop_typ_name

EPSG_STOPS_FILE = 4326
DELETE_EXISTING = True

ROUTE_START_END_NAME = "ROUTE_START_END"
TRANSFER_SELF_NAME = "TRANSFER_SELF"
FILLER_NAME = "FILLERS"

FILLER_MAX_DIST = 500

BUFFER_DIST_SELF_ROUTE_TRANSFER = 30.0
CROSSING_ANGLE_FACTOR = 0.01
MIN_DIST_TO_PLACE_ISECT_STOPS = 80.0

def create_stops_shp_file(stops_shp_file_name):
    # OGR doesn't like relative paths
    abs_stops_shp_file_name = os.path.abspath(stops_shp_file_name)
    print "Creating new stops shape file at path %s:" % abs_stops_shp_file_name
    if os.path.exists(abs_stops_shp_file_name):
        print "File exists at that name."
        if DELETE_EXISTING == True:
            print "deleting so we can overwrite."
            os.unlink(abs_stops_shp_file_name)
        else:
            print "... so exiting."
            sys.exit(1)
    driver = ogr.GetDriverByName("ESRI Shapefile")
    stops_shp_file = driver.CreateDataSource(abs_stops_shp_file_name)
    if stops_shp_file is None:
        print "Error trying to create new shapefile at path %s - exiting." %\
            abs_stops_shp_file_name
        sys.exit(1)
    srs = osr.SpatialReference()
    srs.ImportFromEPSG(EPSG_STOPS_FILE)
    layer = stops_shp_file.CreateLayer("stops", srs, ogr.wkbPoint)
    layer.CreateField(ogr.FieldDefn("gid", ogr.OFTInteger))
    layer.CreateField(ogr.FieldDefn("id", ogr.OFTInteger))
    field = ogr.FieldDefn("typ", ogr.OFTString)
    field.SetWidth(24)
    layer.CreateField(field)
    print "... done."
    return stops_shp_file, layer

def add_stop(stops_lyr, stops_multipoint, stop_type, stop_geom, src_srs):
    pt_id = stops_multipoint.GetGeometryCount()
    stops_multipoint.AddGeometry(stop_geom)
    #Create stop point, with needed fields etc.
    stop_feat = ogr.Feature(stops_lyr.GetLayerDefn())
    #Need to re-project geometry into target SRS (do this now,
    # after we've added to multipoint, which should be in same SRS as
    # above).
    target_srs = stops_lyr.GetSpatialRef()
    assert(src_srs != None)
    assert(target_srs != None)
    transform = osr.CoordinateTransformation(src_srs, target_srs)
    stop_geom2 = stop_geom.Clone()
    stop_geom2.Transform(transform)
    stop_feat.SetGeometry(stop_geom2)
    stop_feat.SetField("gid", pt_id)
    stop_feat.SetField("id", pt_id)
    stop_feat.SetField("typ", stop_type)
    stops_lyr.CreateFeature(stop_feat)
    stop_feat.Destroy()
    return pt_id

def get_min_dist_from_existing_stops(pt_geom, stops_multipoint):
    if stops_multipoint.GetGeometryCount() >= 1:
        dist_from_existing = pt_geom.Distance(stops_multipoint)
    else:
        dist_from_existing = sys.maxint
    return dist_from_existing    

# TODO: delete this? Not recommended for use, the "pre-buffer" approach had
# problems with not having relevant points in range.
def get_min_dist_other_stop_also_on_route(search_point_geom,
        route_sec_within_range, stops_multipoint, within_range_buffer):
    stops_multipoint_in_buffer = stops_multipoint.Intersection(
        within_range_buffer)
    min_dist_also_on_line = sys.maxint
    if stops_multipoint_in_buffer.GetGeometryCount() > 0:
        # A multipoint - iterate through all
        for stop_geom in stops_multipoint_in_buffer:
            dist_to_route = stop_geom.Distance(route_sec_within_range)
            if  dist_to_route < lineargeom.VERY_NEAR_LINE:
                dist_to_new_pt = stop_geom.Distance(search_point_geom)
                if dist_to_new_pt < min_dist_also_on_line:
                    min_dist_also_on_line = dist_to_new_pt
    elif stops_multipoint_in_buffer.GetPointCount() == 1:   
        # A single point - just check it
        stop_geom = stops_multipoint_in_buffer
        dist_to_route = stop_geom.Distance(route_sec_within_range) 
        if dist_to_route < lineargeom.VERY_NEAR_LINE:
            dist_to_new_pt = stop_geom.Distance(search_point_geom)
            if dist_to_new_pt < min_dist_also_on_line:
                min_dist_also_on_line = dist_to_new_pt
    else:
        # no points.
        assert stops_multipoint_in_buffer.GetGeometryName() == \
            "GEOMETRYCOLLECTION"
        assert stops_multipoint_in_buffer.GetPointCount() == 0
        pass
    return min_dist_also_on_line

def get_stops_already_on_route_within_dist(new_pt, route_geom,
        stops_multipoint, test_dist):
    buf_near_pt = new_pt.Buffer(test_dist * 1.05)
    route_geom_in_buf = route_geom.Intersection(buf_near_pt)
    stops_on_route_within_dist = []
    stops_multipoint_in_buffer = stops_multipoint.Intersection(buf_near_pt)
    if stops_multipoint_in_buffer.GetGeometryCount() > 0:
        # A multipoint - iterate through each.
        for stop_geom in stops_multipoint_in_buffer:
            if stop_geom.Distance(route_geom_in_buf) < lineargeom.VERY_NEAR_LINE:
                dist_to_new_pt = stop_geom.Distance(new_pt)
                if dist_to_new_pt < test_dist:
                    stops_on_route_within_dist.append((stop_geom.Clone(),
                        dist_to_new_pt))
    elif stops_multipoint_in_buffer.GetPointCount() == 1:   
        # A single point - check it
        stop_geom = stops_multipoint_in_buffer
        if stop_geom.Distance(route_geom_in_buf) < lineargeom.VERY_NEAR_LINE:
            dist_to_new_pt = stop_geom.Distance(new_pt)
            if dist_to_new_pt < test_dist:
                stops_on_route_within_dist.append((stop_geom.Clone(),
                    dist_to_new_pt))
    else:
        # No points.
        assert stops_multipoint_in_buffer.GetGeometryName() == \
            "GEOMETRYCOLLECTION"
        assert stops_multipoint_in_buffer.GetPointCount() == 0
        pass
    stops_on_route_within_dist.sort(key=operator.itemgetter(1))
    return stops_on_route_within_dist

def add_route_start_end_stops(stops_lyr, input_routes_lyr, stops_multipoint):
    src_srs = input_routes_lyr.GetSpatialRef()
    print "Adding route start and end stops."
    for ii, route in enumerate(input_routes_lyr):
        route_geom = route.GetGeometryRef()
        print "For route '%s':" % route.GetField(0)
        start_pt = ogr.Geometry(ogr.wkbPoint)
        start_pt.AddPoint(*route_geom.GetPoint(0))
        end_pt = ogr.Geometry(ogr.wkbPoint)
        end_pt.AddPoint(*route_geom.GetPoint(route_geom.GetPointCount()-1))
        start_end_pts = [start_pt, end_pt]
        for ii, pt in enumerate(start_end_pts):
            dist_from_existing = get_min_dist_from_existing_stops(pt,
                stops_multipoint)
            #print "(Calc dist from existing for start/end pt %d as %.1f)" %\
            #    (ii, dist_from_existing)
            if dist_from_existing < lineargeom.SAME_POINT:
                #print "...not adding stop at stop at route start/end as "\
                #    "there is a stop here already."
                pass
            else:
                stop_id = add_stop(stops_lyr, stops_multipoint, ROUTE_START_END_NAME,
                    pt, src_srs)
                #print "...Adding stop at route start/end"
    input_routes_lyr.ResetReading()

def first_good_intersect_point(line_geom, other_line_geom,
        start_from_end=False):
    # Multi-pronged approach:
    # Best case is that one of the early points, within BUFFER_DIST * 3,
    #  is very near line.
    # Else, just return the closest within buffer_dist *3
    line_geom_2 = line_geom.Clone()
    line_geom_2.Segmentize(lineargeom.VERY_NEAR_LINE/2.0)
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
        if dist_from_other < lineargeom.VERY_NEAR_LINE:
            return pt_coords
    return None

def get_nearest_point_on_route_within_buf_basic(search_pt_geom, route_geom,
        route_geom_within_range, seg_size):
    # Using the segmentise algorithm below is neither super-accurate
    # nor super-quick. But we're working with just a small section of
    # line, and we don't care about closest point to sub-meter precision,
    # so this should be ok.
    route_geom_srs = route_geom.GetSpatialReference()
    route_sec_within_range_2 = route_geom_within_range.Clone()
    route_sec_within_range_2.Segmentize(seg_size)
    min_dist = sys.maxint
    closest_point_geom = None
    route_sec_segmented_pts = route_sec_within_range_2.GetPoints()
    for ii, vertex in enumerate(route_sec_segmented_pts):
        new_pt = ogr.Geometry(ogr.wkbPoint)
        new_pt.AddPoint(*vertex)
        dist_to_search_stop = new_pt.Distance(search_pt_geom)
        if dist_to_search_stop < min_dist:
            min_dist = dist_to_search_stop
            closest_point_geom = new_pt
    return closest_point_geom

def get_nearest_point_on_route_within_buf_fast(search_pt_geom, route_geom,
        route_geom_within_range):
    near_coords = lineargeom.nearest_point_on_polyline_to_point(
        route_geom_within_range, search_pt_geom.GetPoints()[0])
    closest_point_geom = ogr.Geometry(ogr.wkbPoint)
    closest_point_geom.AddPoint(*near_coords)
    return closest_point_geom

def add_key_intersection_points_as_stops(isect_line, stops_lyr,
        stops_multipoint, route_geom, other_route_geom):
    src_srs = route_geom.GetSpatialReference()
    isect_point_cnt = isect_line.GetPointCount()
    if isect_point_cnt > 0:
        isect_pts_interest = []
        if isect_line.Length() < \
            (2 * BUFFER_DIST_SELF_ROUTE_TRANSFER) * CROSSING_ANGLE_FACTOR:
            # This is a short crossover intersection. (The angle factor is
            # to do with routes that cross at an angle rather than
            # perpendicular.
            # In this case, just use centroid of where the orig route crosses
            # the buffer
            isect_pts_interest = [isect_line.Centroid().GetPoints()[0]]
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
        for pt_coords in isect_pts_interest:
            print "Detected isect_self point at (%f, %f)" % pt_coords
            new_pt = ogr.Geometry(ogr.wkbPoint)
            new_pt.AddPoint(*pt_coords)

            min_dist_also_on_both_routes = sys.maxint
            min_dist_also_on_route = get_stops_already_on_route_within_dist(
                new_pt, route_geom, stops_multipoint, 
                MIN_DIST_TO_PLACE_ISECT_STOPS)
            for exist_stop_geom, dist_new in min_dist_also_on_route: 
                dist_other = exist_stop_geom.Distance(other_route_geom)
                if dist_other < BUFFER_DIST_SELF_ROUTE_TRANSFER:
                    # Use the buffer tfer dist, not
                    # DIST_FOR_MATCHING_STOPS_ON_ROUTES, since given other
                    # algorithm improvements, we're confident transfer
                    # stops will be added to other routes within this range.
                    min_dist_also_on_both_routes = dist_new
                    break
                else:
                    print "...(A close point on route wasn't within %.1fm "\
                        "of other route - %.1fm to new, %.1fm to other)" \
                        % (BUFFER_DIST_SELF_ROUTE_TRANSFER, dist_new, \
                            dist_other)
            print "(Dist from existing on route = %.1f)" % \
                min_dist_also_on_both_routes
            if min_dist_also_on_both_routes < MIN_DIST_TO_PLACE_ISECT_STOPS:
                print "...but there is already a stop within "\
                "%.1fm on this route and other route, so skipping." \
                    % min_dist_also_on_both_routes
            else:    
                stop_id = add_stop(stops_lyr, stops_multipoint,
                    TRANSFER_SELF_NAME, new_pt, src_srs)
                print "...and adding a stop here: B%d." % stop_id
                # A final check. Need to make sure stops get placed 
                # where _both_ bus lines will find them in segmenting
                # algorithm later.
                dist_self = new_pt.Distance(route_geom)
                dist_other = new_pt.Distance(other_route_geom)    
                assert (dist_self < lineargeom.DIST_FOR_MATCHING_STOPS_ON_ROUTES)
                if (dist_other > lineargeom.DIST_FOR_MATCHING_STOPS_ON_ROUTES):
                    # We need to add a stop to nearest point on other route-
                    # that will get picked up in segmenting algorithm.
                    print "...also adding a stop on other route, as dist "\
                        "%.1f is > %.1f" % (dist_other, \
                        lineargeom.DIST_FOR_MATCHING_STOPS_ON_ROUTES)
                    new_pt_buffer = new_pt.Buffer(
                        BUFFER_DIST_SELF_ROUTE_TRANSFER*2)
                    other_route_in_range = other_route_geom.Intersection(
                        new_pt_buffer)
                    new_pt_other = get_nearest_point_on_route_within_buf_fast(
                        new_pt, other_route_geom, other_route_in_range)
                    assert new_pt_other is not None
                    stop_id = add_stop(stops_lyr, stops_multipoint,
                        TRANSFER_SELF_NAME, new_pt_other, src_srs)
                    print "...Stop ID was B%d" % stop_id  
    return            

def add_self_transfer_stops(stops_lyr, input_routes_lyr, stops_multipoint):
    for ii, route in enumerate(input_routes_lyr):
        route_geom = route.GetGeometryRef()
        for jj in range(ii+1, input_routes_lyr.GetFeatureCount()):
            other_route = input_routes_lyr.GetFeature(jj)
            print "Testing for intersection pts on routes '%s' and '%s' "\
                % (route.GetField(0), other_route.GetField(0))
            #if route.GetField(0) == "R16" and other_route.GetField(0) == "R76":
            #    import pdb
            #    pdb.set_trace()
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
                    add_key_intersection_points_as_stops(route_isect, stops_lyr,
                        stops_multipoint, route_geom, other_route_geom)
            else:
                for line in route_isect:
                    add_key_intersection_points_as_stops(line, stops_lyr,
                        stops_multipoint, route_geom, other_route_geom)
    input_routes_lyr.ResetReading()
    return
 
def add_nearest_point_on_route_as_stop(route_sec_within_range, stops_lyr,
        stops_multipoint, route_geom, other_s_geom, other_s_buf,
        stop_typ_name, stop_min_dist):
    route_geom_srs = route_geom.GetSpatialReference()
    closest_point_geom = get_nearest_point_on_route_within_buf_fast(
        other_s_geom, route_geom, route_sec_within_range)
    # Check results of above, to be sure
    assert closest_point_geom is not None        
    dist_to_route = closest_point_geom.Distance(route_sec_within_range)
    assert dist_to_route < lineargeom.VERY_NEAR_LINE
    print "...found closest point at %.2f, %.2f" % \
        closest_point_geom.GetPoints()[0][:2]

    # Now, need to check if there are other stops already added on this
    # line, within min dist to place stops.
    min_dist_also_on_route = get_stops_already_on_route_within_dist(
        closest_point_geom, route_geom, stops_multipoint, 
        stop_min_dist)
    if min_dist_also_on_route == []:
        min_dist_also_on_line = sys.maxint
        print "...(calculated no other stops within dist.)"
    else:
        min_dist_also_on_line = min_dist_also_on_route[0][1]
        print "...(calculated min dist to other stop on route as %.2f)" % \
            min_dist_also_on_line    

    if min_dist_also_on_line >= stop_min_dist:
        stop_id = add_stop(stops_lyr, stops_multipoint, stop_typ_name,
            closest_point_geom, route_geom_srs)
        print "...added stop B%d." % stop_id
    else:
        print "...not adding stop, since is < %.1fm (min dist this mode) "\
            "to existing stop on this line." % stop_min_dist
        pass
    return

def add_other_network_transfer_stops(stops_lyr, input_routes_lyr,
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
        for ii, other_stop in enumerate(tfer_nw_stop_lyr):
            print "Checking for routes within %.1fm of stop %d(%s)" % \
                (isect_nw_def.tfer_range, ii, other_stop.GetField("Name"))
            other_s_geom = other_stop.GetGeometryRef()
            # Now need to transform into this coord system.
            transform = osr.CoordinateTransformation(src_srs, target_srs)
            other_s_geom.Transform(transform)
            other_s_buf = other_s_geom.Buffer(isect_nw_def.tfer_range)
            for route in input_routes_lyr:
                route_geom = route.GetGeometryRef()
                route_sec_within_range = route_geom.Intersection(
                    other_s_buf)
                if other_stop.GetField("Name") == "HELL Port Junction/79 Whiteman St"\
                        and route.GetField(0) == "R61":
                    driver = ogr.GetDriverByName("ESRI Shapefile")
                    if os.path.exists("segs.shp"):
                        os.unlink("segs.shp")
                    segs_shp_file = driver.CreateDataSource("segs.shp")
                    layer = segs_shp_file.CreateLayer("segs", 
                        input_routes_lyr.GetSpatialRef(),
                        ogr.wkbLineString)
                    field = ogr.FieldDefn("station", ogr.OFTString)
                    field.SetWidth(60)
                    layer.CreateField(field)
                    field = ogr.FieldDefn("route", ogr.OFTString)
                    field.SetWidth(24)
                    layer.CreateField(field)
                    feat = ogr.Feature(stops_lyr.GetLayerDefn())
                    feat.SetGeometry(route_sec_within_range)
                    feat.SetField("station",
                        other_stop.GetField("Name"))
                    feat.SetField("route", route.GetField(0))
                    layer.CreateFeature(feat)
                    feat.Destroy()
                    import pdb
                    pdb.set_trace()

                if route_sec_within_range.GetGeometryCount() == 0 \
                        and route_sec_within_range.GetPointCount() > 0:
                    # We think its a polyline. Operate on directly.
                    print "...sections of route %s within range..." %\
                        route.GetField(0)    
                    add_nearest_point_on_route_as_stop(
                        route_sec_within_range,
                        stops_lyr, stops_multipoint, route_geom,
                        other_s_geom, other_s_buf, stop_typ_name,
                        isect_nw_def.stop_min_dist)
                elif route_sec_within_range.GetGeometryCount() > 0:
                    # We think there's multiple polylines. Operate on each.
                    print "...sections of route %s within range..." %\
                        route.GetField(0)    
                    for line in route_sec_within_range:
                        add_nearest_point_on_route_as_stop(line,
                            stops_lyr, stops_multipoint, route_geom,
                            other_s_geom, other_s_buf, stop_typ_name,
                            isect_nw_def.stop_min_dist)
            input_routes_lyr.ResetReading()
        tfer_nw_stop_shp.Destroy()    
    return

def add_filler_stops(stops_lyr, filler_dist, filler_stop_type, stops_multipoint):
    print "\nAdding Filler stops at max dist %.1fm:" % filler_dist
    for ii, route in enumerate(input_routes_lyr):
        print "Adding Filler stops for route %s" % route.GetField(0)
        route_geom = route.GetGeometryRef()
        src_srs = route_geom.GetSpatialReference()
        # First, get the stops of interest along route, we need to 'walk'
        route_buffer = route_geom.Buffer(
            lineargeom.DIST_FOR_MATCHING_STOPS_ON_ROUTES)
        stops_near_route = stops_multipoint.Intersection(route_buffer)
        rem_stop_is = range(stops_near_route.GetGeometryCount())
        # Now walk the route, adding fillers when needed
        start_coord = route_geom.GetPoint(0)
        current_loc = start_coord
        end_coord = route_geom.GetPoint(route_geom.GetPointCount()-1)
        end_point = ogr.Geometry(ogr.wkbPoint)
        end_point.AddPoint(*end_coord)

        line_remains = True
        stops_found = 0
        last_stop_i_along_route = None
        next_stop_i_along_route = None
        while line_remains is True:
            next_stop_on_route_isect, stop_ii, dist_to_next = \
                lineargeom.get_next_stop_and_dist(route_geom, current_loc,
                    stops_near_route, rem_stop_is)
            if next_stop_on_route_isect is not None:
                rem_stop_is.remove(stop_ii)
                stops_found += 1
                next_stop_i_along_route = stops_found-1
            filler_incs = int(math.floor(dist_to_next / filler_dist))
            if filler_incs > 0:
                walk_dist_to_filler = dist_to_next / float(filler_incs+1)
                print "..adding %03d filler stops between stops %02s and "\
                    "%02s (route length %.1fm, filler dist %.1fm)" %\
                    (filler_incs, last_stop_i_along_route, \
                     next_stop_i_along_route, dist_to_next, \
                     walk_dist_to_filler)
                for ii in range(1, filler_incs+1):
                    current_loc = lineargeom.move_dist_along_route(route_geom,
                        current_loc, walk_dist_to_filler)
                    filler_geom = ogr.Geometry(ogr.wkbPoint)
                    filler_geom.AddPoint(*current_loc)
                    #print "..adding filler stop at %.1f, %.1f" %\
                    #    (current_loc[0], current_loc[1])
                    stop_id = add_stop(stops_lyr, stops_multipoint,
                        filler_stop_type, filler_geom, src_srs)
            # For safety, we're going to compute distance from end pt as
            #  a stopping condition check as well.
            curr_loc_pt = ogr.Geometry(ogr.wkbPoint)
            curr_loc_pt.AddPoint(*current_loc)
            dist_to_end = curr_loc_pt.Distance(end_point)
            curr_loc_pt.Destroy()
            if next_stop_on_route_isect is None or \
                    dist_to_end < lineargeom.SAME_POINT:
                # We've added fillers to the last section, so all done.
                line_remains = False
                break
            # Walk ahead.
            current_loc = next_stop_on_route_isect
            last_stop_i_along_route = next_stop_i_along_route

def create_stops(input_routes_lyr, stops_shp_file_name,
        transfer_networks):
    stops_shp_file, stops_lyr = create_stops_shp_file(stops_shp_file_name)
    # We'll use this multipoint for calculating distances more easily
    stops_multipoint = ogr.Geometry(ogr.wkbMultiPoint)
    add_route_start_end_stops(stops_lyr, input_routes_lyr, stops_multipoint)
    add_self_transfer_stops(stops_lyr, input_routes_lyr, stops_multipoint)
    add_other_network_transfer_stops(stops_lyr, input_routes_lyr,
        transfer_networks_def, stops_multipoint)
    add_filler_stops(stops_lyr, FILLER_MAX_DIST, FILLER_NAME, stops_multipoint)
    stops_shp_file.Destroy()
    return

if __name__ == "__main__":
    input_routes_fname = './network_topology_testing/network-self-snapped-reworked-patextend-201405.shp'
    stops_shp_file_name = './network_topology_testing/network-self-snapped-reworked-patextend-201405-stops-inc-fillers.shp'
    segments_shp_file_name = './network_topology_testing/network-self-snapped-reworked-patextend-201405-segments.shp'
    fname = os.path.expanduser(input_routes_fname)
    input_routes_shp = osgeo.ogr.Open(fname, 0)
    if input_routes_shp is None:
        print "Error, input routes shape file given, %s , failed to open." \
            % (input_routes_fname)
        sys.exit(1)
    input_routes_lyr = input_routes_shp.GetLayer(0)    

    transfer_networks_test = [
        ['./network_topology_testing/train_stop.shp', 350, 50, "TRANSFER_TRAIN"],
        # ['motorway_bus_stops.shp', 350m, 50m, "TRANSFER_MWAY_BUS"],
        ['./network_topology_testing/tram_stop.shp', 300, 180, "TRANSFER_TRAM"],
        ]

    transfer_networks_def = []
    for nw_def_entry in transfer_networks_test:
        tf_nw_def = TransferNetworkDef(nw_def_entry[0], nw_def_entry[1],
            nw_def_entry[2], nw_def_entry[3])
        transfer_networks_def.append(tf_nw_def)    

    create_stops(input_routes_lyr, stops_shp_file_name,
        transfer_networks_def)

    stops_shp = osgeo.ogr.Open(stops_shp_file_name, 0)
    if stops_shp is None:
        print "Error, newly created stops shape file, %s , failed to open." \
            % (stops_shp_file_name)
        sys.exit(1)
    #stops_lyr = stops_shp.GetLayer(0)   
    #create_segments(input_routes_lyr, stops_lyr,
    #    segments_shp_file_name)
    input_routes_shp.Destroy()
    stops_shp.Destroy()    