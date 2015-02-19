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
import math

import transitfeed
from osgeo import ogr, osr

import misc_utils
import lineargeom
import time_periods_speeds_model as tps_speeds_model
import time_periods_hways_model as tps_hways_model

DEFAULT_FALLBACK_SEG_SPEED_KM_H = 10.0

ALLOWED_ROUTE_NAME_TYPES = ['route_short_name', 'route_long_name']

GTFS_EPSG = 4326

# GTFS time utils

def secsInPeriodToTimeOfDay(secs_since_midnight):
    """Convert an input number of 'seconds since midnight of the current
    service day' to a Python time object.
    NOTE:- if """
    td = timedelta(seconds=secs_since_midnight)
    return misc_utils.tdToTimeOfDay(td)

# Utility printing functions

def get_gtfs_route_print_name(gtfs_route):
    pname = misc_utils.get_route_print_name(gtfs_route.route_short_name,
        gtfs_route.route_long_name)
    return pname

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

def getStopWithName(schedule, stop_name):
    for s_id, stop in schedule.stops.iteritems():
        if stop.stop_name == stop_name:
            return s_id, stop
    return None, None            

#####################################################################
# Tools for manipulating a schedule, and/or adding to a new schedule.

def create_base_schedule_copy(input_schedule):
    """Create a new schedule based on existing, with all the agencies,
    periods, etc."""
    output_schedule = transitfeed.Schedule(memory_db=False)
    print "Copying file basics to new schedule."
    for agency in input_schedule._agencies.itervalues():
        ag_cpy = copy.copy(agency)
        ag_cpy._schedule = None
        output_schedule.AddAgencyObject(ag_cpy)
    for serv_period in input_schedule.service_periods.itervalues():
        serv_period_cpy = copy.copy(serv_period)
        output_schedule.AddServicePeriodObject(serv_period_cpy)
    return output_schedule

def copy_selected_routes(input_schedule, output_schedule,
        gtfs_routes_to_copy_ids):
    routes_to_copy = []
    # Do the below in case the func was passed a Python Set of routes
    # instead of list.
    # (Don't assume set though since the user may want to copy in a 
    #  certain order for output purposes.)
    gtfs_routes_to_copy_ids_list = list(gtfs_routes_to_copy_ids)
    for id_i, gtfs_route_id in enumerate(gtfs_routes_to_copy_ids_list):
        if len(gtfs_routes_to_copy_ids_list) > 1 and \
                gtfs_route_id in gtfs_routes_to_copy_ids_list[id_i+1:]:
            print "Warning:- route with id %d requested to copy is "\
                "contained multiple times in list to copy: skipping."\
                "this instance." % (gtfs_route_id)
            continue    
        try:
            gtfs_route = input_schedule.routes[gtfs_route_id]
        except KeyError:    
            print "Warning:- route with id %d requested to copy not "\
                "found, skipping." % (gtfs_route_id)
            continue
        route_name = get_gtfs_route_print_name(gtfs_route)
        print "Now creating entry for route id %s, name '%s'" \
            % (gtfs_route_id, route_name)
        route_cpy = copy.copy(gtfs_route)
        route_cpy._schedule = None
        # PDS: (Following is a little bit hacky and is transitfeed library
        # implementation-dependent. But is simplest way that works I was
        # able to find via reading API docs and experiment.)
        route_cpy._trips = []
        output_schedule.AddRouteObject(route_cpy)

        trip_dict = gtfs_route.GetPatternIdTripDict()
        print "Copying across trips and stop times for %d patterns " \
            "in this route." % len(trip_dict)
        for trips in trip_dict.itervalues():
            for trip in trips:
                stop_times = trip.GetStopTimes()
                trip_cpy = copy.copy(trip)
                output_schedule.AddTripObject(trip_cpy)
                for stop_time in stop_times:
                    trip_cpy.AddStopTimeObject(stop_time)
    return

