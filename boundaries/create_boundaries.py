"""
City Boundary Creation Script.
Creates boundary LineStrings from multiple GeoJSON input files
using convex hull of all points in each file.

Generalized from get_boundary.py with enhanced CRS handling,
validation, and support for various input geometries.
"""

import json
import glob
import os
import sys
from shapely.geometry import shape, MultiPoint
from pyproj import Transformer, CRS
import geopandas as gpd
import pandas as pd

sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


def get_epsg_from_geojson(data):
    """
    Extract EPSG code from GeoJSON crs property.
    
    Handles various CRS specification formats:
    - urn:ogc:def:crs:EPSG::6491
    - urn:ogc:def:crs:OGC:1.3:CRS84
    - Named CRS in properties
    
    Returns:
        int: EPSG code, or None if already WGS84 or not specified
    """
    crs_info = data.get('crs')
    if not crs_info:
        return None  # No CRS = assume WGS84

    name = crs_info.get('properties', {}).get('name', '')

    # Handle "urn:ogc:def:crs:EPSG::6491" format
    if 'EPSG' in name:
        code = name.split(':')[-1]
        try:
            code = int(code)
            if code == 4326:
                return None  # Already WGS84
            return code
        except ValueError:
            pass

    # Handle "urn:ogc:def:crs:OGC:1.3:CRS84" format (WGS84)
    if 'CRS84' in name:
        return None

    print(f"  Warning: Could not parse CRS '{name}', assuming WGS84")
    return None


def reproject_coords(coords, source_epsg):
    """
    Reproject coordinates from source EPSG to WGS84.
    
    Args:
        coords: List of (x, y) tuples
        source_epsg: Source EPSG code
        
    Returns:
        List of (lon, lat) tuples in WGS84
    """
    transformer = Transformer.from_crs(
        CRS.from_epsg(source_epsg),
        CRS.from_epsg(4326),
        always_xy=True
    )
    reprojected = []
    for x, y in coords:
        lon, lat = transformer.transform(x, y)
        reprojected.append((lon, lat))
    return reprojected


def extract_coords(geom):
    """
    Extract all coordinates from any geometry type.
    
    Supports: Point, LineString, MultiLineString, MultiPoint, Polygon
    
    Args:
        geom: Shapely geometry object
        
    Returns:
        List of (x, y) coordinate tuples
    """
    if geom.geom_type == 'Point':
        return [geom.coords[0]]
    elif geom.geom_type == 'LineString':
        return list(geom.coords)
    elif geom.geom_type == 'MultiLineString':
        coords = []
        for line in geom.geoms:
            coords.extend(list(line.coords))
        return coords
    elif geom.geom_type == 'MultiPoint':
        return [p.coords[0] for p in geom.geoms]
    elif geom.geom_type == 'Polygon':
        return list(geom.exterior.coords)
    elif geom.geom_type == 'MultiPolygon':
        coords = []
        for poly in geom.geoms:
            coords.extend(list(poly.exterior.coords))
        return coords
    elif geom.geom_type == 'GeometryCollection':
        coords = []
        for sub_geom in geom.geoms:
            coords.extend(extract_coords(sub_geom))
        return coords
    return []


