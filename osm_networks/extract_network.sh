#!/usr/bin/env bash

set -euo pipefail

# ---------- helpers ----------

ask() {
    # ask "prompt text" "default value (optional)"
    local prompt="$1"
    local default="${2:-}"
    local reply
    if [[ -n "$default" ]]; then
        if ! read -r -p "$prompt [$default]: " reply; then
            echo "$default"
            return
        fi
        echo "${reply:-$default}"
    else
        if ! read -r -p "$prompt: " reply; then
            echo
            echo "Error: reached end of input while waiting for an answer to:" >&2
            echo "  $prompt" >&2
            echo "If you're running this non-interactively (e.g. via sbatch with an" >&2
            echo "answers file), that file is missing an answer at this point -- check" >&2
            echo "the number and order of lines against what the script actually asks." >&2
            exit 1
        fi
        echo "$reply"
    fi
}

confirm() {
    # confirm "question" -> returns 0 for yes, 1 for no
    local prompt="$1"
    local reply
    while true; do
        if ! read -r -p "$prompt [y/n]: " reply; then
            echo
            echo "Error: reached end of input while waiting for a y/n answer to:" >&2
            echo "  $prompt" >&2
            echo "If you're running this non-interactively (e.g. via sbatch with an" >&2
            echo "answers file), that file is missing an answer at this point -- check" >&2
            echo "the number and order of lines against what the script actually asks." >&2
            exit 1
        fi
        case "$reply" in
            [Yy]|[Yy][Ee][Ss]) return 0 ;;
            [Nn]|[Nn][Oo]) return 1 ;;
            *) echo "Please answer y or n." ;;
        esac
    done
}

check_or_skip_overwrite() {
    # check_or_skip_overwrite "path" ["force"]
    # returns 0 if we should proceed (file doesn't exist, force=true, or user said overwrite)
    # returns 1 if we should skip this step (file exists, user said keep it)
    local f="$1"
    local force="${2:-false}"
    if [[ -e "$f" ]]; then
        if [[ "$force" == "true" ]]; then
            return 0
        fi
        echo "File already exists: $f"
        if confirm "Overwrite it?"; then
            return 0
        else
            echo "Keeping existing file, skipping this step."
            return 1
        fi
    fi
    return 0
}

require_cmd() {
    command -v "$1" >/dev/null 2>&1
}

