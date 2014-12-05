
"""These global variables determine fields within the GIS Network Topology shapefile"""

import os, os.path
import sys
import re

import osgeo.ogr
from osgeo import ogr, osr

# For normal routes
ROUTE_NAME_FIELD = "NAME"
# For route extensions
ROUTE_EXT_ID_FIELD = "ID"
ROUTE_EXT_NAME_FIELD = "Name"
ROUTE_EXT_TYPE_FIELD = "Ext_Type"
ROUTE_EXT_EXIST_S_NAME_FIELD = "Ext_s_name"
ROUTE_EXT_EXIST_L_NAME_FIELD = "Ext_l_name"
ROUTE_EXT_CONNECTING_STOP_FIELD = "Con_stop_i"
ROUTE_EXT_FIRST_STOP_FIELD = "Fst_stop_i"
ROUTE_EXT_UPD_S_NAME_FIELD = "upd_s_name"
ROUTE_EXT_UPD_L_NAME_FIELD = "upd_l_name"
ROUTE_EXT_UPD_DIR_NAME_FIELD = "upd_dir_n"

ROUTE_EXT_TYPE_EXTENSION = "EXT"
ROUTE_EXT_TYPE_NEW = "NEW"

ROUTE_EXT_ALL_TYPES = [ROUTE_EXT_TYPE_EXTENSION, ROUTE_EXT_TYPE_NEW]

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
ROUTE_DIST_RATIO_TO_KM = 1000       # As it says - effectively encodes units

EPSG_STOPS_FILE = 4326
STOP_LYR_NAME = "stops"
STOP_ID_FIELD = "ID"                # int, 10
STOP_NAME_FIELD = "name"            # str, 254
STOP_TYPE_FIELD = "typ"             # str, 50 - reasonable length type strs.
STOP_GTFS_ID_FIELD = "gtfs_id"      # int, 10

ON_MOTORWAY_FIELD = 'mway'

STOP_TYPE_ROUTE_START_END = "ROUTE_START_END"
STOP_TYPE_SELF_TFER = "TRANSFER_SELF"
STOP_TYPE_FILLERS = "FILLERS"
STOP_TYPE_FROM_EXISTING_GTFS = "FROM_EXISTING_GTFS"
STOP_TYPE_NEW_EXTENDED = "NEW_EXTENDED_ROUTE"

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

def build_stop_id_to_gtfs_stop_id_map(stops_lyr):
    lyr_defn = stops_lyr.GetLayerDefn()
    field_exists, field_i = check_field_exists(lyr_defn, STOP_GTFS_ID_FIELD)
    if not field_exists:
        raise ValueError("Can't build stop ID to GTFS ID map for a "\
            "stops layer that doesn't include a GTFS ID field.")
    stop_id_to_gtfs_id_map = {}
    # Build mapping of osstip route id to gtfs route id
    for stop in stops_lyr:
        stop_id = stop.GetField(STOP_ID_FIELD)
        gtfs_id = stop.GetField(STOP_GTFS_ID_FIELD)
        stop_id_to_gtfs_id_map[stop_id] = gtfs_id
    stops_lyr.ResetReading()
    return stop_id_to_gtfs_id_map

def build_stop_id_to_stop_name_map(stops_lyr):
    lyr_defn = stops_lyr.GetLayerDefn()
    field_exists, field_i = check_field_exists(lyr_defn, STOP_NAME_FIELD)
    if not field_exists:
        raise ValueError("Can't build stop ID to name map for a "\
            "stops layer that doesn't include a name field.")
    stop_id_to_stop_name_map = {}
    # Build mapping of osstip route id to gtfs route id
    for stop in stops_lyr:
        stop_id = stop.GetField(STOP_ID_FIELD)
        stop_name = stop.GetField(STOP_NAME_FIELD)
        stop_id_to_stop_name_map[stop_id] = stop_name
    stops_lyr.ResetReading()
    return stop_id_to_stop_name_map

###########################################################
# Access functions for key properties of segment-stop info

