"""Miscellaneous useful utility functions."""

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


