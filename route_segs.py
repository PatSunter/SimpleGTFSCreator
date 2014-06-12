
"""A module for handling and accessing both the in-memory, and on-disk,
representation of a set of routes as a set of segments. Where each segment
specifies its start and end stop ids, and other data (see
topology_shapefile_data_model.py for more."""

import sys
import csv

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

def find_seg_ref_matching_stops(all_seg_refs, start_stop_id, end_stop_id):
    matched_seg_ref = None
    for seg_ref in all_seg_refs:
        if seg_ref.first_id == start_stop_id and \
                seg_ref.second_id == end_stop_id \
            or seg_ref.first_id == end_stop_id and \
                seg_ref.second_id == start_stop_id:
            matched_seg_ref = seg_ref
            break
    return matched_seg_ref

def add_update_seg_ref(start_stop_id, end_stop_id,
        route_name, route_dist_on_seg, all_seg_refs, seg_refs_this_route):
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


def get_route_num(routeDictEntry):
    return int(routeDictEntry['name'][1:])

# TODO: Modify this to create lists using the new seg_reference above?
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
    return route_defs



