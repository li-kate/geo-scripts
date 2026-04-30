"""
GeoSpatial Tools - Streamlit Application
Home page with task selection and overview.
"""

import streamlit as st

st.set_page_config(
    page_title="GeoSpatial Tools",
    page_icon="🗺️",
    layout="wide",
    initial_sidebar_state="expanded"
)

# Custom CSS for better styling
st.markdown("""
<style>
    .main-header {
        font-size: 2.5rem;
        font-weight: 700;
        margin-bottom: 1rem;
    }
    .sub-header {
        font-size: 1.2rem;
        color: #666;
        margin-bottom: 2rem;
    }
    .tool-card {
        background-color: #f8f9fa;
        border-radius: 10px;
        padding: 1.5rem;
        margin-bottom: 1rem;
        border-left: 4px solid #4CAF50;
    }
    .tool-card h3 {
        color: #2c3e50;
        margin-top: 0;
    }
    .tool-card p {
        color: #555;
        margin-bottom: 0.5rem;
    }
    .tool-card .use-cases {
        color: #777;
        font-size: 0.9rem;
        font-style: italic;
    }
</style>
""", unsafe_allow_html=True)

# Header
st.markdown('<p class="main-header">GeoSpatial Tools</p>', unsafe_allow_html=True)
st.markdown('<p class="sub-header">Process, merge, and validate geospatial data with ease</p>', unsafe_allow_html=True)

st.markdown("---")

# Introduction
st.markdown("""
### Welcome!
Select a tool below to get started. Each tool handles a specific geospatial processing task.
All tools accept common formats (GeoJSON, OSM PBF) and provide detailed results with downloadable outputs.
""")

st.markdown("---")

# Tool Cards
col1, col2 = st.columns(2)

with col1:
    st.markdown("""
    <div class="tool-card">
        <h3>Spatial Merge</h3>
        <p>Transfer attributes between geospatial datasets using nearest-neighbor spatial join.</p>
        <p><strong>Inputs:</strong> Source GeoJSON (attributes) + Target (GeoJSON or OSM PBF)</p>
        <p><strong>Output:</strong> Enriched GeoJSON or OSM XML</p>
        <p class="use-cases">Use cases: Add sidewalk width to routes, attach heat data to road networks, merge any spatial attributes</p>
    </div>
    """, unsafe_allow_html=True)
    
    st.markdown("""
    <div class="tool-card">
        <h3>Validate Network Integrity</h3>
        <p>Compare a GeoJSON network against OSM PBF reference to find missing segments and data quality issues.</p>
        <p><strong>Inputs:</strong> Network GeoJSON + OSM PBF reference</p>
        <p><strong>Output:</strong> Validation report with coverage and quality metrics</p>
        <p class="use-cases">Use cases: Check if your network covers all OSM roads, identify gaps in attribute data</p>
    </div>
    """, unsafe_allow_html=True)

    st.markdown("""
    <div class="tool-card">
        <h3>OSM Downloader</h3>
        <p>Download historical OSM road networks for specific dates using Overpass API.</p>
        <p><strong>Inputs:</strong> CSV with city extents or manual bounding box</p>
        <p><strong>Output:</strong> OSM XML road network with proper topology</p>
        <p class="use-cases">Use cases: Get August 2025 road networks, historical analysis, buffered downloads to prevent edge effects</p>
    </div>
    """, unsafe_allow_html=True)

with col2:
    st.markdown("""
    <div class="tool-card">
        <h3>Validate OSM XML</h3>
        <p>Check OSM XML files for structural issues, missing references, and data consistency.</p>
        <p><strong>Inputs:</strong> OSM XML file</p>
        <p><strong>Output:</strong> Validation report with issues and warnings</p>
        <p class="use-cases">Use cases: Verify output quality, debug node/way references, check XML structure</p>
    </div>
    """, unsafe_allow_html=True)
    
    st.markdown("""
    <div class="tool-card">
        <h3>Create City Boundaries</h3>
        <p>Generate boundary geometries from multiple GeoJSON files using convex hulls.</p>
        <p><strong>Inputs:</strong> Folder of GeoJSON files</p>
        <p><strong>Output:</strong> Combined boundary GeoJSON with city names</p>
        <p class="use-cases">Use cases: Create study area boundaries, define regions of interest</p>
    </div>
    """, unsafe_allow_html=True)

st.markdown("---")

# Navigation help
st.info("""
### How to use:
1. Select a tool from the sidebar navigation
2. Upload your files and configure parameters
3. Run the process and download your results

All processing happens locally - your data never leaves your machine.
""")

# Footer
st.markdown("---")
st.markdown(
    "<p style='text-align: center; color: #999; font-size: 0.9rem;'>"
    "GeoSpatial Tools - Built with Streamlit, GeoPandas, Pyrosm, and Shapely</p>",
    unsafe_allow_html=True
)