#!/usr/bin/env python2

# Credit to https://twitter.com/andybotting for the script which served as a
# template for creating this one.

import os
import sqlite3
import re
import inspect
from datetime import datetime, date, time, timedelta
from optparse import OptionParser
import sys

import transitfeed

# These are plain strings, as required by the transitfeed library
START_DATE_STR = '20130101'
END_DATE_STR = '20131231'

#Format:
# avespeed: average speed (km/h)
# headway: how often each hour a vehicle arrives
# first service: the first service of the day
# last service: the last service of the day. (Ideally should be able to do
#  after midnight ... obviously should be lower than first service though).
# id: Needed for GTFS - a unique ID (important if going to work with multiple
# agencies in a combined larger GTFS file or multiple files.
# index: Similar to ID, but will be used to add route numbers to this index
#  to generate a unique number for each route.

# For speeds - see HiTrans guide, page 127

#Service periods is a list of tuples:-
# Where each is a start time, end time, and then a headway during that period.
default_service_headways = [
    (time(05,00), time(07,30), 20),
    (time(07,30), time(10,00), 5),
    (time(10,00), time(16,00), 10),
    (time(16,00), time(18,30), 5),
    (time(18,30), time(23,00), 10),
    (time(23,00), time(02,00), 20)
    ]

settings = {
    'train': {
        'name': 'Metro Trains - Upgraded',
        'system': 'Subway',
        'avespeed': 65,
        'headways': default_service_headways,
        'firstservice': time(05,00),
        'lastservice': time(01,00), #1AM
        'id': 30,
        'index': 3000000,
    },
    'tram': {
        'name': 'Yarra Trams - Upgraded',
        'system': 'Tram',
        'avespeed': 35,
        'headway': default_service_headways,
        'firstservice': time(05,00),
        'lastservice': time(01,00), #1AM
        'id': 32,
        'index': 3200000,
    },
    'bus': {
        'name': 'Melbourne Bus - Upgraded',
        'system': 'Bus',
        'avespeed': 30,
        'headway': default_service_headways,
        'firstservice': time(05,00),
        'lastservice': time(01,00),
        'id': 34,
        'index': 3400000,
    }
}

#Fake data for testing - later will want to read these from a Spatial DB,
#  e.g. in PosgreSQL with Spatial addon or via shapefiles - as an output from QGIS.

### Hmmm - perhaps these should be Structs?
### Or should I keep it in the "pseudo-DB" form for now in anticipation of
###  reading from shapefiles later anyway

train_stops = {
    '0': ("North Melbourne", (144.94151,-37.806309)),
    '1': ("Kensington", (144.930525,-37.793777)),
    '2': ("Newmarket", (144.928984,-37.787326))
    }

train_route_defs = [
    {
        "name": "Craigieburn",
        "directions": ["City", "Craigieburn"], #Could potentially do these
            #based on first and last stops ... but define as same for each line ...
        "stop_ids": [2, 1, 0],
        "service_periods": ["monfri", "sat", "sun"]
    } 
    ]

def process_routes(route_defs, config, schedule):
    # Routes
    for ii, route_def in enumerate(route_defs):
        route_long_name = route_def["name"]
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



def process_stops(stops_info, config, schedule):
    # Stops
    print "%s() called." % inspect.stack()[0][3]

    for stop_id, stop_info in stops_info.iteritems():

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

        print "Adding stop with ID %d, name '%s', lat,long of (%3f,%3f)" % \
            (int(stop_id), stop_name, lat, lng)

        schedule.AddStopObject(stop)

def add_service_period(days_week_str, schedule):    
    service_period = transitfeed.ServicePeriod(id=days_week_str)
    service_period.SetStartDate(START_DATE_STR)
    service_period.SetEndDate(END_DATE_STR)

    # Set the day of week times
    if days_week_str == 'monthur':
        service_period.SetDayOfWeekHasService(0)
        service_period.SetDayOfWeekHasService(1)
        service_period.SetDayOfWeekHasService(2)
        service_period.SetDayOfWeekHasService(3)
    elif days_week_str == 'fri':    
        service_period.SetDayOfWeekHasService(4)
    elif days_week_str == 'monfri':
        service_period.SetWeekdayService()
    elif days_week_str == 'sat':
        service_period.SetDayOfWeekHasService(5)
    elif days_week_str == 'sun':
        service_period.SetDayOfWeekHasService(6)
    else:
        print("Error: Timetable %s not defined" % days_week_str)

    schedule.AddServicePeriodObject(service_period, validate=False)
    return service_period


