import math
import sys

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

def intersect_point_to_line(point, line_start, line_end):
    line_magnitude =  magnitude(line_end, line_start)
    if line_magnitude == 0.0:
        # A zero length segment - just return one of the endpoints as closest
        return line_start

    u = ((point[0] - line_start[0]) * (line_end[0] - line_start[0]) +
         (point[1] - line_start[1]) * (line_end[1] - line_start[1])) \
         / (line_magnitude ** 2)

    # closest point does not fall within the line segment, 
    # take the shorter distance to an endpoint
    if u < 0.00001 or u > 1:
        ix = magnitude(point, line_start)
        iy = magnitude(point, line_end)
        if ix > iy:
            return line_end
        else:
            return line_start
    else:
        ix = line_start[0] + u * (line_end[0] - line_start[0])
        iy = line_start[1] + u * (line_end[1] - line_start[1])
        return (ix, iy)

def nearest_point_on_polyline_to_point(polyline, point):
    assert polyline.GetGeometryName() == "LINESTRING"
    nearest_point = None
    min_dist = sys.maxint

    for seg_start, seg_end in pairs(polyline.GetPoints()):

        line_start = seg_start
        line_end = seg_end

        intersection_point = intersect_point_to_line(point,
            line_start, line_end)
        cur_dist = magnitude(point, intersection_point)

        if cur_dist < min_dist:
            min_dist = cur_dist
            nearest_point = intersection_point
    return nearest_point

