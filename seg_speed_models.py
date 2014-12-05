
"""A module for different speed models and functions for public transport in
defining and writing timetables."""

import sys
import itertools
from datetime import datetime, date, time, timedelta

import osgeo.ogr
from osgeo import ogr, osr

import route_segs
import topology_shapefile_data_model as tp_model

class SpeedModel:
    """A Class that handles the speed of segments, at different times :-
    including their storage, and reading the speed at a given time.

    This abstraction was introudced as we wanted to introduce more complex
    speed models than just 'peak' and 'off-peak', e.g. speeds during certain
    times of day, and direction."""

    def __init__(self):
        return

    def setup(self, route_defs, segs_layer, stops_layer, mode_config):
        # By default, do nothing.
        return

    def setup_for_route(self, route_def, serv_periods):
        return True

    def setup_for_trip_set(self, route_def, serv_period, dir_id):
        # By default, do nothing.
        return True

    def save_extra_seg_speed_info(self, next_segment, serv_period, travel_dir):
        # By default, do nothing :- as not all sub-classes use this.
        return
    
    def add_extra_needed_speed_fields(self, segments_layer):
        # By default, do nothing :- as not all sub-classes use this.
        return

    def get_speed_on_next_segment(self, seq_stop_info, curr_time,
            peak_status):
        raise NotImplementedError("Error, this is a base class abstract "
            "method. Needs to be over-ridden by implementations.")

    
############################################
# Constant speed for entire mode model

