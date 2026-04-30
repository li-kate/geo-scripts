"""
Unified Spatial Merge Script.
Performs spatial nearest-neighbor join to transfer attributes from a source
GeoJSON to either a target GeoJSON (outputting GeoJSON) or an OSM PBF
(outputting fully-noded OSM XML).

Handles CRS mismatches, missing geometries, bounding box filtering,
and various join strategies through a single interface.
"""

import geopandas as gpd
import pandas as pd
import numpy as np
import time
import os
import sys
from datetime import datetime, timezone
from pyrosm import OSM
from shapely.strtree import STRtree
from shapely.geometry import box
import osmnx as ox
from shapely.ops import unary_union

sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from utils.spatial_utils import (
    spatial_nearest_join,
    filter_by_bounding_box,
    validate_geometries,
    get_geojson_preview,
    detect_and_handle_crs
)


# ============================================================================
# PBF-SPECIFIC FUNCTIONS
# ============================================================================

def reconstruct_missing_nodes(edges_gdf, existing_nodes_gdf):
    """
    Reconstructs missing node geometries from edge LineString endpoints.

    OSM ways can reference nodes outside the PBF extract's coverage.
    Since each edge has a LineString whose first coord = node u and last coord = node v,
    we can recover the lat/lon of any missing node from the geometry.

    Returns:
        combined_nodes_gdf: GeoDataFrame with original + reconstructed nodes (id, lat, lon, geometry)
        n_reconstructed: count of nodes that were synthesized
    """
    existing_ids = set(existing_nodes_gdf['id'].astype(int))
    referenced_ids = set(edges_gdf['u'].astype(int)) | set(edges_gdf['v'].astype(int))
    missing_ids = referenced_ids - existing_ids

    if not missing_ids:
        print("No missing nodes to reconstruct.")
        return existing_nodes_gdf, 0

    print(f"Reconstructing {len(missing_ids)} missing nodes from edge geometry...")

    # Build a lookup: missing_node_id -> (lat, lon) from edge endpoints
    missing_coords = {}

    for _, row in edges_gdf.iterrows():
        geom = row.get('geometry')
        if geom is None or not hasattr(geom, 'coords'):
            continue

        coords = list(geom.coords)
        u, v = int(row['u']), int(row['v'])

        # coords are (lon, lat) in GeoDataFrames
        if u in missing_ids and u not in missing_coords:
            missing_coords[u] = (coords[0][1], coords[0][0])  # (lat, lon)
        if v in missing_ids and v not in missing_coords:
            missing_coords[v] = (coords[-1][1], coords[-1][0])  # (lat, lon)

    # Report any nodes we still couldn't resolve (edges with no geometry)
    still_missing = missing_ids - set(missing_coords.keys())
    if still_missing:
        print(f"  WARNING: {len(still_missing)} nodes could not be reconstructed "
              f"(edges lack geometry). Edges referencing these nodes will be dropped.")

    if not missing_coords:
        return existing_nodes_gdf, 0

    # Build a GeoDataFrame for reconstructed nodes
    reconstructed_records = []
    for nid, (lat, lon) in missing_coords.items():
        reconstructed_records.append({'id': nid, 'lat': lat, 'lon': lon})

    reconstructed_df = pd.DataFrame(reconstructed_records)
    reconstructed_gdf = gpd.GeoDataFrame(
        reconstructed_df,
        geometry=gpd.points_from_xy(reconstructed_df['lon'], reconstructed_df['lat']),
        crs=existing_nodes_gdf.crs
    )

    combined = pd.concat([existing_nodes_gdf, reconstructed_gdf], ignore_index=True)
    print(f"  Reconstructed {len(missing_coords)} nodes. "
          f"Still unresolvable: {len(still_missing)}.")
    return combined, len(missing_coords)


def drop_edges_with_unresolvable_nodes(edges_gdf, nodes_gdf):
    """
    Drops edges that reference nodes not present in the nodes GeoDataFrame.
    This is the fallback for nodes that couldn't be reconstructed from geometry.

    Returns:
        filtered_edges_gdf, n_dropped
    """
    valid_ids = set(nodes_gdf['id'].astype(int))
    mask = (
        edges_gdf['u'].astype(int).isin(valid_ids) &
        edges_gdf['v'].astype(int).isin(valid_ids)
    )
    n_dropped = (~mask).sum()
    if n_dropped > 0:
        print(f"Dropped {n_dropped} edges with unresolvable node references.")
    return edges_gdf[mask].copy(), n_dropped