def get_distance_km(seg_feature):
    rdist = float(seg_feature.GetField(SEG_ROUTE_DIST_FIELD))
    rdist = rdist / ROUTE_DIST_RATIO_TO_KM
    return rdist

def get_routes_on_seg(seg_feature):
    seg_routes = seg_feature.GetField(SEG_ROUTE_LIST_FIELD)
    rlist = map(int, seg_routes.split(','))
    assert len(rlist) > 0
    return rlist

# These get() funcs below were originally in create_gtfs_from_basicinfo.py
def get_stop_feature_default_name(feature, stop_prefix):
    """Note:- this returns the 'default' name for a stop, which is a mode
    prefix followed by its ID, e.g. 'B45' :- not the actual
    name stored in the stop name field."""
    stop_id = feature.GetField(STOP_NAME_FIELD)
    if stop_id is None:
        stop_def_name = None
    else:
        if type(stop_id) == str:
            stop_def_name = stop_id
        else:    
            stop_def_name = stop_prefix+str(int(stop_id))
    return stop_def_name

def get_stop_feature_with_default_name(stop_def_name, stops_lyr, stop_prefix):
    # Just do a linear search for now.
    match_feature = None
    for feature in stops_lyr:
        fname = get_stop_feature_name(feature, stop_prefix)
        if fname == stop_def_name:
            match_feature = feature
            break;    
    stops_lyr.ResetReading()        
    return match_feature

def get_stop_feature_with_name(stops_lyr, stop_name):
    # Just do a linear search for now.
    match_stop = None
    for feature in stops_lyr:
        fname = feature.GetField(STOP_NAME_FIELD)
        if fname == stop_name:
            match_stop = feature
            break;
    stops_lyr.ResetReading()
    return match_stop

def get_stop_id_with_name(stops_lyr, stop_name):
    match_id = None
    match_feat = get_stop_feature_with_name(stops_lyr, stop_name)       
    if match_feat: 
        match_id = match_feat.GetField(STOP_ID_FIELD)
    return match_id

def get_gtfs_stop_id_pair_of_segment(segment, stop_id_to_gtfs_id_map):
    stop_a_id, stop_b_id = get_stop_ids_of_seg(segment)
    gtfs_stop_a_id = stop_id_to_gtfs_id_map[stop_a_id]
    gtfs_stop_b_id = stop_id_to_gtfs_id_map[stop_b_id]
    gtfs_stop_ids_sorted = sorted([gtfs_stop_a_id, gtfs_stop_b_id])
    return tuple(gtfs_stop_ids_sorted)

def get_route_segment(segment_id, route_segments_lyr):
    # Just do a linear search for now.
    match_feature = None
    for feature in route_segments_lyr:
        if int(feature.GetField(SEG_ID_FIELD)) == segment_id:
            match_feature = feature
            break;    
    route_segments_lyr.ResetReading()        
    return match_feature

def get_max_stop_gtfs_id(stops_lyr):
    max_gtfs_id = -1
    for stop_feat in stops_lyr:
        try:
            stop_gtfs_id = int(stop_feat.GetField(STOP_GTFS_ID_FIELD))
        except ValueError:
            continue
        if stop_gtfs_id > max_gtfs_id:
            max_gtfs_id = stop_gtfs_id
    stops_lyr.ResetReading()
    if max_gtfs_id == -1:
        max_gtfs_id = None
    return max_gtfs_id

################
# Section below related to adding stops, routes, segments to shapefiles.

def create_stops_shp_file(stops_shp_file_name, delete_existing=False,
        gtfs_origin_field=False):
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
    field = ogr.FieldDefn(STOP_NAME_FIELD, ogr.OFTString)
    field.SetWidth(254)
    layer.CreateField(field)
    field = ogr.FieldDefn(STOP_TYPE_FIELD, ogr.OFTString)
    field.SetWidth(50)
    layer.CreateField(field)
    if gtfs_origin_field:
        layer.CreateField(ogr.FieldDefn(STOP_GTFS_ID_FIELD, ogr.OFTInteger))
    print "... done."
    return stops_shp_file, layer

