"""
Network Integrity Validation - Streamlit Page
Compare GeoJSON network against OSM PBF reference.
"""

import streamlit as st
import os
import sys
import geopandas as gpd

sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from scripts.validate_network import validate_network_integrity
from utils.file_handlers import TempFileManager

st.set_page_config(
    page_title="Validate Network",
    page_icon="",
    layout="wide"
)

st.title("Validate Network Integrity")
st.markdown("Compare a GeoJSON network against OSM PBF reference to identify gaps and data quality issues.")

# Initialize temp manager
if 'temp_manager_validate' not in st.session_state:
    st.session_state.temp_manager_validate = TempFileManager()

# === SIDEBAR ===
with st.sidebar:
    st.header("Configuration")
    
    # CRS selection
    target_crs = st.text_input(
        "Projected CRS:",
        value="EPSG:6491",
        help="Projected CRS for accurate distance calculations (should use meters)"
    )
    
    # Buffer distance
    buffer_distance = st.number_input(
        "Buffer distance:",
        min_value=0.5,
        value=7.0,
        step=0.5,
        help="Buffer distance for geometry matching (in CRS units)"
    )
    
    st.markdown("---")
    
    # Zero handling
    zero_is_missing = st.checkbox(
        "Treat zeros as missing data",
        value=True,
        help="Count 0 values as missing/bad data"
    )
    
    st.markdown("---")
    
    # Custom attribute columns
    use_custom_cols = st.checkbox(
        "Specify attribute columns to check",
        value=False,
        help="Select specific columns to validate (default: all numeric columns)"
    )

# === MAIN AREA ===

# File upload
st.header("Upload Files")
col1, col2 = st.columns(2)

with col1:
    st.subheader("Network GeoJSON")
    geojson_file = st.file_uploader(
        "Upload network GeoJSON:",
        type=['geojson', 'json'],
        key='network_geojson',
        help="The network file to validate"
    )

with col2:
    st.subheader("OSM PBF Reference")
    pbf_file = st.file_uploader(
        "Upload OSM PBF:",
        type=['pbf', 'osm.pbf'],
        key='reference_pbf',
        help="Ground truth OSM network for comparison"
    )

# Custom columns selection
if use_custom_cols and geojson_file:
    st.subheader("Attribute Columns to Check")
    
    try:
        temp_path = st.session_state.temp_manager_validate.save_uploaded_file(geojson_file)
        gdf = gpd.read_file(temp_path)
        numeric_cols = gdf.select_dtypes(include=['float64', 'int64', 'int32', 'float32']).columns.tolist()
        
        attribute_columns = st.multiselect(
            "Select columns to check for nulls/zeros:",
            options=numeric_cols,
            default=numeric_cols[:5] if numeric_cols else [],
            help="These columns will be checked for missing data"
        )
    except:
        attribute_columns = None
        st.warning("Could not read columns from GeoJSON")
else:
    attribute_columns = None

# Run button
st.markdown("---")
run_col1, run_col2, run_col3 = st.columns([1, 2, 1])

with run_col2:
    run_button = st.button(
        "🔍 Validate Network",
        type="primary",
        use_container_width=True,
        disabled=not (geojson_file and pbf_file)
    )