def write_processed_to_osmxml(
    nodes_gdf,
    merged_ways_gdf,
    output_path,
    attribute_columns=None
):
    """
    Writes a fully-noded OSM XML to disk line-by-line.
    
    Args:
        nodes_gdf: GeoDataFrame of nodes
        merged_ways_gdf: GeoDataFrame of ways with attributes
        output_path: Output XML file path
        attribute_columns: List of columns to write as OSM tags
    """
    start_time = time.time()
    timestamp = datetime.now(timezone.utc).strftime('%Y-%m-%dT%H:%M:%SZ')

    if attribute_columns is None:
        attribute_columns = []

    # Prepare base nodes lookup
    node_coords = {}
    for _, row in nodes_gdf.iterrows():
        nid = int(row['id'])
        node_coords[nid] = (float(row['lat']), float(row['lon']))

    ways_list = merged_ways_gdf.to_dict('records')

    # Generate intermediate nodes for fully-noded requirement
    intermediate_nodes = []
    synthetic_id = 100_000_000_000

    for row in ways_list:
        geom = row.get('geometry')
        u, v = int(row['u']), int(row['v'])

        if geom is not None and hasattr(geom, 'coords'):
            coords = list(geom.coords)

            # Safety net: populate node_coords from geometry if missing
            if u not in node_coords:
                node_coords[u] = (coords[0][1], coords[0][0])  # lat, lon
            if v not in node_coords:
                node_coords[v] = (coords[-1][1], coords[-1][0])  # lat, lon

            node_refs = [u]
            # Create nodes for intermediate points
            for lon, lat in coords[1:-1]:
                intermediate_nodes.append((synthetic_id, lat, lon))
                node_refs.append(synthetic_id)
                synthetic_id += 1
            node_refs.append(v)
            row['node_refs'] = node_refs
        else:
            # No geometry: only write if both nodes exist
            if u in node_coords and v in node_coords:
                row['node_refs'] = [u, v]
            else:
                row['node_refs'] = []  # Will be filtered below

    # Write XML
    print(f"Writing XML to {output_path}...")
    with open(output_path, "w", encoding="utf-8") as f:
        f.write('<?xml version="1.0" encoding="UTF-8"?>\n')
        f.write('<osm version="0.6" generator="spatial_merge_pipeline">\n')

        # Write original nodes
        for nid, (lat, lon) in node_coords.items():
            f.write(f'  <node id="{int(nid)}" lat="{lat}" lon="{lon}" '
                   f'version="1" changeset="1" timestamp="{timestamp}" '
                   f'uid="1" user="script"/>\n')
        
        # Write intermediate nodes
        for nid, lat, lon in intermediate_nodes:
            f.write(f'  <node id="{nid}" lat="{lat}" lon="{lon}" '
                   f'version="1" changeset="1" timestamp="{timestamp}" '
                   f'uid="1" user="script"/>\n')

        # Write ways
        skip_keys = {'geometry', 'u', 'v', 'id', 'node_refs'}
        skip_keys.update(a.lower() for a in attribute_columns)

        for row in ways_list:
            if not row.get('node_refs'):
                continue

            f.write(f'  <way id="{int(row["id"])}" version="1" changeset="1" '
                   f'timestamp="{timestamp}" uid="1" user="script">\n')
            
            for nd in row['node_refs']:
                f.write(f'    <nd ref="{nd}"/>\n')

            # Write standard OSM tags
            for k, v in row.items():
                k_low = str(k).lower()
                if k_low in skip_keys or pd.isna(v):
                    continue
                k_esc = str(k_low).replace('&', '&amp;').replace('"', '&quot;')\
                                   .replace('<', '&lt;').replace('>', '&gt;')
                v_esc = str(v).replace('&', '&amp;').replace('"', '&quot;')\
                               .replace('<', '&lt;').replace('>', '&gt;')
                f.write(f'    <tag k="{k_esc}" v="{v_esc}"/>\n')

            # Write merged attribute tags (skip NaN)
            for attr in attribute_columns:
                val = row.get(attr)
                if val is not None and not (isinstance(val, float) and np.isnan(val)):
                    a_esc = str(attr).lower().replace('&', '&amp;')\
                                    .replace('"', '&quot;').replace('<', '&lt;')\
                                    .replace('>', '&gt;')
                    val_esc = str(val).replace('&', '&amp;').replace('"', '&quot;')\
                                     .replace('<', '&lt;').replace('>', '&gt;')
                    f.write(f'    <tag k="{a_esc}" v="{val_esc}"/>\n')
            f.write('  </way>\n')
        f.write('</osm>\n')
    
    print(f"Done in {time.time() - start_time:.2f}s")


