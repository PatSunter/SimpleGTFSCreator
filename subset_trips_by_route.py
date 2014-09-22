#!/usr/bin/env python2

# This script just to create a new GTFS schedule based off an old one,
#  but subsetting the list of routes.

import os, sys
import os.path
import copy
from optparse import OptionParser

import transitfeed

import parser_utils
import gtfs_ops

def main():
    parser = OptionParser()
    parser.add_option('--input', dest='inputgtfs', help='Path of input file. '\
        'Should end in .zip')
    parser.add_option('--output', dest='output', help='Path of output file. '\
        'Should end in .zip')
    parser.add_option('--routes', dest='route_names', 
        help='Names of routes to subset and copy, comma-separated.')
    (options, args) = parser.parse_args()

    if options.inputgtfs is None:
        parser.print_help()
        parser.error("No input GTFS file given.") 
    if options.output is None:
        parser.print_help()
        parser.error("No input GTFS file given.") 
    if options.route_names is None:
        parser.print_help()
        parser.error("No route names list given to subset.") 

    gtfs_input_fname = options.inputgtfs
    gtfs_output_fname = options.output

    route_names = parser_utils.getlist(options.route_names) 
    #route_names = ['Upfield', 'Pakenham']

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

    # Now :- we just copy across trip times for routes we're interested in.
    gtfs_ops.copy_selected_routes(input_schedule, output_schedule, route_names)

    input_schedule = None
    print "About to do output schedule validate and write ...."
    output_schedule.Validate()
    output_schedule.WriteGoogleTransitFeed(gtfs_output_fname)
    print "Written successfully to: %s" % gtfs_output_fname
    return

if __name__ == "__main__":
    main()

