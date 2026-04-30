"""
Historical OSM Downloader Logic
Downloads historical OSM road networks using Overpass API with [date] filtering.
Returns proper OSM XML with correct topology and complete tags.
No authentication required.
"""

import math
import requests
import time
import xml.etree.ElementTree as ET
from typing import List, Dict, Optional, Tuple
from datetime import datetime, timezone

# Overpass API endpoints - no authentication needed
OVERPASS_ENDPOINTS = [
    "https://overpass-api.de/api/interpreter",
    "https://overpass.kumi.systems/api/interpreter",
    "https://maps.mail.ru/osm/tools/overpass/api/interpreter"
]

# User agent with contact info (good etiquette)
USER_AGENT = "HistoricalOSMDownloader/1.0"

HIGHWAY_TYPES = {
    'driving': 'motorway|trunk|primary|secondary|tertiary|unclassified|residential|motorway_link|trunk_link|primary_link|secondary_link|tertiary_link|living_street|service',
    'walking': 'footway|pedestrian|steps|path|track|sidewalk',
    'biking': 'cycleway|path|track|residential|tertiary|unclassified',
    'all': '.*'
}


def parse_extent_string(extent_str: str) -> List[float]:
    """
    Parse extent string from CSV format.
    
    Examples:
        '(-84.42876612019641, 33.729746912956074, -84.37898673378866, 33.77852582739317)'
    
    Returns:
        [min_lon, min_lat, max_lon, max_lat]
    """
    cleaned = extent_str.strip('()"\' \t')
    parts = [float(x.strip()) for x in cleaned.split(',')]
    if len(parts) != 4:
        raise ValueError(f"Expected 4 values, got {len(parts)}: {parts}")
    return parts


def buffer_extent(extent: List[float], buffer_meters: float) -> List[float]:
    """
    Buffer a bounding box by distance in meters.
    Uses the middle latitude for accurate longitude scaling.
    
    Args:
        extent: [min_lon, min_lat, max_lon, max_lat]
        buffer_meters: Buffer distance in meters
    
    Returns:
        Buffered [min_lon, min_lat, max_lon, max_lat]
    """
    min_lon, min_lat, max_lon, max_lat = extent
    
    mid_lat = (min_lat + max_lat) / 2
    lat_per_meter = 1.0 / 111320.0
    lon_per_meter = 1.0 / (111320.0 * math.cos(math.radians(mid_lat)))
    
    lat_buffer = buffer_meters * lat_per_meter
    lon_buffer = buffer_meters * lon_per_meter
    
    return [
        min_lon - lon_buffer,
        min_lat - lat_buffer,
        max_lon + lon_buffer,
        max_lat + lat_buffer
    ]


def query_overpass_historical(
    bbox: List[float],
    date_str: str,
    network_type: str = "driving",
    max_retries: int = 3,
    timeout: int = 300
) -> Optional[str]:
    """
    Query Overpass API for historical OSM road network.
    Returns proper OSM XML with shared nodes and complete topology.
    No API key or authentication required.
    
    Args:
        bbox: [min_lon, min_lat, max_lon, max_lat] in WGS84
        date_str: Date in 'YYYY-MM-DD' format (uses midnight UTC)
        network_type: 'driving', 'walking', 'biking', or 'all'
        max_retries: Maximum retry attempts across all endpoints
        timeout: Request timeout in seconds
    
    Returns:
        OSM XML string or None on failure
    """
    # Overpass uses south,west,north,east ordering
    south, west, north, east = bbox[1], bbox[0], bbox[3], bbox[2]
    bbox_str = f"{south},{west},{north},{east}"
    
    highway_filter = HIGHWAY_TYPES.get(network_type, HIGHWAY_TYPES['all'])
    
    # Build the Overpass query
    # [date] filter ensures we get the road network exactly as it was on that date
    # (._;>;); recursively includes all nodes referenced by the ways
    query = f"""
    [out:xml][timeout:{timeout}];
    (
        way["highway"~"^{highway_filter}$"]
            [date:"{date_str}T00:00:00Z"]
            ({bbox_str});
    );
    (._;>;);
    out meta;
    """
    
    headers = {"User-Agent": USER_AGENT}
    
    for attempt in range(max_retries):
        # Cycle through endpoints
        endpoint = OVERPASS_ENDPOINTS[attempt % len(OVERPASS_ENDPOINTS)]
        
        try:
            print(f"Querying {endpoint} (attempt {attempt + 1}/{max_retries})...")
            
            response = requests.post(
                endpoint,
                data={"data": query},
                timeout=timeout,
                headers=headers
            )
            
            if response.status_code == 200:
                # Check for Overpass error messages in the response
                if "<remark>" in response.text and "error" in response.text.lower():
                    print(f"Overpass query error: {response.text[:500]}")
                    continue
                    
                return response.text
                
            elif response.status_code == 429:
                wait_time = (attempt + 1) * 10
                print(f"Rate limited. Waiting {wait_time}s...")
                time.sleep(wait_time)
                
            elif response.status_code == 504:
                print(f"Gateway timeout - area may be too large")
                # Could split the bbox into smaller queries here
                if attempt == max_retries - 1:
                    return None
                time.sleep(5)
                
            else:
                print(f"HTTP {response.status_code}: {response.text[:200]}")
                time.sleep(5)
                
        except requests.exceptions.Timeout:
            print(f"Timeout on {endpoint}")
        except requests.exceptions.ConnectionError:
            print(f"Connection error on {endpoint}")
        except Exception as e:
            print(f"Error with {endpoint}: {e}")
    
    return None


