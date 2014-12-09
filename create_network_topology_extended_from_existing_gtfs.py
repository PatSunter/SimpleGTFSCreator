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

def create_extended_route_def(r_def_to_extend, r_ext_info,
        exist_segs_lookup_table, ext_seg_refs):
    init_seg_ref_ids = r_def_to_extend.ordered_seg_ids
    ext_seg_ref_ids = map(operator.attrgetter('seg_id'), ext_seg_refs)
    # Ok:- we need to ensure connecting stop is at one of the ends,
    #  and update seg refs list appropriately.
    seg_refs_along_route = route_segs.create_ordered_seg_refs_from_ids(
        init_seg_ref_ids, exist_segs_lookup_table)
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
        all_stops_lyr, route_ext_infos, route_exts_lyr,
        auto_create_route_gtfs_ids=False):

    existing_segs_lookup_table = tp_model.build_segs_lookup_table(
        existing_segs_lyr)

    existing_route_infos_to_extend = route_segs.get_route_infos_to_extend(
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

    if auto_create_route_gtfs_ids:
        max_exist_gtfs_r_id = max(map(lambda x: int(x.gtfs_origin_id),
            existing_route_defs))
        # Increase to next 1000.
        next_new_gtfs_r_id = (int(max_exist_gtfs_r_id / 1000) + 1) * 1000

    new_ext_r_ids = []
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
        new_ext_r_ids.append(r_id)

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

        new_ext_seg_refs, new_seg_refs_cnt = \
            create_segs.create_segments_along_route(
                r_ext_info.ext_name, r_id, route_ext_geom, 
                all_stops_lyr, stops_near_route, stops_near_route_map,
                combined_seg_refs, warn_not_start_end=False)

        if len(new_ext_seg_refs) == 0:
            print "Error, no new route segments generated for the "\
                "new/extended part of route extension %s."\
                % r_ext_info.ext_name
            sys.exit(1)

        if r_ext_info.ext_type == tp_model.ROUTE_EXT_TYPE_NEW:
            new_r_def = create_new_route_def_extend_existing(
                r_def_to_extend, r_ext_info,
                r_id, connecting_stop_id, orig_route_first_stop_id,
                existing_segs_lookup_table, new_ext_seg_refs)
        elif r_ext_info.ext_type == tp_model.ROUTE_EXT_TYPE_EXTENSION:
            new_r_def = create_extended_route_def(r_def_to_extend, r_ext_info, 
                existing_segs_lookup_table, new_ext_seg_refs)
        else:
            assert 0
        
        if auto_create_route_gtfs_ids:
            new_r_def.gtfs_origin_id = next_new_gtfs_r_id
            next_new_gtfs_r_id += 1
    
        if r_ext_info.ext_type == tp_model.ROUTE_EXT_TYPE_NEW:
            combined_route_defs.append(new_r_def)
        elif r_ext_info.ext_type == tp_model.ROUTE_EXT_TYPE_EXTENSION:
            # Replace in the combined route defs
            to_replace_index = None
            for r_ii, r_def in enumerate(combined_route_defs):
                if r_def.id == r_id:
                    to_replace_index = r_ii
                    break
            assert to_replace_index is not None
            combined_route_defs[to_replace_index] = new_r_def
        else:
            assert 0
        route_ext_feat.Destroy()
    stops_multipoint.Destroy()
    # Set all the new seg refs to be part of the new routes.
    # Only do this at the end since the list is being added to until now.
    combined_seg_refs_lookup = route_segs.build_seg_refs_lookup_table(
        combined_seg_refs)
    for r_def in combined_route_defs:
        r_id = r_def.id
        if r_id in new_ext_r_ids:
            for seg_id in r_def.ordered_seg_ids:
                seg_ref = combined_seg_refs_lookup[seg_id]
                route_segs.add_route_to_seg_ref(seg_ref, r_id)
                
    return combined_route_defs, combined_seg_refs

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
    existing_segs_lyr, existing_segs_shp = tp_model.open_check_shp_lyr(
        options.existing_segments, "existing route segments")
    existing_stops_lyr, existing_stops_shp = tp_model.open_check_shp_lyr(
        options.existing_stops, "existing route stops")
    # Read extended
    route_exts_lyr, route_exts_shp = tp_model.open_check_shp_lyr(
        options.route_extensions, "route extensions")
    ext_stops_lyr, ext_stops_shp = tp_model.open_check_shp_lyr(
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
            mode_config,
            delete_existing=DELETE_EXISTING, 
            gtfs_origin_field=True,
            auto_create_added_gtfs_ids=True)

    route_ext_infos = route_segs.read_route_ext_infos(route_exts_lyr)
    print "New /extended routes read in, defined as follows:"
    route_segs.print_route_ext_infos(route_ext_infos) 

    # Now create extended segments and route defs
    output_route_defs, all_seg_refs = create_extended_topology(
        existing_route_defs, existing_segs_lyr, all_stops_lyr,
        route_ext_infos, route_exts_lyr,
        auto_create_route_gtfs_ids=True)

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

