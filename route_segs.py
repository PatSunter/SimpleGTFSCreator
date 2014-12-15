
"""A module for handling and accessing both the in-memory, and on-disk,
representation of a set of routes as a set of segments. Where each segment
specifies its start and end stop ids, and other data (see
topology_shapefile_data_model.py for more."""

import sys
import csv
import re
import operator
import itertools

import misc_utils
import topology_shapefile_data_model as tp_model

########
# Basic route name handling

def get_route_order_key_from_name(route_def):
    rname = route_def.short_name
    if rname:
        # Courtesy http://stackoverflow.com/questions/4289331/python-extract-numbers-from-a-string
        try:
            order_key = int(re.findall(r'\d+', rname)[0])
        except IndexError:
            order_key = rname
    else:
        order_key = route_def.long_name
    return order_key

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
# Definition of Route_Def and Seg_Reference lightweight classes and basic 
# manipulation of them.

class Route_Def:
    def __init__(self, route_id, short_name, long_name, dir_names,
            ordered_seg_ids, gtfs_origin_id = None):
        self.id = route_id
        self.gtfs_origin_id = gtfs_origin_id
        self.short_name = short_name
        self.long_name = long_name
        self.dir_names = dir_names
        self.ordered_seg_ids = ordered_seg_ids
  
class Seg_Reference:
    """A small lightweight class for using as an in-memory storage of 
    key segment topology information, and reference to actual segment
    feature in a shapefile layer.
    This is designed to save cost of reading actual
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

class Route_Ext_Info:
    """Class for holding relevant info about extended routes."""
    def __init__(self, ext_id, ext_name, ext_type,
            exist_r_s_name, exist_r_l_name,
            exist_r_connect_stop_gtfs_id, exist_r_first_stop_gtfs_id,
            upd_r_short_name, upd_r_long_name, upd_dir_name):
        self.ext_id = ext_id
        self.ext_name = ext_name
        self.ext_type = ext_type
        self.exist_r_short_name = exist_r_s_name
        self.exist_r_long_name = exist_r_l_name
        self.exist_r_connect_stop_gtfs_id = exist_r_connect_stop_gtfs_id
        self.exist_r_first_stop_gtfs_id = exist_r_first_stop_gtfs_id
        self.upd_r_short_name = upd_r_short_name
        self.upd_r_long_name = upd_r_long_name
        self.upd_dir_name = upd_dir_name

        assert ext_type in tp_model.ROUTE_EXT_ALL_TYPES
        assert self.exist_r_connect_stop_gtfs_id is not None
        if ext_type == tp_model.ROUTE_EXT_TYPE_NEW:
            assert self.exist_r_first_stop_gtfs_id is not None
        assert upd_dir_name
        return

def get_print_name(route_def):
    print_name = misc_utils.get_route_print_name(
        route_def.short_name, route_def.long_name)
    return print_name

def add_route_to_seg_ref(seg_ref, route_id):
    if route_id not in seg_ref.routes:
        seg_ref.routes.append(route_id)
    return    

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

def get_other_stop_id(seg_ref, stop_id):
    if stop_id == seg_ref.first_id:
        return seg_ref.second_id
    else:
        assert stop_id == seg_ref.second_id
        return seg_ref.first_id

#####################
# Basic manipulations on a list of seg_refs or route_defs

def get_seg_ref_with_id(seg_id, seg_refs):
    for seg_ref in seg_refs:
        if seg_id == seg_ref.seg_id:
            return seg_ref
    return None

def build_seg_refs_lookup_table(seg_refs):
    seg_refs_lookup_table = {}
    for seg_ref in seg_refs:
        seg_refs_lookup_table[seg_ref.seg_id] = seg_ref
    return seg_refs_lookup_table

def find_seg_ref_matching_stops(all_seg_refs, stop_id_1, stop_id_2):
    matched_seg_ref = None
    for seg_ref in all_seg_refs:
        if seg_has_stops(seg_ref, stop_id_1, stop_id_2):
            matched_seg_ref = seg_ref
            break
    return matched_seg_ref
            
def add_update_seg_ref(start_stop_id, end_stop_id, route_id,
        route_dist_on_seg, all_seg_refs, seg_refs_this_route,
        possible_route_duplicates=False):
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
        #    route_id)
        add_route_to_seg_ref(matched_seg_ref, route_id)
        seg_ref_to_return = matched_seg_ref
        if possible_route_duplicates:
            # Adding a new defensive case:- don't want to add a segment twice to
            #  the same route.
            matched_in_route = find_seg_ref_matching_stops(seg_refs_this_route,
                start_stop_id, end_stop_id)
            if not matched_seg_ref:
                seg_refs_this_route.append(seg_ref_to_return)
        else:
            seg_refs_this_route.append(seg_ref_to_return)
    else:
        new_status = True
        # +1 since we want to start counter at 1
        seg_id = len(all_seg_refs)+1
        new_seg_ref = Seg_Reference(seg_id, start_stop_id, end_stop_id,
            route_dist_on_seg, routes = [route_id])
        # Its a new segment, so append to the list of all segments.
        all_seg_refs.append(new_seg_ref)
        seg_ref_to_return = new_seg_ref
        seg_refs_this_route.append(seg_ref_to_return)

    return seg_ref_to_return, new_status

def route_defs_match_statuses(route_def, route_def2):
    match_statuses = []
    if route_def.id is not None and route_def2.id is not None:
        test = route_def.id == route_def2.id
        match_statuses.append(test)
    if route_def.short_name and route_def2.short_name:
        test = route_def.short_name == route_def2.short_name
        match_statuses.append(test)
    if route_def.long_name and route_def2.long_name:
        test = route_def.long_name == route_def2.long_name
        match_statuses.append(test)
    match_status = False
    # Make sure there is at least one attribute matching, and all match.
    if len(match_statuses) >= 1 and False not in match_statuses:
        match_status = True
    return match_status

def get_matching_route_defs(route_defs, search_route_def):
    matching_route_defs = []
    for rdef in route_defs:
        if route_defs_match_statuses(rdef, search_route_def):
            matching_route_defs.append(rdef)
    return matching_route_defs

def route_def_matches_gtfs_route(route_def, gtfs_route):
    match_statuses = []
    if route_def.id is not None:
        test = route_def.id == gtfs_route.route_id
        match_statuses.append(test)
    if route_def.short_name:
        test = route_def.short_name == gtfs_route.route_short_name
        match_statuses.append(test)
    if route_def.long_name:    
        test = route_def.long_name == gtfs_route.route_long_name
        match_statuses.append(test)
    match_status = False
    # Make sure there is at least one attribute matching, and all match.
    if len(match_statuses) >= 1 and False not in match_statuses:
        match_status = True
    return match_status

def get_gtfs_route_ids_matching_route_defs(route_defs_to_match, gtfs_routes):
    route_defs_to_check_match = zip(route_defs_to_match,
        itertools.count(0))
    matching_gtfs_ids = []
    route_defs_match_status = [False] * len(route_defs_to_match)
    all_matched = False
    for gtfs_route in gtfs_routes:
        matches = False
        # Note we take a copy of list here since we want to remove from it.
        for route_def, r_index in route_defs_to_check_match[:]:
            if route_def_matches_gtfs_route(route_def, gtfs_route):
                route_defs_match_status[r_index] = True
                gtfs_route_id = gtfs_route.route_id
                if gtfs_route_id not in matching_gtfs_ids:
                    matching_gtfs_ids.append(gtfs_route_id)
                else:
                    print "Warning: route def just matched, with ID "\
                        "%s, name %s, already matched a GTFS route. "\
                        "Ignoring 2nd match." \
                        % (gtfs_route_id, get_print_name(route_def))
                if route_def.id == gtfs_route_id:
                    # Only remove the route_def in this case, since we matched
                    # on ID. Otherwise there may be more matches.
                    route_defs_to_check_match.remove((route_def,r_index))
                    if len(route_defs_to_check_match) == 0:
                        all_matched = True
                        break
        if all_matched:
            # All routes matched, we're done.
            break
    for r_index, match_status in enumerate(route_defs_match_status):
        if not match_status:
            unmatched_r_def = route_defs_to_match[r_index]
            print "Warning: route given by ID %s, name %s, didn't match "\
                "any GTFS routes in given selection." \
                % (unmatched_r_def.id, get_print_name(unmatched_r_def))
    return matching_gtfs_ids, route_defs_match_status

def create_route_defs_list_from_route_segs(segs_by_route,
        route_dirs, mode_config, r_ids_output_order=None):
    """Turn a dict containing ordered lists of seg references that make up
    each route (segs_by_route) and related dictionary of route dir names
    (route_dirs) into a list of route definitions. If r_ids_output_order
    provided, routes defs in list will be ordered in that order."""
    route_defs = []
    if r_ids_output_order is None:
        r_ids_output_order = segs_by_route.keys()

    for r_id in r_ids_output_order:
        # Haven't yet implemented ability to create route long names
        r_short_name = tp_model.route_name_from_id(r_id, mode_config)
        r_long_name = None
        rdef = Route_Def(r_id, r_short_name, r_long_name, route_dirs[r_id],
            map(operator.attrgetter('seg_id'), segs_by_route[r_id]))
        route_defs.append(rdef)
    return route_defs

#########
### Functions to do with querying network topology

def find_linking_stop_id(seg1, seg2):
    """Checks if two segments are linked by a common stop. If true, returns
    the ID of the linking stop. If they don't link, returns None."""
    if seg1.first_id == seg2.first_id or seg1.first_id == seg2.second_id:
        return seg1.first_id
    elif seg1.second_id == seg2.first_id or seg1.second_id == seg2.second_id:
        return seg1.second_id
    return None

