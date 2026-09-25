import pandas as pd
import geopandas as gpd

# Read the track data (skip the waypoint section + header line)
df = pd.read_csv("../data/merged_data/marietta_test_13_merged.csv", skiprows=0)

# Clean up columns and drop empty rows
# df.columns = df.columns.str.strip()
# df = df.dropna(subset=["lat", "lon"])

# Convert to GeoDataFrame with Point geometry
gdf = gpd.GeoDataFrame(
    df,
    geometry=gpd.points_from_xy(df["longitude"], df["latitude"]),
    crs="EPSG:4326"
)

# Export to GeoJSON
gdf.to_file("marietta_test_13_before_links.geojson", driver="GeoJSON")

# print("✅ Created 'track_points.geojson' with one Point per GPS record.")

# import pandas as pd
# import geopandas as gpd
# import json
# import osmnx as ox

# # Read CSV
# df = pd.read_csv('../exploration/hot_diffs.csv')

# PLACE = "Atlanta, Georgia, USA"
# NETWORK_TYPE = "walk"  # or "bike"
# G = ox.graph_from_place(PLACE, network_type=NETWORK_TYPE)
# edges = ox.graph_to_gdfs(G, nodes=False, edges=True)  # edges with LineString geometry

# # ---- Convert edge_id in CSV to separate columns ----
# # edge_id format: "(u, v, key)"
# df[["u","v","key"]] = df["edge_id"].apply(
#     lambda x: pd.Series([int(i) for i in x.strip("()").split(",")])
# )

# # ---- Merge CSV with OSM edges ----
# edges_gdf = edges.merge(df, on=["u","v","key"])

# # ---- Export LineString GeoJSON ----
# edges_gdf.to_file('hot_diffs_walking_biking.geojson', driver='GeoJSON')



# """
# Testing the Snapped Points to the Noisy Raw Data
# """
# # --- GPS Layer ---
# # gps_features = [
# #     {
# #         "type": "Feature",
# #         "geometry": {
# #             "type": "Point",
# #             "coordinates": [row['longitude'], row['latitude']]
# #         },
# #         "properties": row.drop(['longitude', 'latitude']).to_dict()
# #     }
# #     for _, row in df.iterrows()
# # ]

# # gps_geojson = {"type": "FeatureCollection", "features": gps_features}
# # with open('TEST_GPS_points.geojson', 'w') as f:
# #     json.dump(gps_geojson, f, indent=2)


# # # --- Snapped Layer ---
# # snapped_features = [
# #     {
# #         "type": "Feature",
# #         "geometry": {
# #             "type": "Point",
# #             "coordinates": [row['route_longitude'], row['route_latitude']]
# #         },
# #         "properties": row.drop(['route_longitude', 'route_latitude']).to_dict()
# #     }
# #     for _, row in df.iterrows()
# # ]

# # snapped_geojson = {"type": "FeatureCollection", "features": snapped_features}
# # with open('TEST_Snapped_points.geojson', 'w') as f:
# #     json.dump(snapped_geojson, f, indent=2)

# # print("Exported TEST_GPS_points.geojson and TEST_Snapped_points.geojson")
