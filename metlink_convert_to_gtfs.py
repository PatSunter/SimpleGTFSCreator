#!/usr/bin/env python2

import os
import sqlite3
import re
import datetime
from optparse import OptionParser

import transitfeed

settings = {
	'train': {
		'file': 'Metlink-Train.sql',
		'name': 'Metro Trains',
		'prefix': 'train',
		'system': 'Subway',
		'id': 30,
		'index': 3000000,
		'state': 'VIC',
	},
	'tram': {
		'file': 'Metlink-Tram.sql',
		'name': 'Yarra Trams',
		'prefix': 'tram',
		'system': 'Tram',
		'id': 32,
		'index': 3200000,
		'state': 'VIC',
	},
	'bus': {
		'file': 'Metlink-Bus.sql',
		'name': 'Melbourne Bus',
		'prefix': 'bus',
		'system': 'Bus',
		'id': 34,
		'index': 3400000,
		'state': 'VIC',
	},
	'vline': {
		'file': 'Metlink-VLine.sql',
		'name': 'V/Line',
		'prefix': 'vline',
		'system': 'regional',
		'id': 36,
		'index': 3600000,
		'state': 'VIC',
	}
}


def process_routes(cur, config, schedule):
	# Routes
	cur.execute("select * from " + config['prefix'] + "_lines")
	for row in cur:

		# Start with a sensible default of using the route_long_name.
		# You don't want to wait hours and hours to find out that
		# neither route_long_name or route_short_name has been set.
		route_long_name = row["line_name"].strip()
		route_short_name = None
		route_description = None

		# Train
		if config['system'] == 'Subway':
			route_long_name = row['line_name'].strip()
			route_type = config['system']

		# Tram
		elif config['system'] == 'Tram':
			# 1 - East Coburb - South Melbourne
			temp_name = row['line_name'].split(' - ')
			route_short_name = temp_name[0]
			route_long_name = temp_name[1]
			if len(temp_name) == 3:
				route_long_name = '%s to %s' % (route_long_name, temp_name[2])

		# V/Line
		elif config['system'] == 'V/Line':
			# Echuca-Moama - Melbourne via Shepparton
			m = re.match('(.*\s-\s.*) via (.*)', row["line_name"].strip())			
			if m:
				short_name = m.groups()[0].replace(" - ", " to ")
				route_name = '%s Line' % short_name
				long_name = m.group(0).replace(" - ", " to ")

		# Bus
		elif config['system'] == 'Bus':
			# 123 - Here - There
			# 843-845-849-861 - Dandenong - Endeavour Hills via Doveton
			m = re.match('([\d{3}?-]+) - (.*)', row["line_name"].strip())
			if m:
				route_short_name = m.groups()[0]
				route_long_name = m.groups()[1]
			else:
				m = re.match('(.*) \(Routes? (.*)\)', row["line_name"].strip())
				if m:
					route_short_name = m.groups()[1]
					route_long_name = m.groups()[0]
				else:
					
					m = re.match('(.*) combined - (.*)', row["line_name"].strip())
					if m:
						route_short_name = m.groups()[0]
						route_long_name = m.groups()[1]
					else:
						# Geelong City - Newtown via Aberdeen St (Anticlockwise Circular - Route 36)
						m = re.match('.* - Route (.*)\)', row["line_name"].strip())
						if m:
							route_short_name = m.groups()[0]
							route_long_name = row["line_name"].strip()

		route_id = str(config['index'] + int(row['line_id']))

		# Added by Pat S, 2013-07-10 :- for now, just set route_short_name
		# same as route_long_name (as some of the transitdatafeed scripts 
		# complain if this is missing)
		#route_short_name = route_long_name

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
	cur.execute("select * from "+ config['prefix'] + "_locations")
	for row in cur:

		stop_name = None
		stop_desc = None
		stop_code = None

		# Train
		if config['system'] == 'Subway':
			# Custom name for train stations
			stop_name = '%s Station' % row['location_name'].strip()

		elif config['system'] == 'Tram':
			# Custom name for tram
			# Match both:
			m = re.match('(.*)\s#(\d+)', row['location_name'].strip())
			# Street Name/Other Street #123
			if m:
				stop_code = m.groups()[1]
				stop_name = m.groups()[0]
			else:
				# 7D-Street Name/Other Street
				m = re.match('(\w+)-(.*)', row["location_name"].strip())
				try:
					stop_code = m.groups()[0]
					stop_name = m.groups()[1]
				except:
					print ("Warning: tram stop entry in DB "\
						"seems to be missing stop code:- entering "\
						"with name as '%s'" % row["location_name"].strip())
					stop_name = row['location_name'].strip()

		else:
			stop_name = row['location_name'].strip()

		stop_id = str(config['index'] + int(row['location_id']))
		lat = row["latitude"]
		lng = row["longitude"]

		stop = transitfeed.Stop(
			stop_id = stop_id,
			name = stop_name,
			stop_code = stop_code,
			lat = lat,
			lng = lng,
		)

		schedule.AddStopObject(stop)


