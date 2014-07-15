from datetime import datetime, date, time, timedelta

#Format:
# avespeed: average speed (km/h)
# headway: how often each hour a vehicle arrives
# first service: the first service of the day
# last service: the last service of the day. (Ideally should be able to do
#  after midnight ... obviously should be lower than first service though).
# id: Needed for GTFS - a unique ID (important if going to work with multiple
# agencies in a combined larger GTFS file or multiple files.
# index: Similar to ID, but will be used to add route numbers to this index
#  to generate a unique number for each route.

# For speeds - see HiTrans guide, page 127

#Service periods is a list of tuples:-
# Where each is a start time, end time, and then a headway during that period.

sparse_test_headways = [
    (time(05,00), time(02,00), 60),
    ]

SPARSE_SERVICE_INFO = [
    ("monfri", sparse_test_headways)
    ]

# Format of columns:-
# 0: start time of period
# 1: end time of period
# 2: headway during period (time between services)
# 3: Is this a peak period? True/False (used to decide speed in congested
# areas).
default_service_headways = [
    (time(05,00), time(07,30), 20, False),
    (time(07,30), time(10,00), 5, True), 
    (time(10,00), time(16,00), 10, False),
    (time(16,00), time(18,30), 5, True),
    (time(18,30), time(23,00), 10, False),
    (time(23,00), time(02,00), 20, False)
    ]

DEFAULT_SERVICE_INFO = [
    ("monfri", default_service_headways),
    ("sat", default_service_headways),
    ("sun", default_service_headways) ]

# Aim of this one is when using peak and off-peak speeds to represent network
# congestion, smooth out the peak-offpeak and vice-versa transitions, to avoid
# large spreading/bunching that can result from this.
ramped_service_headways = [
    (time(04,30), time(06,00), 20, False),
    (time(05,30), time(06,00), 10, False),
    (time(06,00), time(06,30), 7.5, False),
    (time(06,30), time(07,00), 5, False),
    (time(07,00), time(07,15), 4, False), # Special 'pre-peak injection'
    (time(07,15), time(07,30), 3, False), # Special 'pre-peak injection'
    (time(07,30), time(8,00), 5, True), 
    (time(8,00), time(8,40), 5, True), 
    (time(8,40), time(9,30), 7.5, True), 
    (time(9,30), time(10,00), 10, True), 
    (time(10,00), time(10,30), 10, False),
    (time(10,30), time(14,30), 10, False),
    (time(14,30), time(15,00), 7.5, False),
    (time(15,00), time(15,30), 5, False),
    (time(15,30), time(15,45), 4, False),# Special 'pre-peak injection'
    (time(15,45), time(16,00), 3, False),# Special 'pre-peak injection'
    (time(16,00), time(16,30), 5, True),
    (time(16,30), time(17,30), 5, True),
    (time(17,30), time(18,05), 6.5, True),
    (time(18,05), time(18,30), 7.5, True),
    (time(18,30), time(19,00), 7.5, False),
    (time(19,00), time(23,00), 10, False),
    (time(23,00), time(02,00), 20, False)
    ]

RAMPED_SERVICE_INFO = [
    ("monfri", ramped_service_headways),
    ("sat", ramped_service_headways),
    ("sun", ramped_service_headways) ]

# PDS: stop_prefix introduced 2014-05-07: to reflect Netview-based
#  convention to use a different prefix before different types of 
#  stops in relating trip segments to stop IDs.
# N.B. :- the 'system' entry is specific to GTFS logic, so generally
#  should be 'Subway', 'Tram', or 'Bus' - can't just make up any name.
settings = {
    'train': {
        'name': 'Metro Trains - Upgraded',
        'loc': 'Australia/Melbourne',
        'url': 'http://www.bze.org.au',
        'system': 'Subway',
        'avespeed': 65,
        'services_info': DEFAULT_SERVICE_INFO,
        'id': 30,
        'index': 3000000,
        'stop_prefix': 'TR',
    },
    'tram': {
        'name': 'Yarra Trams - Upgraded',
        'loc': 'Australia/Melbourne',
        'url': 'http://www.bze.org.au',
        'system': 'Tram',
        'avespeed': 35,
        'services_info': DEFAULT_SERVICE_INFO,
        'id': 32,
        'index': 3200000,
        'stop_prefix': 'TM',
    },
    'bus': {
        'name': 'Melbourne Bus - Upgraded',
        'loc': 'Australia/Melbourne',
        'url': 'http://www.bze.org.au',
        'system': 'Bus',
        'avespeed': 30,
        'services_info': RAMPED_SERVICE_INFO,
        'id': 34,
        'index': 3400000,
        'stop_prefix': 'B',
    },
    'bus-motorway': {
        'name': 'Melbourne Bus - Motorways',
        'loc': 'Australia/Melbourne',
        'url': 'http://www.bze.org.au',
        'system': 'Bus',
        'avespeed': 55,
        'avespeed-peak': 45,
        'services_info': RAMPED_SERVICE_INFO,
        'id': 36,
        'index': 3600000,
        'stop_prefix': 'N',
    },    
}

# These refs are necessary for setting appropriate speed for both bus and
# bus-motorway networks, which move between motorways and streets.
settings['bus']['on_motorway'] = settings['bus-motorway']
settings['bus-motorway']['on_street'] = settings['bus']

# These are plain strings, as required by the transitfeed library
START_DATE_STR = '20130101'
END_DATE_STR = '20141231'

def calc_total_service_time_elapsed(serv_headways, curr_time):
    first_period_start_time = serv_headways[0][0]
    tdiff = datetime.combine(date.today(), curr_time) \
        - datetime.combine(date.today(), first_period_start_time)
    if tdiff < timedelta(0):
        tdiff += timedelta(days=1)
    return tdiff

def calc_service_time_elapsed_end_period(serv_headways, period_num):
    tdiff = calc_total_service_time_elapsed(serv_headways,
        serv_headways[period_num][1])
    return tdiff