# checkbox_menu: present a numbered list, let user pick multiple by comma-separated
# numbers, "all" for everything, or press Enter to accept the marked default(s).
#
# Usage:
#   checkbox_menu "Prompt to show" "1" opt1 opt2 opt3 ...
#     - 2nd arg = comma-separated indices (1-based) that are selected by default
#     - remaining args = the option labels, in order
#   Result is echoed as a comma-separated list of the CHOSEN LABELS.
checkbox_menu() {
    # NOTE: everything except the final result line is printed to STDERR,
    # because callers capture this function's output via $(...) and only
    # want the comma-separated selection on stdout.
    local prompt="$1"
    local default_indices="$2"
    shift 2
    local -a options=("$@")
    local n=${#options[@]}
    local i

    echo "$prompt" >&2
    for ((i = 0; i < n; i++)); do
        local marker=""
        if [[ ",${default_indices}," == *",$((i+1)),"* ]]; then
            marker=" (default)"
        fi
        printf "  %d) %s%s\n" "$((i+1))" "${options[$i]}" "$marker" >&2
    done

    local reply
    if ! read -r -p "Enter numbers separated by commas, 'all', or press Enter for default: " reply; then
        reply=""
    fi

    local -a chosen_idx=()
    if [[ -z "$reply" ]]; then
        IFS=',' read -r -a chosen_idx <<< "$default_indices"
    elif [[ "$reply" == "all" ]]; then
        for ((i = 1; i <= n; i++)); do chosen_idx+=("$i"); done
    else
        IFS=',' read -r -a chosen_idx <<< "$reply"
    fi

    local -a chosen_labels=()
    for idx in "${chosen_idx[@]}"; do
        idx="$(echo "$idx" | xargs)"  # trim whitespace
        if [[ "$idx" =~ ^[0-9]+$ ]] && (( idx >= 1 && idx <= n )); then
            chosen_labels+=("${options[$((idx-1))]}")
        fi
    done

    local IFS=','
    echo "${chosen_labels[*]}"
}

# run_filter_export: shared by single- and batch-mode.
# Given an extracted .osm.pbf, apply the (already-chosen) tag filter and
# GeoJSON export settings, honoring the global FORCE_OVERWRITE flag.
#
#   run_filter_export <extract_pbf> <filtered_out> <geojson_out>
run_filter_export() {
    local extract_pbf="$1"
    local filtered_out="$2"
    local geojson_out="$3"

    if check_or_skip_overwrite "$filtered_out" "$FORCE_OVERWRITE"; then
        local ow_flag=""
        [[ -e "$filtered_out" ]] && ow_flag="--overwrite"
        echo "Running: osmium tags-filter $extract_pbf ${FILTER_EXPRESSIONS[*]} -o $filtered_out $ow_flag"
        osmium tags-filter "$extract_pbf" "${FILTER_EXPRESSIONS[@]}" -o "$filtered_out" $ow_flag
    else
        echo "Using existing filtered file: $filtered_out"
    fi

    if check_or_skip_overwrite "$geojson_out" "$FORCE_OVERWRITE"; then
        local ow_flag=""
        [[ -e "$geojson_out" ]] && ow_flag="--overwrite"
        if [[ "$UID_MODE" == "none" ]]; then
            echo "Running: osmium export $filtered_out -o $geojson_out --attributes=$ATTR_STRING $ow_flag"
            osmium export "$filtered_out" \
                -o "$geojson_out" \
                --attributes="$ATTR_STRING" $ow_flag
        else
            echo "Running: osmium export $filtered_out -o $geojson_out --add-unique-id=$UID_MODE --attributes=$ATTR_STRING $ow_flag"
            osmium export "$filtered_out" \
                -o "$geojson_out" \
                --add-unique-id="$UID_MODE" \
                --attributes="$ATTR_STRING" $ow_flag
        fi
    else
        echo "Using existing GeoJSON: $geojson_out"
    fi
}

echo "=== Geofabrik -> osmium pipeline ==="
echo

FORCE_OVERWRITE="false"

# ---------- Step 1: Get source .osm.pbf ----------

echo "--- Step 1: Source .osm.pbf ---"

SOURCE_CHOICE=$(ask "Do you want to (download) a fresh extract from Geofabrik, or (local) use a .osm.pbf you already have?" "download")

case "$SOURCE_CHOICE" in
    download)
        echo "Browse available extracts at: https://download.geofabrik.de/"
        echo "(Find your region/sub-region and copy the direct .osm.pbf download link.)"
        echo

        DOWNLOAD_URL=$(ask "Paste the full Geofabrik .osm.pbf URL")
        PBF_FILENAME=$(basename "$DOWNLOAD_URL")

        if [[ -z "$DOWNLOAD_URL" || "$PBF_FILENAME" != *.osm.pbf ]]; then
            echo "Error: that doesn't look like a .osm.pbf URL. Exiting."
            exit 1
        fi

        if check_or_skip_overwrite "$PBF_FILENAME"; then
            echo "Downloading $PBF_FILENAME ..."
            if require_cmd wget; then
                wget --progress=bar:force:noscroll -O "$PBF_FILENAME" "$DOWNLOAD_URL"
            elif require_cmd curl; then
                curl -L -o "$PBF_FILENAME" "$DOWNLOAD_URL"
            else
                echo "Error: neither wget nor curl is available. Install one and re-run."
                exit 1
            fi
        else
            echo "Using existing file: $PBF_FILENAME"
        fi
        ;;
    local)
        PBF_FILENAME=$(ask "Path to your existing .osm.pbf file")
        if [[ ! -f "$PBF_FILENAME" ]]; then
            echo "Error: file '$PBF_FILENAME' not found. Exiting."
            exit 1
        fi
        if [[ "$PBF_FILENAME" != *.osm.pbf && "$PBF_FILENAME" != *.pbf ]]; then
            if ! confirm "That file doesn't end in .pbf / .osm.pbf. Continue anyway?"; then
                exit 1
            fi
        fi
        echo "Using local file: $PBF_FILENAME"
        ;;
    *)
        echo "Error: unrecognized choice '$SOURCE_CHOICE' (expected 'download' or 'local'). Exiting."
        exit 1
        ;;
esac
echo

# ---------- Step 2: Set up osmium-tool ----------

