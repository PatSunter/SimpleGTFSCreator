import math
import sys
import inspect

DIST_FOR_MATCHING_STOPS_ON_ROUTES = 5.0 
# These are of course dependent on projection. One we use is in metres.
VERY_NEAR_LINE = 1.0
SAME_POINT = 1.0

#Next 4 functions below adapted from:
# http://gis.stackexchange.com/questions/396/nearest-neighbor-between-a-point-layer-and-a-line-layer

# pairs iterator:
# http://stackoverflow.com/questions/1257413/1257446#1257446
def pairs(lst, loop=False):
    i = iter(lst)
    first = prev = i.next()
    for item in i:
        yield prev, item
        prev = item
    if loop == True:
        yield item, first

# these methods rewritten from the C version of Paul Bourke's
# geometry computations:
# http://local.wasp.uwa.edu.au/~pbourke/geometry/pointline/
def magnitude(p1, p2):
    vect_x = p2[0] - p1[0]
    vect_y = p2[1] - p1[1]
    return math.sqrt(vect_x**2 + vect_y**2)

def point_dist_along_line(line_start, line_end, dist):
    """Find the projection along a line dist from seg_start"""
    line_magnitude =  magnitude(line_end, line_start)
    if line_magnitude == 0.0: 
        u = 0
    else:
        u = dist / line_magnitude
    ix = line_start[0] + u * (line_end[0] - line_start[0])
    iy = line_start[1] + u * (line_end[1] - line_start[1])
    return (ix, iy)

def intersect_point_to_line(point, line_start, line_end):
    """Finds intersection of point to line. But also, returns a Bool stating
    if the intersection point was within this line segment."""
    line_magnitude =  magnitude(line_end, line_start)
    if line_magnitude == 0.0:
        # A zero length segment - just return one of the endpoints as closest
        return line_start, False

    uval = ((point[0] - line_start[0]) * (line_end[0] - line_start[0]) +
         (point[1] - line_start[1]) * (line_end[1] - line_start[1])) \
         / (line_magnitude ** 2)

    # closest point does not fall within the line segment, 
    # take the shorter distance to an endpoint
    if uval < 0.00001 or uval > 1:
        ix = magnitude(point, line_start)
        iy = magnitude(point, line_end)
        if ix > iy:
            return line_end, False, uval
        else:
            return line_start, False, uval
    else:
        ix = line_start[0] + u * (line_end[0] - line_start[0])
        iy = line_start[1] + u * (line_end[1] - line_start[1])
        return (ix, iy), True, uval

def nearest_point_on_polyline_to_point(polyline, point):
    assert polyline.GetGeometryName() == "LINESTRING"
    nearest_point = None
    min_dist = sys.maxint

    for seg_start, seg_end in pairs(polyline.GetPoints()):

        line_start = seg_start
        line_end = seg_end

        intersection_point, within_seg, uval = intersect_point_to_line(point,
            line_start, line_end)
        cur_dist = magnitude(point, intersection_point)

        if cur_dist < min_dist:
            min_dist = cur_dist
            nearest_point = intersection_point
    return nearest_point, min_dist

def advance_along_route_to_loc(route_geom, segs_iterator, loc):
    # This first section is to skip ahead to correct segment and project
    # starting location onto line itself. So we need to create the iterator
    # outside the for statement to use in 2nd loop.
    start_stop_proj_onto_route = None
    min_dist_to_route = sys.maxint
    for seg_start, seg_end in segs_iterator:
        intersection_point, within_seg, uval = intersect_point_to_line(loc,
            seg_start, seg_end)
        cur_dist = magnitude(loc, intersection_point)
        if cur_dist < min_dist_to_route:
            # Not actually used, but save for debugging purposes
            min_dist_to_route = cur_dist
        if (cur_dist < VERY_NEAR_LINE) or \
                (within_seg and cur_dist < DIST_FOR_MATCHING_STOPS_ON_ROUTES):
            # The first clause in this loop is necessary for start and end
            # points of route possibly now quite being classed as 'within
            # a segment'
            start_stop_proj_onto_route = intersection_point
            break
    if start_stop_proj_onto_route == None:
        func_name = inspect.stack()[0][3]
        print "Error: %s() called with a location not within "\
            "required distance (%.1fm) of route. Loc is (%s, %s). "\
            "Minimum dist to route calc was %.1fm." %\
            (func_name, DIST_FOR_MATCHING_STOPS_ON_ROUTES, loc[0], \
             loc[1], min_dist_to_route)
        sys.exit(1)
    return start_stop_proj_onto_route, seg_start, seg_end

def get_next_stop_and_dist(route_geom, current_loc_on_route,
        stops_multipoint_near_route, rem_stop_is):
    start_pt = current_loc_on_route
    linear_dist_to_next_stop = 0

    segs_iterator = pairs(route_geom.GetPoints())
    start_stop_proj_onto_route, seg_start, seg_end = advance_along_route_to_loc(
        route_geom, segs_iterator, start_pt)
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
                intersection_point, within_seg, uval = intersect_point_to_line(
                    stop_pt, seg_start, seg_end)
                cur_dist = magnitude(stop_pt, intersection_point)
                # See comment in above loop re this 2-clause test.
                if (cur_dist < VERY_NEAR_LINE) or \
                        (within_seg and cur_dist < DIST_FOR_MATCHING_STOPS_ON_ROUTES):
                    dist_isect_from_seg_start = magnitude(seg_start,
                        intersection_point)
                    if dist_isect_from_seg_start < min_stop_isect_from_seg_start:
                        min_stop_isect_from_seg_start = dist_isect_from_seg_start
                        stop_isect_seg_nearest_start = intersection_point
                        min_stop_from_seg_start_ii = stop_ii
            if stop_isect_seg_nearest_start is not None:
                next_stop_on_route_isect = stop_isect_seg_nearest_start
                next_stop_on_route_ii = min_stop_from_seg_start_ii
                linear_dist_from_start_stop += min_stop_isect_from_seg_start
                break
            else:
                linear_dist_from_start_stop += magnitude(seg_start, seg_end)
            seg_start, seg_end = segs_iterator.next()
    except StopIteration:
        pass
    return next_stop_on_route_isect, next_stop_on_route_ii, linear_dist_from_start_stop

def move_dist_along_route(route_geom, current_loc, dist_along_route):
    rem_dist = dist_along_route
    # Get to current location
    segs_iterator = pairs(route_geom.GetPoints())
    start_loc_proj_onto_route, seg_start, seg_end = advance_along_route_to_loc(
        route_geom, segs_iterator, current_loc)
    # Keep walking remaining segs until req. distance travelled.    
    # Special case for start of below loop :- consider "seg_start" as our
    # starting location.
    seg_start = start_loc_proj_onto_route
    try:
        while seg_end is not None:
            dist_to_seg_end = magnitude(seg_start, seg_end)
            if dist_to_seg_end < rem_dist:
                rem_dist -= dist_to_seg_end
            else:
                new_loc = point_dist_along_line(seg_start, seg_end, rem_dist)
                break
            seg_start, seg_end = segs_iterator.next()
    except StopIteration:
        # Means we've walked the whole route, so just move to the end of final
        # segment.
        new_loc = seg_end    
    return new_loc
