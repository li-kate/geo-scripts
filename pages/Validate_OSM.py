"""
OSM XML Validation - Streamlit Page
Validate OSM XML files for structural integrity and data consistency.
"""

import streamlit as st
import os
import sys

sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from scripts.validate_osm import validate_osm_xml
from utils.file_handlers import TempFileManager

st.set_page_config(
    page_title="Validate OSM XML",
    page_icon="",
    layout="wide"
)

st.title("Validate OSM XML")
st.markdown("Check OSM XML files for structural issues, missing references, and data consistency.")

# Initialize temp manager
if 'temp_manager_osm' not in st.session_state:
    st.session_state.temp_manager_osm = TempFileManager()

# === MAIN AREA ===

st.header("Upload OSM XML File")
osm_file = st.file_uploader(
    "Upload OSM XML file:",
    type=['osm', 'xml'],
    help="An OSM XML file to validate (typically output from Spatial Merge tool)"
)

# Run button
if osm_file:
    st.markdown("---")
    run_col1, run_col2, run_col3 = st.columns([1, 2, 1])
    
    with run_col2:
        run_button = st.button(
            "Validate OSM XML",
            type="primary",
            use_container_width=True
        )
    
    if run_button:
        try:
            # Save file
            osm_path = st.session_state.temp_manager_osm.save_uploaded_file(osm_file)
            
            # Progress
            progress_bar = st.progress(0)
            status_text = st.empty()
            
            def update_progress(percent, message):
                progress_bar.progress(percent)
                status_text.text(message)
            
            # Run validation
            with st.spinner("Validating OSM XML..."):
                report = validate_osm_xml(
                    osm_path,
                    progress_callback=update_progress
                )
            
            progress_bar.empty()
            status_text.empty()
            
            # Display results
            st.markdown("---")
            st.header("Validation Report")
            
            # Overall status
            if report['is_valid']:
                st.success("✅ OSM XML is VALID")
            else:
                st.error("❌ OSM XML has ISSUES")
            
            # Key metrics
            col1, col2, col3, col4 = st.columns(4)
            with col1:
                st.metric("Total Nodes", report['nodes']['total'])
            with col2:
                st.metric("Total Ways", report['ways']['total'])
            with col3:
                st.metric("Valid Ways", report['ways']['valid'])
            with col4:
                st.metric("Total Tags", report['tags']['total'])
            
            # Detailed metrics
            st.subheader("Detailed Statistics")
            
            col1, col2 = st.columns(2)
            with col1:
                st.markdown("#### Nodes")
                st.write(f"Total: {report['nodes']['total']}")
                st.write(f"Duplicates: {report['nodes']['duplicates']}")
                st.write(f"Orphans: {report['nodes']['orphans']}")
                
                st.markdown("#### Relations")
                st.write(f"Total: {report['relations']['total']}")
            
            with col2:
                st.markdown("#### Ways")
                st.write(f"Total: {report['ways']['total']}")
                st.write(f"Valid: {report['ways']['valid']}")
                st.write(f"With Issues: {report['ways']['issues']}")
                
                st.markdown("#### Tags")
                st.write(f"Total: {report['tags']['total']}")
                st.write(f"Empty Values: {report['tags']['empty_values']}")
                st.write(f"Suspicious Keys: {report['tags']['suspicious_keys']}")
            
            # Issues
            if report['issues']:
                with st.expander(f"Issues Found ({len(report['issues'])})", expanded=True):
                    for i, issue in enumerate(report['issues'][:50]):
                        st.warning(issue)
                    if len(report['issues']) > 50:
                        st.caption(f"... and {len(report['issues']) - 50} more issues")
            
            # Warnings
            if report['warnings']:
                with st.expander(f"Warnings ({len(report['warnings'])})", expanded=False):
                    for warning in report['warnings'][:20]:
                        st.info(warning)
                    if len(report['warnings']) > 20:
                        st.caption(f"... and {len(report['warnings']) - 20} more warnings")
            
            # Errors
            if report['errors']:
                with st.expander(f"Errors ({len(report['errors'])})", expanded=True):
                    for error in report['errors']:
                        st.error(error)
            
            # Validation time
            st.caption(f"Validation completed in {report.get('validation_time', 0):.2f} seconds")
        
        except Exception as e:
            st.error(f"Error during validation: {str(e)}")
            import traceback
            st.code(traceback.format_exc())
else:
    st.info("Upload an OSM XML file to begin validation")
    st.markdown("""
    ### What gets checked:
    - **Node consistency**: Duplicate IDs, missing lat/lon, valid coordinates
    - **Way integrity**: Missing node references, ways with fewer than 2 nodes
    - **Tag quality**: Empty tag values, special characters in values
    - **Orphan nodes**: Nodes not referenced by any way
    - **Highway tags**: Ways missing highway tags (warning only)
    """)