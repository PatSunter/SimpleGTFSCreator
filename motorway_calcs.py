import osgeo.ogr
from osgeo import ogr, osr

import topology_shapefile_data_model as tp_model
import route_geom_ops

# Values below in m - see route_geom_ops.COMPARISON_EPSG
# Put a _lot_ of leeway here, for stops that were added just off off-ramps
# etc.
STOP_NEAR_MOTORWAY_CHECK_DIST = 30
#SEG_END_NEAR_MOTORWAY_CHECK_DIST = 50 # Value more appropriate for reg bus.
ALONG_ROUTE_EITHER_SIDE_CHECK_DIST = 600
ALONG_ROUTE_EITHER_SIDE_CHECK_NUM = 3

MIN_SEG_LENGTH_ON_MOTORWAYS = 800

def ensure_motorway_field_exists(route_segments_lyr):
    tp_model.ensure_field_exists(route_segments_lyr, tp_model.ON_MOTORWAY_FIELD, 
        ogr.OFTInteger, 10)

def is_on_motorway(route_segment):
    field_name = tp_model.ON_MOTORWAY_FIELD 
    value = route_segment.GetField(field_name)
    if value == 1:
        return True
    else:
        return False

def create_motorways_buffer(mways_lyr, target_srs, 
        mway_buffer_dist=STOP_NEAR_MOTORWAY_CHECK_DIST):
    print "...Creating buffer around all motorways for testing..."
    # Get all motorways as a multi-line
    all_mways_geom = ogr.Geometry(ogr.wkbMultiLineString)
    for mway_section in mways_lyr:
        all_mways_geom.AddGeometry(mway_section.GetGeometryRef())
    # Transform before we do the buffer, since units of buffer matter here.
    mways_src_srs = mways_lyr.GetSpatialRef()
    mways_transform = osr.CoordinateTransformation(mways_src_srs, target_srs)
    all_mways_geom.Transform(mways_transform)
    mways_buffer_geom = all_mways_geom.Buffer(mway_buffer_dist)
    print "...done creating motorways buffer."
    return mways_buffer_geom

def stop_on_motorway(input_geom, route_geom, mways_buffer_geom,
        route_geom_transform, last_vertex_i=None):
    """Check if a stop is considered to be "on the motorway."
    route_seg_transform must be a transform for the route segment to 
    the same SRS as the mways_buffer_geom."""
    on_motorway = False
    current_loc = input_geom.GetPoint(0)
    # Making a temp test geom because we need to reproject it.
    mway_test_geom = input_geom.Clone()
    mway_test_geom.Transform(route_geom_transform)
    within = mways_buffer_geom.Contains(mway_test_geom)
    if within:
        # We need to be a bit careful with the last_vertex_i's in following.
        # We are going to first do a zero-length traversal, to make sure 
        # l_v_i is initialised (it may be none where passed in.)
        current_loc, last_vertex_i = route_geom_ops.move_dist_along_route(
            route_geom, current_loc, 0, last_vertex_i)
        # Now don't over-write l_v_i after this.
        # Check before, all are within. If that fails, check after.
        inc = ALONG_ROUTE_EITHER_SIDE_CHECK_DIST / \
            float(ALONG_ROUTE_EITHER_SIDE_CHECK_NUM)
        all_within_before = True
        mways_before_l_v_i = last_vertex_i
        dist = -inc
        prev_before_pt = current_loc
        for ii in range(1, ALONG_ROUTE_EITHER_SIDE_CHECK_NUM+1):
            before_pt, mways_before_l_v_i = route_geom_ops.move_dist_along_route(
                route_geom, prev_before_pt, dist, mways_before_l_v_i)
            before_geom = ogr.Geometry(ogr.wkbPoint)
            before_geom.AddPoint(*before_pt)
            before_geom.Transform(route_geom_transform)
            within_before = mways_buffer_geom.Contains(before_geom)
            before_geom.Destroy()    
            if not within_before:
                all_within_before = False
                break
            prev_before_pt = before_pt
        if all_within_before:
            on_motorway = True    
        else:
           all_within_after = True
           mways_after_l_v_i = last_vertex_i
           dist = inc
           prev_after_pt = current_loc
           for ii in range(1, ALONG_ROUTE_EITHER_SIDE_CHECK_NUM+1):
               after_pt, mways_after_l_v_i = route_geom_ops.move_dist_along_route(
                   route_geom, prev_after_pt, dist, mways_after_l_v_i)
               after_geom = ogr.Geometry(ogr.wkbPoint)
               after_geom.AddPoint(*after_pt)
               after_geom.Transform(route_geom_transform)
               within_after = mways_buffer_geom.Contains(after_geom)
               after_geom.Destroy()
               if not within_after:
                   all_within_after = False
                   break
               prev_after_pt = after_pt 
           if all_within_after:
               on_motorway = True
    mway_test_geom.Destroy()
    return on_motorway

def segment_on_motorway(route_segment, mways_buffer_geom,
        route_seg_transform, mode_config):
    """Check if a segment is considered to be "on the motorway."
    route_seg_transform must be a transform for the route segment to 
    the same SRS as the mways_buffer_geom."""
    seg_geom_clone = route_segment.GetGeometryRef().Clone()
    # Ensure seg_geom is in correct SRS for testing
    seg_geom_clone.Transform(route_seg_transform)
    seg_length = seg_geom_clone.Length()
    if seg_length < mode_config['min_seg_length_on_motorways']:
        # This helps stop "false positives" on motorways.
        on_motorway = False
    else:    
        seg_coords = seg_geom_clone.GetPoints()
        assert len(seg_coords) == 2
        on_motorway = True
        for seg_coord in seg_coords:
            seg_pt = ogr.Geometry(ogr.wkbPoint)
            seg_pt.AddPoint(*seg_coord)
            within = mways_buffer_geom.Contains(seg_pt)
            seg_pt.Destroy()
            if not within:
                on_motorway = False
                break
    seg_geom_clone.Destroy()
    return on_motorway

