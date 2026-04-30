"""
Spatial Merge Tool - Streamlit Page
Transfer attributes from source GeoJSON to target dataset via spatial join.
"""

import streamlit as st
import os
import sys
import time
import pandas as pd
import geopandas as gpd

# Add parent directory to path
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from scripts.spatial_merge import spatial_merge
from utils.file_handlers import (
    TempFileManager,
    validate_geojson_file,
    validate_pbf_file,
    get_download_link
)
from utils.spatial_utils import detect_and_handle_crs, get_geojson_preview

st.set_page_config(
    page_title="Spatial Merge",
    page_icon="",
    layout="wide"
)

st.title("Spatial Merge")
st.markdown("Transfer attributes between geospatial datasets using nearest-neighbor spatial join.")

# Initialize session state
if 'processed' not in st.session_state:
    st.session_state.processed = False
if 'output_path' not in st.session_state:
    st.session_state.output_path = None
if 'stats' not in st.session_state:
    st.session_state.stats = None

# Create temp file manager
if 'temp_manager' not in st.session_state:
    st.session_state.temp_manager = TempFileManager()

# === SIDEBAR CONFIGURATION ===
with st.sidebar:
    st.header("Configuration")
    
    # Target type selection
    target_type = st.radio(
        "Target Type:",
        options=['geojson', 'pbf'],
        format_func=lambda x: 'GeoJSON → GeoJSON' if x == 'geojson' else 'PBF → OSM XML',
        help="Choose GeoJSON for GeoJSON-to-GeoJSON merge, or PBF for OSM network extraction and merge"
    )
    
    st.markdown("---")
    
    # Max distance
    use_distance = st.checkbox("Set maximum match distance", value=False,
                              help="Limit matches to within a certain distance")
    if use_distance:
        max_distance = st.number_input(
            "Max distance:",
            min_value=0.0,
            value=10.0,
            step=1.0,
            help="Maximum distance for matching (in source CRS units). Features farther than this won't get attributes."
        )
    else:
        max_distance = None
    
    # Fill strategy
    st.markdown("### Unmatched Features")
    fill_strategy = st.radio(
        "Strategy for unmatched features:",
        options=['nan', 'value'],
        format_func=lambda x: 'Leave as NaN' if x == 'nan' else 'Fill with value',
        help="What to do when no source feature is within max distance"
    )
    
    if fill_strategy == 'value':
        fill_value = st.number_input(
            "Fill value:",
            value=0.0,
            step=0.1,
            help="Value to assign to unmatched features"
        )
    else:
        fill_value = None
    
    st.markdown("---")
    
    # Bounding box options
    st.markdown("### Bounding Box Filter (Optional)")
    use_bbox = st.checkbox("Filter by bounding box", value=False,
                          help="Only process features within a specific area")
    
    bbox_mode = None
    bbox_custom = None
    city_names = None
    
    if use_bbox:
        bbox_mode = st.selectbox(
            "Bounding box mode:",
            options=['source_bounds', 'target_bounds', 'custom', 'cities'],
            format_func=lambda x: {
                'source_bounds': 'Use source file bounds',
                'target_bounds': 'Use target file bounds',
                'custom': 'Custom coordinates',
                'cities': 'City names'
            }[x]
        )
        
        if bbox_mode == 'custom':
            col1, col2 = st.columns(2)
            with col1:
                minx = st.number_input("Min longitude (x):", value=-84.55, format="%.4f")
                miny = st.number_input("Min latitude (y):", value=33.60, format="%.4f")
            with col2:
                maxx = st.number_input("Max longitude (x):", value=-84.25, format="%.4f")
                maxy = st.number_input("Max latitude (y):", value=33.90, format="%.4f")
            bbox_custom = [minx, miny, maxx, maxy]
        
        elif bbox_mode == 'cities':
            cities_input = st.text_area(
                "City names (one per line):",
                value="Everett, Massachusetts, USA\nChelsea, Massachusetts, USA",
                help="Full city names with state/country for geocoding"
            )
            city_names = [c.strip() for c in cities_input.split('\n') if c.strip()]
    
    # PBF-specific options
    if target_type == 'pbf':
        st.markdown("---")
        st.markdown("### PBF Options")
        network_type = st.selectbox(
            "Network type:",
            options=['all', 'driving', 'walking', 'cycling', 'driving_service'],
            help="Type of OSM network to extract"
        )
    else:
        network_type = "all"
    
    # Target CRS
    if target_type == 'geojson':
        st.markdown("---")
        st.markdown("### Output Options")
        use_target_crs = st.checkbox("Reproject output", value=False,
                                    help="Change the output coordinate reference system")
        if use_target_crs:
            target_crs = st.text_input("Target CRS:", value="EPSG:4326",
                                      help="e.g., EPSG:4326, EPSG:3857")
        else:
            target_crs = None
    else:
        target_crs = None