def create_stops_shp_file_combined_from_existing(
        stops_shp_file_name,
        stops_lyr_1, stops_lyr_2,
        delete_existing=False, gtfs_origin_field=False,
        auto_create_added_gtfs_ids=False):
    # First create empty new file
    new_stops_shp_file, new_stops_lyr = create_stops_shp_file(
        stops_shp_file_name, delete_existing=delete_existing,
        gtfs_origin_field=gtfs_origin_field)

    all_stops_multipoint = ogr.Geometry(ogr.wkbMultiPoint)
    first_lyr_srs = stops_lyr_1.GetSpatialRef()
    for stop_feat in stops_lyr_1:
        try:
            gtfs_id = stop_feat.GetField(STOP_GTFS_ID_FIELD)
        except ValueError:
            gtfs_id = None
        add_stop(new_stops_lyr, all_stops_multipoint,
            stop_feat.GetField(STOP_TYPE_FIELD),
            stop_feat.GetGeometryRef(),
            first_lyr_srs,
            stop_name=stop_feat.GetField(STOP_NAME_FIELD),
            gtfs_id=gtfs_id)
    stops_lyr_1.ResetReading()

    if auto_create_added_gtfs_ids:
        max_gtfs_id_first = get_max_stop_gtfs_id(stops_lyr_1)
        assert max_gtfs_id_first is not None
        init_auto_added_gtfs_id = (int(max_gtfs_id_first / 1000) + 1) * 1000

    second_lyr_srs = stops_lyr_2.GetSpatialRef()
    for stop_ii_second, stop_feat in enumerate(stops_lyr_2):
        # In this case we're not sure all the optional fields exist.
        try:
            stop_type = stop_feat.GetField(STOP_TYPE_FIELD)
        except ValueError:
            stop_type = STOP_TYPE_NEW_EXTENDED
        try:
            stop_name = stop_feat.GetField(STOP_NAME_FIELD)
        except ValueError:    
            stop_name = None
        if not auto_create_added_gtfs_ids:
            try:
                gtfs_id = stop_feat.GetField(STOP_GTFS_ID_FIELD)
            except ValueError:
                gtfs_id = None
        else:
            gtfs_id = init_auto_added_gtfs_id + stop_ii_second
        add_stop(new_stops_lyr, all_stops_multipoint,
            stop_type,
            stop_feat.GetGeometryRef(),
            second_lyr_srs,
            stop_name=stop_name,
            gtfs_id=gtfs_id)
    stops_lyr_2.ResetReading()
    all_stops_multipoint.Destroy()
    return new_stops_shp_file, new_stops_lyr

def add_stop(stops_lyr, stops_multipoint, stop_type, stop_geom, src_srs,
        stop_name=None, gtfs_id=None):
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
    if stop_name == None:
        stop_feat.SetField(STOP_NAME_FIELD, str(pt_id))
    else:
        stop_feat.SetField(STOP_NAME_FIELD, str(stop_name))
    stop_feat.SetField(STOP_TYPE_FIELD, stop_type)
    if gtfs_id is not None:
        stop_feat.SetField(STOP_GTFS_ID_FIELD, int(gtfs_id))
    stops_lyr.CreateFeature(stop_feat)
    stop_feat.Destroy()
    return pt_id

def get_stop_id_with_gtfs_id(stops_lyr, search_gtfs_id):
    stop_id = None
    for stop_feat in stops_lyr:
        stop_gtfs_id = stop_feat.GetField(STOP_GTFS_ID_FIELD)
        if str(stop_gtfs_id) == str(search_gtfs_id):
            stop_id = stop_feat.GetField(STOP_ID_FIELD)
            break
    stops_lyr.ResetReading()
    return stop_id

def get_stop_with_id(stops_lyr, search_stop_id):
    stop_id_to_return = None
    for stop_feat in stops_lyr:
        stop_id = stop_feat.GetField(ROUTE_EXT_ID_FIELD)
        if str(stop_id) == str(search_stop_id):
            stop_id_to_return = stop_id
            break
    stops_lyr.ResetReading()
    return stop_id_to_return

