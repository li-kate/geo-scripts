# `extract_network.sh`

Before running `extract_network.sh`, make sure your boundary files have already been preprocessed using `preprocess_boundaries.sh`.

## Interactive Pipeline

The script performs the following steps:

1. **Get a source `.osm.pbf`**

   * Download from Geofabrik, or
   * Use an existing local `.osm.pbf` file

2. **Set up `osmium-tool`**

   * Uses a Conda environment
   * Works on PACE or any machine with Conda

3. **Extract area(s)**

   * **Single:** one bounding box or one preprocessed WGS84 polygon file
   * **Batch:** a directory of preprocessed WGS84 city/region boundary files, with one extract per file

4. **Filter the network by tags**

   * Uses a checkbox menu
   * Default: `w/highway`

5. **Export the filtered network to GeoJSON**

   * Uses a checkbox menu for attributes/options
   * Default:

     ```text
     --add-unique-id=type_id
     --attributes=id,version,type
     ```

## Batch Mode

In batch mode, the choices for **steps 4 and 5 are made once** and applied to every boundary in the directory.

This produces:

* One extracted `.osm.pbf` per boundary
* One filtered `.osm.pbf` per boundary
* One `.geojson` per boundary

### Boundary Preprocessing

Boundary validity, dissolve/union, reprojection, and buffering are handled separately by:

```text
preprocess_boundaries.sh
```

This keeps boundary preparation separate from OSM extraction and network processing.

### Overwriting Files

The script asks before doing anything it cannot safely infer.

It will **not overwrite existing files without asking first**, unless you choose the **"overwrite all"** option for a batch run.

---

# `answers.txt`

`extract_network.sh` can be run non-interactively by providing an `answers.txt` file:

```bash
./extract_network.sh < answers.txt
```

The answers must appear **one per line and in the same order as the questions asked by the script**.

## What the Questions Are

The following questions correspond to the entries in `answers.txt`:

| # | Question | Example Answer |
|---:|---|---|
| 1 | Source choice | `local` |
| 2 | Path to existing `.osm.pbf` | `/storage/home/.../us-latest.osm.pbf` |
| 3 | Area extraction mode | `batch` |
| 4 | Directory containing preprocessed WGS84 boundaries | `/storage/home/.../boundaries_wgs84` |
| 5 | Boundary filename pattern | `*.geojson` |
| 6 | Proceed with discovered boundary files? | `y` |
| 7 | Base output directory | `network_output` |
| 8 | Overwrite existing files? | `y` |
| 9 | Osmium extraction strategy | `smart` |
| 10 | Tag filter selection | `1` |
| 11 | Attribute selection | `1,2,3` |
| 12 | Unique ID mode | `1` |

# matching.py
Merges attributes from a GeoJSON (with OSM IDs) into an OSM PBF,
producing an enriched OSM XML file that preserves ALL original OSM node
and way IDs exactly as they appear in the source PBF. No synthetic IDs,
no way-splitting.

This uses pyosmium instead of pyrosm, because pyrosm's get_network() is a
routing-graph extractor: it splits ways at intersections (new way IDs) and
discards/replaces intermediate node geometry (synthetic node IDs) once it
builds the graph. osmium reads the PBF's native data model directly, so a
way with id 12345 in the source file stays way id 12345 in the output,
with the exact same ordered list of node references it had originally.

Install:
    pip install osmium geopandas pandas numpy
    
Usage:
python -u matching.py \
    --heat-path "/storage/home/hcoda1/1/kli605/scratch/safe_routes/Atlanta-062226_UTCI_alltime.geojson" \
    --pbf-path "/storage/home/hcoda1/1/kli605/scratch/safe_routes/georgia-240101.osm.pbf" \
    --output-path "./Atlanta-20240101-UTCI.osm" \
    --heat-cols UTCI_07 UTCI_08 UTCI_09 UTCI_10 UTCI_11 UTCI_12 UTCI_13 UTCI_14 UTCI_15 UTCI_16 UTCI_17 UTCI_18 UTCI_19 UTCI_20 NDVI

Produces a new osm file (not pbf) and only keeps the links that match with the geojson.