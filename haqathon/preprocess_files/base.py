import pandas as pd
from pipeline.config import EXPECTED_YEAR


def standardize_columns(df, column_map):
    """
    Lowercase, remove spaces/special chars, and apply column renaming map.
    """
    df.columns = (
        df.columns
        .str.strip()
        .str.lower()
        .str.replace(" ", "_")
        .str.replace(r"[^\w]", "", regex=True)
    )
    return df.rename(columns={col: column_map[col] for col in df.columns if col in column_map})


def enforce_thresholds(df, col, min_val=None, max_val=None):
    if col not in df:
        return df, pd.DataFrame()

    mask = pd.Series(True, index=df.index)
    if min_val is not None:
        mask &= df[col] >= min_val
    if max_val is not None:
        mask &= df[col] <= max_val

    return df.loc[mask], df.loc[~mask]

def parse_datetime(df, col, local_tz=None, gps_start_time=None):
    if col not in df.columns:
        return df

    raw_values = df[col].copy()
    cleaned = df[col].astype(str).str.strip()

    # Only replace Korean AM/PM if present
    if cleaned.str.contains("오전|오후").any():
        cleaned = cleaned.str.replace("오전", "AM", regex=False)
        cleaned = cleaned.str.replace("오후", "PM", regex=False)

    # Optionally remove trailing non-date characters
    cleaned = cleaned.str.extract(r"([\d/\- :APMapmTzZ]+)")[0]

    parsed = pd.to_datetime(cleaned, errors="coerce")

    wrong_year_mask = parsed.dt.year != EXPECTED_YEAR
    if wrong_year_mask.any():
        print("[DEBUG] Detected wrong year in some timestamps.")
        print("GPS START TIME:", gps_start_time)
        if gps_start_time is not None:
            first_valid_idx = parsed.first_valid_index()
            print("[DEBUG] First valid timestamp index:", first_valid_idx)
            if first_valid_idx is not None:
                # Make both tz-naive for arithmetic
                gps_naive = gps_start_time.tz_localize(None) if gps_start_time.tzinfo else gps_start_time
                parsed_ts = parsed.loc[first_valid_idx]
                offset = gps_naive - parsed_ts
                print(f"[DEBUG] Applying offset: {offset}")
                parsed = parsed + offset
        else:
            parsed = pd.to_datetime(f"{EXPECTED_YEAR}-01-01") + pd.to_timedelta(range(len(parsed)), unit='s')
            parsed = pd.Series(parsed, index=df.index)
            print("[DEBUG] Replaced wrong years with sequential timestamps from 2025-01-01.")

    # Make sure parsed is a Series
    parsed = pd.Series(parsed, index=df.index)
    print(f"[DEBUG] Parsed after ensuring Series, first 5 values:\n{parsed.head()} (type={type(parsed.iloc[0])})")

    # Only localize if naive (no tz info)
    if local_tz and parsed.dt.tz is None:
        parsed = parsed.dt.tz_localize(local_tz, nonexistent="NaT", ambiguous="NaT")

    # Convert to UTC if not already
    if parsed.dt.tz is not None:
        parsed = parsed.dt.tz_convert("UTC")
    else:
        parsed = parsed.dt.tz_localize("UTC")

    df[col] = parsed  # <--- assign back to the DataFrame

    debug_df = pd.DataFrame({"raw": raw_values, "cleaned": cleaned, "parsed_utc": df[col]})
    if df[col].isna().any():
        print(f"[WARN] Rows still unparsed in '{col}':")
        print(debug_df.loc[df[col].isna()])

    return df

