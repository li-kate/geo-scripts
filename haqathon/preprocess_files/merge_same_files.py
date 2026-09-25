import os
import pandas as pd
import gpxpy
from preprocess_files.purpleair import convert_txt_to_csv


def merge_same_type(files, output_file="merged.csv"):
    """
    Merge multiple datasets of the same type (TXT, CSV, or GPX).
    For TXT: all text files are first concatenated, then converted once using convert_txt_to_csv().
    """
    if not files or len(files) < 2:
        raise ValueError("You must provide at least two files to merge.")

    # Detect file type
    extensions = [os.path.splitext(f)[1].lower() for f in files]
    if len(set(extensions)) != 1:
        raise ValueError("All files must have the same extension.")
    ext = extensions[0]

    # ========== TXT MERGE ==========
    if ext == ".txt":
        merged_txt_file = os.path.splitext(output_file)[0] + ".txt"

        # Merge all .txt files into one
        with open(merged_txt_file, "w", encoding="utf-8") as outfile:
            for f in files:
                with open(f, "r", encoding="utf-8") as infile:
                    outfile.write(infile.read().strip() + "\n")

        print(f"Merged {len(files)} TXT files → {merged_txt_file}")

        csv_file = convert_txt_to_csv(merged_txt_file)  # <- change convert_txt_to_csv to return CSV path
        print(f"Converted merged TXT → CSV: {csv_file}")

        # Return CSV path
        return csv_file

    # ========== GPX MERGE ==========
    elif ext == ".gpx":
        # Parse raw GPS points only — do not run the full pipeline (Kalman +
        # map-matching) per file; merge first, process once.
        dfs = []
        for file in files:
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
                        })
            dfs.append(pd.DataFrame(rows))
        merged = pd.concat(dfs, ignore_index=True)

    # ========== CSV MERGE ==========
    elif ext == ".csv":
        dfs = []
        for file in files:
            # Try skipping metadata lines if present
            try:
                df = pd.read_csv(file, skiprows=[0, 1, 2, 4])
            except Exception:
                df = pd.read_csv(file)
            dfs.append(df)

        # Validate schema
        cols = [set(df.columns) for df in dfs]
        if len(set(map(tuple, cols))) != 1:
            raise ValueError("Not all CSV files have the same columns.")

        merged = pd.concat(dfs, ignore_index=True)

    else:
        raise ValueError("Supported file types are: .txt, .csv, or .gpx")

    # ========== SORT BY TIME ==========
    time_col = None
    for candidate in ["utc_date_time", "UTCDateTime"]:
        if candidate in merged.columns:
            time_col = candidate
            break

    if time_col:
        merged[time_col] = pd.to_datetime(merged[time_col], errors="coerce", utc=True)
        merged = merged.dropna(subset=[time_col]).sort_values(time_col).reset_index(drop=True)

    # Save merged result
    merged.to_csv(output_file, index=False)
    print(f"Merged dataset saved to {output_file}")
    return merged


if __name__ == "__main__":
    folder = "data/raw_data/"
    txt_files = [os.path.join(folder, f) for f in os.listdir(folder) if f.endswith(".txt")]
    output_file = os.path.join(folder, "merged_all.csv")

    merge_same_type(txt_files, output_file)
