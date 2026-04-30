"""
Network Integrity Validation Script.
Compares a GeoJSON network against an OSM PBF reference to identify
missing segments and data quality issues.

Generalized from explore_geojson_2.py to work with any attribute columns
and network data, not just heat-related measurements.
"""

import geopandas as gpd
import pandas as pd
import numpy as np
import sys
import os
from pyrosm import OSM
import warnings

sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from utils.spatial_utils import validate_geometries

# Suppress administrative warnings
warnings.simplefilter(action='ignore', category=FutureWarning)


def validate_network_integrity(
    geojson_path,
    pbf_path,
    attribute_columns=None,
    target_crs="EPSG:4326",
    buffer_distance=7.0,
    zero_is_missing=True,
    progress_callback=None
):
    """
    Comprehensive network integrity check comparing GeoJSON against OSM PBF.
    
    Checks for:
    1. Geometry gaps (segments in PBF but missing from GeoJSON)
    2. Attribute gaps (nulls, zeros, missing data)
    3. Coverage percentage within the PBF footprint
    
    Args:
        geojson_path: Path to network GeoJSON file
        pbf_path: Path to OSM PBF reference file
        attribute_columns: Columns to check for data quality (default: all numeric)
        target_crs: CRS for spatial operations (should be projected for accuracy)
        buffer_distance: Buffer distance for geometry matching (in target_crs units)
        zero_is_missing: If True, treat 0 values as missing data
        progress_callback: Optional callback(progress, message)
        
    Returns:
        tuple: (missing_geometry_gdf, bad_data_gdf, statistics_dict)
    """
    stats = {
        'geojson_features': 0,
        'osm_edges': 0,
        'pbf_area_features': 0,
        'missing_from_geojson': 0,
        'coverage_percentage': 0,
        'bad_data_features': 0,
        'quality_percentage': 0,
        'warnings': [],
        'errors': []
    }
    
    try:
        # === STAGE 1: Load GeoJSON ===
        if progress_callback:
            progress_callback(10, "Loading GeoJSON file...")
        
        print(f"\n{'='*60}")
        print(f"NETWORK INTEGRITY VALIDATION")
        print(f"{'='*60}")
        print(f"\n[1/4] Loading GeoJSON: {os.path.basename(geojson_path)}")
        
        gdf = gpd.read_file(geojson_path)
        stats['geojson_features'] = len(gdf)
        print(f"  Loaded {len(gdf)} features")
        
        # Handle CRS
        if gdf.crs is None:
            warning_msg = "GeoJSON has no CRS defined. Assuming EPSG:4326"
            stats['warnings'].append(warning_msg)
            print(f"  WARNING: {warning_msg}")
            gdf.set_crs("EPSG:4326", inplace=True)
        
        # Reproject to target CRS for accurate buffering
        gdf_projected = gdf.to_crs(target_crs)
        
        if progress_callback:
            progress_callback(30, "Extracting OSM network...")
        
        # === STAGE 2: Load OSM Reference ===
        print(f"\n[2/4] Extracting OSM network from: {os.path.basename(pbf_path)}")
        
        # Get study area from GeoJSON
        study_area = gdf.to_crs("EPSG:4326").unary_union.convex_hull
        
        if study_area.is_empty:
            raise ValueError("Cannot determine study area: GeoJSON has empty geometry")
        
        osm = OSM(pbf_path, bounding_box=study_area)
        osm_edges = osm.get_network(network_type="all")
        
        if len(osm_edges) == 0:
            raise ValueError("PBF extraction returned no edges. "
                           "Check if the PBF covers the GeoJSON area.")
        
        stats['osm_edges'] = len(osm_edges)
        print(f"  Extracted {len(osm_edges)} OSM edges")
        
        # Reproject OSM edges to match GeoJSON projection
        osm_edges = osm_edges.to_crs(target_crs)
        
        if progress_callback:
            progress_callback(60, "Finding missing segments...")
        
        # === STAGE 3: Find Geometry Gaps ===
        print(f"\n[3/4] Finding geometry gaps (OSM vs GeoJSON)...")
        
        # Buffer GeoJSON geometries for intersection test
        gdf_buffered = gdf_projected.copy()
        gdf_buffered['geometry'] = gdf_buffered.geometry.buffer(buffer_distance)
        
        # Spatial join: find OSM edges that don't intersect buffered GeoJSON
        joined = gpd.sjoin(
            osm_edges,
            gdf_buffered,
            how="left",
            predicate="intersects"
        )
        
        missing_from_geojson = joined[joined['index_right'].isna()].copy()
        stats['missing_from_geojson'] = len(missing_from_geojson)
        
        # Calculate coverage
        if len(osm_edges) > 0:
            stats['coverage_percentage'] = (
                (len(osm_edges) - len(missing_from_geojson)) / len(osm_edges) * 100
            )
        
        print(f"  Missing from GeoJSON: {len(missing_from_geojson)} "
              f"({100 - stats['coverage_percentage']:.1f}%)")
        print(f"  Coverage: {stats['coverage_percentage']:.1f}%")
        
        if progress_callback:
            progress_callback(80, "Checking data quality...")
        
        # === STAGE 4: Check Data Quality ===
        print(f"\n[4/4] Checking data quality within PBF footprint...")
        
        # Define PBF footprint
        pbf_footprint = osm_edges.unary_union.convex_hull
        
        # Filter GeoJSON to PBF area only
        gdf_in_pbf_area = gdf_projected[gdf_projected.intersects(pbf_footprint)].copy()
        stats['pbf_area_features'] = len(gdf_in_pbf_area)
        print(f"  Features in PBF area: {len(gdf_in_pbf_area)}")
        
        # Determine columns to check
        if attribute_columns is None:
            # Auto-detect numeric columns
            numeric_cols = gdf_in_pbf_area.select_dtypes(
                include=[np.number]
            ).columns.tolist()
            # Exclude geometry-related columns
            exclude = ['id', 'osm_id', 'index_right', 'OBJECTID', 'FID']
            attribute_columns = [c for c in numeric_cols if c not in exclude]
        
        if attribute_columns:
            print(f"  Checking columns: {attribute_columns}")
            
            # Find rows with null or zero values
            def is_bad_data(row):
                for col in attribute_columns:
                    if col in row.index:
                        val = row[col]
                        if pd.isna(val):
                            return True
                        if zero_is_missing and val == 0:
                            return True
                return False
            
            bad_data_mask = gdf_in_pbf_area.apply(is_bad_data, axis=1)
            bad_data_gdf = gdf_in_pbf_area[bad_data_mask].copy()
            stats['bad_data_features'] = len(bad_data_gdf)
            
            # Calculate quality score
            if len(gdf_in_pbf_area) > 0:
                stats['quality_percentage'] = (
                    (len(gdf_in_pbf_area) - len(bad_data_gdf)) /
                    len(gdf_in_pbf_area) * 100
                )
            
            print(f"  Features with bad data: {len(bad_data_gdf)}")
            print(f"  Data quality: {stats['quality_percentage']:.1f}%")
        else:
            bad_data_gdf = gpd.GeoDataFrame()
            print("  No numeric attribute columns found to check")
        
        if progress_callback:
            progress_callback(100, "Validation complete!")
        
        # === FINAL REPORT ===
        print(f"\n{'='*60}")
        print(f"VALIDATION REPORT")
        print(f"{'='*60}")
        print(f"\n[A] Geometry Coverage")
        print(f"  OSM edges in PBF area:     {stats['osm_edges']}")
        print(f"  Missing from GeoJSON:      {stats['missing_from_geojson']}")
        print(f"  Coverage:                  {stats['coverage_percentage']:.2f}%")
        
        if attribute_columns:
            print(f"\n[B] Data Quality (within PBF bounds)")
            print(f"  Features in PBF area:      {stats['pbf_area_features']}")
            print(f"  Features with bad data:     {stats['bad_data_features']}")
            print(f"  Data quality:               {stats['quality_percentage']:.2f}%")
        
        if not missing_from_geojson.empty:
            if 'id' in missing_from_geojson.columns:
                sample_ids = missing_from_geojson['id'].unique()[:10].tolist()
                print(f"\n  Sample missing OSM IDs: {sample_ids}")
        
        if not bad_data_gdf.empty:
            # Find a suitable ID column
            id_col = None
            for col in ['stableEdgeId', 'id', 'edge_id', 'segment_id']:
                if col in bad_data_gdf.columns:
                    id_col = col
                    break
            
            if id_col:
                sample_ids = bad_data_gdf[id_col].unique()[:10].tolist()
                print(f"  Sample bad data IDs: {sample_ids}")
        
        return missing_from_geojson, bad_data_gdf, stats
    
    except Exception as e:
        stats['errors'].append(str(e))
        print(f"\nERROR: {str(e)}")
        raise


if __name__ == "__main__":
    import argparse
    
    parser = argparse.ArgumentParser(description="Validate Network Integrity")
    parser.add_argument("geojson", help="Path to network GeoJSON")
    parser.add_argument("pbf", help="Path to OSM PBF reference")
    parser.add_argument("--columns", nargs='+',
                       help="Attribute columns to check (default: all numeric)")
    parser.add_argument("--crs", default="EPSG:6491",
                       help="Target CRS for spatial operations")
    parser.add_argument("--buffer", type=float, default=7.0,
                       help="Buffer distance for geometry matching")
    parser.add_argument("--no-zero-check", action='store_true',
                       help="Don't treat zeros as missing data")
    
    args = parser.parse_args()
    
    missing_geo, bad_data, stats = validate_network_integrity(
        geojson_path=args.geojson,
        pbf_path=args.pbf,
        attribute_columns=args.columns,
        target_crs=args.crs,
        buffer_distance=args.buffer,
        zero_is_missing=not args.no_zero_check,
        progress_callback=lambda p, m: print(f"  [{p}%] {m}")
    )
    
    print(f"\nDone. Found {len(missing_geo)} missing segments, "
          f"{len(bad_data)} with bad data.")