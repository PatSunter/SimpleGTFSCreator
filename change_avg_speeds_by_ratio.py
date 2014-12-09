#!/usr/bin/env python2

# This script just to create a new GTFS schedule based off an old one,
#  but subsetting the list of routes.

import os, sys
import os.path
import operator
import csv
import glob
from optparse import OptionParser

import misc_utils
import time_periods_speeds_model as tps_speeds_model

SPEED_ROUND_PLACES = 3

def main():
    parser = OptionParser()
    parser.add_option('--input_dir_speeds', dest='input_dir_speeds',
        help='Directory to input avg speed files to read from.')
    parser.add_option('--output_dir_speeds', dest='output_dir_speeds',
        help='Directory to output avg speed files to create.')
    parser.add_option('--speed_ratio', dest='speed_ratio',
        help='Ratio to multiply existing speeds by to create new set.')
    (options, args) = parser.parse_args()

    if options.input_dir_speeds is None:
        parser.print_help()
        parser.error("No input speeds dir given.") 
    if options.output_dir_speeds is None:
        parser.print_help()
        parser.error("No output speeds dir given.") 
    if options.speed_ratio is None:
        parser.print_help()
        parser.error("No speed change ratio given.")
    
    speed_ratio = float(options.speed_ratio)
    if speed_ratio == 0:
        parser.print_help()
        parser.error("Bad value of speed ratio given, should be"\
            "non-zero.")

    input_dir_speeds = options.input_dir_speeds
    if not os.path.exists(input_dir_speeds):
        parser.print_help()
        parser.error("Bad value of input dir of speed files given, "\
            "could not open.")

    output_dir_speeds = options.output_dir_speeds
    if not os.path.exists(output_dir_speeds):
        os.makedirs(output_dir_speeds)

    print "Reading speed from all input speed files in dir %s, "\
        "changing them by ratio of %f, and saving modified results to dir "\
        "%s ..." % (input_dir_speeds, speed_ratio, output_dir_speeds)

    for ii, csv_speeds_in_fname in enumerate(glob.glob("%s%s*speeds*.csv" \
            % (input_dir_speeds, os.sep))):
        #print "Reading speeds in file %s" % csv_speeds_in_fname
        fname_sections = os.path.basename(csv_speeds_in_fname).split('-')
        serv_period = fname_sections[-3]
        trips_dir_file_ready = fname_sections[-2]
        name_b = fname_sections[-5]
        try:
            name_a = fname_sections[-6]
        except IndexError:
            name_a = None
        time_periods, route_avg_speeds_in, seg_distances_in, \
                stop_gtfs_ids_to_names_map = \
            tps_speeds_model.read_route_speed_info_by_time_periods(
                input_dir_speeds, name_a, name_b,
                serv_period, trips_dir_file_ready,
                sort_seg_stop_id_pairs=False)

        route_avg_speeds_out = {}
        for gtfs_stop_id_pair, avg_speeds in route_avg_speeds_in.iteritems():
            speeds_in_tps_out = []
            for sp in avg_speeds:
                if sp > 0:
                    sp_out = sp * speed_ratio
                else:
                    sp_out = sp
                speeds_in_tps_out.append(sp_out)
            route_avg_speeds_out[gtfs_stop_id_pair] = speeds_in_tps_out

        out_fname = \
            tps_speeds_model.get_route_avg_speeds_for_dir_period_fname(
                name_a, name_b, serv_period, trips_dir_file_ready)
        out_fpath = os.path.join(output_dir_speeds, out_fname)
        tps_speeds_model.write_avg_speeds_on_segments(
            stop_gtfs_ids_to_names_map,
            route_avg_speeds_out, seg_distances_in,
            time_periods, out_fpath, SPEED_ROUND_PLACES)    
    print "... done (read and wrote %d speed spec files)." % (ii+1)
    return

if __name__ == "__main__":
    main()

