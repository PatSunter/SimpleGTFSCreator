#!/usr/bin/env python2
import os
import os.path
import sys
import copy
import operator
from optparse import OptionParser

import osgeo.ogr
from osgeo import ogr, osr

import topology_shapefile_data_model as tp_model
import route_segs
import route_geom_ops
import seg_speed_models
import mode_timetable_info as m_t_info
import create_network_topology_segments as create_segs

DELETE_EXISTING = True

class Route_Ext_Info:
    def __init__(self, ext_id, ext_name, ext_type, exist_r_s_name, exist_r_l_name,
            exist_r_connect_stop_gtfs_id, exist_r_first_stop_gtfs_id,
            upd_r_short_name, upd_r_long_name, upd_dir_name):
        self.ext_id = ext_id
        self.ext_name = ext_name
        self.ext_type = ext_type
        self.exist_r_short_name = exist_r_s_name
        self.exist_r_long_name = exist_r_l_name
        self.exist_r_connect_stop_gtfs_id = exist_r_connect_stop_gtfs_id
        self.exist_r_first_stop_gtfs_id = exist_r_first_stop_gtfs_id
        self.upd_r_short_name = upd_r_short_name
        self.upd_r_long_name = upd_r_long_name
        self.upd_dir_name = upd_dir_name

        assert ext_type in tp_model.ROUTE_EXT_ALL_TYPES
        assert self.exist_r_connect_stop_gtfs_id is not None
        if ext_type == tp_model.ROUTE_EXT_TYPE_NEW:
            assert self.exist_r_first_stop_gtfs_id is not None
        assert upd_dir_name
        return

def read_route_ext_infos(route_exts_lyr):
    route_ext_infos = []
    for r_ext_i, route_ext_feat in enumerate(route_exts_lyr):
        ext_id = route_ext_feat.GetField(tp_model.ROUTE_EXT_ID_FIELD)
        ext_name = route_ext_feat.GetField(tp_model.ROUTE_EXT_NAME_FIELD)
        ext_type = route_ext_feat.GetField(tp_model.ROUTE_EXT_TYPE_FIELD)
        exist_r_s_name = \
            route_ext_feat.GetField(tp_model.ROUTE_EXT_EXIST_S_NAME_FIELD)
        exist_r_l_name = \
            route_ext_feat.GetField(tp_model.ROUTE_EXT_EXIST_L_NAME_FIELD)
        exist_r_connect_stop_gtfs_id = \
            route_ext_feat.GetField(tp_model.ROUTE_EXT_CONNECTING_STOP_FIELD)
        exist_r_first_stop_gtfs_id = \
            route_ext_feat.GetField(tp_model.ROUTE_EXT_FIRST_STOP_FIELD)
        if not exist_r_first_stop_gtfs_id:
            exist_r_first_stop_gtfs_id = None
        upd_r_short_name = \
            route_ext_feat.GetField(tp_model.ROUTE_EXT_UPD_S_NAME_FIELD)
        upd_r_long_name = \
            route_ext_feat.GetField(tp_model.ROUTE_EXT_UPD_L_NAME_FIELD)
        upd_dir_name = \
            route_ext_feat.GetField(tp_model.ROUTE_EXT_UPD_DIR_NAME_FIELD)
        route_ext_info = Route_Ext_Info(ext_id, ext_name, ext_type,
            exist_r_s_name, exist_r_l_name,
            exist_r_connect_stop_gtfs_id, exist_r_first_stop_gtfs_id,
            upd_r_short_name, upd_r_long_name, upd_dir_name)
        route_ext_infos.append(route_ext_info)    
    route_exts_lyr.ResetReading()
    return route_ext_infos

