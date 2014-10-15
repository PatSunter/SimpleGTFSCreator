#!/usr/bin/env python2
import os
import os.path
import sys
import inspect
import operator
from optparse import OptionParser

import osgeo.ogr
from osgeo import ogr, osr

import route_geom_ops
import topology_shapefile_data_model as tp_model
import route_segs

import mode_timetable_info as m_t_info

DELETE_EXISTING = True
# This skips building very short segments.
#MIN_SEGMENT_LENGTH = 50.0
MIN_SEGMENT_LENGTH = 50.0


def build_multipoint_from_lyr(stops_lyr):
    stops_multipoint = ogr.Geometry(ogr.wkbMultiPoint)
    stops_multipoint.AssignSpatialReference(stops_lyr.GetSpatialRef())
    # Importantly, this will respect filters.
    for stop in stops_lyr:
        stop_geom = stop.GetGeometryRef()
        stops_multipoint.AddGeometry(stop_geom)
    stops_lyr.ResetReading()    
    return stops_multipoint

def reproject_all_multipoint(multipoint, new_srs):
    mpoint_srs = multipoint.GetSpatialReference()
    transform = osr.CoordinateTransformation(mpoint_srs, new_srs)
    for pt_geom in multipoint:
        pt_geom.Transform(transform)
    return

def get_multipoint_within_with_map(multipoint, test_geom):
    """Get a new multipoint, which is the set of points from input
    multipoint, that are within test_geom. Also return an 'intersection
    map' from indices in the returned new mpoint_within, back to
    corresponding point id within original."""
    xmin, xmax, ymin, ymax = test_geom.GetEnvelope()
    mpoint_within = ogr.Geometry(ogr.wkbMultiPoint)
    isect_map = []
    test_geom_srs = test_geom.GetSpatialReference()
    for pt_i, pt_geom in enumerate(multipoint):
        ptx, pty = pt_geom.GetPoint_2D(0)
        # Hand-roll a bbox check to speed up before more expensive Within
        # check.
        if ptx >= xmin and ptx <= xmax \
                and pty >= ymin and pty <= ymax \
                and pt_geom.Within(test_geom):
            mpoint_within.AddGeometry(pt_geom)
            isect_map.append(pt_i)
    return mpoint_within, isect_map