def copy_stops_with_ids(input_schedule, output_schedule, stop_ids):
    """Copy the stops with given ids from input to output GTFS schedule."""
    for stop_id in stop_ids:
        stop = input_schedule.stops[stop_id]
        stop_cpy = copy.copy(stop)
        stop_cpy._schedule = None
        output_schedule.AddStopObject(stop_cpy)
    return

##################################
# Selecting by geometry operations

def get_route_ids_within_polygons(schedule, route_ids_to_check,
        within_polygons_lyr):
    """Returns a list of all route IDs within the selected polygons."""

    partially_within_route_ids = []
    # Transform the polygon geoms into same SRS as the GTFS stop for testing
    tformed_poly_geoms = []
    src_srs = within_polygons_lyr.GetSpatialRef()
    gtfs_srs = osr.SpatialReference()
    gtfs_srs.ImportFromEPSG(GTFS_EPSG)
    transform = osr.CoordinateTransformation(src_srs, gtfs_srs)
    for poly in within_polygons_lyr:
        poly_geom = poly.GetGeometryRef()
        poly_geom2 = poly_geom.Clone()
        poly_geom2.Transform(transform)
        tformed_poly_geoms.append(poly_geom2)

    for route_id in route_ids_to_check:
        route_within_a_poly = False
        gtfs_route = schedule.routes[route_id]
        #print "Checking if any stops from route %d (%s) fall within "\
        #    "polygons ..." % (int(route_id), get_print_name(gtfs_route))
        for poly_geom in tformed_poly_geoms:
            all_route_stop_ids = get_all_stop_ids_used_by_route(gtfs_route,
                schedule)
            for stop_id in all_route_stop_ids:
                gtfs_stop = schedule.stops[stop_id]
                stop_pt = ogr.Geometry(ogr.wkbPoint)
                stop_pt.AddPoint(gtfs_stop.stop_lon, gtfs_stop.stop_lat)
                if poly_geom.Contains(stop_pt):
                    partially_within_route_ids.append(route_id)
                    route_within_a_poly = True
                    break
                stop_pt.Destroy()    
            if route_within_a_poly:
                break
    return partially_within_route_ids

##########################################
# Extracting relevant info from a schedule

def get_all_stop_ids_used_by_route(schedule, route_id):
    """Returns a set (not list) of all stops visited as part of a route,
    for all trips."""
    stop_ids_all_trips = set([])
    gtfs_route = schedule.routes[route_id]
    trip_dict = gtfs_route.GetPatternIdTripDict()
    for trips in trip_dict.values():
        stop_pattern = trips[0].GetPattern()
        stop_ids_in_trip = map(lambda x: x.stop_id, stop_pattern)
        stop_ids_all_trips = stop_ids_all_trips.union(set(stop_ids_in_trip))
    return stop_ids_all_trips

def get_stop_ids_set_used_by_selected_routes(schedule, gtfs_route_ids):
    stop_ids_used_by_routes = set([])
    for r_id in gtfs_route_ids:
        stop_ids_in_route = get_all_stop_ids_used_by_route(schedule,
            r_id)
        stop_ids_used_by_routes = stop_ids_used_by_routes.union(
            stop_ids_in_route)
    return stop_ids_used_by_routes

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
        pstart_sec = misc_utils.tdToSecs(p0)
        pend_sec = misc_utils.tdToSecs(p1)
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
                    pstart_sec = misc_utils.tdToSecs(p0)
                    pend_sec = misc_utils.tdToSecs(p1)
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
                p_duration_mins = misc_utils.tdToSecs(p_duration) / 60.0
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

# TODO: would be good to allow optional argument to provide a seg_geom here,
# in which
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
        seg_speed_km_h = (seg_dist_m / 1000.0) / \
            float(seg_trav_time_s / float(misc_utils.SECS_PER_HOUR))
    return seg_speed_km_h

def get_update_seg_dist_m(seg_distances, stop_pair):
    s_id_pair = (stop_pair[0].stop_id,
        stop_pair[1].stop_id)
    try:
        seg_dist_m = seg_distances[s_id_pair]
    except KeyError:
        seg_dist_m = calc_distance(stop_pair[0],
            stop_pair[1])
        seg_distances[s_id_pair] = seg_dist_m
    return seg_dist_m