def find_non_linking_stop_id(seg1, seg2):
    """Find the stop in seg1 that doesn't link to seg2."""
    if seg1.first_id == seg2.first_id or seg1.first_id == seg2.second_id:
        return seg1.second_id
    elif seg1.second_id == seg2.first_id or seg1.second_id == seg2.second_id:
        return seg1.first_id
    return None

def get_stop_order(seg_ref, next_seg_ref):
    """Use the fact that for two segments, in the first segment, there must be
    a matching stop with the 2nd segment. Return the IDs of the 1st and 2nd 
    stops in the first segment."""
    
    linking_stop_id = find_linking_stop_id(seg_ref, next_seg_ref)
    if linking_stop_id is None:
        print "Error, in segment with id %d, next seg id is %d, "\
            "stop a is #%d, stop b is #%d, "\
            "next seg stop a is #%d, stop b is #%d, "\
            "couldn't work out stop order."\
            % (seg_ref.seg_id, next_seg_ref.seg_id, \
             seg_ref.first_id, seg_ref.second_id, \
             next_seg_ref.first_id, next_seg_ref.second_id)
        sys.exit(1)
    else:
        first_stop_id = get_other_stop_id(seg_ref, linking_stop_id)
        second_stop_id = linking_stop_id
    return first_stop_id, second_stop_id

def get_stop_ids_in_travel_dir(route_seg_refs, seg_ii, dir_index):
    """Returns the stop ids of segment ii in route_route_seg_refs given
    order of travel by dir_index. (Assumes route_seg_refs ordered in
    direction of travel of dir_index 0.)"""
    seg_ref = route_seg_refs[seg_ii]
    assert seg_ii >= 0 and seg_ii <= len(route_seg_refs) - 1
    if dir_index == 0:
        if seg_ii < len(route_seg_refs) - 1:
            stop_ids = get_stop_order(seg_ref,
                route_seg_refs[seg_ii+1])
        else:
            # Special case for last seg - need to use prev seg.
            linking_id = find_linking_stop_id(seg_ref,
                route_seg_refs[seg_ii-1])
            other_id = get_other_stop_id(seg_ref, linking_id)
            stop_ids = (linking_id, other_id)
    else:    
        if seg_ii > 0:
            stop_ids = get_stop_order(seg_ref, 
                route_seg_refs[seg_ii-1])
        else:
            # Special case for first seg - need to use next seg.
            linking_id = find_linking_stop_id(seg_ref,
                route_seg_refs[seg_ii+1])
            other_id = get_other_stop_id(seg_ref, linking_id)
            # Remember we're going 'backwards' in this case
            stop_ids = (linking_id, other_id)
    return stop_ids