def print_route_ext_infos(route_ext_infos, indent=4):
    for re in route_ext_infos:
        print " " * indent + "Ext id:%s, '%s', of type %s"\
            % (re.ext_id, re.ext_name, re.ext_type)
        print " " * indent * 2 + "connects to existing route '%s' "\
            "('%s'), at GTFS stop ID %s" \
            % (re.exist_r_short_name, re.exist_r_long_name, \
               re.exist_r_connect_stop_gtfs_id)
        if re.ext_type == tp_model.ROUTE_EXT_TYPE_NEW:
            print " " * indent * 2 + "(new route will copy starting from "\
                "stop with GTFS ID %s)"\
                % (re.exist_r_first_stop_gtfs_id)
        print " " * indent * 2 + "will update r name to '%s':'%s' "\
            "and new/updated dir name as '%s'." \
            % (re.upd_r_short_name, re.upd_r_long_name, \
               re.upd_dir_name)
    return

def get_matching_existing_route_info(
        route_defs, segs_lyr, segs_lookup_table, stops_lyr,
        route_ext_info):
    # Find the route def, stops, etc of matching route in existing topology
    search_route_def = route_segs.Route_Def(
        None, 
        route_ext_info.exist_r_short_name,
        route_ext_info.exist_r_long_name,
        None, None)

    matching_r_defs = route_segs.get_matching_route_defs(route_defs,
        search_route_def)
    if len(matching_r_defs) == 0:
        print "Error:- for route extension %s with s name %s, l name %s: "\
            "no matching existing routes!" \
            % (route_ext_info.ext_name, route_ext_info.exist_r_short_name,\
               route_ext_info.exist_r_long_name)
        sys.exit(1)
    elif len(matching_r_defs) > 1:
        print "Error:- for route extension %s with s name %s, l name %s: "\
            "matched multiple existing routes!" \
            % (route_ext_info.ext_name, route_ext_info.exist_r_short_name,\
               route_ext_info.exist_r_long_name)
        sys.exit(1)
    r_def_to_extend = matching_r_defs[0]

    seg_refs_along_route = route_segs.create_ordered_seg_refs_from_ids(
        r_def_to_extend.ordered_seg_ids, segs_lookup_table)
    stop_ids_along_route = route_segs.extract_stop_list_along_route(
        seg_refs_along_route)
    
    connect_stop_id = tp_model.get_stop_id_with_gtfs_id(
        stops_lyr, route_ext_info.exist_r_connect_stop_gtfs_id)

    if connect_stop_id is None:
        print "Error:- extension route with connecting stop spec. "\
            "with GTFS ID %s :- couldn't find an existing stop with "\
            "this GTFS ID."\
            % (route_ext_info.exist_r_connect_stop_gtfs_id)
        sys.exit()
    elif connect_stop_id not in stop_ids_along_route:
        print "Error:- extension route with connecting stop spec. "\
            "with GTFS ID %s exists, but not found in route to extend." \
            % (route_ext_info.exist_r_connect_stop_gtfs_id)
        sys.exit()
    
    if route_ext_info.ext_type == tp_model.ROUTE_EXT_TYPE_EXTENSION:
        if connect_stop_id == stop_ids_along_route[-1]:
            ext_dir_id = 0
        elif connect_stop_id == stop_ids_along_route[0]:
            ext_dir_id = -1
        else:
            print "Error:- extension route with connecting stop spec. "\
                "with GTFS ID %s not found at end of route to extend."\
            % (route_ext_info.exist_r_connect_stop_gtfs_id)
            sys.exit(1)
    # For new routes, the connecting stop can legitimately be 
    #  anywhere along the route.

    orig_route_first_stop_id = tp_model.get_stop_id_with_gtfs_id(
        stops_lyr, route_ext_info.exist_r_first_stop_gtfs_id)

    return r_def_to_extend, seg_refs_along_route, stop_ids_along_route, \
        connect_stop_id, orig_route_first_stop_id

def get_route_infos_to_extend(route_ext_infos, route_defs, segs_lyr,
        segs_lookup_table, stops_lyr):
    """Returns the existing_route_infos_to_extend in the form:- 
    (r_def_to_extend, seg_refs_along_route, stop_ids_along_route,
      connect_stop_id)"""
    existing_route_infos_to_extend = []
    for r_ext_info in route_ext_infos:
        route_info_to_extend = get_matching_existing_route_info(
            route_defs, segs_lyr, segs_lookup_table, stops_lyr,
            r_ext_info)
        existing_route_infos_to_extend.append(route_info_to_extend)        
    return existing_route_infos_to_extend     
     
