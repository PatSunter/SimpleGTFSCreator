
import os, sys
import os.path
from datetime import time, datetime, date, timedelta
import csv

import misc_utils

def get_route_avg_speeds_for_dir_period_fname(r_short_name, r_long_name,
        serv_period, route_dir):
    rname_file_ready = misc_utils.routeNameFileReady(r_short_name, r_long_name)
    rdir_str = misc_utils.routeDirStringToFileReady(route_dir)
    fname = "%s-speeds-%s-%s-all.csv" % \
        (rname_file_ready, serv_period, rdir_str)
    return fname

AVG_SPEED_HEADERS = ['Stop_a_id','Stop_a_name','Stop_b_id','Stop_b_name',\
        'seg_dist_m'] # then time periods follow.

def write_avg_speeds_on_segments(stop_gtfs_ids_to_names_map, period_avg_speeds,
        seg_distances, periods, csv_fname, round_places):
    # Use absolute path to deal with Windows issues with long paths.
    safe_path_fname = misc_utils.get_win_safe_path(csv_fname)
    if sys.version_info >= (3,0,0):
        csv_file = open(safe_path_fname, 'w', newline='')
    else:
        csv_file = open(safe_path_fname, 'wb')
    writer = csv.writer(csv_file, delimiter=';')

    period_names = misc_utils.get_time_period_name_strings(periods)
    writer.writerow(AVG_SPEED_HEADERS + period_names)

    s_id_pairs = period_avg_speeds.keys()
    for s_id_pair in s_id_pairs:
        avg_speeds_on_seg = period_avg_speeds[s_id_pair]
        if round_places:
            assert round_places >= 1
            avg_speeds_on_seg_output = map(lambda x: round(x, round_places),
                avg_speeds_on_seg)
        else:
            avg_speeds_on_seg_output = avg_speeds_on_seg
        writer.writerow(
            [s_id_pair[0], stop_gtfs_ids_to_names_map[int(s_id_pair[0])], \
            s_id_pair[1],  stop_gtfs_ids_to_names_map[int(s_id_pair[1])], \
            round(seg_distances[s_id_pair], round_places)] \
            + avg_speeds_on_seg_output)
    csv_file.close()
    return

def read_route_speed_info_by_time_periods(read_dir, r_short_name, r_long_name,
        serv_period, trips_dir, sort_seg_stop_id_pairs=False):

    if not os.path.exists(read_dir):
        raise ValueError("Bad path %s given to read in average speed "\
            "infos from. " % read_dir)

    fname_all = get_route_avg_speeds_for_dir_period_fname(
        r_short_name, r_long_name, serv_period, trips_dir)
    fpath = os.path.join(read_dir, fname_all)
    time_periods, r_avg_speeds_on_segs, seg_distances = \
        read_avg_speeds_on_segments(fpath, sort_seg_stop_id_pairs)

    return time_periods, r_avg_speeds_on_segs, seg_distances        

def read_avg_speeds_on_segments(csv_fname, sort_seg_stop_id_pairs=False):
    safe_fpath = misc_utils.get_win_safe_path(csv_fname)
    csv_file = open(safe_fpath, 'r')
    reader = csv.reader(csv_file, delimiter=';')

    headers = reader.next()
    tperiod_strings = headers[len(AVG_SPEED_HEADERS):]
    time_periods = misc_utils.get_time_periods_from_strings(tperiod_strings)

    dist_row_i = AVG_SPEED_HEADERS.index('seg_dist_m')
    stop_a_id_i = AVG_SPEED_HEADERS.index('Stop_a_id')
    stop_b_id_i = AVG_SPEED_HEADERS.index('Stop_b_id')

    seg_distances = {}
    r_avg_speeds_on_segs = {}
    for row in reader:
        stop_a_id = row[stop_a_id_i]
        stop_b_id = row[stop_b_id_i]
        stop_ids = stop_a_id, stop_b_id
        if sort_seg_stop_id_pairs:
            stop_ids = tuple(map(str, sorted(map(int, stop_ids))))
        seg_distances[stop_ids] = float(row[dist_row_i])
        speeds_in_tps = map(float, row[len(AVG_SPEED_HEADERS):])
        r_avg_speeds_on_segs[stop_ids] = speeds_in_tps
    csv_file.close()
    return time_periods, r_avg_speeds_on_segs, seg_distances 

