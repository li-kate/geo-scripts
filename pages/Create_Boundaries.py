"""
City Boundaries - Streamlit Page
Create boundary geometries from multiple GeoJSON files.
"""

import streamlit as st
import os
import sys
import zipfile
import tempfile
import json

sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from scripts.create_boundaries import create_city_boundaries
from utils.file_handlers import TempFileManager

st.set_page_config(
    page_title="City Boundaries",
    page_icon="🏙️",
    layout="wide"
)

st.title("Create City Boundaries")
st.markdown("Generate boundary geometries from multiple GeoJSON files using convex hulls.")

# Initialize temp manager
if 'temp_manager_boundaries' not in st.session_state:
    st.session_state.temp_manager_boundaries = TempFileManager()

# === SIDEBAR ===
with st.sidebar:
    st.header("Configuration")
    
    output_format = st.selectbox(
        "Output format:",
        options=['geojson', 'shapefile'],
        help="Output file format"
    )
    
    min_points = st.number_input(
        "Minimum points:",
        min_value=3,
        value=3,
        step=1,
        help="Minimum points required to create a boundary per file"
    )

# === MAIN AREA ===

st.header("Upload GeoJSON Files")

# File upload - multiple files
uploaded_files = st.file_uploader(
    "Upload GeoJSON files (multiple):",
    type=['geojson', 'json'],
    accept_multiple_files=True,
    help="Each file's features will be combined into a single boundary"
)

# Show uploaded files
if uploaded_files:
    st.subheader(f"Uploaded Files ({len(uploaded_files)})")
    
    file_info = []
    for file in uploaded_files:
        city_name = os.path.splitext(file.name)[0]
        file_size = len(file.getbuffer()) / 1024  # KB
        
        try:
            data = json.loads(file.getvalue())
            num_features = len(data.get('features', []))
            file_info.append({
                'File': file.name,
                'City': city_name,
                'Features': num_features,
                'Size (KB)': f"{file_size:.1f}"
            })
        except:
            file_info.append({
                'File': file.name,
                'City': city_name,
                'Features': 'Error',
                'Size (KB)': f"{file_size:.1f}"
            })
    
    st.dataframe(file_info, use_container_width=True)

# Run button
if uploaded_files:
    st.markdown("---")
    run_col1, run_col2, run_col3 = st.columns([1, 2, 1])
    
    with run_col2:
        run_button = st.button(
            "Create Boundaries",
            type="primary",
            use_container_width=True
        )
    
    if run_button:
        try:
            # Create temp directory for input files
            input_dir = tempfile.mkdtemp()
            
            for file in uploaded_files:
                file_path = os.path.join(input_dir, file.name)
                with open(file_path, 'wb') as f:
                    f.write(file.getbuffer())
            
            # Define output path
            output_ext = '.geojson' if output_format == 'geojson' else '.shp'
            output_path = st.session_state.temp_manager_boundaries.get_file_path(
                f"boundaries{output_ext}"
            )
            
            # Progress
            progress_bar = st.progress(0)
            status_text = st.empty()
            
            def update_progress(percent, message):
                progress_bar.progress(percent)
                status_text.text(message)
            
            # Run boundary creation
            with st.spinner("Creating boundaries..."):
                output_file, stats = create_city_boundaries(
                    input_folder=input_dir,
                    output_file=output_path,
                    output_format=output_format,
                    min_points=min_points,
                    progress_callback=update_progress
                )
            
            progress_bar.empty()
            status_text.empty()
            
            st.success(f"Boundaries created from {stats['files_processed']} files!")
            
            # Display results
            st.markdown("---")
            st.header("Results")
            
            col1, col2, col3 = st.columns(3)
            with col1:
                st.metric("Input Files", stats['input_files'])
            with col2:
                st.metric("Boundaries Created", stats['boundaries_created'])
            with col3:
                st.metric("Total Points", f"{stats['total_points']:,}")
            
            # File details
            if stats['files_processed'] > 0:
                st.subheader("Processed Cities")
                st.write(f"Successfully processed: {stats['files_processed']} files")
                if stats['crs_reprojected'] > 0:
                    st.info(f"{stats['crs_reprojected']} files were reprojected to WGS84")
            
            if stats['files_skipped'] > 0:
                st.warning(f"{stats['files_skipped']} files were skipped")
            
            # Download button
            st.markdown("---")
            st.subheader("Download Output")
            
            if output_format == 'shapefile':
                # Create zip for shapefile
                zip_path = st.session_state.temp_manager_boundaries.get_file_path("boundaries.zip")
                
                shapefile_base = os.path.splitext(output_file)[0]
                with zipfile.ZipFile(zip_path, 'w') as zf:
                    for ext in ['.shp', '.shx', '.dbf', '.prj', '.cpg']:
                        component = shapefile_base + ext
                        if os.path.exists(component):
                            zf.write(component, os.path.basename(component))
                
                with open(zip_path, 'rb') as f:
                    st.download_button(
                        "Download Boundaries (Shapefile ZIP)",
                        f.read(),
                        "boundaries.zip",
                        "application/zip",
                        type="primary"
                    )
            else:
                with open(output_file, 'rb') as f:
                    st.download_button(
                        "Download Boundaries (GeoJSON)",
                        f.read(),
                        "boundaries.geojson",
                        "application/octet-stream",
                        type="primary"
                    )
            
            # Preview
            try:
                if output_format == 'geojson':
                    with open(output_file, 'r') as f:
                        preview_data = json.load(f)
                    
                    with st.expander("Preview Boundary Coordinates", expanded=False):
                        for feature in preview_data.get('features', []):
                            props = feature.get('properties', {})
                            city = props.get('city', 'Unknown')
                            points = props.get('point_count', 0)
                            st.write(f"**{city}**: {points} points, "
                                    f"from {props.get('source_file', 'N/A')}")
            except:
                pass
            
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
            st.error(f"Error creating boundaries: {str(e)}")
            import traceback
            st.code(traceback.format_exc())
else:
    st.info("Upload multiple GeoJSON files to create combined boundaries")
    st.markdown("""
    ### How it works:
    1. Each uploaded GeoJSON file represents one city/region
    2. All features within a file are combined using convex hull
    3. The resulting boundary is saved as a LineString in WGS84 coordinates
    
    ### Requirements:
    - Files must be valid GeoJSON
    - Each file should have at least 3 coordinate points
    - Files with non-WGS84 CRS will be automatically reprojected
    """)