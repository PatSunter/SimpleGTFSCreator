
# Lat, long of Melbourne's origin in EPSG:4326 (WGS 84 on WGS 84 datum)
# Cnr of Bourke & Swanston
#ORIGIN_LAT_LON = (-37.81348, 144.96558) 
# As provided by Laurent in function - works out at N-E corner of CBD grid
#ORIGIN_LAT_LON = (-37.809176, 144.970653)
# As calculated by converting allnodes.csv[0] from EPSG:28355 to EPSG:4326
MELB_ORIGIN_LAT_LON = (-37.81081208860423, 144.969328103266179)

def peak_speed_func(Z_km):
    """Formula used as provided by Laurent Allieres, 7 Nov 2013.
    Modified by Pat S, 2014/10/17, to cut off dist from city centre at max
    50km - otherwise inappropriate values result."""
    Z_km = min(Z_km, 50)
    peak_speed = (230 + 15 * Z_km - 0.13 * Z_km**2) * 60/1000.0 * (2/3.0) \
        + 5.0/(Z_km/50.0+1)
    return peak_speed