def calc_speed_on_segment_with_nearby_segs(trip_stop_time_pairs,
        stop_time_pair, stop_pair_i, seg_distances, min_dist_for_speed_calc_m,
        min_time_for_speed_calc_s):
    s_id_pair = (stop_time_pair[0].stop.stop_id,
        stop_time_pair[1].stop.stop_id)
    s_arr_time_pair = (stop_time_pair[0].arrival_secs,
        stop_time_pair[1].arrival_secs)
    stop_pair = (stop_time_pair[0].stop, stop_time_pair[1].stop)
    seg_dist_m = get_update_seg_dist_m(seg_distances, stop_pair)
    seg_trav_time_s = s_arr_time_pair[1] - s_arr_time_pair[0]
    assert seg_trav_time_s >= (0.0 - 1e-6)

    #print "In speed smoothing func:- initial seg is %d, dist %.1fm,"\
    #    " time %.1f sec." % (stop_pair_i, seg_dist_m, seg_trav_time_s)

    # Now, we have to keep adding segment speeds and times, till we reach
    #  the min dist to calculate speed over.
    speed_calc_total_dist_m = seg_dist_m
    speed_calc_total_time_s = seg_trav_time_s
    init_seg_i = stop_pair_i
    move_magnitude = 1
    go_forward_next = True
    prev_at_trip_start = False
    next_at_trip_end = False

    while (speed_calc_total_dist_m < min_dist_for_speed_calc_m \
            or speed_calc_total_time_s < min_time_for_speed_calc_s) \
            and not (prev_at_trip_start and next_at_trip_end):
        if go_forward_next:
            seg_i_to_add = init_seg_i + move_magnitude
            if seg_i_to_add >= len(trip_stop_time_pairs):
                next_at_trip_end = True
                go_forward_next = False
                continue
        else:
            seg_i_to_add = init_seg_i - move_magnitude
            if seg_i_to_add < 0:
                prev_at_trip_start = True
                go_forward_next = True
                move_magnitude += 1
                continue

        #print "...adding time and dist for seg %d..." % seg_i_to_add
        stop_time_pair = trip_stop_time_pairs[seg_i_to_add]
        new_s_id_pair = (stop_time_pair[0].stop.stop_id, \
            stop_time_pair[1].stop.stop_id)

        stop_pair = (stop_time_pair[0].stop, stop_time_pair[1].stop)
        new_seg_dist_m = get_update_seg_dist_m(seg_distances, stop_pair)
        assert new_seg_dist_m >= (0.0 - 1e-6)
        speed_calc_total_dist_m += new_seg_dist_m

        new_seg_trav_time_s = stop_time_pair[1].arrival_secs - \
            stop_time_pair[0].arrival_secs 
        assert new_seg_trav_time_s >= (0.0 - 1e-6)
        speed_calc_total_time_s += new_seg_trav_time_s 

        # This handles the 'moving window' of adding segments to total,
        #  alternating between forwards and backwards.
        go_forward_next = not go_forward_next
        if go_forward_next:
            move_magnitude += 1
        
    #print "...for speed calc, total dist is %.1f m, total time %.1f s" % \
    #    (speed_calc_total_dist_m, speed_calc_total_time_s)
    # use a function here to handle units, special cases (e.g.
    # where dist or time = 0)
    smoothed_seg_speed_km_h = calc_seg_speed_km_h(speed_calc_total_dist_m,
        speed_calc_total_time_s)
    #print "...thus speed calculated as %.2f km/h" % \
    #    (smoothed_seg_speed_km_h)
    return smoothed_seg_speed_km_h

