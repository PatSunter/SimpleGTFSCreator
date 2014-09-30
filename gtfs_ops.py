"""These are convenience functions, that I find useful over-and-above the
functionality provided by the Google-developed Python gtfs package.

See:- https://code.google.com/p/googletransitdatafeed/wiki/TransitFeed

They deal with the basic 'schedule' Idiom and related classes of that package."""

import os, sys
import os.path
import operator
import copy
from datetime import time, datetime, date, timedelta
import csv

import transitfeed

from misc_utils import pairs
import lineargeom

SEC_PER_DAY = 86400

DEFAULT_FALLBACK_SEG_SPEED_KM_H = 10.0

# Converting transitfeed's basic time representation, to Python times,
#   and vice-versa

def toTimeOfDay(secs_since_midnight):
    """Convert an input number of 'seconds since midnight of the current
    service day' to a Python time object.
    NOTE:- if """
    td = timedelta(seconds=secs_since_midnight)
    return tdToTimeOfDay(td)

def tdToTimeOfDay(td):
    return (datetime.combine(date.today(), time(0)) + td).time()

def tdToSecs(td):
    """Convert a Python timedelta object to an amount of seconds, as a double.
    (Useful for back-converting timedeltas into the straight seconds form
    needed by the transitfeed library."""
    secs = td.days * SEC_PER_DAY + td.seconds + td.microseconds / float(1e6)
    return secs

# Utility printing functions

def printAllStopNamesInTrip(trip):    
    snames = [s['stop_name'] for s in trip.GetPattern()]
    print ", ".join(snames)

def printStopsCSV_InTrip(trip, schedule):
    route = schedule.GetRoute(trip['route_id'])
    print "Trip '%s', to '%s', part of route '%s' ('%s')" % \
        (trip['trip_id'], trip['trip_headsign'], \
        route['route_long_name'], route['route_id']) 
    print "stopname,lat,lon"
    for s in trip.GetPattern():
        print "%s,%s,%s" % (s['stop_name'], s['stop_lat'], s['stop_lon'])

def printStops_times_CSV(trip, schedule):
    route = schedule.GetRoute(trip['route_id'])
    print "Trip '%s', to '%s', part of route '%s' ('%s')" % \
        (trip['trip_id'], trip['trip_headsign'], \
        route['route_long_name'], route['route_id']) 
    print "stopname,lat,lon,time"
    stimes_gtfs = trip.GetStopTimes()
    stime_pys = [time(tsecs/(60*60), tsecs % (60*60)/60, tsecs % 60) \
        for tsecs in map(operator.attrgetter('arrival_secs'), stimes_gtfs)]
    for s, stime in zip(trip.GetPattern(), stime_pys):
        print "%s,%s,%s,%s" % (s['stop_name'], s['stop_lat'], s['stop_lon'], \
            stime.strftime("%H:%M:%S"))

def printTripInfoForStops(stop_ids):
    for stop_id in stop_ids:
        print "for stop id '%s'" % stop_id
        stop = schedule.GetStop(stop_id)
        print "is part of trips:"
        trips = stop.GetTrips()
        print "  %s" % ", ".join([t['trip_id'] for t in trips])
        print "which are part of routes:"
        unique_routes = list(set([schedule.GetRoute(t['route_id']) \
            for t in trips]))
        #trips_unique_routes = getTripsWithUniqueRoutes(trips)
        print "Printing stopping patterns for these trips in diff routes."
        unique_routes_found = [False for r in unique_routes]
        trip_iter = iter(trips)
        while False in unique_routes_found:
            trip = trip_iter.next()
            route_id = trip['route_id']
            for ii, r in enumerate(unique_routes):
                if route_id == r['route_id']:
                    unique_routes_found[ii] = True
                    break
            printStopsCSV_InTrip(trip, schedule)        
    return

# General Access helper functions

def getRouteByShortName(schedule, short_name):
    for r_id, route in schedule.routes.iteritems():
        if route.route_short_name == short_name:
            return r_id, route
    return None, None

def getRouteByLongName(schedule, long_name):
    for r_id, route in schedule.routes.iteritems():
        if route.route_long_name == long_name:
            return r_id, route
    return None, None

# Tools for manipulating a schedule, and/or adding to a new schedule.