def build_seg_ref_lists(input_routes_lyr, input_stops_lyr):
    all_seg_refs = []
    route_seg_refs = []
    routes_srs = input_routes_lyr.GetSpatialRef()
    stops_srs = input_stops_lyr.GetSpatialRef()
    target_srs = osr.SpatialReference()
    target_srs.ImportFromEPSG(route_geom_ops.COMPARISON_EPSG)

    # First, get a multipoint in right projection.
    stops_multipoint = build_multipoint_from_lyr(input_stops_lyr)
    reproject_all_multipoint(stops_multipoint, target_srs)

    route_transform = osr.CoordinateTransformation(routes_srs, target_srs)

    print "Building route segment ref. infos:"
    for ii, route in enumerate(input_routes_lyr):
        rname = route.GetField(tp_model.ROUTE_NAME_FIELD)
        # TODO: probably should enforce and use an ID field in route shp file,
        #  rather than use this function.
        r_id = tp_model.route_id_from_name(rname)
        #if rname != "R71": continue
        start_cnt = len(all_seg_refs)
        new_segs_cnt = 0
        seg_refs_this_route = []
        # Get the stops of interest along route, we need to 'walk'
        # Do a transform now for comparison purposes - before creating buffer
        route_geom = route.GetGeometryRef()
        route_geom.Transform(route_transform)
        route_length_total = route_geom.Length()
        print "Creating route segments infos for route %s (%.1fm length)" \
            % (rname, route_length_total)

        route_buffer = route_geom.Buffer(
            route_geom_ops.STOP_ON_ROUTE_CHECK_DIST)
        stops_near_route, isect_map = get_multipoint_within_with_map(
            stops_multipoint, route_buffer)
        if stops_near_route.GetGeometryCount() == 0:
            print "Error, no stops detected near route %s while creating "\
                "segments." % rname
            sys.exit()    
        all_stop_is = range(stops_near_route.GetGeometryCount())
        unvisited_stop_is = all_stop_is[:]
        start_coord = route_geom.GetPoint(0)
        current_loc = start_coord
        end_coord = route_geom.GetPoint(route_geom.GetPointCount()-1)
        end_vertex = ogr.Geometry(ogr.wkbPoint)
        end_vertex.AddPoint(*end_coord)

        route_length_processed = 0
        route_remaining = route_length_total
        line_remains = True
        stops_found = 0
        last_stop_i_along_route = None
        last_stop_i_in_route_set = None
        next_stop_i_along_route = None
        next_stop_i_in_route_set = None
        stop_is_to_remove_from_search = []
        last_vertex_i = 0
        skipped_dist = 0
        last_stop_id_before_skipping = None
        while line_remains is True:
            # Pass in all_stop_is here, except the stop we just visited:
            # to allow for possibility of a route that visits the same stop more than once.
            allowed_stop_is = all_stop_is[:]
            if last_stop_i_along_route is not None:
                for si in stop_is_to_remove_from_search:
                    allowed_stop_is.remove(si)

            next_stop_on_route_isect, stop_ii, dist_to_next, last_vertex_i = \
                route_geom_ops.get_next_stop_and_dist(route_geom, current_loc,
                    stops_near_route, allowed_stop_is, last_vertex_i)
            
            if next_stop_on_route_isect is None:
                # No more stops detected - Finish.
                assert len(unvisited_stop_is) == 0
                line_remains = False
                if route_remaining > route_geom_ops.STOP_ON_ROUTE_CHECK_DIST:
                    print "WARNING: for route %s, last stop is %.1fm from "\
                        "end of route (>%.1fm)." % \
                        (rname, route_remaining, \
                        route_geom_ops.STOP_ON_ROUTE_CHECK_DIST)
                if last_stop_i_in_route_set is not None:
                    last_stop_i = isect_map[last_stop_i_in_route_set]
                    last_stop = input_stops_lyr.GetFeature(last_stop_i)
                    try:
                        if last_stop.GetField(tp_model.STOP_TYPE_FIELD) != \
                                tp_model.STOP_TYPE_ROUTE_START_END:
                            print "WARNING: for route %s, last stop found "\
                                "wasn't of type %s." % \
                                (rname, tp_model.STOP_TYPE_ROUTE_START_END)
                    except ValueError:
                        # Legacy stop sets like motorways don't always have
                        # these fields.
                        pass
                break

            next_stop_i_in_route_set = stop_ii
            assert next_stop_i_in_route_set in all_stop_is
            try:
                unvisited_stop_is.remove(stop_ii)
            except ValueError:
                # We have visited a stop for second time. This is ok.
                pass

            if last_stop_i_along_route is None:
                # At the very first stop. Add to stops found list, but
                # can't build a segment yet.
                stops_found += 1
                next_stop_i_along_route = stops_found-1
                last_stop_i_along_route = next_stop_i_along_route
                last_stop_i_in_route_set = next_stop_i_in_route_set
                stop_is_to_remove_from_search.append(next_stop_i_in_route_set)
                if dist_to_next > route_geom_ops.STOP_ON_ROUTE_CHECK_DIST:
                    print "Warning: for route %s, first stop is %.1fm from "\
                        "start of route (>%.1fm)." % \
                        (rname, dist_to_next, \
                        route_geom_ops.STOP_ON_ROUTE_CHECK_DIST)
            else:
                last_stop_i = isect_map[last_stop_i_in_route_set]
                next_stop_i = isect_map[next_stop_i_in_route_set]
                last_stop = input_stops_lyr.GetFeature(last_stop_i)
                next_stop = input_stops_lyr.GetFeature(next_stop_i)
                try:
                    last_stop_id = last_stop.GetField(tp_model.STOP_ID_FIELD)
                    next_stop_id = next_stop.GetField(tp_model.STOP_ID_FIELD)
                except ValueError:
                    print "Error: a stop found on this route ('%s') is "\
                        "missing the ID field in shapefile, '%s'. Check "\
                        "your shapefile has correct fields/values."\
                        % (rname, tp_model.STOP_ID_FIELD)
                    sys.exit(1)    
                if dist_to_next == 0.0:
                    # Two stops on same position (bad). Skip one of them.
                    if last_stop_id_before_skipping == None:
                        last_stop_id_before_skipping = last_stop_id
                    print "..Warning: two stops at same location: "\
                        "stop ids %d and %d (loc on route is %s)- "\
                        "Skipping creating a segment here." %\
                        (last_stop_id, next_stop_id, \
                         next_stop_on_route_isect)
                    stop_is_to_remove_from_search.append(
                        next_stop_i_in_route_set)
                elif (skipped_dist + dist_to_next) < MIN_SEGMENT_LENGTH and \
                        unvisited_stop_is:
                    # Note the second clause above:- if we hit the very last
                    #  stop, don't skip.
                    if last_stop_id_before_skipping == None:
                        last_stop_id_before_skipping = last_stop_id
                    skipped_dist += dist_to_next
                    print "..Note: skipping stop id %d because it is still "\
                        "within min seg length, %.1fm, of last segment stop "\
                        "%d. Dist to last = %.5fm. Dist skipped so far: %.5fm."\
                        "(Loc on route is %s)." %\
                        (next_stop_id, MIN_SEGMENT_LENGTH,
                         last_stop_id_before_skipping, dist_to_next, \
                         skipped_dist, next_stop_on_route_isect)
                    stop_is_to_remove_from_search.append(
                        next_stop_i_in_route_set)
                else:
                    stops_found += 1
                    next_stop_i_along_route = stops_found-1
                    #print "..adding seg b/w stops %02s (id %d) and "\
                    #    "%02s (id %d) (linear length %.1fm)" %\
                    #        (last_stop_i_along_route, last_stop_id,\
                    #         next_stop_i_along_route, next_stop_id,\
                    #         dist_to_next+skipped_dist)
                    #This function will also handle updating the seg_ref lists
                    seg_ref, new_status = route_segs.add_update_seg_ref(
                        last_stop_id, next_stop_id, r_id,
                        dist_to_next+skipped_dist, all_seg_refs,
                        seg_refs_this_route)
                    if new_status:
                        new_segs_cnt += 1
                    last_stop_i_along_route = next_stop_i_along_route
                    last_stop_i_in_route_set = next_stop_i_in_route_set
                    # Set this list to just the stop we just added
                    stop_is_to_remove_from_search = [next_stop_i_in_route_set] 
                    # Reset these guys since we just added a segment.
                    last_stop_id_before_skipping = None
                    skipped_dist = 0
                last_stop.Destroy()
                next_stop.Destroy()
            # Walk ahead.
            current_loc = next_stop_on_route_isect
            route_length_processed += dist_to_next
            route_remaining = route_length_total - route_length_processed
            if route_remaining < -route_geom_ops.STOP_ON_ROUTE_CHECK_DIST:
                print "ERROR: somehow we've gone beyond end of total route"\
                    " length in creating segments. Segs created so far = %d."\
                    " Is there a loop in the route?"\
                    " current loc (may not be source of problems) is %s." %\
                    (len(seg_refs_this_route), current_loc)
                sys.exit(1)
        route_seg_refs.append((r_id,seg_refs_this_route))
        end_cnt = len(all_seg_refs)
        assert (end_cnt - start_cnt) == new_segs_cnt
        print "..Added %d seg refs for this route (%d of which were new)." % \
            (len(seg_refs_this_route), new_segs_cnt)
        if len(seg_refs_this_route) == 0:
            print "*WARNING*:- Just processed a route ('%s') which resulted "\
                "zero segments. Is the route a loop? Suggest checking "\
                "route layer in a GIS package." % rname
        route_buffer.Destroy()
        stops_near_route.Destroy()
        end_vertex.Destroy()
    nroutes = input_routes_lyr.GetFeatureCount()
    total_segs = len(all_seg_refs)
    mean_segs_per_route = total_segs / float(nroutes)
    print "\nAdded %d new seg refs in total for the %d routes (av. %.1f "\
        "segs/route)." % (total_segs, nroutes, mean_segs_per_route)
    input_routes_lyr.ResetReading()
    return all_seg_refs, route_seg_refs