def build_segment_speeds_by_dir_serv_period(trip_dict, p_keys,
        route_dir_serv_periods, min_dist_for_speed_calc_m,
        min_time_for_speed_calc_s):
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
            trip_stop_time_pairs = list(misc_utils.pairs(trip.GetStopTimes()))
            for seg_i, stop_time_pair in enumerate(trip_stop_time_pairs):
                s_id_pair = (stop_time_pair[0].stop.stop_id,
                    stop_time_pair[1].stop.stop_id)
                stop_pair = (stop_time_pair[0].stop, stop_time_pair[1].stop)
                s_arr_time_pair = (stop_time_pair[0].arrival_secs,
                    stop_time_pair[1].arrival_secs)
                seg_dist_m = get_update_seg_dist_m(seg_distances,
                    stop_pair)

                # We need to calculate a 'smoothed' travel time and thus
                # speed, over several segments :- since for many GTFS feeds,
                # stop times are rounded to the minute.
                seg_speed_km_h = calc_speed_on_segment_with_nearby_segs(
                    trip_stop_time_pairs, stop_time_pair, seg_i,
                    seg_distances, min_dist_for_speed_calc_m, 
                    min_time_for_speed_calc_s)

                assert seg_speed_km_h >= 0.0
                seg_speed_tuple = (s_arr_time_pair[0], s_arr_time_pair[1],
                    seg_speed_km_h)
    
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

    return all_patterns_stop_visit_times, seg_distances

def build_trav_times_by_dir_serv_period_between_selected_stops(trip_dict, p_keys,
        route_dir_serv_periods, min_dist_for_speed_calc_m,
        min_time_for_speed_calc_s, selected_stop_ids):
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
            #trip_stop_time_pairs = list(misc_utils.pairs(trip.GetStopTimes()))
            #for seg_i, stop_time_pair in enumerate(trip_stop_time_pairs):
            prev_sel_stop_id = None
            prev_sel_stop_time = None
            for stop_i, stop_time_tuple in enumerate(trip.GetStopTimes()):
                stop_id = stop_time_tuple.stop.stop_id
                if stop_id not in selected_stop_ids:
                    continue
                else:
                    if prev_sel_stop_id:
                        # We can save this pair's speed.
                        curr_stop_time = stop_time_tuple.arrival_secs  
                        trav_time_between_stops = \
                            (curr_stop_time - prev_sel_stop_time) / 60.0
                        s_id_pair = (prev_sel_stop_id, stop_id)
                        seg_ttime_tuple = (prev_sel_stop_time, \
                            curr_stop_time, trav_time_between_stops)
                        if s_id_pair not in all_patterns_entry:
                            all_patterns_entry[s_id_pair] = [seg_ttime_tuple]
                        else:
                            all_patterns_entry[s_id_pair].append(seg_ttime_tuple)
                    prev_sel_stop_time = stop_time_tuple.arrival_secs
                    prev_sel_stop_id = stop_id

    # Sort results before returning
    for route_dir, serv_period in route_dir_serv_periods:
            all_patterns_entry = \
                all_patterns_stop_visit_times[(route_dir,serv_period)]
            for stop_id_pair in all_patterns_entry.iterkeys():
                # We want to sort these by arrival time at first stop in pair.
                # Fortunately Python's default sort does it this way.
                all_patterns_entry[stop_id_pair].sort()

    return all_patterns_stop_visit_times, seg_distances

