# import gpxpy
# import geojson

# # Path to your GPX file
# gpx_file = 'merged_snapped_routes.gpx'
# geojson_file = 'cool_time_biking_test_gps.geojson'

# # Load GPX
# with open(gpx_file, 'r') as f:
#     gpx = gpxpy.parse(f)

# # Collect all track points
# features = []
# for track in gpx.tracks:
#     for segment in track.segments:
#         for point in segment.points:
#             feature = geojson.Feature(
#                 geometry=geojson.Point((point.longitude, point.latitude)),
#                 properties={
#                     'ele': point.elevation,
#                     'time': point.time.isoformat() if point.time else None,
#                 }
#             )
#             features.append(feature)

# # Create GeoJSON FeatureCollection
# feature_collection = geojson.FeatureCollection(features)

# # Save to file
# with open(geojson_file, 'w') as f:
#     geojson.dump(feature_collection, f, indent=2)

# print(f"Saved {len(features)} points to {geojson_file}")
import gpxpy
import geojson

# Path to your matched GPX file
gpx_file = "../data/raw_data/Marietta St/5-7 PM (walking)/Marietta_GPS.gpx"
geojson_file = "marietta_raw.geojson"

# Load GPX
with open(gpx_file, "r") as f:
    gpx = gpxpy.parse(f)

features = []

for track in gpx.tracks:
    for segment in track.segments:
        # Collect all points in this segment
        coords = [(point.longitude, point.latitude) for point in segment.points]
        if len(coords) < 2:
            continue  # need at least 2 points for LineString
        feature = geojson.Feature(
            geometry=geojson.LineString(coords),
            properties={}
        )
        features.append(feature)

# If you want a single MultiLineString instead:
# multi_coords = [ [(p.longitude, p.latitude) for p in s.points] for t in gpx.tracks for s in t.segments ]
# feature = geojson.Feature(geometry=geojson.MultiLineString(multi_coords), properties={})
# features = [feature]

feature_collection = geojson.FeatureCollection(features)

# Save to file
with open(geojson_file, "w") as f:
    geojson.dump(feature_collection, f, indent=2)

print(f"Saved {len(features)} LineString features to {geojson_file}")

# import gpxpy
# import geojson

# # Path to your matched GPX file
# # gpx_file = "piedmont.gpx"
# # geojson_file = "piedmont.geojson"

# # Load GPX
# def convert_gpx_to_geojson(gpx_file, geojson_file):
#     with open(gpx_file, "r") as f:
#         gpx = gpxpy.parse(f)

#     features = []

#     for track in gpx.tracks:
#         for segment in track.segments:
#             # Collect all points in this segment
#             coords = [(point.longitude, point.latitude) for point in segment.points]
#             if len(coords) < 2:
#                 continue  # need at least 2 points for LineString
#             feature = geojson.Feature(
#                 geometry=geojson.LineString(coords),
#                 properties={}
#             )
#             features.append(feature)

#     # If you want a single MultiLineString instead:
#     # multi_coords = [ [(p.longitude, p.latitude) for p in s.points] for t in gpx.tracks for s in t.segments ]
#     # feature = geojson.Feature(geometry=geojson.MultiLineString(multi_coords), properties={})
#     # features = [feature]

#     feature_collection = geojson.FeatureCollection(features)

#     # Save to file
#     with open(geojson_file, "w") as f:
#         geojson.dump(feature_collection, f, indent=2)

#     print(f"Saved {len(features)} LineString features to {geojson_file}")
#     return geojson_file