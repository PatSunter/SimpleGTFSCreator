#!/usr/bin/env python2

# This script just to create a new GTFS schedule based off an old one,
#  but subsetting the list of routes.

import os, sys
import os.path
import copy
import operator
import csv
import itertools
from optparse import OptionParser

from osgeo import ogr, osr

import misc_utils
import route_segs
import mode_timetable_info as m_t_info
import seg_speed_models
import topology_shapefile_data_model as tp_model
import time_periods_speeds_model as tps_speeds_model
import time_periods_hways_model as tps_hways_model

# We don't want to further round down already rounded values.
SPEED_ROUND_PLACES = 10

class Route_Subset_Spec:
    def __init__(self, short_name, long_name, first_stop, last_stop,
            upd_dir_1, upd_dir_2):     
        self.short_name = short_name
        self.long_name = long_name
        self.first_stop = first_stop
        self.last_stop = last_stop
        self.upd_dir_1 = upd_dir_1
        self.upd_dir_2 = upd_dir_2

def create_new_subset_route_def(stops_lyr, old_r_def, old_r_seg_refs,
        r_subset_spec, new_subset_r_id):
    print "    Creating new subset route %s b/w stops '%s' and '%s' ..." \
        % (misc_utils.get_route_print_name(r_subset_spec.short_name, \
            r_subset_spec.long_name), r_subset_spec.first_stop,
            r_subset_spec.last_stop)

    subset_r_def = copy.deepcopy(old_r_def)
    if r_subset_spec.short_name:
        subset_r_def.short_name = r_subset_spec.short_name
    if r_subset_spec.long_name:
        subset_r_def.long_name = r_subset_spec.long_name
    # We can't be sure of the order the break stops will be
    # encountered.
    subset_stop_first_id = tp_model.get_stop_id_with_name(stops_lyr,
        r_subset_spec.first_stop)
    subset_stop_last_id = tp_model.get_stop_id_with_name(stops_lyr,
        r_subset_spec.last_stop)

    #r_seg_refs = route_segs.create_ordered_seg_refs_from_ids(
    #    old_r_def.ordered_seg_ids, segs_lookup_table)
    old_r_stop_ids = route_segs.extract_stop_list_along_route(old_r_seg_refs)
    # Check that all break stops are included in the stop list
    if subset_stop_first_id not in old_r_stop_ids:
        print "Error:- first break stop with name '%s' not found "\
            "in stop list for route %s (%s)." \
            % (r_subset_spec.first_stop, old_r_def.short_name, old_r_def.long_name)
        sys.exit(1)
    if subset_stop_last_id not in old_r_stop_ids:
        print "Error:- last break stop with name '%s' not found "\
            "in stop list for route %s (%s)." \
            % (r_subset_spec.last_stop, old_r_def.short_name, \
               old_r_def.long_name)
        sys.exit(1)
    t_first_i = old_r_stop_ids.index(subset_stop_first_id)
    t_last_i = old_r_stop_ids.index(subset_stop_last_id)
    if t_first_i == t_last_i:
        print "Error:- both break stops with name '%s' are at same "\
            "place in route %s (%s)." \
            % (r_subset_spec.first_stop, old_r_def.short_name, \
               old_r_def.long_name)
        sys.exit(1)
    assert r_subset_spec.upd_dir_1 or r_subset_spec.upd_dir_2
    # Update the route directions, calc dir mappings.   
    upd_dirs = [r_subset_spec.upd_dir_1, r_subset_spec.upd_dir_2]
    dir_mappings = {}
    if t_last_i < t_first_i:
        upd_dirs.reverse()
    if not upd_dirs[0]:
        subset_r_def.dir_names = (old_r_def.dir_names[0], upd_dirs[1])
    elif not upd_dirs[1]:
        subset_r_def.dir_names = (upd_dirs[0], old_r_def.dir_names[1])
    else:    
        subset_r_def.dir_names = tuple(upd_dirs)

    dir_mappings[old_r_def.dir_names[0]] = subset_r_def.dir_names[0]
    dir_mappings[old_r_def.dir_names[1]] = subset_r_def.dir_names[1]

    # Now process the route segments :- add segments between the subset stops
    # defined to the new route.
    break_stop_ids_rem = [subset_stop_first_id, subset_stop_last_id]
    within_keep_section = False
    subset_r_seg_ids = []
    if old_r_stop_ids[0] in break_stop_ids_rem:
        break_stop_ids_rem.remove(old_r_stop_ids[0])
        within_keep_section = True
    for seg_ii, seg_ref in enumerate(old_r_seg_refs):
        if within_keep_section:
            subset_r_seg_ids.append(seg_ref.seg_id)
            seg_ref.routes.append(new_subset_r_id)
        # Now update the within keep status for next seg.
        seg_second_stop_id = old_r_stop_ids[seg_ii+1]
        if seg_second_stop_id in break_stop_ids_rem:
            break_stop_ids_rem.remove(seg_second_stop_id)
            if len(break_stop_ids_rem) == 0:
                break
            within_keep_section = not within_keep_section

    subset_r_def.ordered_seg_ids = subset_r_seg_ids
    subset_r_def.id = new_subset_r_id
    return subset_r_def, dir_mappings