def calc_avg_segment_property_during_time_periods(schedule, seg_properties_dict,
        time_periods, sort_seg_stop_id_pairs=False):
    """Calculates the average of multiple values for each segment (stop ID
    pair), grouping into time periods. The 'property' could be e.g. speed, or
    travel time.
    Note:- assumes and requires that the seg_properties_dict is already in
    sorted order."""
    
    properties_in_periods = {}
    for s_id_pair, seg_property_tuples in seg_properties_dict.iteritems():
        if sort_seg_stop_id_pairs:
            out_s_id_pair = tuple(sorted(s_id_pair))
        else:
            out_s_id_pair = s_id_pair
        properties_in_periods[out_s_id_pair] = \
            [[] for dummy in xrange(len(time_periods))]
        curr_period_i = 0
        p_start, p_end = time_periods[0]
        pstart_sec = misc_utils.tdToSecs(p_start)
        pend_sec = misc_utils.tdToSecs(p_end)
        for pt_a_time, pt_b_time, seg_property in seg_property_tuples:
            if pt_a_time < pstart_sec:
                # This travel time pair is before any of the time periods of interest.
                # So skip to next occurence of the day.
                continue
            if pt_a_time >= pstart_sec and pt_a_time <= pend_sec:
                times_in_period = \
                    properties_in_periods[out_s_id_pair][curr_period_i]
                times_in_period.append(seg_property)
            else:
                curr_period_i += 1
                if curr_period_i >= len(time_periods):
                    # We've gone through all periods of interest :- go 
                    #  on to next segment.
                    break
                for time_period in time_periods[curr_period_i:]:
                    p_start, p_end = time_period
                    pstart_sec = misc_utils.tdToSecs(p_start)
                    pend_sec = misc_utils.tdToSecs(p_end)
                    if pt_a_time >= pstart_sec and pt_a_time <= pend_sec:
                        times_in_period = \
                            properties_in_periods[out_s_id_pair][curr_period_i]
                        times_in_period.append(seg_property)
                        break
                    curr_period_i += 1
    avg_properties = {}
    property_min_maxes = {}
    for s_id_pair in seg_properties_dict.iterkeys():
        if sort_seg_stop_id_pairs:
            out_s_id_pair = tuple(sorted(s_id_pair))
        else:
            out_s_id_pair = s_id_pair
        avg_properties[out_s_id_pair] = []
        property_min_maxes[out_s_id_pair] = []
        for period_i in range(len(time_periods)):
            s_in_p = properties_in_periods[out_s_id_pair][period_i]
            if len(s_in_p) == 0:
                avg_properties[out_s_id_pair].append(-1)
                property_min_maxes[out_s_id_pair].append(None)
            else:
                avg_property_in_p = sum(s_in_p) / float(len(s_in_p))
                avg_properties[out_s_id_pair].append(avg_property_in_p)
                property_min_maxes[out_s_id_pair].append(
                    (min(s_in_p), max(s_in_p)))
    return avg_properties

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
        sorted_start_time_of_days = [secsInPeriodToTimeOfDay(t) for t in \
            sorted_start_times]
        print "\t(Sorted) start times are %s" % \
            (' ,'.join(map(str, sorted_start_time_of_days)))
    return

def extract_route_speed_info_by_time_periods(schedule, gtfs_route_id,
        time_periods, 
        min_dist_for_speed_calc_m=0,
        min_time_for_speed_calc_s=60,
        sort_seg_stop_id_pairs=False):
    """Note: See doc for function extract_route_freq_info_by_time_periods()
    for explanation of time_periods argument format."""
    gtfs_route = schedule.routes[gtfs_route_id]
    trip_dict = gtfs_route.GetPatternIdTripDict()
    p_keys = trip_dict.keys()

    route_dir_serv_periods = extract_route_dir_serv_period_tuples(trip_dict)

    all_patterns_segment_speed_infos, seg_distances = \
        build_segment_speeds_by_dir_serv_period(trip_dict, p_keys,
        route_dir_serv_periods, min_dist_for_speed_calc_m,
        min_time_for_speed_calc_s)

    route_avg_speeds_during_time_periods = {}
    for dir_period_pair in route_dir_serv_periods:
        route_avg_speeds_during_time_periods[dir_period_pair] = {}

    for dir_period_pair in route_dir_serv_periods:
            all_patterns_entry = \
                all_patterns_segment_speed_infos[dir_period_pair]
            avg_speeds = calc_avg_segment_property_during_time_periods(schedule,
                all_patterns_entry, time_periods, sort_seg_stop_id_pairs)
            route_avg_speeds_during_time_periods[dir_period_pair] = avg_speeds
    return route_avg_speeds_during_time_periods, seg_distances

