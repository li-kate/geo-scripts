import os
import glob
import geopandas as gpd
import pandas as pd

FOLDER = "/storage/scratch1/1/kli605/safe_routes/extracted-stations/bus"
OUTPUT = os.path.join(FOLDER, "bus.geojson")

# Maps source filename to the column(s) holding the stop name
NAME_MAP = {
    "Miami_bus_stops": "StopName",
    "Miami_rail_stations": "NAME",
    "NYC_bus_stops": "DESCRIPTION_BSL",
    "NYC_rail_stations": "STATION_ID",
    "Philadelphia_bus_stops": "StopName",
    "Philadelphia_rail_stations": ["Station_Na", "StopName"],
    "Seattle_bus_stops": "HASTUS_CROSS_STREET_NAME",
    "Seattle_rail_stations": "NAME",
    "Houston_bus_stops": "STOPNAME",
    "Houston_rail_stations": "Stat_Name",
    "SF_bus_stops": "stop_name",
    "SF_rail_stations": "stop_name",
    "Atlanta_bus_stops": "stop_name",
    "Atlanta_rail_stations": "STATION",
    "Boston_rail_stations": "stop_name",
    "Los_Angeles_bus_stops": "stop_name",
    "Los_Angeles_rail_stations": "stop_name",
    "Dallas_bus_stops": "stop_name",
    "Dallas_rail_stations": "stop_name",
}

files = glob.glob(os.path.join(FOLDER, "*.geojson"))

gdfs = []
for f in files:
    gdf = gpd.read_file(f)
    key = os.path.basename(f).replace(".geojson", "")
    gdf["source_file"] = key

    if key in NAME_MAP:
        col = NAME_MAP[key]
        if isinstance(col, list):
            # use first non-null value across the listed columns
            gdf["stop_name"] = gdf[col].bfill(axis=1).iloc[:, 0]
        else:
            gdf["stop_name"] = gdf[col]
    else:
        print(f"  WARNING: no name mapping for {key}, stop_name will be null")
        gdf["stop_name"] = None

    gdfs.append(gdf)
    print(f"  Loaded {key}: {len(gdf)} features")

if gdfs:
    merged = pd.concat(gdfs, ignore_index=True)
    merged = gpd.GeoDataFrame(merged, crs=gdfs[0].crs)
    merged.to_file(OUTPUT, driver="GeoJSON")
    print(f"\nMerged {len(merged)} total features → {OUTPUT}")
else:
    print("No geojson files found.")