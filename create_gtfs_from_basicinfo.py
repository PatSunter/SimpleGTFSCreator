#!/usr/bin/env python2

# Credit to https://twitter.com/andybotting for the script which served as a
# template for creating this one.

import os
import re
import csv
import inspect
import copy
from datetime import datetime, date, time, timedelta
from optparse import OptionParser
import sys
import os.path
from operator import itemgetter
import zipfile

import osgeo.ogr
from osgeo import ogr
import transitfeed

import parser_utils
import mode_timetable_info as m_t_info
import topology_shapefile_data_model as tp_model
import route_segs
import seg_speed_models

# Will determine how much infor is printed.
VERBOSE = False

# Calc this once to save a bit of time as its used a lot
TODAY = date.today()

ROUTE_WRITE_BATCH_SIZE = 10

class Seq_Stop_Info:
    """A small struct to store key info about a stop in the sequence of a
    particular route, pulled from the Shapefiles, that will be later used
    to define time to enter for a stop in actual timetable."""
    def __init__(self, gtfs_stop):
        self.gtfs_stop = gtfs_stop
        self.dist_km_to_next = 0
        # This last attribute can be used by SpeedModel classes to save
        #  any extra info about speed on this segment needed.
        self.extra_speed_info = None

    def save_seq_stop_info(self, next_segment, stops_lyr, speed_model):
        self.dist_km_to_next = tp_model.get_distance_km(next_segment)
        self.extra_speed_info = speed_model.save_extra_seg_speed_info(
            next_segment, stops_lyr)

    def calc_time_on_next_segment(self, speed_model, mode_config, curr_time,
            peak_status):
        """Calculates travel time between two stops. Current algorithm is 
        based on an average speed on that segment, and physical distance
        between them."""
        seg_speed = speed_model.get_speed_on_next_segment(self.extra_speed_info,
            mode_config, curr_time, peak_status)
        time_hrs = self.dist_km_to_next / float(seg_speed)
        # Need to round this to nearest second and return as a timedelta.
        return timedelta(seconds=round(time_hrs * 3600))
 
def build_stop_list_and_seg_info_along_route(route_def, dir_id,
        route_segments_shp, stops_shp, mode_config, schedule, seg_speed_model,
        stop_id_to_gtfs_stop_id_map):

    prebuilt_stop_info_list = []
    if len(route_def.ordered_seg_ids) == 0:
        print "Warning: for route name '%s: %s', no route segments defined." \
            % (route_def.short_name, route_def.long_name)
        return []
    route_segments_lyr = route_segments_shp.GetLayer(0)
    stops_lyr = stops_shp.GetLayer(0)
    # Apply a filter to speed up calculations - only segments on this route.
    where_clause = "%s LIKE '%%%s' OR %s LIKE '%%%s,%%'" % \
        (tp_model.SEG_ROUTE_LIST_FIELD, route_def.id,\
        tp_model.SEG_ROUTE_LIST_FIELD, route_def.id)
    route_segments_lyr.SetAttributeFilter(where_clause)
    segs_lookup_table = tp_model.build_segs_lookup_table(route_segments_lyr)

    ordered_seg_refs = route_segs.create_ordered_seg_refs_from_ids(
        route_def.ordered_seg_ids, segs_lookup_table)
    stop_ids_along_route = route_segs.extract_stop_list_along_route(
        ordered_seg_refs)

    # If direction ID is 1 - process segments and stops in reversed order.
    if dir_id == 0:
        seg_refs_in_dir = iter(ordered_seg_refs)
    else:
        seg_refs_in_dir = reversed(ordered_seg_refs)
        stop_ids_along_route.reverse()

    for seg_ctr, seg_ref in enumerate(seg_refs_in_dir):
        first_stop_id = stop_ids_along_route[seg_ctr]
        first_stop_id_gtfs = stop_id_to_gtfs_stop_id_map[first_stop_id]
        first_stop = schedule.GetStop(first_stop_id_gtfs)
        # We are still going to save key info now, to save accessing the
        # shapefile layers again unnecessarily later.
        seg_feature = segs_lookup_table[seg_ref.seg_id]
        if seg_feature is None:
            print "Error: didn't locate segment in shapefile with given id " \
                "%d." % (segment_id)
            sys.exit(1)    
        s_info = Seq_Stop_Info(first_stop)
        s_info.save_seq_stop_info(seg_feature, stops_lyr, seg_speed_model)
        prebuilt_stop_info_list.append(s_info)

    # Now we've exited from the loop :- we need to now add info for
    #  final stop of the last segment.
    final_stop_id_gtfs = stop_id_to_gtfs_stop_id_map[stop_ids_along_route[-1]]
    final_stop = schedule.GetStop(final_stop_id_gtfs)
    s_info_final = Seq_Stop_Info(final_stop)
    # Final stop doesn't have speed etc on segment, so leave as zero.
    prebuilt_stop_info_list.append(s_info_final)

    for segment in segs_lookup_table.itervalues():
        # tidy up memory.
        segment.Destroy()
    route_segments_lyr.SetAttributeFilter(None)
    return prebuilt_stop_info_list

