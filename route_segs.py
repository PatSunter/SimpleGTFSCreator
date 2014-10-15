
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
# Definition of Route_Def and Seg_Reference lightweight classes and basic 
# manipulation of them.

class Route_Def:
    def __init__(self, route_id, short_name, long_name, dir_names,
            ordered_seg_ids):
        self.id = route_id
        self.short_name = short_name
        self.long_name = long_name
        self.dir_names = dir_names
        self.ordered_seg_ids = ordered_seg_ids
  
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
    if route_name not in seg_ref.routes:
        seg_ref.routes.append(route_name)
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

def find_seg_ref_matching_stops(all_seg_refs, stop_id_1, stop_id_2):
    matched_seg_ref = None
    for seg_ref in all_seg_refs:
        if seg_has_stops(seg_ref, stop_id_1, stop_id_2):
            matched_seg_ref = seg_ref
            break
    return matched_seg_ref
            
def add_update_seg_ref(start_stop_id, end_stop_id, route_name,
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
        #    route_name)
        add_route_to_seg_ref(matched_seg_ref, route_name)
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
            route_dist_on_seg, routes = [route_name])
        # Its a new segment, so append to the list of all segments.
        all_seg_refs.append(new_seg_ref)
        seg_ref_to_return = new_seg_ref
        seg_refs_this_route.append(seg_ref_to_return)

    return seg_ref_to_return, new_status

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

def get_link_with_shortest_dist(link_seg_ids, all_pattern_segs,
        link_dest_stop_ids_disallowed):
    # Trying algorithm of choosing segment with shortest distance.
    min_direct_dist = float("inf")
    min_dist_seg_id = None
    for link_seg_id in link_seg_ids:
        link_seg = get_seg_ref_with_id(link_seg_id, all_pattern_segs)
        if link_seg.first_id in link_dest_stop_ids_disallowed \
                or link_seg.second_id in link_dest_stop_ids_disallowed:
            continue
        if link_seg.route_dist_on_seg < min_direct_dist:
            min_direct_dist = link_seg.route_dist_on_seg
            min_dist_seg_id = link_seg_id
    return min_dist_seg_id

def get_links_sorted_by_distance(link_seg_ids, all_pattern_segs,
        link_dest_stop_ids_disallowed):
    links_and_dists = []
    for link_seg_id in link_seg_ids:
        link_seg = get_seg_ref_with_id(link_seg_id, all_pattern_segs)
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

def get_seg_ids_that_include_stop_id(all_pattern_segs, force_first_stop_id):
    seg_ids_that_include_stop = []
    for seg in all_pattern_segs:
        if force_first_stop_id in (seg.first_id, seg.second_id):
            seg_ids_that_include_stop.append(seg.seg_id)
    return seg_ids_that_include_stop 

def get_seg_ids_with_minimum_links(seg_ids, seg_links):
    min_link_segs = []
    min_links = min([len(seg_links[seg_id]) for seg_id in seg_ids])
    for seg_id in seg_ids:
        if len(seg_links[seg_id]) == min_links:
            min_link_segs.append(seg_id)
    return min_link_segs, min_links

