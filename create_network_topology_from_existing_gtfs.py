#!/usr/bin/env python2
import os
import os.path
import sys
import inspect
import operator
import csv
from optparse import OptionParser

import transitfeed
import osgeo.ogr
from osgeo import ogr, osr

import parser_utils
import topology_shapefile_data_model as tp_model
import route_segs
import mode_timetable_info as m_t_info
import gtfs_ops
import seg_speed_models
from misc_utils import pairs

DELETE_EXISTING = True

def add_all_stops_from_gtfs(schedule, stops_lyr, stops_multipoint):
    print "Adding all stops from GTFS file."
    gtfs_srs = osr.SpatialReference()
    gtfs_srs.ImportFromEPSG(gtfs_ops.GTFS_EPSG)

    gtfs_stop_id_to_stop_id_map = {}

    stop_count = 0
    for row_ii, gtfs_stop in enumerate(schedule.stops.itervalues()):
        stop_pt = ogr.Geometry(ogr.wkbPoint)
        stop_pt.AddPoint(gtfs_stop.stop_lon, gtfs_stop.stop_lat)
        stop_id = tp_model.add_stop(stops_lyr, stops_multipoint,
            tp_model.STOP_TYPE_FROM_EXISTING_GTFS, stop_pt, gtfs_srs,
            gtfs_id=gtfs_stop.stop_id)
        gtfs_stop_id_to_stop_id_map[gtfs_stop.stop_id] = stop_id    
        stop_count += 1
    print "...done adding the %d stops." % stop_count
    return gtfs_stop_id_to_stop_id_map

def calc_seg_refs_for_route(schedule, gtfs_route_id, r_id,
        gtfs_stop_id_to_stop_id_map, seg_distances, route_first_stop_id = None):
    """Calculate all the segments for a full-stop version of the route with
    specified GTFS ID."""
    route_seg_refs = []
    all_pattern_segments = []

    gtfs_route = schedule.routes[gtfs_route_id]
    rname = gtfs_route.route_short_name
    if not rname:
        rname = gtfs_route.route_long_name
    trip_dict = gtfs_route.GetPatternIdTripDict()
    p_keys = trip_dict.keys()

    route_dir_serv_period_pairs = \
        gtfs_ops.extract_route_dir_serv_period_tuples(trip_dict)
    # The use of set() will remove duplicates
    input_route_dirs = list(set(map(operator.itemgetter(0),
        route_dir_serv_period_pairs)))
    # Some routes have >2 headsigns (e.g. that finish mid-way along
    # route in certain trips.
    #assert len(route_dirs) == 2
    master_dir = input_route_dirs[0]

    print 'Calculating full-stop pattern of segments for route id %s, "%s":' \
        % (gtfs_route.route_id, gtfs_ops.get_route_print_name(gtfs_route))
    for trips in trip_dict.itervalues():
        # According to the API, all of these trips in this trip pattern
        # have the same stop pattern. So just look at first one here.
        stop_visit_pattern = trips[0].GetPattern()
        if trips[0].trip_headsign != master_dir:
            # We're only going to worry about one direction.
            # Important for trams and buses that often have stops on
            # opposite sides of the street.
            continue
        
        for seg_i, stop_pair in enumerate(pairs(stop_visit_pattern)):
            stop_a = stop_pair[0]
            stop_b = stop_pair[1]
            first_stop_id = gtfs_stop_id_to_stop_id_map[stop_a.stop_id]
            second_stop_id = gtfs_stop_id_to_stop_id_map[stop_b.stop_id]
            rdist_on_seg = gtfs_ops.get_update_seg_dist_m(seg_distances,
                stop_pair)
            route_segs.add_update_seg_ref(first_stop_id, second_stop_id,
                r_id, rdist_on_seg, all_pattern_segments,
                [])
            
    # (Now all segment pairs for the route are assembled:-)
    # (We now want to find a way to get the 'full-stop' seg pattern for the
    # route - possibly by first excluding express stops.

    seg_links = route_segs.build_seg_links(all_pattern_segments)
    full_stop_pattern_segs = route_segs.get_full_stop_pattern_segs(
        all_pattern_segments, seg_links, route_first_stop_id)

    stop_id_to_gtfs_stop_id_map = {}        
    for gtfs_stop_id, stop_id in gtfs_stop_id_to_stop_id_map.iteritems():
        stop_id_to_gtfs_stop_id_map[stop_id] = gtfs_stop_id
    # Now calculate direction names, based on first and last stops.
    if len(full_stop_pattern_segs) == 1:
        first_stop_id = full_stop_pattern_segs[0].first_id
        last_stop_id = full_stop_pattern_segs[0].second_id
    else:
        first_stop_id = route_segs.find_non_linking_stop_id(
            full_stop_pattern_segs[0], full_stop_pattern_segs[1])
        last_stop_id = route_segs.find_non_linking_stop_id(
            full_stop_pattern_segs[-1], full_stop_pattern_segs[-2])
    first_stop_id_gtfs = stop_id_to_gtfs_stop_id_map[first_stop_id]
    last_stop_id_gtfs = stop_id_to_gtfs_stop_id_map[last_stop_id]
    # Ok :- we now need to find a pattern which starts with each of these
    #   stops, and use that to save the directions.
    #first_stop_name = schedule.stops[first_stop_id_gtfs].stop_name
    #last_stop_name = schedule.stops[last_stop_id_gtfs].stop_name
    #output_route_dirs = (last_stop_name, first_stop_name)
    first_stop_dir = None
    last_stop_dir = None
    min_dist_from_trip_end = sys.maxint
    for trips in trip_dict.itervalues():
        stop_visit_pattern = trips[0].GetPattern()
        trip_stop_ids = map(operator.attrgetter('stop_id'),
            stop_visit_pattern)
        len_trip = len(trip_stop_ids)
        try:
            last_stop_index = trip_stop_ids.index(last_stop_id_gtfs)
        except ValueError:
            continue
        dist_from_trip_end = len(trip_stop_ids) - last_stop_index - 1
        if dist_from_trip_end < min_dist_from_trip_end:
            min_dist_from_trip_end = dist_from_trip_end
            last_stop_dir = trips[0].trip_headsign
        if dist_from_trip_end == 0:
            break
    assert last_stop_dir is not None
    for route_dir in input_route_dirs:
        if route_dir != last_stop_dir:
            first_stop_dir = route_dir
            break
    assert first_stop_dir is not None        
    output_route_dirs = (last_stop_dir, first_stop_dir)
    return full_stop_pattern_segs, output_route_dirs

