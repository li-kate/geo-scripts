import streamlit as st
import pandas as pd
from io import StringIO
from tempfile import NamedTemporaryFile
import os

# ==== Custom imports ====
from preprocess_files.gps_tracks import load_gps, snap_to_route
from preprocess_files.kestrel import load_kestrel
from preprocess_files.purpleair import load_purpleair
from pipeline.config import final_columns
from preprocess_files.merge_same_files import merge_same_type

# ==== Streamlit setup ====
st.set_page_config(page_title="Data Pipeline", layout="wide")
st.title("Data Cleaning & Merging Tool")

# ==== FILE INPUTS ====
st.header("Upload Raw Data Files")

file_gps = st.file_uploader(
    "Upload GPS file(s) (.csv or .gpx)",
    type=["csv", "gpx"],
    accept_multiple_files=True
)
file_kestrel = st.file_uploader(
    "Upload Kestrel file(s) (.csv)",
    type=["csv"],
    accept_multiple_files=True
)
file_purpleair = st.file_uploader(
    "Upload PurpleAir file(s) (.csv or .txt)",
    type=["csv", "txt"],
    accept_multiple_files=True
)
geojson_file = st.file_uploader("Upload route GeoJSON", type=["geojson"])

# ==== GPS ACCURACY SETTING ====
st.subheader("Map Matching Settings")
col_mode, col_acc = st.columns(2)

with col_mode:
    travel_mode = st.selectbox(
        "Travel Mode",
        options=["Walking", "Biking"],
        help="Adjusts maximum allowed speed and routing profile."
    )

with col_acc:
    gps_accuracy = st.slider(
        "GPS Accuracy (meters)",
        min_value=1,
        max_value=50,
        value=9,  # Default value matching the hardcoded one
        step=1,
        help="Higher values mean more trust in the road network, lower values mean more trust in GPS points"
    )

# ==== NAME INPUT ====
st.subheader("Output Settings")
default_name = None
if geojson_file is not None:
    # Try to suggest a name from GeoJSON filename
    default_name = os.path.splitext(geojson_file.name)[0]

road_name = st.text_input("Enter road/route name (used in output filename):", value=default_name or "")
if road_name.strip() == "":
    road_name = "merged_dataset"

def process_uploaded_files(uploaded_files, label):
    """
    Write uploaded file(s) to temp storage and return a single file path.
    When multiple files are provided they are merged first.
    Intermediate temp files created during a merge are cleaned up immediately.
    """
    if not uploaded_files:
        return None

    if len(uploaded_files) == 1:
        ext = os.path.splitext(uploaded_files[0].name)[1]
        tmp = NamedTemporaryFile(delete=False, suffix=f"_{label}{ext}")
        tmp.write(uploaded_files[0].read())
        tmp.flush()
        return tmp.name

    # Multiple files: write each to a temp path, merge, then clean up the intermediaries
    tmp_paths = []
    for f in uploaded_files:
        ext = os.path.splitext(f.name)[1]
        tmp = NamedTemporaryFile(delete=False, suffix=f"_{label}{ext}")
        tmp.write(f.read())
        tmp.flush()
        tmp_paths.append(tmp.name)

    merged_file = NamedTemporaryFile(delete=False, suffix=f"_{label}_merged.csv").name
    merge_same_type(tmp_paths, merged_file)

    for p in tmp_paths:
        try:
            os.remove(p)
        except OSError:
            pass

    return merged_file