# === MAIN AREA ===

# File upload section
st.header("Upload Files")

col1, col2 = st.columns(2)

with col1:
    st.subheader("Source File (with attributes)")
    source_file = st.file_uploader(
        "Upload source GeoJSON:",
        type=['geojson', 'json'],
        key='source',
        help="This file contains the attributes you want to transfer"
    )

with col2:
    st.subheader("Target File")
    if target_type == 'geojson':
        target_file = st.file_uploader(
            "Upload target GeoJSON:",
            type=['geojson', 'json'],
            key='target_geojson',
            help="This file will receive the new attributes"
        )
    else:
        target_file = st.file_uploader(
            "Upload target PBF:",
            type=['pbf', 'osm.pbf'],
            key='target_pbf',
            help="OSM PBF file to extract network from"
        )

# Attribute selection section
if source_file:
    st.header("Attribute Selection")
    
    # Save source temporarily to read columns
    source_path = st.session_state.temp_manager.save_uploaded_file(source_file)
    
    try:
        source_gdf = gpd.read_file(source_path)
        
        # Show source preview
        st.subheader("Source File Preview")
        preview = get_geojson_preview(source_gdf)
        
        col1, col2, col3 = st.columns(3)
        with col1:
            st.metric("Features", preview['total_features'])
        with col2:
            st.metric("Columns", preview['total_columns'])
        with col3:
            st.metric("CRS", preview['crs'])
        
        # Attribute column selection
        available_cols = [c for c in source_gdf.columns if c != 'geometry']
        default_cols = [c for c in available_cols if source_gdf[c].dtype in ['float64', 'int64', 'float32', 'int32']]
        
        attribute_columns = st.multiselect(
            "Select attributes to transfer:",
            options=available_cols,
            default=default_cols[:5] if default_cols else available_cols[:3],
            help="Choose which columns from the source file to add to the target"
        )
        
        # Show sample data
        if attribute_columns:
            st.write("Sample of selected attributes:")
            st.dataframe(
                source_gdf[attribute_columns].head(5),
                use_container_width=True
            )
    
    except Exception as e:
        st.error(f"Error reading source file: {str(e)}")
        attribute_columns = []
else:
    attribute_columns = []

# Run button
st.markdown("---")
run_col1, run_col2, run_col3 = st.columns([1, 2, 1])

with run_col2:
    run_button = st.button(
        "Run Spatial Merge",
        type="primary",
        use_container_width=True,
        disabled=not (source_file and target_file and attribute_columns)
    )

# Processing
if run_button:
    try:
        # Save files
        source_path = st.session_state.temp_manager.save_uploaded_file(source_file)
        target_path = st.session_state.temp_manager.save_uploaded_file(target_file)
        
        # Progress bar
        progress_bar = st.progress(0)
        status_text = st.empty()
        
        def update_progress(percent, message):
            progress_bar.progress(percent)
            status_text.text(f"{message} ({percent}%)")
        
        # Run spatial merge
        with st.spinner("Processing..."):
            output_path, stats = spatial_merge(
                target_path=target_path,
                source_path=source_path,
                attribute_columns=attribute_columns,
                target_type=target_type,
                max_distance=max_distance,
                output_path=None,
                bbox_mode=bbox_mode if use_bbox else None,
                bbox_custom=bbox_custom,
                city_names=city_names,
                fill_strategy=fill_strategy,
                fill_value=fill_value,
                target_crs=target_crs,
                network_type=network_type,
                progress_callback=update_progress
            )
        
        # Store results
        st.session_state.processed = True
        st.session_state.output_path = output_path
        st.session_state.stats = stats
        
        progress_bar.empty()
        status_text.empty()
        
        st.success("Spatial merge completed successfully!")
    
    except Exception as e:
        st.error(f"Error during processing: {str(e)}")
        import traceback
        st.code(traceback.format_exc())

