
def str2bool(v):
    return v.lower() in ("yes", "true", "t", "1")

def getlist(list_string):
    if not list_string:
        parsed_list = []
    else:    
        parsed_list = list_string.split(',')
    return parsed_list

def td_str_to_td(td_str):
    """Reads in a timedelta in the format HH:MM"""
    td_parts = td_str.split(':')
    if len(td_parts) != 2:
        raise ValueError
    td_hrs = int(td_parts[0])
    td_mins = int(td_parts[1])
    td = timedelta(hours=td_hrs, minutes=td_mins)
    return td
