#!/usr/bin/env python2

# Credit to https://twitter.com/andybotting for the script which served as a
# template for creating this one.

import os
import sqlite3
import re
import datetime
from optparse import OptionParser

import transitfeed

settings = {
    'train': {
        'avespeed': 40; # km/h
        'frequency': 5; # minutes (how often a vehicle arrives at each stop)
    },
    'tram': {
        'avespeed': 35; # km/h
        'frequency': 5; # minutes (how often a vehicle arrives at each stop)
    },
    'bus': {
        'avespeed': 30; # km/h
        'frequency': 5; # minutes (how often a vehicle arrives at each stop)
    }
}

#Fake data ...
lines = ["craigieburn"]
stops = {
    '0': ("North Melbourne", (144.94151,-37.806309)),
    '1': ("Kensington", (144.930525,-37.793777)),
    '2': ("Newmarket", (144.928984,-37.787326))
    }

route_defs = [
    "craigieburn": 
        {"stop_ids": [0, 1, 2]} 
]

def process_routes(cur, config, schedule):
	# Routes
	for ii, linename in enumerate(cur):
        row = route_defs[linename]

		route_long_name = linename
		route_short_name = None
		route_description = None
        route_id = str(config['index'] + ii)

		# Add our route
		route = transitfeed.Route(
			short_name = route_short_name, 
			long_name = route_long_name,
			route_type = config['system'],
			route_id = route_id
		)

		schedule.AddRouteObject(route)

	

def process_stops(cur, config, schedule):
	# Stops
	for stop_id, stop_info in cur.iteritems():

		stop_name = stop_info[0]
		stop_desc = None
		stop_code = None
        stop_id = str(config['index'] + int(stop_id))
		lng = stop_info[1][0]
		lat =  stop_info[1][1]

		stop = transitfeed.Stop(
			stop_id = stop_id,
			name = stop_name,
			stop_code = stop_code,
			lat = lat,
			lng = lng,
		)

		schedule.AddStopObject(stop)


def create_stoptimes(route_defs, config, schedule):

    # HACK for now
    timetables = "monfri"

	for timetable in timetables:

		print(timetable)
		service_period = transitfeed.ServicePeriod(id=timetable)
		service_period.SetStartDate('20130101')
		service_period.SetEndDate('20131231')
		service_period.SetWeekdayService()

		schedule.AddServicePeriodObject(service_period, validate=False)

		process_stoptime(cur, config, schedule, service_period, timetable)


def process_stoptime(cur, config, schedule, service_period, table):
	
    #Re-grab the routes, stop etc info from the already-entered info.
    route_id = str(config['index'] + int(row['line_id']))
    route = [r for r in schedule.GetRouteList() if r.route_id == route_id][0]

    stop_id = str(config['index'] + int(row['stop_id']))
    stop = [s for s in schedule.GetStopList() if s.stop_id == stop_id][0]

    headsign = directions[int(row["direction"])] 
    # Get the direction from the other table
    trip_id = config['index'] + int(row['run_id'])

    trip = route.AddTrip(
        schedule, 
        headsign = headsign,
        trip_id = trip_id,
        service_period = service_period 

    # Calculate the starting time for the day
    #while < finish time 
        # add "frequency" to start time 

        # add the first stop at that time 
        # for each other stop along the route ...
            # calculate distance from the last stop based on GIS co-ordinates
            # calc next time :- distance / speed.

            # We know the stops times are in row order, so we'll
            # just make up the sequence here
            stop_seq = len(trip.GetStopTimes())

            # Not sure what we should do about this
            problems = None

            stop_time = transitfeed.StopTime(
                problems, 
                stop,
                pickup_type = 0, # Regularly scheduled pickup 
                drop_off_type = 0, # Regularly scheduled drop off
                shape_dist_traveled = None, 
                arrival_secs = time,
                departure_secs = time, 
                stop_time = time, 
                stop_sequence = stop_seq
            )

            trip.AddStopTimeObject(stop_time)


def process_data(inputdb, config, output):
	# Create our schedule
	schedule = transitfeed.Schedule()

	# Agency
	schedule.AddAgency(config['name'], "http://www.bze.org.au", "Australia/Melbourne", agency_id=config['id'])

    # Hacked the inputs here ...
	process_routes(lines, config, schedule)
	process_stops(stops, config, schedule)
	process_stoptimes(cur, config, schedule)

	schedule.Validate()
	schedule.WriteGoogleTransitFeed(output)


if __name__ == "__main__":

	parser = OptionParser()
	parser.add_option('--file', dest='inputdb', help='SQLite3 databse file.')
	parser.add_option('--service', dest='service', help='Should be train, tram or bus.')
	parser.add_option('--output', dest='output', help='Path of output file. Should end in .zip')
	parser.set_defaults(output='google_transit.zip')
	(options, args) = parser.parse_args()

	config = settings[options.service]

	process_data(options.inputdb, config, options.output)
