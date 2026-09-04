# `clean_boundaries.sh`

Automatically cleans and preprocesses city boundary GeoJSON files for further downstream tasks.

The script asks the user for:

1. **Input boundary directory**
2. **Output directory**
3. **Buffer distance** in meters
4. **Output format**

   * `1` = NAD83 / UTM only
   * `2` = WGS84 only
   * `3` = Both

## Processing for Each City

For each boundary file, the script:

1. Converts the boundary to WGS84 (`EPSG:4326`)
2. Determines the UTM zone automatically
3. Selects the corresponding NAD83 / UTM CRS
4. Reprojects the boundary into that CRS
5. Makes geometries valid
6. Dissolves all features into one geometry
7. Applies the requested buffer in meters
8. Writes the requested output(s)

### NAD83 / UTM Output

* Uses projected coordinates
* Coordinates are in meters
* The appropriate UTM zone is selected automatically

### WGS84 Output

* Uses `EPSG:4326`
* Coordinates are longitude/latitude

**No city-specific EPSG list is required.**

# create_boundaries.py
