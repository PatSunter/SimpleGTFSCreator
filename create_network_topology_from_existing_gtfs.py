#!/usr/bin/env python2
import os
import os.path
import sys
import inspect
import operator
from optparse import OptionParser

import osgeo.ogr
from osgeo import ogr, osr

import transitfeed

import parser_utils
import topology_shapefile_data_model as tp_model
import route_segs
import mode_timetable_info as m_t_info
import gtfs_ops
from misc_utils import pairs

DELETE_EXISTING = True

# GTFS stop coordinates are geographic lat-lons
GTFS_STOPS_EPSG = 4326

def add_all_stops_from_gtfs(schedule, stops_lyr, stops_multipoint):
    print "Adding all stops from GTFS file."
    gtfs_srs = osr.SpatialReference()
    gtfs_srs.ImportFromEPSG(GTFS_STOPS_EPSG)

    gtfs_stop_id_to_stop_id_map = {}

    stop_count = 0
    for row_ii, gtfs_stop in enumerate(schedule.stops.itervalues()):
        stop_pt = ogr.Geometry(ogr.wkbPoint)
        stop_pt.AddPoint(gtfs_stop.stop_lon, gtfs_stop.stop_lat)
        stop_id = tp_model.add_stop(stops_lyr, stops_multipoint,
            tp_model.STOP_TYPE_FROM_EXISTING_GTFS, stop_pt, gtfs_srs)
        gtfs_stop_id_to_stop_id_map[gtfs_stop.stop_id] = stop_id    
        stop_count += 1
    print "...done adding the %d stops." % stop_count
    return gtfs_stop_id_to_stop_id_map

def calc_seg_refs_for_route(schedule, gtfs_route_id,
        gtfs_stop_id_to_stop_id_map, seg_distances):
    """Calculate all the segments for a full-stop version of the route with
    specified GTFS ID."""
    route_seg_refs = []
    all_pattern_segments = []

    gtfs_route = schedule.routes[gtfs_route_id]
    rname = gtfs_route.route_short_name
    if not rname:
        rname = gtfs_route.route_long_name
    str(rname)
    trip_dict = gtfs_route.GetPatternIdTripDict()
    p_keys = trip_dict.keys()

    route_dir_serv_period_pairs = \
        gtfs_ops.extract_route_dir_serv_period_tuples(trip_dict)

    print "Calculating full-stop pattern of segments for route %s:" \
        % rname
    for p_ii, p_key in enumerate(p_keys):
        trips = trip_dict[p_keys[p_ii]]
        # According to the API, all of these trips in this trip pattern
        # have the same stop pattern. So just look at first one here.
        stop_visit_pattern = trips[0].GetPattern()
        
        for seg_i, stop_pair in enumerate(pairs(stop_visit_pattern)):
            stop_a = stop_pair[0]
            stop_b = stop_pair[1]
            first_stop_id = gtfs_stop_id_to_stop_id_map[stop_a.stop_id]
            second_stop_id = gtfs_stop_id_to_stop_id_map[stop_b.stop_id]
            rdist_on_seg = gtfs_ops.get_update_seg_dist_m(seg_distances,
                stop_pair)
            route_segs.add_update_seg_ref(first_stop_id, second_stop_id,
                rname, rdist_on_seg, all_pattern_segments,
                [])
            
    # (Now all segment pairs for the route are assembled:-)
    # (We now want to find a way to get the 'full-stop' seg pattern for the
    # route - possibly by first excluding express stops.

    seg_links = route_segs.build_seg_links(all_pattern_segments)
    full_stop_pattern_seg_links = route_segs.get_full_stop_pattern_segs(
        all_pattern_segments, seg_links)

    # TODO: these route_dirs a bit problematic ...
    # The use of set() will remove duplicates
    route_dirs = list(set(map(operator.itemgetter(0),
        route_dir_serv_period_pairs)))
    assert len(route_dirs) == 2
    # HACK!
    master_dir = route_dirs[0]
    route_dirs = (master_dir, route_dirs[1-route_dirs.index(master_dir)])
    return full_stop_pattern_seg_links, route_dirs

