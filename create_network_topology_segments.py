#!/usr/bin/env python2
import os
import os.path
import sys
import inspect
import operator
from optparse import OptionParser

import osgeo.ogr
from osgeo import ogr, osr

import project_onto_line as lineargeom
import topology_shapefile_data_model as tp_model
import route_segs

import mode_timetable_info as m_t_info

COMPARISON_EPSG = 28355

DELETE_EXISTING = True

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
    target_srs.ImportFromEPSG(COMPARISON_EPSG)

    # First, get a multipoint in right projection.
    stops_multipoint = build_multipoint_from_lyr(input_stops_lyr)
    reproject_all_multipoint(stops_multipoint, target_srs)

    route_transform = osr.CoordinateTransformation(routes_srs, target_srs)

    print "Building route segment ref. infos:"
    for ii, route in enumerate(input_routes_lyr):
        rname = route.GetField(0)
        start_cnt = len(all_seg_refs)
        new_segs_cnt = 0
        seg_refs_this_route = []
        print "Creating route segments infos for route %s" % rname
        # Get the stops of interest along route, we need to 'walk'
        route_geom = route.GetGeometryRef()
        # Do a transform now for comparison purposes - before creating buffer
        route_geom.Transform(route_transform)
        route_buffer = route_geom.Buffer(
            lineargeom.DIST_FOR_MATCHING_STOPS_ON_ROUTES)
        stops_near_route, isect_map = get_multipoint_within_with_map(
            stops_multipoint, route_buffer)
        if stops_near_route.GetGeometryCount() == 0:
            print "Error, no stops detected near route %s while creating "\
                "segments." % rname
            sys.exit()    
        rem_stop_is = range(stops_near_route.GetGeometryCount())
        start_coord = route_geom.GetPoint(0)
        current_loc = start_coord
        end_coord = route_geom.GetPoint(route_geom.GetPointCount()-1)
        end_vertex = ogr.Geometry(ogr.wkbPoint)
        end_vertex.AddPoint(*end_coord)
        line_remains = True
        stops_found = 0
        last_stop_i_along_route = None
        last_stop_i_in_route_set = None
        next_stop_i_along_route = None
        next_stop_i_in_route_set = None
        while line_remains is True:
            next_stop_on_route_isect, stop_ii, dist_to_next = \
                lineargeom.get_next_stop_and_dist(route_geom, current_loc,
                    stops_near_route, rem_stop_is)
            if next_stop_on_route_isect is None:
                # No more stops detected - Finish.
                break

            rem_stop_is.remove(stop_ii)
            stops_found += 1
            next_stop_i_along_route = stops_found-1
            next_stop_i_in_route_set = stop_ii

            if last_stop_i_along_route is not None:
                last_stop_i = isect_map[last_stop_i_in_route_set]
                last_stop = input_stops_lyr.GetFeature(last_stop_i)
                last_stop_id = last_stop.GetField(tp_model.STOP_ID_FIELD)
                next_stop_i = isect_map[next_stop_i_in_route_set]
                next_stop = input_stops_lyr.GetFeature(next_stop_i)
                next_stop_id = next_stop.GetField(tp_model.STOP_ID_FIELD)
                #print "..adding seg b/w stops %02s (id %d) and "\
                #    "%02s (id %d) (linear length %.1fm)" %\
                #        (last_stop_i_along_route, last_stop_id,\
                #         next_stop_i_along_route, next_stop_id,\
                #         dist_to_next)
                # This function will also handle updating the seg_ref lists
                seg_ref, new_status = route_segs.add_update_seg_ref(
                    last_stop_id, next_stop_id, rname,
                    dist_to_next, all_seg_refs, seg_refs_this_route)
                if new_status:
                    new_segs_cnt += 1
                last_stop.Destroy()
                next_stop.Destroy()
            else:
                if dist_to_next > lineargeom.DIST_FOR_MATCHING_STOPS_ON_ROUTES:
                    print "Warning: for route %s, first stop is %.1fm from "\
                        "start of route (>%.1fm)." % \
                        (rname, dist_to_next, \
                        lineargeom.DIST_FOR_MATCHING_STOPS_ON_ROUTES)
            # Walk ahead.
            current_loc = next_stop_on_route_isect
            last_stop_i_along_route = next_stop_i_along_route
            last_stop_i_in_route_set = next_stop_i_in_route_set
            #curr_loc_pt = ogr.Geometry(ogr.wkbPoint)
            #curr_loc_pt.AddPoint(*current_loc)
            #dist_to_end = curr_loc_pt.Distance(end_vertex)
            #curr_loc_pt.Destroy()
            if next_stop_on_route_isect is None or len(rem_stop_is) == 0:
            #        or dist_to_end < lineargeom.SAME_POINT:
                assert len(rem_stop_is) == 0
                line_remains = False
                break
        route_seg_refs.append((rname,seg_refs_this_route))
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