# Display results
if st.session_state.processed and st.session_state.stats:
    st.markdown("---")
    st.header("Results")
    
    stats = st.session_state.stats
    
    # Results metrics
    col1, col2, col3, col4 = st.columns(4)
    with col1:
        st.metric("Target Features", stats.get('target_features', 'N/A'))
    with col2:
        st.metric("Matched", stats.get('matched_features', 'N/A'))
    with col3:
        st.metric("Match Rate", f"{stats.get('match_percentage', 0):.1f}%")
    with col4:
        st.metric("Time", f"{stats.get('execution_time', 0):.1f}s")
    
    # Match statistics
    st.subheader("Match Statistics")
    unmatched = stats.get('unmatched_features', 0)
    matched = stats.get('matched_features', 0)
    total = stats.get('target_features', 1)
    
    st.write(f"✅ Matched: {matched}/{total} features ({matched/total*100:.1f}%)")
    st.write(f"⚠️ Unmatched: {unmatched}/{total} features ({unmatched/total*100:.1f}%)")
    
    if unmatched > 0:
        st.info(
            f"{unmatched} features did not have a source match within "
            f"{max_distance if max_distance else 'any'} distance. "
            f"They were {'filled with ' + str(fill_value) if fill_strategy == 'value' else 'left as NaN'}."
        )
    
    # Warnings and errors
    if stats.get('warnings'):
        with st.expander(f"⚠️ Warnings ({len(stats['warnings'])})", expanded=False):
            for warning in stats['warnings']:
                st.warning(warning)
    
    if stats.get('errors'):
        with st.expander(f"❌ Errors ({len(stats['errors'])})", expanded=True):
            for error in stats['errors']:
                st.error(error)
    
    # Download button
    st.markdown("---")
    st.subheader("Download Output")
    
    if st.session_state.output_path and os.path.exists(st.session_state.output_path):
        with open(st.session_state.output_path, 'rb') as f:
            output_data = f.read()
        
        output_filename = os.path.basename(st.session_state.output_path)
        
        st.download_button(
            label=f"📥 Download {output_filename}",
            data=output_data,
            file_name=output_filename,
            mime='application/octet-stream',
            type="primary"
        )
        
        # Show output preview if GeoJSON
        if target_type == 'geojson':
            try:
                output_gdf = gpd.read_file(st.session_state.output_path)
                with st.expander("Output Preview (first 10 features)", expanded=False):
                    st.dataframe(
                        output_gdf.head(10).drop(columns=['geometry'], errors='ignore'),
                        use_container_width=True
                    )
            except:
                pass
    else:
        st.error("Output file not found. Please try processing again.")

# Help section
with st.expander("How it works", expanded=False):
    st.markdown("""
    ### Spatial Merge Process
    
    1. **Load Files**: Source GeoJSON (with attributes) and target file are loaded
    2. **Validate Geometries**: Invalid or missing geometries are removed
    3. **Apply Bounding Box** (optional): Filter to area of interest
    4. **Spatial Join**: For each target feature, find the nearest source feature
    5. **Transfer Attributes**: Copy selected attributes from source to matched target features
    6. **Handle Unmatched**: Features with no match within max distance get NaN or fill value
    
    ### For PBF Targets
    - OSM network is extracted from the PBF file
    - Missing nodes are reconstructed from edge geometries
    - Output is a fully-noded OSM XML with merged attributes as tags
    
    ### Tips
    - For accurate distance measurements, ensure both files use a projected CRS (meters)
    - Use the bounding box filter to process large files faster
    - Preview source data to select the right attribute columns
    """)

# Cleanup note
st.sidebar.markdown("---")
st.sidebar.caption("Temp files are cleaned up automatically when you close the app.")