def extract_route_trav_time_info_by_time_periods_between_selected_stops(schedule,
        gtfs_route_id,
        time_periods, 
        stop_ids_of_interest,
        min_dist_for_speed_calc_m=0,
        min_time_for_speed_calc_s=60,
        sort_seg_stop_id_pairs=False,
        combine_dirs=False):
    """Note: See doc for function extract_route_freq_info_by_time_periods()
    for explanation of time_periods argument format."""

    if combine_dirs:
        if not sort_seg_stop_id_pairs:
            print "Warning: over-riding sort_seg_stop_id_pairs to be True"\
                " since combine_dirs also True, and sorting seg stop ID pairs"\
                " necessary in this case."
        sort_seg_stop_id_pairs = True

    gtfs_route = schedule.routes[str(gtfs_route_id)]
    trip_dict = gtfs_route.GetPatternIdTripDict()
    p_keys = trip_dict.keys()

    route_dir_serv_periods = extract_route_dir_serv_period_tuples(trip_dict)

    all_patterns_segment_trav_time_infos, seg_distances = \
        build_trav_times_by_dir_serv_period_between_selected_stops(trip_dict, p_keys,
            route_dir_serv_periods, min_dist_for_speed_calc_m,
            min_time_for_speed_calc_s, stop_ids_of_interest)

    route_avg_trav_times_during_time_periods = {}
    if not combine_dirs:
        for dir_period_pair in route_dir_serv_periods:
            all_patterns_entry = \
                all_patterns_segment_trav_time_infos[dir_period_pair]
            avg_trav_times = calc_avg_segment_property_during_time_periods(schedule,
                all_patterns_entry, time_periods, sort_seg_stop_id_pairs)
            route_avg_trav_times_during_time_periods[dir_period_pair] = \
                avg_trav_times
    else:
        route_serv_periods = list(set(map(operator.itemgetter(1),
            route_dir_serv_periods)))

        for serv_period in route_serv_periods:
            trav_time_infos = []
            all_patterns_entries = []
            for dir_period_pair in route_dir_serv_periods:
                if dir_period_pair[1] == serv_period:
                    all_patterns_entries.append(
                        all_patterns_segment_trav_time_infos[dir_period_pair])
            # Now we need to combine these entries for multiple dirs
            combined_entries = {}
            for pattern_entries in all_patterns_entries:
                for stop_id_pair, stop_trav_times in \
                        pattern_entries.iteritems():
                    sorted_id_pair = tuple(sorted(stop_id_pair))
                    if sorted_id_pair not in combined_entries:
                        combined_entries[sorted_id_pair] = stop_trav_times
                    else:    
                        combined_entries[sorted_id_pair] += stop_trav_times
            # We need to sort the times internally here.
            for sorted_id_pair, stop_trav_times in \
                    combined_entries.iteritems():
                combined_entries[sorted_id_pair] = sorted(stop_trav_times)
            avg_trav_times = calc_avg_segment_property_during_time_periods(schedule,
                combined_entries, time_periods, sort_seg_stop_id_pairs)
            route_avg_trav_times_during_time_periods[("all_dirs", serv_period)] = \
                avg_trav_times

    return route_avg_trav_times_during_time_periods, seg_distances

def extract_route_freq_info_by_time_periods_by_pattern(schedule,
        gtfs_route_id, time_periods):

    gtfs_route = schedule.routes[gtfs_route_id]
    trip_dict = gtfs_route.GetPatternIdTripDict()
    p_keys = trip_dict.keys()

    print "Printing basic info for the %d trip patterns in this route." % \
        len(trip_dict)
    print_trip_start_times_for_patterns(trip_dict)
    
    route_dir_serv_periods = extract_route_dir_serv_period_tuples(trip_dict)

    route_hways_by_pattern = []
    route_stop_orders_by_pattern = []
    for p_ii, p_key in enumerate(p_keys):
        trips = trip_dict[p_keys[p_ii]]
        trips_dir = trips[0]['trip_headsign']
        for trip in trips[1:]:
            assert trip['trip_headsign'] == trips_dir
        stop_visit_times_by_p = getStopVisitTimesForTripPatternByServPeriod(
            trips)
        stops_order = trips[0].GetPattern()
        stop_ids_order = [s.stop_id for s in stops_order]
        route_stop_orders_by_pattern.append(stop_ids_order)
        period_headways_by_dir_period_pair = {}
        for serv_period, stop_visit_times in stop_visit_times_by_p.iteritems(): 
            period_headways = calcHeadwaysMinutes(schedule, stop_visit_times,
                time_periods)
            period_headways_by_dir_period_pair[(trips_dir, serv_period)] = \
                period_headways
        route_hways_by_pattern.append(period_headways_by_dir_period_pair)

    return route_hways_by_pattern, route_stop_orders_by_pattern

