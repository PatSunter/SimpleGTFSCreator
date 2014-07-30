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
import create_route_defs_csv as route_defs
import mode_timetable_info as m_t_info

# Length calculations:-

# per route
  # Total route-km.
  # Route-km duplicated with other buses
  # (Optional):- Route-km duplicated with tram network

# Bus service km / route:-

MORNING_PEAK = time(8,00)

def get_route_length(route_def, segs_lookup_dict):
    rlength = 0
    for segtuple in route_def:
        seg_id = segtuple[0]
        seg_feat = segs_lookup_dict[seg_id]
        dist_km = tp_model.get_distance_km(seg_feat)
        rlength += dist_km
    return rlength

def get_route_shared_sections_bus(route_def, segs_lookup_dict):
    shared_len = 0
    shared_lens_by_route = {}
    for segtuple in route_def:
        seg_id = segtuple[0]
        seg_feat = segs_lookup_dict[seg_id]
        seg_rlist = tp_model.get_routes_on_seg(seg_feat)
        if len(seg_rlist) > 1:
            dist_km = tp_model.get_distance_km(seg_feat)
            shared_len += dist_km
    return shared_len, shared_lens_by_route

def calc_time_on_route_peak(route_def, segs_lookup_dict):
    rtime = timedelta(0)
    for segtuple in route_def:
        seg_id = segtuple[0]
        seg_feat = segs_lookup_dict[seg_id]
        dist_km = tp_model.get_distance_km(seg_feat)
        seg_hrs = dist_km / seg_feat.GetField(tp_model.SEG_PEAK_SPEED_FIELD)
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

def get_all_route_infos(segs_lyr, mode_config):
    segs_lookup_dict = tp_model.build_segs_lookup_table(segs_lyr)
    all_routes = route_defs.get_routes_and_segments(segs_lyr)
    rnames_sorted = route_defs.get_route_names_sorted(all_routes)
    routes_ordered, route_dirs = route_defs.order_route_segments(all_routes,
        rnames_sorted)

    route_lengths = {}
    route_shared_section_lengths = {}
    route_shared_section_lengths_by_route = {}
    for rname in rnames_sorted:
        route_def = routes_ordered[rname]
        route_lengths[rname] = get_route_length(route_def, segs_lookup_dict)
        shared_len, shared_lens_by_route = get_route_shared_sections_bus(
            route_def, segs_lookup_dict)
        route_shared_section_lengths[rname] = shared_len
        route_shared_section_lengths_by_route[rname] = shared_lens_by_route
        # TODO:- get_route_shared_sections_tram()

    print "Route lengths for %d routes:" % len(rnames_sorted)
    for rname in rnames_sorted:
        print "%s: %.2fkm" % (rname, route_lengths[rname])
    tot_dist = sum(route_lengths.values())
    print "\nTotal route dist: %.2fkm (%.2fkm if bi-directional)" \
        % (tot_dist, tot_dist * 2)
    tot_multi_route = sum(route_shared_section_lengths.values())
    tot_single_route = tot_dist - tot_multi_route
    print "Of this dist, %.2fkm is single-route, %.2fkm is multi-route." \
        % (tot_single_route, tot_multi_route)

    route_trav_times = {}
    buses_needed = {}
    for rname in rnames_sorted:
        route_def = routes_ordered[rname]
        route_trav_time = calc_time_on_route_peak(route_def,
            segs_lookup_dict)
        route_trav_times[rname] = route_trav_time
        buses_needed[rname] = calc_buses_needed_for_route(route_trav_time,
            mode_config)

    print "Route trav times in peak and est. buses needed:" 
    for rname in rnames_sorted:
        print "%s: %s, %d" % (rname, route_trav_times[rname],
            buses_needed[rname])
    print "\nTotal estimated buses needed in peak for the %d routes: %d" \
        % (len(rnames_sorted), sum(buses_needed.values()))

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
        parser.error("No input shape file path containing route infos given.")
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