def build_seg_links(route_seg_refs):
    """Create a dictionary, which for each segment ID, gives the list 
    of other segments linked to that id via a common stop."""
    seg_links = {}
    for seg in route_seg_refs:
        seg_links[seg.seg_id] = []
    for ii, seg in enumerate(route_seg_refs[:-1]):
        for other_seg in route_seg_refs[ii+1:]:
            if find_linking_stop_id(seg, other_seg) is not None:
                seg_links[seg.seg_id].append(other_seg.seg_id)
                seg_links[other_seg.seg_id].append(seg.seg_id)
    return seg_links

def order_segs_based_on_links(route_seg_refs, seg_links):
    """Construct and ordered list of all segments within a route
    (given in list route_seg_refs), based on their links via common stops."""
    # Ok: start with one of the segments that only has one link
    start_seg_id = None
    for seg_id, links in seg_links.iteritems():
        if len(links) == 1:
            start_seg_id = seg_id
            break
    if start_seg_id is None:
        print "Error: no segment with 1 link."
        sys.exit(1)

    ordered_seg_refs = [get_seg_ref_with_id(start_seg_id, route_seg_refs)]
    prev_seg_id = start_seg_id
    curr_seg_id = seg_links[start_seg_id][0]

    while True:
        curr_seg_ref = get_seg_ref_with_id(curr_seg_id, route_seg_refs)
        ordered_seg_refs.append(curr_seg_ref)
        links = seg_links[curr_seg_id]
        if len(links) > 2:
            print "Error, segment %d is linked to %d other segments %s" %\
                (currseg, len(links), links)
            sys.exit(1)    
        if len(links) == 1:
            # We have reached the final segment in the route.
            break
        next_seg_id = None
        for link_seg_id in links:
            if link_seg_id != prev_seg_id:
                next_seg_id = link_seg_id
        assert next_seg_id is not None
        prev_seg_id = curr_seg_id
        curr_seg_id = next_seg_id

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

def get_set_of_stops_in_route_so_far(segs_so_far):
    stop_ids_in_route_so_far = map(operator.attrgetter('first_id'),
        segs_so_far)
    stop_ids_in_route_so_far += map(operator.attrgetter('second_id'),
        segs_so_far)
    stop_ids_in_route_so_far = set(stop_ids_in_route_so_far)    
    return stop_ids_in_route_so_far

def get_seg_id_with_shortest_dist(link_seg_ids, seg_refs,
        link_dest_stop_ids_disallowed):
    # Trying algorithm of choosing segment with shortest distance.
    min_direct_dist = float("inf")
    min_dist_seg_id = None
    for link_seg_id in link_seg_ids:
        link_seg = get_seg_ref_with_id(link_seg_id, seg_refs)
        if link_seg.first_id in link_dest_stop_ids_disallowed \
                or link_seg.second_id in link_dest_stop_ids_disallowed:
            continue
        if link_seg.route_dist_on_seg < min_direct_dist:
            min_direct_dist = link_seg.route_dist_on_seg
            min_dist_seg_id = link_seg_id
    return min_dist_seg_id

def get_links_sorted_by_distance(link_seg_ids, seg_refs,
        link_dest_stop_ids_disallowed):
    links_and_dists = []
    for link_seg_id in link_seg_ids:
        link_seg = get_seg_ref_with_id(link_seg_id, seg_refs)
        if link_seg.first_id in link_dest_stop_ids_disallowed \
                or link_seg.second_id in link_dest_stop_ids_disallowed:
            continue
        links_and_dists.append((link_seg_id, link_seg.route_dist_on_seg))
    if links_and_dists:
        links_and_dists.sort(key=operator.itemgetter(1))
        link_seg_ids_sorted_by_dist = map(operator.itemgetter(0),
            links_and_dists)
    else:
        link_seg_ids_sorted_by_dist = None
    return link_seg_ids_sorted_by_dist

def get_seg_id_with_stop_ids(seg_refs, stop_id_a, stop_id_b):
    seg_ids_that_include_stop_ids = []
    for seg in seg_refs:
        if stop_id_a in (seg.first_id, seg.second_id) \
                and stop_id_b in (seg.first_id, seg.second_id):
            seg_ids_that_include_stop_ids.append(seg.seg_id)
    assert len(seg_ids_that_include_stop_ids) <= 1        
    if not seg_ids_that_include_stop_ids:
        return None
    else:
        return seg_ids_that_include_stop_ids[0]

def get_seg_ids_that_include_stop_id(seg_refs, stop_id):
    seg_ids_that_include_stop_id = []
    for seg_ref in seg_refs:
        if stop_id in (seg_ref.first_id, seg_ref.second_id):
            seg_ids_that_include_stop_id.append(seg_ref.seg_id)
    return seg_ids_that_include_stop_id 

def get_seg_ids_with_minimum_links(seg_ids, seg_links):
    min_link_segs = []
    min_links = min([len(seg_links[seg_id]) for seg_id in seg_ids])
    for seg_id in seg_ids:
        if len(seg_links[seg_id]) == min_links:
            min_link_segs.append(seg_id)
    return min_link_segs, min_links

def get_seg_refs_for_ordered_stop_ids(stop_ids, seg_refs):
    ordered_segs = []
    for stop_id_a, stop_id_b in misc_utils.pairs(stop_ids):
        seg_id = get_seg_id_with_stop_ids(seg_refs,
            stop_id_a, stop_id_b)
        if seg_id is None:
            print "WARNING:- the pattern being processed contains no "\
                "segments with stop pair IDs %d, %d, in list of "\
                "ordered stop ids you requested."\
                % (stop_id_a, stop_id_b)
            ordered_segs = []
            break
        else:
            seg_ref = get_seg_ref_with_id(seg_id, seg_refs)
            ordered_segs.append(seg_ref)    
    return ordered_segs

