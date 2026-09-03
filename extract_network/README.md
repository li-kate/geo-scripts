# How to Run `.sh` Files

## 1. Clone or Download the Repository

Clone the Git repository to PACE, or download the scripts and place them on PACE.

## 2. Make the Script Executable

From the directory containing the script:

```bash
chmod +x extract_network.sh
```

## 3. Run the Script

```bash
./extract_network.sh
```

---

# `preprocess_boundaries.sh`

Automatically preprocesses city boundary GeoJSON files.

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

---

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

### Example `answers.txt`

**Do not put comments in the actual `answers.txt` file.** The script reads each line as an answer.

```text
local
/storage/home/hcoda1/1/kli605/scratch/output_osm/us-latest.osm.pbf
batch
/storage/home/hcoda1/1/kli605/scratch/output_osm/boundaries/boundaries_wgs84
*.geojson
y
network_output
y
smart
1
```

### Running with `answers.txt`

```bash
./extract_network.sh < answers.txt
```

For PACE, make sure the required Conda environment containing `osmium-tool` is activated before running the script if the environment is not already available on `PATH`.