echo "--- Step 2: Set up osmium-tool ---"

if require_cmd osmium; then
    echo "osmium is already on PATH ($(command -v osmium)). Skipping environment setup."
else
    if ! require_cmd conda; then
        echo "conda not found on PATH."
        if confirm "Are you on PACE and need to run 'module load anaconda3' first?"; then
            echo "Run this manually before continuing, then re-run this script:"
            echo "  module load anaconda3"
            exit 1
        else
            echo "Please install conda (or make osmium available on PATH) and re-run."
            exit 1
        fi
    fi

    ENV_NAME=$(ask "Name for the conda environment to use for osmium" "osmium_env")

    # shellcheck disable=SC1091
    source "$(conda info --base)/etc/profile.d/conda.sh"

    if conda env list | awk '{print $1}' | grep -qx "$ENV_NAME"; then
        echo "Conda environment '$ENV_NAME' already exists. Skipping creation."
    else
        if confirm "Environment '$ENV_NAME' does not exist yet. Create it now (conda create -n $ENV_NAME -c conda-forge osmium-tool)?"; then
            conda create -y -n "$ENV_NAME" -c conda-forge osmium-tool
        else
            echo "Cannot proceed without osmium-tool. Exiting."
            exit 1
        fi
    fi

    echo "Activating conda environment '$ENV_NAME'..."
    conda activate "$ENV_NAME"

    if ! require_cmd osmium; then
        echo "Error: osmium still not found after activating '$ENV_NAME'. Exiting."
        exit 1
    fi
fi

echo "Using osmium: $(osmium --version | head -n 1)"
echo

# ---------- Step 3: Choose single-area or batch mode ----------

echo "--- Step 3: Extract area(s) from $PBF_FILENAME ---"
echo "You can either:"
echo "  1) single -- extract ONE area, via a bounding box or ONE preprocessed WGS84 polygon file"
echo "  2) batch  -- extract ONE area PER preprocessed WGS84 boundary file in a directory"
echo

AREA_MODE=$(ask "Choose 'single' or 'batch'" "single")

