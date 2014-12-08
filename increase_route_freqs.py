#!/usr/bin/env python2

# This script just to create a new GTFS schedule based off an old one,
#  but subsetting the list of routes.

import os, sys
import os.path
import operator
import itertools
from datetime import timedelta
from optparse import OptionParser

import parser_utils
import misc_utils
import time_periods_hways_model as tps_hways_model

HEADWAYS_ROUND_PLACES=10

def main():
    parser = OptionParser()
    parser.add_option('--input_hways', dest='input_hways',
        help='File to read input headway for routes from.')
    parser.add_option('--output_hways', dest='output_hways',
        help='File to save output headway for routes to.')
    parser.add_option('--max_headway', dest='max_headway',
        help='Maximum headway allowed in time window (minutes).')
    parser.add_option('--serv_periods', dest='serv_periods',
        help='Comma-separated list of time periods to apply the maximum '\
            'headway to.')
    parser.add_option('--time_window_start', dest='time_window_start',
        help='Start of the time window to allow maximum headways. '\
            'Format needs to be HH:MM, e.g. 04:30 . Times after midnight '\
            'of the service day should be > 24, e.g. 25:00 for 1AM after '\
            'first service day.')
    parser.add_option('--time_window_end', dest='time_window_end',
        help='End of the time window to allow maximum headways. '\
            'Same format as time window start.')
    parser.add_option('--add_missing_serv_periods',
        dest='add_missing_serv_periods',
        help='Should we add rows for missing service periods?')
    parser.set_defaults(add_missing_serv_periods='True')
    (options, args) = parser.parse_args()

    if options.input_hways is None:
        parser.print_help()
        parser.error("No input headways file given.") 
    if options.output_hways is None:
        parser.print_help()
        parser.error("No output headways file specified.") 
    if options.max_headway is None:
        parser.print_help()
        parser.error("No max headway to apply specified.")
    if options.serv_periods is None:
        parser.print_help()
        parser.error("No set of services periods to modify specified.")
    if options.time_window_start is None:
        parser.print_help()
        parser.error("No time window start specified.")
    if options.time_window_end is None:
        parser.print_help()
        parser.error("No time window end specified.")
    
    max_headway = float(options.max_headway)
    if max_headway <= 0:
        parser.print_help()
        parser.error("Bad value of max headway given, should be"\
            "> zero.")

    serv_periods_to_mod = options.serv_periods.split(',')

    try:
        time_window_start = parser_utils.td_str_to_td(options.time_window_start)
    except ValueError:
        parser.print_help()
        parser.error("Bad value of time_window_start given %s, "\
            "see help above for correct format." % options.time_window_start)
    try:
        time_window_end = parser_utils.td_str_to_td(options.time_window_end)
    except ValueError:
        parser.print_help()
        parser.error("Bad value of time_window_end given %s, "\
            "see help above for correct format." % options.time_window_end)
    if time_window_start < timedelta(0):
        parser.print_help()
        parser.error("Bad value of time_window_start given %s, "\
            "it must be > 00:00." % options.time_window_start)
    if time_window_end <= time_window_start:
        parser.print_help()
        parser.error("Bad value of time_window_end given %s, "\
            "it must be > time_window_start." % options.time_window_end)

    input_hways_fname = options.input_hways
    if not os.path.exists(input_hways_fname):
        parser.print_help()
        parser.error("Bad value of input route headways given, "\
            "does not exist.")

    output_hways_fname = options.output_hways
    if not os.path.exists(os.path.basename(output_hways_fname)):
        os.makedirs(os.path.basename(output_hways_fname))

    add_missing_serv_periods = parser_utils.str2bool(
        options.add_missing_serv_periods)

    print "Decreasing headways to max value of %.2f in service periods %s "\
        "between times %s and %s ..." \
        % (max_headway, serv_periods_to_mod, options.time_window_start,\
           options.time_window_end)

    avg_hways_all_stops_in, tps, r_ids_to_names_map = \
        tps_hways_model.read_route_hways_all_routes_all_stops(input_hways_fname)

    avg_hways_all_stops_out = {}
    for r_id, avg_hways_by_dir_period_in in avg_hways_all_stops_in.iteritems():
        avg_hways_all_stops_out[r_id] = {}    
        for dir_period_pair, avg_hways_in_tps_in in \
                avg_hways_by_dir_period_in.iteritems():
            sp = dir_period_pair[1]
            if sp in serv_periods_to_mod:
                avg_hways_in_tps_out = \
                    tps_hways_model.decrease_hways_to_max_in_window(
                        avg_hways_in_tps_in, tps, max_headway,
                        time_window_start, time_window_end)
            else:
                # Don't modify in this case, we'll just copy.
                avg_hways_in_tps_out = copy.copy(avg_hways_in_tps_in)
            avg_hways_all_stops_out[r_id][dir_period_pair] = \
                avg_hways_in_tps_out
    # Now we potentially need to add missing headway entries
    if add_missing_serv_periods:
        null_hways = [-1] * len(tps)
        max_hways_in_tps_out = tps_hways_model.decrease_hways_to_max_in_window(
            null_hways, tps, max_headway, time_window_start, time_window_end)
        for r_id, avg_hways_by_dir_period_out in \
                avg_hways_all_stops_out.iteritems():
            dir_period_pairs = avg_hways_by_dir_period_out.keys()
            dirs_found = set(map(operator.itemgetter(0), dir_period_pairs))
            dir_period_pairs_needed = itertools.product(dirs_found,
                serv_periods_to_mod)
            for dir_period_pair in dir_period_pairs_needed:
                if dir_period_pair not in avg_hways_by_dir_period_out:
                    avg_hways_by_dir_period_out[dir_period_pair] = \
                        max_hways_in_tps_out

    tps_hways_model.write_route_hways_all_routes_all_stops(r_ids_to_names_map,
        tps, avg_hways_all_stops_out, output_hways_fname, 
        round_places=HEADWAYS_ROUND_PLACES)

    print "...finished saving changed hways with to file %s" \
        % output_hways_fname
    return

if __name__ == "__main__":
    main()