def remove_links_to_route_from_seg_refs(r_id, r_seg_refs):
    for seg_ii, seg_ref in enumerate(r_seg_refs):
        seg_ref.routes.remove(int(r_id))
    return

def remove_empty_seg_refs_from_dict(r_seg_refs, seg_refs_dict):
    for seg_ii, seg_ref in enumerate(r_seg_refs):
        if len(seg_ref.routes) == 0:
            # Get rid of segments not used by any route.
            del(seg_refs_dict[seg_ref.seg_id])
    return

def create_updated_speeds_entries(input_speeds_dir, output_speeds_dir,
        input_r_defs, removed_r_def_tuples, updated_dir_mappings_by_id,
        stop_id_to_gtfs_stop_id_map, output_seg_refs_dict):
    print "Creating new route segment speed files in dir %s:" \
        % output_speeds_dir
    if not os.path.exists(output_speeds_dir):
        os.makedirs(output_speeds_dir)
    # For routes that haven't changed:- just copy them across.

    for r_def in input_r_defs:
        if r_def not in itertools.imap(operator.itemgetter(0),
                removed_r_def_tuples):
            tps_speeds_model.copy_route_speeds(r_def.short_name,
                r_def.long_name, input_speeds_dir, output_speeds_dir)
    # For routes to be removed:- need to open and process new sub-routes
    for old_r_def, new_subset_r_defs_this_route in removed_r_def_tuples:
        # Open the old route speeds files
        route_speeds_fnames = tps_speeds_model.get_avg_speeds_fnames(
            input_speeds_dir, old_r_def.short_name, old_r_def.long_name)
        assert len(route_speeds_fnames) >= 1
        
        subset_routes_seg_refs = {}
        for subset_r_def in new_subset_r_defs_this_route:
            subset_routes_seg_refs[subset_r_def.id] = map(
                lambda seg_id: output_seg_refs_dict[seg_id],
                subset_r_def.ordered_seg_ids)

        for route_speeds_fname in route_speeds_fnames:
            name_a, name_b, trips_dir_file_ready, serv_period = \
                tps_speeds_model.get_info_from_fname(route_speeds_fname,
                    old_r_def.short_name, old_r_def.long_name)
            time_periods, route_avg_speeds_in, seg_distances_in, \
                    stop_gtfs_ids_to_names_map = \
                tps_speeds_model.read_avg_speeds_on_segments(
                    route_speeds_fname, sort_seg_stop_id_pairs=False)        

            for subset_r_def in new_subset_r_defs_this_route:
                # Create new speeds file in output dir from relevant entries
                seg_refs = subset_routes_seg_refs[subset_r_def.id]
                if trips_dir_file_ready == misc_utils.routeDirStringToFileReady(
                        old_r_def.dir_names[0]):
                    old_dir_name = old_r_def.dir_names[0]
                    dir_index = 0
                else:
                    old_dir_name = old_r_def.dir_names[1]
                    dir_index = 1
                dir_mappings = updated_dir_mappings_by_id[subset_r_def.id]
                subset_dir_name = dir_mappings[old_dir_name]
                    
                route_avg_speeds_out = {}
                seg_distances_out = {}
                for seg_ii, seg_ref in enumerate(seg_refs):
                    # Now order the stops in direction of travel and get GTFS IDs
                    stop_ids_ordered = route_segs.get_stop_ids_in_travel_dir(
                        seg_refs, seg_ii, dir_index)
                    seg_gtfs_ids = tp_model.get_gtfs_stop_ids(stop_ids_ordered,
                        stop_id_to_gtfs_stop_id_map, to_str=True)
                    try:
                        route_avg_speeds_out[seg_gtfs_ids] = \
                            route_avg_speeds_in[seg_gtfs_ids]
                        seg_distances_out[seg_gtfs_ids] = \
                            seg_distances_in[seg_gtfs_ids]
                    except KeyError:
                        # The file we are reading mightn't have a value for this
                        # segment (stop pair) in this time period, given GTFS
                        # origin. If so, we just don't copy.
                        pass

                out_fname = \
                    tps_speeds_model.get_route_avg_speeds_for_dir_period_fname(
                        subset_r_def.short_name, subset_r_def.long_name,
                        serv_period, subset_dir_name)
                out_fpath = os.path.join(output_speeds_dir, out_fname)
                tps_speeds_model.write_avg_speeds_on_segments(
                    stop_gtfs_ids_to_names_map,
                    route_avg_speeds_out, seg_distances_out,
                    time_periods, out_fpath, SPEED_ROUND_PLACES)            
    return