def create_segments(input_routes_lyr, input_stops_lyr, segs_shp_file_name,
        mode_config):
    """Creates all the route segments, from a given set of stops.
    Note: See comments re projections below, it gets a bit tricky in this one."""
    
    stops_srs = input_stops_lyr.GetSpatialRef()

    all_seg_refs, route_seg_refs = build_seg_ref_lists(input_routes_lyr,
        input_stops_lyr)

    print "Writing segment references to shapefile..."
    segs_shp_file, segments_lyr = tp_model.create_segs_shp_file(
        segs_shp_file_name, delete_existing=DELETE_EXISTING)

    # Build lookup table by stop ID into stops layer - for speed
    stops_lookup_dict = tp_model.build_stops_lookup_table(input_stops_lyr)

    for seg_ref in all_seg_refs:
        # look up corresponding stops in lookup table, and build geometry
        stop_feat_a = stops_lookup_dict[seg_ref.first_id]
        stop_feat_b = stops_lookup_dict[seg_ref.second_id]
        seg_geom = ogr.Geometry(ogr.wkbLineString)
        seg_geom.AssignSpatialReference(stops_srs)
        seg_geom.AddPoint(*stop_feat_a.GetGeometryRef().GetPoint(0))
        seg_geom.AddPoint(*stop_feat_b.GetGeometryRef().GetPoint(0))
        seg_ii = tp_model.add_seg_ref_as_feature(
            segments_lyr, seg_ref, seg_geom, mode_config)
        seg_geom.Destroy()
    # Force a write.
    segs_shp_file.Destroy()
    print "...done writing."
    return

