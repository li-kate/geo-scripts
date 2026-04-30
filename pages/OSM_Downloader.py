"""
Historical OSM Downloader - Streamlit Page
Download historical OSM road networks using Overpass API.
"""

import streamlit as st
import pandas as pd
from datetime import datetime, timezone
import sys
import os

sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from scripts.download_osm import (
    parse_extent_string,
    download_historical_osm
)

st.set_page_config(
    page_title="OSM Downloader",
    page_icon="",
    layout="wide"
)

st.markdown("""
<style>
    .tool-header { font-size: 2rem; font-weight: 700; margin-bottom: 1rem; }
    .info-box { background-color: #e3f2fd; border-radius: 10px; padding: 1.5rem; margin-bottom: 1rem; border-left: 4px solid #2196F3; }
</style>
""", unsafe_allow_html=True)

st.markdown('<p class="tool-header">OSM Downloader</p>', unsafe_allow_html=True)
st.markdown("Download OSM road networks using Overpass API with `[date]` filtering.")

st.markdown("---")

# Input tabs
tab1, tab2 = st.tabs(["📁 CSV Upload", "✏️ Manual Input"])

with tab1:
    st.markdown("### Upload CSV with City Extents")
    st.markdown("CSV format: `city` and `extent` columns. Extent: `(-84.42, 33.72, -84.37, 33.77)`")
    
    uploaded_file = st.file_uploader("Choose a CSV file", type=['csv'])
    
    if uploaded_file:
        try:
            df = pd.read_csv(uploaded_file, sep='\t')
            if len(df.columns) < 2:
                uploaded_file.seek(0)
                df = pd.read_csv(uploaded_file)
            
            st.success(f"✅ Loaded {len(df)} cities")
            
            parsed = []
            for _, row in df.iterrows():
                try:
                    extent = parse_extent_string(row['extent'])
                    parsed.append({
                        'city': row['city'],
                        'extent': extent
                    })
                except Exception as e:
                    st.error(f"Error parsing {row.get('city', 'unknown')}: {e}")
            
            if parsed:
                st.dataframe(pd.DataFrame(parsed))
                st.session_state['csv_extents'] = parsed
                
        except Exception as e:
            st.error(f"Error reading CSV: {e}")

with tab2:
    st.markdown("### Manual Bounding Box")
    city_name = st.text_input("City Name", "Custom Area")
    
    cols = st.columns(4)
    with cols[0]: min_lon = st.number_input("Min Lon", value=-74.09, format="%.6f")
    with cols[1]: min_lat = st.number_input("Min Lat", value=40.79, format="%.6f")
    with cols[2]: max_lon = st.number_input("Max Lon", value=-74.05, format="%.6f")
    with cols[3]: max_lat = st.number_input("Max Lat", value=40.83, format="%.6f")
    
    st.session_state['manual_extent'] = {
        'city': city_name,
        'extent': [min_lon, min_lat, max_lon, max_lat]
    }

# Configuration
st.markdown("---")
st.markdown("### Download Configuration")

col1, col2, col3 = st.columns(3)

with col1:
    buffer_m = st.number_input("Buffer (meters)", value=500, step=100)
with col2:
    target_date = st.date_input("Target Date", value=datetime(2025, 8, 1))
with col3:
    network = st.selectbox("Network Type", ['driving', 'walking', 'biking', 'all'])

# Download
st.markdown("---")

if st.button("Download OSM Data", type="primary", use_container_width=True):
    extents = st.session_state.get('csv_extents') or [st.session_state.get('manual_extent')]
    
    if not extents or not extents[0]:
        st.warning("Please upload a CSV or enter a bounding box.")
        st.stop()
    
    date_str = target_date.strftime('%Y-%m-%d')
    
    progress = st.progress(0)
    status = st.empty()
    status.text("Downloading...")
    
    osm_xml, stats = download_historical_osm(extents, date_str, buffer_m, network)
    
    progress.progress(100)
    status.text("Complete!")
    
    if osm_xml:
        st.success(f"Downloaded {sum(s['ways'] for s in stats):,} ways across {len(extents)} cities")
        
        st.dataframe(pd.DataFrame(stats))
        
        st.download_button(
            "Download OSM XML",
            osm_xml,
            f"osm_roads_{date_str}.osm",
            "application/xml",
            use_container_width=True
        )
        
        # Show preview
        with st.expander("Preview OSM XML"):
            st.code('\n'.join(osm_xml.split('\n')[:30]), language='xml')
    else:
        st.error("Download failed for all cities.")

st.markdown("---")
st.info("""
**How it works:** Uses Overpass API with `[date]` filtering to retrieve the OSM road network 
exactly as it existed on your chosen date. Returns proper OSM XML with shared intersection 
nodes and complete topology. No authentication or API key required.
""")