def create_gtfs_route_entries(route_defs, mode_config, schedule):
    print "%s() called." % inspect.stack()[0][3]
    route_id_to_gtfs_route_id_map = {}
    # Routes
    sorted_route_defs = sorted(route_defs,
        key=route_segs.get_route_order_key_from_name)
    for ii, route_def in enumerate(sorted_route_defs):
        route_long_name = route_def.long_name
        route_short_name = route_def.short_name
        route_description = None
        gtfs_route_id = str(mode_config['index'] + ii)
        route_id_to_gtfs_route_id_map[route_def.id] = gtfs_route_id
        route = transitfeed.Route(
            short_name = route_short_name, 
            long_name = route_long_name,
            route_type = mode_config['system'],
            route_id = gtfs_route_id
            )
        print "Adding route with ID %s, name '%s: %s'" % \
            (gtfs_route_id, route_short_name, route_long_name)
        schedule.AddRouteObject(route)
    return route_id_to_gtfs_route_id_map        

def create_gtfs_stop_entries(stops_shapefile, mode_config, schedule):
    """This function requires that in the stops shapefile, there is an
    attribute called 'Name' listing the name of the stop. (Note: it is ok if
    this is actually just a number, but it will be treated as a string.)"""

    print "%s() called." % inspect.stack()[0][3]

    stop_id_to_gtfs_stop_id_map = {}
    layer = stops_shapefile.GetLayer(0)
    stop_prefix = mode_config['stop_prefix']
    for stop_cnt, stop_feature in enumerate(layer):
        
        #stop_name = stop_feature.GetField('Name')
        # For BZE's "Interchange" stops file
        stop_id = stop_feature.GetField(tp_model.STOP_ID_FIELD)
        if stop_id is None:
            continue
        stop_name = stop_prefix + str(int(stop_id))
        stop_desc = None
        stop_code = None
        stop_id_gtfs = str(mode_config['index'] + stop_cnt)
        stop_id_to_gtfs_stop_id_map[stop_id] = stop_id_gtfs
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
        if VERBOSE:
            print "Adding stop with ID %s, name '%s', lat,long of (%3f,%3f)" % \
                (stop_id_gtfs, stop_name, lat, lng)
        schedule.AddStopObject(stop)
    # See http://gis.stackexchange.com/questions/76683/python-ogr-nested-loop-only-loops-once
    layer.ResetReading() # Necessary as we need to loop thru again later
    return stop_id_to_gtfs_stop_id_map       

def add_service_period(days_week_str, schedule):    
    service_period = transitfeed.ServicePeriod(id=days_week_str)
    service_period.SetStartDate(m_t_info.START_DATE_STR)
    service_period.SetEndDate(m_t_info.END_DATE_STR)
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

def build_stop_name_to_gtfs_id_map(schedule):
    stop_name_to_gtfs_id_map = {}
    for stop_id, stop in schedule.stops.iteritems():
        stop_name_to_gtfs_id_map[stop.stop_name] = stop_id
    return stop_name_to_gtfs_id_map

def create_gtfs_service_periods(services_info, schedule):
    for serv_period, period_info in services_info:
        gtfs_period = add_service_period(serv_period, schedule)

def create_gtfs_trips_stoptimes(route_defs, route_segments_shp, stops_shp,
        mode_config, schedule, seg_speed_model, route_id_to_gtfs_id_map,
        stop_id_to_gtfs_stop_id_map, initial_trip_id=None):
    """This function creates the GTFS trip and stoptime entries for every trip.

    It requires route definitions linking route names to a definition of
    segments in a shapefile.
    """ 
    # Build this now for fast lookups.
    # Initialise trip_id and counter
    # Need to check existing trip count so updates are right numbers
    if initial_trip_id:
        trip_ctr = initial_trip_id
    else:
        trip_ctr = len(schedule.trips)
    # Do routes and directions as outer loops rather than service periods - as 
    # allows maximal pre-calculation
    sorted_route_defs = sorted(route_defs,
        key=route_segs.get_route_order_key_from_name)
    for ii, route_def in enumerate(sorted_route_defs):
        gtfs_route_id = route_id_to_gtfs_id_map[route_def.id]
        ntrips_this_route = create_gtfs_trips_stoptimes_for_route(route_def,
            route_segments_shp,
            stops_shp, mode_config, schedule, seg_speed_model,
            gtfs_route_id, stop_id_to_gtfs_stop_id_map,
            trip_ctr)
        trip_ctr += ntrips_this_route    
    return

