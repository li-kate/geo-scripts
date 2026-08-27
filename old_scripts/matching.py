"""
Merges UTCI heat attributes from a GeoJSON (with OSM IDs) into an OSM PBF,
producing an enriched OSM XML file.

Creates new IDs but doesn't matter for GraphHopper.

No spatial join — features are matched by OSM ID directly.

Usage:
    python osm_heat_merge.py \
        --heat-path Atlanta-260503-UTCI.geojson \
        --pbf-path atlanta-260503-filtered.osm.pbf \
        --output-path output/Atlanta-260503-UTCI.osm \
        --heat-cols UTCI_07 UTCI_08 UTCI_09 UTCI_10 UTCI_11 UTCI_12 UTCI_13 UTCI_14 UTCI_15 UTCI_16 UTCI_17 UTCI_18 UTCI_19 UTCI_20
"""

import geopandas as gpd
import pandas as pd
import numpy as np
import math
import time
import os
from datetime import datetime, timezone
from pyrosm import OSM
from shapely.geometry import box


def expand_bbox_degrees(bounding_box, buffer_km=2.0):
    """
    Expands a [minx, miny, maxx, maxy] bounding box by buffer_km in all directions.

    Uses approximate degree conversion (~111 km/degree lat, adjusted for longitude).

    Returns:
        expanded [minx, miny, maxx, maxy]
    """
    minx, miny, maxx, maxy = bounding_box
    lat_buf = buffer_km / 111.0
    mid_lat = (miny + maxy) / 2.0
    lon_buf = buffer_km / (111.0 * math.cos(math.radians(mid_lat)))

    expanded = [minx - lon_buf, miny - lat_buf, maxx + lon_buf, maxy + lat_buf]
    print(f"Expanded node search bbox by {buffer_km}km: {bounding_box} -> {[round(c, 6) for c in expanded]}")
    return expanded


def reconstruct_missing_nodes(edges_gdf, existing_nodes_gdf):
    """
    Reconstructs missing node geometries from edge LineString endpoints.
    Fallback when expand_bbox_degrees doesn't capture all referenced nodes.

    Returns:
        combined_nodes_gdf, n_reconstructed
    """
    existing_ids = set(existing_nodes_gdf['id'].astype(int))
    referenced_ids = set(edges_gdf['u'].astype(int)) | set(edges_gdf['v'].astype(int))
    missing_ids = referenced_ids - existing_ids

    if not missing_ids:
        print("No missing nodes to reconstruct.")
        return existing_nodes_gdf, 0

    print(f"Reconstructing {len(missing_ids)} missing nodes from edge geometry...")
    missing_coords = {}

    for _, row in edges_gdf.iterrows():
        geom = row.get('geometry')
        if geom is None or not hasattr(geom, 'coords'):
            continue
        coords = list(geom.coords)
        u, v = int(row['u']), int(row['v'])
        if u in missing_ids and u not in missing_coords:
            missing_coords[u] = (coords[0][1], coords[0][0])
        if v in missing_ids and v not in missing_coords:
            missing_coords[v] = (coords[-1][1], coords[-1][0])

    still_missing = missing_ids - set(missing_coords.keys())
    if still_missing:
        print(f"  WARNING: {len(still_missing)} nodes could not be reconstructed.")

    if not missing_coords:
        return existing_nodes_gdf, 0

    reconstructed_df = pd.DataFrame([
        {'id': nid, 'lat': lat, 'lon': lon}
        for nid, (lat, lon) in missing_coords.items()
    ])
    reconstructed_gdf = gpd.GeoDataFrame(
        reconstructed_df,
        geometry=gpd.points_from_xy(reconstructed_df['lon'], reconstructed_df['lat']),
        crs=existing_nodes_gdf.crs
    )
    combined = pd.concat([existing_nodes_gdf, reconstructed_gdf], ignore_index=True)
    print(f"  Reconstructed {len(missing_coords)} nodes. Still unresolvable: {len(still_missing)}.")
    return combined, len(missing_coords)


def drop_edges_with_unresolvable_nodes(edges_gdf, nodes_gdf):
    """Drops edges referencing nodes not in nodes_gdf."""
    valid_ids = set(nodes_gdf['id'].astype(int))
    mask = (
        edges_gdf['u'].astype(int).isin(valid_ids) &
        edges_gdf['v'].astype(int).isin(valid_ids)
    )
    n_dropped = (~mask).sum()
    if n_dropped > 0:
        print(f"Dropped {n_dropped} edges with unresolvable node references.")
    return edges_gdf[mask].copy(), n_dropped


