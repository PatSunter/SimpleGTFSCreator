
import math
import sys
from math import radians, cos, sin, asin, sqrt

import osgeo.ogr
from osgeo import ogr, osr

"""These functions are to help perform basic linear geometry operations on
polylines - of the sort that PostGIS would be able to do for example.

They are adapted from:
http://gis.stackexchange.com/questions/396/nearest-neighbor-between-a-point-layer-and-a-line-layer

And also:
http://gis.stackexchange.com/questions/4022/looking-for-a-pythonic-way-to-calculate-the-length-of-a-wkt-linestring
"""

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

# A reversed version of the above pairs iterator.
def reverse_pairs(lst, loop=False):
    i = reversed(lst)
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
    """Finds intersection of point to line. 
    But also, returns a Bool stating if the intersection point was
    within this line segment. And also, the 'uval' stating the
    linear proportion along the line it was found.
    (uval values -ve imply before start of line, > 1.0 after end of
    line)."""
    line_magnitude =  magnitude(line_end, line_start)
    if line_magnitude == 0.0:
        # A zero length segment - just return one of the endpoints as closest
        return line_start, False, 0.0

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
        ix = line_start[0] + uval * (line_end[0] - line_start[0])
        iy = line_start[1] + uval * (line_end[1] - line_start[1])
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

# Note:- could possibly also use the shapely length function, or 
# geopy has a Vincenty Distance implementation
# see:- http://gis.stackexchange.com/questions/4022/looking-for-a-pythonic-way-to-calculate-the-length-of-a-wkt-linestring
def haversine(lon1, lat1, lon2, lat2):
    """
     Calculate the great circle distance between two points 
     on the earth (specified in decimal degrees) - return in metres
    """
    # convert decimal degrees to radians 
    lon1, lat1, lon2, lat2 = map(radians, [lon1, lat1, lon2, lat2])
    # haversine formula 
    dlon = lon2 - lon1 
    dlat = lat2 - lat1 
    a = sin(dlat/2)**2 + cos(lat1) * cos(lat2) * sin(dlon/2)**2
    c = 2 * asin(sqrt(a)) 
    km = 6367 * c
    metres = km * 1000
    return metres 

def calc_length_along_line_haversine(line_geom):
    line_lat_lon = ogr.Geometry(ogr.wkbLineString)
    src_srs = line_geom.GetSpatialReference()
    target_srs = osr.SpatialReference()
    target_srs.ImportFromEPSG(4326)
    transform = osr.CoordinateTransformation(src_srs, target_srs)
    for pt in line_geom.GetPoints():
        line_lat_lon.AddPoint(*pt)
    line_lat_lon.Transform(transform)
    #print line_lat_lon.GetPoints()    
    total_metres = 0    
    line_ii = 0
    pt_count = line_lat_lon.GetPointCount()
    #print "Calculating haversine length:"
    while line_ii+1 < pt_count:
        pt_a = line_lat_lon.GetPoint(line_ii)
        pt_b = line_lat_lon.GetPoint(line_ii+1)
        section_metres = haversine(pt_a[0], pt_a[1], pt_b[0], pt_b[1])
        total_metres += section_metres
        #print "...added %f metres." % section_metres
        line_ii += 1
    return total_metres
