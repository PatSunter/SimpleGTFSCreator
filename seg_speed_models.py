
"""A module for different speed models and functions for public transport in
defining and writing timetables."""

import sys
from datetime import datetime, date, time, timedelta

import osgeo.ogr
from osgeo import ogr, osr

class SpeedModel:
    """A Class that handles the speed of segments, at different times :-
    including their storage, and reading the speed at a given time.

    This abstraction was introudced as we wanted to introduce more complex
    speed models than just 'peak' and 'off-peak', e.g. speeds during certain
    times of day, and direction."""

    def __init__(self):
        return

    def save_extra_seg_speed_info(self, next_segment, stops_lyr):
        raise NotImplementedError("Error, this is a base class abstract "
            "method. Needs to be over-ridden by implementations.")
    
    def get_speed_on_next_segment(self, seq_stop_info, mode_config, curr_time,
            peak_status):
        raise NotImplementedError("Error, this is a base class abstract "
            "method. Needs to be over-ridden by implementations.")

    def add_extra_needed_speed_fields(self, segments_layer):
        raise NotImplementedError("Error, this is a base class abstract "
            "method. Needs to be over-ridden by implementations.")

############################################
# Constant speed for entire mode model

class ConstantSpeedPerModeModel(SpeedModel):
    def save_extra_seg_speed_info(self, next_segment, stops_lyr):
        """Nothing to save here, since in this model speed is constant for
        all segments."""
        return None

    def get_speed_on_next_segment(self, seg_speed_info, mode_config,
            curr_time, peak_status):
        return mode_config['avespeed']

    def add_extra_needed_speed_fields(self, segments_layer):
        # Nothing to do here, don't store any extra fields.
        return

#############################################
# Peak and Off-Peak speeds per segment model.

SEG_FREE_SPEED_FIELD = "free_speed" # real, 24, 15
SEG_PEAK_SPEED_FIELD = "peak_speed" # real, 24, 15

class PeakOffPeakSegSpeedInfo:
    """A small struct to store needed extra per-stop speed info read in
    from shapefiles - to be added to a Seq_Stop_Info."""
    def __init__(self, peak_speed_next, free_speed_next):
        self.peak_speed_next = peak_speed_next
        self.free_speed_next = free_speed_next

class PerSegmentPeakOffPeakSpeedModel(SpeedModel):
    def add_extra_needed_speed_fields(self, segments_layer):
        field = ogr.FieldDefn(SEG_FREE_SPEED_FIELD, ogr.OFTReal)
        field.SetWidth(24)
        field.SetPrecision(15)
        segments_layer.CreateField(field)
        field = ogr.FieldDefn(SEG_PEAK_SPEED_FIELD, ogr.OFTReal)
        field.SetWidth(24)
        field.SetPrecision(15)
        segments_layer.CreateField(field) 
        return

    def save_extra_seg_speed_info(self, next_segment, stops_lyr):
        try:
            peak_speed_next = next_segment.GetField(SEG_PEAK_SPEED_FIELD)
        except ValueError:
            print "ERROR: you asked to use per-segment speeds when "\
                "calculating timetable, but given segments shapefile is "\
                "missing field '%s'"\
                % (SEG_PEAK_SPEED_FIELD)
            sys.exit(1)
        try:
            free_speed_next = next_segment.GetField(SEG_FREE_SPEED_FIELD)
        except ValueError:
            print "ERROR: you asked to use per-segment speeds when "\
                "calculating timetable, but given segments shapefile is "\
                "missing field '%s'" % (SEG_FREE_SPEED_FIELD)
            sys.exit(1)
        speed_ext = PeakOffPeakSegSpeedInfo(peak_speed_next, free_speed_next)
        return speed_ext

    def get_speed_on_next_segment(self, seg_speed_info, mode_config, curr_time,
            peak_status):
        """Calculates travel time between two stops. Current algorithm is
        based on an average speed on that segment, and physical distance
        between them."""
        #assert isinstance(seg_speed_info, PeakOffPeakSegSpeedInfo)
        if peak_status:
            seg_speed = seg_speed_info.peak_speed_next
        else:
            seg_speed = seg_speed_info.free_speed_next
        return seg_speed