def add_route_segments_from_gtfs(schedule, segments_lyr,
        stops_lyr, gtfs_stop_id_to_stop_id_map, mode_config):
    """Add all the route segments from an existing GTFS file, to a GIS
    segments layer. Return the list of route_defs describing the routes."""
    route_defs = []
    seg_distances = {}
    route_segments_initial = {}
    all_route_dirs = {}
    
    # Calculate the segments in the full-stop version of each route.
    for gtfs_route_id, gtfs_route in schedule.routes.iteritems():
        route_seg_refs, route_dirs = calc_seg_refs_for_route(schedule, 
            gtfs_route_id, gtfs_stop_id_to_stop_id_map, seg_distances)
        route_segments_initial[gtfs_route_id] = route_seg_refs
        all_route_dirs[gtfs_route_id] = route_dirs

    # We don't add the segments to GIS persistence until all routes are 
    #  processed, to capture possible commonality between routes
    #  (and thus the final list of segments will be smaller).
    
    segs_all_routes = []
    for gtfs_route_id, gtfs_route in schedule.routes.iteritems():
        rname = gtfs_route.route_short_name
        if not rname:
            rname = gtfs_route.route_long_name
        # OGR doesn't like writing unicode Python, so stringify here.
        rname = str(rname)
        updated_segs_this_route = []
        for seg in route_segments_initial[gtfs_route_id]:
            route_segs.add_update_seg_ref(seg.first_id, seg.second_id,
                rname, seg.route_dist_on_seg, segs_all_routes,
                updated_segs_this_route)
        route_def = route_segs.Route_Def(rname, 
            all_route_dirs[gtfs_route_id],
            map(operator.attrgetter('seg_id'), updated_segs_this_route))
        route_defs.append(route_def)

    # now add the refined list of segments to the shapefile.
    print "Writing segment references to shapefile..."
    # Build lookup table by stop ID into stops layer - for speed
    stops_srs = stops_lyr.GetSpatialRef()
    stops_lookup_dict = tp_model.build_stops_lookup_table(stops_lyr)
    for seg_ref in segs_all_routes:
        # look up corresponding stops in lookup table, and build geometry
        stop_feat_a = stops_lookup_dict[seg_ref.first_id]
        stop_feat_b = stops_lookup_dict[seg_ref.second_id]
        seg_geom = ogr.Geometry(ogr.wkbLineString)
        seg_geom.AssignSpatialReference(stops_srs)
        seg_geom.AddPoint(*stop_feat_a.GetGeometryRef().GetPoint(0))
        seg_geom.AddPoint(*stop_feat_b.GetGeometryRef().GetPoint(0))
        tp_model.add_seg_ref_as_feature( segments_lyr, seg_ref,
            seg_geom, mode_config)
        seg_geom.Destroy()

    return route_defs

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

    stops_shp_file, stops_lyr = tp_model.create_stops_shp_file(
        stops_shp_file_name, delete_existing=DELETE_EXISTING)
    stops_multipoint = ogr.Geometry(ogr.wkbMultiPoint)
    segments_shp_file, segments_lyr = tp_model.create_segs_shp_file(
        segs_shp_file_name, delete_existing=DELETE_EXISTING)

    gtfs_stop_id_to_stop_id_map = add_all_stops_from_gtfs(schedule,
        stops_lyr, stops_multipoint)
    route_defs = add_route_segments_from_gtfs(schedule, segments_lyr,
        stops_lyr, gtfs_stop_id_to_stop_id_map, mode_config)
    # Force a write.
    stops_shp_file.Destroy()
    segments_shp_file.Destroy()
    print "...done writing."

    route_segs.write_route_defs(route_defs_fname, route_defs)

    # Cleanup
    schedule = None
    return

if __name__ == "__main__":
    main()
