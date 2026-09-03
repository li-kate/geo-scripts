#!/usr/bin/env bash
#
# preprocess_boundaries.sh
#
# Automatically preprocess city boundary GeoJSON files.
#
# The script asks the user for:
#   1. Input boundary directory
#   2. Output directory
#   3. Buffer distance in meters
#   4. Output format:
#        1 = NAD83 / UTM only
#        2 = WGS84 only
#        3 = Both
#
# Processing for each city:
#   1. Convert boundary to WGS84 (EPSG:4326)
#   2. Determine UTM zone automatically
#   3. Select corresponding NAD83 / UTM CRS
#   4. Reproject into that CRS
#   5. Make geometries valid
#   6. Dissolve all features into one geometry
#   7. Apply the requested buffer in meters
#   8. Write the requested output(s)
#
# NAD83 / UTM output:
#   - projected coordinates
#   - coordinates are in meters
#
# WGS84 output:
#   - EPSG:4326
#   - coordinates are longitude/latitude
#
# No city-specific EPSG list is required.
#

set -euo pipefail


# ============================================================
# Ask for a parameter with a default value
# ============================================================

ask_with_default() {
    local prompt="$1"
    local default="$2"
    local answer

    read -r -p "$prompt [$default]: " answer

    if [[ -z "$answer" ]]; then
        echo "$default"
    else
        echo "$answer"
    fi
}


# ============================================================
# Get layer name
# ============================================================

get_layer_name() {
    local file="$1"

    ogrinfo -ro -q "$file" 2>/dev/null |
        sed -n 's/^[0-9][0-9]*: \([^ ]*\).*/\1/p' |
        head -n 1
}


# ============================================================
# Determine NAD83 / UTM EPSG automatically
#
# The source files are expected to contain longitude/latitude
# coordinates.
#
# The function:
#
#   1. Gets the geographic extent
#   2. Calculates the midpoint longitude
#   3. Calculates the UTM zone
#   4. Returns the corresponding NAD83 / UTM North EPSG
#
# NAD83 / UTM North:
#
#   EPSG = 26900 + UTM zone
#
# ============================================================

get_utm_epsg() {
    local in_file="$1"

    local extent
    extent="$(
        ogrinfo -ro -so -al "$in_file" 2>/dev/null |
        awk '
            /Extent:/ {
                gsub(/[(),]/, " ")
                print $2, $3, $5, $6
                exit
            }
        '
    )"

    if [[ -z "$extent" ]]; then
        echo "ERROR: Could not determine extent for $in_file" >&2
        return 1
    fi

    local minx miny maxx maxy
    read -r minx miny maxx maxy <<< "$extent"

    # Use the center longitude of the boundary.
    local center_lon
    center_lon=$(awk -v a="$minx" -v b="$maxx" 'BEGIN {print (a+b)/2}')

    # Determine UTM zone from longitude.
    local zone
    zone=$(awk -v lon="$center_lon" '
        BEGIN {
            z = int((lon + 180) / 6) + 1
            if (z < 1) z = 1
            if (z > 60) z = 60
            print z
        }
    ')

    # NAD83 / UTM North:
    # EPSG:26901 = NAD83 / UTM zone 1N
    # ...
    # EPSG:26960 = NAD83 / UTM zone 60N
    local epsg=$((26900 + zone))

    echo "$epsg"
}


# ============================================================
# Process one city
# ============================================================