def copy_selected_routes(input_schedule, output_schedule,
        route_short_names, route_long_names):

    routes_to_copy = []
    for route_name in route_short_names:
        r_id, route = getRouteByShortName(input_schedule, route_name)
        if r_id is None:
            print "Warning:- route with short name '%s' requested to copy not "\
                "found, skipping." % (route_name)
            route_name
        else:
            if r_id in [r[0] for r in routes_to_copy]:
                print "Warning:- you already asked to copy route with "\
                    "short name '%s' (ID '%d')." % route_name
            else:
                routes_to_copy.append((route_name, r_id, route))
    
    for route_name in route_long_names:
        r_id, route = getRouteByLongName(input_schedule, route_name)
        if r_id is None:
            print "Warning:- route with long name '%s' requested to copy not "\
                "found, skipping." % (route_name)
            route_name
        else:
            if r_id in [r[0] for r in routes_to_copy]:
                print "Warning:- you already asked to copy route with "\
                    "long name '%s' (ID '%d')." % route_name
            else:
                routes_to_copy.append((route_name, r_id, route))
    
    for route_name, r_id, route in routes_to_copy:
        print "Now creating entry for route '%s'" % route_name
        assert r_id is not None and route is not None
        route_cpy = copy.copy(route)
        route_cpy._schedule = None
        route_cpy._trips = []
        output_schedule.AddRouteObject(route_cpy)

        trip_dict = route.GetPatternIdTripDict()
        p_keys = [k for k in trip_dict.iterkeys()]

        print "Copying across trips and stop times for %d patterns " \
            "in this route." % len(trip_dict)
        for p_ii, p_key in enumerate(p_keys):
            trips = trip_dict[p_key]
            n_trips = len(trips)
            trip_headsign = trips[0].trip_headsign
            trip_pattern = trips[0].GetPattern()
            n_stops = len(trip_pattern)
            for trip in trips:
                stop_times = trip.GetStopTimes()
                trip_cpy = copy.copy(trip)
                output_schedule.AddTripObject(trip_cpy)
                for stop_time in stop_times:
                    trip_cpy.AddStopTimeObject(stop_time)
    return

# Extracting relevant info from a schedule, and saving to file.

def getStopVisitTimesForTripPatternByServPeriod(trips):
    master_stops = trips[0].GetPattern()
    master_stop_ids = [s.stop_id for s in master_stops]

    stop_visit_times_by_p = {}
    for trip in trips:
        serv_period = trip.service_id
        if serv_period not in stop_visit_times_by_p:
            stop_visit_times_by_p[serv_period] = {}
            for s_id in master_stop_ids:
                stop_visit_times_by_p[serv_period][s_id] = []

    for trip in trips:
        serv_period = trip.service_id
        for stop_time in trip.GetStopTimes():
            s_id = stop_time.stop.stop_id
            stop_visit_times_by_p[serv_period][s_id].append(
                stop_time.arrival_secs)
    # Now sort all the visit times
    for serv_period, stop_visit_times in stop_visit_times_by_p.iteritems():
        for s_id, visit_times in stop_visit_times.iteritems():
            stop_visit_times_by_p[serv_period][s_id] = sorted(visit_times)
    return stop_visit_times_by_p

def getPeriodCountsByStopId(stop_visit_times, periods):
    period_totals = {}
    for s_id, visit_times in stop_visit_times.iteritems():
        period_totals[s_id] = [0] * len(periods)
        curr_period_i = 0
        p0, p1 = periods[0]
        pstart_sec = tdToSecs(p0)
        pend_sec = tdToSecs(p1)
        for v_time_sec in visit_times:
            if v_time_sec >= pstart_sec and v_time_sec <= pend_sec:
                period_totals[s_id][curr_period_i] += 1
            else:
                curr_period_i += 1
                if curr_period_i >= len(periods): 
                    # We've gone through all periods of interest, so any more 
                    # stop times must also be later, so go on to next stop.
                    break
                for period in periods[curr_period_i:]:
                    p0, p1 = period
                    pstart_sec = tdToSecs(p0)
                    pend_sec = tdToSecs(p1)
                    if v_time_sec >= pstart_sec and v_time_sec <= pend_sec:
                        period_totals[s_id][curr_period_i] += 1
                        break
                    curr_period_i += 1    
    return period_totals 

