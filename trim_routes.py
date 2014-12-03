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

import route_segs
import mode_timetable_info as m_t_info
import seg_speed_models
import topology_shapefile_data_model as tp_model

def get_route_def_and_trim_stop_specs_from_csv(csv_fname):
    """Reads a CSV with rows of the format:
    (route_idents),first_stop_name,last_stop_name,dir1,dir2
    where:- route_idents can be one or more of 
    route_id, route_short_name, route_long_name - and must uniquely identify
    a route.
    first_stop_name, last_stop_name :- names of the stops you want to keep
    the route segments in-between. Segments outside this will be 'trimmed'
    from this row's specified route.
    dir1, dir2 :- if non-null, these are renamed route directions
    (likely worth changing since you are changing the stop end-points.)
    dir1, dir2 should be in the order such that 
    first_stop_name -> last_stop_name = dir1, and the reverse for dir2."""

    route_defs_and_trim_stops_and_dirs = []
    csv_file = open(csv_fname, 'r')
    dict_reader = csv.DictReader(csv_file, delimiter=',', quotechar="'")
    for csv_row in dict_reader:
        try:
            r_id = csv_row['route_id']
            if not r_id:
                r_id = None
            else:
                r_id = int(r_id)
        except KeyError:
            r_id = None
        try:
            short_name = csv_row['route_short_name']
            if not short_name:
                short_name = None
        except KeyError:
            short_name = None
        try:
            long_name = csv_row['route_long_name']
            if not long_name:
                long_name = None
        except KeyError:
            long_name = None
        if not (r_id or short_name or long_name):
            print "Error:- in trim spec CSV:- there is a row where no "\
                "route identifying info has been specified."
            sys.exit(1)
        r_def = route_segs.Route_Def(r_id, short_name, long_name, 
            (None, None), None)
        trim_first = csv_row['first_stop_name']
        trim_last = csv_row['last_stop_name']
        dir1 = csv_row['dir1']
        if not dir1:
            dir1 = None
        dir2 = csv_row['dir2']
        if not dir2:
            dir2 = None
        route_defs_and_trim_stops_and_dirs.append(
            (r_def, trim_first, trim_last,dir1,dir2))
    csv_file.close()
    return route_defs_and_trim_stops_and_dirs