def create_segs_shp_file(segs_shp_file_name, speed_model,
        delete_existing=False):
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

    speed_model.add_extra_needed_speed_fields(layer)

    print "... done."
    return segs_shp_file, layer

def add_route_to_seg(segments_lyr, seg_feat, route_name):
    orig_list = seg_feat.GetField(SEG_ROUTE_LIST_FIELD)
    upd_list = orig_list + ",%s" % route_name
    seg_feat.SetField(SEG_ROUTE_LIST_FIELD, upd_list)
    segments_lyr.SetFeature(seg_feat)
    return

def stop_default_name_from_id(stop_id, mode_config):
    return "%s%d" % (mode_config['stop_prefix'], stop_id)

def route_name_from_id(route_id, mode_config):
    return "%s%03d" % (mode_config['route_prefix'], route_id)

# NOTE : this is a specific simple data model for early simple GTFS creator
# work. Probably should generalise and just record an ID for each route in
# the actual shapefile/database.
def route_id_from_name(route_name):
    # prefixc characters could by 'R', 'M' etc.
    try:
        r_id = int(re.findall(r'\d+', route_name)[0])
    except IndexError:
        print "Error:- for route name '%s', couldn't extract an ID. "\
            "Route names should be of pattern text prefix followed by "\
            "a route number, e.g. 'R43', 'M002'." \
            % (route_name)
    return r_id

def get_stop_ids_of_seg(seg_feature):
    pt_a_name = seg_feature.GetField(SEG_STOP_1_NAME_FIELD)
    pt_b_name = seg_feature.GetField(SEG_STOP_2_NAME_FIELD)
    # Courtesy http://stackoverflow.com/questions/4289331/python-extract-numbers-from-a-string
    pt_a_id = int(re.findall(r'\d+', pt_a_name)[0])
    pt_b_id = int(re.findall(r'\d+', pt_b_name)[0])
    return pt_a_id, pt_b_id

def create_seg_geom_from_stop_pair(stop_feat_a, stop_feat_b, stops_srs):
    seg_geom = ogr.Geometry(ogr.wkbLineString)
    seg_geom.AssignSpatialReference(stops_srs)
    seg_geom.AddPoint(*stop_feat_a.GetGeometryRef().GetPoint(0))
    seg_geom.AddPoint(*stop_feat_b.GetGeometryRef().GetPoint(0))
    return seg_geom

def add_segment(segs_lyr, seg_id, seg_routes, stop_a_id, stop_b_id,
        route_dist_on_seg, seg_geom, mode_config,
        seg_free_speed=0.0, seg_peak_speed=0.0):
    """
    Add a single route segment to segments shape file, defined by input
    parameters.
    (mode_config paramenter needed at the moment, since we prefix stop ids
    with a letter based on mode at the moment in the shapefile.)

    NOTE:- not sure this is exactly how I should handle optional free and
    peak speeds, as arguments :- leave this till I refactor speed of segments
    properly anyway."""
    seg_ii = segs_lyr.GetFeatureCount()
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
    seg_feat.SetField(SEG_ROUTE_LIST_FIELD, ",".join(map(str, seg_routes)))
    seg_feat.SetField(SEG_STOP_1_NAME_FIELD,
        stop_default_name_from_id(stop_a_id, mode_config))
    seg_feat.SetField(SEG_STOP_2_NAME_FIELD,
        stop_default_name_from_id(stop_b_id, mode_config))
    # Rounding to nearest meter below per convention.
    seg_feat.SetField(SEG_ROUTE_DIST_FIELD, "%.0f" % route_dist_on_seg)
    segs_lyr.CreateFeature(seg_feat)
    seg_feat.Destroy()
    seg_geom2.Destroy()
    return seg_ii
    
def get_route_ext_with_id(route_exts_lyr, search_ext_id):
    route_ext_to_return = None
    for route_ext in route_exts_lyr:
        ext_id = route_ext.GetField(ROUTE_EXT_ID_FIELD)
        if str(ext_id) == str(search_ext_id):
            route_ext_to_return = route_ext
            break
    route_exts_lyr.ResetReading()
    return route_ext_to_return