if __name__ == "__main__":
    allowedServs = ', '.join(sorted(["'%s'" % key for key in \
        m_t_info.settings.keys()]))
    parser = OptionParser()
    parser.add_option('--routes', dest='inputroutes',
        help='Shapefile of line routes.')
    parser.add_option('--segments', dest='outputsegments',
        help='Shapefile of line segments to create.')
    parser.add_option('--stops', dest='inputstops',
        help='Shapefile of line stops to create.')
    parser.add_option('--service', dest='service',
        help="Should be one of %s" % allowedServs)
    (options, args) = parser.parse_args()    

    if options.inputroutes is None:
        parser.print_help()
        parser.error("No routes shapefile path given.")
    if options.outputsegments is None:
        parser.print_help()
        parser.error("No segments shapefile path given.")
    if options.inputstops is None:
        parser.print_help()
        parser.error("No stops shapefile path given.")
    if options.service is None:
        parser.print_help()
        parser.error("No service option requested. Should be one of %s" \
            % (allowedServs))
    if options.service not in m_t_info.settings:
        parser.print_help()
        parser.error("Service option requested '%s' not in allowed set, of %s" \
            % (options.service, allowedServs))

    mode_config = m_t_info.settings[options.service]

    routes_fname = os.path.expanduser(options.inputroutes)
    input_routes_shp = osgeo.ogr.Open(routes_fname, 0)
    if input_routes_shp is None:
        print "Error, input routes shape file given, %s , failed to open." \
            % (options.inputroutes)
        sys.exit(1)
    input_routes_lyr = input_routes_shp.GetLayer(0)    
    routes_shp = osgeo.ogr.Open(routes_fname, 0)

    stops_fname = os.path.expanduser(options.inputstops)
    stops_shp = osgeo.ogr.Open(stops_fname, 0)
    if stops_shp is None:
        print "Error, newly created stops shape file, %s , failed to open." \
            % (stops_shp_file_name)
        sys.exit(1)
    stops_lyr = stops_shp.GetLayer(0)   

    # The other shape files we're going to create :- so don't check
    #  existence, just read names.
    segments_fname = os.path.expanduser(options.outputsegments)

    create_segments(input_routes_lyr, stops_lyr,
        segments_fname, mode_config)

    # Cleanup
    input_routes_shp.Destroy()
    stops_shp.Destroy()    
