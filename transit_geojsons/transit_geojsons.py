#!/usr/bin/env python3
"""
transit_geojsons: clip per-city transit stop/station files to city boundaries,
then merge them into unified geojson(s) with a normalized stop_name column.

Usage:
    transit_geojsons.py clip  --boundaries boundaries.geojson --data-dir stations/ \
                           --out-dir extracted-stations/ --config config.yaml \
                           [--city-column city] [--city-separator -]

    transit_geojsons.py merge --in-dir extracted-stations/ --config config.yaml \
                           --out merged.geojson
                           # OR, for one file per mode instead of one combined file:
    transit_geojsons.py merge --in-dir extracted-stations/ --config config.yaml \
                           --separate --out-dir merged/

Everything city/mode-specific lives in one YAML config file (see config.yaml):

    bus:
      suffix: "_bus.geojson"
      name_columns:
        Miami: StopName
        Philadelphia:
          - Station_Na
          - StopName
    rail:
      suffix: "_rail.geojson"
      name_columns:
        Miami: NAME
"""

import argparse
import glob
import os
import sys

import geopandas as gpd
import pandas as pd
import yaml
from shapely.geometry import Polygon


# -----------------------------
# Shared helpers
# -----------------------------
def load_config(path):
    with open(path) as f:
        config = yaml.safe_load(f) or {}
    if not config:
        sys.exit(f"error: config file '{path}' is empty or invalid")
    for mode_name, cfg in config.items():
        if "suffix" not in cfg:
            sys.exit(f"error: mode '{mode_name}' in {path} is missing a 'suffix' key")
        cfg.setdefault("name_columns", {})
    return config


def normalize_city_from_boundary(name, separator):
    """Los_Angeles-260503-UTCI.osm-sorted -> Los_Angeles (with separator='-')"""
    return name.split(separator)[0]


def normalize_city_from_filename(filename, config):
    """Los_Angeles_bus.geojson -> Los_Angeles"""
    for cfg in config.values():
        filename = filename.replace(cfg["suffix"], "")
    return filename


# -----------------------------
# clip subcommand
# -----------------------------
def cmd_clip(args):
    config = load_config(args.config)
    os.makedirs(args.out_dir, exist_ok=True)

    cities = gpd.read_file(args.boundaries).to_crs(epsg=4326)
    if args.city_column not in cities.columns:
        sys.exit(
            f"error: boundaries file has no column '{args.city_column}'. "
            f"Available columns: {list(cities.columns)}"
        )

    # Convert LineString boundaries to Polygons where needed
    cities["geometry"] = cities["geometry"].apply(
        lambda g: Polygon(g) if g.geom_type == "LineString" else g
    )

    # Index all data files in data-dir by normalized city name + mode
    all_files = glob.glob(os.path.join(args.data_dir, "*.geojson"))
    file_index = {}
    for f in all_files:
        base = os.path.basename(f)
        city_key = normalize_city_from_filename(base, config)
        for mode_name, cfg in config.items():
            if cfg["suffix"] in base:
                file_index.setdefault(city_key, {})[mode_name] = f

    if not file_index:
        print(f"warning: no files matching configured mode suffixes found in {args.data_dir}")

    for _, city in cities.iterrows():
        raw_city_name = city[args.city_column]
        city_name = normalize_city_from_boundary(raw_city_name, args.city_separator)
        city_geom = city.geometry

        print(f"\nProcessing: {raw_city_name} -> {city_name}")

        if city_name not in file_index:
            print(f"  No matching files for {city_name}")
            continue

        for mode_name, path in file_index[city_name].items():
            gdf = gpd.read_file(path).to_crs(epsg=4326)

            # quick bbox filter (speed optimization)
            gdf = gdf[gdf.intersects(city_geom.envelope)]

            # clip to actual boundary
            clipped = gpd.clip(gdf, city_geom)

            out_path = os.path.join(args.out_dir, f"{city_name}_{mode_name}.geojson")
            if not clipped.empty:
                clipped.to_file(out_path, driver="GeoJSON")
                print(f"  Saved {mode_name}: {len(clipped)} features -> {out_path}")
            else:
                print(f"  No {mode_name} features in {city_name}")

    print("\nDone.")


