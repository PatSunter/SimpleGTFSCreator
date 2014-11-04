#!/usr/bin/env python2

import os
import inspect
import osgeo.ogr
from osgeo import ogr
import csv
import sys
import math
import operator
from datetime import timedelta, time
from optparse import OptionParser

import parser_utils
import route_segs
import gtfs_ops
import seg_speed_models
import gtfs_ops
import topology_shapefile_data_model as tp_model
import mode_timetable_info as m_t_info

# Length calculations:-

# per route
  # Total route-km.
  # Route-km duplicated with other vehicles
  # (Optional):- Route-km duplicated with tram network

# Bus service km / route:-

PEAK_SERV_PERIOD = "monfri"
MORNING_PEAK = time(8,00)
MORNING_PEAK_TD = timedelta(hours=8,minutes=00)

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

def calc_time_on_route_peak(route_def, segs_in_route, segs_lookup_dict,
        seg_speed_model, peak_busy_dir_i):
    rtime = timedelta(0)
    for seg_ref in segs_in_route:
        seg_id = seg_ref.seg_id
        seg_route_dist_km = route_segs.get_seg_dist_km(seg_ref)
        seg_feat = segs_lookup_dict[seg_id]
        #seg_peak_speed_km_h = seg_feat.GetField(
        #    seg_speed_models.SEG_PEAK_SPEED_FIELD)
        seq_stop_info = seg_speed_model.save_extra_seg_speed_info(seg_feat,
            PEAK_SERV_PERIOD, peak_busy_dir_i)
        seg_peak_speed_km_h = seg_speed_model.get_speed_on_next_segment(
            seq_stop_info, MORNING_PEAK_TD, True)
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
        route_trav_time, service_headways):
    # This approach based on assuming need to start both route directions
    # simultaneously at the start.
    hway_near_peak, valid_time = m_t_info.get_nearest_next_valid_freq_and_time(
        service_headways, MORNING_PEAK)
    assert hway_near_peak and hway_near_peak > 0
    route_time_min = get_minutes(route_trav_time)
    vehicles_needed = 2 * math.ceil(route_time_min / float(hway_near_peak))
    return vehicles_needed, valid_time

RECOVERY_TIME_PERCENT = 10

def calc_vehicles_needed_for_route_with_recovery_time(
        route_trav_time, service_headways):
    # Formula in this func based on that at http://www.transitmix.net
    hway_near_peak, valid_time = m_t_info.get_nearest_next_valid_freq_and_time(
        service_headways, MORNING_PEAK)
    assert hway_near_peak and hway_near_peak > 0
    route_time_min = get_minutes(route_trav_time)
    bidir_route_time_with_rec = 2 * route_time_min \
        * (100+RECOVERY_TIME_PERCENT)/100
    vehicles_needed = math.ceil(bidir_route_time_with_rec / \
        float(hway_near_peak))
    return vehicles_needed, valid_time

calc_vehicles_needed_for_route = \
    calc_vehicles_needed_for_route_with_recovery_time
#calc_vehicles_needed_for_route = \
#    calc_vehicles_needed_for_route_conservative_bidir

def format_timedelta_nicely(time_d):
    total_secs = gtfs_ops.tdToSecs(time_d)
    hours, rem_secs = divmod(total_secs, gtfs_ops.SECS_PER_HOUR)
    mins, secs = divmod(rem_secs, 60)
    return "%d:%02d:%04.1f" % (hours, mins, secs)