case "$AREA_MODE" in

    single)
        EXTRACT_METHOD=$(ask "Choose extraction method: 'bbox' or 'polygon'" "bbox")

        EXTRACT_OUTPUT=$(ask "Output filename for the extracted area (e.g. seattle-051426.osm.pbf)")
        if [[ -z "$EXTRACT_OUTPUT" ]]; then
            echo "Error: output filename is required. Exiting."
            exit 1
        fi

        STRATEGY=$(ask "osmium extract strategy (-s flag): 'simple', 'complete_ways', or 'smart'" "smart")

        if check_or_skip_overwrite "$EXTRACT_OUTPUT"; then
            ow_flag=""
            [[ -e "$EXTRACT_OUTPUT" ]] && ow_flag="--overwrite"
            case "$EXTRACT_METHOD" in
                bbox)
                    BBOX=$(ask "Enter bounding box as min_lon,min_lat,max_lon,max_lat")
                    if [[ -z "$BBOX" ]]; then
                        echo "Error: bounding box is required for this method. Exiting."
                        exit 1
                    fi
                    echo "Running: osmium extract -b $BBOX $PBF_FILENAME -o $EXTRACT_OUTPUT -s $STRATEGY $ow_flag"
                    osmium extract -b "$BBOX" "$PBF_FILENAME" -o "$EXTRACT_OUTPUT" -s "$STRATEGY" $ow_flag
                    ;;
                polygon)
                    POLY_FILE=$(ask "Path to the preprocessed WGS84 polygon file (e.g. boundaries_wgs84/Atlanta.geojson)")
                    if [[ ! -f "$POLY_FILE" ]]; then
                        echo "Error: polygon file '$POLY_FILE' not found. Exiting."
                        exit 1
                    fi
                    echo "Running: osmium extract --polygon $POLY_FILE $PBF_FILENAME -o $EXTRACT_OUTPUT -s $STRATEGY $ow_flag"
                    osmium extract --polygon "$POLY_FILE" "$PBF_FILENAME" -o "$EXTRACT_OUTPUT" -s "$STRATEGY" $ow_flag
                    ;;
                *)
                    echo "Error: unrecognized extraction method '$EXTRACT_METHOD' (expected 'bbox' or 'polygon'). Exiting."
                    exit 1
                    ;;
            esac
        else
            echo "Using existing extract: $EXTRACT_OUTPUT"
        fi
        ;;

    batch)
        BOUNDARY_DIR=$(ask \
            "Path to the directory containing preprocessed WGS84 boundary files" \
            "boundaries/boundaries_wgs84"
        )

        if [[ ! -d "$BOUNDARY_DIR" ]]; then
            echo "Error: directory '$BOUNDARY_DIR' not found. Exiting."
            exit 1
        fi

        BOUNDARY_PATTERN=$(ask "Filename pattern for boundary files in that directory" "*.geojson")

        # Collect matching files (portable against spaces in filenames).
        BOUNDARY_FILES=()
        while IFS= read -r -d '' f; do
            BOUNDARY_FILES+=("$f")
        done < <(find "$BOUNDARY_DIR" -maxdepth 1 -type f -name "$BOUNDARY_PATTERN" -print0 | sort -z)

        if [[ ${#BOUNDARY_FILES[@]} -eq 0 ]]; then
            echo "Error: no files matching '$BOUNDARY_PATTERN' found in '$BOUNDARY_DIR'. Exiting."
            exit 1
        fi

        echo "Found ${#BOUNDARY_FILES[@]} boundary file(s):"
        for f in "${BOUNDARY_FILES[@]}"; do
            echo "  - $(basename "$f")"
        done
        if ! confirm "Proceed with these ${#BOUNDARY_FILES[@]} boundaries?"; then
            echo "Aborting."
            exit 1
        fi

        OUTPUT_DIR=$(ask "Base output directory for batch results" "network_output")
        EXTRACT_DIR="$OUTPUT_DIR/extracted"
        FILTERED_DIR="$OUTPUT_DIR/filtered"
        GEOJSON_DIR="$OUTPUT_DIR/geojson"

        mkdir -p "$EXTRACT_DIR" "$FILTERED_DIR" "$GEOJSON_DIR"

        STRATEGY=$(ask "osmium extract strategy (-s flag) to use for every boundary: 'simple', 'complete_ways', or 'smart'" "smart")

        if confirm "Overwrite any existing output files without asking each time? (recommended for batch runs)"; then
            FORCE_OVERWRITE="true"
        fi
        ;;

    *)
        echo "Error: unrecognized choice '$AREA_MODE' (expected 'single' or 'batch'). Exiting."
        exit 1
        ;;
esac
echo

# ---------- Step 4: Filter by tags (chosen once, applied to every area) ----------

echo "--- Step 4: Filter the network by tags ---"

FILTER_OPTIONS=(
    "highway-ways      w/highway -- ways with a highway tag (the default road network filter)"
    "highway-nodes     n/highway -- nodes with a highway tag e.g. traffic signals / stop signs"
    "railway           w/railway -- ways with a railway tag"
    "waterway          w/waterway -- ways with a waterway tag"
    "buildings         w/building + a/building -- building ways and areas"
    "route-relations   r/type=route -- route relations e.g. bus/bike routes"
    "custom            type in my own osmium tags-filter expression(s)"
)

FILTER_SELECTION=$(checkbox_menu "Select which tag filter(s) to apply:" "1" "${FILTER_OPTIONS[@]}")

# Build the actual list of osmium tags-filter expressions from the selection.
# Each label's FIRST whitespace-delimited token is a stable key we match on.
declare -a FILTER_EXPRESSIONS=()
IFS=',' read -r -a SELECTED_LABELS <<< "$FILTER_SELECTION"
for label in "${SELECTED_LABELS[@]}"; do
    key=$(echo "$label" | awk '{print $1}')
    case "$key" in
        highway-ways)    FILTER_EXPRESSIONS+=("w/highway") ;;
        highway-nodes)   FILTER_EXPRESSIONS+=("n/highway") ;;
        railway)         FILTER_EXPRESSIONS+=("w/railway") ;;
        waterway)        FILTER_EXPRESSIONS+=("w/waterway") ;;
        buildings)       FILTER_EXPRESSIONS+=("w/building" "a/building") ;;
        route-relations) FILTER_EXPRESSIONS+=("r/type=route") ;;
        custom)
            CUSTOM=$(ask "Enter custom osmium tags-filter expression(s), space-separated (e.g. w/highway w/public_transport)")
            if [[ -n "$CUSTOM" ]]; then
                # shellcheck disable=SC2206
                FILTER_EXPRESSIONS+=($CUSTOM)
            fi
            ;;
    esac