# ============================================================================
# BOUNDING BOX HELPERS
# ============================================================================

def get_bounding_box(mode, **kwargs):
    """
    Get bounding box based on different modes.
    
    Args:
        mode: 'custom', 'cities', 'source_bounds', 'target_bounds'
        **kwargs: Additional arguments based on mode
            - For 'custom': bbox=[minx, miny, maxx, maxy]
            - For 'cities': city_names=['City1', 'City2']
            - For 'source_bounds': source_gdf
            - For 'target_bounds': target_gdf
            
    Returns:
        list: [minx, miny, maxx, maxy] in EPSG:4326
    """
    if mode == 'custom':
        bbox = kwargs.get('bbox')
        if bbox is None:
            raise ValueError("Custom bbox requires bbox=[minx, miny, maxx, maxy]")
        return bbox
    
    elif mode == 'cities':
        city_names = kwargs.get('city_names', [])
        if not city_names:
            raise ValueError("Cities mode requires city_names list")
        
        city_geometries = []
        for city in city_names:
            try:
                gdf = ox.geocode_to_gdf(city)
                city_geometries.append(gdf.geometry.iloc[0])
                print(f"  Geocoded: {city}")
            except Exception as e:
                print(f"  Could not find {city}: {e}")
        
        if not city_geometries:
            raise RuntimeError("No city geometries could be geocoded. Cannot proceed.")
        
        combined_geometry = unary_union(city_geometries)
        return list(combined_geometry.bounds)
    
    elif mode == 'source_bounds':
        source_gdf = kwargs.get('source_gdf')
        if source_gdf is None:
            raise ValueError("source_bounds mode requires source_gdf")
        return list(source_gdf.to_crs("EPSG:4326").total_bounds)
    
    elif mode == 'target_bounds':
        target_gdf = kwargs.get('target_gdf')
        if target_gdf is None:
            raise ValueError("target_bounds mode requires target_gdf")
        return list(target_gdf.to_crs("EPSG:4326").total_bounds)
    
    else:
        raise ValueError(f"Unknown bounding box mode: {mode}")


# ============================================================================
# MAIN UNIFIED PIPELINE
# ============================================================================

