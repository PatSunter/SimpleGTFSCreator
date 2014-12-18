from datetime import datetime, date, time, timedelta

TODAY = date.today()

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
TP_START_COL = 0
TP_END_COL = 1
HWAY_COL = 2
PEAK_STATUS_COL = 3
default_service_headways = [
    (time(05,00), time(07,30), 20, False),
    (time(07,30), time(10,00), 5, True), 
    (time(10,00), time(16,00), 10, False),
    (time(16,00), time(18,30), 5, True),
    (time(18,30), time(23,00), 10, False),
    (time(23,00), time(02,00), 20, False)
    ]

DEFAULT_TRAINS_SERVICE_INFO = [
    ("monfri", default_service_headways),
    ("sat", default_service_headways),
    ("sun", default_service_headways) ]

# Using 'monthur', 'fri', and 'monfri' to copy PTV's for trams currently.
# (Individual routes have either first pair, or latter)
DEFAULT_TRAMS_SERVICE_INFO = [
    ("monthur", default_service_headways),
    ("monfri", default_service_headways),
    ("fri", default_service_headways),
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
        'maxspeed': 100,
        'accel': 1.0,
        'stop_dwell_time': 30,
        'avespeed': 65,
        'avespeed-peak': 50,
        'services_info': DEFAULT_TRAINS_SERVICE_INFO,
        'id': 30,
        'index': 3000000,
        #'id': 40,
        #'index': 4000000,
        'route_prefix': 'TR',
        'stop_prefix': 'TR',
    },
    'tram': {
        'name': 'Yarra Trams - Upgraded',
        'loc': 'Australia/Melbourne',
        'url': 'http://www.bze.org.au',
        'system': 'Tram',
        'maxspeed': 80,
        'accel': 1.2,
        'stop_dwell_time': 15,
        'avespeed': 35,
        'avespeed-peak': 15,
        'services_info': DEFAULT_TRAMS_SERVICE_INFO,
        'id': 32,
        'index': 3200000,
        #'id': 42,
        #'index': 4200000,
        'route_prefix': 'TM',
        'stop_prefix': 'TM',
    },
    'bus': {
        'name': 'Melbourne Bus - Upgraded',
        'loc': 'Australia/Melbourne',
        'url': 'http://www.bze.org.au',
        'system': 'Bus',
        'maxspeed': 60,
        'accel': 1.0,
        'stop_dwell_time': 20,
        'avespeed': 30,
        'avespeed-peak': 15,
        'services_info': RAMPED_SERVICE_INFO,
        'id': 44,
        'index': 4400000,
        'route_prefix': 'R',
        'stop_prefix': 'B',
        # Dist used to decide if segments are considered 'on motorway'
        # for speed purposes
        'on_motorway_seg_check_dist': 100,
        'min_seg_length_on_motorways': 650,
    },
    'bus-smartbus': {
        'name': 'Melbourne Bus - Upgraded - Smartbus',
        'loc': 'Australia/Melbourne',
        'url': 'http://www.bze.org.au',
        'system': 'Bus',
        'maxspeed': 60,
        'accel': 1.0,
        'stop_dwell_time': 20,
        'avespeed': 30,
        'avespeed-peak': 15,
        'services_info': RAMPED_SERVICE_INFO,
        'id': 45,
        'index': 4500000,
        'route_prefix': 'R',
        'stop_prefix': 'B',
        # Dist used to decide if segments are considered 'on motorway'
        # for speed purposes
        'on_motorway_seg_check_dist': 100,
        'min_seg_length_on_motorways': 650,
    },
    'bus-motorway': {
        'name': 'Melbourne Bus - Motorways',
        'loc': 'Australia/Melbourne',
        'url': 'http://www.bze.org.au',
        'system': 'Bus',
        'maxspeed': 100,
        'accel': 1.0,
        'stop_dwell_time': 20,
        'avespeed': 55,
        'avespeed-peak': 45,
        'services_info': RAMPED_SERVICE_INFO,
        'id': 46,
        'index': 4600000,
        'route_prefix': 'M',
        'stop_prefix': 'N',
        'on_motorway_seg_check_dist': 80,
        'min_seg_length_on_motorways': 300,
    },
}

# These refs are necessary for setting appropriate speed for both bus and
# bus-motorway networks, which move between motorways and streets.
settings['bus']['on_motorway'] = settings['bus-motorway']
settings['bus-smartbus']['on_motorway'] = settings['bus-motorway']
settings['bus-motorway']['on_street'] = settings['bus']

# These are plain strings, as required by the transitfeed library
START_DATE_STR = '20130101'
END_DATE_STR = '20141231'

def calc_total_service_time_elapsed(serv_headways, curr_time):
    first_period_start_time = serv_headways[0][TP_START_COL]
    tdiff = datetime.combine(TODAY, curr_time) \
        - datetime.combine(TODAY, first_period_start_time)
    if tdiff < timedelta(0):
        tdiff += timedelta(days=1)
    return tdiff

def calc_service_time_elapsed_end_period(serv_headways, period_num):
    tdiff = calc_total_service_time_elapsed(serv_headways,
        serv_headways[period_num][TP_END_COL])
    return tdiff

def get_freq_at_time(service_headways, time_of_day):
    for headway_period in service_headways:
        if time_of_day >= headway_period[TP_START_COL] and \
            time_of_day <= headway_period[TP_END_COL]:
            return headway_period[HWAY_COL]
    return None

def get_nearest_next_valid_freq_and_time(service_headways, time_of_day):
    valid_hway = None
    valid_hway_time = None
    for hp_i, headway_period in enumerate(service_headways):
        if time_of_day >= headway_period[TP_START_COL] and \
            time_of_day <= headway_period[TP_END_COL]:
            hp_start_i = hp_i
    
    for hp_i in range(hp_start_i, len(service_headways)):
        headway_period = service_headways[hp_i]
        hway = headway_period[HWAY_COL]
        if hway > 0:
            valid_hway = hway
            if hp_i == hp_start_i:
                valid_hway_time = time_of_day
            else:
                valid_hway_time = headway_period[TP_START_COL]
            break
    return valid_hway, valid_hway_time