def create_gtfs_trips_stoptimes_for_route(route_def, route_segments_shp,
        stops_shp, mode_config, schedule, seg_speed_model,
        gtfs_route_id, stop_id_to_gtfs_stop_id_map,
        init_trip_ctr):

    print "Adding trips and stops for route '%s: %s'" \
        % (route_def.short_name, route_def.long_name)
    ntrips_this_route = 0
    #Re-grab the route entry from our GTFS schedule
    route = schedule.GetRoute(gtfs_route_id)
    # For our basic scheduler, we're going to just create both trips in
    # both directions, starting at exactly the same time, at the same
    # frequencies. The real-world implication of this is at least
    # 2 vehicles needed to service each route.
    for dir_id, direction in enumerate(route_def.dir_names):
        headsign = direction
        # Pre-calculate the stops list and save relevant info related to 
        # speed calculation from shapefiles for later.
        # as this is a moderately expensive operation.
        # This way we do this just once per route and direction.
        prebuilt_stop_info_list = build_stop_list_and_seg_info_along_route(
            route_def, dir_id, route_segments_shp, stops_shp,
            mode_config, schedule, seg_speed_model,
            stop_id_to_gtfs_stop_id_map)
        
        # N.B.: Possible we might want to convert
        # the services_info of headway periods to a configurable per-route 
        # later rather than per mode...
        services_info = mode_config['services_info']
        for serv_period, serv_headways in services_info:
            print "Handing service period '%s'" % (serv_period)
            try:
                gtfs_period = schedule.GetServicePeriod(serv_period)
            except KeyError:    
                gtfs_period = add_service_period(serv_period, schedule)

            curr_period = 0    
            while curr_period < len(serv_headways):
                curr_period_inc = timedelta(0)
                curr_period_start = serv_headways[curr_period][0]
                curr_period_end = serv_headways[curr_period][1]
                period_duration = datetime.combine(TODAY, \
                    curr_period_end) - \
                    datetime.combine(TODAY, curr_period_start)
                # This logic needed to handle periods that cross midnight
                if period_duration < timedelta(0):
                    period_duration += timedelta(days=1)
                curr_headway = timedelta(minutes=serv_headways[curr_period][2])

                curr_start_time = curr_period_start
                while curr_period_inc < period_duration:
                    trip_id = mode_config['index'] + init_trip_ctr \
                        + ntrips_this_route   
                    trip = route.AddTrip(
                        schedule, 
                        headsign = headsign,
                        trip_id = trip_id,
                        service_period = gtfs_period )

                    create_gtfs_trip_stoptimes(trip, curr_start_time,
                        curr_period, serv_headways,
                        route_def, prebuilt_stop_info_list, mode_config,
                        schedule, seg_speed_model)
                    ntrips_this_route += 1
                    # Now update necessary variables ...
                    curr_period_inc += curr_headway
                    next_start_time = (datetime.combine(TODAY, \
                        curr_start_time) + curr_headway).time()
                    curr_start_time = next_start_time
                curr_period += 1
    return ntrips_this_route