def getPeriodHeadways(period_visit_counts_by_stop_id, periods):
    period_headways = {}
    for s_id, period_visit_counts in \
            period_visit_counts_by_stop_id.iteritems():
        period_headways[s_id] = [-1] * len(periods)
        for p_ii, period in enumerate(periods):
            p_visit_count = period_visit_counts_by_stop_id[s_id][p_ii]
            if p_visit_count > 0:
                p_duration = period[1] - period[0]
                p_duration_mins = tdToSecs(p_duration) / 60.0
                headway = p_duration_mins / float(p_visit_count)
                period_headways[s_id][p_ii] = round(headway,2)
    return period_headways

def calcHeadwaysMinutes(schedule, stop_visit_times, periods):
    period_visit_counts = getPeriodCountsByStopId(stop_visit_times, periods)
    period_headways = getPeriodHeadways(period_visit_counts, periods)
    return period_headways

def build_nominal_stop_orders_by_dir_serv_period(trip_dict, p_keys,
        route_dir_serv_periods):
    all_patterns_nominal_orders = {}
    for dir_period_pair in route_dir_serv_periods:
        all_patterns_nominal_orders[dir_period_pair] = []

    for p_ii, p_key in enumerate(p_keys):
        trips = trip_dict[p_keys[p_ii]]
        for trip in trips:
            trip_dir = trip['trip_headsign']
            trip_serv_period = trip['service_id']
            nominal_order = all_patterns_nominal_orders[\
                (trip_dir,trip_serv_period)]
            s_id_prev = None
            for s_t_i, stop_time in enumerate(trip.GetStopTimes()):
                s_id = stop_time.stop.stop_id
                if s_id not in nominal_order:
                    if s_t_i == 0:
                        nominal_order.insert(0, s_id)
                    elif s_id_prev:
                        try:
                            prev_i = nominal_order.index(s_id_prev)
                            nominal_order.insert(prev_i+1, s_id)
                        except ValueError:
                            nominal_order.append(s_id)
                    else:
                        nominal_order.append(s_id)
                s_id_prev = s_id
    return all_patterns_nominal_orders


def build_stop_visit_times_by_dir_serv_period(trip_dict, p_keys,
        route_dir_serv_periods):
    all_patterns_stop_visit_times = {}
    for dir_period_pair in route_dir_serv_periods:
        all_patterns_stop_visit_times[dir_period_pair] = {}

    for p_ii, p_key in enumerate(p_keys):
        trips = trip_dict[p_keys[p_ii]]
        # Now add relevant info to all stop patterns list.
        # Note:- since this includes different dir, period pairs, need
        #  to do individually.
        for trip in trips:
            trip_dir = trip['trip_headsign']
            trip_serv_period = trip['service_id']
            all_patterns_entry = \
                all_patterns_stop_visit_times[(trip_dir,trip_serv_period)]
            for stop_time in trip.GetStopTimes():
                s_id = stop_time.stop.stop_id
                s_arr_time = stop_time.arrival_secs
                if s_id not in all_patterns_entry:
                    all_patterns_entry[s_id] = [s_arr_time]
                else:
                    all_patterns_entry[s_id].append(s_arr_time)
    # Sort results before returning
    for route_dir, serv_period in route_dir_serv_periods:
            all_patterns_entry = \
                all_patterns_stop_visit_times[(route_dir,serv_period)]
            for s_id in all_patterns_entry.iterkeys():
                all_patterns_entry[s_id].sort()
    return all_patterns_stop_visit_times

def routeDirStringToFileReady(route_dir):
    return route_dir.replace(' ','_').replace('(','').replace(')','')

# TODO: would be good to allow optional argument to provide a seg_geom here, in which
# case this is used to calculate the actual distance along seg geom (rather
# than straight-line distance along surface of the earth)??
def calc_distance(gtfs_stop_a, gtfs_stop_b):
    # Use the Haversine function to get an approx dist along the earth.
    dist_m = lineargeom.haversine(gtfs_stop_a.stop_lon, gtfs_stop_a.stop_lat,
        gtfs_stop_b.stop_lon, gtfs_stop_b.stop_lat)
    return dist_m

def calc_seg_speed_km_h(seg_dist_m, seg_trav_time_s):
    # Handle edge-case of problematic GTFS that does sometimes appear in practice :-
    # two stops having same scheduled stop time.
    # We don't want divide-by-zero errors to occur later when converting back
    # to a travel time :- so set to a default speed. 
    if seg_trav_time_s < 1e-6:
        seg_speed_km_h = DEFAULT_FALLBACK_SEG_SPEED_KM_H
    else:
        seg_speed_km_h = seg_dist_m / float(seg_trav_time_s)
    return seg_speed_km_h

