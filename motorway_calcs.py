import osgeo.ogr
from osgeo import ogr, osr

import mode_timetable_info as m_t_info
import topology_shapefile_data_model as tp_model

COMPARISON_EPSG = 28355
# Put a _lot_ of leeway here, for stops that were added just off off-ramps
# etc.
SEG_END_NEAR_MOTORWAY_CHECK_DIST = 150
#SEG_END_NEAR_MOTORWAY_CHECK_DIST = 50 # Value more appropriate for reg bus.

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
    mways_buffer_geom = all_mways_geom.Buffer(SEG_END_NEAR_MOTORWAY_CHECK_DIST)
    print "...done creating motorways buffer."
    return mways_buffer_geom

def segment_on_motorway(route_segment, mways_buffer_geom,
        route_seg_transform):
    """Check if a segment is considered to be "on the motorway."
    route_seg_transform must be a transform for the route segment to 
    the same SRS as the mways_buffer_geom."""
    field_name = tp_model.ON_MOTORWAY_FIELD 
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