def create_gtfs_trip_stoptimes(trip, trip_start_time,
        trip_start_period, serv_headways,
        route_def, prebuilt_stop_info_list, mode_config, schedule,
        seg_speed_model):
    """Creates the actual stop times on a route.
    Since Apr 2014, now needs to access curr_period and serv_headways,
    since we are allowing for time-dependent vehicle speeds by serv period.
    Still uses pre-calculated list of stops, segments along a route."""

    if VERBOSE:
        print "\n%s() called on route '%s', trip_id = %d, trip start time %s"\
            % (inspect.stack()[0][3], route_def.name, trip.trip_id,\
                str(trip_start_time))

    if len(route_def.ordered_seg_ids) == 0:
        print "Warning: for route name '%s', no route segments defined " \
            "skipping." % route_def.name
        return

    # We will also create the stopping time object as a timedelta, as this way
    # it will handle trips that cross midnight the way GTFS requires
    # (as a number that can increases past 24:00 hours,
    # rather than ticking back to 00:00)
    start_time_delta = datetime.combine(TODAY, trip_start_time) - \
        datetime.combine(TODAY, time(0))
    cumulative_time_on_trip = timedelta(0)
    # These variable needed to track change in periods for possible
    # time-dependent vehicle speed in peak or off-peak
    period_at_stop = trip_start_period
    peak_status = serv_headways[period_at_stop][3]
    time_at_stop = trip_start_time
    end_elapsed_curr_p = m_t_info.calc_service_time_elapsed_end_period(
        serv_headways, period_at_stop)
    n_stops_on_route = len(prebuilt_stop_info_list)

    for stop_seq, s_info in enumerate(prebuilt_stop_info_list):
        # Enter a stop at first stop in the segment in chosen direction.
        problems = None
        # Enter the stop info now at the start. Then will add on time in this
        # segment.
        # Need to add cumulative time on trip start time to get it as a 'daily'
        # time_delta, suited for GTFS.
        stop_time_delta = start_time_delta + cumulative_time_on_trip
        time_at_stop = (datetime.min + stop_time_delta).time()
        time_sec_for_gtfs = stop_time_delta.days * 24*60*60 \
            + stop_time_delta.seconds
        gtfs_stop_time = transitfeed.StopTime(
            problems, 
            s_info.gtfs_stop,
            pickup_type = 0, # Regularly scheduled pickup 
            drop_off_type = 0, # Regularly scheduled drop off
            shape_dist_traveled = None, 
            arrival_secs = time_sec_for_gtfs,
            departure_secs = time_sec_for_gtfs, 
            stop_time = time_sec_for_gtfs, 
            stop_sequence = stop_seq
            )
        trip.AddStopTimeObject(gtfs_stop_time)
        if VERBOSE:
            print "Added stop # %d for this route (stop ID %s) - at t %s" \
                % (stop_seq, gtfs_stop.stop_id, stop_time_delta)

        # Given elapsed time at stop we just added:- have we just crossed over
        # int peak period of schedule for this mode? Will affect calc. time to
        # next stop.
        # N.B.: first part of check is- for last trips of the 'day' 
        # (even if after # midnite), they will may still be on the
        # road/rails after the
        # nominal end time of the period. In this case, just keep going
        # in same conditions of current period.
        serv_elapsed = m_t_info.calc_total_service_time_elapsed(
            serv_headways, time_at_stop)
        if (period_at_stop+1 < len(serv_headways)) \
                and serv_elapsed >= end_elapsed_curr_p:
            period_at_stop += 1
            peak_status = serv_headways[period_at_stop][3]
            end_elapsed_curr_p = m_t_info.calc_service_time_elapsed_end_period(
                serv_headways, period_at_stop)
            
        # Only have to do time inc. calculations if more stops remaining.
        if (stop_seq+1) < n_stops_on_route:
            time_inc = s_info.calc_time_on_next_segment(seg_speed_model,
                mode_config, stop_time_delta, peak_status)
            cumulative_time_on_trip += time_inc
    return

def get_partial_save_name(output_fname, ii):
    fname = output_fname+".partial.%d.zip" % ii
    return fname

