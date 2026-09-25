# haqathon backend

Data-processing backend migrated from the haqathon app. It ingests raw field
data (GPS tracks, Kestrel weather, PurpleAir air-quality), standardizes and
merges it, and converts point data into routable links.

It is a Streamlit app plus a supporting pipeline. Entry points:

- `merge_datasets.py` — Streamlit entry for merging raw datasets.
- `pages/` — additional Streamlit pages (conversions, points-to-links).
- `pipeline/` — core conversion logic and configuration.
- `preprocess_files/` — per-source loaders (gps_tracks, kestrel, purpleair) and
  the `map_matching/` snapping logic.
- `conversions/` — file-format converters used by the pipeline.
- `data/` — raw and merged field datasets.
- `graphhopper/config-haqathon.yml` — GraphHopper config for map matching.

## Running

```bash
pip install -r requirements.txt
streamlit run merge_datasets.py
```

Run commands from this directory so the intra-package imports
(`pipeline.*`, `preprocess_files.*`, `conversions.*`) resolve.

## Relationship to geo-scripts

Some converters and the map-matching logic here overlap with the shared
top-level `file_conversions/` and `map_matching/` tooling in geo-scripts. This
folder keeps its own copies so the haqathon pipeline runs self-contained; the
top-level geo-scripts versions remain the shared, general-purpose tooling.

## Not committed

Large GraphHopper build artifacts are intentionally excluded from git (see the
repo `.gitignore`): the OSM extract (`*.osm.pbf`) and the GraphHopper server
JAR (`*.jar`). Download or build these locally as needed.