def get_gtfs_route_ids_in_output_order(routes_dict):
    gtfs_route_id_output_order = []
    temp_route_defs = []
    for route in routes_dict.itervalues():
        # Create a temp route_def
        route_def = route_segs.Route_Def(route.route_id,
            route.route_short_name,
            route.route_long_name, ["", ""], [])
        temp_route_defs.append(route_def)
    temp_route_defs.sort(key=route_segs.get_route_order_key_from_name)
    gtfs_route_id_output_order = map(operator.attrgetter('id'), 
        temp_route_defs)
    return gtfs_route_id_output_order

def get_route_defs_and_segments_from_gtfs(schedule, segments_lyr,
        stops_lyr, gtfs_stop_id_to_stop_id_map, mode_config,
        line_start_stop_info = None):
    """Get all the route segments from an existing GTFS file, to a GIS
    segments layer. Return the list of route_defs describing the routes."""
    route_defs = []
    seg_distances = {}
    route_segments_initial = {}
    all_route_dirs = {}
    
    force_start_stop_ids_by_gtfs_route_id = None
    if line_start_stop_info:
        force_start_stop_ids_by_gtfs_route_id = {}
        r_name_type = line_start_stop_info[1]
        for rname, stop_name in line_start_stop_info[0].iteritems():
            if r_name_type == 'route_long_name':
                r_id, r_info = gtfs_ops.getRouteByLongName(schedule, rname)
            elif r_name_type == 'route_short_name':
                r_id, r_info = gtfs_ops.getRouteByShortName(schedule, rname)
            else:
                print "Error: unrecognised route description keyword in "\
                    "line_start_stop_info ('%s')" % r_name_type
                sys.exit(1)
            if r_id is None:
                print "Warning:- route name specified in line start stop "\
                    "info, '%s', of type '%s', not found in schedule. "\
                    "Skipping." % (rname, r_name_type)
                continue
            gtfs_stop_id, s_info = gtfs_ops.getStopWithName(schedule,
                stop_name)
            if gtfs_stop_id is None:
                print "Warning:- stop name specified in line start stop "\
                    "info, '%s', for route '%s', not found in schedule. "\
                    "Skipping." % (stop_name, rname)
                continue
            first_stop_id = gtfs_stop_id_to_stop_id_map[gtfs_stop_id]
            force_start_stop_ids_by_gtfs_route_id[r_id] = first_stop_id

    # Work out a nice processing order.
    gtfs_route_ids_output_order = get_gtfs_route_ids_in_output_order(
        schedule.routes)

    # Set up a canonical mapping from gtfs route ID to OSSTIP route ID.
    gtfs_route_ids_to_route_ids_map = {}
    for r_id, gtfs_r_id in enumerate(gtfs_route_ids_output_order):
        gtfs_route_ids_to_route_ids_map[gtfs_r_id] = r_id

    # Calculate the segments in the full-stop version of each route.
    for gtfs_route_id in gtfs_route_ids_output_order:
        r_id = gtfs_route_ids_to_route_ids_map[gtfs_route_id]
        gtfs_route = schedule.routes[gtfs_route_id]
        force_first_stop_id = None
        if force_start_stop_ids_by_gtfs_route_id:
            try:
                force_first_stop_id = \
                    force_start_stop_ids_by_gtfs_route_id[gtfs_route_id]
            except KeyError:
                force_first_stop_id = None
        route_seg_refs, route_dirs = calc_seg_refs_for_route(schedule, 
            gtfs_route_id, r_id, gtfs_stop_id_to_stop_id_map, seg_distances,
            force_first_stop_id)
        route_segments_initial[gtfs_route_id] = route_seg_refs
        all_route_dirs[gtfs_route_id] = route_dirs

    # We don't add the segments to GIS persistence until all routes are 
    #  processed, to capture possible commonality between routes
    #  (and thus the final list of segments will be smaller).
    segs_all_routes = []
    for gtfs_route_id in gtfs_route_ids_output_order:
        r_id = gtfs_route_ids_to_route_ids_map[gtfs_route_id]
        gtfs_route = schedule.routes[gtfs_route_id]
        r_short_name = str(gtfs_route.route_short_name)
        r_long_name = str(gtfs_route.route_long_name)
        updated_segs_this_route = []
        for seg in route_segments_initial[gtfs_route_id]:
            route_segs.add_update_seg_ref(seg.first_id, seg.second_id,
                r_id, seg.route_dist_on_seg, segs_all_routes,
                updated_segs_this_route)
        seg_ids = map(operator.attrgetter('seg_id'), updated_segs_this_route)
        route_def = route_segs.Route_Def(r_id, r_short_name, r_long_name, 
            all_route_dirs[gtfs_route_id], seg_ids,
            gtfs_origin_id=gtfs_route_id)
        route_defs.append(route_def)

    return route_defs, segs_all_routes

