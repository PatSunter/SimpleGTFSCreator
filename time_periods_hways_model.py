
import os, sys
import os.path
from datetime import time, datetime, date, timedelta
import csv

import misc_utils

def get_route_hways_for_pattern_fname(gtfs_route, pattern_i,
        route_dir, serv_period):
    rname_file_ready = misc_utils.routeNameFileReady(
        gtfs_route.route_short_name, gtfs_route.route_long_name)
    rdir_str = misc_utils.routeDirStringToFileReady(route_dir)
    fname = "%s-hways-p%d-%s-%s.csv" % \
        (rname_file_ready, pattern_i, rdir_str, serv_period)
    return fname 

def get_route_hways_for_dir_period_fname(gtfs_route, serv_period,
        route_dir):
    rname_file_ready = misc_utils.routeNameFileReady(
        gtfs_route.route_short_name, gtfs_route.route_long_name)
    rdir_str = misc_utils.routeDirStringToFileReady(route_dir)
    fname = "%s-hways-%s-%s-all.csv" % \
        (rname_file_ready, serv_period, rdir_str)
    return fname

def write_headways_minutes(schedule, period_headways, periods, csv_fname,
        stop_id_order=None):

    if sys.version_info >= (3,0,0):
        csv_file = open(csv_fname, 'w', newline='')
    else:
        csv_file = open(csv_fname, 'wb')

    writer = csv.writer(csv_file, delimiter=';')

    period_names = misc_utils.get_time_period_name_strings(periods)
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

AVG_HWAYS_ALL_STOPS_HDRS = ['route_id','route_short_name','route_long_name',\
    'serv_period','trips_dir']

def write_route_hways_all_routes_all_stops(schedule, time_periods,
        avg_hways_all_stops, output_fname, round_places=2):
    print "Writing all route average headways in TPs to file %s ..." \
        % output_fname
    csv_file = open(output_fname, 'w')
    writer = csv.writer(csv_file, delimiter=';')
    period_names = misc_utils.get_time_period_name_strings(time_periods)
    writer.writerow(AVG_HWAYS_ALL_STOPS_HDRS + period_names)
    for route_id, avg_hways_all_stops_by_serv_periods in \
            avg_hways_all_stops.iteritems():
        gtfs_route = schedule.routes[route_id]    
        r_short_name = gtfs_route.route_short_name
        r_long_name = gtfs_route.route_long_name
        avg_hways_all_stops_by_sps_sorted = \
            sorted(avg_hways_all_stops_by_serv_periods.items(),
                key=lambda x: x[0][1])
        for dir_period_pair, avg_hways_in_tps in \
                avg_hways_all_stops_by_sps_sorted:
            trips_dir = dir_period_pair[0]
            serv_period = dir_period_pair[1]
            avg_hways_in_tps_rnd = map(lambda x: round(x, round_places), \
                avg_hways_in_tps)
            writer.writerow([route_id, r_short_name, r_long_name, \
                serv_period, trips_dir] + avg_hways_in_tps_rnd)
    csv_file.close()
    print "... done writing."
    return

def read_route_hways_all_routes_all_stops(per_route_hways_fname):
    csv_in_file = open(per_route_hways_fname, 'r')
    reader = csv.reader(csv_in_file, delimiter=';')

    avg_hways_all_stops = {}
    r_id_i = AVG_HWAYS_ALL_STOPS_HDRS.index('route_id')
    sp_i = AVG_HWAYS_ALL_STOPS_HDRS.index('serv_period')
    td_i = AVG_HWAYS_ALL_STOPS_HDRS.index('trips_dir')
    headers = reader.next()
    n_base_cols = len(AVG_HWAYS_ALL_STOPS_HDRS) 
    tp_strs = headers[n_base_cols:]
    tps = misc_utils.get_time_periods_from_strings(tp_strs)
    for row in reader:
        r_id = row[r_id_i]
        serv_period = row[sp_i]
        trips_dir = row[td_i]
        avg_hways_in_tps = map(float, row[n_base_cols:])
        if r_id not in avg_hways_all_stops:
            avg_hways_all_stops[r_id] = {}
        avg_hways_all_stops[r_id][(trips_dir,serv_period)] = avg_hways_in_tps
    csv_in_file.close()
    return avg_hways_all_stops, tps

def get_tp_hways_tuples(avg_hways_in_tps, time_periods, peak_status=True):
    """Assumes avg_hways_in_tps is in the form returned by func 
    get_average_hways_all_stops_by_time_periods() for one route, and
    one direction,serv_period pair."""
    tp_hway_tuples = []
    for tp, avg_hway in zip(time_periods, avg_hways_in_tps):
        # This conversion to Times is a bit of a legacy of format in
        # mdoe_timetable_info.py :- should probably be changed later.
        tp_start = misc_utils.tdToTimeOfDay(tp[0])
        tp_end = misc_utils.tdToTimeOfDay(tp[1])
        tp_hway_tuple = (tp_start, tp_end, avg_hway, peak_status)
        tp_hway_tuples.append(tp_hway_tuple)
    return tp_hway_tuples
