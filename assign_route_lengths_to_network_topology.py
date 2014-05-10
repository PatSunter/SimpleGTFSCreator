#!/usr/bin/env python2
import os
import os.path
import re
import sys
import inspect
import operator
from math import radians, cos, sin, asin, sqrt

import osgeo.ogr
from osgeo import ogr, osr

import topology_shapefile_data_model as tp_model

ROUTE_NAME_FIELD = "NAME"
STOP_ID_FIELD = 'gid'
SEG_ID_FIELD = 'id'

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
    src = line_geom.GetSpatialReference()
    target = osr.SpatialReference()
    target.ImportFromEPSG(4326)
    transform = osr.CoordinateTransformation(src, target)
    for pt in line_geom.GetPoints():
        line_lat_lon.AddPoint(*pt)
    line_lat_lon.Transform(transform)
    #print line_lat_lon.GetPoints()    
    total_metres = 0    
    line_ii = 0
    pt_count = line_lat_lon.GetPointCount()
    print "Calculating haversine length:"
    while line_ii+1 < pt_count:
        pt_a = line_lat_lon.GetPoint(line_ii)
        pt_b = line_lat_lon.GetPoint(line_ii+1)
        section_metres = haversine(pt_a[0], pt_a[1], pt_b[0], pt_b[1])
        total_metres += section_metres
        #print "...added %f metres." % section_metres
        line_ii += 1
    return total_metres

def calc_distance(route, stops):
    route_geom = route.GetGeometryRef()
    stop_geoms = [stop.GetGeometryRef() for stop in stops]

    stop_coords = []
    for ii, stop_geom in enumerate(stop_geoms):
        stop_coords.append(*stop_geom.GetPoints())
    #print "Stop coords are: %s" % (stop_coords)

    stop_points_tform = []
    stop_coords_tform = []
    for ii, coord in enumerate(stop_coords):
        stop_points_tform.append(ogr.Geometry(ogr.wkbPoint))
        stop_points_tform[-1].AddPoint(*coord)

        src = stop_geoms[0].GetSpatialReference()
        target = route_geom.GetSpatialReference()
        transform = osr.CoordinateTransformation(src, target)
        stop_points_tform[-1].Transform(transform)
        stop_coords_tform.append(stop_points_tform[-1].GetPoint())

    assert len(stop_points_tform) == 2

    route_coords = route_geom.GetPoints()
    subline_indices = [None, None]
    distances = [[], []]
    for ii, route_coord in enumerate(route_coords):
        route_pt = ogr.Geometry(ogr.wkbPoint)
        route_pt.AddPoint(*route_coord)
        distances[0].append(route_pt.Distance(stop_points_tform[0]))
        distances[1].append(route_pt.Distance(stop_points_tform[1]))

    min_i0, min_d0 = min(enumerate(distances[0]), key=operator.itemgetter(1))
    min_i1, min_d1 = min(enumerate(distances[1]), key=operator.itemgetter(1))
    min_is = [min_i0, min_i1]
    min_ds = [min_d0, min_d1]

    #print "Min distances were %f [%d], %f [%d] (m)" \
    #    % (min_d0, min_i0, min_d1, min_i1)

    if min_d0 < 100.0:
        subline_indices[0] = min_i0
    if min_d1 < 100.0:
        subline_indices[1] = min_i1
            
    #print subline_indices
    assert None not in subline_indices

    if subline_indices[0] > subline_indices[1]:
        subline_indices.reverse()
        stop_coords.reverse()
        stop_coords_tform.reverse()
        stop_points_tform.reverse()
        min_is.reverse()
        min_ds.reverse()
        distances.reverse()

    #print subline_indices, stop_coords, min_ds, min_is

    subline = ogr.Geometry(ogr.wkbLineString)

    if subline_indices[0] == subline_indices[1]:
        print "In special case correction, of both stops closest "\
            "to same point."
        #Annoying special case:- both stop points are closest to the same
        # vertex (implies stops very close relative to vertex spacing)
        testline = ogr.Geometry(ogr.wkbLineString)
        greater_dist_ii, gd = max(enumerate(min_ds), key=operator.itemgetter(1))
        testline.AddPoint(*route_coords[subline_indices[0]])
        testline.AddPoint(*stop_coords_tform[greater_dist_ii])
        if testline.Distance(stop_points_tform[1-greater_dist_ii]) < 0.01:
            print "Points on same side of closest, so just use stops."
            # if the closer stop is on the same line as a line between closest
            # point and the further stop, just use two stops.
            subline.AddPoint(*stop_coords_tform[0])
            subline.AddPoint(*stop_coords_tform[1])
        else:
            print "Points on opposite sides of closest, so build 3 point line."
            # need to build a line with the closest point in the middle
            subline.AddPoint(*stop_coords_tform[0])
            subline.AddPoint(*route_coords[subline_indices[0]])
            subline.AddPoint(*stop_coords_tform[1])
    else:
        for ii in range(subline_indices[0], subline_indices[1]+1):
            subline.AddPoint(*route_coords[ii])

        if min_ds[0] > 0.01:
            #print "Going to apply end 0 correction:"
            firstseg = ogr.Geometry(ogr.wkbLineString)
            subcount = subline.GetPointCount()
            firstseg.AddPoint(*subline.GetPoint(0))
            firstseg.AddPoint(*subline.GetPoint(1))
            if firstseg.Distance(stop_points_tform[0]) < 0.01:
                #print "Replacing first point with stop since pt is on "\
                #    "first segment"
                newsubline = ogr.Geometry(ogr.wkbLineString)
                newsubline.AddPoint(*stop_coords_tform[0])
                for ii in range(1,subline.GetPointCount()):
                    newsubline.AddPoint(*subline.GetPoint(ii))
                subline = newsubline
            else:
                #print "Adding on stop to subline since this is not on "\
                #    "first segment"
                newsubline = ogr.Geometry(ogr.wkbLineString)
                newsubline.AddPoint(*stop_coords_tform[0])
                for ii in range(subline.GetPointCount()):
                    newsubline.AddPoint(*subline.GetPoint(ii))
                subline = newsubline

        if min_ds[1] > 0.01:
            #print "Going to apply end 1 correction:"
            lastseg = ogr.Geometry(ogr.wkbLineString)
            subcount = subline.GetPointCount()
            lastseg.AddPoint(*subline.GetPoint(subcount-2))
            lastseg.AddPoint(*subline.GetPoint(subcount-1))
            if lastseg.Distance(stop_points_tform[1]) < 0.01:
                #print "Replacing last point with stop since pt is on "\
                #   "last segment"
                newsubline = ogr.Geometry(ogr.wkbLineString)
                for ii in range(subline.GetPointCount()-1):
                    newsubline.AddPoint(*subline.GetPoint(ii))
                newsubline.AddPoint(*stop_coords_tform[1])
                subline = newsubline
            else:    
                #print "Adding on stop to subline since this is not on "\
                #   "last segment"
                subline.AddPoint(*stop_coords_tform[1])
            
    subline.AssignSpatialReference(route_geom.GetSpatialReference())
    #print subline.GetPoints()
    #length = subline.Length()
    length = calc_length_along_line_haversine(subline)
    print "Length was %d meters." % round(length)

