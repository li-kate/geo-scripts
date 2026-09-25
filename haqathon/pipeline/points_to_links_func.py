import geojson
import pandas as pd
from shapely import wkt
from shapely.geometry import mapping
from shapely.geometry import Point, LineString, Polygon
from shapely.ops import substring
import geojson

def convert_points_to_links(df, edge_id_col="gh_edge_id"):
    """
    Groups data by GraphHopper edge ID and uses the full edge geometry.
    The full edge geometry is already stored in the 'edge_geometry' column.
    """
    if df.empty:
        return geojson.FeatureCollection([])

    # Make a copy to avoid modifying original
    df = df.copy()
    
    # Convert WKT strings to shapely geometries if needed
    if 'edge_geometry' in df.columns:
        # First, handle NaN/None values
        df['edge_geometry'] = df['edge_geometry'].fillna('').astype(str)
        
        # Only attempt to load WKT for non-empty strings
        mask = df['edge_geometry'].str.strip() != ''
        df.loc[mask, 'edge_geometry'] = df.loc[mask, 'edge_geometry'].apply(wkt.loads)
        
        # For empty strings, set to None
        df.loc[~mask, 'edge_geometry'] = None

    features = []
    
    # Define sensor columns to average
    agg_cols = [
        "pm2_5_cf_1", "pm10_0_cf_1", "pm2_5_atm", "pm10_0_atm",
        "temperature", "relative_humidity", "calculated_heat_index",
        "wind_speed"
    ]
    actual_agg_cols = [c for c in agg_cols if c in df.columns]

    # Group by edge ID - each group represents one full road edge
    for edge_id, group in df.groupby(edge_id_col):
        if group.empty:
            continue
            
        # Skip if edge_id is None or NaN
        if pd.isna(edge_id) or edge_id == '':
            continue
            
        # Get the full edge geometry (all points in the group share the same geometry)
        edge_geom = group['edge_geometry'].iloc[0]
        
        # Skip if geometry is None or not a valid geometry
        if edge_geom is None:
            continue
            
        # If geometry is still a string (WKT), convert it
        if isinstance(edge_geom, str) and edge_geom.strip():
            try:
                edge_geom = wkt.loads(edge_geom)
            except:
                continue
        elif not hasattr(edge_geom, '__geo_interface__') and not isinstance(edge_geom, (Point, LineString, Polygon)):
            # Not a valid geometry object
            continue
        
        # Calculate means for sensor data from points on this edge
        mean_vals = group[actual_agg_cols].mean(numeric_only=True)
        props = {k: round(float(v), 2) for k, v in mean_vals.items() if pd.notna(v)}
        
        # Add identifiers - ensure they're not NaN
        gh_edge_id_val = int(edge_id) if edge_id is not None and not pd.isna(edge_id) else None
        
        osm_id_val = None
        if 'osm_way_id' in group.columns:
            osm_val = group['osm_way_id'].iloc[0]
            if pd.notna(osm_val):
                osm_id_val = int(osm_val)
        
        props.update({
            "gh_edge_id": gh_edge_id_val,
            "osm_way_id": osm_id_val,
            "sample_count": len(group)
        })
        
        features.append(
            geojson.Feature(
                geometry=mapping(edge_geom),  # Use the full edge geometry
                properties=props
            )
        )

    return geojson.FeatureCollection(features)

# def load_osm_graph(graph_path="graphhopper/georgia-251106.osm"):
#     """
#     Safely load OSM graph from file, ignoring broken relations that crash OSMnx.
    
#     Args:
#         graph_path: Path to OSM file (.osm)
    
#     Returns:
#         GeoDataFrame with OSM ways and their geometries
#     """
#     try:
#         if not os.path.exists(graph_path):
#             raise FileNotFoundError(f"Graph file not found: {graph_path}")
        
#         print(f"Safely loading OSM data from {graph_path} (Bypassing OSMnx parser)...")
        
#         nodes = {}
#         ways = []
        
#         # iterparse efficiently reads large XML files without loading the whole thing into memory
#         context = ET.iterparse(graph_path, events=('end',))
        
#         for event, elem in context:
#             if elem.tag == 'node':
#                 # Store node coordinates
#                 nodes[int(elem.attrib['id'])] = (float(elem.attrib['lon']), float(elem.attrib['lat']))
#                 elem.clear() # Clear from memory
                
#             elif elem.tag == 'way':
#                 way_id = int(elem.attrib['id'])
                
#                 # Find all node references in this way
#                 nd_refs = [int(nd.attrib['ref']) for nd in elem.findall('nd')]
                
#                 # Retrieve coordinates for the nodes we have
#                 coords = [nodes[n] for n in nd_refs if n in nodes]
                
