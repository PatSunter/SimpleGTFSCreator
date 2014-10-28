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

MAX_SERV_PERIOD_HRS = 48

def frange(x, y, jump):
  while x < y:
    yield x
    x += jump

def main():
    parser = OptionParser()
    parser.add_option('--input_gtfs', dest='inputgtfs',
        help='Path of input file. Should end in .zip')
    parser.add_option('--output_dir_hways', dest='output_dir_hways',
        help='Directory to output headway files to.')
    parser.add_option('--output_dir_speeds', dest='output_dir_speeds',
        help='Directory to output avg speed files to.')
    parser.add_option('--speed_calc_min_mins', dest='speed_calc_min_mins',
        help='Minimum time in minutes along routes to use for smoothing '\
            'in speed calculation algorithm.')
    parser.add_option('--speed_calc_min_dist_m', dest='speed_calc_min_dist_m',
        help='Minimum dist along route in metres to use for smoothing '\
            'in speed calculation algorithm.')
    parser.add_option('--time_period_width_hours',
        dest='time_period_width_hours',
        help='Width of hours to split the servic day into for aggregating.')
    parser.add_option('--time_period_max_hours',
        dest='time_period_max_hours',
        help='Maximum time period hours to use.')
    parser.set_defaults(
        time_period_width_hours=2,
        time_period_max_hours=28,
        speed_calc_min_mins=4,
        speed_calc_min_dist_m=0)
    (options, args) = parser.parse_args()

    if options.inputgtfs is None:
        parser.print_help()
        parser.error("No input GTFS file given.") 
    if options.output_dir_hways is None:
        parser.print_help()
        parser.error("No output headways dir given.") 
    if options.output_dir_speeds is None:
        parser.print_help()
        parser.error("No output speeds dir given.") 
    if options.time_period_width_hours is None:
        parser.print_help()
        parser.error("No time period width (in hours) given.")
    
    speed_smooth_min_mins = float(options.speed_calc_min_mins)
    speed_smooth_min_dist_m = float(options.speed_calc_min_dist_m)
    if speed_smooth_min_mins < 0:
        parser.print_help()
        parser.error("Bad value of speed smooth min mins given, must be "\
            ">= 0.")
    if speed_smooth_min_dist_m < 0:
        parser.print_help()
        parser.error("Bad value of speed smooth min dist m given, must be "\
            ">= 0.")

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

    gtfs_input_fname = options.inputgtfs
    output_dir_hways = options.output_dir_hways
    output_dir_speeds = options.output_dir_speeds

    for out_dir in (output_dir_hways, output_dir_speeds):
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

    for r_id in schedule.routes.iterkeys():
        route_avg_speeds, seg_distances = \
            gtfs_ops.extract_route_speed_info_by_time_periods(
                schedule, r_id, time_periods, 
                min_dist_for_speed_calc_m=speed_smooth_min_dist_m,
                min_time_for_speed_calc_s=speed_smooth_min_mins*60)
        gtfs_ops.write_route_speed_info_by_time_periods(schedule, r_id,
            time_periods, route_avg_speeds, seg_distances, output_dir_speeds)
        #hways_by_patterns, pattern_stop_orders = \
        #    gtfs_ops.extract_route_freq_info_by_time_periods_by_pattern(
        #        schedule, r_id, time_periods)
        #gtfs_ops.write_route_freq_info_by_time_periods_by_patterns(
        #    schedule, r_id, time_periods,
        #    hways_by_patterns, pattern_stop_orders, output_dir_hways)    
        hways_all_patterns, all_patterns_stop_orders = \
            gtfs_ops.extract_route_freq_info_by_time_periods_all_patterns(
                schedule, r_id, time_periods)
        gtfs_ops.write_route_freq_info_by_time_periods_all_patterns(
            schedule, r_id, time_periods,
            hways_all_patterns, all_patterns_stop_orders, output_dir_hways)
    return

if __name__ == "__main__":
    main()

