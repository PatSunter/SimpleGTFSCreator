#!/usr/bin/env python2

import os
import inspect
from optparse import OptionParser
import pyproj
import osgeo.ogr
from osgeo import ogr
import csv
import sys

import topology_shapefile_data_model as tp_model

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
        print "Error: no segment with 1 link."
        sys.exit(1)
    ordered_segtuples = [getsegtuple(startseg, rsegtuples)]
    lastlinkseg = startseg
    currseg = seglinks[startseg][0]
    while True:
        currsegtuple = getsegtuple(currseg, rsegtuples)
        ordered_segtuples.append(currsegtuple)
        links = seglinks[currseg]
        if len(links) > 2:
            print "Error, segment %d is linked to %d other segments %s" %\
                (currseg, len(links), links)
            sys.exit(1)    
        if len(links) == 1:
            break
        nextlinkseg = None
        for linkseg in links:
            if linkseg != lastlinkseg:
                nextlinkseg = linkseg
        lastlinkseg = currseg
        currseg = nextlinkseg

    if len(rsegtuples) != len(ordered_segtuples):
        print "Error: total # segments for this route is %d, but only "\
            "found a linked chain of %d segments." \
            % (len(rsegtuples), len(ordered_segtuples))
        print "Unlinked segments (and their stops):"
        for seg in rsegtuples:
            if seg not in ordered_segtuples:
                print "\t%s" % (str(seg))
        sys.exit(1)    
    return ordered_segtuples

def get_routes_and_segments(segs_lyr):
    all_routes = {}
    for feature in segs_lyr:
        seg_id = int(feature.GetField(tp_model.SEG_ID_FIELD))
        seg_routes = feature.GetField(tp_model.SEG_ROUTE_LIST_FIELD)
        pt_a = feature.GetField(tp_model.SEG_STOP_1_NAME_FIELD)
        pt_b = feature.GetField(tp_model.SEG_STOP_2_NAME_FIELD)
        seg_rlist = seg_routes.split(',')
        segtuple = (seg_id, pt_a, pt_b)
        for route in seg_rlist:
            if route not in all_routes:
                all_routes[route] = [segtuple]
            else:
                all_routes[route].append(segtuple)
    #for rname, rsegs in all_routes.iteritems():
    #    print "For Route '%s': segments are %s" % (rname, rsegs)    
    return all_routes

def get_route_names_sorted(route_defs):
    # Get an ordered list of route names so we can write in name order,
    # Dropping the 'R' for route.
    rnames_sorted = sorted(route_defs.keys(), key=lambda s: int(s[1:]))
    return rnames_sorted

def order_route_segments(all_routes, rnames_sorted=None):
    # Now order each route properly ...
    # for each route - find unique stop names 
    if rnames_sorted == None:
        rnames_sorted = get_route_names_sorted(all_routes)
    routes_ordered = {}
    route_dirs = {}
    for rname in rnames_sorted:
        print "Ordering segments by traversal for route '%s'" % rname
        rsegtuples = all_routes[rname]
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
    assert len(routes_ordered) == len(all_routes)
    return routes_ordered, route_dirs

def process_all_routes(input_shp_fname, output_fname):
    shapefile = osgeo.ogr.Open(input_shp_fname)
    segs_lyr = shapefile.GetLayer(0)
    all_routes = get_routes_and_segments(segs_lyr)
    print "(A total of %d routes.)" % len(all_routes)
    rnames_sorted = get_route_names_sorted(all_routes)
    routes_ordered, route_dirs = order_route_segments(all_routes, rnames_sorted)

    # Now write out to file.
    routesfile = open(output_fname, 'w')
    rwriter = csv.writer(routesfile, delimiter=';')
    rwriter.writerow(['Route','dir1','dir2','Segments'])

    for rname in rnames_sorted:
        dirs = route_dirs[rname]
        rsegtuples = routes_ordered[rname]
        segstrs = [str(segtuple[0]) for segtuple in rsegtuples]
        segstr = ','.join(segstrs)
        rwriter.writerow([rname,dirs[0],dirs[1],segstr])

    routesfile.close()
    print "Wrote output to %s" % (output_fname)
    shapefile.Destroy()

if __name__ == "__main__":    
    parser = OptionParser()
    parser.add_option('--input_shp', dest='input_shp',
        help='Shape file containing bus segments, which list routes in each'\
            ' segment.')
    parser.add_option('--output_csv', dest='output_csv',
        help='Output file name you want to store CSV of route segments in'\
            ' (suggest should end in .csv)')
    parser.set_defaults(output_csv='route_defs.csv')        
    (options, args) = parser.parse_args()

    if options.input_shp is None:
        parser.print_help()
        parser.error("No input shape file path containing route infos given.")

    process_all_routes(options.input_shp, options.output_csv)