def create_extended_route_def(r_def_to_extend, r_ext_info,
        segs_lookup_table, ext_seg_refs):
    init_seg_ref_ids = r_def_to_extend.ordered_seg_ids
    ext_seg_ref_ids = map(operator.attrgetter('seg_id'), ext_seg_refs)
    # Ok:- we need to ensure connecting stop is at one of the ends,
    #  and update seg refs list appropriately.
    seg_refs_along_route = route_segs.create_ordered_seg_refs_from_ids(
        init_seg_ref_ids, segs_lookup_table)
    stop_ids_along_route = route_segs.extract_stop_list_along_route(
        seg_refs_along_route)
    stop_ids_of_extension = route_segs.extract_stop_list_along_route(
        ext_seg_refs)

    if stop_ids_along_route[-1] == stop_ids_of_extension[0]:
        combined_seg_ref_ids = init_seg_ref_ids + ext_seg_ref_ids
        updated_dir_names = \
            (r_ext_info.upd_dir_name, r_def_to_extend.dir_names[1])
    elif stop_ids_along_route[-1] == stop_ids_of_extension[-1]:
        combined_seg_ref_ids = init_seg_ref_ids + \
            list(reversed(ext_seg_ref_ids))
        updated_dir_names = \
            (r_ext_info.upd_dir_name, r_def_to_extend.dir_names[1])
    elif stop_ids_along_route[0] == stop_ids_of_extension[-1]:
        # Trickier:- need to insert the extensions at the start, thus
        # preserving direction of original section
        combined_seg_ref_ids = ext_seg_ref_ids + init_seg_ref_ids
        updated_dir_names = \
            (r_def_to_extend.dir_names[0], r_ext_info.upd_dir_name)
    elif stop_ids_along_route[0] == stop_ids_of_extension[0]:
        # Insert at front, also reversed.
        combined_seg_ref_ids = list(reversed(ext_seg_ref_ids)) \
            + init_seg_ref_ids
        updated_dir_names = \
            (r_def_to_extend.dir_names[0], r_ext_info.upd_dir_name)
    else:
        # Shouldn't reach this case for an extended route.
        assert 0

    if r_ext_info.upd_r_short_name:
        r_short_name = r_ext_info.upd_r_short_name
    else:
        r_short_name = r_def_to_extend.short_name
    if r_ext_info.upd_r_long_name:
        r_long_name = r_ext_info.upd_r_long_name
    else:
        r_long_name = r_def_to_extend.long_name

    extended_r_def = route_segs.Route_Def(
        r_def_to_extend.id,
        r_short_name,
        r_long_name,
        updated_dir_names,
        combined_seg_ref_ids)

    return extended_r_def

