"""
Shared spatial utility functions used across multiple scripts.
Includes CRS handling, STRtree spatial joins, coordinate reprojection,
and geometry validation helpers.
"""

import geopandas as gpd
import pandas as pd
import numpy as np
from shapely.strtree import STRtree
from shapely.geometry import box, Point
from pyproj import Transformer, CRS
import warnings


def detect_and_handle_crs(gdf, file_label="Input"):
    """
    Detects CRS of a GeoDataFrame and returns information for UI display.
    
    Args:
        gdf: GeoDataFrame to check
        file_label: Label for display purposes
        
    Returns:
        dict with 'crs', 'epsg', 'is_projected', 'units', 'valid'
    """
    info = {
        'crs': str(gdf.crs),
        'epsg': None,
        'is_projected': False,
        'units': 'degrees',
        'valid': True
    }
    
    if gdf.crs is None:
        info['valid'] = False
        info['crs'] = 'Not specified (assumed WGS84)'
        return info
    
    try:
        crs_obj = CRS.from_user_input(gdf.crs)
        if crs_obj.is_epsg_code:
            info['epsg'] = crs_obj.to_epsg()
        info['is_projected'] = crs_obj.is_projected
        info['units'] = 'meters' if crs_obj.is_projected else 'degrees'
    except Exception as e:
        info['crs'] = f"Error parsing CRS: {str(e)}"
        info['valid'] = False
    
    return info


def reproject_if_needed(gdf, target_crs="EPSG:4326", silent=False):
    """
    Reprojects GeoDataFrame to target CRS if different.
    
    Args:
        gdf: Input GeoDataFrame
        target_crs: Target CRS (default WGS84)
        silent: If True, suppress print statements
        
    Returns:
        Reprojected GeoDataFrame
    """
    if gdf.crs is None:
        if not silent:
            print(f"No CRS defined. Assuming {target_crs}.")
        gdf = gdf.set_crs(target_crs)
        return gdf
    
    if gdf.crs != target_crs:
        if not silent:
            print(f"Reprojecting from {gdf.crs} to {target_crs}...")
        return gdf.to_crs(target_crs)
    
    return gdf


