import math
import sys
import inspect
import operator

import osgeo.ogr
from osgeo import ogr, osr

import lineargeom

# Chose EPSG:28355 ("GDA94 / MGA zone 55") as an appropriate projected
    # spatial ref. system, in meters, for the Melbourne region.
    #  (see http://spatialreference.org/ref/epsg/gda94-mga-zone-55/)
COMPARISON_EPSG = 28355

# These values are of course dependent on comparison EPSG above - needs to be
# in (m).
STOP_ON_ROUTE_CHECK_DIST = 5.0 
VERY_NEAR_ROUTE = 1.0
SAME_POINT = 1.0

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
            if  dist_to_route < VERY_NEAR_ROUTE:
                dist_to_new_pt = stop_geom.Distance(search_point_geom)
                if dist_to_new_pt < min_dist_also_on_line:
                    min_dist_also_on_line = dist_to_new_pt
    elif stops_multipoint_in_buffer.GetPointCount() == 1:   
        # A single point - just check it
        stop_geom = stops_multipoint_in_buffer
        dist_to_route = stop_geom.Distance(route_sec_within_range) 
        if dist_to_route < VERY_NEAR_ROUTE:
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
            if stop_geom.Distance(route_geom_in_buf) < VERY_NEAR_ROUTE:
                dist_to_new_pt = stop_geom.Distance(new_pt)
                if dist_to_new_pt < test_dist:
                    stops_on_route_within_dist.append((stop_geom.Clone(),
                        dist_to_new_pt))
    elif stops_multipoint_in_buffer.GetPointCount() == 1:   
        # A single point - check it
        stop_geom = stops_multipoint_in_buffer
        if stop_geom.Distance(route_geom_in_buf) < VERY_NEAR_ROUTE:
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

def get_nearest_point_on_route_within_buf(search_pt_geom, route_geom,
        route_geom_within_range):
    near_coords, near_dist = lineargeom.nearest_point_on_polyline_to_point(
        route_geom_within_range, search_pt_geom.GetPoint(0))
    closest_point_geom = ogr.Geometry(ogr.wkbPoint)
    closest_point_geom.AddPoint(*near_coords)
    return closest_point_geom

def advance_along_route_to_loc(segs_iterator, loc):
    # This first section is to skip ahead to correct segment and project
    # starting location onto line itself. So we need to create the iterator
    # outside the for statement to use in 2nd loop.
    start_stop_proj_onto_route = None
    min_dist_to_route = sys.maxint
    vertexes_passed = 0
    for seg_start, seg_end in segs_iterator:
        isect_pt, within_seg, uval = lineargeom.intersect_point_to_line(loc,
            seg_start, seg_end)
        cur_dist = lineargeom.magnitude(loc, isect_pt)
        if cur_dist < min_dist_to_route:
            # Not actually used, but save for debugging purposes
            min_dist_to_route = cur_dist
        if (cur_dist < VERY_NEAR_ROUTE) or \
                (within_seg and cur_dist < STOP_ON_ROUTE_CHECK_DIST):
            # The first clause in this loop is necessary for start and end
            # points of route possibly not quite being classed as 'within
            # a segment'
            start_stop_proj_onto_route = isect_pt
            break
        vertexes_passed += 1    
    if start_stop_proj_onto_route == None:
        func_name = inspect.stack()[0][3]
        print "Error: %s() called with a location not within "\
            "required distance (%.1fm) of route. Loc is (%s, %s). "\
            "Minimum dist to route calc was %.1fm." %\
            (func_name, STOP_ON_ROUTE_CHECK_DIST, loc[0], \
             loc[1], min_dist_to_route)
        sys.exit(1)
    return start_stop_proj_onto_route, seg_start, seg_end, vertexes_passed