def create_new_route_def_extend_existing(r_def_to_extend, r_ext_info,
        new_r_id, connecting_stop_id, orig_route_first_stop_id,
        segs_lookup_table, ext_seg_refs):

    init_seg_ref_ids = r_def_to_extend.ordered_seg_ids
    ext_seg_ref_ids = map(operator.attrgetter('seg_id'), ext_seg_refs)
    # Ok:- we need to ensure connecting stop is at one of the ends,
    #  and update seg refs list appropriately.
    seg_refs_along_route = route_segs.create_ordered_seg_refs_from_ids(
        init_seg_ref_ids, segs_lookup_table)
    stop_ids_along_route = route_segs.extract_stop_list_along_route(
        seg_refs_along_route)
    stop_ids_of_extension = route_segs.extract_stop_list_along_route(
        ext_seg_refs)

    assert connecting_stop_id in (stop_ids_of_extension[0], \
        stop_ids_of_extension[-1])

    first_index = stop_ids_along_route.index(orig_route_first_stop_id)
    connecting_index = stop_ids_along_route.index(connecting_stop_id)

    assert first_index != connecting_index
    if connecting_index > first_index:
        init_seg_ref_ids_to_use = init_seg_ref_ids[first_index:connecting_index]
        dir_name_to_keep = r_def_to_extend.dir_names[1]
    else:
        init_seg_ref_ids_to_use = list(reversed(
            init_seg_ref_ids[connecting_index:first_index]))
        dir_name_to_keep = r_def_to_extend.dir_names[0]

    if connecting_stop_id == stop_ids_of_extension[0]:
        combined_seg_ref_ids = init_seg_ref_ids_to_use + \
            ext_seg_ref_ids
    elif connecting_stop_id == stop_ids_of_extension[-1]:
        combined_seg_ref_ids = init_seg_ref_ids_to_use + \
            list(reversed(ext_seg_ref_ids))
    else:
        assert 0

    if r_ext_info.upd_r_short_name:
        r_short_name = r_ext_info.upd_r_short_name
    else:
        r_short_name = r_def_to_extend.short_name
    if r_ext_info.upd_r_long_name:
        r_long_name = r_ext_info.upd_r_long_name
    else:
        r_long_name = r_def_to_extend.long_name

    # Due to the algorithm above, the segments are now always listed in the
    # order of going _to_ the extension.
    dir_names = (r_ext_info.upd_dir_name, dir_name_to_keep)

    new_r_def = route_segs.Route_Def(
        new_r_id, 
        r_short_name,
        r_long_name,
        dir_names,
        combined_seg_ref_ids)

    return new_r_def

def create_extended_topology( existing_route_defs, existing_segs_lyr,
        all_stops_lyr, route_ext_infos, route_exts_lyr):

    existing_segs_lookup_table = tp_model.build_segs_lookup_table(
        existing_segs_lyr)

    existing_route_infos_to_extend = get_route_infos_to_extend(
        route_ext_infos, existing_route_defs, existing_segs_lyr,
        existing_segs_lookup_table, all_stops_lyr)

    # This 2nd list of route defs is the one we're going to manipulate
    # outputs in
    combined_route_defs = copy.deepcopy(existing_route_defs)

    existing_seg_refs = route_segs.get_all_seg_refs(existing_segs_lyr)
    route_exts_srs = route_exts_lyr.GetSpatialRef()
    target_srs = osr.SpatialReference()
    target_srs.ImportFromEPSG(route_geom_ops.COMPARISON_EPSG)
    route_transform = osr.CoordinateTransformation(route_exts_srs, target_srs)

    # This list is going to be extended with the new seg refs.
    combined_seg_refs = existing_seg_refs[:]

    # First, get a stops multipoint in right projection.
    stops_multipoint = route_geom_ops.build_multipoint_from_lyr(all_stops_lyr)
    route_geom_ops.reproject_all_multipoint(stops_multipoint, target_srs)

    max_exist_r_id = max(map(lambda x: int(x.id), existing_route_defs))
    next_new_r_id = max_exist_r_id + 1

    # OK, now actually process the route extension geometries, and then
    #  connect on to existing routes.
    for r_ext_info, existing_route_infos_to_extend in \
            zip(route_ext_infos, existing_route_infos_to_extend):
        # Get matching route_ext_feat and geom.
        route_ext_feat = tp_model.get_route_ext_with_id(route_exts_lyr,
            r_ext_info.ext_id)
        assert route_ext_feat
        # Unpack the tuple.
        r_def_to_extend, exist_seg_refs_along_route, \
            exist_stop_ids_along_route, connecting_stop_id, \
            orig_route_first_stop_id = \
            existing_route_infos_to_extend

        if r_ext_info.ext_type == tp_model.ROUTE_EXT_TYPE_NEW:
            r_id = next_new_r_id
            next_new_r_id += 1
        elif r_ext_info.ext_type == tp_model.ROUTE_EXT_TYPE_EXTENSION:
            r_id = r_def_to_extend.id
        else:
            assert 0

        # Get geom, transform into right SRS for stops comparison, and get
        # nearby stops
        route_ext_geom = route_ext_feat.GetGeometryRef()
        route_ext_geom.Transform(route_transform)
        stops_near_route, stops_near_route_map = \
            route_geom_ops.get_stops_near_route(route_ext_geom,
                stops_multipoint)
        if stops_near_route.GetGeometryCount() == 0:
            print "Error, no stops detected near route ext %s while creating "\
                "segments." % r_ext_info.ext_name
            sys.exit(1)
        if stops_near_route.GetGeometryCount() == 1:
            print "Error, only one stop detected near route ext %s while "\
                "creating segments." % r_ext_info.ext_name
            sys.exit(1)

        ext_seg_refs, new_seg_refs_cnt = \
            create_segs.create_segments_along_route(
                r_ext_info.ext_name, r_id, route_ext_geom, 
                all_stops_lyr, stops_near_route, stops_near_route_map,
                combined_seg_refs, warn_not_start_end=False)

        if len(ext_seg_refs) == 0:
            print "Error, no new route segments generated for the "\
                "new/extended part of route extension %s."\
                % r_ext_info.ext_name
            sys.exit(1)

        if r_ext_info.ext_type == tp_model.ROUTE_EXT_TYPE_NEW:
            new_r_def = create_new_route_def_extend_existing(
                r_def_to_extend, r_ext_info,
                r_id, connecting_stop_id, orig_route_first_stop_id,
                existing_segs_lookup_table, ext_seg_refs)
            combined_route_defs.append(new_r_def)
        elif r_ext_info.ext_type == tp_model.ROUTE_EXT_TYPE_EXTENSION:
            ext_r_def = create_extended_route_def(r_def_to_extend, r_ext_info, 
                existing_segs_lookup_table, ext_seg_refs)
            # Replace in the combined route defs
            to_replace_index = None
            for r_ii, r_def in enumerate(combined_route_defs):
                if r_def.id == r_id:
                    to_replace_index = r_ii
                    break
            assert to_replace_index is not None
            combined_route_defs[to_replace_index] = ext_r_def
        else:
            assert 0
        route_ext_feat.Destroy()
    stops_multipoint.Destroy()
    return combined_route_defs, combined_seg_refs

