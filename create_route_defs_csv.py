#!/usr/bin/env python2

import os
import inspect
from optparse import OptionParser
import pyproj
import osgeo.ogr
from osgeo import ogr
import csv
import sys

def segs_link(segtuple, othersegtuple):
    if segtuple[1] == othersegtuple[1]:
        return segtuple[1]
    elif segtuple[1] == othersegtuple[2]:
        return segtuple[1]
    elif segtuple[2] == othersegtuple[1]:
        return segtuple[2]
    elif segtuple[2] == othersegtuple[2]:
        return segtuple[2]
    return None

def getsegtuple(segnum, segtuples):
    for segtuple in segtuples:
        if segnum == segtuple[0]:
            return segtuple
    return None

def build_seg_links(rsegtuples):
    # for each seg :- find the linked segs
    seglinks = {}
    for segtuple in rsegtuples:
        seglinks[segtuple[0]] = []
    for ii, segtuple in enumerate(rsegtuples[:-1]):
        for othersegtuple in rsegtuples[ii+1:]:
            if segs_link(segtuple, othersegtuple) is not None:
                seglinks[segtuple[0]].append(othersegtuple[0])
                seglinks[othersegtuple[0]].append(segtuple[0])
    return seglinks    

def order_based_on_links(rsegtuples, seglinks):
    # Ok: start with one of the segments that only has one link
    startseg = None
    for seg, links in seglinks.iteritems():
        if len(links) == 1:
            startseg = seg
            break
    if startseg is None:
        print "Error: for route %s, no segment with 1 link." % rname
        sys.exit(1)
    ordered_segtuples = [getsegtuple(startseg, rsegtuples)]
    lastlinkseg = startseg
    currseg = seglinks[startseg][0]
    while True:
        currsegtuple = getsegtuple(currseg, rsegtuples)
        ordered_segtuples.append(currsegtuple)
        links = seglinks[currseg]
        assert len(links) <= 2
        if len(links) == 1:
            break
        nextlinkseg = None
        for linkseg in links:
            if linkseg != lastlinkseg:
                nextlinkseg = linkseg
        lastlinkseg = currseg
        currseg = nextlinkseg

    return ordered_segtuples

fname = "/Users/pds_phd/Dropbox/PhD-TechnicalProjectWork/OSSTIP_BZE/Melbourne_GIS_NetworkDataWork/BZE_New_Network/Bus_lines_segments-HerveVersion-2/bus-edges/bus-edges.shp"
shapefile = osgeo.ogr.Open(fname)
layer = shapefile.GetLayer(0)
all_routes = {}
for feature in layer:
    seg_id = int(feature.GetField("id"))
    seg_routes = feature.GetField("route_list")
    pt_a = feature.GetField("pt_a")
    pt_b = feature.GetField("pt_b")
    seg_rlist = seg_routes.split(',')
    segtuple = (seg_id, pt_a, pt_b)
    for route in seg_rlist:
        if route not in all_routes:
            all_routes[route] = [segtuple]
        else:
            all_routes[route].append(segtuple)

#for rname, rsegs in all_routes.iteritems():
#    print "For Route '%s': segments are %s" % (rname, rsegs)    

print "(A total of %d routes.)" % len(all_routes)

# Now order each route properly ...
# for each route - find unique stop names 
routes_ordered = {}
route_dirs = {}
for rname, rsegtuples in all_routes.iteritems():

    if len(rsegtuples) == 1:
        routes_ordered[rname] = rsegtuples
        continue
    seglinks = build_seg_links(rsegtuples)
    ordered_segtuples = order_based_on_links(rsegtuples, seglinks)
    routes_ordered[rname] = ordered_segtuples
    # Now create the directions
    linkstop = segs_link(ordered_segtuples[0], ordered_segtuples[1])
    if ordered_segtuples[0][1] != linkstop:
        startstop = ordered_segtuples[0][1]
    else:
        startstop = ordered_segtuples[0][2]
    linkstop = segs_link(ordered_segtuples[-2], ordered_segtuples[-1])
    if ordered_segtuples[-1][1] != linkstop:
        endstop = ordered_segtuples[-1][1]
    else:
        endstop = ordered_segtuples[-1][2]
    dir1 = "%s->%s" % (startstop, endstop)
    dir2 = "%s->%s" % (endstop, startstop)
    route_dirs[rname] = (dir1, dir2)

routesfilename = 'route_defs.csv'
routesfile = open(routesfilename, 'w')
rwriter = csv.writer(routesfile, delimiter=';')
rwriter.writerow(['Route','dir1','dir2','Segments'])

for rname, rsegtuples in routes_ordered.iteritems():
    segstrs = [str(segtuple[0]) for segtuple in rsegtuples]
    segstr = ','.join(segstrs)
    dirs = route_dirs[rname]
    rwriter.writerow([rname,dirs[0],dirs[1],segstr])

routesfile.close()
print "Wrote output to %s" % (routesfilename)