def build_segment_speeds_by_dir_serv_period(trip_dict, p_keys,
        route_dir_serv_periods):
    all_patterns_stop_visit_times = {}
    for dir_period_pair in route_dir_serv_periods:
        all_patterns_stop_visit_times[dir_period_pair] = {}

    # This lookup dict will be used for keeping track of distances between
    #  needed stop pairs (segments) for this route.
    seg_distances = {}
    
    for p_ii, p_key in enumerate(p_keys):
        trips = trip_dict[p_keys[p_ii]]
        # Now add relevant info to all stop patterns list.
        # Note:- since this includes different dir, period pairs, need
        #  to do individually.
        for trip in trips:
            trip_dir = trip['trip_headsign']
            trip_serv_period = trip['service_id']
            all_patterns_entry = \
                all_patterns_stop_visit_times[(trip_dir,trip_serv_period)]
            #import pdb
            #pdb.set_trace()
            for stop_time_pair in pairs(trip.GetStopTimes()):
                s_id_pair = (stop_time_pair[0].stop.stop_id,
                    stop_time_pair[1].stop.stop_id)
                s_arr_time_pair = (stop_time_pair[0].arrival_secs,
                    stop_time_pair[1].arrival_secs)
                try:
                    seg_dist_m = seg_distances[s_id_pair]
                except KeyError:
                    seg_dist_m = calc_distance(stop_time_pair[0].stop,
                        stop_time_pair[1].stop)
                    seg_distances[s_id_pair] = seg_dist_m

                seg_trav_time_s = s_arr_time_pair[1] - s_arr_time_pair[0]
                assert seg_trav_time_s >= (0.0 - 1e-6)
                # use a function here to handle units, special cases (e.g.
                # where dist or time = 0)
                seg_speed_km_h = calc_seg_speed_km_h(seg_dist_m, seg_trav_time_s)
                assert seg_speed_km_h >= 0.0

                seg_speed_tuple = (s_arr_time_pair[0], s_arr_time_pair[1], seg_speed_km_h)
    
                if s_id_pair not in all_patterns_entry:
                    all_patterns_entry[s_id_pair] = [seg_speed_tuple]
                else:
                    all_patterns_entry[s_id_pair].append(seg_speed_tuple)

    # Sort results before returning
    for route_dir, serv_period in route_dir_serv_periods:
            all_patterns_entry = \
                all_patterns_stop_visit_times[(route_dir,serv_period)]
            for stop_id_pair in all_patterns_entry.iterkeys():
                # We want to sort these by arrival time at first stop in pair.
                # Fortunately Python's default sort does it this way.
                all_patterns_entry[stop_id_pair].sort()

    return all_patterns_stop_visit_times

def calc_avg_speeds_during_time_periods(schedule, seg_speeds_dict, time_periods):
    """Note:- assumes and requires that the seg_speeds_dict is already in
    sorted order."""
    speeds_in_periods = {}
    for s_id_pair, seg_speed_tuples in seg_speeds_dict.iteritems():
        speeds_in_periods[s_id_pair] = [[] for ii in range(len(time_periods))]
        curr_period_i = 0
        p_start, p_end = time_periods[0]
        pstart_sec = tdToSecs(p_start)
        pend_sec = tdToSecs(p_end)
        for pt_a_time, pt_b_time, seg_speed_km_h in seg_speed_tuples:
            if pt_a_time >= pstart_sec and pt_a_time <= pend_sec:
                speeds_in_periods[s_id_pair][curr_period_i].append(seg_speed_km_h)
            else:
                curr_period_i += 1
                if curr_period_i >= len(time_periods):
                    # We've gone through all periods of interest :- go 
                    #  on to next segment.
                    break
                for time_period in time_periods[curr_period_i:]:
                    p_start, p_end = time_period
                    pstart_sec = tdToSecs(p_start)
                    pend_sec = tdToSecs(p_end)
                    if pt_a_time >= pstart_sec and pt_a_time <= pend_sec:
                        speeds_in_periods[s_id_pair][curr_period_i].append(\
                            seg_speed_km_h)
                        break
                    curr_period_i += 1

    avg_speeds = {}
    speed_min_maxes = {}
    for s_id_pair in seg_speeds_dict.iterkeys():
        avg_speeds[s_id_pair] = []
        speed_min_maxes[s_id_pair] = []
        for period_i in range(len(time_periods)):
            s_in_p = speeds_in_periods[s_id_pair][period_i]
            if len(s_in_p) == 0:
                avg_speeds[s_id_pair].append(-1)
                speed_min_maxes[s_id_pair].append(None)
            else:
                avg_speed_in_p = sum(s_in_p) / float(len(s_in_p))
                avg_speeds[s_id_pair].append(avg_speed_in_p)
                speed_min_maxes[s_id_pair].append(
                    (min(s_in_p), max(s_in_p)))
    return avg_speeds

