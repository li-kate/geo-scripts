"""
Merges UTCI heat attributes from a GeoJSON (with OSM IDs) into an OSM PBF,
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
    python osm_heat_merge_idsafe.py \
        --heat-path Atlanta-260503-UTCI.geojson \
        --pbf-path atlanta-260503-filtered.osm.pbf \
        --output-path output/Atlanta-260503-UTCI.osm \
        --heat-cols UTCI_07 UTCI_08 UTCI_09 UTCI_10 UTCI_11 UTCI_12 UTCI_13 UTCI_14 UTCI_15 UTCI_16 UTCI_17 UTCI_18 UTCI_19 UTCI_20
"""

import os
import time
import argparse
from datetime import datetime, timezone

import numpy as np
import pandas as pd
import geopandas as gpd
import osmium


# ----------------------------------------------------------------------
# Heat lookup (unchanged logic from the original script)
# ----------------------------------------------------------------------

def build_heat_lookup(heat_gdf, heat_cols, id_col='id', type_col='type'):
    """
    Builds lookup dicts from the heat GeoJSON keyed by OSM ID.

    Returns:
        way_heat: dict of way_id -> {col: value, ...}
        node_heat: dict of node_id -> {col: value, ...}
    """
    way_heat = {}
    node_heat = {}

    for _, row in heat_gdf.iterrows():
        feat_id = row.get(id_col)
        feat_type = str(row.get(type_col, '')).lower().strip()

        if pd.isna(feat_id):
            continue
        feat_id = int(feat_id)

        vals = {}
        has_data = False
        for col in heat_cols:
            v = row.get(col)
            if pd.notna(v):
                vals[col] = v
                has_data = True
            else:
                vals[col] = np.nan

        if not has_data:
            continue

        if feat_type == 'way':
            way_heat[feat_id] = vals
        elif feat_type == 'node':
            node_heat[feat_id] = vals

    print(f"  Heat lookup built: {len(way_heat)} ways, {len(node_heat)} nodes")
    return way_heat, node_heat


# ----------------------------------------------------------------------
# Pass 1: scan PBF for ways that have a heat match (by way ID, or by
# averaging the heat of their first/last node), and collect every node
# ID referenced by a matched way.
# ----------------------------------------------------------------------

class WayScanHandler(osmium.SimpleHandler):
    def __init__(self, way_heat, node_heat, heat_cols, way_filter_ids=None, node_filter_ids=None):
        super().__init__()
        self.way_heat = way_heat
        self.node_heat = node_heat
        self.heat_cols = heat_cols
        self.way_filter_ids = way_filter_ids      # optional set to restrict scan (speed)
        self.node_filter_ids = node_filter_ids    # optional set to restrict scan (speed)

        self.matched_ways = {}      # way_id -> {'refs': [node_ids...], 'tags': {...}, 'heat': {...}}
        self.needed_node_ids = set()

        self.way_matched_count = 0
        self.node_matched_count = 0
        self.scanned_count = 0

        # For the by-highway-type match-rate diagnostic table
        self.total_by_highway = {}    # highway tag value -> count of all scanned ways
        self.matched_by_highway = {}  # highway tag value -> count of matched ways

    def way(self, w):
        self.scanned_count += 1
        wid = w.id

        if self.way_filter_ids is not None and wid not in self.way_filter_ids:
            # Still allow node-endpoint matching pass even if not in way_filter_ids,
            # since way_filter_ids only restricts by bbox candidates upstream.
            pass

        refs = [n.ref for n in w.nodes]
        if not refs:
            return

        highway_val = w.tags.get('highway', '(none)')
        self.total_by_highway[highway_val] = self.total_by_highway.get(highway_val, 0) + 1

        heat_vals = None

        # Pass 1: direct way ID match
        if wid in self.way_heat:
            heat_vals = self.way_heat[wid]
            self.way_matched_count += 1
        else:
            # Pass 2: average heat from first/last node endpoints
            u, v = refs[0], refs[-1]
            u_heat = self.node_heat.get(u)
            v_heat = self.node_heat.get(v)
            if u_heat or v_heat:
                heat_vals = {}
                for col in self.heat_cols:
                    u_val = u_heat.get(col) if u_heat else np.nan
                    v_val = v_heat.get(col) if v_heat else np.nan
                    if pd.notna(u_val) and pd.notna(v_val):
                        heat_vals[col] = (u_val + v_val) / 2.0
                    elif pd.notna(u_val):
                        heat_vals[col] = u_val
                    elif pd.notna(v_val):
                        heat_vals[col] = v_val
                    else:
                        heat_vals[col] = np.nan
                if any(pd.notna(v) for v in heat_vals.values()):
                    self.node_matched_count += 1
                else:
                    heat_vals = None

        if heat_vals is None:
            return

        self.matched_by_highway[highway_val] = self.matched_by_highway.get(highway_val, 0) + 1

        tags = {tag.k: tag.v for tag in w.tags}
        self.matched_ways[wid] = {
            'refs': refs,
            'tags': tags,
            'heat': heat_vals,
        }
        self.needed_node_ids.update(refs)


