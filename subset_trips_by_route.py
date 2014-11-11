#!/usr/bin/env python2

# This script just to create a new GTFS schedule based off an old one,
#  but subsetting the list of routes.

import os, sys
import os.path
import copy
import operator
import csv
from optparse import OptionParser

import transitfeed
from osgeo import ogr, osr

import parser_utils
import gtfs_ops
import route_segs

def get_route_def_specs_from_csv(csv_fname):
    route_defs = []
    csv_file = open(csv_fname, 'r')
    dict_reader = csv.DictReader(csv_file, delimiter=';', quotechar="'")
    for csv_row in dict_reader:
        try:
            r_id = csv_row['route_id']
        except KeyError:
            r_id = None
        try:
            short_name = csv_row['route_short_name']
        except KeyError:
            short_name = None
        try:
            long_name = csv_row['route_long_name']
        except KeyError:
            long_name = None
        r_def = route_segs.Route_Def(r_id, short_name, long_name, (None, None),
            None)
        route_defs.append(r_def)
    csv_file.close()
    return route_defs

def get_single_route_def_list(route_short_names, route_long_names,
        csv_route_defs):
    single_route_def_list = []
    for short_name in route_short_names:
        r_def = route_segs.Route_Def(None, short_name, None, (None, None), None)
        if True not in [route_segs.route_defs_match_statuses(r_def, r_def2) \
            for r_def2 in single_route_def_list]:
            single_route_def_list.append(r_def)
        else:
            print "Warning:- you already asked to copy route with "\
                "ID %s, name %s. Skipping repeat instance." \
                    % (str(r_def.id), route_segs.get_print_name(r_def))
    for long_name in route_long_names:    
        r_def = route_segs.Route_Def(None, None, long_name, (None, None), None)    
        if True not in [route_segs.route_defs_match_statuses(r_def, r_def2) \
            for r_def2 in single_route_def_list]:
            single_route_def_list.append(r_def)
        else:
            print "Warning:- you already asked to copy route with "\
                "ID %s, name %s. Skipping repeat instance." \
                    % (str(r_def.id), route_segs.get_print_name(r_def))
    for csv_route_def in csv_route_defs:
        r_def_matches = [route_segs.route_defs_match_statuses(csv_route_def, \
            r_def) for r_def in single_route_def_list]
        if True not in r_def_matches:
            single_route_def_list.append(csv_route_def)            
        else:
            print "Warning:- you already asked to copy route with "\
                "ID %s, name %s (or a more general version of it)." \
                    % (str(csv_route_def.id), \
                      route_segs.get_print_name(csv_route_def))
    return single_route_def_list