if st.button("Run"):
    if not file_gps:
        st.error("Please upload GPS files (required).")
    else:
        with st.spinner("Processing datasets..."):

            gps_path = process_uploaded_files(file_gps, "gps")
            kestrel_path = process_uploaded_files(file_kestrel, "kestrel")
            purpleair_path = process_uploaded_files(file_purpleair, "purpleair")

            # --- LOAD & CLEAN DATASETS ---
            df_kestrel = None
            kestrel_times = None
            if kestrel_path:
                df_kestrel = load_kestrel(kestrel_path)
                if df_kestrel is not None and len(df_kestrel) > 0:
                    kestrel_times = df_kestrel["utc_date_time"].tolist()

            df_purpleair = None
            purple_times = None
            if purpleair_path:
                df_purpleair = load_purpleair(purpleair_path)
                if df_purpleair is not None and len(df_purpleair) > 0:
                    purple_times = df_purpleair["utc_date_time"].tolist()

            # Inject interpolated GPS positions at every sensor timestamp so
            # each reading gets an accurate spatial location after map-matching.
            all_sensor_times = []
            if kestrel_times:
                all_sensor_times.extend(kestrel_times)
            if purple_times:
                all_sensor_times.extend(purple_times)
            all_sensor_times = sorted(set(all_sensor_times))

            df_gps, df_route_geom, df_kalman = load_gps(
                gps_path,
                gps_accuracy=gps_accuracy,
                return_line=True,
                sensor_times=all_sensor_times,
                mode=travel_mode,
            )

            # --- PREVIEW DATA ---
            st.subheader("Preview of Loaded Data")
            st.write("**--- GPS ---**")
            st.dataframe(df_gps.head(10))

            st.write("**--- Kestrel ---**")
            if df_kestrel is not None:
                st.dataframe(df_kestrel.head(10))
            else:
                st.info("No Kestrel data uploaded")

            st.write("**--- PurpleAir ---**")
            if df_purpleair is not None:
                st.dataframe(df_purpleair.head(10))
            else:
                st.info("No PurpleAir data uploaded")

            # GPS datetime is parsed inline in load_gps; ensure UTC-aware here
            df_gps["utc_date_time"] = pd.to_datetime(df_gps["utc_date_time"], errors="coerce", utc=True)

            # --- MERGE DATASETS ---
            merged = df_gps.copy()

            if df_purpleair is not None:
                merged = pd.merge_asof(
                    merged.sort_values("utc_date_time"),
                    df_purpleair.sort_values("utc_date_time"),
                    on="utc_date_time",
                    direction="nearest",
                    tolerance=pd.Timedelta("2min"),
                )

            if df_kestrel is not None:
                merged = pd.merge_asof(
                    merged.sort_values("utc_date_time"),
                    df_kestrel.sort_values("utc_date_time"),
                    on="utc_date_time",
                    direction="nearest",
                    tolerance=pd.Timedelta("1min"),
                )

            # --- SELECT FINAL COLUMNS ---
            df_selected = merged[[c for c in final_columns if c in merged.columns]]

            output_name = f"{road_name.replace(' ', '_')}_merged.csv"
            csv_data = df_selected.to_csv(index=False).encode("utf-8")

            st.success(f"Merged dataset for **{road_name}** successfully created!")
            st.dataframe(df_selected.head())

            st.subheader("Downloads")
            col1, col2 = st.columns(2)

            with col1:
                st.download_button(
                    label="Download Merged CSV",
                    data=csv_data,
                    file_name=output_name,
                    mime="text/csv",
                )

            with col2:
                if df_route_geom is not None:
                    st.download_button(
                        label="Download Snapped Route (GeoJSON)",
                        data=df_route_geom.to_json(),
                        file_name=f"{road_name.replace(' ', '_')}_route.geojson",
                        mime="application/json",
                    )
                if df_kalman is not None:
                    st.download_button(
                        label="Download Smoothed Points (CSV)",
                        data=df_kalman.to_csv(index=False).encode("utf-8"),
                        file_name=f"{road_name.replace(' ', '_')}_kalman_points.csv",
                        mime="text/csv",
                    )
                else:
                    st.warning("No route geometry generated.")

            st.toast(f"Merged dataset '{output_name}' ready for download.")

            # --- CLEAN UP TEMP FILES ---
            for path in [gps_path, kestrel_path, purpleair_path]:
                if path and os.path.exists(path):
                    try:
                        os.remove(path)
                    except OSError as e:
                        st.warning(f"Could not delete temp file {path}: {e}")