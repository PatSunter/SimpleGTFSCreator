#!/usr/bin/env python2

import os
import inspect
from optparse import OptionParser
import osgeo.ogr
from osgeo import ogr
import csv
import sys
import math
from datetime import timedelta, time

import topology_shapefile_data_model as tp_model
import mode_timetable_info as m_t_info
import route_segs
import gtfs_ops

# Length calculations:-

# per route
  # Total route-km.
  # Route-km duplicated with other vehicles
  # (Optional):- Route-km duplicated with tram network

# Bus service km / route:-

MORNING_PEAK = time(8,00)

def get_route_length(segs_in_route):
    rlength = 0
    for seg_ref in segs_in_route:
        rlength += route_segs.get_seg_dist_km(seg_ref)
    return rlength

def get_route_shared_sections_same(segs_in_route, curr_r_id):
    shared_len = 0
    shared_lens_by_route = {}
    for seg_ref in segs_in_route:
        if len(seg_ref.routes) > 1:
            seg_route_dist_km = route_segs.get_seg_dist_km(seg_ref)
            shared_len += seg_route_dist_km
            for r_id in seg_ref.routes:
                if r_id == curr_r_id:
                    continue
                if r_id not in shared_lens_by_route:
                    shared_lens_by_route[r_id] = seg_route_dist_km     
                else:
                    shared_lens_by_route[r_id] += seg_route_dist_km
    return shared_len, shared_lens_by_route

def calc_time_on_route_peak(segs_in_route, segs_lookup_dict):
    rtime = timedelta(0)
    for seg_ref in segs_in_route:
        seg_id = seg_ref.seg_id
        seg_route_dist_km = route_segs.get_seg_dist_km(seg_ref)
        seg_feat = segs_lookup_dict[seg_id]
        seg_peak_speed_km_h = seg_feat.GetField(tp_model.SEG_PEAK_SPEED_FIELD)
        if seg_peak_speed_km_h <= 0:
            print "Error in calc time on segment id %d - bad speed value of "\
                "%f km/h encountered." % (seg_id, seg_peak_speed_km_h)
            sys.exit(1)
        seg_hrs = seg_route_dist_km / seg_peak_speed_km_h
        rtime += timedelta(hours=seg_hrs)
    return rtime

def get_minutes(t_delta):
    return t_delta.days * 60 * 24 + t_delta.seconds / 60 \
        + t_delta.microseconds / 1e6 / 60

def calc_vehicles_needed_for_route_conservative_bidir(
        route_trav_time, mode_config):
    # This approach based on assuming need to start both route directions
    # simultaneously at the start.
    service_headways = mode_config['services_info'][0][1]
    freq_in_peak = m_t_info.get_freq_at_time(service_headways, MORNING_PEAK)
    route_time_min = get_minutes(route_trav_time)
    vehicles_needed = 2 * math.ceil(route_time_min / float(freq_in_peak))
    return vehicles_needed

def calc_vehicles_needed_for_route_with_recovery_time(
        route_trav_time, mode_config):
    # Formula in this func based on that at http://www.transitmix.net
    RECOVERY_TIME_PERCENT = 10
    service_headways = mode_config['services_info'][0][1]
    freq_in_peak = m_t_info.get_freq_at_time(service_headways, MORNING_PEAK)
    route_time_min = get_minutes(route_trav_time)
    bidir_route_time_with_rec = 2 * route_time_min \
        * (100+RECOVERY_TIME_PERCENT)/100
    vehicles_needed = math.ceil(bidir_route_time_with_rec / float(freq_in_peak))
    return vehicles_needed

calc_vehicles_needed_for_route = calc_vehicles_needed_for_route_with_recovery_time
#calc_vehicles_needed_for_route = calc_vehicles_needed_for_route_conservative_bidir

def format_timedelta_nicely(time_d):
    total_secs = gtfs_ops.tdToSecs(time_d)
    hours, rem_secs = divmod(total_secs, gtfs_ops.SECS_PER_HOUR)
    mins, secs = divmod(rem_secs, 60)
    return "%d:%02d:%04.1f" % (hours, mins, secs)