def parse_line_start_stops_csv_file(line_start_stop_info_csv_fname):
    line_start_stop_dict = {}
    try:
        csv_file = open(line_start_stop_info_csv_fname, 'r')
    except IOError:
        print "Error, line start stop CSV file given, %s , failed to open." \
            % (line_start_stop_info_csv_fname)
        sys.exit(1) 
    reader = csv.reader(csv_file, delimiter=',', quotechar="'") 
    headers = reader.next()
    route_name_type = headers[0]
    if route_name_type not in gtfs_ops.ALLOWED_ROUTE_NAME_TYPES:
        print "Error:- in line start stop info file %s, route type "\
            "specified in column 0 of '%s' not in allowed types list "\
            "%s." % (line_start_stop_info_csv_fname, route_name_type, \
             gtfs_ops.ALLOWED_ROUTE_NAME_TYPES)
        sys.exit(1)     
    for ii, row in enumerate(reader):
        rname = row[0]
        stop_name = row[1]
        line_start_stop_dict[rname] = stop_name
    csv_file.close()
    line_start_stop_info = None
    if len(line_start_stop_dict) >= 1:
        line_start_stop_info = line_start_stop_dict, route_name_type
    return line_start_stop_info

def main():
    allowedServs = ', '.join(sorted(["'%s'" % key for key in \
        m_t_info.settings.keys()]))
    parser = OptionParser()
    parser.add_option('--input_gtfs', dest='inputgtfs',
        help='GTFS zip file to read from. Should end in .zip')
    parser.add_option('--stops', dest='outputstops',
        help='Shapefile of line stops to create.')
    parser.add_option('--segments', dest='outputsegments',
        help='Shapefile of route segments to create.')
    parser.add_option('--routes', dest='outputroutes',
        help='Output file name you want to store CSV of route segments in'\
            ' (suggest should end in .csv)')
    parser.add_option('--service', dest='service',
        help="Should be one of %s" % allowedServs)        
    parser.add_option('--line_start_stops', dest='line_start_stops',
        help="Optional CSV file stating routes that should have the "\
            "full-stop route-building algorithm forced to start at a specific "\
            "stop.")
    (options, args) = parser.parse_args()

    if options.inputgtfs is None:
        parser.print_help()
        parser.error("No input GTFS file path given.")
    if options.outputstops is None:
        parser.print_help()
        parser.error("No output stops shapefile path given.")
    if options.outputsegments is None:
        parser.print_help()
        parser.error("No output segments shapefile path given.")
    if options.outputroutes is None:
        parser.print_help()
        parser.error("No output route definitions CSV file path given.")
    if options.service not in m_t_info.settings:
        parser.print_help()
        parser.error("Service option requested '%s' not in allowed set, of %s" \
            % (options.service, allowedServs))
    mode_config = m_t_info.settings[options.service]

    gtfs_input_fname = options.inputgtfs

    if not os.path.exists(gtfs_input_fname):
        print "Error:- gtfs input file name given doesn't exist (%s)." \
            % gtfs_input_fname
    # The shape files we're going to create :- don't check
    #  existence, just read names.
    stops_shp_file_name = os.path.expanduser(options.outputstops)
    segs_shp_file_name = os.path.expanduser(options.outputsegments)
    route_defs_fname = os.path.expanduser(options.outputroutes)

    accumulator = transitfeed.SimpleProblemAccumulator()
    problemReporter = transitfeed.ProblemReporter(accumulator)

    loader = transitfeed.Loader(gtfs_input_fname, problems=problemReporter)
    print "Loading input schedule from file %s ..." % gtfs_input_fname
    schedule = loader.Load()
    print "... done."

    # TODO:- will need a more advanced speed model in future.
    speed_model = seg_speed_models.PerSegmentPeakOffPeakSpeedModel()
    stops_shp_file, stops_lyr = tp_model.create_stops_shp_file(
        stops_shp_file_name, delete_existing=DELETE_EXISTING,
        gtfs_origin_field=True)
    stops_multipoint = ogr.Geometry(ogr.wkbMultiPoint)
    segments_shp_file, segments_lyr = tp_model.create_segs_shp_file(
        segs_shp_file_name, speed_model, delete_existing=DELETE_EXISTING)

    line_start_stop_info = None
    if options.line_start_stops:
        line_start_stop_info = parse_line_start_stops_csv_file(
            options.line_start_stops)

    # Now read out stops and segments from GTFS :- converting the multiple
    #  patterns per route in GTFS if necessary into a 'full-stop pattern'.
    gtfs_stop_id_to_stop_id_map = add_all_stops_from_gtfs(schedule,
        stops_lyr, stops_multipoint)
    route_defs, all_segs = get_route_defs_and_segments_from_gtfs(schedule,
        segments_lyr, stops_lyr, gtfs_stop_id_to_stop_id_map, mode_config,
        line_start_stop_info)
    # Now write to GIS files.
    route_segs.write_segments_to_shp_file(segments_lyr, stops_lyr,
        all_segs, mode_config)
    route_segs.write_route_defs(route_defs_fname, route_defs)

    # Force a write.
    stops_shp_file.Destroy()
    segments_shp_file.Destroy()
    print "...done writing."
    # Cleanup
    schedule = None
    return

if __name__ == "__main__":
    main()