class ConstantSpeedPerModeModel(SpeedModel):
    def __init__(self):
        self._mode_avg_speed = None

    def setup(self, route_defs, segs_layer, stops_layer, mode_config):
        self._mode_avg_speed = mode_config['avespeed']
        return

    def get_speed_on_next_segment(self, seg_speed_info, curr_time,
            peak_status):
        return self._mode_avg_speed

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

    def save_extra_seg_speed_info(self, next_segment, serv_period, travel_dir):
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

    def get_speed_on_next_segment(self, seg_speed_info, curr_time,
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

    def assign_speeds_to_all_segments(self, segments_layer, mode_config,
            prelim_check_func, free_speed_func, peak_speed_func):
        if prelim_check_func:
            prelim_check_func(segments_layer, mode_config)    
        assign_speeds_to_segs(segments_layer, mode_config,
            free_speed_func, SEG_FREE_SPEED_FIELD)
        assign_speeds_to_segs(segments_layer, mode_config,
            peak_speed_func, SEG_PEAK_SPEED_FIELD)
        return

def ensure_speed_field_exists(route_segments_lyr, speed_field_name):
    tp_model.ensure_field_exists(route_segments_lyr, speed_field_name,
        ogr.OFTReal, 24, 15)

def assign_speed_to_seg(route_segments_lyr, route_segment, speed_field_name,
        speed):
    route_segment.SetField(speed_field_name, speed)
    # This SetFeature() call is necessary to actually write the change
    # back to the layer itself.
    route_segments_lyr.SetFeature(route_segment)

def assign_speeds_to_segs(route_segments_lyr, mode_config, speed_func,
        speed_field_name):
    ensure_speed_field_exists(route_segments_lyr, speed_field_name)
    segs_total = route_segments_lyr.GetFeatureCount()
    print "Assigning speed to all %d route segments:" % segs_total
    one_tenth = segs_total / 10.0
    segs_since_print = 0
    for seg_num, route_segment in enumerate(route_segments_lyr):
        if segs_since_print / one_tenth > 1:
            print "...assigning to segment number %d ..." % (seg_num)
            segs_since_print = 0
        else:
            segs_since_print += 1
        speed = speed_func(route_segment, mode_config)
        assign_speed_to_seg(route_segments_lyr, route_segment,
            speed_field_name, speed)
        route_segment.Destroy()    
    print "...finished assigning speeds to segments."    
    route_segments_lyr.ResetReading()
    return


##################################################################################
# Segments with multiple speeds in different time periods, in different directions 

DIR_NAMES = ['a', 'b']
SEG_SPEED_DIR_FIELD_PREFIXES = ["spd-%s-" % d for d in DIR_NAMES]

# Idea is that time periods will be defined as a list of tuples of time 
#  period start and end, such as:
#    time_periods = [
#        (timedelta(hours=00,minutes=00), timedelta(hours=04,minutes=00)),
#        (timedelta(hours=04,minutes=00), timedelta(hours=06,minutes=00)),

def is_in_time_period(time_delta, tp):
    return time_delta >= tp[0] and time_delta <= tp[1]

def get_time_period_index(time_periods, last_time_period_found_i, curr_time):
    tp_found_i = None
    if last_time_period_found_i is not None:
        tp = time_periods[last_time_period_found_i]
        if is_in_time_period(curr_time, tp):
            tp_found_i = last_time_period_found_i
            return tp_found_i        
    for tp_i, tp in enumerate(time_periods):
        if is_in_time_period(curr_time, tp):
            tp_found_i = tp_i
            break
    return tp_found_i

def find_valid_speed_nearest_to_period(tp_speeds, tp_i):
    """Find the nearest seg speed to this TP index, that is not -1.
    First try tp_i index, then progressively search 1 spot forward,
    1 spot back, 2 spots forward, etc."""
    loop_i = 0
    tp_try_i = 0
    tp_i_shift = 0
    seg_speed = -1
    while tp_try_i <= len(tp_speeds):
        tp_i_to_read = tp_i + tp_i_shift
        if tp_i_to_read < len(tp_speeds) and tp_i_to_read >= 0:
            tp_try_i += 1    
            seg_speed = tp_speeds[tp_i_to_read]
            if seg_speed > 0:
                break
        if loop_i % 2 == 0:
            tp_i_shift = abs(tp_i_shift) + 1
        else:
            tp_i_shift *= -1 
        loop_i += 1
    return seg_speed    

class MultipleTimePeriodsSegSpeedInfo:
    """A small struct to store needed extra per-stop speed info read in
    from shapefiles - to be added to a Seq_Stop_Info."""
    def __init__(self, time_period_speeds):
        # We only need to worry about one direction at a time.
        self.time_period_speeds = time_period_speeds

class MultipleTimePeriodsSpeedModel(SpeedModel):
    def __init__(self, time_periods):
        self.time_periods = time_periods
        self._last_time_period_found_i = None

    def add_extra_needed_speed_fields(self, segments_layer):
        for ii, travel_dir in enumerate(DIR_NAMES):
            for jj, time_period in self.time_periods:
                field_name = "%s%d" % SEG_SPEED_DIR_FIELD_PREFIXES[ii]
                field = ogr.FieldDefn(field_name, ogr.OFTReal)
                field.SetWidth(24)
                field.SetPrecision(15)
                segments_layer.CreateField(field)
        return

    def save_extra_seg_speed_info(self, next_segment, serv_period, travel_dir):
        time_period_speeds = []
        seg_field_prefix_in_dir = SEG_SPEED_IR_FIELD_PREFIXES[travel_dir]
        try:
            for ii, time_period in self.time_periods:
                field_name = "%s%d" % SEG_SPEED_DIR_FIELD_PREFIXES[ii]
                speed_in_period = next_segment.GetField(field_name)
                time_period_speeds.append(speed_in_period)
        except ValueError:
            print "ERROR: you asked to use per-segment and per time-period "\
                "speeds when calculating timetable, but given segments "\
                "shapefile is missing field '%s'"\
                % (field_name)
            sys.exit(1)    
        speed_ext = MultipleTimePeriodSegSpeedInfo(time_period_speeds)
        return speed_ext

    def setup_for_trip_set(self, route_def, serv_period, dir_id):
        self._last_time_period_found_i = None
        return True

    def get_speed_on_next_segment(self, seg_speed_info, curr_time,
            peak_status):
        tp_speeds = seg_speed_info.time_period_speeds
        tp_i = get_time_period_index(self.time_periods, 
            self._last_time_period_found_i, curr_time)
        if tp_i is None:
            # If curr_time is beyond end of all time periods, its possibly
            # that this is a trip that started in last TP but continues beyond
            # it, which is OK.
            if curr_time > self.time_periods[-1][1]:
                tp_i = len(self.time_periods) - 1
        assert tp_i is not None
        self._last_time_period_found_i = tp_i
        seg_speed = find_valid_speed_nearest_to_period(tp_speeds, tp_i)
        return seg_speed


##############################################################################
# Segments with multiple speeds in different time periods, in different
# directions and has potential to allow speeds to vary per-route.

class MultipleTimePeriodsPerRouteSegSpeedInfo:
    """A small struct to store needed extra per-stop speed info read in
    from shapefiles - to be added to a Seq_Stop_Info."""
    def __init__(self, time_periods, time_period_speeds):
        # We only need to worry about one direction, serv period at a time.
        self.time_periods = time_periods
        self.time_period_speeds = time_period_speeds

class MultipleTimePeriodsPerRouteSpeedModel(MultipleTimePeriodsSpeedModel):
    def __init__(self, avg_speeds_dir):
        self.input_avg_speeds_dir = avg_speeds_dir
        self._last_time_period_found_i = None
        self._curr_time_periods = None
        self._curr_route_def = None
        self._curr_route_seg_speeds = None
        self.stop_id_to_gtfs_id_map = None

    def add_extra_needed_speed_fields(self, segments_layer):
        # override to do nothing :- we don't store anything on segs lyr,
        #  because the speeds differ per-route.
        return

    def setup(self, route_defs, segs_layer, stops_layer, mode_config):
        self.stop_id_to_gtfs_id_map = \
            tp_model.build_stop_id_to_gtfs_stop_id_map(stops_layer)
        return

    def setup_for_route(self, route_def, serv_periods):
        success_flag = True
        self._curr_route_def = route_def
        self._curr_route_seg_speeds = {}
        self._curr_time_periods = {}
        for serv_period, trips_dir in \
                itertools.product(serv_periods, route_def.dir_names):
            one_dir_opened = False
            try:
                import gtfs_ops
                time_periods, route_avg_speeds, seg_distances = \
                    gtfs_ops.read_route_speed_info_by_time_periods(
                        self.input_avg_speeds_dir, route_def.short_name,
                        route_def.long_name, serv_period,
                        trips_dir, sort_seg_stop_id_pairs=True)
            except IOError:
                # Just skip this if not found
                # Might be because different routes have diff. serv periods
                #print "Warning: for route %s, no avg speeds found for "\
                #    "dir-period combo (%s, %s)." \
                #    % (route_segs.get_print_name(route_def), trips_dir, \
                #       serv_period)
                continue    
            else:
                one_dir_opened = True
                self._curr_route_seg_speeds[(trips_dir, serv_period)] = \
                    route_avg_speeds        
                self._curr_time_periods[(trips_dir, serv_period)] = time_periods
            if not one_dir_opened:
                success_flag = False
        return success_flag

    def setup_for_trip_set(self, route_def, serv_period, dir_id):
        self._last_time_period_found_i = None
        self._curr_serv_period = serv_period
        self._curr_dir_name = route_def.dir_names[dir_id]
        dir_name = route_def.dir_names[dir_id]
        if (dir_name, serv_period) not in self._curr_route_seg_speeds:
            # Possibly, we don't have info for this time period / direction.
            #return False
            pass
        return True

    def save_extra_seg_speed_info(self, next_segment, serv_period, travel_dir):
        # We will look up relevant data for current serv period and direction,
        #  and save.
        gtfs_stop_pair = tp_model.get_gtfs_stop_id_pair_of_segment(next_segment,
            self.stop_id_to_gtfs_id_map)
        gtfs_stop_pair = tuple([str(gtfs_id) for gtfs_id in gtfs_stop_pair])
        dir_name = self._curr_route_def.dir_names[travel_dir]
        tps = None
        tp_speeds = None
        try:
            tps = self._curr_time_periods[(dir_name,serv_period)]
            sp_dir_speeds = self._curr_route_seg_speeds[(dir_name,serv_period)]
            tp_speeds = sp_dir_speeds[gtfs_stop_pair]
        except KeyError:    
            # Fall-back to searching all the other days and directions.
            for dir_period_pair, sp_dir_speeds \
                    in self._curr_route_seg_speeds.iteritems():
                try:
                    tps = self._curr_time_periods[dir_period_pair]
                    tp_speeds = sp_dir_speeds[gtfs_stop_pair]
                except KeyError:
                    continue
                else:
                    # We've got a workable speed set to use.
                    break    
        if not tp_speeds and tps:
            print "While curr_route is id %s, name %s:- "\
                "Error for segment %s: can't find a matching set of "\
                "avg speeds for this segment in any service period. "\
                "GTFS ids of stops are %s and %s." \
                % (self._curr_route_def.id, \
                   route_segs.get_print_name(self._curr_route_def), \
                   next_segment.GetField(tp_model.SEG_ID_FIELD), \
                   gtfs_stop_pair[0], gtfs_stop_pair[1])
            assert tp_speeds and tps
        speed_ext = MultipleTimePeriodsPerRouteSegSpeedInfo(tps, tp_speeds)
        return speed_ext

    def get_speed_on_next_segment(self, seg_speed_info, curr_time,
            peak_status):
        dir_period_pair = (self._curr_dir_name, self._curr_serv_period)
        # Now need to read this off the seg speed info, since if that segment
        # doesn't exist in the 'main' time period, we could be reading a
        # version that used different TPs.
        tps = seg_speed_info.time_periods
        assert tps
        tp_i = get_time_period_index(tps, self._last_time_period_found_i,
            curr_time)
        if tp_i is None:
            # If curr_time is beyond end of all time periods, its possibly
            # that this is a trip that started in last TP but continues beyond
            # it, which is OK.
            if curr_time > tps[-1][1]:
                tp_i = len(tps) - 1
        assert tp_i is not None
        self._last_time_period_found_i = tp_i
        tp_speeds = seg_speed_info.time_period_speeds
        seg_speed = find_valid_speed_nearest_to_period(tp_speeds, tp_i)
        return seg_speed
