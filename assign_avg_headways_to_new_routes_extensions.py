#!/usr/bin/env python2

import os
import os.path
import sys
import operator
import itertools
import copy
from datetime import timedelta
from optparse import OptionParser

from osgeo import ogr, osr

import misc_utils
import parser_utils
import route_segs
import topology_shapefile_data_model as tp_model
import time_periods_hways_model as tps_hways_model

# We don't want to further round down already rounded values.
HEADWAY_ROUND_PLACES = 10

def create_new_avg_headway_entries(
        route_defs, route_ext_defs,
        input_hways_fname, output_hways_fname,
        serv_periods, time_window_start, time_window_end, def_headway):

    avg_hways_all_stops_in, tps, r_ids_to_names_map = \
        tps_hways_model.read_route_hways_all_routes_all_stops(input_hways_fname)

    avg_hways_all_stops_out = copy.deepcopy(avg_hways_all_stops_in)

    null_hways = [-1] * len(tps)
    def_hways_in_tps_out = tps_hways_model.decrease_hways_to_max_in_window(
        null_hways, tps, def_headway, time_window_start, time_window_end)

    for route_ext_def in route_ext_defs:
        old_r_s_name = route_ext_def.exist_r_short_name
        old_r_l_name = route_ext_def.exist_r_long_name
        ext_r_s_name = route_ext_def.upd_r_short_name
        ext_r_l_name = route_ext_def.upd_r_long_name

        # Need to get the gtfs route ID, and names, of the old route.
        old_gtfs_r_id = None
        old_r_s_name_found, old_r_l_name_found = None, None
        for r_id, r_name_pair in r_ids_to_names_map.iteritems():
            if (old_r_s_name or old_r_l_name) and \
                  (not old_r_s_name or old_r_s_name == r_name_pair[0]) \
                   and (not old_r_l_name or old_r_l_name == r_name_pair[1]):
                old_gtfs_r_id = r_id
                old_r_s_name_found = r_name_pair[0]
                old_r_l_name_found = r_name_pair[1]
                break
        assert old_gtfs_r_id

        ext_route_spec = route_segs.Route_Def(None, ext_r_s_name, ext_r_l_name,
            None, None)
        ext_routes = route_segs.get_matching_route_defs(route_defs,
            ext_route_spec)
        assert len(ext_routes) == 1
        ext_route = ext_routes[0]

        ext_gtfs_r_id = ext_route.gtfs_origin_id
        r_s_name_out = ext_r_s_name
        r_l_name_out = ext_r_l_name
        if not r_s_name_out:
            r_s_name_out = old_r_s_name_found
        if not r_l_name_out:
            r_l_name_out = old_r_l_name_found
        r_ids_to_names_map[ext_gtfs_r_id] = (r_s_name_out, r_l_name_out)

        if route_ext_def.ext_type == tp_model.ROUTE_EXT_TYPE_EXTENSION:
            upd_dir_name = route_ext_def.upd_dir_name
            other_new_dir_i = 1 - ext_route.dir_names.index(upd_dir_name)
            other_dir_name = ext_route.dir_names[other_new_dir_i]
            old_dpps = avg_hways_all_stops_in[old_gtfs_r_id].keys()
            old_serv_periods = list(set(map(operator.itemgetter(1), old_dpps)))
            old_dir_names = list(set(map(operator.itemgetter(0), old_dpps)))
            rep_i = 1 - old_dir_names.index(other_dir_name)
            replaced_dir_name = old_dir_names[rep_i]
            avg_hways_all_stops_out[ext_gtfs_r_id] = {}
            for serv_period in old_serv_periods:
                dpp_1 = (other_dir_name, serv_period)
                avg_hways_all_stops_out[ext_gtfs_r_id][dpp_1] = \
                    avg_hways_all_stops_in[old_gtfs_r_id][dpp_1]
                dpp_2_new = (upd_dir_name, serv_period)
                dpp_2_old = (replaced_dir_name, serv_period)
                avg_hways_all_stops_out[ext_gtfs_r_id][dpp_2_new] = \
                    avg_hways_all_stops_in[old_gtfs_r_id][dpp_2_old]
        else:
            avg_hways_all_stops_out[ext_gtfs_r_id] = {}
            dir_period_pairs_needed = itertools.product(ext_route.dir_names,
                serv_periods)
            for dir_period_pair in dir_period_pairs_needed:
                avg_hways_all_stops_out[ext_gtfs_r_id][dir_period_pair] = \
                    def_hways_in_tps_out

    tps_hways_model.write_route_hways_all_routes_all_stops(r_ids_to_names_map,
        tps, avg_hways_all_stops_out, output_hways_fname,
        round_places=HEADWAY_ROUND_PLACES)
    return

