#!/usr/bin/env python2

# Credit to https://twitter.com/andybotting for the script which served as a
# template for creating this one.

import os
import re
import csv
import inspect
from datetime import datetime, date, time, timedelta
from optparse import OptionParser
import pyproj
import osgeo.ogr
from osgeo import ogr
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

DEFAULT_SERVICE_INFO = [
    ("monfri", default_service_headways),
    ("sat", default_service_headways),
    ("sun", default_service_headways) ]

settings = {
    'train': {
        'name': 'Metro Trains - Upgraded',
        'url': 'http://www.bze.org.au',
        'system': 'Subway',
        'avespeed': 65,
        'id': 30,
        'index': 3000000,
    },
    'tram': {
        'name': 'Yarra Trams - Upgraded',
        'url': 'http://www.bze.org.au',
        'system': 'Tram',
        'avespeed': 35,
        'id': 32,
        'index': 3200000,
    },
    'bus': {
        'name': 'Melbourne Bus - Upgraded',
        'url': 'http://www.bze.org.au',
        'system': 'Bus',
        'avespeed': 30,
        'id': 34,
        'index': 3400000,
    }
}

#Fake data for testing - later will want to read these from a Spatial DB,
#  e.g. in PosgreSQL with Spatial addon or via shapefiles - as an output from QGIS.

### Hmmm - perhaps these should be Structs?
### Or should I keep it in the "pseudo-DB" form for now in anticipation of
###  reading from shapefiles later anyway

train_route_defs = [
    {
        "name": "Craigieburn",
        "directions": ["City", "Craigieburn"], #Could potentially do these
            #based on first and last stops ... but define as same for each line ...
        "segments": [0, 1, 2],
    } 
    ]
#"Ascot Vale Station",
#"Newmarket Station",
#"Kensington Station",
#"North Melbourne Station"

def create_gtfs_route_entries(route_defs, config, schedule):
    print "%s() called." % inspect.stack()[0][3]
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

        print "Adding route with ID %s, name '%s'" % \
            (route_id, route_long_name)
        schedule.AddRouteObject(route)


def create_gtfs_stop_entries(stops_shapefile, config, schedule):
    """This function requires that in the stops shapefile, there is an
    attribute called 'Name' listing the name of the stop. (Note: it is ok if
    this is actually just a number, but it will be treated as a string.)"""

    print "%s() called." % inspect.stack()[0][3]
    layer = stops_shapefile.GetLayer(0)
    for stop_cnt, stop_feature in enumerate(layer):
        
        stop_name = stop_feature.GetField('Name')
        stop_desc = None
        stop_code = None
        stop_id_gtfs = str(config['index'] + stop_cnt)
        geom = stop_feature.GetGeometryRef()
        lng = geom.GetX()
        lat = geom.GetY() 
        # TODO: For now assume they are in Lat/Lon WGS84 - really should
        # double-check and do a coordinate transform if not.

        stop = transitfeed.Stop(
            stop_id = stop_id_gtfs,
            name = stop_name,
            stop_code = stop_code,
            lat = lat,
            lng = lng,
        )
        print "Adding stop with ID %s, name '%s', lat,long of (%3f,%3f)" % \
            (stop_id_gtfs, stop_name, lat, lng)
        schedule.AddStopObject(stop)
    layer.ResetReading() # Necessary as we need to loop thru again later
    return        

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


def create_gtfs_trips_stoptimes(route_defs, route_segments_shp, stops_shp, config, schedule):
    """This function creates the GTFS trip and stoptime entries for every
    trip.

    It requires route definitions linking route names to a definition of segments
    in a shapefile.
    """ 

    # Initialise trip_id and counter
    trip_ctr = 0
    # TODO: force this as a default for now. Possible we might want to convert
    # this to a database or configurable per-route for now ...
    services_info = DEFAULT_SERVICE_INFO
    for serv_period, serv_headways in services_info:
        service_period = add_service_period(serv_period, schedule)
        for ii, route_def in enumerate(route_defs):
            gtfs_route_id = str(config['index'] + ii)
            #Re-grab the route entry from our GTFS schedule
            route = [r for r in schedule.GetRouteList() if r.route_id == gtfs_route_id][0]

            # For our basic scheduler, we're going to just create both trips in
            # both directions, starting at exactly the same time, at the same
            # frequencies. The real-world implication of this is at least
            # 2 vehicles needed to service each route.

            # The GTFS output creation logic is as follows:-
            # For each direction, add all the trips as per the needed frequency.
            for dir_id, direction in enumerate(route_def["directions"]):
                headsign = direction

                curr_period = 0    
                while curr_period < len(serv_headways):
                    curr_period_inc = timedelta(0)
                    curr_period_start = serv_headways[curr_period][0]
                    curr_period_end = serv_headways[curr_period][1]
                    period_duration = datetime.combine(date.today(), curr_period_end) - \
                        datetime.combine(date.today(), curr_period_start)
                    # This logic needed to handle periods that cross midnight
                    if period_duration < timedelta(0):
                        period_duration += timedelta(days=1)
                    curr_headway = timedelta(minutes=serv_headways[curr_period][2])

                    curr_start_time = curr_period_start
                    while curr_period_inc < period_duration:
                        trip_id = config['index'] + trip_ctr
                        trip = route.AddTrip(
                            schedule, 
                            headsign = headsign,
                            trip_id = trip_id,
                            service_period = service_period )

                        create_gtfs_trip_stoptimes(trip, curr_start_time,
                            route_def, dir_id, route_segments_shp,
                            stops_shp, config, schedule)
                        trip_ctr += 1

                        # Now update necessary variables ...
                        curr_period_inc += curr_headway
                        next_start_time = (datetime.combine(date.today(), curr_start_time) 
                            + curr_headway).time()
                        curr_start_time = next_start_time

                    curr_period += 1
    return                            