def create_updated_hways_entries(input_hways_dir, output_hways_dir,
        input_r_defs, removed_r_def_tuples, updated_dir_mappings_by_id,
        stop_id_to_gtfs_stop_id_map, output_seg_refs_dict):
    print "Creating new route stop hways files in dir %s:" \
        % output_hways_dir
    if not os.path.exists(output_hways_dir):
        os.makedirs(output_hways_dir)
    # For routes that haven't changed:- just copy them across.

    for r_def in input_r_defs:
        if r_def not in itertools.imap(operator.itemgetter(0),
                removed_r_def_tuples):
            tps_hways_model.copy_route_hways(r_def.short_name,
                r_def.long_name, input_hways_dir, output_hways_dir)
    # For routes to be removed:- need to open and process new sub-routes
    for old_r_def, new_subset_r_defs_this_route in removed_r_def_tuples:
        # Open the old route hways files
        route_hways_fnames = tps_hways_model.get_hways_fnames(
            input_hways_dir, old_r_def.short_name, old_r_def.long_name)
        assert len(route_hways_fnames) >= 1
        
        subset_routes_seg_refs = {}
        for subset_r_def in new_subset_r_defs_this_route:
            subset_routes_seg_refs[subset_r_def.id] = map(
                lambda seg_id: output_seg_refs_dict[seg_id],
                subset_r_def.ordered_seg_ids)

        for route_hways_fname in route_hways_fnames:
            name_a, name_b, trips_dir_file_ready, serv_period = \
                tps_hways_model.get_info_from_fname(route_hways_fname,
                    old_r_def.short_name, old_r_def.long_name)
            time_periods, route_hways_in, \
                    stop_gtfs_ids_to_names_map = \
                tps_hways_model.read_headways_minutes(route_hways_fname)

            for subset_r_def in new_subset_r_defs_this_route:
                # Create new hways file in output dir from relevant entries
                seg_refs = subset_routes_seg_refs[subset_r_def.id]
                if trips_dir_file_ready == misc_utils.routeDirStringToFileReady(
                        old_r_def.dir_names[0]):
                    old_dir_name = old_r_def.dir_names[0]
                    dir_index = 0
                else:
                    old_dir_name = old_r_def.dir_names[1]
                    dir_index = 1
                dir_mappings = updated_dir_mappings_by_id[subset_r_def.id]
                subset_dir_name = dir_mappings[old_dir_name]
                    
                route_hways_out = {}
                stop_ids = route_segs.extract_stop_list_along_route(seg_refs)
                for stop_id in stop_ids:
                    stop_gtfs_id = str(stop_id_to_gtfs_stop_id_map[stop_id])
                    try:
                        route_hways_out[stop_gtfs_id] = \
                            route_hways_in[stop_gtfs_id]
                    except KeyError:
                        # The file we are reading mightn't have a value for this
                        # segment (stop pair) in this time period, given GTFS
                        # origin. If so, we just don't copy.
                        pass

                out_fname = \
                    tps_hways_model.get_route_hways_for_dir_period_fname(
                        subset_r_def.short_name, subset_r_def.long_name,
                        serv_period, subset_dir_name)
                out_fpath = os.path.join(output_hways_dir, out_fname)
                tps_hways_model.write_headways_minutes(
                    stop_gtfs_ids_to_names_map,
                    route_hways_out, 
                    time_periods, out_fpath)            
    return