#                 # Only create a LineString if we have at least 2 valid coordinates
#                 if len(coords) >= 2:
#                     ways.append({
#                         'osmid': way_id,
#                         'geometry': LineString(coords)
#                     })
#                 elem.clear() # Clear from memory
                
#             elif elem.tag == 'relation':
#                 # We purposefully ignore relations to prevent the 33160608 error
#                 elem.clear()
                
#         if not ways:
#             print("Warning: No valid ways found in the OSM file.")
#             return None
            
#         # Convert our clean dictionary list into the GeoDataFrame your script expects
#         gdf = gpd.GeoDataFrame(ways)
#         print(f"Successfully loaded {len(gdf)} road geometries from OSM file")
#         return gdf
        
#     except Exception as e:
#         print(f"Error loading OSM graph: {e}")
#         return None


# def build_osm_geometry_lookup(osm_gdf):
#     """
#     Build efficient lookup dictionary for OSM IDs to geometries.
    
#     Args:
#         osm_gdf: GeoDataFrame with OSM ways
    
#     Returns:
#         Dictionary mapping OSM ID to geometry
#     """
#     osm_to_geom = {}
    
#     for idx, row in osm_gdf.iterrows():
#         osm_id = row['osmid']
#         geometry = row['geometry']
        
#         # Handle different OSM ID formats (could be int, str, or list)
#         if isinstance(osm_id, list):
#             for oid in osm_id:
#                 try:
#                     osm_to_geom[int(oid)] = geometry
#                 except (ValueError, TypeError):
#                     continue
#         else:
#             try:
#                 osm_to_geom[int(osm_id)] = geometry
#             except (ValueError, TypeError):
#                 continue
    
#     print(f"Built lookup with {len(osm_to_geom)} unique OSM IDs")
#     return osm_to_geom


# def convert_points_to_links(df, 
#                                     osm_file_path="graphhopper/georgia-251106.osm",
#                                     edge_id_col="gh_edge_id", 
#                                     osm_id_col="osm_way_id"):
#     """
#     Convert map-matched points to LineStrings grouped by GraphHopper edge ID.
#     Uses OSM IDs to get actual road geometries from local OSM file.
#     Creates ONE LineString per GraphHopper ID, aggregating all points with that ID.
    
#     Args:
#         df: DataFrame with points from map-matching
#         osm_file_path: Path to local OSM file (.osm or .pbf)
#         edge_id_col: Column name containing GraphHopper edge IDs
#         osm_id_col: Column name containing OSM way IDs
    
#     Returns:
#         GeoJSON FeatureCollection with one LineString per GraphHopper edge
#     """
    
#     # =========================================================================
#     # 1. VALIDATION AND PREPARATION
#     # =========================================================================
    
#     # Check if input is empty
#     if df.empty:
#         print("Warning: Input DataFrame is empty")
#         return geojson.FeatureCollection([])
    
#     # Filter out rows with missing critical data
#     df = df.dropna(subset=[edge_id_col, osm_id_col]).copy()
#     if df.empty:
#         print("Warning: No rows with valid edge_id and osm_id")
#         return geojson.FeatureCollection([])
    
#     # Convert to proper types
#     df[edge_id_col] = df[edge_id_col].astype(int)
    
#     # Handle OSM IDs (could be int, string, or comma-separated string)
#     def parse_osm_ids(osm_val):
#         """Parse OSM ID(s) from various formats."""
#         if pd.isna(osm_val):
#             return []
#         if isinstance(osm_val, (int, float)):
#             return [int(osm_val)]
#         if isinstance(osm_val, str):
#             if ',' in osm_val:
#                 # Handle comma-separated IDs (e.g., "12345,67890")
#                 return [int(id.strip()) for id in osm_val.split(',') if id.strip().isdigit()]
#             elif osm_val.isdigit():
#                 return [int(osm_val)]
#         return []
    
#     # Apply parsing to create a list of OSM IDs per row
#     df['parsed_osm_ids'] = df[osm_id_col].apply(parse_osm_ids)
    
#     # Explode so each OSM ID gets its own row (for lookup purposes)
#     df_exploded = df.explode('parsed_osm_ids').dropna(subset=['parsed_osm_ids'])
#     df_exploded['parsed_osm_ids'] = df_exploded['parsed_osm_ids'].astype(int)
    
#     # =========================================================================
#     # 2. LOAD OSM DATA AND BUILD LOOKUP
#     # =========================================================================
    
#     # Load OSM graph
#     osm_gdf = load_osm_graph(osm_file_path)
#     if osm_gdf is None:
#         print("Error: Could not load OSM graph")
#         return geojson.FeatureCollection([])
    
#     # Build efficient lookup
#     osm_to_geom = build_osm_geometry_lookup(osm_gdf)
    
#     # =========================================================================
#     # 3. VERIFY WHICH OSM IDs ARE FOUND
#     # =========================================================================
    