def extract_route_freq_info_by_time_periods_all_patterns(schedule,
        gtfs_route_id, time_periods):
    """Note: time_periods argument of the form of a list of tuples.
    Each tuple is a pair of Python timedelta objects. First of these
    represents "time past midnight of service day that period of interest
    starts. Latter is time that the period of interest ends.
    Periods need to be sequential, and shouldn't overlap."""

    gtfs_route = schedule.routes[gtfs_route_id]
    trip_dict = gtfs_route.GetPatternIdTripDict()
    p_keys = trip_dict.keys()
    route_dir_serv_periods = extract_route_dir_serv_period_tuples(trip_dict)

    all_patterns_stop_order = build_nominal_stop_orders_by_dir_serv_period(
        trip_dict, p_keys, route_dir_serv_periods)
    all_patterns_stop_visit_times = build_stop_visit_times_by_dir_serv_period(
        trip_dict, p_keys, route_dir_serv_periods)

    route_hways_all_patterns = {}
    for dir_period_pair in route_dir_serv_periods:
            all_patterns_entry = \
                all_patterns_stop_visit_times[dir_period_pair]
            headways = calcHeadwaysMinutes(schedule,
                all_patterns_stop_visit_times[dir_period_pair],
                time_periods)
            route_hways_all_patterns[dir_period_pair] = headways    

    return route_hways_all_patterns, all_patterns_stop_order

#########################################################
# I/O of speed and frequency information by time periods

def extract_stop_ids_from_pairs(stop_id_pairs):
    s_ids = set()
    for s_id_pair in stop_id_pairs:
        s_ids = s_ids.union(list(s_id_pair))
    return s_ids

def build_stop_gtfs_ids_to_names_map(schedule, s_ids):
    stop_gtfs_ids_to_names_map = {}
    for s_id in s_ids:
        stop_gtfs_ids_to_names_map[int(s_id)] = schedule.stops[s_id].stop_name
    return stop_gtfs_ids_to_names_map

def write_route_speed_info_by_time_periods(schedule, gtfs_route_id,
        time_periods,
        route_avg_speeds_during_time_periods,
        seg_distances, output_path, round_places=2):

    if not os.path.exists(output_path):
        os.makedirs(output_path)

    gtfs_route = schedule.routes[str(gtfs_route_id)]
    trip_dict = gtfs_route.GetPatternIdTripDict()

    for route_dir, serv_period in \
            route_avg_speeds_during_time_periods.iterkeys():
        avg_speeds = route_avg_speeds_during_time_periods[\
            (route_dir, serv_period)]
        s_ids_this_route_period = extract_stop_ids_from_pairs(
            avg_speeds.iterkeys())
        stop_gtfs_ids_to_names_map = build_stop_gtfs_ids_to_names_map(schedule,
            s_ids_this_route_period)

        fname_all = tps_speeds_model.get_route_avg_speeds_for_dir_period_fname(
            gtfs_route.route_short_name, gtfs_route.route_long_name,
            serv_period, route_dir)
        fpath = os.path.join(output_path, fname_all)
        tps_speeds_model.write_avg_speeds_on_segments(
            stop_gtfs_ids_to_names_map,
            avg_speeds, seg_distances, time_periods,
            fpath, round_places)
    return

