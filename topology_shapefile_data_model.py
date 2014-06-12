
"""These global variables determine fields within the GIS Network Topology shapefile"""

import os, os.path
import sys

import osgeo.ogr
from osgeo import ogr, osr

ROUTE_NAME_FIELD = "NAME"

# Note re route list field - a comma-separated list of route short names seg
# belongs to. If route names short (e.g. 4 chars), can be up to 40 routes.
#  If route names were a lot longer, this could potentially be an issue.
EPSG_SEGS_FILE = 4326
SEG_LYR_NAME = "segments"
SEG_ID_FIELD = "id"                 # str, 21
SEG_ROUTE_LIST_FIELD = "route_list" # str, 254
SEG_STOP_1_NAME_FIELD = "pt_a"      # str, 24
SEG_STOP_2_NAME_FIELD = "pt_b"      # str, 24
SEG_ROUTE_DIST_FIELD = 'leg_length' # real, 24, 15
SEG_FREE_SPEED_FIELD = "free_speed" # real, 24, 15
SEG_PEAK_SPEED_FIELD = "peak_speed" # real, 24, 15
ROUTE_DIST_RATIO_TO_KM = 1000       # As it says - effectively encodes units

EPSG_STOPS_FILE = 4326
STOP_LYR_NAME = "stops"
STOP_ID_FIELD = "gid"               # int, 10
STOP_NAME_FIELD = "ID"              # int, 10
STOP_TYPE_FIELD = "typ"             # str, 50 - reasonable length type strs.

def get_distance_km(seg_feature):
    rdist = float(seg_feature.GetField(SEG_ROUTE_DIST_FIELD))
    rdist = rdist / ROUTE_DIST_RATIO_TO_KM
    return rdist

def create_stops_shp_file(stops_shp_file_name, delete_existing=False):
    """Creates an empty stops shapefile. Returns the newly created shapefile,
    and the stops layer within it."""
    # OGR doesn't like relative paths
    abs_stops_shp_file_name = os.path.abspath(stops_shp_file_name)
    print "Creating new stops shape file at path %s:" % abs_stops_shp_file_name
    if os.path.exists(abs_stops_shp_file_name):
        print "File exists at that name."
        if delete_existing == True:
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
    layer = stops_shp_file.CreateLayer(STOP_LYR_NAME, srs, ogr.wkbPoint)
    layer.CreateField(ogr.FieldDefn(STOP_ID_FIELD, ogr.OFTInteger))
    layer.CreateField(ogr.FieldDefn(STOP_NAME_FIELD, ogr.OFTInteger))
    field = ogr.FieldDefn(STOP_TYPE_FIELD, ogr.OFTString)
    field.SetWidth(50)
    layer.CreateField(field)
    print "... done."
    return stops_shp_file, layer

def add_stop(stops_lyr, stops_multipoint, stop_type, stop_geom, src_srs):
    """Adds a stop to stops_lyr, and also its geometry to stops_multipoint. 
    In the case of stops_lyr, the new stops' geometry will be re-projected into
    the SRS of that layer before adding (hence need to pass srs_srs as an
    input var. In the case of stops_multipoint, the geometry will be added
    as is, without reprojection (this is useful for geometrical operations
    in the original SRS of the routes shapefile you're working with."""
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
    stop_feat.SetField(STOP_ID_FIELD, pt_id)
    stop_feat.SetField(STOP_NAME_FIELD, pt_id)
    stop_feat.SetField(STOP_TYPE_FIELD, stop_type)
    stops_lyr.CreateFeature(stop_feat)
    stop_feat.Destroy()
    return pt_id

def create_segs_shp_file(segs_shp_file_name, delete_existing=False):
    """Creates an empty segments shapefile. Returns the newly created shapefile,
    and the segments layer within it."""
    # OGR doesn't like relative paths
    abs_segs_shp_file_name = os.path.abspath(segs_shp_file_name)
    print "Creating new segs shape file at path %s:" % abs_segs_shp_file_name
    if os.path.exists(abs_segs_shp_file_name):
        print "File exists at that name."
        if delete_existing == True:
            print "deleting so we can overwrite."
            os.unlink(abs_segs_shp_file_name)
        else:
            print "... so exiting."
            sys.exit(1)
    driver = ogr.GetDriverByName("ESRI Shapefile")
    segs_shp_file = driver.CreateDataSource(abs_segs_shp_file_name)
    if segs_shp_file is None:
        print "Error trying to create new shapefile at path %s - exiting." %\
            abs_segs_shp_file_name
        sys.exit(1)
    srs = osr.SpatialReference()
    srs.ImportFromEPSG(EPSG_SEGS_FILE)
    layer = segs_shp_file.CreateLayer(SEG_LYR_NAME, srs, ogr.wkbLineString)
    field = ogr.FieldDefn(SEG_ID_FIELD, ogr.OFTString)
    field.SetWidth(21)
    layer.CreateField(field)
    field = ogr.FieldDefn(SEG_ROUTE_LIST_FIELD, ogr.OFTString)
    field.SetWidth(254)
    layer.CreateField(field)
    field = ogr.FieldDefn(SEG_STOP_1_NAME_FIELD, ogr.OFTString)
    field.SetWidth(24)
    layer.CreateField(field)
    field = ogr.FieldDefn(SEG_STOP_2_NAME_FIELD, ogr.OFTString)
    field.SetWidth(24)
    layer.CreateField(field)
    field = ogr.FieldDefn(SEG_ROUTE_DIST_FIELD, ogr.OFTReal)
    field.SetWidth(24)
    field.SetPrecision(15)
    layer.CreateField(field)
    layer.CreateField(field)
    field = ogr.FieldDefn(SEG_FREE_SPEED_FIELD, ogr.OFTReal)
    field.SetWidth(24)
    field.SetPrecision(15)
    layer.CreateField(field)
    field = ogr.FieldDefn(SEG_PEAK_SPEED_FIELD, ogr.OFTReal)
    field.SetWidth(24)
    field.SetPrecision(15)
    layer.CreateField(field)
    print "... done."
    return segs_shp_file, layer