def get_full_stop_pattern_segs(all_pattern_segs, seg_links,
        force_first_stop_ids=None):
    """More advanced function to build a list of segments into a route :-
    this time by finding a 'full-stop' pattern linking all the segments.

    (This is useful if you're trying to reconstruct a single full-stop pattern
    from a set of all segments derived from a GTFS file with varying stop 
    patterns throughout the day.)

    (Note: current implementation is unlikely to deal with branching routes
    well. It will follow the branch with the most segments, won't include
    other branches.)

    Note re alg tuning and force_first_stop_ids argument:- after a fair bit
    of effort I was able to make the algorithm produce sensible results for
    the 'full stop' version of routes with expresses and a 'city loop' trains
    in most cases. However a few cases such as the Belgrave line in Melbourne
    are difficult to come up with a good outcome with no initial information.

    Therefore there is a force_first_stop_ids argument that allows to force
    beginning the segment-chain building algorithm at a particular stop(s), to
    help get a good result.
    """

    full_stop_pattern_segs = []
    all_seg_ids = map(operator.attrgetter('seg_id'), all_pattern_segs) 

    if len(all_pattern_segs) == 1:
        full_stop_pattern_segs = list(all_pattern_segs)
        return full_stop_pattern_segs

    if force_first_stop_ids and len(force_first_stop_ids) >= 3:
        # In this case :- we have at least two segments to start from in a
        # given order. Build these then add the longest chain at end.
        # We know there's no need to extend/reverse from here.
        print "Starting building chain with segs between stops %s ...." \
            % (force_first_stop_ids)
        full_stop_pattern_segs = get_seg_refs_for_ordered_stop_ids(
            force_first_stop_ids, all_pattern_segs)
        if not full_stop_pattern_segs: return []
        first_link_seg_id = full_stop_pattern_segs.pop().seg_id
        print "Added seg IDs b/w these stops: %s - next is %d" \
            % (map(operator.attrgetter('seg_id'), full_stop_pattern_segs),\
               first_link_seg_id)
        seg_chain, chain_len = get_longest_seg_linked_chain(first_link_seg_id,
            all_pattern_segs, full_stop_pattern_segs, seg_links, {})
        full_stop_pattern_segs += seg_chain
        return full_stop_pattern_segs
    elif force_first_stop_ids and len(force_first_stop_ids) == 2:
        # We've been given req'd first two stops, hence req'd first 
        # segment. So search all options with this segment in order.
        print "Starting building chain with seg between stops %s ...." \
            % (force_first_stop_ids)
        full_stop_pattern_segs = get_seg_refs_for_ordered_stop_ids(
            force_first_stop_ids, all_pattern_segs)
        if not full_stop_pattern_segs: return []
        first_seg_id = full_stop_pattern_segs[0].seg_id
        print "First build seg is #%d" % first_seg_id
        link_seg_ids = seg_links[first_seg_id]
        link_segs = [get_seg_ref_with_id(seg_id, all_pattern_segs) for \
            seg_id in link_seg_ids]
        cand_init_link_seg_ids = get_seg_ids_that_include_stop_id(
            link_segs, force_first_stop_ids[-1])
        # Now we need to find the longest sub-chain for all of these 
        # init link candidates.
        longest_chain = []
        for init_link_seg_id in cand_init_link_seg_ids:
            seg_chain, chain_len = get_longest_seg_linked_chain(
                init_link_seg_id, all_pattern_segs, full_stop_pattern_segs,
                seg_links, {})
            if chain_len > len(longest_chain):
                longest_chain = seg_chain
        full_stop_pattern_segs += longest_chain         
    elif force_first_stop_ids and len(force_first_stop_ids) == 1:
        # We have a first stop ID - but don't necessarily know which segment
        # this stop belongs to to start at. Need to potentially try
        # all combos passing through this stop.
        first_stop_id = force_first_stop_ids[0]
        print "Forcing start of building chain at stop ID %d" \
            % first_stop_id
        cand_start_seg_ids = get_seg_ids_that_include_stop_id(
            all_pattern_segs, first_stop_id)
        start_seg_ids_and_chains = []
        for start_seg_id in cand_start_seg_ids:
            start_seg_ref = get_seg_ref_with_id(start_seg_id, all_pattern_segs)
            other_stop_id = get_other_stop_id(start_seg_ref, first_stop_id)
            link_seg_ids = seg_links[start_seg_id]
            link_segs = [get_seg_ref_with_id(seg_id, all_pattern_segs) for \
                seg_id in link_seg_ids]
            # We only want 'forward' links away from the first stop id
            # work out longest of these.
            cand_init_link_seg_ids = get_seg_ids_that_include_stop_id(
                link_segs, other_stop_id)
            longest_sub_chain = []
            for link_seg_id in cand_init_link_seg_ids:
                seg_chain, chain_len = get_longest_seg_linked_chain(
                    link_seg_id, all_pattern_segs, [start_seg_ref],
                    seg_links, {})
                if chain_len > len(longest_sub_chain):
                    longest_sub_chain = seg_chain
            start_seg_ids_and_chains.append([start_seg_ref] + longest_sub_chain)

        # We need to get the longest chain
        start_seg_ids_and_chains.sort(key = len)
        full_stop_pattern_segs = start_seg_ids_and_chains[0]
    else:
        # We don't have a forced seg to start at.
        # Ok: best bet in this case is search for one of the segments that 
        # only has one link - and is therefore an end of the route.
        possible_reverse_links = False
        start_seg_id = None
        for seg_id, link_seg_ids in seg_links.iteritems():
            if len(link_seg_ids) == 1:
                start_seg_id = seg_id
                break
        if start_seg_id is not None:
            print "No start stop specified, so starting with seg #%d "\
                "that has only one link." % start_seg_id
        else:
            print "No start stop specified, and route has no "\
                "segments with only one link."
            possible_reverse_links = True
            # Fallback case.
            cand_start_seg_ids, min_links = get_seg_ids_with_minimum_links(
                all_seg_ids, seg_links)
            print "Minimum links of any seg is %d" % min_links
            # Try the 'starts' and 'ends' first in order we read segs for this
            # route.
            min_dist_from_end = float("inf")
            for seg_id in cand_start_seg_ids:
                dist_from_end = min(seg_id - 1, len(all_pattern_segs) - seg_id)
                if dist_from_end < min_dist_from_end:
                    min_dist_from_end = dist_from_end
                    start_seg_id = seg_id
                    if dist_from_end == 0:
                        break
            print "Starting with seg to have this # of links closest to "\
                "start or end = seg #%s" % start_seg_id
                    
        # Ok:- we've chosen a start seg ID, now need to choose best link seg
        #print "Added start seg %d." % start_seg_id
        start_seg_ref = get_seg_ref_with_id(start_seg_id, all_pattern_segs)
        full_stop_pattern_segs.append(start_seg_ref)
        init_link_seg_ids = seg_links[start_seg_id]
        first_link_seg_id = get_seg_id_with_shortest_dist(init_link_seg_ids,
            all_pattern_segs, [])

        seg_chain, chain_len = get_longest_seg_linked_chain(first_link_seg_id,
            all_pattern_segs, full_stop_pattern_segs, seg_links, {})
        full_stop_pattern_segs += seg_chain

        if possible_reverse_links:
            # We want to try building other possible 'reverse' chains, given
            # with this flag we may have started in the middle of a route.
            rem_init_link_seg_ids = list(init_link_seg_ids)
            rem_init_link_seg_ids.remove(first_link_seg_id)
            first_stop_id = find_non_linking_stop_id(full_stop_pattern_segs[0],
                full_stop_pattern_segs[1])
            stop_ids_in_route_so_far = get_set_of_stops_in_route_so_far(
                full_stop_pattern_segs) 
            rev_candidate_link_ids = []
            for link_seg_id in rem_init_link_seg_ids:
                link_seg_ref = get_seg_ref_with_id(link_seg_id, all_pattern_segs)
                if first_stop_id not in \
                        (link_seg_ref.first_id, link_seg_ref.second_id):
                    # This must be a 'branch' from the first stop, not a
                    # possible reverse.
                    continue
                non_link_stop = get_other_stop_id(link_seg_ref, first_stop_id)
                # NOTE:- rules out some loops
                if non_link_stop not in stop_ids_in_route_so_far:
                    # we have an unexplored section, not an express into 
                    # already included chain.
                    rev_candidate_link_ids.append(link_seg_id)
            if rev_candidate_link_ids:
                print "Calling special reverse case ..."
                full_stop_pattern_segs.reverse()
                longest_chains_lookup_cache = {}
                longest_sub_chain = []
                longest_sub_chain_len = 0
                for rev_link_seg_id in rev_candidate_link_ids:
                    seg_sub_chain, sub_chain_len = get_longest_seg_linked_chain(
                        rev_link_seg_id, all_pattern_segs,
                        full_stop_pattern_segs, seg_links,
                        #longest_chains_lookup_cache)
                        {})
                    if sub_chain_len > longest_sub_chain_len:
                        longest_sub_chain = seg_sub_chain
                        longest_sub_chain_len = sub_chain_len
                full_stop_pattern_segs += longest_sub_chain

    return full_stop_pattern_segs 