def extract_route_dir_serv_period_tuples(trip_patterns_dict):
    # Handle these as tuples, since we want to make sure we only consider
    #  service period, direction pairs that actually exist.
    route_dir_serv_periods = [] 
    for trips in trip_patterns_dict.itervalues():
        for trip in trips:
            trip_dir = trip['trip_headsign']
            trip_serv_period = trip['service_id']
            dir_period_pair = (trip_dir, trip_serv_period)
            if dir_period_pair not in route_dir_serv_periods:
                route_dir_serv_periods.append(dir_period_pair)
    return route_dir_serv_periods

def print_trip_start_times_for_patterns(trip_patterns_dict):   
    for p_ii, p_key in enumerate(trip_patterns_dict.keys()):
        trips = trip_patterns_dict[p_key]
        n_trips = len(trips)
        trips_headsign = trips[0].trip_headsign
        trip_pattern = trips[0].GetPattern()
        n_stops = len(trip_pattern)
        for trip in trips:
            assert trip.trip_headsign == trips_headsign
            assert len(trip.GetPattern()) == n_stops
        trip_start_times = [t.GetStartTime() for t in trips]
        print "P %d: %d trips, to '%s', with %d stops." % \
            (p_ii, n_trips, trips_headsign, n_stops)
        sorted_start_times = sorted(trip_start_times)
        sorted_start_time_of_days = [toTimeOfDay(t) for t in \
            sorted_start_times]
        print "\t(Sorted) start times are %s" % \
            (' ,'.join(map(str, sorted_start_time_of_days)))
    return

def get_time_period_name_strings(periods):
    period_names = []
    for p0, p1 in periods:
        p0t = tdToTimeOfDay(p0)
        p1t = tdToTimeOfDay(p1)
        pname = "%s-%s" % (p0t.strftime('%H_%M'), p1t.strftime('%H_%M'))
        period_names.append(pname)
    return period_names

def writeHeadwaysMinutes(schedule, period_headways, periods, csv_fname,
        stop_id_order=None):

    csv_file = open(csv_fname, 'w')
    writer = csv.writer(csv_file, delimiter=';')

    period_names = get_time_period_name_strings(periods)
    writer.writerow(['Stop_id','Stop_name',] + period_names)

    if stop_id_order is None:
        s_ids = period_headways.keys()
    else:
        s_ids = stop_id_order
    for s_id in s_ids:
        period_headways_at_stop = period_headways[s_id]
        writer.writerow([s_id, schedule.stops[s_id].stop_name] \
            + period_headways_at_stop)
    csv_file.close()
    return

def writeAvgSpeedsOnSegments(schedule, period_avg_speeds, periods, csv_fname):
    csv_file = open(csv_fname, 'w')
    writer = csv.writer(csv_file, delimiter=';')

    period_names = get_time_period_name_strings(periods)
    writer.writerow(['Stop_a_id','Stop_a_name','Stop_b_id','Stop_b_name']\
        + period_names)

    s_id_pairs = period_avg_speeds.keys()
    for s_id_pair in s_id_pairs:
        avg_speeds_on_seg = period_avg_speeds[s_id_pair]
        writer.writerow(
            [s_id_pair[0], schedule.stops[s_id_pair[0]].stop_name, \
            s_id_pair[1], schedule.stops[s_id_pair[1]].stop_name] \
            + avg_speeds_on_seg)
    csv_file.close()
    return

