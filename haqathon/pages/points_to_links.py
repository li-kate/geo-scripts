import streamlit as st
import pandas as pd
import geojson
from pipeline.points_to_links_func import convert_points_to_links

st.set_page_config(page_title="OSM Link Converter", layout="wide")
st.title("Point → OSM Link Data Converter")

uploaded_csv = st.file_uploader("Upload merged CSV", type=["csv"])

if uploaded_csv and st.button("Convert to OSM-linked GeoJSON"):
    with st.spinner("Processing and matching points to OSM network..."):
        df = pd.read_csv(uploaded_csv)

        feature_collection = convert_points_to_links(df)
        geojson_bytes = geojson.dumps(feature_collection, indent=2).encode("utf-8")

    # Build output filename using input name (strip .csv, add .geojson)
    base_name = uploaded_csv.name.rsplit(".", 1)[0]
    output_name = f"{base_name}.geojson"

    st.success("GeoJSON conversion complete!")
    st.download_button(
        label="Download OSM-Linked GeoJSON",
        data=geojson_bytes,
        file_name=output_name,
        mime="application/geo+json"
    )