#     unique_osm_ids = set(df_exploded['parsed_osm_ids'].unique())
#     found_osm_ids = unique_osm_ids & set(osm_to_geom.keys())
#     missing_osm_ids = unique_osm_ids - set(osm_to_geom.keys())
    
#     print(f"OSM ID coverage: {len(found_osm_ids)}/{len(unique_osm_ids)} found in graph")
#     if missing_osm_ids:
#         print(f"Warning: {len(missing_osm_ids)} OSM IDs not found in graph")
#         print(f"Sample missing IDs: {list(missing_osm_ids)[:5]}")
    
#     # =========================================================================
#     # 4. DEFINE COLUMNS TO AGGREGATE
#     # =========================================================================
    
#     agg_cols = [
#         "pm2_5_cf_1", "pm10_0_cf_1", "pm2_5_atm", "pm10_0_atm",
#         "temperature", "relative_humidity", "calculated_heat_index",
#         "wet_bulb_temp", "wind_speed"
#     ]
#     actual_agg_cols = [c for c in agg_cols if c in df.columns]
    
#     # =========================================================================
#     # 5. GROUP BY GRAPHHOPPER EDGE ID (ONE FEATURE PER ID)
#     # =========================================================================
    
#     features = []
#     # edges_processed = 0
#     # edges_skipped = 0
    
#     # Group by GraphHopper edge ID only - this is the key change
#     # We want ONE feature per ID regardless of continuity
#     for gh_id, group in df.groupby(edge_id_col):
#             # Identify which OSM Way(s) this segment belongs to
#             # We handle potential strings or floats by converting to int
#             try:
#                 raw_osm_id = group[osm_id_col].iloc[0]
#                 if isinstance(raw_osm_id, str) and ',' in raw_osm_id:
#                     osm_ids = [int(x.strip()) for x in raw_osm_id.split(',') if x.strip().isdigit()]
#                 else:
#                     osm_ids = [int(float(raw_osm_id))]
#             except (ValueError, TypeError):
#                 continue

#             # Find the geometry in our lookup
#             valid_geoms = [osm_to_geom[oid] for oid in osm_ids if oid in osm_to_geom]
            
#             if not valid_geoms:
#                 continue # This didn't happen in your last run!
                
#             # 2. Assign geometry
#             if len(valid_geoms) == 1:
#                 full_road_geom = valid_geoms[0]
#             else:
#                 full_road_geom = linemerge(valid_geoms)

#             # 1. Extract GPS coordinates from the group
#             # Ensure they are in (Lon, Lat) to match OSM
#             points = [Point(xy) for xy in zip(group['longitude'], group['latitude'])]
            
#             # 2. Project points onto the road to find their relative positions (0.0 to 1.0)
#             # We find the min and max "distance" along the line where our points sit
#             distances = [full_road_geom.project(p, normalized=True) for p in points]
#             min_dist = min(distances)
#             max_dist = max(distances)

#             # 3. Cut the line. If points are too close, we keep a tiny segment to avoid errors
#             if min_dist == max_dist:
#                 # If only 1 point exists, create a tiny 1-meter segment on the road 
#                 # so it remains a LineString, not a Polygon/Circle.
#                 # 0.00001 is roughly 1 meter in normalized distance for most city blocks
#                 start = max(0, min_dist - 0.00001)
#                 end = min(1, max_dist + 0.00001)
#                 final_geom = substring(full_road_geom, start, end, normalized=True)
#             else:
#                 final_geom = substring(full_road_geom, min_dist, max_dist, normalized=True)

#             # 3. Build properties (ADD THE FLAG HERE)
#             mean_vals = group[actual_agg_cols].mean(numeric_only=True)
#             props = {k: round(float(v), 2) if pd.notna(v) else None for k, v in mean_vals.items()}
            
#             props.update({
#                 "gh_edge_id": int(gh_id),
#                 "osm_way_id": osm_ids[0] if len(osm_ids) == 1 else osm_ids,
#                 "point_count": len(group),
#                 "has_road_geometry": True  # <--- ADD THIS LINE
#             })
            
#             features.append(
#                 geojson.Feature(
#                     geometry=mapping(final_geom),
#                     properties=props
#                 )
#             )
    
#     # =========================================================================
#     # 7. RETURN FINAL FEATURE COLLECTION
#     # =========================================================================
    
#     print(f"\nSummary:")
#     print(f"  Total unique GraphHopper edges: {df[edge_id_col].nunique()}")
#     print(f"  Features created: {len(features)}")
#     print(f"  Using OSM road geometries: {sum(1 for f in features if f.properties.get('has_road_geometry', False))}")
#     print(f"  Using GPS fallback: {sum(1 for f in features if not f.properties.get('has_road_geometry', False))}")
    
#     return geojson.FeatureCollection(features)