def get_longest_seg_linked_chain(init_seg_id, all_segs, segs_visited_so_far,
        seg_links, longest_chains_lookup_cache):

    # Special case for having visited all segments - esp for 1-segment routes
    if len(all_segs) == len(segs_visited_so_far):
        return [], 0

    seg_chain = []

    init_seg_ref = get_seg_ref_with_id(init_seg_id, all_segs)
    prev_seg_ref = segs_visited_so_far[-1]
    prev_seg_id = prev_seg_ref.seg_id
    prev_stop_id = find_linking_stop_id(prev_seg_ref, init_seg_ref)
    stop_ids_in_route_so_far = get_set_of_stops_in_route_so_far(
        segs_visited_so_far)

    curr_seg_id = init_seg_id
    while True:
        curr_seg_ref = get_seg_ref_with_id(curr_seg_id, all_segs)
        assert curr_seg_id not in map(operator.attrgetter('seg_id'), seg_chain) 
        seg_chain.append(curr_seg_ref)
        #print "Appended seg %d to sub chain. - sub chain is now %s." % \
        #    (curr_seg_id, map(operator.attrgetter('seg_id'), seg_chain))
        curr_stop_id = find_non_linking_stop_id(curr_seg_ref, prev_seg_ref)
        stop_ids_in_route_so_far.add(curr_stop_id)
        link_seg_ids = seg_links[curr_seg_id]
        next_seg_id = None
        if len(link_seg_ids) == 1:
            # We have reached the final segment in the route.
            break
        elif len(link_seg_ids) == 2:
            for link_seg_id in link_seg_ids:
                if link_seg_id != prev_seg_id:
                    next_seg_id = link_seg_id
            assert next_seg_id is not None
            next_seg_ref = get_seg_ref_with_id(next_seg_id, all_segs)
            linking_stop_id = find_linking_stop_id(next_seg_ref, curr_seg_ref)
            # Need this check to deal with single-segment branch cases.
            if linking_stop_id == prev_stop_id:
                #print "Warning:- single 'forward' link found from seg %d "\
                #    "to seg %d, but this next seg is actually a branch "\
                #    "from previous link. So breaking here."\
                #    % (curr_seg_id, next_seg_id)
                break
            # We need this extra check to avoid loops back into existing
            #  stops.
            next_stop_id = get_other_stop_id(next_seg_ref, linking_stop_id)
            if next_stop_id in stop_ids_in_route_so_far:
                #print "Warning:- single forward link found from seg %d "\
                #    "to seg %d, but this next seg links back to an "\
                #    "already visited stop. So breaking here."\
                #    % (curr_seg_id, next_seg_id)
                break    
        else:
            # This means there is either a 'branch', 'express' section,
            #  or a loop.
            fwd_link_seg_ids = list(link_seg_ids)
            fwd_link_seg_ids.remove(prev_seg_id)
            stops_disallowed = set(stop_ids_in_route_so_far)
            stops_disallowed.remove(curr_stop_id)
            fwd_link_seg_ids = get_links_sorted_by_distance(fwd_link_seg_ids,
               all_segs, stops_disallowed)
            if fwd_link_seg_ids is None:
                #print "Warning: multiple links from current segment, but "\
                #    "all of them looped back to an already used stop. "\
                #    "So breaking here (last added seg ID was %d)."\
                #    % curr_seg_id
                break
            longest_sub_chain = []
            longest_sub_chain_len = 0
            #print "*In recursive part*, curr_seg_id=%d" % curr_seg_id
            updated_segs_visited_so_far = segs_visited_so_far + seg_chain
            # We only want to cache lookup chains at the same depth level
            sub_longest_chains_lookup_cache = {}
            for link_seg_id in fwd_link_seg_ids:
                try:
                    sub_seg_chain = longest_chains_lookup_cache[link_seg_id]
                    sub_chain_len = len(sub_seg_chain)
                    #print "(lookup answer from cache for link %d was %d)" \
                    #    % (link_seg_id, sub_chain_len)
                except KeyError:
                    # Recursive call, to try all possible branches.
                    #print "*Launching recursive call on link seg id %d" \
                    #    % link_seg_id
                    sub_seg_chain, sub_chain_len = get_longest_seg_linked_chain(
                        link_seg_id, all_segs,
                        updated_segs_visited_so_far, seg_links,
                        #sub_longest_chains_lookup_cache)
                        {})
                    #print "...Sub-chain from link %d was %d long" \
                    #    % (link_seg_id, sub_chain_len)
                if sub_chain_len > longest_sub_chain_len:
                    longest_sub_chain = sub_seg_chain
                    longest_sub_chain_len = sub_chain_len
            assert len(set(longest_sub_chain)) == len(longest_sub_chain)
            seg_chain += longest_sub_chain
            assert len(set(seg_chain)) == len(seg_chain)
            break

        # Defensive check
        if next_seg_id in map(operator.attrgetter('seg_id'),
                segs_visited_so_far + seg_chain):
            #print "Warning, we found a loop in segments while constructing "\
            #    "full-stop pattern - breaking with loop seg id being %d."\
            #    % next_seg_id
            break
        prev_seg_id = curr_seg_id
        prev_stop_id = curr_stop_id
        prev_seg_ref = curr_seg_ref
        curr_seg_id = next_seg_id
    longest_chains_lookup_cache[init_seg_id] = seg_chain
    #print "sub-chain of ids calc was %s" \
    #    % (map(operator.attrgetter('seg_id'), seg_chain))
    assert len(set(seg_chain)) == len(seg_chain)
    all_segs_thus_far = segs_visited_so_far + seg_chain
    assert len(set(all_segs_thus_far)) == \
        len(all_segs_thus_far)
    stop_ids_in_route_thus_far = get_set_of_stops_in_route_so_far(
        all_segs_thus_far)
    assert len(set(stop_ids_in_route_thus_far)) == \
        len(stop_ids_in_route_thus_far)
    return seg_chain, len(seg_chain)

