
"""A module for handling and accessing both the in-memory, and on-disk,
representation of a set of routes as a set of segments. Where each segment
specifies its start and end stop ids, and other data (see
topology_shapefile_data_model.py for more."""

import sys
import csv
import re
import operator

import topology_shapefile_data_model as tp_model

########
# Basic route name handling

def get_route_names_sorted(route_names):
    # Get an ordered list of route names so we can write in name order,
    keyfunc = None
    if len(route_names[0]) <= 3:
        # Dropping the 'R' for route, for short route names, and sort
        #  by integer version of remaining string
        keyfunc = lambda s: int(s[1:])
    else:
        # Just sort by the full route name string.
        keyfunc = lambda s: s
    rnames_sorted = sorted(route_names, key=keyfunc)
    return rnames_sorted

########
# Definition of seg_reference class and basic manipulation of them.

class Seg_Reference:
    """A small lightweight class for using as an in-memory storage of key segment
    topology information, and reference to actual segment feature in a 
    shapefile layer. This is designed to save cost of reading actual
    shapefile frequently, e.g. for algorithms that need to search and/or
    add to segments list a lot."""
    def __init__(self, seg_id, first_stop_id, second_stop_id,
            route_dist_on_seg=None, routes=None):
        self.seg_id = seg_id    # Segment ID
        self.first_id = first_stop_id
        self.second_id = second_stop_id
        self.route_dist_on_seg = route_dist_on_seg
        if routes is None:
            self.routes = []
        else:
            self.routes = routes
        self.seg_ii = None    # Index into segments layer shapefile -
    
def add_route_to_seg_ref(seg_ref, route_name):
    seg_ref.routes.append(route_name)

def segs_linked(seg1, seg2):
    """Checks if two segments are linked by a common stop. If true, returns
    the ID of the linking stop. If they don't link, returns None."""
    if seg1.first_id == seg2.first_id or seg1.first_id == seg2.second_id:
        return seg1.first_id
    elif seg1.second_id == seg2.first_id or seg1.second_id == seg2.second_id:
        return seg1.second_id
    return None

def seg_has_stops(seg_ref, stop_id_1, stop_id_2):
    if seg_ref.first_id == stop_id_1 and \
            seg_ref.second_id == stop_id_2 \
        or seg_ref.first_id == stop_id_2 and \
            seg_ref.second_id == stop_id_1:
        return True
    return False

def get_seg_dist_km(seg_ref):
    if seg_ref is not None:
        return seg_ref.route_dist_on_seg / tp_model.ROUTE_DIST_RATIO_TO_KM
    else:
        print "Warning:- asked for distance of a seg_ref with ID %d, but "\
            "route distance hasn't yet been read or calculated for this "\
            "seg_ref." % seg_ref.seg_id
        return None

#####################
# Basic manipulations on a list of seg_refs

def get_seg_ref_with_id(seg_id, seg_refs):
    for seg_ref in seg_refs:
        if seg_id == seg_ref.seg_id:
            return seg_ref
    return None

def find_seg_ref_matching_stops(all_seg_refs, stop_id_1, stop_id_2):
    matched_seg_ref = None
    for seg_ref in all_seg_refs:
        if seg_has_stops(seg_ref, stop_id_1, stop_id_2):
            matched_seg_ref = seg_ref
            break
    return matched_seg_ref
            
