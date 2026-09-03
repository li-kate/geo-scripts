# transit_geojsons.py

Command-line script for subcommands `clip` and `merge`. No paths or per-city logic are hardcoded
in the script — everything is a flag or lives in **one** YAML config file
(`config.yaml`) that both subcommands share.

## Install

```bash
pip install geopandas shapely pyyaml pandas --break-system-packages
```

## Don't want to deal with flags? Just run it.

```bash
python3 transit_geojsons.py
```

With no arguments, it launches a guided wizard: it asks you plain-English
questions one at a time (what file, what folder, etc.), tells you if a path
doesn't exist so you can fix it, and shows you the equivalent full command at
the end of each step in case you want to skip the questions next time. This
is the easiest way to use the tool if you're not comfortable with command-line
flags — everything below is for reference / for scripting it later.

## config.yaml

One file defines every transit mode (bus, rail, ...), the filename suffix
that identifies it, and — per city — which column holds the stop name:

```yaml
bus:
  suffix: "_bus.geojson"
  name_columns:
    Miami: StopName
    Philadelphia: StopName

rail:
  suffix: "_rail.geojson"
  name_columns:
    Miami: NAME
    Philadelphia:
      - Station_Na   # first non-null value across these columns wins
      - StopName
```

- **Add a new city**: add a line under the relevant mode's `name_columns`.
- **Add a new mode** (e.g. ferry): copy a whole top-level block and edit it.
- The shipped `config.yaml` is a direct port of the old hardcoded `NAME_MAP`.

## 1. Clip raw stop files to city boundaries

```bash
python3 transit_geojsons.py clip \
  --boundaries boundaries.geojson \
  --data-dir stations/ \
  --out-dir extracted-stations/ \
  --config config.yaml
```

- `--boundaries`: your boundaries geojson (LineStrings are auto-converted to polygons)
- `--data-dir`: folder with raw `*_bus.geojson` / `*_rail.geojson` files
- `--out-dir`: where clipped `{city}_{mode}.geojson` files get written
- `--city-column` (default `city`): column in the boundaries file with the city name
- `--city-separator` (default `-`): the boundaries' city field looks like
  `Los_Angeles-260503-UTCI.osm-sorted` — this strips everything from the separator onward

## 2. Merge clipped files into one (or more) unified output(s)

```bash
# One combined file with a "mode" column distinguishing bus/rail:
python3 transit_geojsons.py merge \
  --in-dir extracted-stations/ \
  --config config.yaml \
  --out merged.geojson

# OR one file per mode:
python3 transit_geojsons.py merge \
  --in-dir extracted-stations/ \
  --config config.yaml \
  --separate --out-dir merged/
```

If a file has no entry in `config.yaml`'s `name_columns`, it's still merged,
`stop_name` is left null, and you get a warning at the end telling you
exactly which key(s) to add.

## Note on filenames

`clip` names its outputs `{city}_{mode}` (mode = whatever key you used in
`config.yaml`, e.g. `bus`/`rail`), so `merge` expects that naming too. If
you're feeding it files from the *old* scripts (named e.g.
`Miami_bus_stops.geojson`), rename them to match, or change `suffix` in
`config.yaml` to `_bus_stops.geojson` / `_rail_stations.geojson`.