def get_matching_route_def(r_defs, r_def_spec):
    for r_def in r_defs:
        if route_segs.route_defs_match_statuses(r_def, r_def_spec):
            return r_def
    return None            

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
    parser.add_option('--route_trim_spec_csv', dest='route_trim_spec_csv',
        help='Path to CSV file containing list of routes to trim, and '
            'stops to trim between.')
    (options, args) = parser.parse_args()

    if options.route_trim_spec_csv is None:
        parser.print_help()
        parser.error("No route trim specs CSV file given.")
    if options.service not in m_t_info.settings:
        parser.print_help()
        parser.error("Service option requested '%s' not in allowed set, of %s" \
            % (options.service, allowedServs))
    mode_config = m_t_info.settings[options.service]

    # Get the list of route IDs we're going to trim
    try:
        route_trims = get_route_def_and_trim_stop_specs_from_csv(
            options.route_trim_spec_csv)
    except IOError:
        parser.print_help()
        print "\nError, route trip spec CSV file given, %s , failed to open." \
            % (options.route_trim_spec_csv)
        sys.exit(1)

    # Load the route defs from file
    r_defs = route_segs.read_route_defs(options.input_route_defs)
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
    updated_r_defs = []
    for r_def_spec, trim_stop_first, trim_stop_second, upd_dir_1, upd_dir_2 \
            in route_trims:
        # We can't be sure of the order the trim stops will be
        # encountered.
        trim_stop_first_id = tp_model.get_stop_id_with_name(stops_lyr,
            trim_stop_first)
        trim_stop_second_id = tp_model.get_stop_id_with_name(stops_lyr,
            trim_stop_second)
        r_def = get_matching_route_def(r_defs, r_def_spec)
        if not r_def:
            print "Error:- the route you specified to be trimmed, with "\
                "ID %s, short name '%s', long name '%s' - not found in "\
                "list of routes specified in file %s ." %\
                (r_def_spec.id, r_def_spec.short_name, r_def_spec.long_name,\
                 options.input_route_defs)
            sys.exit(1)
        r_seg_refs = [output_seg_refs_dict[s_id] for s_id in \
            r_def.ordered_seg_ids]
        #r_seg_refs = route_segs.create_ordered_seg_refs_from_ids(
        #    r_def.ordered_seg_ids, segs_lookup_table)
        r_stop_ids = route_segs.extract_stop_list_along_route(r_seg_refs)
        # Check that all trim stops are included in the stop list
        if trim_stop_first_id not in r_stop_ids:
            print "Error:- first trim stop with name '%s' not found "\
                "in stop list for route %s (%s)." \
                % (trim_stop_first, r_def.short_name, r_def.long_name)
            sys.exit(1)
        if trim_stop_second_id not in r_stop_ids:
            print "Error:- second trim stop with name '%s' not found "\
                "in stop list for route %s (%s)." \
                % (trim_stop_second, r_def.short_name, r_def.long_name)
            sys.exit(1)
        t_first_i = r_stop_ids.index(trim_stop_first_id)
        t_second_i = r_stop_ids.index(trim_stop_second_id)
        if t_first_i == t_second_i:
            print "Error:- both trim stops with name '%s' are at same "\
                "place in route %s (%s)." \
                % (trim_stop_first, r_def.short_name, r_def.long_name)
            sys.exit(1)
        if upd_dir_1 or upd_dir_2:
            # Update the route directions    
            upd_dirs = [upd_dir_1, upd_dir_2]
            if t_second_i < t_first_i:
                upd_dirs.reverse()
            if not upd_dirs[0]:
                r_def.dir_names = (r_def.dir_names[0], upd_dirs[1])
            elif not upd_dirs[1]:
                r_def.dir_names = (upd_dirs[0], r_def.dir_names[1])
            else:    
                r_def.dir_names = tuple(upd_dirs)
        # Now process the route segments :- trim out any part not within the 
        # stops defined by trim stops a and b.
        trim_stop_ids_rem = [trim_stop_first_id, trim_stop_second_id]
        within_keep_section = False
        updated_r_seg_ids = []
        if r_stop_ids[0] in trim_stop_ids_rem:
            trim_stop_ids_rem.remove(r_stop_ids[0])
            within_keep_section = True
        for seg_ii, seg_ref in enumerate(r_seg_refs):
            if not within_keep_section:
                seg_ref.routes.remove(int(r_def.id))
                if len(seg_ref.routes) == 0:
                    # Get rid of seg refs not used in any routes
                    # so they won't be written out at end.
                    del(output_seg_refs_dict[seg_ref.seg_id])
            else:
                updated_r_seg_ids.append(seg_ref.seg_id)
            # Now update the within keep status for next seg.
            seg_second_stop_id = r_stop_ids[seg_ii+1]
            if seg_second_stop_id in trim_stop_ids_rem:
                trim_stop_ids_rem.remove(seg_second_stop_id)
                # Don't use below, since we wish to remove route specs
                # from remaining segments.
                #if len(trim_stop_ids_rem) == 0:
                #    break
                within_keep_section = not within_keep_section
        updated_r_def = copy.deepcopy(r_def)
        updated_r_def.ordered_seg_ids = updated_r_seg_ids
        updated_r_defs.append(updated_r_def)
    # Create output r_defs list
    updated_r_ids = map(operator.attrgetter("id"), updated_r_defs)
    output_r_defs = []
    for r_def in r_defs:
        try:
            upd_ii = updated_r_ids.index(r_def.id)
        except ValueError:
            output_r_defs.append(r_def)
        else:
            output_r_defs.append(updated_r_defs[upd_ii])
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

