import pandas as pd
import numpy as np
import requests
import geopandas as gpd
from shapely.geometry import Point, LineString
from geopy.distance import geodesic
from polyline import decode
import gpxpy.gpx
from .kalman_filter import KalmanFilter


def prefilter_points(df, mode = "Walking"):
    """
    1. Sorts by time.
    2. Drops high-accuracy-error points.
    3. Smooths trajectory using 4D State-Space Kalman Filter.
    4. Applies Physics Gating.
    """
    if df.empty: return df
    
    # --- Step 0: Standardize ---
    df = df.sort_values("utc_date_time").reset_index(drop=True)
    print(f"DEBUG: Points after standardize: {len(df)}")

    # --- Step 1: Quality Gating ---
    if 'accuracy' in df.columns:
        df['accuracy'] = pd.to_numeric(df['accuracy'], errors='coerce').fillna(20)
        df = df[df['accuracy'] <= 50].copy()
        print(f"DEBUG: Points after accuracy gate: {len(df)}")
    
    if df.empty: return df

    # --- Step 2: Physics Gating ---
    clean_rows = []
    last_valid = None
    MAX_SPEED_MPS = 15.0 if mode == "Biking" else 4.0 # meters per second (33.6 mph for biking, 8.9 mph for walking)
    
    for i, row in df.iterrows():
        if last_valid is None:
            clean_rows.append(row)
            last_valid = row
            continue
        
        p1 = (last_valid['latitude'], last_valid['longitude'])
        p2 = (row['latitude'], row['longitude'])
        
        dist = geodesic(p1, p2).meters
        time_delta = (row['utc_date_time'] - last_valid['utc_date_time']).total_seconds()
        
        if time_delta <= 0: continue 
        
        speed = dist / time_delta
        
        if speed > MAX_SPEED_MPS: continue
        # if dist < MIN_DIST_DELTA: continue

        clean_rows.append(row)
        last_valid = row
    print(f"DEBUG: Points after physics gating: {len(clean_rows)}")

    df_gated = pd.DataFrame(clean_rows).reset_index(drop=True)
    if df_gated.empty: return df_gated

    # --- Step 3: Advanced Kalman Smoothing ---
    # forward_step() initialises itself on the first call (when self.x is None).
    # Do not pre-set kf.x here — doing so causes the first point to be fed
    # twice, producing an N+1 history for N points and an off-by-one in the
    # smoothed output.
    kf = KalmanFilter(process_noise_std=1e-6, measurement_noise_std=1e-4)
    prev_time = df_gated.iloc[0]['utc_date_time']

    for i, row in df_gated.iterrows():
        curr_time = row['utc_date_time']
        dt = (curr_time - prev_time).total_seconds()

        # Guard against zero/negative dt (duplicate timestamps, clock issues)
        if dt <= 0:
            dt = 0.01

        kf.forward_step([row['latitude'], row['longitude']], dt=dt)
        prev_time = curr_time

    smoothed_states, _ = kf.rts_smooth()
    
    print(f"DEBUG: Points after Kalman: {len(smoothed_states)}")
    
    df_gated['latitude'] = [state[0] for state in smoothed_states]
    df_gated['longitude'] = [state[1] for state in smoothed_states]

    return df_gated

def _find_edge(point_dist, cumulative_distances, edge_details, osm_details):
    """
    Return (edge_id_str, osm_way_id) for the route point at `point_dist`.

    `cumulative_distances` is a list of distances along the matched route in
    metres (one entry per route coordinate).  `edge_details` and `osm_details`
    are the [start_idx, end_idx, id] triplets returned by GraphHopper.
    """
    point_idx = min(
        range(len(cumulative_distances)),
        key=lambda k: abs(cumulative_distances[k] - point_dist),
    )
    for start, end, e_id in edge_details:
        if start <= point_idx < end:
            found_osm = next(
                (way_id for s, e, way_id in osm_details if s <= point_idx < e),
                None,
            )
            return str(e_id), found_osm
    return None, None


def normalize_linestring(coords):
    if len(coords) < 2:
        return coords
    return coords if coords[0] < coords[-1] else list(reversed(coords))