def order_all_route_segments(all_segs_by_route, r_ids_sorted=None):
    # Now order each route properly ...
    # for each route - find unique stop names 
    if r_ids_sorted == None:
        r_ids_sorted = sorted(all_segs_by_route.keys())
    segs_by_routes_ordered = {}
    for r_id in r_ids_sorted:
        print "Ordering segments by traversal for route ID %d:" \
            % (r_id)
        route_seg_refs = all_segs_by_route[r_id]
        if len(route_seg_refs) == 1:
            segs_by_routes_ordered[r_id] = route_seg_refs
        else:
            seg_links = build_seg_links(route_seg_refs)
            ordered_seg_refs = order_segs_based_on_links(route_seg_refs,
                seg_links)
            segs_by_routes_ordered[r_id] = ordered_seg_refs

    assert len(segs_by_routes_ordered) == len(all_segs_by_route)
    return segs_by_routes_ordered

def create_basic_route_dir_names(all_segs_by_route, mode_config):
    """Creating basic direction names for routes :- based on first and last
    stop ids and names in each route."""
    route_dir_names = {}
    for r_id, route_seg_refs in all_segs_by_route.iteritems():
        if len(route_seg_refs) == 1:
            start_stop = route_seg_refs[0].first_id
            end_stop = route_seg_refs[0].second_id
        else:    
            first_seg, second_seg = route_seg_refs[0], route_seg_refs[1]
            start_stop = find_non_linking_stop_id(first_seg, second_seg)
            if start_stop is None:
                print "Error in working out directions for route ID %d:- "\
                    "first and second segments don't link via a common stop!"\
                    % r_id
                sys.exit(1)    
            last_seg = route_seg_refs[-1]
            second_last_seg = route_seg_refs[-2]
            end_stop = find_non_linking_stop_id(last_seg, second_last_seg)
            if end_stop is None:
                print "Error in working out directions for route ID %d:- "\
                    "last and second last segments don't link via a "\
                    "common stop!"\
                    % r_id
                sys.exit(1)    

        first_stop_name = tp_model.stop_default_name_from_id(start_stop,
            mode_config) 
        last_stop_name = tp_model.stop_default_name_from_id(end_stop,
            mode_config)
        dir1 = "%s->%s" % (first_stop_name, last_stop_name)
        dir2 = "%s->%s" % (last_stop_name, first_stop_name)
        route_dir_names[r_id] = (dir1, dir2)
    assert len(all_segs_by_route) == len(route_dir_names)
    return route_dir_names

def extract_stop_list_along_route(ordered_seg_refs):
    stop_ids = []
    if len(ordered_seg_refs) == 1:
        # special case for a route with only one segment.
        seg_ref = ordered_seg_refs[0]
        stop_ids = [seg_ref.first_id, seg_ref.second_id]
    else:
        first_stop_id, second_stop_id = get_stop_order(
            ordered_seg_refs[0], ordered_seg_refs[1])
        stop_ids.append(first_stop_id)
        prev_second_stop_id = second_stop_id
        for seg_ref in ordered_seg_refs[1:]:
            first_stop_id = prev_second_stop_id
            second_stop_id = get_other_stop_id(seg_ref, first_stop_id)
            stop_ids.append(first_stop_id)
            prev_second_stop_id = second_stop_id
        # Finally, add second stop of final segment.
        stop_ids.append(second_stop_id)
    return stop_ids

########################################
# I/O from segments and stops shapefiles

def seg_ref_from_feature(seg_feature):
    seg_id = int(seg_feature.GetField(tp_model.SEG_ID_FIELD))
    stop_id_a, stop_id_b = tp_model.get_stop_ids_of_seg(seg_feature)
    route_dist_on_seg = float(seg_feature.GetField(
        tp_model.SEG_ROUTE_DIST_FIELD))
    seg_rlist = tp_model.get_routes_on_seg(seg_feature)
    seg_ref = Seg_Reference(seg_id, stop_id_a, stop_id_b, 
        route_dist_on_seg=route_dist_on_seg, routes=seg_rlist)
    return seg_ref

