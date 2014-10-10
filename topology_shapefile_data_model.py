
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

ON_MOTORWAY_FIELD = 'mway'

STOP_TYPE_ROUTE_START_END = "ROUTE_START_END"
STOP_TYPE_SELF_TFER = "TRANSFER_SELF"
STOP_TYPE_FILLERS = "FILLERS"
STOP_TYPE_FROM_EXISTING_GTFS = "FROM_EXISTING_GTFS"

#################
# Low-level functions to add new fields or check required ones exist.
def check_field_exists(lyr_defn, field_name):
    field_match = False
    field_i = None
    for field_i in range(lyr_defn.GetFieldCount()):
        if lyr_defn.GetFieldDefn(field_i).GetName() == field_name:
            field_match = True
            break;
    if field_match:
        return True, field_i
    else:
        return False, None

def check_field_props(lyr_defn, field_i, req_type_code, min_width,
        min_precision=None):
    f_defn = lyr_defn.GetFieldDefn(field_i)
    # Check type etc is correct
    f_type_code = f_defn.GetType()
    f_width = f_defn.GetWidth()
    f_precision = f_defn.GetPrecision()
    if f_type_code == req_type_code and f_width >= min_width:
        if min_precision is None:
            return True
        elif f_precision >= min_precision:
            return True
        else:
            return False
    else:
        return False

def ensure_field_exists(route_segments_lyr, field_name, field_type_code,
        field_width, field_precision=None):
    lyr_defn = route_segments_lyr.GetLayerDefn()
    field_exists, field_i = check_field_exists(lyr_defn, field_name)
    if field_exists == True:
        ok_props = check_field_props(lyr_defn, field_i, field_type_code,
            field_width, field_precision)
        if not ok_props:
            print "Error: field '%s' exists, but badly defined - deleting, "\
                "will re-create." % (field_name)
            route_segments_lyr.DeleteField(field_i)
            field_exists = False
    if field_exists == False:
        print "Creating new field '%s'." % field_name
        f_defn = ogr.FieldDefn(field_name, field_type_code)
        f_defn.SetWidth(field_width)
        if field_precision:
            f_defn.SetPrecision(field_precision)
        route_segments_lyr.CreateField(f_defn)


#################
# Functions to build Python lookup tables (dicts) into sets of all stops
#  and segments, to allow fast access to them by integer ID.

def build_stops_lookup_table(stops_lyr):
    """Given a layer of stops, creates a 'lookup table' dict where 
    keys are stop IDs, and values are ptrs to individual features.
    
    This is useful to build for speedup where a subsequent algorithm
    will need to access individual stops many times.
    
    NOTE: meant as a temporary structure, since as soon as you close the
    relevant shapefile or modify the layer, it becomes redundant."""
    lookup_dict = {}
    for feature in stops_lyr:
        stop_id = (feature.GetField(STOP_ID_FIELD))
        lookup_dict[int(stop_id)] = feature
    stops_lyr.ResetReading()
    return lookup_dict

def build_segs_lookup_table(route_segments_lyr):
    """Given a layer of route segments, creates a 'lookup table' dict where 
    keys are segment IDs, and values are ptrs to individual features.
    
    This is useful to build for speedup where a subsequent algorithm
    will need to access individual segments many times (e.g. when processing
    routes).
    
    NOTE: meant as a temporary structure, since as soon as you close the
    relevant shapefile or modify the layer, it becomes redundant."""
    lookup_dict = {}
    for feature in route_segments_lyr:
        seg_id = (feature.GetField(SEG_ID_FIELD))
        lookup_dict[int(seg_id)] = feature
    route_segments_lyr.ResetReading()
    return lookup_dict

###########################################################
# Access functions for key properties of segment-stop info

def get_distance_km(seg_feature):
    rdist = float(seg_feature.GetField(SEG_ROUTE_DIST_FIELD))
    rdist = rdist / ROUTE_DIST_RATIO_TO_KM
    return rdist

