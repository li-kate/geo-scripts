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
