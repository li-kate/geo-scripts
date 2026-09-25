import streamlit as st
import pandas as pd
from io import BytesIO
import json
import tempfile
import os

# === IMPORT YOUR CONVERTERS ===
# from conversions.convert_csv_to_geojson import convert_csv_to_geojson
from conversions.convert_csv_to_gpx import convert_csv_to_gpx_bytes
# from conversions.convert_gpx_to_geojson import convert_gpx_to_geojson

st.set_page_config(page_title="File Conversion Tool", layout="wide")
st.title("File Conversion Tool")

st.write("Convert between supported formats: CSV, GeoJSON, GPX")

# ==== File Upload ====
uploaded_file = st.file_uploader("Upload a file:", type=["csv", "geojson", "gpx"])

conversion_options = (
    "CSV → GeoJSON",
    "CSV → GPX",
    "GPX → GeoJSON",
)

conversion_type = st.selectbox("Choose Conversion Type", conversion_options)


# ==== Helper: load file to temp path (if needed) ====
def write_temp_file(uploaded, suffix):
    tmp = tempfile.NamedTemporaryFile(delete=False, suffix=suffix)
    tmp.write(uploaded.read())
    tmp.flush()
    return tmp.name


# ==== Process ====
if uploaded_file:
    try:
        # Create preview if CSV or GeoJSON
        if uploaded_file.name.endswith(".csv"):
            df = pd.read_csv(uploaded_file)
            st.subheader("Preview (CSV)")
            st.dataframe(df.head())
        elif uploaded_file.name.endswith(".geojson"):
            geojson_data = json.load(uploaded_file)
            st.json(list(geojson_data.keys())[:5])
        else:
            st.info("Preview not supported for GPX")

        # Reset pointer for conversion step
        uploaded_file.seek(0)

        input_path = write_temp_file(uploaded_file, f".{uploaded_file.name.split('.')[-1]}")
        output_data = None
        output_ext = None

        # ====== CALL YOUR CONVERTERS ======
        # if conversion_type == "CSV → GeoJSON":
        #     output_data = convert_csv_to_geojson(input_path)
        #     output_ext = "geojson"

        if conversion_type == "CSV → GPX":
            output_data = convert_csv_to_gpx_bytes(input_path)
            output_ext = "gpx"

        # elif conversion_type == "GPX → GeoJSON":
        #     output_data = convert_gpx_to_geojson(input_path)
        #     output_ext = "geojson"


        if output_data:
            st.success("Conversion completed!")

            st.download_button(
                label=f"Download {output_ext.upper()} File",
                data=output_data,
                file_name=f"{os.path.splitext(uploaded_file.name)[0]}_converted.{output_ext}",
                mime="application/json" if output_ext == "geojson" else "application/gpx+xml"
            )

        # Clean up temp
        os.remove(input_path)

    except Exception as e:
        st.error(f"Conversion failed: {e}")