def add_update_seg_ref(start_stop_id, end_stop_id, route_name,
        route_dist_on_seg, all_seg_refs, seg_refs_this_route):
    """Add a new segment to the two pre-existing lists all_seg_refs, and 
    seg_refs_this_route. If segment already exists, update its route list."""
    seg_id = None
    new_status = False
    seg_ref_to_return = None
    matched_seg_ref = find_seg_ref_matching_stops(all_seg_refs, start_stop_id,
        end_stop_id)
    if matched_seg_ref:
        new_status = False
        #print "While adding, matched a segment! Seg id = %s, existing "\
        #    "routes = %s, new route = '%s'" %\
        #    (matched_seg_ref.seg_id\
        #    matched_seg_ref.routes,\
        #    route_name)
        add_route_to_seg_ref(matched_seg_ref, route_name)
        seg_ref_to_return = matched_seg_ref
    else:
        new_status = True
        # +1 since we want to start counter at 1
        seg_id = len(all_seg_refs)+1
        new_seg_ref = Seg_Reference(seg_id, start_stop_id, end_stop_id,
            route_dist_on_seg, routes = [route_name])
        # Its a new segment, so append to the list of all segments.
        all_seg_refs.append(new_seg_ref)
        seg_ref_to_return = new_seg_ref
    seg_refs_this_route.append(seg_ref_to_return)
    return seg_ref_to_return, new_status

#########
### Functions to do with querying network topology

def build_seg_links(route_seg_refs):
    """Create a dictionary, which for each segment ID, gives the list 
    of other segments linked to that id via a common stop."""
    seglinks = {}
    for seg in route_seg_refs:
        seglinks[seg.seg_id] = []
    for ii, seg in enumerate(route_seg_refs[:-1]):
        for other_seg in route_seg_refs[ii+1:]:
            if segs_linked(seg, other_seg):
                seglinks[seg.seg_id].append(other_seg.seg_id)
                seglinks[other_seg.seg_id].append(seg.seg_id)
    return seglinks

def order_segs_based_on_links(route_seg_refs, seglinks):
    """Construct and ordered list of all segments within a route
    (given in list route_seg_refs), based on their links via common stops."""
    # Ok: start with one of the segments that only has one link
    start_seg_id = None
    for seg_id, links in seglinks.iteritems():
        if len(links) == 1:
            start_seg_id = seg_id
            break
    if start_seg_id is None:
        print "Error: no segment with 1 link."
        sys.exit(1)
    ordered_seg_refs = [get_seg_ref_with_id(start_seg_id, route_seg_refs)]
    last_link_id = start_seg_id
    curr_id = seglinks[start_seg_id][0]

    while True:
        curr_seg_ref = get_seg_ref_with_id(curr_id, route_seg_refs)
        ordered_seg_refs.append(curr_seg_ref)
        links = seglinks[curr_id]
        if len(links) > 2:
            print "Error, segment %d is linked to %d other segments %s" %\
                (currseg, len(links), links)
            sys.exit(1)    
        if len(links) == 1:
            # We have reached the final segment in the route.
            break
        next_link_id = None
        for link_seg_id in links:
            if link_seg_id != last_link_id:
                next_link_id = link_seg_id
        assert next_link_id is not None
        last_link_id = curr_id
        curr_id = next_link_id

    if len(route_seg_refs) != len(ordered_seg_refs):
        print "Error: total # segments for this route is %d, but only "\
            "found a linked chain of %d segments." \
            % (len(route_seg_refs), len(ordered_seg_refs))
        unlinked_seg_ids = []
        for seg in route_seg_refs:
            if get_seg_ref_with_id(seg.seg_id, route_seg_refs) is None:
                unlinked_seg_ids.append(seg.seg_id)
        print "Unlinked segment IDs: %s" % unlinked_seg_ids
        sys.exit(1)
    return ordered_seg_refs

