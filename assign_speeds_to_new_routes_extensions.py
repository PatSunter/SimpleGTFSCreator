#!/usr/bin/env python2

import os
import os.path
import sys
import operator
from optparse import OptionParser

from osgeo import ogr, osr

import misc_utils
import mode_timetable_info as m_t_info
import route_segs
import seg_speed_models
import topology_shapefile_data_model as tp_model
import time_periods_speeds_model as tps_speeds_model

# We don't want to further round down already rounded values.
SPEED_ROUND_PLACES = 10

def get_orig_route_gtfs_pair_with_speeds_nearest(
        orig_route_gtfs_stop_pairs_w_speeds, starting_in_ext_section,
        ext_r_seg_refs, last_orig_seg_ref_ii, dir_index,
        stop_id_to_gtfs_stop_id_map, stop_id_to_name_map):
    # Handle the case where the last orig segment doesn't have speed 
    # entries in this current file.
    seg_ref_ii_to_try = last_orig_seg_ref_ii
    shifted_last = 0
    while True:
        stop_ids_ordered = route_segs.get_stop_ids_in_travel_dir(
            ext_r_seg_refs, seg_ref_ii_to_try, dir_index)

        closest_gtfs_ids_to_last_orig_seg = tp_model.get_gtfs_stop_ids(
            stop_ids_ordered, stop_id_to_gtfs_stop_id_map, to_str=True)
        if closest_gtfs_ids_to_last_orig_seg in \
                orig_route_gtfs_stop_pairs_w_speeds:
            # Good have found best speeds entries to use.
            break
        print "\t\tWarning:- couldn't get speed for calc. last "\
            "original seg ii %d, from stop ids %s ('%s' to '%s'), "\
            "shifting back along route by 1."\
            % (seg_ref_ii_to_try, stop_ids_ordered,\
               stop_id_to_name_map[stop_ids_ordered[0]],\
               stop_id_to_name_map[stop_ids_ordered[1]])
        shifted_last += 1
        if starting_in_ext_section:
            seg_ref_ii_to_try += shifted_last
            if seg_ref_ii_to_try >= len(ext_r_seg_refs)-1:
                return None
        else:        
            seg_ref_ii_to_try -= shifted_last
            if seg_ref_ii_to_try < 0:
                return None
    return closest_gtfs_ids_to_last_orig_seg

