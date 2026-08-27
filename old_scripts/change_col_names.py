import geopandas as gpd
import re

gdf = gpd.read_file("Atlanta-062226_UTCI_alltime.geojson")

def rename_column(col):
    m = re.fullmatch(r"UTCI_(\d{1,2})(am|pm)", col)
    if not m:
        return col  # Leave NDVI and *_scale columns unchanged

    hour = int(m.group(1))
    period = m.group(2)

    if period == "am":
        hour24 = 0 if hour == 12 else hour
    else:  # pm
        hour24 = 12 if hour == 12 else hour + 12

    return f"UTCI_{hour24:02d}"

gdf.rename(columns={col: rename_column(col) for col in gdf.columns}, inplace=True)

gdf.to_file("output.geojson", driver="GeoJSON")