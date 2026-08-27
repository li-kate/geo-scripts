import os
import glob
import geopandas as gpd
from shapely.geometry import Polygon

# -----------------------------
# CONFIG
# -----------------------------
CITIES_FILE = "/storage/scratch1/1/kli605/safe_routes/final/boundaries.geojson"
DATA_DIR = "/storage/scratch1/1/kli605/safe_routes/stations"
OUTPUT_DIR = "extracted-stations"

DATA_TYPES = {
    "bus_stops": "_bus.geojson",
    "rail_stations": "_rail.geojson",
}

os.makedirs(OUTPUT_DIR, exist_ok=True)

# -----------------------------
# HELPERS
# -----------------------------
def normalize_city(name: str) -> str:
    """
    Converts:
    Los_Angeles-260503-UTCI.osm-sorted
    → Los_Angeles
    """
    return name.split("-")[0]

def normalize_file_city(filename: str) -> str:
    """
    Converts:
    Los_Angeles_bus.geojson
    → Los_Angeles
    """
    for suffix in DATA_TYPES.values():
        filename = filename.replace(suffix, "")
    return filename

# -----------------------------
# LOAD CITIES
# -----------------------------
cities = gpd.read_file(CITIES_FILE).to_crs(epsg=4326)

# Convert LineString boundaries to Polygons
cities["geometry"] = cities["geometry"].apply(
    lambda g: Polygon(g) if g.geom_type == "LineString" else g
)

# -----------------------------
# INDEX ALL DATA FILES
# -----------------------------
all_files = glob.glob(os.path.join(DATA_DIR, "*.geojson"))

file_index = {}
for f in all_files:
    base = os.path.basename(f)
    city_key = normalize_file_city(base)
    for dtype, suffix in DATA_TYPES.items():
        if suffix in base:
            file_index.setdefault(city_key, {})[dtype] = f

# -----------------------------
# PROCESS EACH CITY
# -----------------------------
for _, city in cities.iterrows():
    raw_city_name = city["city"]
    city_name = normalize_city(raw_city_name)
    city_geom = city.geometry

    print(f"\nProcessing: {raw_city_name} → {city_name}")

    # skip if no matching dataset
    if city_name not in file_index:
        print(f"  No matching files for {city_name}")
        continue

    # -----------------------------
    # PROCESS EACH TRANSPORT TYPE
    # -----------------------------
    for dtype, path in file_index[city_name].items():
        gdf = gpd.read_file(path).to_crs(epsg=4326)

        # quick bbox filter (speed optimization)
        gdf = gdf[gdf.intersects(city_geom.envelope)]

        # clip to actual boundary
        clipped = gpd.clip(gdf, city_geom)

        out_path = os.path.join(OUTPUT_DIR, f"{city_name}_{dtype}.geojson")
        if not clipped.empty:
            clipped.to_file(out_path, driver="GeoJSON")
            print(f"  Saved {dtype}: {len(clipped)} features")
        else:
            print(f"  No {dtype} features in {city_name}")

print("\nDone.")