def create_trips_stoptimes(route_defs, stops, config, schedule):
    """This function creates the GTFS trip and stoptime entries for every
    trip.

    N.B. currently reads these in from the route_defs and stops data
    structures. In future may want to read these from the Shapefiles that
    define these directly.""" 

    # Initialise trip_id and counter
    trip_ctr = 0
    for ii, route_def in enumerate(route_defs):
        route_id = str(config['index'] + ii)
        #Re-grab the route entry from our GTFS schedule
        route = [r for r in schedule.GetRouteList() if r.route_id == route_id][0]

        # For our basic scheduler, we're going to just create both trips in
        # both directions, starting at exactly the same time, at the same
        # frequencies. In reality this implies at least 2 vehicles per route.

        # TODO: currently just doing mon-fri services ...
        service_period = add_service_period("monfri", schedule)

        for dir_id, direction in enumerate(route_def["directions"]):
            headsign = direction
                
            curr_period = 0
            first_service = config['headways'][curr_period][0]
            curr_period_end = config['headways'][curr_period][1]

            period_duration = datetime.combine(date.today(), curr_period_end) - \
                datetime.combine(date.today(), first_service)
            # This logic needed to handle periods that cross midnight
            if period_duration < timedelta(0):
                period_duration += timedelta(days=1)
            curr_period_inc = timedelta(0)
            curr_start_time = first_service

            while curr_period < len(config['headways']):

                trip_id = config['index'] + trip_ctr
                trip = route.AddTrip(
                    schedule, 
                    headsign = headsign,
                    trip_id = trip_id,
                    service_period = service_period )

                create_trip_stoptimes(route_def, trip, curr_start_time, dir_id,
                    config, schedule)

                # Now update necessary variables ...
                trip_ctr += 1
                curr_headway = timedelta(minutes=config['headways'][curr_period][2])
                curr_period_inc += curr_headway

                if curr_period_inc < period_duration:
                    next_start_time = (datetime.combine(date.today(), curr_start_time) 
                        + curr_headway).time()
                    curr_start_time = next_start_time
                else:
                    if curr_period == (len(config['headways'])-1):
                        # Check we've processed all service periods - if we
                        # have, then break.
                        break
                    else:
                        next_start_time = config['headways'][curr_period+1][0]
                        next_end_time = config['headways'][curr_period+1][1]
                        period_duration = datetime.combine(date.today(), next_end_time) - \
                            datetime.combine(date.today(), next_start_time)
                        if period_duration < timedelta(0):
                            period_duration += timedelta(days=1)
                        curr_start_time = next_start_time
                        curr_period_inc = timedelta(0)
                        curr_period += 1
    return                            



def create_trip_stoptimes(route_def, trip, trip_start_time, dir_id, config, schedule):

    print "\n%s() called with trip_id = %d, trip start time %s" % (inspect.stack()[0][3], \
         trip.trip_id, str(trip_start_time) )

    # If direction ID is 1 - generally "away from city" - create an iterable  in reverse
    #  stop id order.
    if dir_id == 0:
        stop_ids = route_def["stop_ids"]
    else:
        stop_ids = reversed(route_def["stop_ids"])

    # We will create the stopping time object as a timedelta, as this way it will handle
    # trips that cross midnight the way GTFS requires (as a number that can increases past
    # 24:00 hours, rather than ticking back to 00:00)
    time_delta = datetime.combine(date.today(), trip_start_time) - \
        datetime.combine(date.today(), time(0))

    for stop_seq, stop_id in enumerate(stop_ids):

        stop_id_gtfs = str(config['index'] + stop_id)
        try:
            stop = [s for s in schedule.GetStopList() if s.stop_id == stop_id_gtfs][0]
        except IndexError:
            print "Error: seems like stop with ID %d isn't yet in GTFS stops DB." % stop_id_gtfs
            sys.exit(1)

        if stop_seq > 0:
            # TODO: calculate distance from the last stop (e.g. based on GIS co-ordinates)
            # TODO: calc next time :- distance / speed.
            # HACK for now
            time_inc_laststop = timedelta(minutes = 8)
            time_delta += time_inc_laststop

        time_sec = time_delta.days * 24*60*60 + time_delta.seconds

        # Not currently using this Problems data-reporting capability of GTFS
        # library
        problems = None

        stop_time = transitfeed.StopTime(
            problems, 
            stop,
            pickup_type = 0, # Regularly scheduled pickup 
            drop_off_type = 0, # Regularly scheduled drop off
            shape_dist_traveled = None, 
            arrival_secs = time_sec,
            departure_secs = time_sec, 
            stop_time = time_sec, 
            stop_sequence = stop_seq
            )
        trip.AddStopTimeObject(stop_time)
        print "Added stop time %d for this route (ID %s) - at t %s" % (stop_id, \
            stop_id_gtfs, time_delta)


def process_data(inputdb, config, output):
    # Create our schedule
    schedule = transitfeed.Schedule()

    # Agency
    schedule.AddAgency(config['name'], "http://www.bze.org.au", "Australia/Melbourne", agency_id=config['id'])

    # Hacked the inputs here ...
    process_routes(train_route_defs, config, schedule)
    process_stops(train_stops, config, schedule)
    create_trips_stoptimes(train_route_defs, train_stops, config, schedule)

    schedule.Validate()
    schedule.WriteGoogleTransitFeed(output)


if __name__ == "__main__":

    parser = OptionParser()
    parser.add_option('--file', dest='inputdb', help='SQLite3 databse file.')
    parser.add_option('--service', dest='service', help='Should be train, tram or bus.')
    parser.add_option('--output', dest='output', help='Path of output file. Should end in .zip')
    parser.set_defaults(output='google_transit.zip')
    (options, args) = parser.parse_args()

    # Hack override ...
    options.service = "train"
    config = settings[options.service]

    process_data(options.inputdb, config, options.output)
