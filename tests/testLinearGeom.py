#!/usr/bin/env python2

import lineargeom

seg1_start = (16143597.833908474, -4573071.089996331)
seg1_end = (16143641.002326438, -4572902.0192941455)
# Calcs a U value of 1.003116792609841

seg2_start = seg1_end
seg2_end = (16143656.019054238, -4572719.494394004)
# Calcs a U value of -0.001526408954544881 for this.

targ_point = (16143645.866695723, -4572902.699990039)

isect_pt, within, uval = lineargeom.intersect_point_to_line(targ_point,
    seg1_start, seg1_end)
dist = lineargeom.magnitude(isect_pt, seg1_end)
print isect_pt, within, uval, dist
isect_pt, within, uval = lineargeom.intersect_point_to_line(targ_point,
    seg2_start, seg2_end)
dist = lineargeom.magnitude(isect_pt, seg2_start)
print isect_pt, within, uval, dist

