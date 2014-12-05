#!/usr/bin/env python2

# This script just to create a new GTFS schedule based off an old one,
#  but subsetting the list of routes.

import os, sys
import os.path
import operator
import csv
from datetime import time, datetime, date, timedelta
from optparse import OptionParser

import transitfeed
import gtfs_ops
import route_segs
import time_periods_hways_model as tps_hways_model

MAX_SERV_PERIOD_HRS = 48

def frange(x, y, jump):
  while x < y:
    yield x
    x += jump

def main():
    parser = OptionParser()
    parser.add_option('--input_gtfs', dest='inputgtfs',
        help='Path of input file. Should end in .zip')
    parser.add_option('--output_hways', dest='output_hways',
        help='File to save output headway for routes to.')
    parser.add_option('--time_period_width_hours',
        dest='time_period_width_hours',
        help='Width of hours to split the servic day into for aggregating.')
    parser.add_option('--time_period_max_hours',
        dest='time_period_max_hours',
        help='Maximum time period hours to use.')
    parser.add_option('--round_places',
        dest='round_places',
        help='Number of places to round output minutes to.')
    parser.set_defaults(
        time_period_width_hours=2,
        time_period_max_hours=28,
        round_places=2)
    (options, args) = parser.parse_args()

    if options.inputgtfs is None:
        parser.print_help()
        parser.error("No input GTFS file given.") 
    if options.output_hways is None:
        parser.print_help()
        parser.error("No output headways file given.") 
    if options.time_period_width_hours is None:
        parser.print_help()
        parser.error("No time period width (in hours) given.")
    
    tp_width_hrs = float(options.time_period_width_hours)
    if tp_width_hrs <= 0 or tp_width_hrs > MAX_SERV_PERIOD_HRS:
        parser.print_help()
        parser.error("Bad value of time period width hours given, should "
            "greater than 0 and less than %d." % MAX_SERV_PERIOD_HRS)
    tp_max_hrs = float(options.time_period_max_hours)
    if tp_width_hrs <= 0 or tp_width_hrs > MAX_SERV_PERIOD_HRS:
        parser.print_help()
        parser.error("Bad value of time period max hours given, should "
            "greater than 0 and less than %d." % MAX_SERV_PERIOD_HRS)

    round_places = int(options.round_places)

    gtfs_input_fname = options.inputgtfs
    output_hways_fname = options.output_hways

    for out_dir in [os.path.dirname(output_hways_fname)]:
        if not os.path.exists(out_dir):
            os.makedirs(out_dir)

    accumulator = transitfeed.SimpleProblemAccumulator()
    problemReporter = transitfeed.ProblemReporter(accumulator)

    loader = transitfeed.Loader(gtfs_input_fname, problems=problemReporter)
    print "Loading schedule ..."
    schedule = loader.Load()
    print "... done."

    time_periods = []
    for hr_start in frange(0, tp_max_hrs, tp_width_hrs):
        hr_end = min([hr_start+tp_width_hrs, tp_max_hrs])
        tp = (timedelta(hours=hr_start), timedelta(hours=hr_end))
        time_periods.append(tp)    

    avg_hways_all_stops = {}
    for r_id in schedule.routes.iterkeys():
        hways_all_patterns, all_patterns_stop_orders = \
            gtfs_ops.extract_route_freq_info_by_time_periods_all_patterns(
                schedule, r_id, time_periods)
        avg_hways_all_stops_this_route = \
            gtfs_ops.get_average_hways_all_stops_by_time_periods(
                hways_all_patterns)
        avg_hways_all_stops[r_id] = avg_hways_all_stops_this_route    
            
    tps_hways_model.write_route_hways_all_routes_all_stops(schedule,
        time_periods, avg_hways_all_stops, output_hways_fname, round_places)
    return

if __name__ == "__main__":
    main()