def process_data(route_defs_csv_fname, input_segments_fname,
        input_stops_fname, mode_config, output, use_seg_speeds,
        memory_db):
    # Now see if we can open both needed shape files correctly
    route_defs = route_segs.read_route_defs(route_defs_csv_fname)
    route_segments_shp = osgeo.ogr.Open(input_segments_fname)
    if route_segments_shp is None:
        print "Error, route segments shape file given, %s , failed to open." \
            % (input_segments_fname)
        sys.exit(1) 
    stops_shp = osgeo.ogr.Open(input_stops_fname)
    if stops_shp is None:
        print "Error, stops shape file given, %s , failed to open." \
            % (input_stops_fname)
        sys.exit(1)

    if use_seg_speeds:
        seg_speed_model = seg_speed_models.PerSegmentPeakOffPeakSpeedModel()
    else:
        seg_speed_model = seg_speed_models.ConstantSpeedPerModeModel()

    partial_save_files = []
    trips_total = 0
    for ii, r_start in enumerate(range(0, len(route_defs), \
            ROUTE_WRITE_BATCH_SIZE)):
        # Create our schedule
        schedule = transitfeed.Schedule(memory_db=memory_db)
        # Agency
        schedule.AddAgency(mode_config['name'], mode_config['url'],
            mode_config['loc'], agency_id=mode_config['id'])
        create_gtfs_service_periods(mode_config['services_info'], schedule)
        route_id_to_gtfs_route_id_map = create_gtfs_route_entries(route_defs,
            mode_config, schedule)
        stop_id_to_gtfs_stop_id_map = create_gtfs_stop_entries(stops_shp,
            mode_config, schedule)
        r_end = r_start + (ROUTE_WRITE_BATCH_SIZE-1)
        if r_end >= len(route_defs):
            r_end = len(route_defs)-1
        print "Processing routes %d to %d" % (r_start, r_end)
        create_gtfs_trips_stoptimes(route_defs[r_start:r_end+1],
            route_segments_shp, stops_shp, mode_config, schedule,
            seg_speed_model, route_id_to_gtfs_route_id_map,
            stop_id_to_gtfs_stop_id_map,
            initial_trip_id = trips_total)
        trips_total += len(schedule.trips)
        fname = get_partial_save_name(output, ii)
        print "About to save timetable so far to file %s in case..." % fname
        schedule.WriteGoogleTransitFeed(fname)
        print "...finished writing."
        if fname not in partial_save_files:
            partial_save_files.append(fname)

    # Now we want to re-combine the separate zip files together
    # to create our master schedule
    master_schedule = transitfeed.Schedule(memory_db=False)
    master_schedule.AddAgency(mode_config['name'], mode_config['url'],
        mode_config['loc'], agency_id=mode_config['id'])
    create_gtfs_service_periods(mode_config['services_info'],
        master_schedule)
    create_gtfs_route_entries(route_defs, mode_config, master_schedule)
    create_gtfs_stop_entries(stops_shp, mode_config, master_schedule)
    # Now close the shape files.
    stops_shp = None
    route_segments_shp = None

    # Load it up progressively from partial files.
    for fname in partial_save_files:
        loader = transitfeed.Loader(feed_path=fname,
            problems=transitfeed.ProblemReporter(),
            memory_db=memory_db,
            load_stop_times=True)
        print "... now re-opening partial file %s ...." % fname 
        part_schedule = loader.Load()
        for trip in part_schedule.trips.itervalues():
            stop_times = trip.GetStopTimes()
            master_schedule.AddTripObject(trip)
            for stop_time in stop_times:
                trip.AddStopTimeObject(stop_time)
        part_schedule = None

    print "About to do final validate and write ...."
    master_schedule.Validate()
    master_schedule.WriteGoogleTransitFeed(output)
    print "Written successfully to: %s" % output
    #print "Cleaning up temp save files."
    #for fname in partial_save_files:
    #    if os.path.exists(fname):
    #        print "Deleting %s" % fname
    #        os.unlink(fname)

if __name__ == "__main__":
    allowedServs = ', '.join(sorted(["'%s'" % key for key in \
        m_t_info.settings.keys()]))
    parser = OptionParser()
    parser.add_option('--routedefs', dest='routedefs', 
        help='CSV file listing name, directions, and segments of each route.')
    parser.add_option('--segments', dest='inputsegments', help='Shapefile '\
        'of line segments.')
    parser.add_option('--stops', dest='inputstops', help='Shapefile of stops.')
    parser.add_option('--service', dest='service',
        help="Should be one of %s" % allowedServs)
    parser.add_option('--output', dest='output', help='Path of output file. '\
        'Should end in .zip')
    parser.add_option('--usesegspeeds', dest='usesegspeeds', 
        help='Use per-segment speeds defined in route segments shapefile? '\
            'If false, then will just use a constant speed defined per mode.')
    parser.add_option('--memorydb', dest='memorydb', 
        help='Should the GTFS schedule use an in-memory DB, or file based '\
            'one? Creating large GTFS schedules can be memory-hungry.')
    parser.set_defaults(output='google_transit.zip', usesegspeeds='True',
        memorydb='True')
    (options, args) = parser.parse_args()

    if options.routedefs is None:
        parser.print_help()
        parser.error("No route definitions CSV file path given.") 
    if options.inputsegments is None:
        parser.print_help()
        parser.error("No segments shapefile path given.") 
    if options.inputstops is None:
        parser.print_help()
        parser.error("No stops shapefile path given.")
    if options.service is None:
        parser.print_help()
        parser.error("No service option requested. Should be one of %s" \
            % (allowedServs))
    if options.service not in m_t_info.settings:
        parser.print_help()
        parser.error("Service option requested '%s' not in allowed set, of %s" \
            % (options.service, allowedServs))

    use_seg_speeds = parser_utils.str2bool(options.usesegspeeds)
    memory_db = parser_utils.str2bool(options.memorydb)

    mode_config = m_t_info.settings[options.service]

    process_data(
        os.path.expanduser(options.routedefs),
        os.path.expanduser(options.inputsegments), 
        os.path.expanduser(options.inputstops),
        mode_config,
        os.path.expanduser(options.output),
        use_seg_speeds,
        memory_db)
