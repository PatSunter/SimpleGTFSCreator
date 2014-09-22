"""These are convenience functions, that I find useful over-and-above the
functionality provided by the Google-developed Python gtfs package."""

import copy

import transitfeed

def getRouteByLongName(schedule, long_name):
    for r_id, route in schedule.routes.iteritems():
        if route.route_long_name == long_name:
            return r_id, route
    return None, None        

def copy_selected_routes(input_schedule, output_schedule, route_names):
    for route_name in route_names:
        print "Now creating entry for route '%s'" % route_name
        r_id, route = getRouteByLongName(input_schedule, route_name)
        route_cpy = copy.copy(route)
        route_cpy._schedule = None
        route_cpy._trips = []
        output_schedule.AddRouteObject(route_cpy)

        trip_dict = route.GetPatternIdTripDict()
        p_keys = [k for k in trip_dict.iterkeys()]

        print "Copying across trips and stop times for %d patterns " \
            "in this route." % len(trip_dict)
        for p_ii, p_key in enumerate(p_keys):
            trips = trip_dict[p_key]
            n_trips = len(trips)
            trip_headsign = trips[0].trip_headsign
            trip_pattern = trips[0].GetPattern()
            n_stops = len(trip_pattern)
            for trip in trips:
                stop_times = trip.GetStopTimes()
                trip_cpy = copy.copy(trip)
                output_schedule.AddTripObject(trip_cpy)
                for stop_time in stop_times:
                    trip_cpy.AddStopTimeObject(stop_time)
    return

