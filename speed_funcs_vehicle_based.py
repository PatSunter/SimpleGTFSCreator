#!/usr/bin/env python

def dist_trav_rest_to_max_speed(max_speed, accel):
    # Use re-arranged 5th law of motion
    # Assume max speed in m/s.
    dist = max_speed**2 / (2 * accel)
    return dist

def calc_vehicle_trav_time_bw_stops(stop_dist_m,
        max_spd_m_s, accel_m_s2):
    dist_rest_to_max = dist_trav_rest_to_max_speed(
       max_spd_m_s, accel_m_s2)
    #import pdb
    #pdb.set_trace()
    if (dist_rest_to_max * 2) >= stop_dist_m:
        # We never actually reach full speed :-
        # halve the distance and work out trav time under full
        # accel/decel.
        accel_dist = stop_dist_m / 2.0
        # know a, u, s - use 3rd law
        accel_time = (2 * accel_dist / float(accel_m_s2)) ** 0.5
        time_s = accel_time * 2
    else:
        # Re-arranged 1st law
        accel_time = max_spd_m_s / float(accel_m_s2)
        rem_dist = stop_dist_m - (dist_rest_to_max * 2)
        assert rem_dist >= 0
        # This remaining dist travelled at constant max speed
        const_spd_time = rem_dist / float(max_spd_m_s)
        time_s = 2 * accel_time + const_spd_time
    return time_s

def calc_vehicle_speed_bw_stops(seg_dist_m,
        max_spd_km_h, accel_m_s2, stop_dwell_time_s):
    max_spd_m_s = max_spd_km_h / 3.6
    trav_time = calc_vehicle_trav_time_bw_stops(seg_dist_m,
        max_spd_m_s, accel_m_s2)
    tot_time = stop_dwell_time_s + trav_time
    avg_speed_inc_dwell_km_h = (seg_dist_m / tot_time) * 3.6
    return avg_speed_inc_dwell_km_h