def spatial_merge(
    target_path,
    source_path,
    attribute_columns,
    target_type='geojson',      # 'geojson' or 'pbf'
    max_distance=None,
    output_path=None,
    bbox_mode=None,             # None, 'custom', 'cities', 'source_bounds', 'target_bounds'
    bbox_custom=None,
    city_names=None,
    fill_strategy='nan',
    fill_value=None,
    target_crs=None,
    network_type="all",         # Only for PBF targets
    progress_callback=None
):
    """
    Unified spatial merge pipeline.
    
    Transfers attributes from a source GeoJSON to a target dataset using
    spatial nearest-neighbor join.
    
    For target_type='geojson': outputs an enriched GeoJSON
    For target_type='pbf': extracts OSM network from PBF, merges attributes,
                           filters by bounding box, and outputs fully-noded OSM XML
    
    Args:
        target_path: Path to target GeoJSON or OSM PBF file
        source_path: Path to source GeoJSON with attributes to transfer
        attribute_columns: List of column names to transfer
        target_type: 'geojson' or 'pbf'
        max_distance: Maximum distance for matching (in source CRS units)
        output_path: Path for output file (auto-generated if None)
        bbox_mode: Bounding box mode (None for no filtering)
        bbox_custom: [minx, miny, maxx, maxy] for 'custom' mode
        city_names: List of city names for 'cities' mode
        fill_strategy: 'nan' or 'value' for unmatched features
        fill_value: Value for unmatched features when fill_strategy='value'
        target_crs: Optional CRS for output (defaults to source CRS)
        network_type: OSM network type for PBF extraction
        progress_callback: Optional callback(progress_percent, message)
        
    Returns:
        tuple: (output_path, statistics_dict)
    """
    t0 = time.time()
    stats = {
        'execution_time': 0,
        'target_type': target_type,
        'target_features': 0,
        'source_features': 0,
        'matched_features': 0,
        'unmatched_features': 0,
        'match_percentage': 0,
        'output_features': 0,
        'output_file': None,
        'warnings': [],
        'errors': []
    }
    
    try:
        print(f"\n{'='*60}")
        print(f"SPATIAL MERGE PIPELINE")
        print(f"{'='*60}")
        print(f"  Target type: {target_type.upper()}")
        print(f"  Source: {os.path.basename(source_path)}")
        print(f"  Target: {os.path.basename(target_path)}")
        print(f"  Attributes: {attribute_columns}")
        print(f"  Max distance: {max_distance if max_distance else 'No limit'}")
        
        # ====================================================================
        # STAGE 1: Load and validate source GeoJSON
        # ====================================================================
        if progress_callback:
            progress_callback(5, "Loading source GeoJSON...")
        
        print(f"\n[1/4] Loading source GeoJSON...")
        source_gdf = gpd.read_file(source_path)
        source_gdf = source_gdf[source_gdf.geometry.notna()].reset_index(drop=True)
        source_gdf, source_geom_issues = validate_geometries(source_gdf, "Source")
        stats['source_features'] = len(source_gdf)
        print(f"  Loaded {len(source_gdf)} valid features")
        
        # Validate attribute columns
        missing_cols = [c for c in attribute_columns if c not in source_gdf.columns]
        if missing_cols:
            raise ValueError(f"Columns not found in source: {missing_cols}")
        
        if progress_callback:
            progress_callback(10, "Loading target data...")
        
        # ====================================================================
        # STAGE 2: Load target based on type
        # ====================================================================
        if target_type == 'geojson':
            print(f"\n[2/4] Loading target GeoJSON...")
            target_gdf = gpd.read_file(target_path)
            target_gdf, target_geom_issues = validate_geometries(target_gdf, "Target")
            stats['target_features'] = len(target_gdf)
            print(f"  Loaded {len(target_gdf)} valid features")
            
            # Apply bounding box filter if specified
            if bbox_mode:
                print(f"  Applying bounding box filter (mode: {bbox_mode})...")
                if bbox_mode == 'custom' and bbox_custom:
                    bbox = bbox_custom
                elif bbox_mode == 'cities' and city_names:
                    bbox = get_bounding_box('cities', city_names=city_names)
                elif bbox_mode == 'source_bounds':
                    bbox = get_bounding_box('source_bounds', source_gdf=source_gdf)
                elif bbox_mode == 'target_bounds':
                    bbox = get_bounding_box('target_bounds', target_gdf=target_gdf)
                else:
                    raise ValueError(f"Invalid bbox_mode '{bbox_mode}' or missing parameters")
                
                target_gdf = filter_by_bounding_box(target_gdf, bbox)
                stats['target_features'] = len(target_gdf)
            
            if progress_callback:
                progress_callback(25, "Performing spatial merge...")
            
            # ================================================================
            # STAGE 3: Spatial join for GeoJSON target
            # ================================================================
            print(f"\n[3/4] Performing spatial merge...")
            
            enriched_gdf, join_stats = spatial_nearest_join(
                target_gdf=target_gdf,
                source_gdf=source_gdf,
                attribute_cols=attribute_columns,
                max_distance=max_distance,
                match_strategy='nearest',
                fill_missing=fill_strategy,
                fill_value=fill_value,
                progress_callback=lambda c, t: progress_callback(
                    25 + int((c/t)*60), f"Matching features ({c}/{t})..."
                ) if progress_callback else None
            )
            
            stats.update({
                'matched_features': join_stats['matched'],
                'unmatched_features': join_stats['unmatched'],
                'match_percentage': join_stats['match_percentage'],
                'output_features': len(enriched_gdf)
            })
            
            if progress_callback:
                progress_callback(90, "Saving output...")
            
            # ================================================================
            # STAGE 4: Save GeoJSON output
            # ================================================================
            print(f"\n[4/4] Saving enriched GeoJSON...")
            
            if output_path is None:
                base = os.path.splitext(os.path.basename(target_path))[0]
                output_path = f"{base}_merged.geojson"
            
            # Apply target CRS if specified
            if target_crs:
                enriched_gdf = enriched_gdf.to_crs(target_crs)
            
            enriched_gdf.to_file(output_path, driver='GeoJSON')
            stats['output_file'] = output_path
            print(f"  Saved to: {output_path}")
        
        # ====================================================================
        # PBF TARGET PATH
        # ====================================================================
        elif target_type == 'pbf':
            print(f"\n[2/4] Extracting OSM network from PBF...")
            print(f"  Network type: {network_type}")
            
            # Determine bounding box
            if bbox_mode is None:
                # Default to source bounds for PBF targets
                bbox_mode = 'source_bounds'
                print(f"  Using source bounds as default bounding box")
            
            if bbox_mode == 'custom' and bbox_custom:
                bounding_box = bbox_custom
            elif bbox_mode == 'cities' and city_names:
                bounding_box = get_bounding_box('cities', city_names=city_names)
            elif bbox_mode == 'source_bounds':
                bounding_box = get_bounding_box('source_bounds', source_gdf=source_gdf)
            elif bbox_mode == 'target_bounds':
                # For PBF, target_bounds means full PBF extent (no filter)
                print(f"  Using full PBF extent (no bounding box filter)")
                bounding_box = None
            else:
                raise ValueError(f"Invalid bbox_mode '{bbox_mode}' for PBF target")
            
            if bounding_box:
                print(f"  Bounding box: {bounding_box}")
            
            # Extract OSM network
            # Load full OSM because ways can reference nodes outside bounding box
            osm = OSM(target_path)
            nodes, edges = osm.get_network(network_type=network_type, nodes=True)
            
            print(f"  Total edges in PBF: {len(edges)}")
            print(f"  Total nodes in PBF: {len(nodes)}")
            
            # Filter to bounding box if specified
            if bounding_box:
                bbox_polygon = box(*bounding_box)
                edges_in_area = edges[edges.intersects(bbox_polygon)].copy()
                print(f"  Edges in area of interest: {len(edges_in_area)}")
            else:
                edges_in_area = edges.copy()
            
            # Get referenced node IDs
            referenced_node_ids = (
                set(edges_in_area['u'].astype(int)) |
                set(edges_in_area['v'].astype(int))
            )
            nodes_to_keep = nodes[nodes['id'].astype(int).isin(referenced_node_ids)].copy()
            
            if progress_callback:
                progress_callback(35, "Reconstructing missing nodes...")
            
            # ================================================================
            # STAGE 3: Handle missing nodes + spatial join for PBF target
            # ================================================================
            print(f"\n[3/4] Handling node references + spatial merge...")
            
            # Reconstruct missing nodes from edge geometries
            nodes_to_keep, n_reconstructed = reconstruct_missing_nodes(
                edges_in_area, nodes_to_keep
            )
            stats['nodes_reconstructed'] = n_reconstructed
            
            # Drop edges with unresolvable nodes
            edges_in_area, n_dropped = drop_edges_with_unresolvable_nodes(
                edges_in_area, nodes_to_keep
            )
            stats['edges_dropped'] = n_dropped
            
            # Add IDs to edges if missing
            if 'id' not in edges_in_area.columns or edges_in_area['id'].isna().all():
                edges_in_area['id'] = range(
                    10_000_000_000,
                    10_000_000_000 + len(edges_in_area)
                )
            
            stats['target_features'] = len(edges_in_area)
            
            if progress_callback:
                progress_callback(50, "Performing spatial merge...")
            
            # Perform spatial join
            edges_with_attrs, join_stats = spatial_nearest_join(
                target_gdf=edges_in_area,
                source_gdf=source_gdf,
                attribute_cols=attribute_columns,
                max_distance=max_distance,
                match_strategy='nearest',
                fill_missing=fill_strategy,
                fill_value=fill_value,
                progress_callback=lambda c, t: progress_callback(
                    50 + int((c/t)*35), f"Matching edges ({c}/{t})..."
                ) if progress_callback else None
            )
            
            stats.update({
                'matched_features': join_stats['matched'],
                'unmatched_features': join_stats['unmatched'],
                'match_percentage': join_stats['match_percentage'],
                'output_features': len(edges_with_attrs)
            })
            
            if progress_callback:
                progress_callback(90, "Writing OSM XML output...")
            
            # ================================================================
            # STAGE 4: Write OSM XML output
            # ================================================================
            print(f"\n[4/4] Writing OSM XML...")
            
            if output_path is None:
                base = os.path.splitext(os.path.basename(target_path))[0]
                output_path = f"{base}_merged.osm"
            
            write_processed_to_osmxml(
                nodes_gdf=nodes_to_keep,
                merged_ways_gdf=edges_with_attrs,
                output_path=output_path,
                attribute_columns=attribute_columns
            )
            
            stats['output_file'] = output_path
            stats['nodes_in_output'] = len(nodes_to_keep) + n_reconstructed
        
        else:
            raise ValueError(f"Unknown target_type: {target_type}")
        
        # ====================================================================
        # FINAL STATISTICS
        # ====================================================================
        elapsed = time.time() - t0
        stats['execution_time'] = elapsed
        
        print(f"\n{'='*60}")
        print(f"SPATIAL MERGE COMPLETE")
        print(f"{'='*60}")
        print(f"  Output: {stats['output_file']}")
        print(f"  Features: {stats['output_features']}")
        print(f"  Matched: {stats['matched_features']}/{stats['target_features']} "
              f"({stats['match_percentage']:.1f}%)")
        print(f"  Time: {elapsed:.2f}s")
        
        if progress_callback:
            progress_callback(100, "Complete!")
        
        return output_path, stats
    
    except Exception as e:
        stats['errors'].append(str(e))
        print(f"\nERROR: {str(e)}")
        raise


