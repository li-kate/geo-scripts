import pandas as pd
import gpxpy
import os
from preprocess_files.base import standardize_columns, parse_datetime
from pipeline.config import column_map
from conversions.convert_csv_to_gpx import convert_csv_to_gpx
from preprocess_files.map_matching.map_matching import prefilter_points, snap_to_route

def load_gps(file, skip_rows=4, gps_accuracy=13, return_line=False, sensor_times=None, mode = "Walking"):
    """
    Load GPS data, standardize, parse datetime, Pre-filter, and Snap
    
    Parameters:
    -----------
    file : str
        Path to GPS file (CSV or GPX)
    skip_rows : int, optional (default=4)
        Number of rows to skip when reading CSV files
    gps_accuracy : int, optional (default=13)
        GPS accuracy parameter for map matching
    return_line : bool, optional (default=False)
        Whether to return the route geometry
    sensor_times : list or pandas.Series, optional
        Additional timestamps from Kestrel/PurpleAir to add points for
    """
    ext = file.split(".")[-1].lower()
    
    # Validate gps_accuracy parameter
    if not isinstance(gps_accuracy, (int, float)) or gps_accuracy <= 0:
        print(f"WARNING: Invalid gps_accuracy value {gps_accuracy}. Using default 9.")
        gps_accuracy = 9
    
    if ext == "csv":
        df = pd.read_csv(file, skiprows=skip_rows)
        df = standardize_columns(df, column_map)
        if "dategmt" in df.columns:
            df["utc_date_time"] = pd.to_datetime(df["dategmt"], errors="coerce", utc=True)
        else:
            df = parse_datetime(df, "utc_date_time")
        file = convert_csv_to_gpx(file, file.replace(".csv", ".gpx"))
    
    elif ext == "gpx":
        with open(file, "r") as f:
            gpx = gpxpy.parse(f)

        rows = []
        for track in gpx.tracks:
            for segment in track.segments:
                for point in segment.points:
                    rows.append({
                        "utc_date_time": point.time,
                        "latitude": point.latitude,
                        "longitude": point.longitude,
                        "accuracy": getattr(point, 'horizontal_dilution', 0)
                    })
        df = pd.DataFrame(rows)
        df = standardize_columns(df, column_map)
        df["utc_date_time"] = pd.to_datetime(df["utc_date_time"], errors="coerce", utc=True)
    
    else:
        raise ValueError(f"Unsupported GPS file type: {ext}")

    # --- 1. PRE-FILTERING ---
    print(f"Points before filtering: {len(df)}")
    df_clean = prefilter_points(df, mode)
    print(f"Points after filtering: {len(df_clean)}")

    gh_profile = "bike" if mode == "Biking" else "foot"

    # --- 2. SNAP TO ROUTE (with sensor timestamps) ---
    gdf_snapped, route_geom = snap_to_route(
        file, 
        points_df=df_clean, 
        gps_accuracy=gps_accuracy, 
        return_line=return_line,
        sensor_times=sensor_times,
        profile = gh_profile
    )


    return gdf_snapped, route_geom, df_clean