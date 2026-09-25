import json
import geojson
from shapely.geometry import LineString, mapping


def edge_cache_to_geojson(cache_path: str):
    """
    Convert GraphHopper edge geometry cache into GeoJSON FeatureCollection.
    """
    with open(cache_path, "r") as f:
        cache = json.load(f)

    features = []

    for edge_id, coords in cache.items():
        # Skip invalid geometries
        if not coords or len(coords) < 2:
            continue

        if len(set(map(tuple, coords))) < 2:
            continue

        features.append(
            geojson.Feature(
                geometry=mapping(LineString(coords)),
                properties={"gh_edge_id": int(edge_id)}
            )
        )

    return geojson.FeatureCollection(features)

fc = edge_cache_to_geojson("../data/cache/edge_geometries.json")

with open("edge_geometries.geojson", "w") as f:
    geojson.dump(fc, f, indent=2)