def snap_to_route(input_path, points_df=None, match_url="http://localhost:8989/match",
                  gps_accuracy=13, return_line=False, sensor_times=None, profile="foot"):
    """
    Snaps GPS points to GraphHopper and adds points at sensor timestamps.
    
    Parameters:
    -----------
    input_path : str
        Path to input GPX file
    points_df : pandas.DataFrame, optional
        DataFrame containing cleaned GPS points
    match_url : str
        URL of GraphHopper map matching service
    gps_accuracy : int
        GPS accuracy parameter
    return_line : bool
        Whether to return the route geometry
    sensor_times : list or pandas.Series, optional
        Additional timestamps from Kestrel/PurpleAir to add points for
    """
    HEADERS = {"Content-Type": "application/gpx+xml"}
    all_records = []
    full_route_geom = None  # set inside the loop; guarded before use at the end

    if not isinstance(gps_accuracy, (int, float)) or gps_accuracy <= 0:
        print(f"WARNING: Invalid gps_accuracy value {gps_accuracy}. Using default 13.")
        gps_accuracy = 13

    # Build orig_data list from the pre-cleaned DataFrame when available.
    # GPS timestamps are already UTC-aware from load_gps, so comparisons with
    # sensor_times (also UTC-aware) are safe.
    if points_df is not None:
        orig_data = [
            {
                "time": row['utc_date_time'],
                "raw_lat": row['latitude'],
                "raw_lon": row['longitude'],
                "raw_geom": Point(row['longitude'], row['latitude']),
            }
            for _, row in points_df.iterrows()
        ]
        tracks_data = [orig_data]
    else:
        # Fallback: read GPX file directly (used only when points_df is None)
        with open(input_path, "r") as f:
            gpx = gpxpy.parse(f)
        tracks_data = []
        for track in gpx.tracks:
            for segment in track.segments:
                seg_data = [
                    {
                        "time": p.time,
                        "raw_lat": p.latitude,
                        "raw_lon": p.longitude,
                        "raw_geom": Point(p.longitude, p.latitude),
                    }
                    for p in segment.points
                    if p.time
                ]
                tracks_data.append(seg_data)

    # --- DO THE MAP-MATCHING FIRST ---
    for orig_data in tracks_data:
        if not orig_data: continue

        # Create GPX for map-matching
        gpx_to_snap = gpxpy.gpx.GPX()
        tr = gpxpy.gpx.GPXTrack()
        seg_snap = gpxpy.gpx.GPXTrackSegment()
        gpx_to_snap.tracks.append(tr)
        tr.segments.append(seg_snap)

        for d in orig_data:
            seg_snap.points.append(gpxpy.gpx.GPXTrackPoint(d['raw_lat'], d['raw_lon']))

        # Call GraphHopper
        params = {
            "type": "json",
            "points_encoded": "false",
            "profile": profile,
            "details": ["osm_way_id", "edge_id"],
            "gps_accuracy": gps_accuracy,
            "max_visited_nodes": 5000,
        }

        try:
            resp = requests.post(
                f"{match_url}",
                params=params,
                data=gpx_to_snap.to_xml().encode("utf-8"),
                headers=HEADERS,
                timeout=60
            )
            resp.raise_for_status()
            result = resp.json()
            path = result["paths"][0]
        except Exception as e:
            print(f"GraphHopper matching failed: {e}")
            continue

        # Get the matched route geometry
        points_data = path.get("points")
        if isinstance(points_data, dict) and "coordinates" in points_data:
            line_coords = [(p[0], p[1]) for p in points_data["coordinates"]]
        else:
            decoded = decode(points_data, precision=5)
            line_coords = [(lon, lat) for lat, lon in decoded]

        full_route_geom = LineString(line_coords)

        edge_details = path.get("details", {}).get("edge_id", [])
        osm_details = path.get("details", {}).get("osm_way_id", [])

        # Build edge geometry lookup (keyed by str(edge_id))
        edge_geometry_lookup = {
            str(edge_id): LineString(line_coords[start_idx:end_idx + 1])
            for start_idx, end_idx, edge_id in edge_details
        }

        # Derive the UTM zone from the route's own coordinates so this works
        # anywhere in the world, not just Atlanta.  estimate_utm_crs() picks
        # the correct zone from the geometry's centroid.
        route_gs = gpd.GeoSeries([full_route_geom], crs="EPSG:4326")
        local_utm = route_gs.estimate_utm_crs()
        route_gdf_metric = gpd.GeoDataFrame(geometry=route_gs).to_crs(local_utm)
        full_route_geom_metric = route_gdf_metric.geometry.iloc[0]

        cumulative_distances = [0.0]
        metric_coords = list(full_route_geom_metric.coords)
        for idx in range(1, len(metric_coords)):
            p1 = Point(metric_coords[idx - 1])
            p2 = Point(metric_coords[idx])
            cumulative_distances.append(cumulative_distances[-1] + p1.distance(p2))

        # --- PROCESS ORIGINAL GPS POINTS ---
        for item in orig_data:
            # Project in metric CRS so .project() returns metres, matching
            # cumulative_distances units.
            raw_geom_metric = (
                gpd.GeoSeries([item['raw_geom']], crs="EPSG:4326")
                .to_crs(local_utm)
                .iloc[0]
            )
            projected_dist = full_route_geom_metric.project(raw_geom_metric)
            snapped_point_metric = full_route_geom_metric.interpolate(projected_dist)
            # Convert snapped point back to WGS84 for output
            snapped_point = (
                gpd.GeoSeries([snapped_point_metric], crs=local_utm)
                .to_crs("EPSG:4326")
                .iloc[0]
            )

            found_edge_id, found_osm_id = _find_edge(
                projected_dist, cumulative_distances, edge_details, osm_details
            )
            edge_geom = edge_geometry_lookup.get(found_edge_id) if found_edge_id else None

            all_records.append({
                "utc_date_time": item['time'],
                "latitude": snapped_point.y,
                "longitude": snapped_point.x,
                "osm_way_id": found_osm_id,
                "gh_edge_id": found_edge_id,
                "geometry": snapped_point,
                "edge_geometry": edge_geom.wkt if edge_geom else None,
                "point_type": "gps_original",
                "data_source": "gps",
            })

        # --- ADD POINTS AT SENSOR TIMESTAMPS ---
        if sensor_times is not None and len(sensor_times) > 0:
            segment_start_time = orig_data[0]['time']
            segment_end_time = orig_data[-1]['time']
            segment_sensor_times = [
                t for t in sensor_times
                if segment_start_time <= t <= segment_end_time
            ]

            for sensor_time in segment_sensor_times:
                # Skip if within 1 ms of an existing GPS point (avoid duplicates)
                if any(
                    abs((item['time'] - sensor_time).total_seconds()) < 0.001
                    for item in orig_data
                ):
                    continue

                # Find the two GPS points that bracket this sensor timestamp
                prev_gps = None
                next_gps = None
                for k in range(len(orig_data) - 1):
                    if orig_data[k]['time'] <= sensor_time <= orig_data[k + 1]['time']:
                        prev_gps = orig_data[k]
                        next_gps = orig_data[k + 1]
                        break

                if prev_gps is None or next_gps is None:
                    continue

                # Linear interpolation along the route by time fraction.
                # Assumes constant speed between consecutive GPS samples, which
                # is a reasonable approximation at 1–5 s GPS sampling rates.
                time_diff_total = (next_gps['time'] - prev_gps['time']).total_seconds()
                time_diff_to_sensor = (sensor_time - prev_gps['time']).total_seconds()
                time_fraction = time_diff_to_sensor / time_diff_total if time_diff_total > 0 else 0

                prev_geom_metric = (
                    gpd.GeoSeries([prev_gps['raw_geom']], crs="EPSG:4326")
                    .to_crs(local_utm)
                    .iloc[0]
                )
                next_geom_metric = (
                    gpd.GeoSeries([next_gps['raw_geom']], crs="EPSG:4326")
                    .to_crs(local_utm)
                    .iloc[0]
                )
                prev_dist = full_route_geom_metric.project(prev_geom_metric)
                next_dist = full_route_geom_metric.project(next_geom_metric)
                sensor_dist = prev_dist + time_fraction * (next_dist - prev_dist)

                sensor_point_metric = full_route_geom_metric.interpolate(sensor_dist)
                sensor_point = (
                    gpd.GeoSeries([sensor_point_metric], crs=local_utm)
                    .to_crs("EPSG:4326")
                    .iloc[0]
                )

                found_edge_id, found_osm_id = _find_edge(
                    sensor_dist, cumulative_distances, edge_details, osm_details
                )
                edge_geom = edge_geometry_lookup.get(found_edge_id) if found_edge_id else None

                all_records.append({
                    "utc_date_time": sensor_time,
                    "latitude": sensor_point.y,
                    "longitude": sensor_point.x,
                    "osm_way_id": found_osm_id,
                    "gh_edge_id": found_edge_id,
                    "geometry": sensor_point,
                    "edge_geometry": edge_geom.wkt if edge_geom else None,
                    "point_type": "interpolated",
                    "data_source": "sensor_timestamp",
                })

    gdf = pd.DataFrame(all_records)

    if gdf.empty:
        return (
            gpd.GeoDataFrame(
                columns=["utc_date_time", "latitude", "longitude", "osm_way_id", "geometry"],
                crs="EPSG:4326",
            ),
            None,
        )

    gdf["utc_date_time"] = pd.to_datetime(gdf["utc_date_time"], utc=True, errors="coerce")
    gdf = gdf.sort_values("utc_date_time").reset_index(drop=True)
    gdf["is_original_gps"] = gdf["point_type"] == "gps_original"
    gdf = gpd.GeoDataFrame(gdf, geometry="geometry", crs="EPSG:4326")

    route_gdf = (
        gpd.GeoDataFrame({"id": [1]}, geometry=[full_route_geom], crs="EPSG:4326")
        if full_route_geom is not None
        else None
    )
    return gdf, route_gdf