def main():
    allowedServs = ', '.join(sorted(["'%s'" % key for key in \
        m_t_info.settings.keys()]))
    parser = OptionParser()
    parser.add_option('--input_route_defs', dest='input_route_defs', 
        help='CSV file listing name, directions, and segments of each route.')
    parser.add_option('--input_segments', dest='input_segments',
        help='Shapefile of line segments.')
    parser.add_option('--input_stops', dest='input_stops',
        help='Shapefile of stops.')
    parser.add_option('--output_route_defs', dest='output_route_defs', 
        help='CSV file (to create) listing name, directions, and '\
            'segments of each route.')
    parser.add_option('--output_segments', dest='output_segments',
        help='(Output) shapefile of line segments.')
    parser.add_option('--route_break_spec_csv', dest='route_break_spec_csv',
        help='Path to CSV file containing list of routes to break, and '
            'stops to break between.')
    parser.add_option('--service', dest='service',
        help="Should be one of %s" % allowedServs)
    parser.add_option('--input_speeds_dir', dest='input_speeds_dir',
        help="(Optional) Path of directory containing speeds for input routes"
            "- will be updated to output_speeds_dir.")
    parser.add_option('--output_speeds_dir', dest='output_speeds_dir',
        help="(Optional) Path of directory to save output speeds to."\
            "(Requires input_speeds_dir also specified).")
    parser.add_option('--input_hways_dir', dest='input_hways_dir',
        help="(Optional) Path of directory containing hways for input routes"
            "- will be updated to output_hways_dir.")
    parser.add_option('--output_hways_dir', dest='output_hways_dir',
        help="(Optional) Path of directory to save output hways to."\
            "(Requires input_hways_dir also specified).")
    (options, args) = parser.parse_args()

    if options.route_break_spec_csv is None:
        parser.print_help()
        parser.error("No route break specs CSV file given.")
    if options.service not in m_t_info.settings:
        parser.print_help()
        parser.error("Service option requested '%s' not in allowed set, of %s" \
            % (options.service, allowedServs))
    mode_config = m_t_info.settings[options.service]

    input_speeds_dir = None
    output_speeds_dir = None
    if options.input_speeds_dir:
        input_speeds_dir = options.input_speeds_dir
        if not os.path.exists(input_speeds_dir):
            parser.print_help()
            parser.error("input_speeds_dir specified %s doesn't exist." \
                % input_speeds_dir)
        output_speeds_dir = options.output_speeds_dir
        if not output_speeds_dir:    
            parser.print_help()
            parser.error("input_speeds_dir specified, but no corresponding "\
                "output speeds dir was.")

    input_hways_dir = None
    output_hways_dir = None
    if options.input_hways_dir:
        input_hways_dir = options.input_hways_dir
        if not os.path.exists(input_hways_dir):
            parser.print_help()
            parser.error("input_hways_dir specified %s doesn't exist." \
                % input_hways_dir)
        output_hways_dir = options.output_hways_dir
        if not output_hways_dir:    
            parser.print_help()
            parser.error("input_hways_dir specified, but no corresponding "\
                "output hways dir was.")


    # Get the list of route IDs we're going to break
    #try:
    #    route_breaks = get_route_def_and_break_stop_specs_from_csv(
    #        options.route_break_spec_csv)
    #except IOError:
    #    parser.print_help()
    #    print "\nError, route trip spec CSV file given, %s , failed to open." \
    #        % (options.route_break_spec_csv)
    #    sys.exit(1)
    route_breaks = None
    #TODO: read properly in from a file.
    rt_901_spec = route_segs.Route_Def(None, "901", None, (None, None), None)
    rt_901_subset = Route_Subset_Spec("901", 
        "Frankston - The Pines SC (SMARTBUS Service)",
        "Frankston Station/Young St",
        "The Pines SC/Reynolds Rd",
        "The Pines SC",
        None)
    rt_911_subset = Route_Subset_Spec("911", 
        "The Pines SC - Melbourne Airport (SMARTBUS Service)",
        "The Pines SC/Reynolds Rd",
        "Melbourne Airport/Arrival Dr",
        None,
        "The Pines SC")
    rt_902_spec = route_segs.Route_Def(None, "902", None, (None, None), None)
    rt_902_subset = Route_Subset_Spec("902", 
        "Chelsea Station - Doncaster Shoppingtown (SMARTBUS Service)",
        "Chelsea Railway Station/Station St",
        "Doncaster SC/Williamsons Rd",
        "Doncaster Shoppingtown",
        None)
    rt_912_subset = Route_Subset_Spec("912", 
        "Doncaster Shoppingtown - Airport West (SMARTBUS Service)",
        "Doncaster SC/Williamsons Rd",
        "Airport West Shoppingtown/Louis St",
        None,
        "Doncaster Shoppingtown")
    rt_903_spec = route_segs.Route_Def(None, "903", None, (None, None), None)
    rt_903_subset = Route_Subset_Spec("903", 
        "Mordialloc - Northland Shopping Centre (SMARTBUS Service)",
        "Mordialloc Shopping Centre/Centre Way",
        "Northland Shopping Centre/Murray Rd",
        "Northland Shopping Centre",
        None)
    rt_913_subset = Route_Subset_Spec("913", 
        "Northland Shopping Centre - Essendon Station (SMARTBUS Service)",
        "Northland Shopping Centre/Murray Rd",
        "Essendon Railway Station/Russell St",
        "Essendon Station",
        "Northland Shopping Centre")
    rt_933_subset = Route_Subset_Spec("933", 
        "Essendon Station to Altona via Sunshine (SMARTBUS Service)",
        "Essendon Railway Station/Russell St",
        "Altona Railway Station/Railway St South",
        "Altona",
        "Essendon Station")

    route_breaks = [
        (rt_901_spec, (rt_901_subset, rt_911_subset)),
        (rt_902_spec, (rt_902_subset, rt_912_subset)),
        (rt_903_spec, (rt_903_subset, rt_913_subset, rt_933_subset)),
        ]

    print "Read in the list of %d routes you want to break ..." \
        % len(route_breaks)

    # Load the route defs from file
    in_r_defs = route_segs.read_route_defs(options.input_route_defs,
        do_sort=False)
    # Load the segments and stops from file
    stops_shp = ogr.Open(options.input_stops)
    stops_lyr = stops_shp.GetLayer(0)
    # Copy the segments from input to output shape, and build lookup table.
    input_segs_shp = ogr.Open(options.input_segments)
    input_segs_lyr = input_segs_shp.GetLayer(0)
    output_seg_refs_dict = {}
    for seg_feat in input_segs_lyr:
        seg_ref = route_segs.seg_ref_from_feature(seg_feat)
        output_seg_refs_dict[seg_ref.seg_id] = seg_ref
    #segs_lookup_table = tp_model.build_segs_lookup_table(output_segs_lyr)

    output_r_defs = copy.deepcopy(in_r_defs)
    removed_r_def_tuples = []
    curr_max_r_id = max(output_r_defs, key=operator.attrgetter('id')).id
    updated_dir_mappings_by_id = {}
    print "Starting breaking these routes:"
    for r_def_spec, r_subset_specs in route_breaks:
        print "  Breaking route %s into %d sub-routes ..." \
            % (misc_utils.get_route_print_name(r_def_spec.short_name, \
                r_def_spec.long_name), len(r_subset_specs))

        match_r_defs = route_segs.get_matching_route_defs(output_r_defs, r_def_spec)
        if len(match_r_defs) == 0:
            print "Error:- the route you specified to be broken, with "\
                "ID %s, short name '%s', long name '%s' - not found in "\
                "list of routes specified in file %s ." %\
                (r_def_spec.id, r_def_spec.short_name, r_def_spec.long_name,\
                 options.input_route_defs)
            sys.exit(1)
        elif len(match_r_defs) > 1:
            print "Error:- the route you specified to be broken, with "\
                "ID %s, short name '%s', long name '%s' - matched multiple "\
                "routes of those specified in file %s ." %\
                (r_def_spec.id, r_def_spec.short_name, r_def_spec.long_name,\
                 options.input_route_defs)
            sys.exit(1)
        old_r_def = match_r_defs[0]

        old_r_seg_refs = [output_seg_refs_dict[s_id] for s_id in \
            old_r_def.ordered_seg_ids]

        new_subset_r_defs_this_route = []
        for r_subset_spec in r_subset_specs:
            new_r_id = curr_max_r_id + 1
            subset_r_def, dir_mappings = create_new_subset_route_def(stops_lyr,
                old_r_def, old_r_seg_refs, r_subset_spec, new_r_id)
            print "    ...route subset created with %d segments of original %d." \
                % (len(subset_r_def.ordered_seg_ids), len(old_r_seg_refs))
            new_subset_r_defs_this_route.append(subset_r_def)
            curr_max_r_id += 1
            updated_dir_mappings_by_id[new_r_id] = dir_mappings

        remove_links_to_route_from_seg_refs(old_r_def.id, old_r_seg_refs)
        remove_empty_seg_refs_from_dict(old_r_seg_refs, output_seg_refs_dict)
        output_r_defs.remove(old_r_def)
        output_r_defs += new_subset_r_defs_this_route
        # These lists useful if doing speed/hway updating later
        removed_r_def_tuples.append((old_r_def, new_subset_r_defs_this_route))

    # Write updated route defs
    route_segs.write_route_defs(options.output_route_defs, output_r_defs)
    # Write updated segments file
    # TODO:- would be good to auto-detect this based on segment fields
    speed_model = seg_speed_models.MultipleTimePeriodsPerRouteSpeedModel("")
    output_segs_shp, output_segs_lyr = tp_model.create_segs_shp_file(
        options.output_segments, speed_model, delete_existing=True)
    output_seg_refs = map(operator.itemgetter(1), sorted(
        output_seg_refs_dict.iteritems()))
    route_segs.write_segments_to_shp_file(output_segs_lyr, stops_lyr, 
        output_seg_refs, mode_config)
    # Force write
    output_segs_shp.Destroy()

    stop_id_to_gtfs_stop_id_map = None
    if input_speeds_dir or input_hways_dir:
        stop_id_to_gtfs_stop_id_map = tp_model.build_stop_id_to_gtfs_stop_id_map(
            stops_lyr)

    # Now :- if specified, update the speed and headway files.
    if input_speeds_dir:
        create_updated_speeds_entries(input_speeds_dir, output_speeds_dir,
            in_r_defs, removed_r_def_tuples, updated_dir_mappings_by_id,
            stop_id_to_gtfs_stop_id_map, output_seg_refs_dict)

    if input_hways_dir:
        create_updated_hways_entries(input_hways_dir, output_hways_dir,
            in_r_defs, removed_r_def_tuples, updated_dir_mappings_by_id,
            stop_id_to_gtfs_stop_id_map, output_seg_refs_dict)

    # Cleanup
    input_segs_shp.Destroy()
    stops_shp.Destroy()
    return

if __name__ == "__main__":
    main()

