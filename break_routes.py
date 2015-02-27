#!/usr/bin/env python2

# This script just to create a new GTFS schedule based off an old one,
#  but subsetting the list of routes.

import os, sys
import os.path
import copy
import operator
import csv
from optparse import OptionParser

from osgeo import ogr, osr

import misc_utils
import route_segs
import mode_timetable_info as m_t_info
import seg_speed_models
import topology_shapefile_data_model as tp_model

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
    # Update the route directions    
    upd_dirs = [r_subset_spec.upd_dir_1, r_subset_spec.upd_dir_2]
    if t_last_i < t_first_i:
        upd_dirs.reverse()
    if not upd_dirs[0]:
        subset_r_def.dir_names = (old_r_def.dir_names[0], upd_dirs[1])
    elif not upd_dirs[1]:
        subset_r_def.dir_names = (upd_dirs[0], old_r_def.dir_names[1])
    else:    
        subset_r_def.dir_names = tuple(upd_dirs)
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
        # Now update the within keep status for next seg.
        seg_second_stop_id = old_r_stop_ids[seg_ii+1]
        if seg_second_stop_id in break_stop_ids_rem:
            break_stop_ids_rem.remove(seg_second_stop_id)
            if len(break_stop_ids_rem) == 0:
                break
            within_keep_section = not within_keep_section

    subset_r_def.ordered_seg_ids = subset_r_seg_ids
    subset_r_def.id = new_subset_r_id
    return subset_r_def

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
    parser.add_option('--service', dest='service',
        help="Should be one of %s" % allowedServs)
    parser.add_option('--output_route_defs', dest='output_route_defs', 
        help='CSV file (to create) listing name, directions, and '\
            'segments of each route.')
    parser.add_option('--output_segments', dest='output_segments',
        help='(Output) shapefile of line segments.')
    parser.add_option('--route_break_spec_csv', dest='route_break_spec_csv',
        help='Path to CSV file containing list of routes to break, and '
            'stops to break between.')
    (options, args) = parser.parse_args()

    if options.route_break_spec_csv is None:
        parser.print_help()
        parser.error("No route break specs CSV file given.")
    if options.service not in m_t_info.settings:
        parser.print_help()
        parser.error("Service option requested '%s' not in allowed set, of %s" \
            % (options.service, allowedServs))
    mode_config = m_t_info.settings[options.service]

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
    curr_max_r_id = max(output_r_defs, key=operator.attrgetter('id')).id
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

        for r_subset_spec in r_subset_specs:
            new_r_id = curr_max_r_id + 1
            subset_r_def = create_new_subset_route_def(stops_lyr, old_r_def,
                old_r_seg_refs, r_subset_spec, new_r_id)
            print "    ...route subset created with %d segments of original %d." \
                % (len(subset_r_def.ordered_seg_ids), len(old_r_seg_refs))
            output_r_defs.append(subset_r_def)
            curr_max_r_id += 1

        remove_links_to_route_from_seg_refs(old_r_def.id, old_r_seg_refs)
        remove_empty_seg_refs_from_dict(old_r_seg_refs, output_seg_refs_dict)
        output_r_defs.remove(old_r_def)

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
    # Cleanup
    input_segs_shp.Destroy()
    stops_shp.Destroy()
    return

if __name__ == "__main__":
    main()