# Then, for each extended route geometry:-
# Cool :- should then have an updated route_def, segments shpfile
  # (And possibly stops shapefile, though shouldn't need to do this unless IDs
  # change).
  # :- which contains the 'extended routes'.

def open_check_shp_lyr(shp_filename, shp_description):
    if not shp_filename:
        print "Error, needed shape file of %s was given an empty path " \
            "string." % (shp_description)
        sys.exit(1)
    full_fname = os.path.expanduser(shp_filename)
    shp = osgeo.ogr.Open(full_fname, 0)
    if shp is None:
        print "Error, needed shape file of %s with given path %s failed "\
        "to open." % (shp_description, shp_filename)
        sys.exit(1)
    lyr = shp.GetLayer(0)    
    return lyr, shp

def main():
    allowedServs = ', '.join(sorted(["'%s'" % key for key in \
        m_t_info.settings.keys()]))
    parser = OptionParser()
    parser.add_option('--existing_route_defs', dest='existing_route_defs',
        help='Existing route definitions.')
    parser.add_option('--existing_segments', dest='existing_segments',
        help='Shapefile of existing line segments.')
    parser.add_option('--existing_stops', dest='existing_stops',
        help='Shapefile of existing stops.')
    parser.add_option('--route_extensions', dest='route_extensions',
        help='Shapefile containing route extension geometries and info.')
    parser.add_option('--extension_stops', dest='extension_stops',
        help='Shapefile of stops for line extensions.')
    parser.add_option('--output_route_defs', dest='output_route_defs',
        help='Path to write expanded set of route definitions, including '\
            'extensions, to (should end in .csv)')
    parser.add_option('--output_segments', dest='output_segments',
        help='Path to Shapefile of all line segments, including extensions, '
            'to create.')
    parser.add_option('--output_stops', dest='output_stops',
        help='Path to create new Shapefile combining existing and extended '\
            'stops.')
    parser.add_option('--service', dest='service',
        help="Should be one of %s" % allowedServs)
    (options, args) = parser.parse_args()    

    if not options.existing_route_defs:
        parser.print_help()
        parser.error("No (or empty) existing route defs file path given.")
    if not options.existing_segments:
        parser.print_help()
        parser.error("No (or empty) existing segments shapefile path given.")
    if not options.existing_stops:
        parser.print_help()
        parser.error("No (or empty) existing stops shapefile path given.")
    if not options.route_extensions:
        parser.print_help()
        parser.error("No (or empty) path to route extensions shapefile given.")
    if not options.extension_stops:
        parser.print_help()
        parser.error("No (or empty) route extension stops shapefile "\
            "path given.")
    if not options.output_route_defs:
        parser.print_help()
        parser.error("No (or empty) output route definitions CSV file path "\
            "given.")
    if not options.output_segments:
        parser.print_help()
        parser.error("No (or empty) output route segments shapefile "\
            "path given.")
    if not options.output_stops:
        parser.print_help()
        parser.error("No (or empty) output route stops shapefile path given.")
    if not options.service:
        parser.print_help()
        parser.error("No (or empty) service option requested. Should be one "
            "of %s" % (allowedServs))
    if options.service not in m_t_info.settings:
        parser.print_help()
        parser.error("Service option requested '%s' not in allowed set, of %s" \
            % (options.service, allowedServs))

    mode_config = m_t_info.settings[options.service]

    # Read Existing
    existing_route_defs = route_segs.read_route_defs(
        options.existing_route_defs)
    existing_segs_lyr, existing_segs_shp = open_check_shp_lyr(
        options.existing_segments, "existing route segments")
    existing_stops_lyr, existing_stops_shp = open_check_shp_lyr(
        options.existing_stops, "existing route stops")
    # Read extended
    route_exts_lyr, route_exts_shp = open_check_shp_lyr(
        options.route_extensions, "route extensions")
    ext_stops_lyr, ext_stops_shp = open_check_shp_lyr(
        options.extension_stops, "new/extended route stops")

    output_route_defs_fname = options.output_route_defs
    output_segments_fname = options.output_segments
    output_stops_fname = options.output_stops

    # create combined stops shpfile here, to get IDs right etc,
    # N.B.:- for now the auto create GTFS option is needed so
    #  that these stops can be assigned a speed later.
    all_stops_shp_file, all_stops_lyr = \
        tp_model.create_stops_shp_file_combined_from_existing(
            output_stops_fname,
            existing_stops_lyr, ext_stops_lyr,
            delete_existing=DELETE_EXISTING, 
            gtfs_origin_field=True,
            auto_create_added_gtfs_ids=True)

    route_ext_infos = read_route_ext_infos(route_exts_lyr)
    print "New /extended routes read in, defined as follows:"
    print_route_ext_infos(route_ext_infos) 

    # Now create extended segments and route defs
    output_route_defs, all_seg_refs = create_extended_topology(
        existing_route_defs, existing_segs_lyr, all_stops_lyr,
        route_ext_infos, route_exts_lyr)

    # Write out the (extended/added) per-route definition lists
    print "Now writing out extended route defs to %s:" \
        % (output_route_defs_fname)
    route_segs.write_route_defs(output_route_defs_fname, output_route_defs)

    # Now write extended segments to file.
    # NOTE:- maybe abstract this speed model in future 
    speed_model = seg_speed_models.MultipleTimePeriodsPerRouteSpeedModel("")
    all_segs_shp_file, all_segs_lyr = tp_model.create_segs_shp_file(
        output_segments_fname, speed_model, delete_existing=DELETE_EXISTING)
    route_segs.write_segments_to_shp_file(all_segs_lyr,
        all_stops_lyr, all_seg_refs, mode_config)

    # Force write to disk of new shpfiles
    all_stops_shp_file.Destroy()
    all_segs_shp_file.Destroy()

    # Cleanup input shapefiles.
    existing_segs_shp.Destroy()
    existing_stops_shp.Destroy()
    route_exts_shp.Destroy()
    ext_stops_shp.Destroy()

    return

if __name__ == "__main__":
    main()