# ----------------------------------------------------------------------
# Pass 2: collect lat/lon for exactly the node IDs we need
# ----------------------------------------------------------------------

class NodeCollectHandler(osmium.SimpleHandler):
    def __init__(self, needed_node_ids):
        super().__init__()
        self.needed_node_ids = needed_node_ids
        self.node_coords = {}  # id -> (lat, lon)

    def node(self, n):
        if n.id in self.needed_node_ids:
            self.node_coords[n.id] = (n.location.lat, n.location.lon)


# ----------------------------------------------------------------------
# XML writer — original IDs only
# ----------------------------------------------------------------------

def _esc(s):
    return (str(s)
            .replace('&', '&amp;')
            .replace('"', '&quot;')
            .replace('<', '&lt;')
            .replace('>', '&gt;'))


def write_osmxml(node_coords, matched_ways, output_path, heat_cols):
    timestamp = datetime.now(timezone.utc).strftime('%Y-%m-%dT%H:%M:%SZ')
    start = time.time()

    # Drop ways that reference a node we couldn't resolve (shouldn't normally happen,
    # since we scan the same PBF, but PBFs with missing nodes/extracts are possible)
    usable_ways = {}
    dropped = 0
    for wid, w in matched_ways.items():
        if all(r in node_coords for r in w['refs']):
            usable_ways[wid] = w
        else:
            dropped += 1
    if dropped:
        print(f"  WARNING: dropped {dropped} ways referencing unresolved nodes.")

    referenced_node_ids = set()
    for w in usable_ways.values():
        referenced_node_ids.update(w['refs'])

    print(f"Writing XML to {output_path} ({len(referenced_node_ids)} nodes, {len(usable_ways)} ways)...")
    with open(output_path, 'w', encoding='utf-8') as f:
        f.write('<?xml version="1.0" encoding="UTF-8"?>\n')
        f.write('<osm version="0.6" generator="osmium_idsafe_merge">\n')

        for nid in sorted(referenced_node_ids):
            lat, lon = node_coords[nid]
            f.write(f'  <node id="{nid}" lat="{lat}" lon="{lon}" version="1" changeset="1" '
                    f'timestamp="{timestamp}" uid="1" user="script"/>\n')

        for wid, w in usable_ways.items():
            f.write(f'  <way id="{wid}" version="1" changeset="1" timestamp="{timestamp}" '
                    f'uid="1" user="script">\n')
            for ref in w['refs']:
                f.write(f'    <nd ref="{ref}"/>\n')
            for k, v in w['tags'].items():
                f.write(f'    <tag k="{_esc(k)}" v="{_esc(v)}"/>\n')
            for col in heat_cols:
                val = w['heat'].get(col)
                if val is not None and not (isinstance(val, float) and np.isnan(val)):
                    f.write(f'    <tag k="{_esc(col.lower())}" v="{_esc(val)}"/>\n')
            f.write('  </way>\n')

        f.write('</osm>\n')

    print(f"Done in {time.time() - start:.2f}s")


# ----------------------------------------------------------------------
# Pipeline
# ----------------------------------------------------------------------