def route_ext_from_feature(route_ext_feat):
    ext_id = route_ext_feat.GetField(tp_model.ROUTE_EXT_ID_FIELD)
    ext_name = route_ext_feat.GetField(tp_model.ROUTE_EXT_NAME_FIELD)
    ext_type = route_ext_feat.GetField(tp_model.ROUTE_EXT_TYPE_FIELD)
    exist_r_s_name = \
        route_ext_feat.GetField(tp_model.ROUTE_EXT_EXIST_S_NAME_FIELD)
    exist_r_l_name = \
        route_ext_feat.GetField(tp_model.ROUTE_EXT_EXIST_L_NAME_FIELD)
    exist_r_connect_stop_gtfs_id = \
        route_ext_feat.GetField(tp_model.ROUTE_EXT_CONNECTING_STOP_FIELD)
    exist_r_first_stop_gtfs_id = \
        route_ext_feat.GetField(tp_model.ROUTE_EXT_FIRST_STOP_FIELD)
    if not exist_r_first_stop_gtfs_id:
        exist_r_first_stop_gtfs_id = None
    upd_r_short_name = \
        route_ext_feat.GetField(tp_model.ROUTE_EXT_UPD_S_NAME_FIELD)
    upd_r_long_name = \
        route_ext_feat.GetField(tp_model.ROUTE_EXT_UPD_L_NAME_FIELD)
    upd_dir_name = \
        route_ext_feat.GetField(tp_model.ROUTE_EXT_UPD_DIR_NAME_FIELD)
    route_ext_info = Route_Ext_Info(
        ext_id, ext_name, ext_type,
        exist_r_s_name, exist_r_l_name,
        exist_r_connect_stop_gtfs_id, exist_r_first_stop_gtfs_id,
        upd_r_short_name, upd_r_long_name, upd_dir_name)
    return route_ext_info

def read_route_ext_infos(route_exts_lyr):
    route_ext_infos = []
    for r_ext_i, route_ext_feat in enumerate(route_exts_lyr):
        route_ext_info = route_ext_from_feature(route_ext_feat)
        route_ext_infos.append(route_ext_info)
    route_exts_lyr.ResetReading()
    return route_ext_infos

def get_routes_and_segments(segs_lyr):
    all_routes = {}
    for feature in segs_lyr:
        seg_ref = seg_ref_from_feature(feature)
        for route_id in seg_ref.routes:
            if route_id not in all_routes:
                all_routes[route_id] = [seg_ref]
            else:
                all_routes[route_id].append(seg_ref)
    #for r_id, rsegs in all_routes.iteritems():
    #    print "For Route ID '%s': segments are %s" % (r_id, rsegs)    
    segs_lyr.ResetReading()
    return all_routes

def get_all_seg_refs(segs_lyr):
    all_seg_refs = []
    for feature in segs_lyr:
        seg_ref = seg_ref_from_feature(feature)
        all_seg_refs.append(seg_ref)
    segs_lyr.ResetReading()
    return all_seg_refs

def create_ordered_seg_refs_from_ids(ordered_seg_ids, segs_lookup_table):
    ordered_seg_refs = []
    for seg_id in ordered_seg_ids:
        seg_feature = segs_lookup_table[seg_id]
        seg_ref = seg_ref_from_feature(seg_feature)
        ordered_seg_refs.append(seg_ref)
    return ordered_seg_refs

def write_seg_ref_to_shp_file(seg_ref, segments_lyr, stop_feat_a, stop_feat_b,
        stops_srs, mode_config):
    # Create line geometry based on two stops.
    seg_geom = tp_model.create_seg_geom_from_stop_pair(stop_feat_a,
        stop_feat_b, stops_srs)
    seg_ii = tp_model.add_segment(segments_lyr,
        seg_ref.seg_id, seg_ref.routes, seg_ref.first_id, seg_ref.second_id,
        seg_ref.route_dist_on_seg, seg_geom, mode_config)
    seg_geom.Destroy()
    return seg_ii

def write_segments_to_shp_file(segments_lyr, input_stops_lyr, seg_refs,
        mode_config):
    """Write all segments defined by input seg_refs list to the segments_lyr.
    Geometries of segments defined by stop pairs in input_stops_lyr.
    """
    print "Writing segment references to shapefile:"
    stops_srs = input_stops_lyr.GetSpatialRef()
    # Build lookup table by stop ID into stops layer - for speed
    stops_lookup_dict = tp_model.build_stops_lookup_table(input_stops_lyr)
    for seg_ref in seg_refs:
        # look up corresponding stops in lookup table, and build geometry
        stop_feat_a = stops_lookup_dict[seg_ref.first_id]
        stop_feat_b = stops_lookup_dict[seg_ref.second_id]
        seg_ii = write_seg_ref_to_shp_file(seg_ref, segments_lyr,
            stop_feat_a, stop_feat_b, stops_srs, mode_config)
    print "...done writing."
    return

############################
# Route Ext Info processing.

def print_route_ext_infos(route_ext_infos, indent=4):
    for re in route_ext_infos:
        print " " * indent + "Ext id:%s, '%s', of type %s"\
            % (re.ext_id, re.ext_name, re.ext_type)
        print " " * indent * 2 + "connects to existing route '%s' "\
            "('%s'), at GTFS stop ID %s" \
            % (re.exist_r_short_name, re.exist_r_long_name, \
               re.exist_r_connect_stop_gtfs_id)
        if re.ext_type == tp_model.ROUTE_EXT_TYPE_NEW:
            print " " * indent * 2 + "(new route will copy starting from "\
                "stop with GTFS ID %s)"\
                % (re.exist_r_first_stop_gtfs_id)
        print " " * indent * 2 + "will update r name to '%s':'%s' "\
            "and new/updated dir name as '%s'." \
            % (re.upd_r_short_name, re.upd_r_long_name, \
               re.upd_dir_name)
    return