# ============================================================================
# CLI SUPPORT
# ============================================================================

if __name__ == "__main__":
    import argparse
    
    parser = argparse.ArgumentParser(description="Unified Spatial Merge Pipeline")
    parser.add_argument("target", help="Target GeoJSON or OSM PBF file")
    parser.add_argument("source", help="Source GeoJSON with attributes")
    parser.add_argument("--columns", nargs='+', required=True,
                       help="Attribute columns to transfer")
    parser.add_argument("--target-type", choices=['geojson', 'pbf'],
                       default='geojson', help="Target file type")
    parser.add_argument("--max-distance", type=float,
                       help="Maximum matching distance")
    parser.add_argument("--output", help="Output file path")
    parser.add_argument("--bbox-mode",
                       choices=['custom', 'cities', 'source_bounds', 'target_bounds'],
                       help="Bounding box mode")
    parser.add_argument("--bbox", nargs=4, type=float,
                       help="Custom bounding box: minx miny maxx maxy")
    parser.add_argument("--cities", nargs='+',
                       help="City names for cities mode")
    parser.add_argument("--fill-strategy", choices=['nan', 'value'],
                       default='nan', help="Strategy for unmatched features")
    parser.add_argument("--fill-value", type=float,
                       help="Fill value for unmatched features")
    parser.add_argument("--target-crs", help="Target CRS for output")
    parser.add_argument("--network-type", default="all",
                       help="OSM network type (PBF only)")
    
    args = parser.parse_args()
    
    output, stats = spatial_merge(
        target_path=args.target,
        source_path=args.source,
        attribute_columns=args.columns,
        target_type=args.target_type,
        max_distance=args.max_distance,
        output_path=args.output,
        bbox_mode=args.bbox_mode,
        bbox_custom=args.bbox if args.bbox else None,
        city_names=args.cities,
        fill_strategy=args.fill_strategy,
        fill_value=args.fill_value,
        target_crs=args.target_crs,
        network_type=args.network_type
    )
    
    print(f"\nSuccess! Output saved to: {output}")