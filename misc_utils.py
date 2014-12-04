"""Miscellaneous useful utility functions."""

import math
from datetime import time, datetime, date, timedelta

SECS_PER_HOUR = 60 * 60
SECS_PER_DAY = SECS_PER_HOUR * 24

# pairs iterator:
# http://stackoverflow.com/questions/1257413/1257446#1257446
def pairs(lst, loop=False):
    i = iter(lst)
    first = prev = i.next()
    for item in i:
        yield prev, item
        prev = item
    if loop == True:
        yield item, first

# A reversed version of the above pairs iterator.
def reverse_pairs(lst, loop=False):
    i = reversed(lst)
    first = prev = i.next()
    for item in i:
        yield prev, item
        prev = item
    if loop == True:
        yield item, first

#################################################
# Handy time conversions - esp relevant for GTFS

def tdToTimeOfDay(td):
    return (datetime.combine(date.today(), time(0)) + td).time()

def tdToSecs(td):
    """Convert a Python timedelta object to an amount of seconds, as a double.
    (Useful for back-converting timedeltas into the straight seconds form
    needed by the transitfeed library."""
    secs = td.days * SECS_PER_DAY + td.seconds + td.microseconds / float(1e6)
    return secs

def tdToHours(td):
    return tdToSecs(td) / float(SECS_PER_HOUR)

##############################################
# Related to pretty-printing

def get_route_print_name(route_short_name, route_long_name):
    print_name = ""
    if route_short_name and route_short_name != "None":
        print_name = route_short_name
    if route_long_name and route_long_name != "None":
        if not print_name:
            print_name = route_long_name
        else:
            print_name += " (%s)" % route_long_name 
    return print_name

##############################################
# Generally useful file IO stuff

def to_file_ready_string(in_string):
    out_string = ""
    for char in in_string:
        if char.isalnum():
            out_string += char
        else:
            out_string += '_'
    return out_string

def routeDirStringToFileReady(route_dir):
    return to_file_ready_string(route_dir)

def routeNameFileReady(r_short_name, r_long_name):
    route_name_file_string = ""
    if r_short_name:
        route_name_file_string += to_file_ready_string(r_short_name)
        if r_long_name:
            route_name_file_string += "-"
    if r_long_name:
        route_name_file_string += to_file_ready_string(r_long_name)
    return route_name_file_string

def get_time_period_name_strings(periods):
    period_names = []
    for p0, p1 in periods:
        #p0t = tdToTimeOfDay(p0)
        #p1t = tdToTimeOfDay(p1)
        #pname = "%s-%s" % (p0t.strftime('%H_%M'), p1t.strftime('%H_%M'))
        p0h = math.floor(tdToHours(p0))
        p0m = round((tdToSecs(p0) % SECS_PER_HOUR) / 60)
        p1h = math.floor(tdToHours(p1))
        p1m = round((tdToSecs(p1) % SECS_PER_HOUR) / 60)
        pname = "%02d_%02d-%02d_%02d" % (p0h, p0m, p1h, p1m)
        period_names.append(pname)
    return period_names

def get_time_periods_from_strings(tperiod_strings):
    time_periods = []
    for tp_string in tperiod_strings:
        tp_a_str, tp_b_str = tp_string.split('-')
        tp_a_hr_str, tp_a_min_str = tp_a_str.split('_')
        tp_b_hr_str, tp_b_min_str = tp_b_str.split('_')
        tp_a = timedelta(hours=int(tp_a_hr_str), minutes=int(tp_a_min_str))
        tp_b = timedelta(hours=int(tp_b_hr_str), minutes=int(tp_b_min_str))
        time_periods.append((tp_a, tp_b))
    return time_periods