def spatial_nearest_join(
    target_gdf,
    source_gdf,
    attribute_cols,
    max_distance=None,
    match_strategy='nearest',
    fill_missing='nan',
    fill_value=None,
    progress_callback=None
):
    """
    Performs spatial nearest-neighbor join using STRtree for efficiency.
    
    Matches each target geometry to the nearest source geometry and transfers
    specified attributes if within max_distance (when specified).
    
    Args:
        target_gdf: GeoDataFrame to enrich (will be projected to match source CRS)
        source_gdf: GeoDataFrame with attributes to transfer
        attribute_cols: List of column names to transfer from source to target
        max_distance: Maximum distance in source CRS units (None = no limit)
        match_strategy: 'nearest' only for now (extensible)
        fill_missing: 'nan' or 'value' - how to handle unmatched targets
        fill_value: Value to use when fill_missing='value'
        progress_callback: Optional callback(current, total) for progress updates
        
    Returns:
        tuple: (enriched_target_gdf, statistics_dict)
    """
    # Validate inputs
    if source_gdf.crs is None:
        raise ValueError("Source GeoDataFrame has no CRS defined. Cannot perform spatial join.")
    
    if target_gdf.crs is None:
        raise ValueError("Target GeoDataFrame has no CRS defined. Please assign a CRS.")
    
    # Reproject target to match source CRS for accurate distance calculations
    target_proj = target_gdf.to_crs(source_gdf.crs)
    
    # Validate attribute columns exist in source
    missing_cols = [col for col in attribute_cols if col not in source_gdf.columns]
    if missing_cols:
        raise ValueError(f"Attribute columns not found in source: {missing_cols}")
    
    print(f"Performing spatial nearest-neighbor join...")
    print(f"  Target features: {len(target_proj)}")
    print(f"  Source features: {len(source_gdf)}")
    print(f"  Attributes to transfer: {attribute_cols}")
    print(f"  Max distance: {max_distance if max_distance else 'No limit'}")
    print(f"  Fill strategy: {fill_missing}")
    
    # Build STRtree on source geometries
    tree = STRtree(source_gdf.geometry.values)
    
    # Initialize target columns with appropriate missing values
    for col in attribute_cols:
        if fill_missing == 'value' and fill_value is not None:
            target_proj[col] = fill_value
        else:
            target_proj[col] = np.nan
    
    # Track column positions for performance
    source_col_indices = {col: source_gdf.columns.get_loc(col) for col in attribute_cols}
    target_col_indices = {col: target_proj.columns.get_loc(col) for col in attribute_cols}
    
    # Perform nearest neighbor queries
    target_geoms = target_proj.geometry.values
    source_geoms = source_gdf.geometry.values
    
    # Query all targets at once using STRtree.nearest
    try:
        nearest_indices = tree.nearest(target_geoms)
        # nearest_indices shape: (n_targets, 1) for single nearest, or (n_targets, k) for k nearest
        if len(nearest_indices.shape) == 1:
            nearest_indices = nearest_indices.reshape(-1, 1)
    except Exception as e:
        raise RuntimeError(f"STRtree.nearest query failed: {str(e)}")
    
    matched_count = 0
    total = len(target_proj)
    
    # Process matches
    for i in range(total):
        if progress_callback and i % max(1, total // 100) == 0:
            progress_callback(i, total)
        
        best_match_idx = nearest_indices[i, 0]
        
        # Check distance threshold if specified
        if max_distance is not None:
            dist = target_geoms[i].distance(source_geoms[best_match_idx])
            if dist > max_distance:
                continue  # Skip this match, leave as missing value
        
        # Transfer attributes
        for col, src_idx in source_col_indices.items():
            target_proj.iat[i, target_col_indices[col]] = source_gdf.iat[best_match_idx, src_idx]
        
        matched_count += 1
    
    if progress_callback:
        progress_callback(total, total)
    
    # Calculate statistics
    unmatched_count = total - matched_count
    stats = {
        'total_targets': total,
        'matched': matched_count,
        'unmatched': unmatched_count,
        'match_percentage': (matched_count / total * 100) if total > 0 else 0,
        'max_distance_used': max_distance,
        'fill_strategy': fill_missing,
        'attributes_transferred': attribute_cols,
        'unmatched_ids': target_proj.iloc[np.where(
            target_proj[attribute_cols[0]].isna()
        )[0]].index.tolist() if unmatched_count > 0 else []
    }
    
    print(f"  Matched: {matched_count}/{total} ({stats['match_percentage']:.1f}%)")
    print(f"  Unmatched: {unmatched_count}")
    
    return target_proj, stats


def filter_by_bounding_box(gdf, bbox, bbox_crs="EPSG:4326"):
    """
    Filters GeoDataFrame to features intersecting a bounding box.
    
    Args:
        gdf: Input GeoDataFrame
        bbox: [minx, miny, maxx, maxy] or Shapely polygon
        bbox_crs: CRS of the bbox coordinates
        
    Returns:
        Filtered GeoDataFrame
    """
    if isinstance(bbox, (list, tuple)):
        bbox_poly = box(*bbox)
    else:
        bbox_poly = bbox
    
    # Create a temporary GeoSeries in the bbox CRS
    bbox_gdf = gpd.GeoDataFrame(
        geometry=[bbox_poly],
        crs=bbox_crs
    )
    
    # Reproject bbox to match gdf CRS if needed
    if gdf.crs != bbox_gdf.crs:
        bbox_gdf = bbox_gdf.to_crs(gdf.crs)
    
    bbox_poly = bbox_gdf.geometry.iloc[0]
    
    # Filter
    mask = gdf.geometry.intersects(bbox_poly)
    filtered = gdf[mask].copy()
    
    print(f"  Bounding box filter: {len(filtered)}/{len(gdf)} features retained")
    
    return filtered


def get_geojson_preview(gdf, max_features=5):
    """
    Generates a preview of a GeoDataFrame for Streamlit display.
    
    Args:
        gdf: Input GeoDataFrame
        max_features: Maximum number of features to include in preview
        
    Returns:
        dict with preview information
    """
    preview = {
        'total_features': len(gdf),
        'total_columns': len(gdf.columns),
        'columns': list(gdf.columns),
        'geometry_type': str(gdf.geometry.geom_type.unique()),
        'crs': str(gdf.crs),
        'sample_rows': min(max_features, len(gdf)),
        'data_preview': gdf.head(max_features).drop(columns=['geometry'], errors='ignore').to_dict('records')
    }
    return preview


def validate_geometries(gdf, label="Input"):
    """
    Validates geometries in a GeoDataFrame and reports issues.
    
    Args:
        gdf: Input GeoDataFrame
        label: Label for display purposes
        
    Returns:
        tuple: (cleaned_gdf, issues_dict)
    """
    issues = {
        'null_geometries': 0,
        'invalid_geometries': 0,
        'empty_geometries': 0,
        'total_removed': 0
    }
    
    # Check for None/NaN geometries
    null_mask = gdf.geometry.isna()
    issues['null_geometries'] = null_mask.sum()
    
    # Check for empty geometries
    empty_mask = gdf.geometry.is_empty if len(gdf) > 0 else pd.Series([False])
    issues['empty_geometries'] = empty_mask.sum()
    
    # Check for invalid geometries (self-intersections, etc.)
    with warnings.catch_warnings():
        warnings.simplefilter('ignore')
        invalid_mask = ~gdf.geometry.is_valid if len(gdf) > 0 else pd.Series([False])
    issues['invalid_geometries'] = invalid_mask.sum()
    
    # Combine all issues
    bad_mask = null_mask | empty_mask | invalid_mask
    issues['total_removed'] = bad_mask.sum()
    
    if issues['total_removed'] > 0:
        print(f"  {label}: Removed {issues['total_removed']} problematic geometries")
        print(f"    - Null geometries: {issues['null_geometries']}")
        print(f"    - Empty geometries: {issues['empty_geometries']}")
        print(f"    - Invalid geometries: {issues['invalid_geometries']}")
        cleaned_gdf = gdf[~bad_mask].copy()
    else:
        cleaned_gdf = gdf.copy()
    
    return cleaned_gdf, issues