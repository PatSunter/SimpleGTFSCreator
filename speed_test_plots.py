#!/usr/bin/env python

"""A simple script to plot the speed-distance from CBD relationship based on
Laurent's script of bus-peak speed in Melbourne."""

import numpy
import matplotlib.pyplot as plt

from speed_funcs_location_based import peak_speed_func
from speed_funcs_vehicle_based import *

def plot_melb_bus_dist_based():
    X = numpy.arange(0, 50, 0.1)

    Y=numpy.zeros(len(X))
    for ii, val in enumerate(X): 
        Y[ii] = peak_speed_func(val)

    fig = plt.figure()
    ax = fig.add_subplot(1,1,1)
    ax.grid(color="gray",zorder=0)
    line, = ax.plot(X, Y, '--', linewidth=2, zorder=3)
    line.set_dashes([10,5,100,5])
    plt.ylim(ymin=0, ymax=30)
    plt.title("Operational speed for Melb buses in peak, derived from data.")
    plt.xlabel("Distance from Melb CBD (km)")
    plt.ylabel("Average speed (km/h)")
    plt.savefig('speed-distance-bus-peak-Melb')

# These values are set based on examples from HiTrans book:
# Nielsen, G., Nelson, J., Mulley, C., Tegner, G., Lind, G., & Lange, T. 2005,
# Public transport - Planning the networks. HiTrans Best practice guide No. 2., ,  . 
# p126-127.

speed_func_params = {
    'slow_bus': {
        'full_speed': 40,
        'accel': 1.0,
        'stop_dwell_time': 20.0,
        },
    'tram': {
        'full_speed': 80,
        'accel': 1.0,
        'stop_dwell_time': 20.0,
        },
    'train': {
        'full_speed': 120,
        'accel': 1.0,
        'stop_dwell_time': 20.0,
        }
    }

def plot_mode_speeds_for_segment_lengths(min_dist, max_dist, dist_inc):

    dists = numpy.arange(min_dist, max_dist, dist_inc)
    seg_dists = [100, 200, 300, 500, 1000, 2500, 3000, 5000]
    for mode, s_f_ps in speed_func_params.iteritems():
        max_spd_m_s = s_f_ps['full_speed'] / 3.6
        dist_rest_to_max = dist_trav_rest_to_max_speed(
           max_spd_m_s, s_f_ps['accel'])
        print "For mode %s: dist taken from rest to max spd %.1f km/h = %.1fm" \
            % (mode, s_f_ps['full_speed'], dist_rest_to_max)
        print "For mode %s, at seg dists:" % mode
        for ii, seg_dist in enumerate(seg_dists):
            trav_time = calc_vehicle_trav_time_bw_stops(seg_dist,
                max_spd_m_s, s_f_ps['accel'])
            tot_time = s_f_ps['stop_dwell_time'] + trav_time
            avg_speed_inc_dwell_km_h = seg_dist / tot_time * 3.6
            print "\t%.1fm: trav time=%.1fs, avg speed inc dwell = %.1fkm/h" \
                % (seg_dist, trav_time, avg_speed_inc_dwell_km_h)

    speeds = {}

    fig = plt.figure()
    ax = fig.add_subplot(1,1,1)
    ax.grid(color="gray",zorder=0)
    for mode, s_f_ps in speed_func_params.iteritems():
        speeds[mode] = numpy.zeros(len(dists))
        for ii, dval in enumerate(dists): 
            speeds[mode][ii] = calc_vehicle_speed_bw_stops(
                dval,
                s_f_ps['full_speed'],
                s_f_ps['accel'],
                s_f_ps['stop_dwell_time'])
        line, = plt.plot(dists, speeds[mode], '--', linewidth=2,
            label="%s (%.1f km/h max spd)" % (mode, s_f_ps['full_speed']),
            zorder=3)
        line.set_dashes([50,2,10,2])

    plt.title("Operational speeds achievable")
    plt.xlabel("Distance between stops (m)")
    plt.ylabel("Average speed (km/h)")
    plt.xlim(xmin=0, xmax=max_dist)
    plt.ylim(ymin=0, ymax=100)
    plt.legend(loc="upper left", shadow=True)
    plt.savefig('speed-for-modes-vs-section-length')

if __name__ == "__main__":
    plot_melb_bus_dist_based()
    plot_mode_speeds_for_segment_lengths(100, 3000, 100)