process_city() {
    local input_file="$1"
    local city="$2"

    local projected_output_file="$NAD83_OUTPUT_DIR/$(basename "$input_file")"
    local wgs84_output_file="$WGS84_OUTPUT_DIR/$(basename "$input_file")"

    local layer_name
    local epsg
    local zone

    local temp_wgs84
    local temp_projected


    # --------------------------------------------------------
    # Basic information
    # --------------------------------------------------------

    echo
    echo "========================================"
    echo "Processing: $city"
    echo "Input:      $input_file"
    echo "Buffer:     ${BUFFER_METERS} m"
    echo "========================================"

    layer_name="$(get_layer_name "$input_file")"

    if [[ -z "$layer_name" ]]; then
        echo "Error: could not determine layer name."
        return 1
    fi

    echo "Layer:      $layer_name"


    # --------------------------------------------------------
    # Determine NAD83 / UTM CRS automatically
    # --------------------------------------------------------

    echo
    echo "  Determining appropriate NAD83 / UTM CRS..."

    if ! epsg="$(get_utm_epsg "$input_file")"; then
        echo "Error: could not determine appropriate UTM CRS."
        return 1
    fi

    zone=$((epsg - 26900))

    echo "  UTM zone:  $zone"
    echo "  NAD83 CRS: EPSG:$epsg"


    # --------------------------------------------------------
    # Temporary files
    # --------------------------------------------------------

    temp_wgs84="$(mktemp --suffix=.geojson)"
    temp_projected="$(mktemp --suffix=.geojson)"


    # --------------------------------------------------------
    # Cleanup helper
    # --------------------------------------------------------

    cleanup_city() {
        rm -f "$temp_wgs84"
        rm -f "$temp_projected"
    }


    # --------------------------------------------------------
    # Step 1:
    # Convert to WGS84
    # --------------------------------------------------------

    echo
    echo "  [1/3] Converting to WGS84..."

    rm -f "$temp_wgs84"

    if ! ogr2ogr \
        -f GeoJSON \
        "$temp_wgs84" \
        "$input_file" \
        -t_srs EPSG:4326 \
        -makevalid \
        -dim 2 \
        -nlt PROMOTE_TO_MULTI; then

        echo
        echo "Error: WGS84 conversion failed."

        cleanup_city
        return 1
    fi


    # --------------------------------------------------------
    # Step 2:
    # Reproject to NAD83 / UTM
    # --------------------------------------------------------

    echo
    echo "  [2/3] Reprojecting to NAD83 / UTM..."

    rm -f "$temp_projected"

    if ! ogr2ogr \
        -f GeoJSON \
        "$temp_projected" \
        "$temp_wgs84" \
        -t_srs "EPSG:$epsg" \
        -makevalid \
        -dim 2 \
        -nlt PROMOTE_TO_MULTI; then

        echo
        echo "Error: NAD83 reprojection failed."

        cleanup_city
        return 1
    fi


    # --------------------------------------------------------
    # Get projected layer name
    # --------------------------------------------------------

    local projected_layer

    projected_layer="$(get_layer_name "$temp_projected")"

    if [[ -z "$projected_layer" ]]; then
        echo
        echo "Error: could not determine projected layer name."

        cleanup_city
        return 1
    fi

    local escaped_projected_layer
    escaped_projected_layer="${projected_layer//\"/\"\"}"


    # --------------------------------------------------------
    # Step 3:
    # Dissolve + buffer
    #
    # The data is now in a projected CRS whose units are meters.
    #
    # ST_Collect:
    #   Combines all features.
    #
    # ST_UnaryUnion:
    #   Dissolves overlapping/touching polygons.
    #
    # ST_Buffer:
    #   Applies the requested buffer distance in meters.
    # --------------------------------------------------------

    echo
    echo "  [3/3] Dissolving polygons and applying ${BUFFER_METERS} m buffer..."

    # We ALWAYS create the projected temporary result first.
    # This ensures that if both outputs are requested, the WGS84
    # version is derived from the exact same buffered geometry.

    local temp_buffered_projected
    temp_buffered_projected="$(mktemp --suffix=.geojson)"

    rm -f "$temp_buffered_projected"

    if ! ogr2ogr \
        -f GeoJSON \
        "$temp_buffered_projected" \
        "$temp_projected" \
        -dialect SQLite \
        -sql "
            SELECT
                ST_Buffer(
                    ST_UnaryUnion(
                        ST_Collect(
                            ST_MakeValid(geometry)
                        )
                    ),
                    $BUFFER_METERS
                ) AS geometry
            FROM \"$escaped_projected_layer\"
        " \
        -nln merged_boundary \
        -nlt MULTIPOLYGON \
        -dim 2; then

        echo
        echo "Error: dissolve/buffer failed."

        rm -f "$temp_buffered_projected"
        cleanup_city
        return 1
    fi


    # --------------------------------------------------------
    # Output 1:
    # NAD83 / UTM
    # --------------------------------------------------------

    if [[ "$OUTPUT_MODE" == "1" || "$OUTPUT_MODE" == "3" ]]; then

        echo
        echo "  Writing NAD83 / UTM output..."

        rm -f "$projected_output_file"

        if ! ogr2ogr \
            -f GeoJSON \
            "$projected_output_file" \
            "$temp_buffered_projected" \
            -nln "$(basename "$projected_output_file" .geojson)" \
            -nlt MULTIPOLYGON \
            -dim 2; then

            echo
            echo "Error: failed to write NAD83 / UTM output."

            rm -f "$temp_buffered_projected"
            cleanup_city
            rm -f "$projected_output_file"

            return 1
        fi

        echo "  NAD83 output: $projected_output_file"
        echo "  CRS: EPSG:$epsg"
        echo "  Units: meters"
    fi


    # --------------------------------------------------------
    # Output 2:
    # WGS84
    #
    # Reproject the ALREADY BUFFERED projected geometry.
    # This means the 200 m buffer is performed in meters first.
    # --------------------------------------------------------

    if [[ "$OUTPUT_MODE" == "2" || "$OUTPUT_MODE" == "3" ]]; then

        echo
        echo "  Writing WGS84 output..."

        rm -f "$wgs84_output_file"

        if ! ogr2ogr \
            -f GeoJSON \
            "$wgs84_output_file" \
            "$temp_buffered_projected" \
            -t_srs EPSG:4326 \
            -nln "$(basename "$wgs84_output_file" .geojson)" \
            -nlt MULTIPOLYGON \
            -dim 2; then

            echo
            echo "Error: failed to write WGS84 output."

            rm -f "$temp_buffered_projected"
            cleanup_city
            rm -f "$wgs84_output_file"

            return 1
        fi

        echo "  WGS84 output: $wgs84_output_file"
        echo "  CRS: EPSG:4326"
        echo "  Units: degrees"
    fi


    # --------------------------------------------------------
    # Cleanup
    # --------------------------------------------------------

    rm -f "$temp_buffered_projected"
    cleanup_city


    # --------------------------------------------------------
    # Validate outputs
    # --------------------------------------------------------

    echo
    echo "  Checking output..."

    if [[ "$OUTPUT_MODE" == "1" || "$OUTPUT_MODE" == "3" ]]; then
        if ! ogrinfo -ro -q "$projected_output_file" >/dev/null 2>&1; then
            echo "  Warning: NAD83 output could not be opened by ogrinfo."
            return 1
        fi
    fi

    if [[ "$OUTPUT_MODE" == "2" || "$OUTPUT_MODE" == "3" ]]; then
        if ! ogrinfo -ro -q "$wgs84_output_file" >/dev/null 2>&1; then
            echo "  Warning: WGS84 output could not be opened by ogrinfo."
            return 1
        fi
    fi

    echo "  Output is valid."
    echo "  Buffer: ${BUFFER_METERS} m"

    return 0
}