# -----------------------------
# merge subcommand
# -----------------------------
def cmd_merge(args):
    config = load_config(args.config)

    files = glob.glob(os.path.join(args.in_dir, "*.geojson"))
    if not files:
        sys.exit(f"error: no geojson files found in {args.in_dir}")

    by_mode = {mode_name: [] for mode_name in config}
    unmapped = []

    for f in files:
        base = os.path.basename(f)
        key = base.replace(".geojson", "")

        # figure out which mode this file belongs to, from its filename
        mode_name = None
        for m in config:
            if key.endswith(f"_{m}"):
                mode_name = m
                break
        if mode_name is None:
            print(f"  WARNING: could not determine mode for '{base}', skipping")
            continue

        city_name = key[: -(len(mode_name) + 1)]  # strip trailing "_<mode>"
        name_columns = config[mode_name]["name_columns"]

        gdf = gpd.read_file(f)
        gdf["source_file"] = key
        gdf["mode"] = mode_name

        if city_name in name_columns:
            col = name_columns[city_name]
            if isinstance(col, list):
                missing = [c for c in col if c not in gdf.columns]
                if missing:
                    print(f"  WARNING: {key} missing mapped column(s) {missing}")
                present = [c for c in col if c in gdf.columns]
                if present:
                    gdf["stop_name"] = gdf[present].bfill(axis=1).iloc[:, 0]
                else:
                    gdf["stop_name"] = None
            else:
                if col not in gdf.columns:
                    print(f"  WARNING: {key} missing mapped column '{col}'")
                    gdf["stop_name"] = None
                else:
                    gdf["stop_name"] = gdf[col]
        else:
            print(f"  WARNING: no name mapping for '{key}', stop_name will be null")
            unmapped.append(key)
            gdf["stop_name"] = None

        by_mode[mode_name].append(gdf)
        print(f"  Loaded {key}: {len(gdf)} features")

    non_empty_modes = {m: gdfs for m, gdfs in by_mode.items() if gdfs}
    if not non_empty_modes:
        sys.exit("error: no matching files were loaded for any configured mode")

    if args.separate:
        if not args.out_dir:
            sys.exit("error: --separate requires --out-dir")
        os.makedirs(args.out_dir, exist_ok=True)
        for mode_name, gdfs in non_empty_modes.items():
            merged = pd.concat(gdfs, ignore_index=True)
            merged = gpd.GeoDataFrame(merged, crs=gdfs[0].crs)
            out_path = os.path.join(args.out_dir, f"{mode_name}.geojson")
            merged.to_file(out_path, driver="GeoJSON")
            print(f"\nMerged {len(merged)} '{mode_name}' features -> {out_path}")
    else:
        if not args.out:
            sys.exit("error: combined output requires --out")
        all_gdfs = [g for gdfs in non_empty_modes.values() for g in gdfs]
        merged = pd.concat(all_gdfs, ignore_index=True)
        merged = gpd.GeoDataFrame(merged, crs=all_gdfs[0].crs)
        merged.to_file(args.out, driver="GeoJSON")
        print(f"\nMerged {len(merged)} total features -> {args.out}")

    if unmapped:
        print(f"\n{len(unmapped)} file(s) had no name mapping (stop_name is null): {unmapped}")
        print(f"Add them to {args.config} to fix this.")


# -----------------------------
# Interactive wizard (for anyone who doesn't want to deal with flags)
# -----------------------------
def ask_text(prompt, default=None, validator=None):
    """Ask a free-text question. Re-asks until a valid, non-empty answer is given."""
    while True:
        suffix = f" [{default}]" if default is not None else ""
        raw = input(f"{prompt}{suffix}: ").strip().strip('"').strip("'")
        value = raw if raw else default
        if not value:
            print("  -> This one's required, please type something.\n")
            continue
        if validator:
            ok, message = validator(value)
            if not ok:
                print(f"  -> {message}\n")
                continue
        return value


def ask_choice(prompt, options):
    """Ask the user to pick one of a numbered list of options. Returns the option's text."""
    print(f"\n{prompt}")
    for i, opt in enumerate(options, 1):
        print(f"  {i}. {opt}")
    while True:
        raw = input(f"Enter a number (1-{len(options)}): ").strip()
        if raw.isdigit() and 1 <= int(raw) <= len(options):
            return options[int(raw) - 1]
        print(f"  -> Please type a number between 1 and {len(options)}.\n")


def ask_yes_no(prompt, default=True):
    hint = "Y/n" if default else "y/N"
    while True:
        raw = input(f"{prompt} [{hint}]: ").strip().lower()
        if not raw:
            return default
        if raw in ("y", "yes"):
            return True
        if raw in ("n", "no"):
            return False
        print("  -> Please answer y or n.\n")


def must_be_file(path):
    if not os.path.isfile(path):
        return False, f"Can't find a file at '{path}'. Double check the path and try again."
    return True, ""


def must_be_dir(path):
    if not os.path.isdir(path):
        return False, f"Can't find a folder at '{path}'. Double check the path and try again."
    return True, ""


def show_command_recap(pieces):
    """Print the equivalent command-line invocation, for anyone who wants to skip the wizard next time."""
    print("\n(Next time, you can skip these questions by running this directly:)")
    print("  " + " ".join(pieces))