# Processing
if run_button:
    try:
        # Save files
        geojson_path = st.session_state.temp_manager_validate.save_uploaded_file(geojson_file)
        pbf_path = st.session_state.temp_manager_validate.save_uploaded_file(pbf_file)
        
        # Progress
        progress_bar = st.progress(0)
        status_text = st.empty()
        
        def update_progress(percent, message):
            progress_bar.progress(percent)
            status_text.text(message)
        
        # Run validation
        with st.spinner("Validating network integrity..."):
            missing_geo, bad_data, stats = validate_network_integrity(
                geojson_path=geojson_path,
                pbf_path=pbf_path,
                attribute_columns=attribute_columns,
                target_crs=target_crs,
                buffer_distance=buffer_distance,
                zero_is_missing=zero_is_missing,
                progress_callback=update_progress
            )
        
        progress_bar.empty()
        status_text.empty()
        
        st.success("Validation complete!")
        
        # Display results
        st.markdown("---")
        st.header("Validation Results")
        
        # Key metrics
        col1, col2, col3 = st.columns(3)
        with col1:
            coverage = stats.get('coverage_percentage', 0)
            st.metric(
                "Network Coverage",
                f"{coverage:.1f}%",
                delta="Good" if coverage > 95 else "Needs Review",
                delta_color="normal" if coverage > 95 else "off"
            )
        with col2:
            quality = stats.get('quality_percentage', 0)
            st.metric(
                "Data Quality",
                f"{quality:.1f}%",
                delta="Good" if quality > 90 else "Needs Review",
                delta_color="normal" if quality > 90 else "off"
            )
        with col3:
            st.metric(
                "OSM Edges in Area",
                stats.get('osm_edges', 'N/A')
            )
        
        # Detailed breakdown
        st.subheader("Detailed Report")
        
        col1, col2 = st.columns(2)
        with col1:
            st.markdown("#### Geometry Coverage")
            st.write(f"OSM edges in PBF area: {stats.get('osm_edges', 'N/A')}")
            st.write(f"Missing from GeoJSON: {stats.get('missing_from_geojson', 'N/A')}")
            st.write(f"Features in PBF area: {stats.get('pbf_area_features', 'N/A')}")
            st.write(f"Coverage: {stats.get('coverage_percentage', 0):.2f}%")
        
        with col2:
            st.markdown("#### Data Quality")
            if attribute_columns or not use_custom_cols:
                st.write(f"Features checked: {stats.get('pbf_area_features', 'N/A')}")
                st.write(f"Features with bad data: {stats.get('bad_data_features', 'N/A')}")
                st.write(f"Data quality: {stats.get('quality_percentage', 0):.2f}%")
            else:
                st.write("No attribute columns specified for quality check")
        
        # Sample missing segments
        if not missing_geo.empty:
            with st.expander(f"Missing Segments ({len(missing_geo)} total)", expanded=False):
                st.dataframe(
                    missing_geo[['id', 'highway', 'length'] if 'highway' in missing_geo.columns else ['id']].head(20),
                    use_container_width=True
                )
        
        # Sample bad data
        if not bad_data.empty:
            with st.expander(f"Bad Data Features ({len(bad_data)} total)", expanded=False):
                st.dataframe(
                    bad_data.head(20).drop(columns=['geometry'], errors='ignore'),
                    use_container_width=True
                )
        
        # Download results
        if not missing_geo.empty or not bad_data.empty:
            st.markdown("---")
            st.subheader("Download Detailed Results")
            
            col1, col2 = st.columns(2)
            
            with col1:
                if not missing_geo.empty:
                    missing_path = st.session_state.temp_manager_validate.save_dataframe(
                        missing_geo,
                        "missing_segments.geojson"
                    )
                    with open(missing_path, 'rb') as f:
                        st.download_button(
                            "📥 Download Missing Segments (GeoJSON)",
                            f.read(),
                            "missing_segments.geojson",
                            "application/octet-stream"
                        )
            
            with col2:
                if not bad_data.empty:
                    bad_path = st.session_state.temp_manager_validate.save_dataframe(
                        bad_data,
                        "bad_data_features.geojson"
                    )
                    with open(bad_path, 'rb') as f:
                        st.download_button(
                            "📥 Download Bad Data Features (GeoJSON)",
                            f.read(),
                            "bad_data_features.geojson",
                            "application/octet-stream"
                        )
        
        # Warnings and errors
        if stats.get('warnings'):
            with st.expander(f"Warnings ({len(stats['warnings'])})"):
                for w in stats['warnings']:
                    st.warning(w)
        
        if stats.get('errors'):
            with st.expander(f"Errors ({len(stats['errors'])})"):
                for e in stats['errors']:
                    st.error(e)
    
    except Exception as e:
        st.error(f"Error during validation: {str(e)}")
        import traceback
        st.code(traceback.format_exc())