# ============================================================
# Main
# ============================================================

echo
echo "========================================"
echo " Boundary Preprocessing"
echo "========================================"
echo


# ============================================================
# Check dependencies
# ============================================================

require_cmd() {
    command -v "$1" >/dev/null 2>&1
}

if ! require_cmd ogr2ogr; then
    echo "Error: ogr2ogr was not found on PATH."
    echo
    echo "Load GDAL before running this script."
    exit 1
fi

if ! require_cmd ogrinfo; then
    echo "Error: ogrinfo was not found on PATH."
    exit 1
fi


# ============================================================
# Ask for parameters
# ============================================================

INPUT_DIR="$(
    ask_with_default \
        "Enter input boundary directory" \
        "polygon_boundaries"
)"

OUTPUT_BASE_DIR="$(
    ask_with_default \
        "Enter output directory" \
        "boundaries"
)"

BUFFER_METERS="$(
    ask_with_default \
        "Enter buffer distance in meters" \
        "200"
)"


# ============================================================
# Ask for output format
# ============================================================

echo
echo "Output format:"
echo "  1) NAD83 / UTM only"
echo "     Projected coordinates in meters"
echo
echo "  2) WGS84 only"
echo "     EPSG:4326 longitude/latitude"
echo
echo "  3) Both"
echo "     Create both projected and WGS84 outputs"
echo

OUTPUT_MODE="$(
    ask_with_default \
        "Choose 1, 2, or 3" \
        "1"
)"


# ============================================================
# Validate output mode
# ============================================================

if [[ "$OUTPUT_MODE" != "1" &&
      "$OUTPUT_MODE" != "2" &&
      "$OUTPUT_MODE" != "3" ]]; then

    echo
    echo "Error: output format must be 1, 2, or 3."
    exit 1
