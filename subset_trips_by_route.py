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

import parser_utils
import gtfs_ops
import route_segs

def get_route_def_specs_from_csv(csv_fname):
    route_defs = []
    try:
        csv_file = open(csv_fname, 'r')
    except IOError:
        print "Error, route spec CSV file given, %s , failed to open." \
            % (csv_fname)
        sys.exit(1) 

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
        if True not in [route_segs.route_defs_match_statuses(r_def, r_def2) for \
                r_def2 in single_route_def_list]:
            single_route_def_list.append(r_def)
        else:
            print "Warning:- you already asked to copy route with "\
                "ID %s, name %s. Skipping repeat instance." \
                    % (str(r_def.id), route_segs.get_print_name(r_def))
    for long_name in route_long_names:    
        r_def = route_segs.Route_Def(None, None, long_name, (None, None), None)    
        if True not in [route_segs.route_defs_match_statuses(r_def, r_def2) for \
                r_def2 in single_route_def_list]:
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
    parser.add_option('--route_short_names', dest='route_short_names', 
        help='Names of route short names to subset and copy, comma-separated.')
    parser.add_option('--route_long_names', dest='route_long_names', 
        help='Names of route long names to subset and copy, comma-separated.')
    parser.add_option('--route_spec_csv', dest='route_spec_csv',
        help='Path to CSV file containing list of route names to include.')
    parser.set_defaults(route_short_names='', route_long_names='')
    (options, args) = parser.parse_args()

    if options.inputgtfs is None:
        parser.print_help()
        parser.error("No input GTFS file given.") 
    if options.output is None:
        parser.print_help()
        parser.error("No output GTFS file given.") 
    if not (options.route_short_names or options.route_long_names \
            or options.route_spec_csv):
        parser.print_help()
        parser.error("No option to specify routes to subset given.")

    gtfs_input_fname = options.inputgtfs
    gtfs_output_fname = options.output

    route_short_names = parser_utils.getlist(options.route_short_names)
    route_long_names = parser_utils.getlist(options.route_long_names)
    
    csv_route_defs = []
    if options.route_spec_csv:
        csv_route_defs = get_route_def_specs_from_csv(options.route_spec_csv)

    route_defs_to_subset = get_single_route_def_list(route_short_names,
        route_long_names, csv_route_defs) 

    accumulator = transitfeed.SimpleProblemAccumulator()
    problemReporter = transitfeed.ProblemReporter(accumulator)

    loader = transitfeed.Loader(gtfs_input_fname, problems=problemReporter)
    print "Loading input schedule from file %s ..." % gtfs_input_fname
    input_schedule = loader.Load()
    print "... done."

    output_schedule = transitfeed.Schedule(memory_db=False)
    # First, we're going to re-create with all the agencies, period,
    #  stop locations etc

    print "Copying file basics to new schedule."
    for agency in input_schedule._agencies.itervalues():
        ag_cpy = copy.copy(agency)
        ag_cpy._schedule = None
        output_schedule.AddAgencyObject(ag_cpy)
    for stop in input_schedule.stops.itervalues():
        stop_cpy = copy.copy(stop)
        stop_cpy._schedule = None
        output_schedule.AddStopObject(stop_cpy)
    for serv_period in input_schedule.service_periods.itervalues():
        serv_period_cpy = copy.copy(serv_period)
        output_schedule.AddServicePeriodObject(serv_period_cpy)

    matched_gtfs_route_ids, match_statuses = \
        route_segs.get_gtfs_route_ids_matching_route_defs(route_defs_to_subset,
            input_schedule.routes.itervalues())

    print "Copying routes, trips, and trip stop times for the %d " \
        "matched routes." % len(matched_gtfs_route_ids)
    gtfs_ops.copy_selected_routes(input_schedule, output_schedule,
        matched_gtfs_route_ids)

    input_schedule = None
    print "About to do output schedule validate and write ...."
    output_schedule.Validate()
    output_schedule.WriteGoogleTransitFeed(gtfs_output_fname)
    print "Written successfully to: %s" % gtfs_output_fname
    return

if __name__ == "__main__":
    main()