def get_full_stop_pattern_segs(all_pattern_segs, seg_links,
        force_first_stop_id=None):
    """More advanced function to build a list of segments into a route :-
    this time by finding a 'full-stop' pattern linking all the segments.

    (This is useful if you're trying to reconstruct a single full-stop pattern
    from a set of all segments derived from a GTFS file with varying stop 
    patterns throughout the day.)

    (Note: current implementation is unlikely to deal with branching routes
    well. It will follow the branch with the most segments, won't include
    other branches.)

    Note re alg tuning and force_first_stop_id argument:- after a fair bit
    of effort I was able to make the algorithm produce sensible results for
    the 'full stop' version of routes with expresses and a 'city loop' trains
    in most cases. However a few cases such as the Belgrave line in Melbourne
    are difficult to come up with a good outcome with no initial information.

    Therefore there is a force_first_stop_id argument that allows to force
    beginning the segment-chain building algorithm at a particular stop, to
    help get a good result.
    """

    full_stop_pattern_segs = []
    all_seg_ids = map(operator.attrgetter('seg_id'), all_pattern_segs) 

    if len(all_pattern_segs) == 1:
        full_stop_pattern_segs = list(all_pattern_segs)
        return full_stop_pattern_segs

    if force_first_stop_id is None:
        # Ok: start with a search for one of the segments that 
        # only has one link - and is therefore an end of the route.
        start_seg_id = None
        multiple_start_links = False
        for seg_id, link_seg_ids in seg_links.iteritems():
            if len(link_seg_ids) == 1:
                start_seg_id = seg_id
                break
        if start_seg_id is None:
            print "This route has no segments with only one link."
            multiple_start_links = True
            # Fallback case.
            candidate_start_seg_ids, min_links = get_seg_ids_with_minimum_links(
                all_seg_ids, seg_links)
            print "Minimum links of any seg is %d" % min_links
            # Try the starts and ends first.
            min_dist_from_end = float("inf")
            for seg_id in candidate_start_seg_ids:
                dist_from_end = min(seg_id - 1, len(all_pattern_segs) - seg_id)
                if dist_from_end < min_dist_from_end:
                    min_dist_from_end = dist_from_end
                    start_seg_id = seg_id
                    if dist_from_end == 0:
                        break
            print "Starting with seg to have this # of links closest to "\
                "start or end = seg #%s" % start_seg_id
    else:
        # Force a start at a segment that includes the given stop.
        # This stop may still be included in several segments, so use the 
        # segment with the least links and shortest.
        print "Forcing start of building chain at stop ID %d" \
            % force_first_stop_id
        candidate_segs = get_seg_ids_that_include_stop_id(all_pattern_segs,
            force_first_stop_id)
        revised_cand_segs, min_links = get_seg_ids_with_minimum_links(
            candidate_segs, seg_links)
        if min_links > 1:
            multiple_start_links = True
        start_seg_id = get_link_with_shortest_dist(revised_cand_segs,
            all_pattern_segs, [])
        print "Starting with seg %d, which has %d links, and is the "\
            "shortest seg with this many links." \
            % (start_seg_id, min_links)

    #print "Added start seg %d." % start_seg_id
    start_seg_ref = get_seg_ref_with_id(start_seg_id, all_pattern_segs)
    full_stop_pattern_segs.append(start_seg_ref)

    if multiple_start_links:
        init_link_seg_ids = seg_links[start_seg_id]
        first_link_seg_id = get_link_with_shortest_dist(init_link_seg_ids,
            all_pattern_segs, [])
    else:
        init_link_seg_ids = seg_links[start_seg_id]
        first_link_seg_id = init_link_seg_ids[0]

    seg_chain, chain_len = get_longest_seg_linked_chain(first_link_seg_id,
        all_pattern_segs, full_stop_pattern_segs, seg_links, {})
    full_stop_pattern_segs += seg_chain

    if multiple_start_links and len(full_stop_pattern_segs) > 1:
        # Special case for if we started in the middle of a line
        rem_init_link_seg_ids = list(init_link_seg_ids)
        rem_init_link_seg_ids.remove(first_link_seg_id)
        first_stop_id = find_non_linking_stop_id(full_stop_pattern_segs[0],
            full_stop_pattern_segs[1])
        stop_ids_in_route_so_far = get_set_of_stops_in_route_so_far(
            full_stop_pattern_segs) 
        rev_candidate_link_ids = []
        for link_seg_id in rem_init_link_seg_ids:
            link_seg_ref = get_seg_ref_with_id(link_seg_id, all_pattern_segs)
            # There are legitimate cases where this link might not be from
            #  the first stop.
            if first_stop_id not in \
                    (link_seg_ref.first_id, link_seg_ref.second_id):
                continue
            non_link_stop = get_other_stop_id(link_seg_ref, first_stop_id)
            if non_link_stop not in stop_ids_in_route_so_far:
                # we have an unexplored section, not an express.
                rev_candidate_link_ids.append(link_seg_id)
        if rev_candidate_link_ids:
            print "Calling special reverse case ..."
            full_stop_pattern_segs.reverse()
            longest_chains_lookup_cache = {}
            longest_sub_chain = []
            longest_sub_chain_len = 0
            for rev_link_seg_id in rev_candidate_link_ids:
                seg_sub_chain, sub_chain_len = get_longest_seg_linked_chain(
                    link_seg_id, all_pattern_segs,
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

    seg_chain = []
    prev_seg_ref = segs_visited_so_far[-1]
    prev_seg_id = prev_seg_ref.seg_id
    stop_ids_in_route_so_far = get_set_of_stops_in_route_so_far(
        segs_visited_so_far) 

    # Special case for having visited all segments - esp for 1-segment routes
    if len(all_segs) == len(segs_visited_so_far):
        return [], 0

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
            # We need this extra check to avoid loops back into existing
            #  stops.
            next_seg_ref = get_seg_ref_with_id(next_seg_id, all_segs)
            next_stop_id = find_non_linking_stop_id(next_seg_ref, curr_seg_ref)
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

def order_all_route_segments(all_segs_by_route, rnames_sorted=None):
    # Now order each route properly ...
    # for each route - find unique stop names 
    if rnames_sorted == None:
        rnames_sorted = get_route_names_sorted(all_segs_by_route.keys())
    routes_ordered = {}
    route_dirs = {}
    for rname in rnames_sorted:
        print "Ordering segments by traversal for route '%s'" % rname
        route_seg_refs = all_segs_by_route[rname]
        if len(route_seg_refs) == 1:
            segs_by_route_ordered[rname] = route_seg_refs
            startstop = route_seg_refs[0].first_id
            endstop = route_seg_refs[0].second_id
        else:
            seg_links = build_seg_links(route_seg_refs)
            ordered_seg_refs = order_segs_based_on_links(route_seg_refs,
                seg_links)
            segs_by_route_ordered[rname] = ordered_seg_refs
            # Now create the directions
            first_seg, second_seg = ordered_seg_refs[0], ordered_seg_refs[1]
            linkstop = find_linking_stop_id(first_seg, second_seg)
            if first_seg.first_id != linkstop:
                startstop = first_seg.first_id
            else:
                startstop = first_seg.second_id
            last_seg = ordered_seg_refs[-1]
            second_last_seg = ordered_seg_refs[-2]
            linkstop = find_linking_stop_id(last_seg, second_last_seg)
            if last_seg.first_id != linkstop:
                endstop = last_seg.first_id
            else:
                endstop = last_seg.second_id
        dir1 = "%s->%s" % (startstop, endstop)
        dir2 = "%s->%s" % (endstop, startstop)
        route_dirs[rname] = (dir1, dir2)
    assert len(segs_by_route_ordered) == len(all_segs_by_route)
    assert len(segs_by_route_ordered) == len(route_dirs)
    return segs_by_route_ordered, route_dirs

def extract_stop_list_along_route(seg_refs):
    stop_ids = []
    for seg_ctr, seg_ref in enumerate(seg_refs):
        if seg_ctr == 0:
            # special case for a route with only one segment.
            if len(seg_refs) == 1:
                if dir_id == 0:
                    first_stop_id = seg_ref.first_id
                    second_stop_id = seg_ref.second_id
                else:    
                    first_stop_id = seg_ref.second_id
                    second_stop_id = seg_ref.first_id
            else:        
                next_seg_ref = seg_refs[seg_ctr+1]
                first_stop_id, second_stop_id = get_stop_order(seg_ref,
                    next_seg_ref)
        else:
            first_stop_id = prev_second_stop_id
            second_stop_id = get_other_stop_id(seg_ref, first_stop_id)

        stop_ids.append(first_stop_id)
        # Save this to help with calculations in subsequent steps
        prev_second_stop_id = second_stop_id
    # Finally, add second stop of final segment.
    stop_ids.append(second_stop_id)
    return stop_ids

########################################
# I/O from segments and stops shapefiles

def seg_ref_from_feature(seg_feature):
    seg_id = int(seg_feature.GetField(tp_model.SEG_ID_FIELD))
    stop_id_a, stop_id_b = tp_model.get_stop_ids_of_seg(seg_feature)
    route_dist_on_seg = float(seg_feature.GetField(tp_model.SEG_ROUTE_DIST_FIELD))
    seg_rlist = tp_model.get_routes_on_seg(seg_feature)
    seg_ref = Seg_Reference(seg_id, stop_id_a, stop_id_b, 
        route_dist_on_seg=route_dist_on_seg, routes=seg_rlist)
    return seg_ref

def get_routes_and_segments(segs_lyr):
    all_routes = {}
    for feature in segs_lyr:
        seg_ref = seg_ref_from_feature(feature)
        for route in seg_ref.routes:
            if route not in all_routes:
                all_routes[route] = [seg_ref]
            else:
                all_routes[route].append(seg_ref)
    #for rname, rsegs in all_routes.iteritems():
    #    print "For Route '%s': segments are %s" % (rname, rsegs)    
    segs_lyr.ResetReading()
    return all_routes

def create_ordered_seg_refs_from_ids(ordered_seg_ids, segs_lookup_table):
    ordered_seg_refs = []
    for seg_id in ordered_seg_ids:
        seg_feature = segs_lookup_table[seg_id]
        seg_ref = seg_ref_from_feature(seg_feature)
        ordered_seg_refs.append(seg_ref)
    return ordered_seg_refs

###############################
# I/O from route definition CSV

# Old (Pre 15 Oct 2014) headers of route_defs.csv
# ['Route', 'dir1', 'dir2', 'Segments'])

# New headers:
# ['route_id', 'route_short_name', 'route_long_name',
#    'dir1', 'dir2', 'Segments'])

def get_route_num(route_def):
    rname = route_def.short_name
    if rname == None:
        rname = route_def.long_name
    # Courtesy http://stackoverflow.com/questions/4289331/python-extract-numbers-from-a-string
    try:
        rnum = int(re.findall(r'\d+', rname)[0])
    except IndexError:
        # Fallback to just using entire route name.
        rnum = rname
    return rnum

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

    reader = csv.reader(csv_file, delimiter=';', quotechar="'") 
    # skip headings
    headers = reader.next()
    # Deal with old and new formats
    if headers[0] == 'Route':
        format_version = "00"
    else:
        format_version = "01"
    for ii, row in enumerate(reader):
        if format_version == "00":
            r_id = ii
            r_short_name = row[0]
            r_long_name = None
            dir1 = row[1]
            dir2 = row[2]
            segments_str = row[3].split(',')
        else:
            r_id = row[0]
            r_short_name = row[1]
            if r_short_name == 'None':
                r_short_name = None
            r_long_name = row[2]
            if r_long_name == 'None':
                r_long_name = None
            assert r_short_name or r_long_name
            dir1 = row[3]
            dir2 = row[4]
            segments_str = row[5].split(',')
        seg_ids = [int(segstr) for segstr in segments_str]
        route_def = Route_Def(r_id, r_short_name, r_long_name,
            (dir1, dir2), seg_ids)
        route_defs.append(route_def)
    if do_sort == True:
        route_defs.sort(key=get_route_num)        
    csv_file.close()
    return route_defs

def write_route_defs(csv_file_name, route_defs):
    routesfile = open(csv_file_name, 'w')
    rwriter = csv.writer(routesfile, delimiter=';')
    rwriter.writerow(['route_id', 'route_short_name', 'route_long_name',
        'dir1', 'dir2', 'Segments'])

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
            dirs[0], dirs[1], seg_str_all])

    routesfile.close()
    print "Wrote output to %s" % (csv_file_name)
    return

