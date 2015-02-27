
import os, sys
import os.path
from datetime import time, datetime, date, timedelta
import csv
import glob
import shutil

import misc_utils
HWAYS_PER_STOP_HDRS = ['Stop_id','Stop_name']
AVG_HWAYS_ALL_STOPS_HDRS = ['route_id','route_short_name','route_long_name',\
    'serv_period','trips_dir']

def get_route_hways_for_pattern_fname(r_short_name, r_long_name,
        pattern_i, route_dir, serv_period):
    rname_file_ready = misc_utils.routeNameFileReady(
        r_short_name, r_long_name)
    rdir_str = misc_utils.routeDirStringToFileReady(route_dir)
    fname = "%s-hways-p%d-%s-%s.csv" % \
        (rname_file_ready, pattern_i, rdir_str, serv_period)
    return fname 

def get_route_hways_for_dir_period_fname(r_short_name, r_long_name,
        serv_period, route_dir):
    rname_file_ready = misc_utils.routeNameFileReady(
        r_short_name, r_long_name)
    rdir_str = misc_utils.routeDirStringToFileReady(route_dir)
    fname = "%s-hways-%s-%s-all.csv" % \
        (rname_file_ready, serv_period, rdir_str)
    return fname

def get_info_from_fname(route_hways_fname, r_s_name=None, r_l_name=None):
    fname_sections = os.path.basename(route_hways_fname).split('-')
    # Index from the back, as name used depends on if 
    # both short and long name specified.
    serv_period = fname_sections[-3]
    trips_dir_file_ready = fname_sections[-2]
    if r_s_name and r_l_name:
        name_a = r_s_name
        name_b = r_l_name
    else:
        # We need to get these from the file.
        name_b = fname_sections[-5]
        try:
            name_a = fname_sections[-6]
        except IndexError:
            name_a = None
    return name_a, name_b, trips_dir_file_ready, serv_period 

def get_hways_fnames(hways_dir, r_short_name, r_long_name):
    # The match depends on if we've specified both old route short
    # and long names. If only one specified, need looser search.
    route_print_name = misc_utils.routeNameFileReady(
        r_short_name, r_long_name)
    match_exps = []
    if r_short_name and r_long_name:
        match_exps.append("%s%s%s-hways-*-all.csv" \
            % (hways_dir, os.sep, route_print_name))
    elif r_short_name:
        match_exps.append("%s%s%s-hways-*-all.csv" \
            % (hways_dir, os.sep, route_print_name))
        match_exps.append("%s%s%s-*-hways-*-all.csv" \
            % (hways_dir, os.sep, route_print_name))
    elif r_long_name:            
        match_exps.append("%s%s%s-hways-*-all.csv" \
            % (hways_dir, os.sep, route_print_name))
        match_exps.append("%s%s*-%s-hways-*-all.csv" \
            % (hways_dir, os.sep, route_print_name))
    route_hways_fnames = []
    for match_exp in match_exps:    
        route_hways_fnames += glob.glob(match_exp)
    return route_hways_fnames

def copy_route_hways(r_short_name, r_long_name, hways_dir_in,
        hways_dir_out):
    route_print_name = misc_utils.routeNameFileReady(
        r_short_name, r_long_name)
    route_hways_fnames = glob.glob(
        "%s%s%s-hways-*-all.csv" % (hways_dir_in, os.sep, \
            route_print_name))
    copy_path_out = misc_utils.get_win_safe_path(hways_dir_out)
    for hways_fname in route_hways_fnames:
        copy_path_in = misc_utils.get_win_safe_path(hways_fname)
        shutil.copy(copy_path_in, copy_path_out)
    return

def write_headways_minutes(stop_gtfs_ids_to_names_map, period_headways,
        periods, csv_fname, stop_id_order=None):

    safe_path_fname = misc_utils.get_win_safe_path(csv_fname)
    if sys.version_info >= (3,0,0):
        csv_file = open(safe_path_fname, 'w', newline='')
    else:
        csv_file = open(safe_path_fname, 'wb')

    writer = csv.writer(csv_file, delimiter=';')

    period_names = misc_utils.get_time_period_name_strings(periods)
    writer.writerow(HWAYS_PER_STOP_HDRS + period_names)

    if stop_id_order is None:
        s_ids = period_headways.keys()
    else:
        s_ids = stop_id_order
    for s_id in s_ids:
        period_headways_at_stop = period_headways[s_id]
        writer.writerow([s_id, stop_gtfs_ids_to_names_map[int(s_id)]] \
            + period_headways_at_stop)
    csv_file.close()
    return