def get_matching_existing_route_info(
        route_defs, segs_lyr, segs_lookup_table, stops_lyr,
        route_ext_info):
    # Find the route def, stops, etc of matching route in existing topology
    search_route_def = Route_Def(
        None, 
        route_ext_info.exist_r_short_name,
        route_ext_info.exist_r_long_name,
        None, None)

    matching_r_defs = get_matching_route_defs(route_defs,
        search_route_def)
    if len(matching_r_defs) == 0:
        print "Error:- for route extension %s with s name %s, l name %s: "\
            "no matching existing routes!" \
            % (route_ext_info.ext_name, route_ext_info.exist_r_short_name,\
               route_ext_info.exist_r_long_name)
        sys.exit(1)
    elif len(matching_r_defs) > 1:
        print "Error:- for route extension %s with s name %s, l name %s: "\
            "matched multiple existing routes!" \
            % (route_ext_info.ext_name, route_ext_info.exist_r_short_name,\
               route_ext_info.exist_r_long_name)
        sys.exit(1)
    r_def_to_extend = matching_r_defs[0]

    seg_refs_along_route = create_ordered_seg_refs_from_ids(
        r_def_to_extend.ordered_seg_ids, segs_lookup_table)
    stop_ids_along_route = extract_stop_list_along_route(
        seg_refs_along_route)
    
    connect_stop_id = tp_model.get_stop_id_with_gtfs_id(
        stops_lyr, route_ext_info.exist_r_connect_stop_gtfs_id)

    if connect_stop_id is None:
        print "Error:- extension route with connecting stop spec. "\
            "with GTFS ID %s :- couldn't find an existing stop with "\
            "this GTFS ID."\
            % (route_ext_info.exist_r_connect_stop_gtfs_id)
        sys.exit()
    elif connect_stop_id not in stop_ids_along_route:
        print "Error:- extension route with connecting stop spec. "\
            "with GTFS ID %s exists, but not found in route to extend." \
            % (route_ext_info.exist_r_connect_stop_gtfs_id)
        sys.exit()
    
    if route_ext_info.ext_type == tp_model.ROUTE_EXT_TYPE_EXTENSION:
        if connect_stop_id == stop_ids_along_route[-1]:
            ext_dir_id = 0
        elif connect_stop_id == stop_ids_along_route[0]:
            ext_dir_id = -1
        else:
            print "Error:- extension route with connecting stop spec. "\
                "with GTFS ID %s not found at end of route to extend."\
            % (route_ext_info.exist_r_connect_stop_gtfs_id)
            sys.exit(1)
    # For new routes, the connecting stop can legitimately be 
    #  anywhere along the route.

    orig_route_first_stop_id = tp_model.get_stop_id_with_gtfs_id(
        stops_lyr, route_ext_info.exist_r_first_stop_gtfs_id)

    return r_def_to_extend, seg_refs_along_route, stop_ids_along_route, \
        connect_stop_id, orig_route_first_stop_id

def get_route_infos_to_extend(route_ext_infos, route_defs, segs_lyr,
        segs_lookup_table, stops_lyr):
    """Returns the existing_route_infos_to_extend in the form:- 
    (r_def_to_extend, seg_refs_along_route, stop_ids_along_route,
      connect_stop_id)"""
    existing_route_infos_to_extend = []
    for r_ext_info in route_ext_infos:
        route_info_to_extend = get_matching_existing_route_info(
            route_defs, segs_lyr, segs_lookup_table, stops_lyr,
            r_ext_info)
        existing_route_infos_to_extend.append(route_info_to_extend)        
    return existing_route_infos_to_extend     

###############################
# I/O from route definition CSV

# Old (Pre 15 Oct 2014) headers of route_defs.csv
ROUTE_CSV_HEADERS_00 = ['Route', 'dir1', 'dir2', 'Segments']

# New headers:
ROUTE_CSV_HEADERS_01 = ['route_id', 'route_short_name', 'route_long_name',
    'gtfs_id', 'dir1', 'dir2', 'Segments']

def read_route_defs(csv_file_name, do_sort=True):
    """Reads a CSV of route_defs, into a list of 'route_defs'.
    Each route_def is a dictionary, with following entries:
     name: name of route.
     directions: a tuple of two strings, the route directions.
     segments: a list of (ordered) route segments IDs."""
    route_defs = []
    try:
        csv_file = open(csv_file_name, 'r')
    except IOError:
        print "Error, route mapping CSV file given, %s , failed to open." \
            % (csv_file_name)
        sys.exit(1) 

    dict_reader = csv.DictReader(csv_file, delimiter=';', quotechar="'") 

    # Check old vs new format
    if 'Route' in dict_reader.fieldnames:
        format_version = "00"
    else:
        format_version = "01"

    for ii, row in enumerate(dict_reader):
        if format_version == "00":
            r_id = ii
            r_short_name = row['Route']
            r_long_name = None
        else:
            r_id = int(row['route_id'])
            r_short_name = row['route_short_name']
            if r_short_name == 'None' or len(r_short_name) == 0:
                r_short_name = None
            r_long_name = row['route_long_name']
            if r_long_name == 'None' or len(r_long_name) == 0:
                r_long_name = None
            assert r_short_name or r_long_name
            
        try:
            r_gtfs_id = row['gtfs_id']
            if r_gtfs_id == 'None' or len(r_gtfs_id) == 0:
                r_gtfs_id = None
        except KeyError:
            r_gtfs_id = None
        dir1 = row['dir1']
        dir2 = row['dir2']
        segments_str = row['Segments'].split(',')

        seg_ids = [int(segstr) for segstr in segments_str]
        route_def = Route_Def(r_id, r_short_name, r_long_name,
            (dir1, dir2), seg_ids, gtfs_origin_id=r_gtfs_id)
        route_defs.append(route_def)
    if do_sort == True:
        route_defs.sort(key=get_route_order_key_from_name)
    csv_file.close()
    return route_defs

def write_route_defs(csv_file_name, route_defs):
    if sys.version_info >= (3,0,0):
        routesfile = open(csv_file_name, 'w', newline='')
    else:
        routesfile = open(csv_file_name, 'wb')
    rwriter = csv.writer(routesfile, delimiter=';')
    rwriter.writerow(ROUTE_CSV_HEADERS_01)

    for rdef in route_defs:
        dirs = tuple(rdef.dir_names)
        if not dirs:
            print "Warning:- no dirs listed for route %s to write. "\
                "writing as empty dirs." % rdef.short_name
            dirs = ("", "")
        if len(dirs) == 1:    
            print "Warning:- only one dir listed for route %s to write. "\
                "writing other dir as empty." % rdef.short_name
            dirs = (dirs[0], "")
            
        seg_str_all = ','.join(map(str, rdef.ordered_seg_ids))
        rwriter.writerow([rdef.id, rdef.short_name, rdef.long_name,
            rdef.gtfs_origin_id, dirs[0], dirs[1], seg_str_all])

    routesfile.close()
    print "Wrote output to %s" % (csv_file_name)
    return