def main():
    parser = OptionParser()
    parser.add_option('--route_defs', dest='route_defs', 
        help='CSV file listing name, directions, and segments of each route.')
    parser.add_option('--route_extensions', dest='route_extensions', 
        help='Shapefile containing info about route extensions.')
    parser.add_option('--input_hways', dest='input_hways',
        help='File to read input headway for routes from.')
    parser.add_option('--output_hways', dest='output_hways',
        help='File to save output headway for routes to.')
    parser.add_option('--def_headway', dest='def_headway',
        help='Maximum headway allowed in time window (minutes).')
    parser.add_option('--serv_periods', dest='serv_periods',
        help='Comma-separated list of time periods to apply the default '\
            'headway to.')
    parser.add_option('--time_window_start', dest='time_window_start',
        help='Start of the time window to apply default headways for new routes. '\
            'Format needs to be HH:MM, e.g. 04:30 . Times after midnight '\
            'of the service day should be > 24, e.g. 25:00 for 1AM after '\
            'first service day.')
    parser.add_option('--time_window_end', dest='time_window_end',
        help='End of the time window to apply default headways for new routes. '\
            'Same format as time window start.')
    (options, args) = parser.parse_args()

    if options.input_hways is None:
        parser.print_help()
        parser.error("No input headways file given.") 
    if options.output_hways is None:
        parser.print_help()
        parser.error("No output headways file specified.") 
    if options.def_headway is None:
        parser.print_help()
        parser.error("No default headway to apply specified.")
    if options.serv_periods is None:
        parser.print_help()
        parser.error("No set of services periods to modify specified.")
    if options.time_window_start is None:
        parser.print_help()
        parser.error("No time window start specified.")
    if options.time_window_end is None:
        parser.print_help()
        parser.error("No time window end specified.")

    def_headway = float(options.def_headway)
    if def_headway <= 0:
        parser.print_help()
        parser.error("Bad value of default headway given, should be"\
            "> zero.")

    serv_periods = options.serv_periods.split(',')

    try:
        time_window_start = parser_utils.td_str_to_td(options.time_window_start)
    except ValueError:
        parser.print_help()
        parser.error("Bad value of time_window_start given %s, "\
            "see help above for correct format." % options.time_window_start)
    try:
        time_window_end = parser_utils.td_str_to_td(options.time_window_end)
    except ValueError:
        parser.print_help()
        parser.error("Bad value of time_window_end given %s, "\
            "see help above for correct format." % options.time_window_end)
    if time_window_start < timedelta(0):
        parser.print_help()
        parser.error("Bad value of time_window_start given %s, "\
            "it must be > 00:00." % options.time_window_start)
    if time_window_end <= time_window_start:
        parser.print_help()
        parser.error("Bad value of time_window_end given %s, "\
            "it must be > time_window_start." % options.time_window_end)

    input_hways_fname = options.input_hways
    if not os.path.exists(input_hways_fname):
        parser.print_help()
        parser.error("Bad value of input route headways given, "\
            "does not exist.")

    output_hways_fname = options.output_hways
    if not os.path.exists(os.path.basename(output_hways_fname)):
        os.makedirs(os.path.basename(output_hways_fname))

    route_defs = route_segs.read_route_defs(options.route_defs)
    route_exts_lyr, route_exts_shp = tp_model.open_check_shp_lyr(
        options.route_extensions, "route extension geometries and specs")
    route_ext_defs = route_segs.read_route_ext_infos(route_exts_lyr)

    create_new_avg_headway_entries(
        route_defs, route_ext_defs,
        input_hways_fname, output_hways_fname,
        serv_periods, time_window_start, time_window_end, def_headway)
        
    # Close the shape files
    route_exts_shp.Destroy()

if __name__ == "__main__":
    main()