fi


# ============================================================
# Set output directories
# ============================================================

case "$OUTPUT_MODE" in

    1)
        NAD83_OUTPUT_DIR="$OUTPUT_BASE_DIR/boundaries_nad83"
        WGS84_OUTPUT_DIR=""
        ;;

    2)
        NAD83_OUTPUT_DIR=""
        WGS84_OUTPUT_DIR="$OUTPUT_BASE_DIR/boundaries_wgs84"
        ;;

    3)
        NAD83_OUTPUT_DIR="$OUTPUT_BASE_DIR/boundaries_nad83"
        WGS84_OUTPUT_DIR="$OUTPUT_BASE_DIR/boundaries_wgs84"
        ;;

esac


# ============================================================
# Validate buffer
# ============================================================

if ! [[ "$BUFFER_METERS" =~ ^[0-9]+([.][0-9]+)?$ ]]; then
    echo
    echo "Error: buffer distance must be a positive number."
    exit 1
fi


# ============================================================
# Validate input directory
# ============================================================

if [[ ! -d "$INPUT_DIR" ]]; then
    echo
    echo "Error: input directory does not exist:"
    echo "  $INPUT_DIR"
    exit 1
fi


# ============================================================
# Create output directories
# ============================================================

if [[ -n "$NAD83_OUTPUT_DIR" ]]; then
    mkdir -p "$NAD83_OUTPUT_DIR"
fi

if [[ -n "$WGS84_OUTPUT_DIR" ]]; then
    mkdir -p "$WGS84_OUTPUT_DIR"
fi


# ============================================================
# Find boundary files
# ============================================================

BOUNDARY_FILES=()

while IFS= read -r -d '' file; do
    BOUNDARY_FILES+=("$file")
done < <(
    find "$INPUT_DIR" \
        -maxdepth 1 \
        -type f \
        -iname "*.geojson" \
        -print0 |
    sort -z
)


# ============================================================
# Check that files were found
# ============================================================

if [[ ${#BOUNDARY_FILES[@]} -eq 0 ]]; then
    echo
    echo "Error: no .geojson files found in:"
    echo "  $INPUT_DIR"
    exit 1
fi


# ============================================================
# Display parameters
# ============================================================

echo
echo "========================================"
echo " Parameters"
echo "========================================"
echo "Input directory:  $INPUT_DIR"
echo "Buffer distance:  ${BUFFER_METERS} m"
echo "Output mode:      $OUTPUT_MODE"
echo "Boundary files:   ${#BOUNDARY_FILES[@]}"
echo

case "$OUTPUT_MODE" in
    1)
        echo "NAD83 output:"
        echo "  $NAD83_OUTPUT_DIR"
        ;;
    2)
        echo "WGS84 output:"
        echo "  $WGS84_OUTPUT_DIR"
        ;;
    3)
        echo "NAD83 output:"
        echo "  $NAD83_OUTPUT_DIR"
        echo
        echo "WGS84 output:"
        echo "  $WGS84_OUTPUT_DIR"
        ;;
esac

echo "========================================"


# ============================================================
# Process all cities
# ============================================================

SUCCESSFUL=()
FAILED=()

for input_file in "${BOUNDARY_FILES[@]}"; do

    filename="$(basename "$input_file" .geojson)"

    if process_city "$input_file" "$filename"; then
        SUCCESSFUL+=("$filename")
    else
        FAILED+=("$filename")
    fi

done


# ============================================================
# Summary
# ============================================================

echo
echo
echo "========================================"
echo " Preprocessing complete"
echo "========================================"
echo

echo "Successful:"

if [[ ${#SUCCESSFUL[@]} -eq 0 ]]; then
    echo "  None"
else
    for city in "${SUCCESSFUL[@]}"; do
        echo "  $city"
    done
fi

echo

echo "Failed:"

if [[ ${#FAILED[@]} -eq 0 ]]; then
    echo "  None"
else
    for city in "${FAILED[@]}"; do
        echo "  $city"
    done
fi

echo

echo "Output base directory:"
echo "  $OUTPUT_BASE_DIR"

echo

if [[ ${#FAILED[@]} -gt 0 ]]; then
    exit 1
fi

echo "All boundaries processed successfully."