def create_new_speed_entries(route_defs, route_ext_defs, segs_lookup_table,
        stop_id_to_gtfs_stop_id_map, stop_id_to_name_map,
        speeds_dir_in, speeds_dir_out, speed_func, mode_config):

    if not os.path.exists(speeds_dir_out):
        os.makedirs(speeds_dir_out)

    # Make a reverse map for lookup purposes
    gtfs_stop_id_to_stop_id_map = {}
    for stop_id, gtfs_stop_id in stop_id_to_gtfs_stop_id_map.iteritems():
        gtfs_stop_id_to_stop_id_map[str(gtfs_stop_id)] = stop_id

    routes_processed = {}
    for route_def in route_defs:
        routes_processed[route_def.id] = False

    print "Creating per-time period speed entries for the %d new/extended "\
        "routes:" % len(route_ext_defs)
    # Handle the new/extended routes first
    for route_ext_def in route_ext_defs:
        old_r_s_name = route_ext_def.exist_r_short_name
        old_r_l_name = route_ext_def.exist_r_long_name
        ext_r_s_name = route_ext_def.upd_r_short_name
        ext_r_l_name = route_ext_def.upd_r_long_name
        
        print "\tProcessing new/extended route %s,\n\t  copying "\
            "pre-existing seg speeds from route %s" \
            % (misc_utils.get_route_print_name(ext_r_s_name, ext_r_l_name), \
               misc_utils.get_route_print_name(old_r_s_name, old_r_l_name))
               
        route_speeds_fnames = tps_speeds_model.get_avg_speeds_fnames(
            speeds_dir_in, old_r_s_name, old_r_l_name)
        assert len(route_speeds_fnames) >= 1

        conn_stop_gtfs_id = route_ext_def.exist_r_connect_stop_gtfs_id
        upd_dir_name = route_ext_def.upd_dir_name

        ext_route_spec = route_segs.Route_Def(None, ext_r_s_name, ext_r_l_name,
            None, None)
        ext_routes = route_segs.get_matching_route_defs(route_defs,
            ext_route_spec)
        assert len(ext_routes) == 1
        ext_route = ext_routes[0]

        other_dir_i = 1 - ext_route.dir_names.index(upd_dir_name)
        other_dir_name = ext_route.dir_names[other_dir_i]

        conn_stop_id = gtfs_stop_id_to_stop_id_map[str(conn_stop_gtfs_id)]

        ext_r_seg_refs = route_segs.create_ordered_seg_refs_from_ids(
            ext_route.ordered_seg_ids, segs_lookup_table)
        r_stop_ids = route_segs.extract_stop_list_along_route(ext_r_seg_refs)

        # Get info about the connecting stop, segment.
        conn_stop_ii = r_stop_ids.index(conn_stop_id)
        if upd_dir_name == ext_route.dir_names[0]:
            starting_in_ext_section = False
            assert conn_stop_ii >= 1
        if upd_dir_name == ext_route.dir_names[1]:
            starting_in_ext_section = True
            assert conn_stop_ii < len(r_stop_ids) - 1
        if starting_in_ext_section:
            last_orig_seg_ref_ii = conn_stop_ii
        else:
            last_orig_seg_ref_ii = conn_stop_ii - 1

        if not speed_func:
            last_orig_seg_ref = ext_r_seg_refs[last_orig_seg_ref_ii]
            last_orig_seg = segs_lookup_table[last_orig_seg_ref.seg_id]
            last_orig_seg_gtfs_ids = tp_model.get_gtfs_stop_id_pair_of_segment(
                last_orig_seg, stop_id_to_gtfs_stop_id_map)
            # Stringify
            last_orig_seg_gtfs_ids = tuple(map(str, last_orig_seg_gtfs_ids))
            last_seg_stop_name_a = stop_id_to_name_map[\
                last_orig_seg_ref.first_id]
            last_seg_stop_name_b = stop_id_to_name_map[\
                last_orig_seg_ref.second_id]
            print "\t...calculated ideal last original segment to copy speeds "\
                "from\n\t  is b/w stops '%s' and '%s'." \
                % (last_seg_stop_name_a, last_seg_stop_name_b)

        stop_gtfs_ids_to_names_map = {}
        for s_id in r_stop_ids:
            s_gtfs_id = stop_id_to_gtfs_stop_id_map[s_id]
            s_name = stop_id_to_name_map[s_id]
            stop_gtfs_ids_to_names_map[s_gtfs_id] = s_name

        # Now process all the existing speeds files for this route (or
        #  its old name), and make copies.
        for route_speeds_fname in route_speeds_fnames:
            name_a, name_b, trips_dir_file_ready, serv_period = \
                tps_speeds_model.get_info_from_fname(route_speeds_fname,
                    old_r_s_name, old_r_l_name)

            # First step is to work out the direction mapping from speeds
            #  file to new route def, given we replaced one of the dirs.
            if trips_dir_file_ready == \
                    misc_utils.routeDirStringToFileReady(other_dir_name):
                working_dir_name = other_dir_name
            else:
                working_dir_name = upd_dir_name    
            print "\t  creating file for new dir/period '%s', '%s' "\
                % (working_dir_name, serv_period)

            if misc_utils.routeDirStringToFileReady(working_dir_name) \
                    != trips_dir_file_ready:    
                print "\t   (from old dir file '%s'):"\
                    % (trips_dir_file_ready)
            time_periods, route_avg_speeds_in, seg_distances_in, null = \
                tps_speeds_model.read_route_speed_info_by_time_periods(
                    speeds_dir_in, name_a, name_b,
                    serv_period, trips_dir_file_ready,
                    sort_seg_stop_id_pairs=False)

            # We need to calc connecting stop order here, as looking it up 
            #  from speeds file depends on direction of travel.
            dir_index = ext_route.dir_names.index(working_dir_name)

            last_orig_seg_gtfs_ids_in_dir = None
            if not speed_func:
                gtfs_stop_pairs_this_file = route_avg_speeds_in.keys()
                last_orig_seg_gtfs_ids_in_dir = \
                    get_orig_route_gtfs_pair_with_speeds_nearest(
                        gtfs_stop_pairs_this_file, starting_in_ext_section,
                        ext_r_seg_refs, last_orig_seg_ref_ii, dir_index,
                        stop_id_to_gtfs_stop_id_map, stop_id_to_name_map)
                if not last_orig_seg_gtfs_ids_in_dir:
                    print "Error! We have not found any entries for "\
                        "connecting segment default values."

            route_avg_speeds_out = {}
            seg_distances_out = {}
            for seg_ii, seg_ref in enumerate(ext_r_seg_refs):
                # Now order the stops in direction of travel and get GTFS IDs
                stop_ids_ordered = route_segs.get_stop_ids_in_travel_dir(
                    ext_r_seg_refs, seg_ii, dir_index)
                seg_gtfs_ids = tp_model.get_gtfs_stop_ids(stop_ids_ordered,
                    stop_id_to_gtfs_stop_id_map, to_str=True)
                if (starting_in_ext_section and seg_ii < conn_stop_ii) or \
                    (not starting_in_ext_section and seg_ii >= conn_stop_ii):
                    # We are in an extended section:- 
                    # save new seg distance.
                    seg_distances_out[seg_gtfs_ids] = \
                        seg_ref.route_dist_on_seg
                    if not speed_func:
                        # copy speeds of closest existing
                        route_avg_speeds_out[seg_gtfs_ids] = \
                            route_avg_speeds_in[last_orig_seg_gtfs_ids_in_dir]
                    else:
                        ext_segment = segs_lookup_table[seg_ref.seg_id]
                        new_calc_speeds = []
                        for tp in time_periods:
                            new_calc_speed = speed_func(ext_segment, tp, mode_config)
                            new_calc_speeds.append(new_calc_speed)
                        route_avg_speeds_out[seg_gtfs_ids] = \
                            new_calc_speeds
                else:
                    # Normal section :- just copy entries from previous.
                    try:
                        route_avg_speeds_out[seg_gtfs_ids] = \
                            route_avg_speeds_in[seg_gtfs_ids]
                        seg_distances_out[seg_gtfs_ids] = \
                            seg_distances_in[seg_gtfs_ids]
                    except KeyError:    
                        # The file we are reading mightn't have a value for this
                        # segment (stop pair) in this time period, given GTFS
                        # origin. If so, we just don't copy.
                        pass
            # write out these new speeds to new file
            out_fname = \
                tps_speeds_model.get_route_avg_speeds_for_dir_period_fname(
                    ext_route.short_name, ext_route.long_name,
                    serv_period, working_dir_name)
            out_fpath = os.path.join(speeds_dir_out, out_fname)
            tps_speeds_model.write_avg_speeds_on_segments(
                stop_gtfs_ids_to_names_map,
                route_avg_speeds_out, seg_distances_out,
                time_periods, out_fpath, SPEED_ROUND_PLACES)
        routes_processed[ext_route.id] = True
    n_reg_routes = sum([1 if p==False else 0 for p in \
        routes_processed.values()])
    assert n_reg_routes + len(route_ext_defs) == len(routes_processed)
    print "Now copying per-time period speed entries for the remaining %d "\
        "regular routes." % (n_reg_routes)
    # Now copy all remaining route files
    for route_def in route_defs:
        if not routes_processed[route_def.id]:
            tps_speeds_model.copy_route_speeds(route_def.short_name,
                route_def.long_name, speeds_dir_in, speeds_dir_out)
    print "...done."
    return