def calc_single_route_segment_length(route_lyr, stops_lyr, route_num, stop_ids):
    found_route = None
    for route in route_lyr:
        if route.GetField(ROUTE_NAME_FIELD) == route_num:
            found_route = route
            break
    assert found_route is not None
    route = found_route
    route_lyr.ResetReading()

    stops = []
    for stop_id in stop_ids:
        for stop_ii, stop in enumerate(stops_lyr):
            if stop.GetField(STOP_ID_FIELD) == stop_id:
                #print "Found stop %d, at %d thru stops list" \
                #   % (stop_id, stop_ii)
                stops.append(stop)
                break
        stops_lyr.ResetReading()
    assert len(stops) == 2    
    calc_distance(route, stops)

    
def calc_all_route_segment_lengths(route_lyr, segments_lyr, stops_lyr,
        route_num, stop_ids):
    print "Calculating segment lengths for route %s" % (route_num)

    for segment in segments_lyr:
        rlist = segment.GetField(tp_model.SEG_ROUTE_LIST_FIELD).split(',')
        if route_num in rlist:
            print "Calculating length of segment %s:"\
                % segment.GetField(tp_model.SEG_ID_FIELD)
            s_id_a = int(segment.GetField(tp_model.SEG_STOP_1_NAME_FIELD)[1:])
            s_id_b = int(segment.GetField(tp_model.SEG_STOP_2_NAME_FIELD)[1:])
            stop_ids = [s_id_a, s_id_b]
            calc_single_route_segment_length(route_lyr, stops_lyr, route_num,
                stop_ids)
            print "(Prev stored length: %s)" % \
                (segment.GetField(tp_model.SEG_ROUTE_DIST_FIELD))
            

if __name__ == "__main__":
    fname = os.path.expanduser('/Users/pds_phd/Dropbox/PhD-TechnicalProjectWork/OSSTIP_BZE/Melbourne_GIS_NetworkDataWork/BZE_New_Network/QGISnetwork/in/shp/network-self-snapped-reworked-patextend-201405.shp')
    route_shape = osgeo.ogr.Open(fname, 0) 
    stops_fname = '/Users/pds_phd/Dropbox/PhD-TechnicalProjectWork/OSSTIP_BZE/Melbourne_GIS_NetworkDataWork/BZE_New_Network/bus-nodes-segments-13_dec-motorway-stops-removed/bus-nodes.shp'
    stops_shape = osgeo.ogr.Open(stops_fname, 0) 
    segments_fname = '/Users/pds_phd/Dropbox/PhD-TechnicalProjectWork/OSSTIP_BZE/Melbourne_GIS_NetworkDataWork/BZE_New_Network/bus-nodes-segments-13_dec-motorway-stops-removed/bus-edges.shp'
    segments_shape = osgeo.ogr.Open(segments_fname, 0) 
    route_lyr = route_shape.GetLayer(0)
    stops_lyr = stops_shape.GetLayer(0)
    segments_lyr = segments_shape.GetLayer(0)

    route_num = 'R93'
    #stop_ids = [2361, 151]
    stop_ids = [231, 230]

    calc_single_route_segment_length(route_lyr, stops_lyr, route_num, stop_ids)

    calc_all_route_segment_lengths(route_lyr, segments_lyr, stops_lyr,
        route_num, stop_ids)

    route_shape.Destroy()
    route_shape = None
    stops_shape.Destroy()
    stops_shape = None

