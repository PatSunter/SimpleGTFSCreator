#!/usr/bin/env python2

import os
import os.path
import sys
import operator
import glob
import shutil
from optparse import OptionParser

from osgeo import ogr, osr

import misc_utils
import mode_timetable_info as m_t_info
import route_segs
import topology_shapefile_data_model as tp_model
import time_periods_speeds_model as tps_speeds_model

# We don't want to further round down already rounded values.
SPEED_ROUND_PLACES = 10

# (None,'Sunbury'     ,None,'Bacchus Marsh'   ,1218,'Bacchus Marsh'),

def create_new_speed_entries(route_defs, route_ext_specs, segs_lookup_table,
        stop_id_to_gtfs_stop_id_map, stop_id_to_name_map,
        speeds_dir_in, speeds_dir_out):

    if not os.path.exists(speeds_dir_out):
        os.makedirs(speeds_dir_out)

    # Make a reverse map for lookup purposes
    gtfs_stop_id_to_stop_id_map = {}
    for stop_id, gtfs_stop_id in stop_id_to_gtfs_stop_id_map.iteritems():
        gtfs_stop_id_to_stop_id_map[gtfs_stop_id] = stop_id

    routes_processed = {}
    for route_def in route_defs:
        routes_processed[route_def.id] = False
    # Handle the new/extended routes first
    for route_ext_spec in route_ext_specs:
        old_r_s_name = route_ext_spec[0]
        old_r_l_name = route_ext_spec[1]
        ext_r_s_name, ext_r_l_name = route_ext_spec[2], route_ext_spec[3]
        conn_stop_gtfs_id = route_ext_spec[4]
        upd_dir_name = route_ext_spec[5]

        ext_route_spec = route_segs.Route_Def(None, ext_r_s_name, ext_r_l_name,
            None, None)
        ext_routes = route_segs.get_matching_route_defs(route_defs,
            ext_route_spec)
        assert len(ext_routes) == 1
        ext_route = ext_routes[0]

        other_dir_i = 1 - ext_route.dir_names.index(upd_dir_name)
        other_dir_name = ext_route.dir_names[other_dir_i]

        conn_stop_id = gtfs_stop_id_to_stop_id_map[conn_stop_gtfs_id]

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
        conn_seg_ref = ext_r_seg_refs[conn_stop_ii]
        if starting_in_ext_section:
            last_orig_seg_ref = ext_r_seg_refs[conn_stop_ii]
        else:
            last_orig_seg_ref = ext_r_seg_refs[conn_stop_ii-1]
        last_orig_seg = segs_lookup_table[last_orig_seg_ref.seg_id]
        last_orig_seg_gtfs_ids = tp_model.get_gtfs_stop_id_pair_of_segment(
            last_orig_seg, stop_id_to_gtfs_stop_id_map)
        # Stringify
        last_orig_seg_gtfs_ids = tuple(map(str, last_orig_seg_gtfs_ids))

        stop_gtfs_ids_to_names_map = {}
        for s_id in r_stop_ids:
            s_gtfs_id = stop_id_to_gtfs_stop_id_map[s_id]
            s_name = stop_id_to_name_map[s_id]
            stop_gtfs_ids_to_names_map[s_gtfs_id] = s_name

        # Now process all the existing speeds files for this route (or
        #  its old name), and make copies.
        old_route_print_name = misc_utils.routeNameFileReady(
            old_r_s_name, old_r_l_name)
        route_speeds_fnames = glob.glob(
            "%s%s%s-speeds-*-all.csv" % (speeds_dir_in, os.sep, \
                old_route_print_name))
        for route_speeds_fname in route_speeds_fnames:
            fname_sections = os.path.basename(route_speeds_fname).split('-')
            serv_period = fname_sections[2]
            trips_dir_file_ready = fname_sections[3]
            time_periods, route_avg_speeds_in, seg_distances_in = \
                tps_speeds_model.read_route_speed_info_by_time_periods(
                    speeds_dir_in, old_r_s_name, old_r_l_name,
                    serv_period, trips_dir_file_ready, sort_seg_stop_id_pairs=True)
            # Handle the case where the connecting stop isn't included.
            gtfs_stop_pairs_this_file = route_avg_speeds_in.keys()
            shifted_last = 0
            while last_orig_seg_gtfs_ids not in gtfs_stop_pairs_this_file:
                shifted_last += 1
                if starting_in_ext_section:
                    if conn_stop_ii + shifted_last >= len(r_stop_ids)-1:
                        print "Error! We have not found any entries for "\
                            "connecting segment default values."
                        assert 0
                    last_orig_seg_ref = ext_r_seg_refs[conn_stop_ii+shifted_last]
                else:        
                    if conn_stop_ii - shifted_last <= 1:
                        print "Error! We have not found any entries for "\
                            "connecting segment default values."
                        assert 0
                    last_orig_seg_ref = ext_r_seg_refs[conn_stop_ii-1-shifted_last]
                last_orig_seg = segs_lookup_table[last_orig_seg_ref.seg_id]
                last_orig_seg_gtfs_ids = tp_model.get_gtfs_stop_id_pair_of_segment(
                    last_orig_seg, stop_id_to_gtfs_stop_id_map)
                # Stringify
                last_orig_seg_gtfs_ids = tuple(map(str, last_orig_seg_gtfs_ids))
            route_avg_speeds_out = {}
            seg_distances_out = {}
            for s_ii, seg_ref in enumerate(ext_r_seg_refs):
                seg = segs_lookup_table[seg_ref.seg_id]
                seg_gtfs_ids = tp_model.get_gtfs_stop_id_pair_of_segment(
                    seg, stop_id_to_gtfs_stop_id_map)
                seg_gtfs_ids = tuple(map(str, seg_gtfs_ids))
                if (starting_in_ext_section and s_ii < conn_stop_ii) or \
                    (not starting_in_ext_section and s_ii >= conn_stop_ii):
                    # We are in an extended section:- need to copy speeds
                    # of closest existing
                    route_avg_speeds_out[seg_gtfs_ids] = \
                        route_avg_speeds_in[last_orig_seg_gtfs_ids]
                    # And save new seg distance.
                    seg_distances_out[seg_gtfs_ids] = \
                        seg_ref.route_dist_on_seg
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
            # Map to new direction name
            if trips_dir_file_ready == \
                    misc_utils.routeDirStringToFileReady(other_dir_name):
                out_dir = other_dir_name
            else:
                out_dir = upd_dir_name
            out_fname = tps_speeds_model.get_route_avg_speeds_for_dir_period_fname(
                ext_route.short_name, ext_route.long_name,
                serv_period, out_dir)
            out_fpath = os.path.join(speeds_dir_out, out_fname)
            tps_speeds_model.write_avg_speeds_on_segments(
                stop_gtfs_ids_to_names_map,
                route_avg_speeds_out, seg_distances_out,
                time_periods, out_fpath, SPEED_ROUND_PLACES)
        routes_processed[ext_route.id] = True
    # Now copy all remaining route files
    for route_def in route_defs:
        if not routes_processed[route_def.id]:
            route_print_name = misc_utils.routeNameFileReady(
                route_def.short_name, route_def.long_name)
            route_speeds_fnames = glob.glob(
                "%s%s%s-speeds-*-all.csv" % (speeds_dir_in, os.sep, \
                    route_print_name))
            for speeds_fname in route_speeds_fnames:
                shutil.copy(speeds_fname, speeds_dir_out)
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
        
    mode_config = m_t_info.settings[options.service]

    route_defs = route_segs.read_route_defs(options.route_defs)
    fname = os.path.expanduser(options.segments)
    route_segments_shp = ogr.Open(fname, 0)    
    if route_segments_shp is None:
        print "Error, route segments shape file given, %s , failed to open." \
            % (options.segments)
        sys.exit(1)    
    segs_lyr = route_segments_shp.GetLayer(0)
    stops_shp = ogr.Open(options.stops)
    stops_lyr = stops_shp.GetLayer(0)

    # TODO read the route extensions info

    route_ext_specs = [
        (None,'Sunbury'     ,None,'Bacchus Marsh'   ,1218,'Bacchus Marsh'),
        (None,'Cranbourne'  ,None,'Clyde (fmr. Cranbourne)',1045,'Clyde'),
        ]

    # Orig route :- short and long name
    # Ext route :- short and long name
    # (Remember, these could be None according to the spec, in which case,
    #   use originals)
    # Conn stop gtfs id
    # Upd dir name.

    segs_lookup_table = tp_model.build_segs_lookup_table(segs_lyr)
    stop_id_to_gtfs_stop_id_map = tp_model.build_stop_id_to_gtfs_stop_id_map(
        stops_lyr)
    stop_id_to_name_map = tp_model.build_stop_id_to_stop_name_map(stops_lyr)

    create_new_speed_entries(route_defs, route_ext_specs, segs_lookup_table,
        stop_id_to_gtfs_stop_id_map, stop_id_to_name_map,
        options.input_speeds_dir, options.output_speeds_dir)

    # Close the shape files - includes making sure it writes
    route_segments_shp.Destroy()
    route_segments_shp = None

if __name__ == "__main__":
    main()