def calc_distance_km(segment):
    # In H's script, this will be saved as an attribute in the generation
    # phase.
    return float(segment.GetField('route_dist'))


def calc_time_on_segment(segment, stop_lyr, config):
    """Calculates travel time between two stops. Current algorithm is based on
    an average speed on that segment, and physical distance between them."""
    #avespeed = config['avespeed']
    avespeed = segment.GetField('avespeed')

    # TODO: update this from just reading the stops list to using the shapefile.
    s1_name = segment.GetField('stop1N')
    s2_name = segment.GetField('stop2N')

    s1 = get_stop_feature(s1_name, stop_lyr)
    s2 = get_stop_feature(s2_name, stop_lyr)
    distance_km = calc_distance_km(segment)
    time_hrs = distance_km / avespeed
    time_inc = timedelta(hours = time_hrs)
    # Now round to nearest second
    time_inc = time_inc - timedelta(microseconds=time_inc.microseconds) + \
        timedelta(seconds=round(time_inc.microseconds/1e6))
    return time_inc
    
def get_gtfs_stop_id(stop_id, config):
    return str(config['index'] + stop_id)

def get_gtfs_stop_byid(stop_id_gtfs, schedule):
    try:
        stop = [s for s in schedule.GetStopList() if s.stop_id == stop_id_gtfs][0]
    except IndexError:
        print "Error: seems like stop with ID %d isn't yet in GTFS " \
            "stops DB." % stop_id_gtfs
        sys.exit(1)
    return stop 

def get_gtfs_stop_byname(stop_name, schedule):
    try:
        stop = [s for s in schedule.GetStopList() if s.stop_name == stop_name][0]
    except IndexError:
        print "Error: seems like stop with name '%s' isn't yet in GTFS " \
            "stops DB." % stop_name
        sys.exit(1)
    return stop 


def get_stop_feature(stop_name, stop_lyr):
    # Just do a linear search for now.
    match_feature = None
    for feature in stop_lyr:
        if feature.GetField('Name') == stop_name:
            match_feature = feature
            break;    
    stop_lyr.ResetReading()        
    return match_feature

def get_route_segment(segment_id, route_segments_lyr):
    # Just do a linear search for now.
    match_feature = None
    for feature in route_segments_lyr:
        if int(feature.GetField('id')) == segment_id:
            match_feature = feature
            break;    
    route_segments_lyr.ResetReading()        
    return match_feature