def main():
    parser = OptionParser()
    parser.add_option('--input', dest='inputgtfs', help='Path of input file. '\
        'Should end in .zip')
    parser.add_option('--output', dest='output', help='Path of output file. '\
        'Should end in .zip')
    parser.add_option('--output_rem', dest='output_rem', help='(Optional) Path of '
        'output GTFS file to save "remainder" routes, not in selection, to '\
        '(Should end in .zip).')
    parser.add_option('--route_short_names', dest='route_short_names', 
        help='Names of route short names to subset and copy, comma-separated.')
    parser.add_option('--route_long_names', dest='route_long_names', 
        help='Names of route long names to subset and copy, comma-separated.')
    parser.add_option('--route_spec_csv', dest='route_spec_csv',
        help='Path to CSV file containing list of route names to include.')
    parser.add_option('--partially_within_polygons',
        dest='partially_within_polygons',
        help='Shapefile of a set of polygons to test if each route is within'
            'these, and only subset those that are.')
    parser.set_defaults(route_short_names='', route_long_names='')
    (options, args) = parser.parse_args()

    if options.inputgtfs is None:
        parser.print_help()
        parser.error("No input GTFS file given.") 
    if options.output is None:
        parser.print_help()
        parser.error("No output GTFS file given.") 
    if not (options.route_short_names or options.route_long_names \
            or options.route_spec_csv or options.partially_within_polygons):
        parser.print_help()
        parser.error("No option to specify routes to subset given.")

    gtfs_input_fname = options.inputgtfs
    gtfs_output_fname = options.output

    gtfs_output_rem_fname = None
    if options.output_rem:
        gtfs_output_rem_fname = options.output_rem

    route_short_names = parser_utils.getlist(options.route_short_names)
    route_long_names = parser_utils.getlist(options.route_long_names)
    
    csv_route_defs = []
    if options.route_spec_csv:
        try:
            csv_route_defs = get_route_def_specs_from_csv(options.route_spec_csv)
        except IOError:
            parser.print_help()
            print "\nError, route spec CSV file given, %s , failed to open." \
                % (options.route_spec_csv)
            sys.exit(1)

    route_defs_to_subset = get_single_route_def_list(route_short_names,
        route_long_names, csv_route_defs) 

    accumulator = transitfeed.SimpleProblemAccumulator()
    problemReporter = transitfeed.ProblemReporter(accumulator)
    loader = transitfeed.Loader(gtfs_input_fname, problems=problemReporter)
    print "Loading input schedule from file %s ..." % gtfs_input_fname
    input_schedule = loader.Load()
    print "... done."

    if route_defs_to_subset:
        print "Calculating subset of routes based on matching supplied "\
            "route short names, long names, and IDs."
        matched_gtfs_route_ids, match_statuses = \
            route_segs.get_gtfs_route_ids_matching_route_defs(
                route_defs_to_subset,
                input_schedule.routes.itervalues())
        subset_gtfs_route_ids = matched_gtfs_route_ids
    else:
        subset_gtfs_route_ids = input_schedule.routes.keys()

    if options.partially_within_polygons:
        print "Calculating subset of routes based on being at least partly "\
            "within polygons in supplied shape file."
        polygons_fname = os.path.expanduser(options.partially_within_polygons)
        polygons_shp = ogr.Open(polygons_fname, 0)
        if polygons_shp is None:
            print "Error, partially within polygons shape file given, %s , "\
                "failed to open." % (options.partially_within_polygons)
            sys.exit(1)
        polygons_lyr = polygons_shp.GetLayer(0)
        subset_gtfs_route_ids = gtfs_ops.get_route_ids_within_polygons(
            input_schedule, subset_gtfs_route_ids, polygons_lyr)
        polygons_shp.Destroy()

    stop_ids_used_in_subset_routes = gtfs_ops.get_stop_ids_set_used_by_selected_routes(
        input_schedule, subset_gtfs_route_ids)

    print "Copying stops, routes, trips, and trip stop times for the %d " \
        "matched routes to new GTFS file %s ." \
        % (len(subset_gtfs_route_ids), gtfs_output_fname)
    output_schedule = gtfs_ops.create_base_schedule_copy(input_schedule)
    gtfs_ops.copy_stops_with_ids(input_schedule, output_schedule,
        stop_ids_used_in_subset_routes)
    gtfs_ops.copy_selected_routes(input_schedule, output_schedule,
        subset_gtfs_route_ids)

    print "About to do output schedule validate and write ...."
    output_schedule.Validate()
    output_schedule.WriteGoogleTransitFeed(gtfs_output_fname)
    print "Written successfully to: %s" % gtfs_output_fname
    output_schedule = None

    if gtfs_output_rem_fname:
        rem_gtfs_route_ids = \
            set(input_schedule.routes.iterkeys()).difference(subset_gtfs_route_ids)
        print "Given the 'output_rem' option enabled, now saving a GTFS with "\
            "the %d routes (and related trips, stops etc) NOT in the route "\
            "subset, to file %s ." % \
            (len(rem_gtfs_route_ids), gtfs_output_rem_fname)
        # Careful, don't use a set below :- as stops can be re-used between
        # routes, so need to re-calculate.
        rem_gtfs_stop_ids = gtfs_ops.get_stop_ids_set_used_by_selected_routes(
            input_schedule, rem_gtfs_route_ids)
        output_rem_schedule = gtfs_ops.create_base_schedule_copy(input_schedule)
        gtfs_ops.copy_stops_with_ids(input_schedule, output_rem_schedule,
            rem_gtfs_stop_ids)
        gtfs_ops.copy_selected_routes(input_schedule, output_rem_schedule,
            rem_gtfs_route_ids)
        print "About to do output schedule validate and write ...."
        output_rem_schedule.Validate()
        output_rem_schedule.WriteGoogleTransitFeed(gtfs_output_rem_fname)
        print "Written successfully to: %s" % gtfs_output_rem_fname
        output_rem_schedule = None

    input_schedule = None
    return

if __name__ == "__main__":
    main()