def merge_osm_xml(xml_strings: List[str]) -> str:
    """
    Merge multiple OSM XML strings into one, deduplicating nodes and ways.
    
    Args:
        xml_strings: List of complete OSM XML strings
    
    Returns:
        Combined OSM XML string
    """
    all_nodes = {}
    all_ways = {}
    
    for xml_str in xml_strings:
        try:
            root = ET.fromstring(xml_str)
            
            for node in root.findall('node'):
                node_id = node.get('id')
                if node_id not in all_nodes:
                    all_nodes[node_id] = node
            
            for way in root.findall('way'):
                way_id = way.get('id')
                if way_id not in all_ways:
                    all_ways[way_id] = way
                    
        except ET.ParseError as e:
            print(f"Warning: Could not parse XML: {e}")
            continue
    
    # Build combined output
    output = ['<?xml version="1.0" encoding="UTF-8"?>']
    output.append('<osm version="0.6" generator="historical-osm-downloader">')
    
    for node in all_nodes.values():
        output.append(ET.tostring(node, encoding='unicode').strip())
    
    for way in all_ways.values():
        output.append(ET.tostring(way, encoding='unicode').strip())
    
    output.append('</osm>')
    
    return '\n'.join(output)


def download_historical_osm(
    extents: List[Dict],
    date_str: str,
    buffer_meters: float = 500.0,
    network_type: str = "driving"
) -> Tuple[Optional[str], List[Dict]]:
    """
    Download historical OSM road network for multiple bounding boxes.
    
    Args:
        extents: List of {'city': str, 'extent': [min_lon, min_lat, max_lon, max_lat]}
        date_str: Target date 'YYYY-MM-DD'
        buffer_meters: Buffer distance in meters (default 500)
        network_type: 'driving', 'walking', 'biking', or 'all'
    
    Returns:
        Tuple of (combined_osm_xml, stats_list)
        - combined_osm_xml: Merged OSM XML for all cities, or None if all failed
        - stats_list: Per-city download statistics
    """
    xml_parts = []
    city_stats = []
    
    for i, extent_info in enumerate(extents):
        city = extent_info['city']
        extent = extent_info['extent']
        
        # Apply buffer
        buffered_extent = buffer_extent(extent, buffer_meters)
        
        print(f"Downloading {city} ({i+1}/{len(extents)})...")
        print(f"  Original: {extent}")
        print(f"  Buffered: {buffered_extent}")
        
        osm_xml = query_overpass_historical(
            buffered_extent,
            date_str,
            network_type=network_type
        )
        
        if osm_xml:
            xml_parts.append(osm_xml)
            
            # Count ways and nodes for stats
            num_ways = osm_xml.count('<way ')
            num_nodes = osm_xml.count('<node ')
            
            city_stats.append({
                'city': city,
                'ways': num_ways,
                'nodes': num_nodes,
                'status': '✅ Success'
            })
            print(f"  Downloaded {num_ways} ways, {num_nodes} nodes")
        else:
            city_stats.append({
                'city': city,
                'ways': 0,
                'nodes': 0,
                'status': '❌ Failed'
            })
            print(f"  Failed to download")
    
    if not xml_parts:
        return None, city_stats
    
    # Merge all city data into one OSM XML file
    print("Merging XML data...")
    combined_xml = merge_osm_xml(xml_parts)
    
    return combined_xml, city_stats


if __name__ == "__main__":
    # Test with a single city
    extents = [
        {
            'city': 'NYC',
            'extent': [-74.0925, 40.7997, -74.0561, 40.8273]
        }
    ]
    
    print("Testing historical OSM download...")
    output, stats = download_historical_osm(
        extents,
        "2025-08-01",
        buffer_meters=500
    )
    
    if output:
        with open("test_historical.osm", 'w') as f:
            f.write(output)
        print(f"Saved {len(output):,} bytes to test_historical.osm")
        print(f"Stats: {stats}")
    else:
        print("Download failed")