"""
File handling utilities for Streamlit application.
Manages temporary files, downloads, and file validation.
"""

import os
import tempfile
import shutil
from pathlib import Path
import geopandas as gpd
import json


class TempFileManager:
    """
    Manages temporary files created during processing.
    Ensures cleanup when done.
    """
    
    def __init__(self):
        self.temp_dir = tempfile.mkdtemp()
        self.files = []
    
    def save_uploaded_file(self, uploaded_file):
        """
        Saves a Streamlit UploadedFile to temp directory.
        
        Args:
            uploaded_file: Streamlit UploadedFile object
            
        Returns:
            Path to saved file
        """
        file_path = os.path.join(self.temp_dir, uploaded_file.name)
        
        with open(file_path, 'wb') as f:
            f.write(uploaded_file.getbuffer())
        
        self.files.append(file_path)
        return file_path
    
    def save_dataframe(self, gdf, filename, driver='GeoJSON'):
        """
        Saves a GeoDataFrame to temp directory.
        
        Args:
            gdf: GeoDataFrame to save
            filename: Output filename
            driver: OGR driver name
            
        Returns:
            Path to saved file
        """
        file_path = os.path.join(self.temp_dir, filename)
        gdf.to_file(file_path, driver=driver)
        self.files.append(file_path)
        return file_path
    
    def get_file_path(self, filename):
        """Get full path in temp directory."""
        return os.path.join(self.temp_dir, filename)
    
    def cleanup(self):
        """Remove all temporary files."""
        try:
            shutil.rmtree(self.temp_dir)
        except Exception:
            pass  # Best effort cleanup
    
    def __del__(self):
        self.cleanup()


def validate_geojson_file(file_path):
    """
    Validates that a file is a proper GeoJSON.
    
    Args:
        file_path: Path to file
        
    Returns:
        tuple: (is_valid, error_message)
    """
    try:
        with open(file_path, 'r', encoding='utf-8') as f:
            data = json.load(f)
        
        if 'type' not in data:
            return False, "Not a valid GeoJSON: missing 'type' property"
        
        if data['type'] != 'FeatureCollection':
            return False, f"Expected 'FeatureCollection', got '{data['type']}'"
        
        if 'features' not in data:
            return False, "Missing 'features' array"
        
        if len(data['features']) == 0:
            return False, "GeoJSON has no features (empty)"
        
        return True, None
        
    except json.JSONDecodeError as e:
        return False, f"Invalid JSON format: {str(e)}"
    except Exception as e:
        return False, f"Error reading file: {str(e)}"


def validate_pbf_file(file_path):
    """
    Validates that a file appears to be a valid PBF file.
    
    Args:
        file_path: Path to file
        
    Returns:
        tuple: (is_valid, error_message)
    """
    if not os.path.exists(file_path):
        return False, "File does not exist"
    
    if os.path.getsize(file_path) == 0:
        return False, "File is empty"
    
    # Basic check for .pbf extension
    if not file_path.lower().endswith('.pbf'):
        return False, "File does not have .pbf extension"
    
    return True, None


def get_download_link(file_path, button_text="Download Result"):
    """
    Creates a download link for a file in Streamlit.
    
    Args:
        file_path: Path to file
        button_text: Text for download button
        
    Returns:
        str: HTML download link
    """
    import streamlit as st
    
    if not os.path.exists(file_path):
        st.error(f"File not found: {file_path}")
        return None
    
    with open(file_path, 'rb') as f:
        file_data = f.read()
    
    file_name = os.path.basename(file_path)
    
    return st.download_button(
        label=button_text,
        data=file_data,
        file_name=file_name,
        mime='application/octet-stream'
    )