def get_next_stop_and_dist(route_geom, current_loc_on_route,
        stops_multipoint_near_route, rem_stop_is, last_vertex_i=None):
    start_pt = current_loc_on_route
    linear_dist_to_next_stop = 0

    segs_iterator = lineargeom.pairs(route_geom.GetPoints())
    if last_vertex_i is None:
        # Initialise.
        last_vertex_i = 0
    else:
        assert last_vertex_i < route_geom.GetPointCount()
        # "Fast-forward" segs iterator to last known vertex
        vertex_i = 0
        while vertex_i < last_vertex_i:
            segs_iterator.next()
            vertex_i += 1
    start_stop_proj_onto_route, seg_start, seg_end, vertexes_passed = \
        advance_along_route_to_loc(segs_iterator, start_pt)
    last_vertex_i += vertexes_passed
    # Now we are going to walk thru remaining segments, and keep testing
    # remaining stops till we find one on the current segment.
    linear_dist_from_start_stop = 0
    next_stop_on_route_isect = None
    next_stop_on_route_ii = None
    # Override seg start in first loop iteration to be starting point.
    seg_start = start_stop_proj_onto_route
    try:
        while seg_end is not None:
            # We need to be a little bit careful here as multiple stops could be 
            #  within this segment. So need to try all of them, and get the
            # _closest_ to start of the segment that is on the segment.
            stop_isect_seg_nearest_start = None
            min_stop_isect_from_seg_start = sys.maxint
            min_stop_from_seg_start_ii = None
            for stop_ii in rem_stop_is:
                stop_geom = stops_multipoint_near_route.GetGeometryRef(stop_ii)
                stop_pt = stop_geom.GetPoint(0)
                isect_pt, within_seg, uval = lineargeom.intersect_point_to_line(
                    stop_pt, seg_start, seg_end)
                cur_dist = lineargeom.magnitude(stop_pt, isect_pt)
                # Pat S, 13/6/2014: simplified this If statement to not also
                # test 'within_seg' as this was causing probs for boundary
                # cases. Thus now, even stops slightly beyond the start and
                # end of route will match, as long as within range. But this
                # seems OK in terms of the spirit of geometric matching of
                # this algorithm.
                if cur_dist < STOP_ON_ROUTE_CHECK_DIST:
                    dist_isect_from_seg_start = lineargeom.magnitude(seg_start,
                        isect_pt)
                    if dist_isect_from_seg_start < min_stop_isect_from_seg_start:
                        min_stop_isect_from_seg_start = dist_isect_from_seg_start
                        stop_isect_seg_nearest_start = isect_pt
                        min_stop_from_seg_start_ii = stop_ii
            if stop_isect_seg_nearest_start is not None:
                next_stop_on_route_isect = stop_isect_seg_nearest_start
                next_stop_on_route_ii = min_stop_from_seg_start_ii
                linear_dist_from_start_stop += min_stop_isect_from_seg_start
                break
            else:
                linear_dist_from_start_stop += lineargeom.magnitude(seg_start,
                    seg_end)
            seg_start, seg_end = segs_iterator.next()
            last_vertex_i += 1
    except StopIteration:
        pass
    return next_stop_on_route_isect, next_stop_on_route_ii, \
        linear_dist_from_start_stop, last_vertex_i

def move_dist_along_route(route_geom, current_loc, dist_along_route,
        last_vertex_i=None):
    segs_iterator = None
    rem_dist = 0
    if dist_along_route == 0 and last_vertex_i is not None:
        # The 2nd clause needed since we may need to work out last
        #  vertex i, even if not moving.
        return current_loc, last_vertex_i
    elif dist_along_route >= 0:
        rem_dist = dist_along_route
        segs_iterator = lineargeom.pairs(route_geom.GetPoints())
    else:
        # Flip directions.
        rem_dist = -dist_along_route
        segs_iterator = lineargeom.reverse_pairs(route_geom.GetPoints())

    # Setup last_vertex_i and fast-fwd to there
    if last_vertex_i is None:
        # Initialise
        if dist_along_route >= 0:
            last_vertex_i = 0
        else:
            total_vertexes = route_geom.GetPointCount()
            last_vertex_i = (total_vertexes - 1) - 1
    else:
        total_vertexes = route_geom.GetPointCount()
        assert last_vertex_i < total_vertexes
        # "Fast-forward" segs iterator to last known vertex
        vertex_i = 0
        vertex_skip_total = last_vertex_i
        if dist_along_route < 0:
            # we're going backwards in this case.
            vertex_skip_total = (total_vertexes-1) - last_vertex_i - 1
        while vertex_i < vertex_skip_total:
            segs_iterator.next()
            vertex_i += 1

    start_loc_proj_onto_route, seg_start, seg_end, vertexes_passed = \
        advance_along_route_to_loc(segs_iterator, current_loc)
    # Keep walking remaining segs until req. distance travelled.    
    # Special case for start of below loop :- consider "seg_start" as our
    # starting location.
    seg_start = start_loc_proj_onto_route
    try:
        while seg_end is not None:
            dist_to_seg_end = lineargeom.magnitude(seg_start, seg_end)
            if dist_to_seg_end < rem_dist:
                rem_dist -= dist_to_seg_end
            else:
                new_loc = lineargeom.point_dist_along_line(seg_start, seg_end, rem_dist)
                break
            seg_start, seg_end = segs_iterator.next()
            vertexes_passed += 1
    except StopIteration:
        # Means we've walked the whole route, so just move to the end of final
        # segment.
        new_loc = seg_end
    if dist_along_route >= 0:
        last_vertex_i += vertexes_passed
    else:
        last_vertex_i -= vertexes_passed
    return new_loc, last_vertex_i