def get_all_route_infos(segs_lyr, stops_lyr, route_defs_csv_fname,
        mode_config, seg_speed_model, per_route_hways=None, hways_tps=None):

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
    print "Of this dist, %05.2fkm is single-route, %05.2fkm is multi-route.\n"\
        % (tot_single_route, tot_multi_route)

    route_peak_time_of_days = {}
    route_trav_times = {}
    route_hways_in_peak = {}
    route_avg_speeds = {}
    route_vehicles_needed = {}

    seg_speed_model.setup(route_defs, segs_lyr, stops_lyr, mode_config)
    for r_def in route_defs:
        r_id = r_def.id
        rname = route_segs.get_print_name(r_def)
        segs_in_route = route_segs.create_ordered_seg_refs_from_ids(
            r_def.ordered_seg_ids, segs_lookup_dict)
        # TODO: ideally, calculate the 'in to city' direction,
        # as likely slower.
        peak_busy_dir_id = 0
        peak_busy_dir = r_def.dir_names[peak_busy_dir_id]
        services_info = mode_config['services_info']
        serv_periods = map(operator.itemgetter(0), services_info)
        PEAK_SERV_PERIOD_I = serv_periods.index(PEAK_SERV_PERIOD)
        setup_success = seg_speed_model.setup_for_route(r_def,
            [PEAK_SERV_PERIOD])
        if setup_success:
            serv_period_to_use = PEAK_SERV_PERIOD
            serv_period_to_use_i = PEAK_SERV_PERIOD_I
        if not setup_success:
            for serv_period_i in range(len(services_info)):
                if serv_period_i == PEAK_SERV_PERIOD_I:
                    continue
                serv_period = serv_periods[serv_period_i]
                setup_success = seg_speed_model.setup_for_route(r_def,
                    [serv_period])
                if setup_success:
                    serv_period_to_use = serv_period
                    serv_period_to_use_i = serv_period_i
                    break
        if not setup_success:
            print "Warning:- for route ID %s - %s, no route speeds setup "\
                "successfully for any period. Entering vehicles "\
                "needed as 0." % (str(r_id), rname)
            route_peak_time_of_days[r_id] = None
            route_hways_in_peak[r_id] = -1
            route_trav_times[r_id] = timedelta(0)
            route_avg_speeds[r_id] = 0
            route_vehicles_needed[r_id] = 0
            continue
        # Load up for all service periods where possible, just in case we need
        # them for speed calcs.
        setup_success = seg_speed_model.setup_for_route(r_def,
            serv_periods)

        seg_speed_model.setup_for_trip_set(r_def, PEAK_SERV_PERIOD,
            peak_busy_dir_id)

        if not per_route_hways:
            # Use the same period as we used to calc speed :- hopefully
            # the peak period.
            service_headways = services_info[serv_period_to_use_i][1]
        else:
            gtfs_r_id = r_def.gtfs_origin_id
            avg_hways_for_route = per_route_hways[gtfs_r_id]
            try:
                avg_hways_for_route_in_dir_period = \
                    avg_hways_for_route[(peak_busy_dir, serv_period_to_use)]
            except:
                # In some cases for bus loops, we had to manually add a
                # reverse dir, so try other one.
                other_dir = r_def.dir_names[1-peak_busy_dir_id]
                avg_hways_for_route_in_dir_period = \
                    avg_hways_for_route[(other_dir, serv_period_to_use)]
            service_headways = gtfs_ops.get_tp_hways_tuples(
                avg_hways_for_route_in_dir_period, hways_tps)
        peak_hways, peak_valid_time = \
            m_t_info.get_nearest_next_valid_freq_and_time(service_headways,
                MORNING_PEAK)
    
        route_trav_time = calc_time_on_route_peak(r_def, segs_in_route,
            segs_lookup_dict, seg_speed_model, peak_busy_dir_id)
        route_peak_time_of_days[r_id] = peak_valid_time
        route_hways_in_peak[r_id] = peak_hways
        route_trav_times[r_id] = route_trav_time
        route_avg_speeds[r_id] = route_lengths[r_id] \
            / gtfs_ops.tdToHours(route_trav_time)
        route_vehicles_needed[r_id], valid_trip_start_time = \
            calc_vehicles_needed_for_route(route_trav_time, service_headways)

    print "Route dists, peak times, hways at peak, trav times in peak, "\
        "avg speed (km/h), and min. vehicles needed:" 
    for r_def in route_defs:
        r_id = r_def.id
        rname = route_segs.get_print_name(r_def)
        print "%s: %s, %.2f min, %05.2fkm, time %s, avespeed %.2f, vehicles %d" %\
            (rname,
            route_peak_time_of_days[r_id],
            route_hways_in_peak[r_id],
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
    parser.add_option('--stops', dest='stops',
        help='Shapefile of stops.')
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
    parser.add_option('--usesegspeeds', dest='usesegspeeds', 
        help='Use per-segment speeds defined in route segments shapefile? '\
            'If false, then will just use a constant speed defined per mode.')
    parser.add_option('--gtfs_speeds_dir', dest='gtfs_speeds_dir',
        help='Path to dir containing extracted speeds per time period from '
            'a GTFS input file.')
    parser.add_option('--per_route_hways', dest='per_route_hways',
        help='An optional file specifying per-route headways in time '\
            'periods.')
    parser.set_defaults(output_csv='route_infos.csv', usesegspeeds='True')
    (options, args) = parser.parse_args()

    if options.stops is None:
        parser.print_help()
        parser.error("No stops shapefile path given.")
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
        parser.error("Service option requested '%s' not in allowed set, "\
            "of %s" % (options.service, allowedServs))
    mode_config = m_t_info.settings[options.service]

    gtfs_speeds_dir = options.gtfs_speeds_dir
    use_seg_speeds = parser_utils.str2bool(options.usesegspeeds)
    use_gtfs_speeds = False
    if gtfs_speeds_dir:
        use_gtfs_speeds = True
        # Override
        use_seg_speeds = False
        gtfs_speeds_dir = os.path.expanduser(gtfs_speeds_dir)
        if not os.path.exists(gtfs_speeds_dir):
            parser.print_help()
            parser.error("GTFS speeds dir given '%s' doesn't exist." \
                % gtfs_speeds_dir)

    if options.per_route_hways:
        per_route_hways_fname = options.per_route_hways
        if not os.path.exists(per_route_hways_fname):
            parser.print_help()
            parser.error("Per-route headways file given '%s' doesn't exist." \
                % per_route_hways)
        per_route_hways, hways_tps = \
            gtfs_ops.read_route_hways_all_routes_all_stops(
                per_route_hways_fname)
    else:
        per_route_hways = None
        hways_tps = None

    seg_speed_model = None
    if use_gtfs_speeds:
        seg_speed_model = \
            seg_speed_models.MultipleTimePeriodsPerRouteSpeedModel(
                gtfs_speeds_dir)        
    elif use_seg_speeds:
        seg_speed_model = seg_speed_models.PerSegmentPeakOffPeakSpeedModel()
    else:
        seg_speed_model = seg_speed_models.ConstantSpeedPerModeModel()

    segs_shp = osgeo.ogr.Open(options.segments)
    segs_lyr = segs_shp.GetLayer(0)
    stops_shp = osgeo.ogr.Open(options.stops)
    stops_lyr = stops_shp.GetLayer(0)
    
    get_all_route_infos(segs_lyr, stops_lyr, options.routes, mode_config,
        seg_speed_model, per_route_hways, hways_tps)
    segs_shp.Destroy()
    stops_shp.Destroy()

if __name__ == "__main__":
    main()
