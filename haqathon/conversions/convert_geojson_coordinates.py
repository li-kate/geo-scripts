import geopandas as gpd

# Load your file
gdf = gpd.read_file("snapped_lines.geojson")

# Reproject to WGS84
gdf = gdf.to_crs(epsg=4326)

# Save new file
gdf.to_file("../../public/layers/smapped_lines_wgs84.geojson", driver="GeoJSON")