def wizard_clip():
    print("\n--- Step: Clip raw stop files to city boundaries ---")
    print("This trims your raw bus/rail files down to just the stops inside each city's boundary.\n")

    boundaries = ask_text(
        "Path to your boundaries file (the geojson with one polygon/line per city)",
        validator=must_be_file,
    )
    data_dir = ask_text(
        "Path to the folder with your raw stop/station files",
        validator=must_be_dir,
    )
    config = ask_text(
        "Path to your config.yaml file (defines bus/rail suffixes and stop-name columns)",
        default="config.yaml",
        validator=must_be_file,
    )
    out_dir = ask_text(
        "Where should the clipped files be saved? (will be created if it doesn't exist)",
        default="extracted-stations",
    )
    city_column = ask_text(
        "Which column in the boundaries file holds the city name?",
        default="city",
    )
    city_separator = ask_text(
        "City names sometimes have extra text after them (e.g. 'Miami-260503-UTCI'). "
        "What character separates the real city name from that extra text?",
        default="-",
    )

    args = argparse.Namespace(
        boundaries=boundaries,
        data_dir=data_dir,
        out_dir=out_dir,
        config=config,
        city_column=city_column,
        city_separator=city_separator,
    )

    show_command_recap([
        "python3", sys.argv[0], "clip",
        "--boundaries", boundaries,
        "--data-dir", data_dir,
        "--out-dir", out_dir,
        "--config", config,
        "--city-column", city_column,
        "--city-separator", city_separator,
    ])

    if ask_yes_no("\nRun this now?", default=True):
        cmd_clip(args)
    return args


def wizard_merge(default_in_dir=None):
    print("\n--- Step: Merge clipped files into one dataset ---")
    print("This combines all the per-city clipped files into a single, unified file with a consistent stop_name column.\n")

    in_dir = ask_text(
        "Path to the folder with your clipped files (the output from the clip step)",
        default=default_in_dir,
        validator=must_be_dir,
    )
    config = ask_text(
        "Path to your config.yaml file",
        default="config.yaml",
        validator=must_be_file,
    )
    separate = not ask_yes_no(
        "\nDo you want ONE combined file with both bus and rail stops together?",
        default=True,
    )

    out = None
    out_dir = None
    if separate:
        out_dir = ask_text(
            "Where should the separate bus.geojson / rail.geojson files be saved? (created if it doesn't exist)",
            default="merged",
        )
    else:
        out = ask_text(
            "What should the combined output file be called?",
            default="merged.geojson",
        )

    args = argparse.Namespace(
        in_dir=in_dir,
        config=config,
        separate=separate,
        out=out,
        out_dir=out_dir,
    )

    pieces = ["python3", sys.argv[0], "merge", "--in-dir", in_dir, "--config", config]
    if separate:
        pieces += ["--separate", "--out-dir", out_dir]
    else:
        pieces += ["--out", out]
    show_command_recap(pieces)

    if ask_yes_no("\nRun this now?", default=True):
        cmd_merge(args)


def run_wizard():
    print("=" * 60)
    print("  transit_tool - guided setup")
    print("=" * 60)
    print(
        "\nI'll ask a few questions instead of needing command-line flags.\n"
        "Press Enter to accept anything shown in [brackets].\n"
    )

    choice = ask_choice(
        "What would you like to do?",
        [
            "Clip raw stop files to city boundaries",
            "Merge already-clipped files into one dataset",
            "Both: clip, then merge",
        ],
    )

    try:
        if choice.startswith("Clip"):
            wizard_clip()
        elif choice.startswith("Merge"):
            wizard_merge()
        else:
            clip_args = wizard_clip()
            wizard_merge(default_in_dir=clip_args.out_dir)
    except KeyboardInterrupt:
        print("\n\nCancelled.")
        sys.exit(1)

    print("\nAll done!")


# -----------------------------
# CLI
# -----------------------------
def main():
    # No arguments at all -> friendly guided wizard instead of requiring flags.
    if len(sys.argv) == 1:
        run_wizard()
        return

    parser = argparse.ArgumentParser(
        description="Clip and merge transit stop/station geojsons across cities. "
        "Run with no arguments for a guided, question-by-question mode."
    )
    sub = parser.add_subparsers(dest="command", required=True)

    p_clip = sub.add_parser("clip", help="Clip per-city transit files to city boundaries")
    p_clip.add_argument("--boundaries", required=True, help="Path to boundaries.geojson")
    p_clip.add_argument("--data-dir", required=True, help="Directory with raw *_<mode>.geojson files")
    p_clip.add_argument("--out-dir", required=True, help="Directory to write clipped per-city files")
    p_clip.add_argument("--config", required=True, help="YAML config file (modes + name columns)")
    p_clip.add_argument("--city-column", default="city", help="Column in boundaries file holding the city name (default: city)")
    p_clip.add_argument("--city-separator", default="-", help="Separator used to strip suffixes from the city name field (default: '-')")
    p_clip.set_defaults(func=cmd_clip)

    p_merge = sub.add_parser("merge", help="Merge clipped files into unified output(s)")
    p_merge.add_argument("--in-dir", required=True, help="Directory of clipped *_<mode>.geojson files")
    p_merge.add_argument("--config", required=True, help="YAML config file (modes + name columns)")
    p_merge.add_argument("--separate", action="store_true", help="Write one output file per mode instead of a single combined file")
    p_merge.add_argument("--out", help="Output path for combined merge (required unless --separate)")
    p_merge.add_argument("--out-dir", help="Output directory for per-mode files (required with --separate)")
    p_merge.set_defaults(func=cmd_merge)

    args = parser.parse_args()
    args.func(args)


if __name__ == "__main__":
    main()