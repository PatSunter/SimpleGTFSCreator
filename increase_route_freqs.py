#!/usr/bin/env python2

# This script just to create a new GTFS schedule based off an old one,
#  but subsetting the list of routes.

import os, sys
import os.path
import operator
import csv
import glob
from optparse import OptionParser
from datetime import timedelta

import gtfs_ops
import parser_utils

def td_str_to_td(td_str):
    td_parts = td_str.split(':')
    if len(td_parts) != 2:
        raise ValueError
    td_hrs = int(td_parts[0])
    td_mins = int(td_parts[1])
    td = timedelta(hours=td_hrs, minutes=td_mins)
    return td


def decrease_hways_to_max_in_window(avg_hways_in_tps, tps, max_headway,
        time_window_start, time_window_end):
    avg_hways_in_tps_out = []
    for tp_i, hway in enumerate(avg_hways_in_tps):
        tp = tps[tp_i]
        if tp[1] > time_window_start and tp[0] < time_window_end:
            hway_out = min(hway, max_headway)
            if hway_out <= 0:
                hway_out = max_headway
        else:
            hway_out = hway
        avg_hways_in_tps_out.append(hway_out)
    return avg_hways_in_tps_out

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
        time_window_start = td_str_to_td(options.time_window_start)
    except ValueError:
        parser.print_help()
        parser.error("Bad value of time_window_start given %s, "\
            "see help above for correct format." % options.time_window_start)
    try:
        time_window_end = td_str_to_td(options.time_window_end)
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

    csv_in_file = open(input_hways_fname, 'r')
    reader = csv.reader(csv_in_file, delimiter=';')
    csv_out_file = open(output_hways_fname, 'w')    
    writer = csv.writer(csv_out_file, delimiter=';')

    r_id_i = gtfs_ops.AVG_HWAYS_ALL_STOPS_HDRS.index('route_id') 
    sp_i = gtfs_ops.AVG_HWAYS_ALL_STOPS_HDRS.index('serv_period')
    td_i = gtfs_ops.AVG_HWAYS_ALL_STOPS_HDRS.index('trips_dir')

    headers = reader.next()
    writer.writerow(headers)
    n_base_cols = len(gtfs_ops.AVG_HWAYS_ALL_STOPS_HDRS) 
    tp_strs = headers[n_base_cols:]
    tps = gtfs_ops.get_time_periods_from_strings(tp_strs)
    prev_route_id = None
    serv_periods_read_by_route_id = {}
    trip_dirs_read_by_route_id = {}
    for row in reader:
        route_id = row[r_id_i]
        serv_period = row[sp_i]
        trips_dir = row[td_i]
        if route_id not in serv_periods_read_by_route_id:
            serv_periods_read_by_route_id[route_id] = set()
        serv_periods_read_by_route_id[route_id].add(serv_period)
        if route_id not in trip_dirs_read_by_route_id:
            trip_dirs_read_by_route_id[route_id] = set()
        trip_dirs_read_by_route_id[route_id].add(trips_dir)
        if prev_route_id and add_missing_serv_periods \
            and route_id != prev_route_id:
            # Thw way conditional is written assumes all the route ID entries
            # are read/written in order.
            for sp in serv_periods_to_mod:
                if sp not in serv_periods_read_by_route_id[prev_route_id]:
                    # We need to write in rows for trips during these SPs, at
                    #  the maxmimum headway.
                    for trips_dir in trip_dirs_read_by_route_id[prev_route_id]:
                        init_col_vals = prev_init_col_vals 
                        init_col_vals[sp_i] = sp
                        init_col_vals[td_i] = trips_dir
                        null_hways = [-1] * len(tps)
                        avg_hways_in_tps_out = decrease_hways_to_max_in_window(
                            null_hways, tps, max_headway, time_window_start,
                            time_window_end)
                        writer.writerow(init_col_vals + avg_hways_in_tps_out)
        if serv_period not in serv_periods_to_mod:
            # Skip, which means write as-is to output.
            writer.writerow(row)
            continue
        init_col_vals = row[:n_base_cols]
        avg_hways_in_tps = map(float, row[n_base_cols:])
        avg_hways_in_tps_out = decrease_hways_to_max_in_window(
            avg_hways_in_tps, tps, max_headway, time_window_start,
            time_window_end)
        writer.writerow(init_col_vals + avg_hways_in_tps_out)
        prev_route_id = route_id
        prev_init_col_vals = init_col_vals
    print "...finished saving changed hways with to file %s" \
        % output_hways_fname
    csv_in_file.close()
    csv_out_file.close()
    return

if __name__ == "__main__":
    main()

