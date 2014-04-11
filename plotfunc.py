#!/usr/bin/env python

"""A simple script to plot the speed-distance from CBD relationship based on
Laurent's script of bus-peak speed in Melbourne."""

import numpy
import matplotlib.pyplot as plt

from assign_speeds_to_network_topology import peak_speed_func

X = numpy.arange(0, 50, 0.1)

Y=numpy.zeros(len(X))
for ii, val in enumerate(X): 
    Y[ii] = peak_speed_func(val)

line, = plt.plot(X, Y, '--', linewidth=2)
line.set_dashes([10,5,100,5])
plt.ylim(ymin=0, ymax=30)
plt.savefig('speed-distance-bus-peak-Melb')