def create_gtfs_trip_stoptimes(trip, trip_start_time, route_def, dir_id, route_segments_shp, stops_shp,
        config, schedule):

    print "\n%s() called with trip_id = %d, trip start time %s" % (inspect.stack()[0][3], \
         trip.trip_id, str(trip_start_time) )

    route_segments_lyr = route_segments_shp.GetLayer(0)
    stops_lyr = stops_shp.GetLayer(0)

    assert len(route_def['segments']) >= 1
    # If direction ID is 1 - generally "away from city" - create an iterable in reverse
    #  stop id order.
    if dir_id == 0:
        segments_iter = route_def["segments"]
    else:
        segments_iter = reversed(route_def["segments"])

    # We will create the stopping time object as a timedelta, as this way it will handle
    # trips that cross midnight the way GTFS requires (as a number that can increases past
    # 24:00 hours, rather than ticking back to 00:00)
    time_delta = datetime.combine(date.today(), trip_start_time) - \
        datetime.combine(date.today(), time(0))

    stop_seq = 0
    for seg_ctr, segment_id in enumerate(segments_iter):
        
        segment = get_route_segment(segment_id, route_segments_lyr)
        if segment is None:
            print "Error: didn't locate segment in shapefile with given id " \
                "%d." % (segment_id)
            sys.exit(1)    

        #This logic handles direction of the route for later steps.
        if dir_id == 0:
            first_stop_id = segment.GetField('stop1')
            second_stop_id = segment.GetField('stop2')
            first_stop_name = segment.GetField('stop1N')
            second_stop_name = segment.GetField('stop2N')
        else:
            first_stop_id = segment.GetField('stop2')
            second_stop_id = segment.GetField('stop1')
            first_stop_name = segment.GetField('stop2N')
            second_stop_name = segment.GetField('stop1N')
            
        # Enter a stop at first stop in the segment in chosen direction.
        problems = None
        # NB: temporarily searching by name.
        #first_stop_id_gtfs = get_gtfs_stop_id(first_stop_id, config)
        #first_stop = get_gtfs_stop_byid(first_stop_id_gtfs, schedule)
        first_stop = get_gtfs_stop_byname(first_stop_name, schedule)
        time_sec = time_delta.days * 24*60*60 + time_delta.seconds
        first_stop_time = transitfeed.StopTime(
            problems, 
            first_stop,
            pickup_type = 0, # Regularly scheduled pickup 
            drop_off_type = 0, # Regularly scheduled drop off
            shape_dist_traveled = None, 
            arrival_secs = time_sec,
            departure_secs = time_sec, 
            stop_time = time_sec, 
            stop_sequence = stop_seq
            )
        trip.AddStopTimeObject(first_stop_time)
        print "Added stop # %d for this route (stop ID %s) - at t %s" % (stop_seq, \
            first_stop.stop_id, time_delta)

        # Calculate the time duration to reach the second stop and add to
        # running time 
        time_inc = calc_time_on_segment(segment, stops_lyr, config)
        time_delta += time_inc
        stop_seq += 1

    # Now we've exited from the loop :- we need to now add a final stop for
    # the second stop in the final segment in the direction we're travelling.
    # second_stop_id should be set correctly from last run thru above loop.
    #final_stop_id_gtfs = get_gtfs_stop_id(second_stop_id, config)
    #final_stop = get_gtfs_stop_byid(final_stop_id_gtfs, schedule)
    final_stop = get_gtfs_stop_byname(second_stop_name, schedule)
    time_sec = time_delta.days * 24*60*60 + time_delta.seconds
    final_stop_time = transitfeed.StopTime(
        problems, 
        final_stop,
        pickup_type = 0, # Regularly scheduled pickup 
        drop_off_type = 0, # Regularly scheduled drop off
        shape_dist_traveled = None, 
        arrival_secs = time_sec,
        departure_secs = time_sec, 
        stop_time = time_sec, 
        stop_sequence = stop_seq
        )
    trip.AddStopTimeObject(final_stop_time)
    print "Added (final) stop time %d for this route (ID %s) - at t %s" % (stop_seq, \
        final_stop.stop_id, time_delta)
    return    


def process_data(input_segments_fname, input_stops_fname, config, output):
    # Create our schedule
    schedule = transitfeed.Schedule()
    # Agency
    schedule.AddAgency(config['name'], config['url'], "Australia/Melbourne", agency_id=config['id'])

    # Now see if we can open both needed shape files correctly
    stops_shp = osgeo.ogr.Open(input_stops_fname)
    route_segments_shp = osgeo.ogr.Open(input_segments_fname)
    # Now do actual data processing
    # TODO:- train_route_defs is hacked for now.
    create_gtfs_route_entries(train_route_defs, config, schedule)
    create_gtfs_stop_entries(stops_shp, config, schedule)
    create_gtfs_trips_stoptimes(train_route_defs, route_segments_shp,
        stops_shp, config, schedule)
    # Now close the shape files.
    stops_shp = None
    route_segments_shp = None

    schedule.Validate()
    schedule.WriteGoogleTransitFeed(output)


if __name__ == "__main__":

    parser = OptionParser()
    parser.add_option('--segments', dest='inputsegments', help='Shapefile of line segments.')
    parser.add_option('--stops', dest='inputstops', help='Shapefile of stops.')
    parser.add_option('--service', dest='service', help="Should be 'train', 'tram' or 'bus'.")
    parser.add_option('--output', dest='output', help='Path of output file. Should end in .zip')
    parser.set_defaults(output='google_transit.zip')
    (options, args) = parser.parse_args()

    if options.inputsegments is None:
        parser.print_help()
        parser.error("No segments shapefile path given.") 
    if options.inputstops is None:
        parser.print_help()
        parser.error("No stops shapefile path given.")
    if options.service is None:
        parser.print_help()
        parser.error("Need to specify a service.")

    config = settings[options.service]

    process_data(options.inputsegments, options.inputstops, config, options.output)
