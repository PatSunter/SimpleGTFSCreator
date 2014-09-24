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

SEC_PER_DAY = 86400

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

def getRouteByLongName(schedule, long_name):
    for r_id, route in schedule.routes.iteritems():
        if route.route_long_name == long_name:
            return r_id, route
    return None, None        

# Tools for manipulating a schedule, and/or adding to a new schedule.

def copy_selected_routes(input_schedule, output_schedule, route_names):
    for route_name in route_names:
        print "Now creating entry for route '%s'" % route_name
        r_id, route = getRouteByLongName(input_schedule, route_name)
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

def writeHeadwaysMinutes(schedule, stop_visit_times, periods, csv_fname,
        stop_id_order=None):
    period_visit_counts = getPeriodCountsByStopId(stop_visit_times, periods)
    period_headways = getPeriodHeadways(period_visit_counts, periods)

    csv_file = open(csv_fname, 'w')
    writer = csv.writer(csv_file, delimiter=';')
    period_names = []
    for p0, p1 in periods:
        p0t = tdToTimeOfDay(p0)
        p1t = tdToTimeOfDay(p1)
        pname = "%s-%s" % (p0t.strftime('%H_%M'), p1t.strftime('%H_%M'))
        period_names.append(pname)

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

def extract_route_speed_freq_info_by_time_periods(schedule, route_name,
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
    p_keys = [k for k in trip_dict.iterkeys()]

    print "Printing basic info for the %d trip patterns in this route." % \
        len(trip_dict)

    for p_ii, p_key in enumerate(p_keys):
        trips = trip_dict[p_key]
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

    # Handle these as tuples, since we want to make sure we only consider
    #  service period, direction pairs that actually exist.
    route_dir_serv_periods = [] 
    for p_key in p_keys:
        trips = trip_dict[p_key]
        for trip in trips:
            trip_dir = trip['trip_headsign']
            trip_serv_period = trip['service_id']
            dir_period_pair = (trip_dir, trip_serv_period)
            if dir_period_pair not in route_dir_serv_periods:
                route_dir_serv_periods.append(dir_period_pair)

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
            fname = "%s-hways-p%d-%s-%s.csv" % \
                (route_name, p_ii, routeDirStringToFileReady(trips_dir),
                    serv_period)
            fpath = os.path.join(output_path, fname)
            writeHeadwaysMinutes(schedule, stop_visit_times, time_periods,
                fpath, stop_id_order=master_stop_ids)

    all_patterns_nominal_orders = build_nominal_stop_orders_by_dir_serv_period(
        trip_dict, p_keys, route_dir_serv_periods)
    all_patterns_stop_visit_times = build_stop_visit_times_by_dir_serv_period(
        trip_dict, p_keys, route_dir_serv_periods)

    # Finally print to file relevant info.
    for route_dir, serv_period in route_dir_serv_periods:
            all_patterns_entry = \
                all_patterns_stop_visit_times[(route_dir,serv_period)]
            nominal_order = all_patterns_nominal_orders[\
                (route_dir,serv_period)]
            fname_all = "%s-hways-%s-%s-all.csv" % \
                (route_name, serv_period, \
                routeDirStringToFileReady(route_dir))
            fpath = os.path.join(output_path, fname_all)
            writeHeadwaysMinutes(schedule,
                all_patterns_stop_visit_times[(route_dir, serv_period)],
                time_periods, fpath, stop_id_order=nominal_order)
    return

