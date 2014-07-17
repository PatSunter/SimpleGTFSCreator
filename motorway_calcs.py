import osgeo.ogr
from osgeo import ogr, osr

import mode_timetable_info as m_t_info
import topology_shapefile_data_model as tp_model
import project_onto_line as lineargeom

COMPARISON_EPSG = 28355
# Put a _lot_ of leeway here, for stops that were added just off off-ramps
# etc.
STOP_NEAR_MOTORWAY_CHECK_DIST = 30
#SEG_END_NEAR_MOTORWAY_CHECK_DIST = 50 # Value more appropriate for reg bus.
ALONG_ROUTE_EITHER_SIDE_CHECK_DIST = 600
ALONG_ROUTE_EITHER_SIDE_CHECK_NUM = 3

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

def create_motorways_buffer(mways_lyr, target_srs):
    print "...Creating buffer around all motorways for testing..."
    # Get all motorways as a multi-line
    all_mways_geom = ogr.Geometry(ogr.wkbMultiLineString)
    for mway_section in mways_lyr:
        all_mways_geom.AddGeometry(mway_section.GetGeometryRef())
    # Transform before we do the buffer, since units of buffer matter here.
    mways_src_srs = mways_lyr.GetSpatialRef()
    mways_transform = osr.CoordinateTransformation(mways_src_srs, target_srs)
    all_mways_geom.Transform(mways_transform)
    mways_buffer_geom = all_mways_geom.Buffer(STOP_NEAR_MOTORWAY_CHECK_DIST)
    print "...done creating motorways buffer."
    return mways_buffer_geom

def stop_on_motorway(input_geom, route_geom, mways_buffer_geom,
        route_geom_transform):
    """Check if a stop is considered to be "on the motorway."
    route_seg_transform must be a transform for the route segment to 
    the same SRS as the mways_buffer_geom."""
    on_motorway = False
    current_loc = input_geom.GetPoint(0)
    # Making a temp test geom because we need to reproject it.
    mway_test_geom = ogr.Geometry(ogr.wkbPoint)
    mway_test_geom.AddPoint(*current_loc)
    mway_test_geom.Transform(route_geom_transform)
    within = mways_buffer_geom.Contains(mway_test_geom)
    if within:
        # Check before, all are within. If that fails, check after.
        inc = ALONG_ROUTE_EITHER_SIDE_CHECK_DIST / \
            float(ALONG_ROUTE_EITHER_SIDE_CHECK_NUM)
        all_within_before = True
        for ii in range(1, ALONG_ROUTE_EITHER_SIDE_CHECK_NUM+1):
            dist = ii * -inc
            before_pt = lineargeom.move_dist_along_route(route_geom,
                current_loc, dist)
            before_geom = ogr.Geometry(ogr.wkbPoint)
            before_geom.AddPoint(*before_pt)
            before_geom.Transform(route_geom_transform)
            within_before = mways_buffer_geom.Contains(before_geom)
            before_geom.Destroy()    
            if not within_before:
                all_within_before = False
                break
        if all_within_before:
            on_motorway = True    
        else:
           all_within_after = True
           for ii in range(1, ALONG_ROUTE_EITHER_SIDE_CHECK_NUM+1):
               dist = ii * inc
               after_pt = lineargeom.move_dist_along_route(route_geom,
                   current_loc, dist)
               after_geom = ogr.Geometry(ogr.wkbPoint)
               after_geom.AddPoint(*after_pt)
               after_geom.Transform(route_geom_transform)
               within_after = mways_buffer_geom.Contains(after_geom)
               after_geom.Destroy()
               if not within_after:
                   all_within_after = False
                   break
           if all_within_after:
               on_motorway = True
    mway_test_geom.Destroy()
    return on_motorway

def segment_on_motorway(route_segment, mways_buffer_geom,
        route_seg_transform):
    """Check if a segment is considered to be "on the motorway."
    route_seg_transform must be a transform for the route segment to 
    the same SRS as the mways_buffer_geom."""
    seg_geom = route_segment.GetGeometryRef()
    seg_coords = seg_geom.GetPoints()
    assert len(seg_coords) == 2
    on_motorway = True
    for seg_coord in seg_coords:
        seg_pt = ogr.Geometry(ogr.wkbPoint)
        seg_pt.AddPoint(*seg_coord)
        # Ensure seg_pt is in correct SRS
        seg_pt.Transform(route_seg_transform)
        within = mways_buffer_geom.Contains(seg_pt)
        seg_pt.Destroy()
        if not within:
            on_motorway = False
            break
    return on_motorway            