done

if [[ ${#FILTER_EXPRESSIONS[@]} -eq 0 ]]; then
    echo "No filters selected, defaulting to w/highway."
    FILTER_EXPRESSIONS=("w/highway")
fi

if [[ "$AREA_MODE" == "single" ]]; then
    FILTERED_OUTPUT=$(ask "Output filename for the filtered file" "${EXTRACT_OUTPUT%.osm.pbf}-filtered.osm.pbf")
fi
echo

# ---------- Step 5: Export to GeoJSON (chosen once, applied to every area) ----------

echo "--- Step 5: Export filtered network to GeoJSON ---"

ATTR_OPTIONS=(
    "id           (element id -- default)"
    "version      (element version -- default)"
    "type         (element type -- default)"
    "deleted      (deleted flag)"
    "changeset    (changeset id)"
    "timestamp    (edit timestamp)"
    "uid          (user id)"
    "user         (user display name)"
    "way-nodes    (node ids/coords making up a way)"
)

ATTR_SELECTION=$(checkbox_menu "Select which --attributes to include in the export:" "1,2,3" "${ATTR_OPTIONS[@]}")

declare -a ATTR_LIST=()
IFS=',' read -r -a SELECTED_ATTR_LABELS <<< "$ATTR_SELECTION"
for label in "${SELECTED_ATTR_LABELS[@]}"; do
    # first whitespace-delimited token is the real attribute name
    ATTR_LIST+=("$(echo "$label" | awk '{print $1}')")
done
if [[ ${#ATTR_LIST[@]} -eq 0 ]]; then
    ATTR_LIST=("id" "version" "type")
fi
ATTR_STRING=$(IFS=,; echo "${ATTR_LIST[*]}")

UID_OPTIONS=(
    "type_id      (default -- unique id combining element type + id)"
    "counter      (sequential counter id)"
    "extra        (id stored as an extra property instead of top-level id)"
    "none         (do not add a unique id)"
)
UID_SELECTION=$(checkbox_menu "Select the --add-unique-id mode:" "1" "${UID_OPTIONS[@]}")
UID_MODE=$(echo "$UID_SELECTION" | awk -F',' '{print $1}' | awk '{print $1}')
[[ -z "$UID_MODE" ]] && UID_MODE="type_id"

if [[ "$AREA_MODE" == "single" ]]; then
    GEOJSON_OUTPUT=$(ask "Output filename for the GeoJSON" "${FILTERED_OUTPUT%.osm.pbf}.geojson")
fi
echo

# ---------- Run the pipeline ----------

if [[ "$AREA_MODE" == "single" ]]; then

    run_filter_export "$EXTRACT_OUTPUT" "$FILTERED_OUTPUT" "$GEOJSON_OUTPUT"

    echo
    echo "=== Done ==="
    echo "Source PBF:         $PBF_FILENAME"
    echo "Extracted area:     $EXTRACT_OUTPUT"
    echo "Filtered file:      $FILTERED_OUTPUT  (filters: ${FILTER_EXPRESSIONS[*]})"
    echo "GeoJSON output:     $GEOJSON_OUTPUT  (attributes: $ATTR_STRING, unique-id: $UID_MODE)"

else
    # batch mode: ONE osmium extract pass for all boundaries (much faster
    # than re-reading a huge source file once per city), then filter+export
    # per boundary as before.
    echo "--- Running batch pipeline for ${#BOUNDARY_FILES[@]} boundaries ---"
    echo

    declare -a SUMMARY=()
    declare -a PENDING_BOUNDARIES=()
    declare -a SKIPPED_EXISTING=()
    declare -a FAILED_EXTRACTS=()

    CONFIG_FILE="$OUTPUT_DIR/extract_config.json"

    json_escape() {
        # minimal JSON string escaping for backslashes and double quotes
        printf '%s' "$1" | sed 's/\\/\\\\/g; s/"/\\"/g'
    }

    {
        echo '{'
        echo '  "extracts": ['
        first=true
        for boundary in "${BOUNDARY_FILES[@]}"; do
            name="$(basename "$boundary")"
            name="${name%.*}"
            extract_out="$EXTRACT_DIR/$name.osm.pbf"

            if [[ -e "$extract_out" && "$FORCE_OVERWRITE" != "true" ]]; then
                SKIPPED_EXISTING+=("$name")
                continue
            fi

            PENDING_BOUNDARIES+=("$boundary")
            esc_poly="$(json_escape "$(realpath "$boundary")")"
            esc_out="$(json_escape "$(realpath -m "$extract_out")")"

            if [[ "$first" == "true" ]]; then
                first=false
            else
                echo ','
            fi
            printf '    { "output": "%s", "output_format": "pbf", "polygon": { "file_name": "%s", "file_type": "geojson" } }' \
                "$esc_out" "$esc_poly"
        done
        echo
        echo '  ]'
        echo '}'
    } > "$CONFIG_FILE"

    if [[ ${#SKIPPED_EXISTING[@]} -gt 0 ]]; then
        echo "Skipping ${#SKIPPED_EXISTING[@]} boundary/boundaries already extracted: ${SKIPPED_EXISTING[*]}"
    fi

    if [[ ${#PENDING_BOUNDARIES[@]} -gt 0 ]]; then
        EXTRACT_ARGS=(-c "$CONFIG_FILE" -s "$STRATEGY")
        [[ "$FORCE_OVERWRITE" == "true" ]] && EXTRACT_ARGS+=(--overwrite)

        echo "Running one-pass extract for ${#PENDING_BOUNDARIES[@]} boundary/boundaries (single read of $PBF_FILENAME):"
        echo "Running: osmium extract ${EXTRACT_ARGS[*]} $PBF_FILENAME"
        if ! osmium extract "${EXTRACT_ARGS[@]}" "$PBF_FILENAME"; then
            echo "Warning: the single-pass batch extract failed."
            echo "Falling back to extracting each pending boundary one at a time,"
            echo "so a bad boundary doesn't block the rest."
            echo
            for boundary in "${PENDING_BOUNDARIES[@]}"; do
                name="$(basename "$boundary")"
                name="${name%.*}"
                extract_out="$EXTRACT_DIR/$name.osm.pbf"
                ow_flag=""
                [[ -e "$extract_out" ]] && ow_flag="--overwrite"
                echo "-> $name (fallback single extract)"
                if ! osmium extract --polygon "$boundary" "$PBF_FILENAME" -o "$extract_out" -s "$STRATEGY" $ow_flag; then
                    echo "   Warning: extraction failed for '$name', skipping this boundary."
                    FAILED_EXTRACTS+=("$name")
                fi
            done
            echo
        fi
    else
        echo "All extracts already exist, skipping the extract pass entirely."
    fi
    echo

    for boundary in "${BOUNDARY_FILES[@]}"; do
        name="$(basename "$boundary")"
        name="${name%.*}"   # strip extension

        if [[ " ${FAILED_EXTRACTS[*]} " == *" $name "* ]]; then
            SUMMARY+=("$name: FAILED (extract)")
            continue
        fi

        extract_out="$EXTRACT_DIR/$name.osm.pbf"
        filtered_out="$FILTERED_DIR/$name-filtered.osm.pbf"
        geojson_out="$GEOJSON_DIR/$name.geojson"

        if [[ ! -e "$extract_out" ]]; then
            echo "-> $name: extract file missing, skipping."
            SUMMARY+=("$name: FAILED (extract missing)")
            continue
        fi

        echo "-> $name"
        run_filter_export "$extract_out" "$filtered_out" "$geojson_out"
        SUMMARY+=("$name: OK -> $geojson_out")
        echo
    done

    echo "=== Done ==="
    echo "Source PBF:      $PBF_FILENAME"
    echo "Boundaries dir:  $BOUNDARY_DIR (pattern: $BOUNDARY_PATTERN)"
    echo "Filters used:    ${FILTER_EXPRESSIONS[*]}"
    echo "Attributes:      $ATTR_STRING, unique-id: $UID_MODE"
    echo "Output layout:"
    echo "  $EXTRACT_DIR/<name>.osm.pbf"
    echo "  $FILTERED_DIR/<name>-filtered.osm.pbf"
    echo "  $GEOJSON_DIR/<name>.geojson"
    echo
    echo "Per-boundary results:"
    for line in "${SUMMARY[@]}"; do
        echo "  $line"
    done
fi