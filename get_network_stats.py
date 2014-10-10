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
  # Route-km duplicated with other buses
  # (Optional):- Route-km duplicated with tram network

# Bus service km / route:-

MORNING_PEAK = time(8,00)

def get_route_length(segs_in_route):
    rlength = 0
    for seg_ref in segs_in_route:
        rlength += route_segs.get_seg_dist_km(seg_ref)
    return rlength

def get_route_shared_sections_bus(segs_in_route, curr_route_name):
    shared_len = 0
    shared_lens_by_route = {}
    for seg_ref in segs_in_route:
        if len(seg_ref.routes) > 1:
            seg_route_dist_km = route_segs.get_seg_dist_km(seg_ref)
            shared_len += seg_route_dist_km
            for rname in seg_ref.routes:
                if rname == curr_route_name:
                    continue
                if rname not in shared_lens_by_route:
                    shared_lens_by_route[rname] = seg_route_dist_km     
                else:
                    shared_lens_by_route[rname] += seg_route_dist_km
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

def calc_buses_needed_for_route_conservative_bidir(
        route_trav_time, mode_config):
    # This approach based on assuming need to start both route directions
    # simultaneously at the start.
    service_headways = mode_config['services_info'][0][1]
    freq_in_peak = m_t_info.get_freq_at_time(service_headways, MORNING_PEAK)
    route_time_min = get_minutes(route_trav_time)
    buses_needed = 2 * math.ceil(route_time_min / float(freq_in_peak))
    return buses_needed

def calc_buses_needed_for_route_with_recovery_time(
        route_trav_time, mode_config):
    # Formula in this func based on that at http://www.transitmix.net
    RECOVERY_TIME_PERCENT = 10
    service_headways = mode_config['services_info'][0][1]
    freq_in_peak = m_t_info.get_freq_at_time(service_headways, MORNING_PEAK)
    route_time_min = get_minutes(route_trav_time)
    bidir_route_time_with_rec = 2 * route_time_min \
        * (100+RECOVERY_TIME_PERCENT)/100
    buses_needed = math.ceil(bidir_route_time_with_rec / float(freq_in_peak))
    return buses_needed

calc_buses_needed_for_route = calc_buses_needed_for_route_with_recovery_time
#calc_buses_needed_for_route = calc_buses_needed_for_route_conservative_bidir

def format_timedelta_nicely(time_d):
    total_secs = gtfs_ops.tdToSecs(time_d)
    hours, rem_secs = divmod(total_secs, gtfs_ops.SECS_PER_HOUR)
    mins, secs = divmod(rem_secs, 60)
    return "%d:%02d:%04.1f" % (hours, mins, secs)

def get_all_route_infos(segs_lyr, mode_config):
    seg_refs_by_routes = route_segs.get_routes_and_segments(segs_lyr)
    rnames_sorted = route_segs.get_route_names_sorted(
        seg_refs_by_routes.keys())
    routes_ordered, route_dirs = route_segs.order_all_route_segments(
        seg_refs_by_routes, rnames_sorted)

    segs_lookup_dict = tp_model.build_segs_lookup_table(segs_lyr)
    route_lengths = {}
    route_shared_section_lengths = {}
    route_shared_section_lengths_by_route = {}
    for rname in rnames_sorted:
        segs_in_route = routes_ordered[rname]
        route_lengths[rname] = get_route_length(segs_in_route)
        shared_len, shared_lens_by_route = get_route_shared_sections_bus(
            segs_in_route, rname)
        route_shared_section_lengths[rname] = shared_len
        route_shared_section_lengths_by_route[rname] = shared_lens_by_route
        # TODO:- get_route_shared_sections_tram()

    print "Route lengths for %d routes:" % len(rnames_sorted)
    for rname in rnames_sorted:
        print "%s: %05.2fkm" % (rname, route_lengths[rname])
    tot_dist = sum(route_lengths.values())
    print "\nTotal route dist: %05.2fkm (%05.2fkm if bi-directional)" \
        % (tot_dist, tot_dist * 2)
    tot_multi_route = sum(route_shared_section_lengths.values())
    tot_single_route = tot_dist - tot_multi_route
    print "Of this dist, %05.2fkm is single-route, %05.2fkm is multi-route.\n" \
        % (tot_single_route, tot_multi_route)

    route_trav_times = {}
    route_avg_speeds = {}
    route_buses_needed = {}
    for rname in rnames_sorted:
        segs_in_route = routes_ordered[rname]
        route_trav_time = calc_time_on_route_peak(segs_in_route,
            segs_lookup_dict)
        route_trav_times[rname] = route_trav_time
        route_avg_speeds[rname] = route_lengths[rname] \
            / gtfs_ops.tdToHours(route_trav_time)
        route_buses_needed[rname] = calc_buses_needed_for_route(route_trav_time,
            mode_config)

    print "Route dists, trav times in peak, avg speed (km/h), and min. "\
        "buses needed:" 
    for rname in rnames_sorted:
        print "%s: %05.2fkm, time %s, avespeed %.2f, buses %d" % (rname,
            route_lengths[rname],
            format_timedelta_nicely(route_trav_times[rname]),
            route_avg_speeds[rname],
            route_buses_needed[rname])
    print "\nTotal estimated buses needed in peak for the %d routes: %d" \
        % (len(rnames_sorted), sum(route_buses_needed.values()))

def main():
    allowedServs = ', '.join(sorted(["'%s'" % key for key in \
        m_t_info.settings.keys()]))
    parser = OptionParser()
    parser.add_option('--segments', dest='segments',
        help='Shape file containing route segments, which list routes in each'\
            ' segment, segment speed, etc.')
    parser.add_option('--output_csv', dest='output_csv',
        help='Output file name you want to store summary results in per-route'\
            ' (suggest should end in .csv)')
    parser.add_option('--service', dest='service',
        help="Should be one of %s" % allowedServs)
    parser.set_defaults(output_csv='route_infos.csv')
    (options, args) = parser.parse_args()

    if options.segments is None:
        parser.print_help()
        parser.error("seg_refs_by_routes input shape file path containing route infos given.")
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

    get_all_route_infos(segs_lyr, mode_config)
    shapefile.Destroy()

if __name__ == "__main__":
    main()