def read_headways_minutes(csv_fname):
    safe_fpath = misc_utils.get_win_safe_path(csv_fname)
    csv_file = open(safe_fpath, 'r')
    reader = csv.reader(csv_file, delimiter=';')

    headers = reader.next()
    tperiod_strings = headers[len(HWAYS_PER_STOP_HDRS):]
    time_periods = misc_utils.get_time_periods_from_strings(tperiod_strings)
    stop_id_i = HWAYS_PER_STOP_HDRS.index('Stop_id')
    stop_name_i = HWAYS_PER_STOP_HDRS.index('Stop_name')

    seg_distances = {}
    headways_at_stops_in_tps = {}
    stop_gtfs_ids_to_names_map = {}
    for row in reader:
        stop_id = row[stop_id_i]
        stop_name = row[stop_name_i]
        if not stop_name: stop_name = None
        stop_gtfs_ids_to_names_map[int(stop_id)] = stop_name
        hways_in_tps = map(float, row[len(HWAYS_PER_STOP_HDRS):])
        headways_at_stops_in_tps[stop_id] = hways_in_tps
    csv_file.close()
    return time_periods, headways_at_stops_in_tps, \
        stop_gtfs_ids_to_names_map 

def write_route_hways_all_routes_all_stops(r_ids_to_names_map,
        time_periods, avg_hways_all_stops, output_fname, round_places=2):
    print "Writing all route average headways in TPs to file %s ..." \
        % output_fname
    
    safe_path_fname = misc_utils.get_win_safe_path(output_fname)
    if sys.version_info >= (3,0,0):
        csv_file = open(safe_path_fname, 'w', newline='')
    else:
        csv_file = open(safe_path_fname, 'wb')
    writer = csv.writer(csv_file, delimiter=';')
    period_names = misc_utils.get_time_period_name_strings(time_periods)
    route_ids_sorted = sorted(avg_hways_all_stops.keys(), key=lambda x:int(x))
    writer.writerow(AVG_HWAYS_ALL_STOPS_HDRS + period_names)
    for route_id in route_ids_sorted:
        avg_hways_all_stops_by_dir_period_pairs = avg_hways_all_stops[route_id]
        r_short_name, r_long_name = r_ids_to_names_map[route_id]
        avg_hways_all_stops_by_dpps_sorted = \
            sorted(avg_hways_all_stops_by_dir_period_pairs.items(),
                key=lambda x: (x[0][1], x[0][0]))
        for dir_period_pair, avg_hways_in_tps in \
                avg_hways_all_stops_by_dpps_sorted:
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
    safe_path_fname = misc_utils.get_win_safe_path(per_route_hways_fname)
    csv_in_file = open(safe_path_fname, 'r')
    reader = csv.reader(csv_in_file, delimiter=';')

    avg_hways_all_stops = {}
    r_ids_to_names_map = {}
    r_id_i = AVG_HWAYS_ALL_STOPS_HDRS.index('route_id')
    r_s_name_i = AVG_HWAYS_ALL_STOPS_HDRS.index('route_short_name')
    r_l_name_i = AVG_HWAYS_ALL_STOPS_HDRS.index('route_long_name')
    sp_i = AVG_HWAYS_ALL_STOPS_HDRS.index('serv_period')
    td_i = AVG_HWAYS_ALL_STOPS_HDRS.index('trips_dir')
    headers = reader.next()
    n_base_cols = len(AVG_HWAYS_ALL_STOPS_HDRS) 
    tp_strs = headers[n_base_cols:]
    tps = misc_utils.get_time_periods_from_strings(tp_strs)
    for row in reader:
        r_id = row[r_id_i]
        r_short_name = row[r_s_name_i]
        if not r_short_name:
            r_short_name = None
        r_long_name = row[r_l_name_i]
        if not r_long_name:
            r_long_name = None
        r_ids_to_names_map[r_id] = r_short_name, r_long_name
        serv_period = row[sp_i]
        trips_dir = row[td_i]
        avg_hways_in_tps = map(float, row[n_base_cols:])
        if r_id not in avg_hways_all_stops:
            avg_hways_all_stops[r_id] = {}
        avg_hways_all_stops[r_id][(trips_dir,serv_period)] = avg_hways_in_tps
    csv_in_file.close()
    return avg_hways_all_stops, tps, r_ids_to_names_map

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

def decrease_hways_to_max_in_window(avg_hways_in_tps, tps, max_headway,
        time_window_start, time_window_end):
    avg_hways_in_tps_out = []
    for tp_i, hway in enumerate(avg_hways_in_tps):
        tp = tps[tp_i]
        if tp[1] > time_window_start and tp[0] < time_window_end:
            hway_out = min(hway, max_headway)
            if hway_out <= 0:
                hway_out = max_headway
        else:
            hway_out = hway
        avg_hways_in_tps_out.append(hway_out)
    return avg_hways_in_tps_out
