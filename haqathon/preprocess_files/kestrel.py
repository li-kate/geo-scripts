import pandas as pd
import math
from preprocess_files.base import standardize_columns, parse_datetime, enforce_thresholds
from pipeline.config import column_map, columns_to_keep, thresholds

def load_kestrel(file_path, skip_rows=None, gps_start_time=None):
    """
    Load Kestrel CSV, standardize columns, parse datetime, convert temperature units if needed,
    calculate heat index, enforce thresholds, and keep relevant columns.
    """
    if skip_rows is None:
        skip_rows = [0, 1, 2, 4]

    # --- Load CSV ---
    df = pd.read_csv(file_path, skiprows=skip_rows)

    # --- Standardize columns ---
    df = standardize_columns(df, column_map)

    # --- Convert Fahrenheit → Celsius if needed ---
    convert_temperature_columns(df)

    # --- Parse datetime to UTC ---
    df = parse_datetime(df, "utc_date_time", local_tz="America/New_York")

    # --- Validate heat index ---
    check_heat_index(df)

    # --- Enforce thresholds ---
    df = enforce_temperature_thresholds(df)

    # --- Keep relevant columns ---
    keep_cols = [c for c in columns_to_keep["kestrel"] if c in df.columns]
    return df[keep_cols]


# ------------------- Helper functions -------------------
def convert_temperature_columns(df):
    """Convert temperature-related columns from °F to °C if values look like Fahrenheit."""
    for col in ["temperature", "wet_bulb_temp", "heat_index"]:
        if col in df.columns and df[col].max() > 60:
            df[col] = (df[col] - 32) * 5/9
            # print(f"[INFO] Converted '{col}' from °F to °C")

def calculate_heat_index(temp_c, rh):
    """
    Calculate heat index (°C) from temperature (°C) and relative humidity (%)
    using NOAA/NWS Rothfusz regression with adjustments.
    """
    # Convert to Fahrenheit for calculations
    T = temp_c * 9/5 + 32
    R = rh

    # Step 1: Simple formula
    simple = 0.5 * (T + 61.0 + ((T - 68.0) * 1.2) + (R * 0.094))
    avg_simple = (simple + T) / 2.0

    # If simple estimate < 80°F, use it (converted back to °C)
    if avg_simple < 80:
        return (avg_simple - 32) * 5/9

    # Step 2: Rothfusz regression
    HI = (
        -42.379 + 2.04901523*T + 10.14333127*R
        - 0.22475541*T*R - 0.00683783*T**2
        - 0.05481717*R**2 + 0.00122874*T**2*R
        + 0.00085282*T*R**2 - 0.00000199*T**2*R**2
    )

    # Step 3: Adjustments
    if R < 13 and 80 <= T <= 112:
        adj = ((13 - R) / 4) * math.sqrt((17 - abs(T - 95)) / 17)
        HI -= adj
    elif R > 85 and 80 <= T <= 87:
        adj = ((R - 85) / 10) * ((87 - T) / 5)
        HI += adj

    # Convert back to Celsius
    return (HI - 32) * 5/9

def check_heat_index(df):
    """Calculate and compare heat index, warn if mismatch."""
    if {"temperature", "relative_humidity"}.issubset(df.columns):
        df["calculated_heat_index"] = df.apply(
            lambda row: calculate_heat_index(row["temperature"], row["relative_humidity"]),
            axis=1
        )
        if "heat_index" in df.columns:
            df["heat_index_diff"] = df["heat_index"] - df["calculated_heat_index"]
            bad_rows = df[df["heat_index_diff"].abs() > thresholds.get("heat_index_diff", 4)]
            if not bad_rows.empty:
                print(f"[WARN] 'heat_index' mismatch in rows: {list(bad_rows.index)}")
                print(bad_rows[["utc_date_time", "heat_index", "calculated_heat_index", "heat_index_diff"]])

def enforce_temperature_thresholds(df: pd.DataFrame) -> pd.DataFrame:
    """Drop rows with out-of-range temperature and warn about what was removed."""
    if "temperature" not in df.columns:
        return df
    df_clean, invalid_temp = enforce_thresholds(
        df,
        "temperature",
        min_val=thresholds["temperature_min"],
        max_val=thresholds["temperature_max"],
    )
    if not invalid_temp.empty:
        print(f"[WARN] {len(invalid_temp)} rows with out-of-range temperature dropped")
        print(invalid_temp[["utc_date_time", "temperature"]])
    return df_clean
