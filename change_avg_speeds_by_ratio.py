#!/usr/bin/env python2

# This script just to create a new GTFS schedule based off an old one,
#  but subsetting the list of routes.

import os, sys
import os.path
import operator
import csv
import glob
from optparse import OptionParser

import gtfs_ops

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

    print "Increasing speed by ratio in all input speed files ..."

    for csv_speeds_in_fname in glob.glob("%s%s*speeds*.csv" \
            % (input_dir_speeds, os.sep)):
        print "Reading speeds in file %s" % csv_speeds_in_fname
        csv_in_file = open(csv_speeds_in_fname, 'r')
        reader = csv.reader(csv_in_file, delimiter=';')
        csv_speeds_out_fname = os.path.join(output_dir_speeds,
            os.path.basename(csv_speeds_in_fname))
        csv_out_file = open(csv_speeds_out_fname, 'w')    
        writer = csv.writer(csv_out_file, delimiter=';')

        headers = reader.next()
        writer.writerow(headers)
        for row in reader:
            n_base_cols = len(gtfs_ops.AVG_SPEED_HEADERS) 
            init_col_vals = row[:n_base_cols]
            speeds_in_tps = map(float, row[n_base_cols:])
            speeds_in_tps_out = []
            for sp in speeds_in_tps:
                if sp > 0:
                    sp_out = sp * speed_ratio
                else:
                    sp_out = sp
                speeds_in_tps_out.append(sp_out)
            writer.writerow(init_col_vals + speeds_in_tps_out)
        print "...finished saving changed speeds by ratio to file %s" \
            % csv_speeds_out_fname
        csv_in_file.close()
        csv_out_file.close()

    print "... done."
    return

if __name__ == "__main__":
    main()