def add_new_segment(segs_lyr, start_stop_id, end_stop_id, route_name,
        route_dist_on_seg, seg_geom):
    seg_ii = segs_lyr.GetFeatureCount()
    seg_id = seg_ii + 1                 # Start from 1.
    #Create seg feature, with needed fields etc.
    seg_feat = ogr.Feature(segs_lyr.GetLayerDefn())
    #Need to re-project geometry into target SRS (do this now,
    # after we've added to multipoint, which should be in same SRS as
    # above).
    assert(seg_geom.GetPointCount() == 2)
    src_srs = seg_geom.GetSpatialReference()
    target_srs = segs_lyr.GetSpatialRef()
    assert(src_srs != None)
    assert(target_srs != None)
    transform = osr.CoordinateTransformation(src_srs, target_srs)
    seg_geom2 = seg_geom.Clone()
    seg_geom2.Transform(transform)
    seg_feat.SetGeometry(seg_geom2)
    seg_feat.SetField(SEG_ID_FIELD, seg_id)
    seg_feat.SetField(SEG_ROUTE_LIST_FIELD, route_name)
    seg_feat.SetField(SEG_STOP_1_NAME_FIELD, "B%d" % start_stop_id)
    seg_feat.SetField(SEG_STOP_2_NAME_FIELD, "B%d" % end_stop_id)
    # Rounding to nearest meter below per convention.
    seg_feat.SetField(SEG_ROUTE_DIST_FIELD, "%.0f" % route_dist_on_seg)
    seg_feat.SetField(SEG_FREE_SPEED_FIELD, 0.0)
    seg_feat.SetField(SEG_PEAK_SPEED_FIELD, 0.0)
    segs_lyr.CreateFeature(seg_feat)
    seg_feat.Destroy()
    seg_geom2.Destroy()
    return seg_ii, seg_id

def add_route_to_seg(segments_lyr, seg_feat, route_name):
    orig_list = seg_feat.GetField(SEG_ROUTE_LIST_FIELD)
    upd_list = orig_list + ",%s" % route_name
    seg_feat.SetField(SEG_ROUTE_LIST_FIELD, upd_list)
    segments_lyr.SetFeature(seg_feat)
    return

def add_update_segment(segments_lyr, start_stop_id,
        end_stop_id, route_name, route_dist_on_seg, seg_geom,
        all_seg_tuples):
    seg_id = None
    new_status = False
    # First, search for existing segment in list
    # TODO:- search in all_seg_tuples for tuple with right attribs
    matched_seg = None
    matched_seg_tuple = None
    for seg_tuple in all_seg_tuples:
        if seg_tuple[1] == start_stop_id and seg_tuple[2] == end_stop_id or \
                seg_tuple[1] == end_stop_id and seg_tuple[2] == start_stop_id:
            matched_seg_tuple = seg_tuple
            matched_seg = segments_lyr.GetFeature(matched_seg_tuple[0])
            break
    if matched_seg:
        #print "While adding, matched a segment! Seg id = %s, existing "\
        #    "routes = '%s', new route = '%s'" %\
        #    (matched_seg.GetField(SEG_ID_FIELD),\
        #    matched_seg.GetField(SEG_ROUTE_LIST_FIELD),\
        #    route_name)
        add_route_to_seg(segments_lyr, matched_seg, route_name)
        new_status = False
        seg_ii = matched_seg_tuple[0]
        seg_id = matched_seg.GetField(SEG_ID_FIELD)
    else:    

        seg_ii, seg_id = add_new_segment(segments_lyr, start_stop_id, end_stop_id,
            route_name, route_dist_on_seg, seg_geom)
        new_status = True
    return seg_ii, seg_id, new_status