def main():
    allowedServs = ', '.join(sorted(["'%s'" % key for key in \
        m_t_info.settings.keys()]))
    parser = OptionParser()
    parser.add_option('--route_defs', dest='route_defs', 
        help='CSV file listing name, directions, and segments of each route.')
    parser.add_option('--segments', dest='segments',
        help='Shapefile of line segments.')
    parser.add_option('--stops', dest='stops',
        help='Shapefile of stops.')
    parser.add_option('--route_extensions', dest='route_extensions', 
        help='Shapefile containing info about route extensions.')
    parser.add_option('--service', dest='service',
        help="Should be one of %s" % allowedServs)
    parser.add_option('--input_speeds_dir', dest='input_speeds_dir', 
        help='Path in which to read input speeds files.')
    parser.add_option('--output_speeds_dir', dest='output_speeds_dir', 
        help='Path in which to create output speeds files.')
    parser.add_option('--speed_func', dest='speed_func',
        help='(Optional) speed function to use to set speeds in '\
            'network extensions (otherwise the extension approach used.)')
    (options, args) = parser.parse_args()

    if options.segments is None:
        parser.print_help()
        parser.error("No segments shapefile path given.")
    if options.service is None:
        parser.print_help()
        parser.error("No service option requested. Should be one of %s" \
            % (m_t_info.settings.keys()))
    if options.service not in m_t_info.settings:
        parser.print_help()
        parser.error("Service option requested '%s' not in allowed set, of %s" \
            % (options.service, m_t_info.settings.keys()))
    if options.speed_func:
        try:
            speed_func = \
                seg_speed_models.SPEED_FUNCS_REGISTER[options.speed_func]
        except KeyError:
            parser.print_help()
            parser.error("Speed func requested '%s' not in register of "
                "available speed funcs, which are %s" \
                % (options.speed_func, \
                   seg_speed_models.SPEED_FUNCS_REGISTER.keys()))
    else:
        speed_func = None

    mode_config = m_t_info.settings[options.service]

    route_defs = route_segs.read_route_defs(options.route_defs)

    segs_lyr, segs_shp = tp_model.open_check_shp_lyr(
        options.segments, "route segments")
    stops_lyr, stops_shp = tp_model.open_check_shp_lyr(
        options.stops, "route stops")
    route_exts_lyr, route_exts_shp = tp_model.open_check_shp_lyr(
        options.route_extensions, "route extension geometries and specs")

    route_ext_defs = route_segs.read_route_ext_infos(route_exts_lyr)
    segs_lookup_table = tp_model.build_segs_lookup_table(segs_lyr)
    stop_id_to_gtfs_stop_id_map = tp_model.build_stop_id_to_gtfs_stop_id_map(
        stops_lyr)
    stop_id_to_name_map = tp_model.build_stop_id_to_stop_name_map(stops_lyr)

    create_new_speed_entries(route_defs, route_ext_defs, segs_lookup_table,
        stop_id_to_gtfs_stop_id_map, stop_id_to_name_map,
        options.input_speeds_dir, options.output_speeds_dir,
        speed_func, mode_config)

    # Close the shape files
    segs_shp.Destroy()
    stops_shp.Destroy()
    route_exts_shp.Destroy()

if __name__ == "__main__":
    main()