def build_heat_lookup(heat_gdf, heat_cols, id_col='id', type_col='type'):
    """
    Builds lookup dicts from the heat GeoJSON keyed by OSM ID.

    The heat GeoJSON has 'id' (OSM ID) and 'type' ('node' or 'way') fields.
    Pyrosm edges carry the original OSM way ID, so way-type heat features
    map directly to edges by that ID.

    Node-type heat features can be applied to edges whose u or v matches
    the node ID, with values averaged across endpoints.

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

        # Only store if at least one heat column has data
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


def apply_heat_to_edges(edges_gdf, way_heat, node_heat, heat_cols, original_way_ids):
    """
    Applies heat values to edges by OSM ID matching.

    Strategy:
      1. Match by original way ID (direct — same OSM way, split by pyrosm)
      2. For unmatched edges, try averaging node heat from u and v endpoints

    Args:
        edges_gdf: pyrosm edges GeoDataFrame
        way_heat: dict from build_heat_lookup (way_id -> heat values)
        node_heat: dict from build_heat_lookup (node_id -> heat values)
        heat_cols: list of UTCI column names
        original_way_ids: Series of original OSM way IDs aligned with edges_gdf

    Returns:
        edges_gdf with heat columns added
    """
    for col in heat_cols:
        edges_gdf[col] = np.nan

    way_matched = 0
    node_matched = 0

    for i in range(len(edges_gdf)):
        # Pass 1: match by original OSM way ID
        orig_id = original_way_ids.iloc[i]
        if pd.notna(orig_id):
            orig_id = int(orig_id)
            if orig_id in way_heat:
                for col in heat_cols:
                    edges_gdf.iat[i, edges_gdf.columns.get_loc(col)] = way_heat[orig_id][col]
                way_matched += 1
                continue

        # Pass 2: average node heat from u and v endpoints
        u = int(edges_gdf.iloc[i]['u'])
        v = int(edges_gdf.iloc[i]['v'])
        u_heat = node_heat.get(u)
        v_heat = node_heat.get(v)

        if u_heat or v_heat:
            for col in heat_cols:
                u_val = u_heat.get(col) if u_heat else np.nan
                v_val = v_heat.get(col) if v_heat else np.nan
                if pd.notna(u_val) and pd.notna(v_val):
                    edges_gdf.iat[i, edges_gdf.columns.get_loc(col)] = (u_val + v_val) / 2.0
                elif pd.notna(u_val):
                    edges_gdf.iat[i, edges_gdf.columns.get_loc(col)] = u_val
                elif pd.notna(v_val):
                    edges_gdf.iat[i, edges_gdf.columns.get_loc(col)] = v_val
            node_matched += 1

    total_matched = way_matched + node_matched
    total_unmatched = len(edges_gdf) - total_matched
    print(f"  Way ID matched: {way_matched}")
    print(f"  Node endpoint matched: {node_matched}")
    print(f"  Total matched: {total_matched}/{len(edges_gdf)}")
    print(f"  Unmatched: {total_unmatched}")

    return edges_gdf


def write_processed_to_osmxml(nodes_gdf, merged_ways_gdf, output_path, heat_attrs):
    """Writes a fully-noded OSM XML to disk line-by-line."""
    start_time = time.time()
    timestamp = datetime.now(timezone.utc).strftime('%Y-%m-%dT%H:%M:%SZ')

    # 1. Prepare Base Nodes
    node_coords = {}
    for _, row in nodes_gdf.iterrows():
        nid = int(row['id'])
        node_coords[nid] = (float(row['lat']), float(row['lon']))

    ways_list = merged_ways_gdf.to_dict('records')

    # 2. Generate Intermediate Nodes for the 'Fully Noded' requirement
    intermediate_nodes = []
    synthetic_id = 100_000_000_000

    for row in ways_list:
        geom = row.get('geometry')
        u, v = int(row['u']), int(row['v'])

        if geom is not None and hasattr(geom, 'coords'):
            coords = list(geom.coords)
            if u not in node_coords:
                node_coords[u] = (coords[0][1], coords[0][0])
            if v not in node_coords:
                node_coords[v] = (coords[-1][1], coords[-1][0])

            node_refs = [u]
            for lon, lat in coords[1:-1]:
                intermediate_nodes.append((synthetic_id, lat, lon))
                node_refs.append(synthetic_id)
                synthetic_id += 1
            node_refs.append(v)
            row['node_refs'] = node_refs
        else:
            if u in node_coords and v in node_coords:
                row['node_refs'] = [u, v]
            else:
                row['node_refs'] = []

    # 3. Write XML
    print(f"Writing XML to {output_path}...")
    with open(output_path, "w", encoding="utf-8") as f:
        f.write('<?xml version="1.0" encoding="UTF-8"?>\n')
        f.write('<osm version="0.6" generator="pyrosm_rtree_noded">\n')

        for nid, (lat, lon) in node_coords.items():
            f.write(f'  <node id="{int(nid)}" lat="{lat}" lon="{lon}" version="1" changeset="1" timestamp="{timestamp}" uid="1" user="script"/>\n')
        for nid, lat, lon in intermediate_nodes:
            f.write(f'  <node id="{nid}" lat="{lat}" lon="{lon}" version="1" changeset="1" timestamp="{timestamp}" uid="1" user="script"/>\n')

        skip_keys = {'geometry', 'u', 'v', 'id', 'node_refs', 'osm_way_id'} | set(a.lower() for a in heat_attrs)
        for row in ways_list:
            if not row.get('node_refs'):
                continue

            f.write(f'  <way id="{int(row["id"])}" version="1" changeset="1" timestamp="{timestamp}" uid="1" user="script">\n')
            for nd in row['node_refs']:
                f.write(f'    <nd ref="{nd}"/>\n')

            for k, v in row.items():
                k_low = str(k).lower()
                if k_low in skip_keys or pd.isna(v):
                    continue
                k_esc = k_low.replace('&', '&amp;').replace('"', '&quot;').replace('<', '&lt;').replace('>', '&gt;')
                v_esc = str(v).replace('&', '&amp;').replace('"', '&quot;').replace('<', '&lt;').replace('>', '&gt;')
                f.write(f'    <tag k="{k_esc}" v="{v_esc}"/>\n')

            for attr in heat_attrs:
                val = row.get(attr)
                if val is not None and not (isinstance(val, float) and np.isnan(val)):
                    a_esc = str(attr).lower().replace('&', '&amp;').replace('"', '&quot;').replace('<', '&lt;').replace('>', '&gt;')
                    val_esc = str(val).replace('&', '&amp;').replace('"', '&quot;').replace('<', '&lt;').replace('>', '&gt;')
                    f.write(f'    <tag k="{a_esc}" v="{val_esc}"/>\n')
            f.write('  </way>\n')
        f.write('</osm>\n')
    print(f"Done in {time.time() - start_time:.2f}s")


def run_pipeline(pbf_path, heat_path, output_path, heat_cols,
                 id_col='id', type_col='type',
                 bbox_buffer_km=2.0, drop_unmatched=True):
    """
    Main pipeline: matches heat GeoJSON to OSM PBF by ID, writes enriched OSM XML.

    Args:
        pbf_path: path to .osm.pbf
        heat_path: path to heat GeoJSON (with 'id' and 'type' fields)
        output_path: where to write output .osm XML
        heat_cols: UTCI column names to transfer
        id_col: name of the OSM ID column in the heat GeoJSON
        type_col: name of the type column ('node'/'way') in the heat GeoJSON
        bbox_buffer_km: buffer for node search
        drop_unmatched: if True, drop edges with no heat match
    """
    t0 = time.time()
    print(f"\n{'='*60}")
    print(f"Processing: {os.path.basename(heat_path)}")
    print(f"  PBF:    {pbf_path}")
    print(f"  Output: {output_path}")
    print(f"{'='*60}")

    # 1. Load Heat Data and build ID lookup
    heat_gdf = gpd.read_file(heat_path)
    heat_gdf = heat_gdf[heat_gdf.geometry.notna()].reset_index(drop=True)

    if heat_gdf.empty:
        print(f"  WARNING: {heat_path} has no valid geometries. Skipping.")
        return

    # Validate columns
    if id_col not in heat_gdf.columns:
        raise ValueError(f"Heat GeoJSON missing ID column '{id_col}'. Available: {list(heat_gdf.columns)}")
    if type_col not in heat_gdf.columns:
        raise ValueError(f"Heat GeoJSON missing type column '{type_col}'. Available: {list(heat_gdf.columns)}")

    missing_cols = [c for c in heat_cols if c not in heat_gdf.columns]
    if missing_cols:
        raise ValueError(f"Heat GeoJSON missing expected columns: {missing_cols}")

    print(f"  Heat features: {len(heat_gdf)}")
    print(f"  Geometry types: {heat_gdf.geom_type.value_counts().to_dict()}")
    print(f"  Feature types: {heat_gdf[type_col].value_counts().to_dict()}")

    way_heat, node_heat = build_heat_lookup(heat_gdf, heat_cols, id_col=id_col, type_col=type_col)

    # 2. Extract OSM network
    bounding_box = list(heat_gdf.to_crs("EPSG:4326").total_bounds)
    print(f"  Heat data bbox: {[round(c, 6) for c in bounding_box]}")

    osm = OSM(pbf_path)
    nodes, edges = osm.get_network(network_type="all", nodes=True)

    bbox_polygon = box(*bounding_box)
    edges_in_area = edges[edges.intersects(bbox_polygon)].copy()
    print(f"  Edges in area: {len(edges_in_area)}")

    if edges_in_area.empty:
        print(f"  WARNING: No edges found in bounding box.")
        return

    # 3. Node handling
    referenced_node_ids = set(edges_in_area['u'].astype(int)) | set(edges_in_area['v'].astype(int))
    expanded_bbox = expand_bbox_degrees(bounding_box, buffer_km=bbox_buffer_km)
    expanded_polygon = box(*expanded_bbox)

    nodes_in_expanded = nodes[nodes.intersects(expanded_polygon)]
    nodes_to_keep = nodes_in_expanded[nodes_in_expanded['id'].astype(int).isin(referenced_node_ids)].copy()

    existing_ids = set(nodes_to_keep['id'].astype(int))
    still_missing = referenced_node_ids - existing_ids
    if still_missing:
        print(f"  {len(still_missing)} nodes still missing — reconstructing from geometry...")
        nodes_to_keep, _ = reconstruct_missing_nodes(edges_in_area, nodes_to_keep)
        edges_in_area, _ = drop_edges_with_unresolvable_nodes(edges_in_area, nodes_to_keep)
    else:
        print("  All referenced nodes found within expanded bounding box.")

    # Preserve original OSM way ID before reassigning synthetic IDs
    # Pyrosm stores the original way ID in 'id' — save it for matching
    original_way_ids = edges_in_area['id'].copy()
    edges_in_area['id'] = range(10_000_000_000, 10_000_000_000 + len(edges_in_area))

    # 4. Apply heat values by ID matching
    print(f"\nMatching heat data by OSM ID...")
    edges_with_heat = apply_heat_to_edges(edges_in_area, way_heat, node_heat, heat_cols, original_way_ids)

    # Diagnostic
    unmatched = edges_with_heat[edges_with_heat[heat_cols[0]].isna()]
    if not unmatched.empty and 'highway' in edges_with_heat.columns:
        total_by_type = edges_with_heat['highway'].value_counts()
        matched_df = edges_with_heat[edges_with_heat[heat_cols[0]].notna()]
        matched_by_type = matched_df['highway'].value_counts()

        comparison = pd.DataFrame({
            'total_edges': total_by_type,
            'matched': matched_by_type.reindex(total_by_type.index, fill_value=0).astype(int),
            'unmatched': (total_by_type - matched_by_type.reindex(total_by_type.index, fill_value=0)).astype(int),
        })
        comparison['match_rate'] = (comparison['matched'] / comparison['total_edges'] * 100).round(1)
        print(f"\n  Edge match comparison by highway type:")
        print(comparison.to_string())

    if drop_unmatched and not unmatched.empty:
        edges_with_heat = edges_with_heat[edges_with_heat[heat_cols[0]].notna()].copy()
        print(f"\n  Dropped {len(unmatched)} unmatched edges.")
        print(f"  Final edge count: {len(edges_with_heat)}")

    # 5. Export
    write_processed_to_osmxml(nodes_to_keep, edges_with_heat, output_path, heat_attrs=heat_cols)
    print(f"  Pipeline time: {time.time() - t0:.2f}s")


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="Merge UTCI heat data into OSM network by ID matching.")
    parser.add_argument("--heat-path", required=True,
                        help="Path to the heat GeoJSON (with 'id' and 'type' columns).")
    parser.add_argument("--pbf-path", required=True,
                        help="Path to the .osm.pbf file.")
    parser.add_argument("--output-path", required=True,
                        help="Path for the output .osm XML file.")
    parser.add_argument("--heat-cols", nargs="+",
                        default=['UTCI_07', 'UTCI_08', 'UTCI_09', 'UTCI_10', 'UTCI_11',
                                 'UTCI_12', 'UTCI_13', 'UTCI_14', 'UTCI_15', 'UTCI_16',
                                 'UTCI_17', 'UTCI_18', 'UTCI_19', 'UTCI_20', 'NDVI'],
                        help="UTCI column names to transfer.")
    parser.add_argument("--id-col", default="@id",
                        help="Name of the OSM ID column in the heat GeoJSON (default: @id).")
    parser.add_argument("--type-col", default="@type",
                        help="Name of the type column in the heat GeoJSON (default: @type).")
    parser.add_argument("--bbox-buffer-km", type=float, default=2.0,
                        help="Buffer (km) to expand bbox for node search (default: 2.0).")
    parser.add_argument("--keep-unmatched", action="store_true",
                        help="Keep edges with no heat match (NaN values) instead of dropping them.")
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
        bbox_buffer_km=args.bbox_buffer_km,
        drop_unmatched=not args.keep_unmatched,
    )