def get_routes_on_seg(seg_feature):
    seg_routes = seg_feature.GetField(SEG_ROUTE_LIST_FIELD)
    rlist = seg_routes.split(',')
    assert len(rlist) > 0
    return rlist

# These get() funcs below were originally in create_gtfs_from_basicinfo.py
def get_stop_feature_name(feature, stop_prefix):
    stop_id = feature.GetField(STOP_NAME_FIELD)
    if stop_id is None:
        stop_name = None
    else:
        if type(stop_id) == str:
            stop_name = stop_id
        else:    
            stop_name = stop_prefix+str(int(stop_id))
    return stop_name

def get_stop_feature(stop_name, stops_lyr, stop_prefix):
    # Just do a linear search for now.
    match_feature = None
    for feature in stops_lyr:
        fname = get_stop_feature_name(feature, stop_prefix)
        if fname == stop_name:
            match_feature = feature
            break;    
    stops_lyr.ResetReading()        
    return match_feature

def get_route_segment(segment_id, route_segments_lyr):
    # Just do a linear search for now.
    match_feature = None
    for feature in route_segments_lyr:
        if int(feature.GetField(SEG_ID_FIELD)) == segment_id:
            match_feature = feature
            break;    
    route_segments_lyr.ResetReading()        
    return match_feature

def get_other_stop_name(seg_feat, stop_name):
    stop_name_a = seg_feat.GetField(SEG_STOP_1_NAME_FIELD)
    if stop_name == stop_name_a:
        return seg_feat.GetField(SEG_STOP_2_NAME_FIELD)
    else:
        return stop_name_a

################
# Section below related to adding stops, routes, segments to shapefiles.

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
    dirname = os.path.dirname(abs_stops_shp_file_name)
    if not os.path.exists(dirname):
        os.makedirs(dirname)
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

def add_route_to_seg(segments_lyr, seg_feat, route_name):
    orig_list = seg_feat.GetField(SEG_ROUTE_LIST_FIELD)
    upd_list = orig_list + ",%s" % route_name
    seg_feat.SetField(SEG_ROUTE_LIST_FIELD, upd_list)
    segments_lyr.SetFeature(seg_feat)
    return

def add_seg_ref_as_feature(segs_lyr, seg_ref, seg_geom, mode_config):
    seg_ii = segs_lyr.GetFeatureCount()
    #Create seg feature, with needed fields etc.
    seg_feat = ogr.Feature(segs_lyr.GetLayerDefn())
    #Need to re-project geometry into target SRS (do this now,
    # after we've added to multipoint, which should be in same SRS as
    # above).
    prefix = mode_config['stop_prefix']
    assert(seg_geom.GetPointCount() == 2)
    src_srs = seg_geom.GetSpatialReference()
    target_srs = segs_lyr.GetSpatialRef()
    assert(src_srs != None)
    assert(target_srs != None)
    transform = osr.CoordinateTransformation(src_srs, target_srs)
    seg_geom2 = seg_geom.Clone()
    seg_geom2.Transform(transform)
    seg_feat.SetGeometry(seg_geom2)
    seg_feat.SetField(SEG_ID_FIELD, seg_ref.seg_id)
    seg_feat.SetField(SEG_ROUTE_LIST_FIELD, ",".join(seg_ref.routes))
    seg_feat.SetField(SEG_STOP_1_NAME_FIELD, "%s%d" % (prefix, seg_ref.first_id))
    seg_feat.SetField(SEG_STOP_2_NAME_FIELD, "%s%d" % (prefix, seg_ref.second_id))
    # Rounding to nearest meter below per convention.
    seg_feat.SetField(SEG_ROUTE_DIST_FIELD, "%.0f" % seg_ref.route_dist_on_seg)
    seg_feat.SetField(SEG_FREE_SPEED_FIELD, 0.0)
    seg_feat.SetField(SEG_PEAK_SPEED_FIELD, 0.0)
    segs_lyr.CreateFeature(seg_feat)
    seg_feat.Destroy()
    seg_geom2.Destroy()
    return seg_ii