def extract_route_speed_info_by_time_periods(schedule, route_name,
        time_periods, output_path):
    """Note: See doc for function extract_route_freq_info_by_time_periods()
    for explanation of time_periods argument format."""
    if not os.path.exists(output_path):
        os.makedirs(output_path)

    r_id, r_info = getRouteByLongName(schedule, route_name)
    trip_dict = r_info.GetPatternIdTripDict()
    p_keys = trip_dict.keys()

    route_dir_serv_periods = extract_route_dir_serv_period_tuples(trip_dict)

    all_patterns_segment_speed_infos = build_segment_speeds_by_dir_serv_period(
        trip_dict, p_keys, route_dir_serv_periods)

    route_avg_speeds_during_time_periods = {}
    for dir_period_pair in route_dir_serv_periods:
        route_avg_speeds_during_time_periods[dir_period_pair] = {}

    for dir_period_pair in route_dir_serv_periods:
            all_patterns_entry = \
                all_patterns_segment_speed_infos[dir_period_pair]
            avg_speeds = calc_avg_speeds_during_time_periods(schedule,
                all_patterns_entry, time_periods)
            route_avg_speeds_during_time_periods[dir_period_pair] = avg_speeds

    # write to relevant files.
    for route_dir, serv_period in route_dir_serv_periods:
            avg_speeds = route_avg_speeds_during_time_periods[\
                (route_dir, serv_period)]
            fname_all = "%s-speeds-%s-%s-all.csv" % \
                (route_name, serv_period, \
                routeDirStringToFileReady(route_dir))
            fpath = os.path.join(output_path, fname_all)
            writeAvgSpeedsOnSegments(schedule, avg_speeds,
                time_periods, fpath)
    return

def extract_route_freq_info_by_time_periods(schedule, route_name,
        time_periods, output_path):
    """Note: time_periods argument of the form of a list of tuples.
    Each tuple is a pair of Python timedelta objects. First of these
    represents "time past midnight of service day that period of interest
    starts. Latter is time that the period of interest ends.
    Periods need to be sequential, and shouldn't overlap."""
    if not os.path.exists(output_path):
        os.makedirs(output_path)

    r_id, r_info = getRouteByLongName(schedule, route_name)
    trip_dict = r_info.GetPatternIdTripDict()
    p_keys = trip_dict.keys()

    print "Printing basic info for the %d trip patterns in this route." % \
        len(trip_dict)

    print_trip_start_times_for_patterns(trip_dict)
    
    route_dir_serv_periods = extract_route_dir_serv_period_tuples(trip_dict)

    for p_ii, p_key in enumerate(p_keys):
        trips = trip_dict[p_keys[p_ii]]
        trips_dir = trips[0]['trip_headsign']
        for trip in trips[1:]:
            assert trip['trip_headsign'] == trips_dir
        stop_visit_times_by_p = getStopVisitTimesForTripPatternByServPeriod(
            trips)
        master_stops = trips[0].GetPattern()
        master_stop_ids = [s.stop_id for s in master_stops]
        for serv_period, stop_visit_times in stop_visit_times_by_p.iteritems(): 
            period_headways = calcHeadwaysMinutes(schedule, stop_visit_times, time_periods)
            fname = "%s-hways-p%d-%s-%s.csv" % \
                (route_name, p_ii, routeDirStringToFileReady(trips_dir),
                    serv_period)
            fpath = os.path.join(output_path, fname)
            writeHeadwaysMinutes(schedule, period_headways, time_periods,
                fpath, stop_id_order=master_stop_ids)

    all_patterns_nominal_orders = build_nominal_stop_orders_by_dir_serv_period(
        trip_dict, p_keys, route_dir_serv_periods)
    all_patterns_stop_visit_times = build_stop_visit_times_by_dir_serv_period(
        trip_dict, p_keys, route_dir_serv_periods)

    # TODO: - good to create an intermediate step here where I save the
    # headways to a Pythonic data structure, rather than direct to CSV.
    # Finally print to file relevant info.
    for route_dir, serv_period in route_dir_serv_periods:
            all_patterns_entry = \
                all_patterns_stop_visit_times[(route_dir,serv_period)]
            period_headways = calcHeadwaysMinutes(schedule,
                all_patterns_stop_visit_times[(route_dir, serv_period)],
                time_periods)
            stop_write_order = all_patterns_nominal_orders[\
                (route_dir,serv_period)]
            fname_all = "%s-hways-%s-%s-all.csv" % \
                (route_name, serv_period, \
                routeDirStringToFileReady(route_dir))
            fpath = os.path.join(output_path, fname_all)
            writeHeadwaysMinutes(schedule, period_headways,
                time_periods, fpath, stop_id_order=stop_write_order)
    return