def run_pipeline(pbf_path, heat_path, output_path, heat_cols,
                  id_col='id', type_col='type', drop_unmatched=True):
    t0 = time.time()
    print(f"\n{'='*60}")
    print(f"Processing: {os.path.basename(heat_path)}")
    print(f"  PBF:    {pbf_path}")
    print(f"  Output: {output_path}")
    print(f"{'='*60}")

    heat_gdf = gpd.read_file(heat_path)
    heat_gdf = heat_gdf[heat_gdf.geometry.notna()].reset_index(drop=True)
    if heat_gdf.empty:
        print(f"  WARNING: {heat_path} has no valid geometries. Skipping.")
        return

    if id_col not in heat_gdf.columns:
        raise ValueError(f"Heat GeoJSON missing ID column '{id_col}'. Available: {list(heat_gdf.columns)}")
    if type_col not in heat_gdf.columns:
        raise ValueError(f"Heat GeoJSON missing type column '{type_col}'. Available: {list(heat_gdf.columns)}")
    missing_cols = [c for c in heat_cols if c not in heat_gdf.columns]
    if missing_cols:
        raise ValueError(f"Heat GeoJSON missing expected columns: {missing_cols}")

    print(f"  Heat features: {len(heat_gdf)}")
    print(f"  Feature types: {heat_gdf[type_col].value_counts().to_dict()}")

    way_heat, node_heat = build_heat_lookup(heat_gdf, heat_cols, id_col=id_col, type_col=type_col)

    print("\nScanning PBF for matching ways (this reads the whole file once)...")
    scan = WayScanHandler(way_heat, node_heat, heat_cols)
    scan.apply_file(pbf_path, locations=False)
    print(f"  Ways scanned: {scan.scanned_count}")
    print(f"  Way ID matched: {scan.way_matched_count}")
    print(f"  Node endpoint matched: {scan.node_matched_count}")
    print(f"  Total matched ways: {len(scan.matched_ways)}")
    print(f"  Unmatched ways: {scan.scanned_count - len(scan.matched_ways)}")

    if scan.total_by_highway:
        total_series = pd.Series(scan.total_by_highway, name='total_edges')
        matched_series = pd.Series(scan.matched_by_highway, name='matched').reindex(total_series.index, fill_value=0).astype(int)
        comparison = pd.DataFrame({
            'total_edges': total_series,
            'matched': matched_series,
            'unmatched': (total_series - matched_series).astype(int),
        })
        comparison['match_rate'] = (comparison['matched'] / comparison['total_edges'] * 100).round(1)
        comparison = comparison.sort_values('total_edges', ascending=False)
        print(f"\n  Edge match comparison by highway type:")
        print(comparison.to_string())

    if not scan.matched_ways:
        print("  WARNING: no ways matched. Nothing to write.")
        return

    print(f"\nResolving coordinates for {len(scan.needed_node_ids)} referenced nodes...")
    nodecol = NodeCollectHandler(scan.needed_node_ids)
    nodecol.apply_file(pbf_path, locations=True)
    print(f"  Nodes resolved: {len(nodecol.node_coords)}")

    write_osmxml(nodecol.node_coords, scan.matched_ways, output_path, heat_cols)
    print(f"  Pipeline time: {time.time() - t0:.2f}s")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Merge UTCI heat data into OSM network by ID matching, preserving original OSM IDs.")
    parser.add_argument("--heat-path", required=True)
    parser.add_argument("--pbf-path", required=True)
    parser.add_argument("--output-path", required=True)
    parser.add_argument("--heat-cols", nargs="+",
                        default=['UTCI_07', 'UTCI_08', 'UTCI_09', 'UTCI_10', 'UTCI_11',
                                 'UTCI_12', 'UTCI_13', 'UTCI_14', 'UTCI_15', 'UTCI_16',
                                 'UTCI_17', 'UTCI_18', 'UTCI_19', 'UTCI_20', 'NDVI'])
    parser.add_argument("--id-col", default="@id")
    parser.add_argument("--type-col", default="@type")
    parser.add_argument("--keep-unmatched", action="store_true",
                        help="Currently unmatched ways are never written, since there's nothing to merge; flag kept for CLI compatibility.")
    args = parser.parse_args()

    if not os.path.isfile(args.heat_path):
        raise FileNotFoundError(f"Heat file not found: {args.heat_path}")
    if not os.path.isfile(args.pbf_path):
        raise FileNotFoundError(f"PBF file not found: {args.pbf_path}")

    os.makedirs(os.path.dirname(args.output_path) or ".", exist_ok=True)

    run_pipeline(
        pbf_path=args.pbf_path,
        heat_path=args.heat_path,
        output_path=args.output_path,
        heat_cols=args.heat_cols,
        id_col=args.id_col,
        type_col=args.type_col,
    )