def process_stoptimes(cur, config, schedule):

	timetables = []

	# Lookup which times we have
	cur.execute("SELECT name FROM sqlite_master WHERE type='table' AND name LIKE '" + config['prefix'] + "_stops%' ORDER BY name;")
	for row in cur:
		# Table name is train_stops_monthur, so get the last part
		name = row['name'].split('_')[-1]
		timetables.append(name)


	for timetable in timetables:

		print(timetable)
		service_period = transitfeed.ServicePeriod(id=timetable)
		service_period.SetStartDate('20130101')
		service_period.SetEndDate('20131231')

		# Set the day of week times
		if timetable == 'monthur':
			service_period.SetDayOfWeekHasService(0)
			service_period.SetDayOfWeekHasService(1)
			service_period.SetDayOfWeekHasService(2)
			service_period.SetDayOfWeekHasService(3)
		elif timetable == 'fri':	
			service_period.SetDayOfWeekHasService(4)
		elif timetable == 'monfri':
			service_period.SetWeekdayService()
		elif timetable == 'sat':
			service_period.SetDayOfWeekHasService(5)
		elif timetable == 'sun':
			service_period.SetDayOfWeekHasService(6)
		else:
			print("Error: Timetable %s not defined" % timetable)

		schedule.AddServicePeriodObject(service_period, validate=False)
		process_stoptime(cur, config, schedule, service_period, timetable)


def process_stoptime(cur, config, schedule, service_period, table):
	
	# Lookup our directions first
	directions = {}
	cur.execute("select * from "+ config['prefix'] + "_direction")
	for row in cur:
		direction_id = row["direction_id"]
		name = row['direction_name']
		directions[direction_id] = name

	# Save these for helping us work out services that run past midnight
	last_trip_id = 0
	last_time = 0

	cur.execute("select * from "+ config['prefix'] + "_stops_" + table)
	for row in cur:
		route_id = str(config['index'] + int(row['line_id']))
		route = [r for r in schedule.GetRouteList() if r.route_id == route_id][0]

		stop_id = str(config['index'] + int(row['stop_id']))
		stop = [s for s in schedule.GetStopList() if s.stop_id == stop_id][0]

		headsign = directions[int(row["direction"])] # Get the direction from the other table
		trip_id = config['index'] + int(row['run_id'])

		# If the next time is past midnight, add more time to take it past 24 hours,
		# because GTFS requires it
		time = row["time"]
		if time < last_time:
			if last_trip_id == trip_id:
				time += 86400
		last_time = time
		last_trip_id = trip_id

		trip_list = [t for t in schedule.GetTripList() if t.trip_id == trip_id]

		# If we don't have an existing trip, create a new one
		if trip_list:
			trip = trip_list[0]
		else:
			trip = route.AddTrip(
				schedule, 
				headsign = headsign,
				trip_id = trip_id,
				service_period = service_period 
			)

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

	# Open SqliteDB
	con = sqlite3.connect(inputdb)
	con.row_factory = sqlite3.Row
	cur = con.cursor()
	
	# Create our schedule
	schedule = transitfeed.Schedule()

	# Agency
	schedule.AddAgency(config['name'], "http://www.metlinkmelbourne.com.au", "Australia/Melbourne", agency_id=config['id'])

	process_routes(cur, config, schedule)
	process_stops(cur, config, schedule)
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
    import pdb
    pdb.set_trace()

	config = settings[options.service]

	process_data(options.inputdb, config, options.output)