def get_all_route_infos(segs_lyr, route_defs_csv_fname, mode_config):

    route_defs = route_segs.read_route_defs(route_defs_csv_fname)
    route_defs.sort(key=route_segs.get_route_order_key_from_name)

    segs_lookup_dict = tp_model.build_segs_lookup_table(segs_lyr)
    route_lengths = {}
    route_shared_section_lengths = {}
    route_shared_section_lengths_by_route = {}

    for r_def in route_defs:
        r_id = r_def.id
        segs_in_route = route_segs.create_ordered_seg_refs_from_ids(
            r_def.ordered_seg_ids, segs_lookup_dict)
        route_lengths[r_id] = get_route_length(segs_in_route)
        shared_len, shared_lens_by_route = get_route_shared_sections_same(
            segs_in_route, r_id)
        route_shared_section_lengths[r_id] = shared_len
        route_shared_section_lengths_by_route[r_id] = shared_lens_by_route
        # TODO:- get_route_shared_sections_tram()

    print "Route lengths for %d routes:" % len(route_defs)
    for r_def in route_defs:
        r_id = r_def.id
        rname = route_segs.get_print_name(r_def)
        print "%s: %05.2fkm" % (rname, route_lengths[r_id])
    tot_dist = sum(route_lengths.values())
    print "\nTotal route dist: %05.2fkm (%05.2fkm if bi-directional)" \
        % (tot_dist, tot_dist * 2)
    tot_multi_route = sum(route_shared_section_lengths.values())
    tot_single_route = tot_dist - tot_multi_route
    print "Of this dist, %05.2fkm is single-route, %05.2fkm is multi-route.\n" \
        % (tot_single_route, tot_multi_route)

    route_trav_times = {}
    route_avg_speeds = {}
    route_vehicles_needed = {}
    for r_def in route_defs:
        r_id = r_def.id
        rname = route_segs.get_print_name(r_def)
        segs_in_route = route_segs.create_ordered_seg_refs_from_ids(
            r_def.ordered_seg_ids, segs_lookup_dict)
        route_trav_time = calc_time_on_route_peak(segs_in_route,
            segs_lookup_dict)
        route_trav_times[r_id] = route_trav_time
        route_avg_speeds[r_id] = route_lengths[r_id] \
            / gtfs_ops.tdToHours(route_trav_time)
        route_vehicles_needed[r_id] = calc_vehicles_needed_for_route(
            route_trav_time, mode_config)

    print "Route dists, trav times in peak, avg speed (km/h), and min. "\
        "vehicles needed:" 
    for r_def in route_defs:
        r_id = r_def.id
        rname = route_segs.get_print_name(r_def)
        print "%s: %05.2fkm, time %s, avespeed %.2f, vehicles %d" % (rname,
            route_lengths[r_id],
            format_timedelta_nicely(route_trav_times[r_id]),
            route_avg_speeds[r_id],
            route_vehicles_needed[r_id])
    print "\nTotal estimated vehicles needed in peak for the %d routes: %d" \
        % (len(route_defs), sum(route_vehicles_needed.values()))

def main():
    allowedServs = ', '.join(sorted(["'%s'" % key for key in \
        m_t_info.settings.keys()]))
    parser = OptionParser()
    parser.add_option('--segments', dest='segments',
        help='Shape file containing route segments, which list routes in each'\
            ' segment, segment speed, etc.')
    parser.add_option('--routes', dest='routes',
        help='file name containing route definitions (.csv)')
    parser.add_option('--output_csv', dest='output_csv',
        help='Output file name you want to store summary results in per-route'\
            ' (suggest should end in .csv)')
    parser.add_option('--service', dest='service',
        help="Should be one of %s" % allowedServs)

    parser.set_defaults(output_csv='route_infos.csv')
    (options, args) = parser.parse_args()

    if options.segments is None:
        parser.print_help()
        parser.error("input shape file path containing segments not given.")
    if options.routes is None:
        parser.print_help()
        parser.error("input route defs file path not given.")
    if options.service is None:
        parser.print_help()
        parser.error("No service option requested. Should be one of %s" \
            % (allowedServs))
    if options.service not in m_t_info.settings:
        parser.print_help()
        parser.error("Service option requested '%s' not in allowed set, of %s" \
            % (options.service, allowedServs))

    mode_config = m_t_info.settings[options.service]

    shapefile = osgeo.ogr.Open(options.segments)
    segs_lyr = shapefile.GetLayer(0)

    get_all_route_infos(segs_lyr, options.routes, mode_config)
    shapefile.Destroy()

if __name__ == "__main__":
    main()