def create_city_boundaries(
    input_folder,
    output_file,
    output_format='geojson',
    min_points=3,
    progress_callback=None
):
    """
    Create boundary polygons/LineStrings from multiple GeoJSON files.
    
    Each input file's features are combined using convex hull to create
    a single boundary per file.
    
    Args:
        input_folder: Folder containing input GeoJSON files
        output_file: Path for output file
        output_format: 'geojson' or 'shapefile'
        min_points: Minimum points required to create a boundary
        progress_callback: Optional callback(progress, message)
        
    Returns:
        tuple: (output_file, statistics_dict)
    """
    stats = {
        'input_files': 0,
        'files_processed': 0,
        'files_skipped': 0,
        'boundaries_created': 0,
        'total_points': 0,
        'crs_reprojected': 0,
        'errors': [],
        'warnings': []
    }
    
    try:
        # Find all GeoJSON files
        files = glob.glob(os.path.join(input_folder, "*.geojson"))
        files.extend(glob.glob(os.path.join(input_folder, "*.json")))
        files = list(set(files))  # Remove duplicates
        
        stats['input_files'] = len(files)
        
        if not files:
            raise ValueError(f"No GeoJSON files found in {input_folder}")
        
        print(f"\n{'='*60}")
        print(f"CITY BOUNDARY CREATION")
        print(f"{'='*60}")
        print(f"\nFound {len(files)} GeoJSON files in: {input_folder}")
        
        features = []
        
        for idx, file_path in enumerate(files):
            if progress_callback:
                progress = int((idx / len(files)) * 90) + 5
                progress_callback(progress, f"Processing {os.path.basename(file_path)}...")
            
            city_name = os.path.splitext(os.path.basename(file_path))[0]
            all_coords = []
            
            try:
                with open(file_path, 'r', encoding='utf-8') as f:
                    data = json.load(f)
            except json.JSONDecodeError as e:
                stats['files_skipped'] += 1
                stats['errors'].append(f"{city_name}: Invalid JSON - {str(e)}")
                print(f"  ERROR: {city_name}: Invalid JSON format")
                continue
            except Exception as e:
                stats['files_skipped'] += 1
                stats['errors'].append(f"{city_name}: Error reading file - {str(e)}")
                continue
            
            # Detect CRS per file
            source_epsg = get_epsg_from_geojson(data)
            if source_epsg:
                stats['crs_reprojected'] += 1
                print(f"  {city_name}: detected EPSG:{source_epsg}, will reproject to WGS84")
            else:
                print(f"  {city_name}: using WGS84")
            
            # Extract coordinates from all features
            for feature in data.get('features', []):
                try:
                    geom = shape(feature['geometry'])
                    coords = extract_coords(geom)
                    all_coords.extend(coords)
                except Exception as e:
                    stats['warnings'].append(
                        f"{city_name}: Error extracting geometry - {str(e)}"
                    )
                    continue
            
            if len(all_coords) < min_points:
                stats['files_skipped'] += 1
                stats['warnings'].append(
                    f"{city_name}: Not enough points ({len(all_coords)}), minimum {min_points}"
                )
                print(f"  Skipping {city_name}: not enough points ({len(all_coords)})")
                continue
            
            # Reproject if needed
            if source_epsg:
                try:
                    all_coords = reproject_coords(all_coords, source_epsg)
                except Exception as e:
                    stats['errors'].append(
                        f"{city_name}: Reprojection failed - {str(e)}"
                    )
                    continue
            
            # Create convex hull
            try:
                hull = MultiPoint(all_coords).convex_hull
            except Exception as e:
                stats['errors'].append(
                    f"{city_name}: Convex hull creation failed - {str(e)}"
                )
                continue
            
            # Extract boundary coordinates
            if hull.geom_type == 'Polygon':
                ring_coords = list(hull.exterior.coords)
                geometry_type = 'LineString'
            elif hull.geom_type == 'LineString':
                ring_coords = list(hull.coords)
                geometry_type = 'LineString'
            else:
                # Degenerate case (point)
                ring_coords = [(hull.x, hull.y)]
                geometry_type = 'Point'
            
            # Create feature
            features.append({
                "type": "Feature",
                "properties": {
                    "city": city_name,
                    "point_count": len(all_coords),
                    "source_file": os.path.basename(file_path)
                },
                "geometry": {
                    "type": geometry_type,
                    "coordinates": [[round(c[0], 6), round(c[1], 6)]
                                  for c in ring_coords]
                }
            })
            
            stats['files_processed'] += 1
            stats['boundaries_created'] += 1
            stats['total_points'] += len(all_coords)
            
            print(f"  {city_name}: boundary created from {len(all_coords)} points")
        
        if progress_callback:
            progress_callback(95, "Saving output...")
        
        # Save output
        if output_format == 'geojson':
            output_geojson = {
                "type": "FeatureCollection",
                "features": features
            }
            
            with open(output_file, 'w', encoding='utf-8') as f:
                json.dump(output_geojson, f, indent=2)
        
        elif output_format == 'shapefile':
            if features:
                gdf = gpd.GeoDataFrame.from_features(features, crs="EPSG:4326")
                gdf.to_file(output_file)
        
        stats['output_file'] = output_file
        
        if progress_callback:
            progress_callback(100, "Complete!")
        
        # Summary
        print(f"\n{'='*60}")
        print(f"BOUNDARY CREATION COMPLETE")
        print(f"{'='*60}")
        print(f"  Input files: {stats['input_files']}")
        print(f"  Processed: {stats['files_processed']}")
        print(f"  Skipped: {stats['files_skipped']}")
        print(f"  Boundaries created: {stats['boundaries_created']}")
        print(f"  Total points: {stats['total_points']}")
        print(f"  CRS reprojections: {stats['crs_reprojected']}")
        print(f"  Output: {output_file}")
        
        return output_file, stats
    
    except Exception as e:
        stats['errors'].append(str(e))
        print(f"\nERROR: {str(e)}")
        raise


if __name__ == "__main__":
    import argparse
    
    parser = argparse.ArgumentParser(description="Create city boundaries from GeoJSON files")
    parser.add_argument("input_folder", help="Folder containing input GeoJSON files")
    parser.add_argument("output", help="Output file path")
    parser.add_argument("--format", choices=['geojson', 'shapefile'],
                       default='geojson', help="Output format")
    parser.add_argument("--min-points", type=int, default=3,
                       help="Minimum points required per city")
    
    args = parser.parse_args()
    
    output, stats = create_city_boundaries(
        input_folder=args.input_folder,
        output_file=args.output,
        output_format=args.format,
        min_points=args.min_points,
        progress_callback=lambda p, m: print(f"  [{p}%] {m}")
    )
    
    print(f"\nSuccess! Output saved to: {output}")