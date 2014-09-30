
def str2bool(v):
    return v.lower() in ("yes", "true", "t", "1")

def getlist(list_string):
    if not list_string:
        parsed_list = []
    else:    
        parsed_list = list_string.split(',')
    return parsed_list