def order_all_route_segments(all_routes, rnames_sorted=None):
    # Now order each route properly ...
    # for each route - find unique stop names 
    if rnames_sorted == None:
        rnames_sorted = get_route_names_sorted(all_routes.keys())
    routes_ordered = {}
    route_dirs = {}
    for rname in rnames_sorted:
        print "Ordering segments by traversal for route '%s'" % rname
        route_seg_refs = all_routes[rname]
        if len(route_seg_refs) == 1:
            routes_ordered[rname] = route_seg_refs
            startstop = route_seg_refs[0].first_id
            endstop = route_seg_refs[0].second_id
        else:
            seglinks = build_seg_links(route_seg_refs)
            ordered_seg_refs = order_segs_based_on_links(route_seg_refs, seglinks)
            routes_ordered[rname] = ordered_seg_refs
            # Now create the directions
            first_seg, second_seg = ordered_seg_refs[0], ordered_seg_refs[1]
            linkstop = segs_linked(first_seg, second_seg)
            if first_seg.first_id != linkstop:
                startstop = first_seg.first_id
            else:
                startstop = first_seg.second_id
            last_seg = ordered_seg_refs[-1]
            second_last_seg = ordered_seg_refs[-2]
            linkstop = segs_linked(last_seg, second_last_seg)
            if last_seg.first_id != linkstop:
                endstop = last_seg.first_id
            else:
                endstop = last_seg.second_id
        dir1 = "%s->%s" % (startstop, endstop)
        dir2 = "%s->%s" % (endstop, startstop)
        route_dirs[rname] = (dir1, dir2)
    assert len(routes_ordered) == len(all_routes) == len(route_dirs)
    return routes_ordered, route_dirs


########################################
# I/O from segments and stops shapefiles

def get_routes_and_segments(segs_lyr):
    all_routes = {}
    for feature in segs_lyr:
        seg_id = int(feature.GetField(tp_model.SEG_ID_FIELD))
        pt_a = feature.GetField(tp_model.SEG_STOP_1_NAME_FIELD)
        pt_b = feature.GetField(tp_model.SEG_STOP_2_NAME_FIELD)
        route_dist_on_seg = float(feature.GetField(tp_model.SEG_ROUTE_DIST_FIELD))
        seg_rlist = tp_model.get_routes_on_seg(feature)
        seg_ref = Seg_Reference(seg_id, pt_a, pt_b, 
            route_dist_on_seg=route_dist_on_seg, routes=seg_rlist)
        for route in seg_rlist:
            if route not in all_routes:
                all_routes[route] = [seg_ref]
            else:
                all_routes[route].append(seg_ref)
    #for rname, rsegs in all_routes.iteritems():
    #    print "For Route '%s': segments are %s" % (rname, rsegs)    
    segs_lyr.ResetReading()
    return all_routes


###############################
# I/O from route definition CSV

def get_route_num(routeDictEntry):
    rname = routeDictEntry['name']
    # Courtesy http://stackoverflow.com/questions/4289331/python-extract-numbers-from-a-string
    return int(re.findall(r'\d+', rname)[0])

def read_route_defs(csv_file_name, do_sort=True):
    """Reads a CSV of route_defs, into a list of 'route_defs'.
    Each route_def is a dictionary, with following entries:
     name: name of route.
     directions: a tuple of two strings, the route directions.
     segments: a list of (ordered) route segments IDs."""
    route_defs = []
    csv_file = open(csv_file_name, 'r')
    if csv_file is None:
        print "Error, route mapping CSV file given, %s , failed to open." \
            % (csv_file_name)
        sys.exit(1) 
    reader = csv.reader(csv_file, delimiter=';', quotechar="'") 
    # skip headings
    reader.next()
    for ii, row in enumerate(reader):
        route_def = {}
        route_def['name'] = row[0]
        dir1 = row[1]
        dir2 = row[2]
        route_def['directions'] = (dir1, dir2)
        segments_str = row[3].split(',')
        route_def['segments'] = [int(segstr) for segstr in segments_str]
        route_defs.append(route_def)
    if do_sort == True:
        route_defs.sort(key=get_route_num)        

    csv_file.close()
    return route_defs

def write_route_defs(csv_file_name, rnames, route_dirs, route_segs_ordered):
        # Now write out to file.
    routesfile = open(csv_file_name, 'w')
    rwriter = csv.writer(routesfile, delimiter=';')
    rwriter.writerow(['Route','dir1','dir2','Segments'])

    for rname in rnames:
        dirs = route_dirs[rname]
        rsegs = route_segs_ordered[rname]
        seg_strs = map(lambda x: str(x.seg_id), rsegs)
        seg_str_all = ','.join(seg_strs)
        rwriter.writerow([rname,dirs[0],dirs[1],seg_str_all])

    routesfile.close()
    print "Wrote output to %s" % (csv_file_name)
    return