def write_route_freq_info_by_time_periods_by_patterns(schedule, gtfs_route_id,
        time_periods, hways_by_patterns,
        pattern_stop_orders, output_path, round_places=2):
    if not os.path.exists(output_path):
        os.makedirs(output_path)

    gtfs_route = schedule.routes[gtfs_route_id]
    trip_dict = gtfs_route.GetPatternIdTripDict()
    route_dir_serv_periods = extract_route_dir_serv_period_tuples(trip_dict)

    for p_ii, pattern_hways in enumerate(hways_by_patterns):
        stop_write_order = pattern_stop_orders[p_ii]
        stop_gtfs_ids_to_names_map = build_stop_gtfs_ids_to_names_map(
            schedule, stop_write_order)

        for dir_period_pair, headways in pattern_hways.iteritems():
            route_dir, serv_period = dir_period_pair
            r_s_name = gtfs_route.route_short_name
            r_l_name = gtfs_route.route_long_name
            fname = tps_hways_model.get_route_hways_for_pattern_fname(
                r_s_name, r_l_name, p_ii, route_dir, serv_period)
            fpath = os.path.join(output_path, fname)
            tps_hways_model.write_headways_minutes(stop_gtfs_ids_to_names_map, 
                headways, time_periods, fpath, stop_id_order=stop_write_order)
    return

def write_route_freq_info_by_time_periods_all_patterns(schedule, gtfs_route_id,
        time_periods, route_hways_during_time_periods_all_patterns,
        all_patterns_nominal_stop_orders, output_path, round_places=2):
    if not os.path.exists(output_path):
        os.makedirs(output_path)
    gtfs_route = schedule.routes[gtfs_route_id]
    trip_dict = gtfs_route.GetPatternIdTripDict()
    route_dir_serv_periods = extract_route_dir_serv_period_tuples(trip_dict)

    for route_dir, serv_period in route_dir_serv_periods:
        stop_write_order = all_patterns_nominal_stop_orders[\
            (route_dir, serv_period)]
        stop_gtfs_ids_to_names_map = build_stop_gtfs_ids_to_names_map(
            schedule, stop_write_order)
        r_s_name = gtfs_route.route_short_name
        r_l_name = gtfs_route.route_long_name
        fname_all = tps_hways_model.get_route_hways_for_dir_period_fname(
            r_s_name, r_l_name, serv_period, route_dir)
        fpath = os.path.join(output_path, fname_all)
        headways = route_hways_during_time_periods_all_patterns[\
            (route_dir, serv_period)]
        tps_hways_model.write_headways_minutes(stop_gtfs_ids_to_names_map,
            headways, time_periods, fpath, stop_id_order=stop_write_order)
    return

def get_average_hways_all_stops_by_time_periods(hways_all_patterns):
    n_tps = len(hways_all_patterns.values()[0].values()[0])
    tp_hways_all_stops = {}
    for dir_period_pair in hways_all_patterns.iterkeys():
        tp_hways_all_stops[dir_period_pair] = \
            [[] for dummy in xrange(n_tps)]
    for dir_period_pair, each_stop_hways_in_tps in \
            hways_all_patterns.iteritems():
        for stop_hways_in_tps in each_stop_hways_in_tps.itervalues():
            for tp_i, stop_hway in enumerate(stop_hways_in_tps):
                if stop_hway > 0:
                    tp_hways_all_stops[dir_period_pair][tp_i].append(stop_hway)
    avg_hways_all_stops = {}
    for dir_period_pair in hways_all_patterns.iterkeys():
        avg_hways_all_stops[dir_period_pair] = [-1] * n_tps
        for tp_i, tp_hways_at_stops in \
                enumerate(tp_hways_all_stops[dir_period_pair]):
            n_valid = len(tp_hways_at_stops)
            if n_valid:
                avg_hways_all_stops[dir_period_pair][tp_i] = \
                    sum(tp_hways_at_stops) / float(n_valid)
    return avg_hways_all_stops

