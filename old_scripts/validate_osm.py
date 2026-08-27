"""
OSM XML Validation Script.
Validates OSM XML files for structural integrity, node consistency,
and common issues like duplicate IDs or missing references.

Generalized from validate_osm.py with additional checks and reporting.
"""

import xml.etree.ElementTree as ET
import sys
import os
from collections import Counter
from datetime import datetime


def validate_osm_xml(file_path, progress_callback=None):
    """
    Comprehensive OSM XML validator.
    
    Checks:
    - XML structure validity
    - Duplicate node IDs
    - Missing node references in ways
    - Ways with insufficient nodes (< 2)
    - Missing highway tags on ways
    - Orphan nodes (not referenced by any way)
    - Tag value issues (empty values, invalid characters)
    
    Args:
        file_path: Path to OSM XML file
        progress_callback: Optional callback(progress, message)
        
    Returns:
        dict: Validation report with issues found and statistics
    """
    report = {
        'file_path': file_path,
        'validation_time': None,
        'is_valid': True,
        'nodes': {'total': 0, 'duplicates': 0, 'orphans': 0},
        'ways': {'total': 0, 'valid': 0, 'issues': 0},
        'relations': {'total': 0},
        'tags': {'total': 0, 'empty_values': 0, 'suspicious_keys': 0},
        'issues': [],
        'warnings': [],
        'errors': []
    }
    
    start_time = datetime.now()
    
    try:
        # === STAGE 1: Parse XML ===
        if progress_callback:
            progress_callback(10, "Parsing XML file...")
        
        print(f"\n{'='*60}")
        print(f"OSM XML VALIDATION")
        print(f"{'='*60}")
        print(f"\nValidating: {os.path.basename(file_path)}")
        
        tree = ET.parse(file_path)
        root = tree.getroot()
        
        if root.tag != 'osm':
            report['errors'].append("Root element is not 'osm'")
            report['is_valid'] = False
            return report
        
        print(f"  XML parsed successfully")
        
        if progress_callback:
            progress_callback(20, "Collecting nodes...")
        
        # === STAGE 2: Collect and validate nodes ===
        node_ids = set()
        node_duplicates = []
        node_elements = []
        
        for node in root.findall('node'):
            report['nodes']['total'] += 1
            node_id = node.get('id')
            
            if node_id is None:
                report['issues'].append("Found node without 'id' attribute")
                continue
            
            try:
                node_id_int = int(node_id)
            except ValueError:
                report['issues'].append(f"Invalid node ID: '{node_id}'")
                continue
            
            if node_id_int in node_ids:
                node_duplicates.append(node_id_int)
                report['nodes']['duplicates'] += 1
            else:
                node_ids.add(node_id_int)
                node_elements.append((node_id_int, node))
            
            # Validate lat/lon
            lat = node.get('lat')
            lon = node.get('lon')
            if lat is None or lon is None:
                report['issues'].append(f"Node {node_id} missing lat/lon")
            else:
                try:
                    lat_f, lon_f = float(lat), float(lon)
                    if not (-90 <= lat_f <= 90):
                        report['issues'].append(
                            f"Node {node_id} has invalid latitude: {lat_f}"
                        )
                    if not (-180 <= lon_f <= 180):
                        report['issues'].append(
                            f"Node {node_id} has invalid longitude: {lon_f}"
                        )
                except ValueError:
                    report['issues'].append(
                        f"Node {node_id} has non-numeric lat/lon"
                    )
        
        if node_duplicates:
            report['errors'].append(
                f"Found {len(node_duplicates)} duplicate node IDs"
            )
            report['is_valid'] = False
        
        print(f"  Nodes: {report['nodes']['total']} "
              f"({report['nodes']['duplicates']} duplicates)")
        
        if progress_callback:
            progress_callback(50, "Validating ways...")
        
        # === STAGE 3: Validate ways ===
        visited_nodes = set()
        
        for way in root.findall('way'):
            report['ways']['total'] += 1
            way_id = way.get('id')
            way_issues = []
            
            if way_id is None:
                report['issues'].append("Found way without 'id' attribute")
                continue
            
            # Get node references
            nd_elements = way.findall('nd')
            nd_refs = []
            
            for nd in nd_elements:
                ref = nd.get('ref')
                if ref is None:
                    way_issues.append(f"  Way {way_id}: missing 'ref' in <nd>")
                    continue
                
                try:
                    ref_int = int(ref)
                    nd_refs.append(ref_int)
                    visited_nodes.add(ref_int)
                except ValueError:
                    way_issues.append(
                        f"  Way {way_id}: invalid node reference '{ref}'"
                    )
            
            # Check way length
            if len(nd_refs) < 2:
                way_issues.append(
                    f"  Way {way_id}: has only {len(nd_refs)} nodes (minimum 2 required)"
                )
                report['ways']['issues'] += 1
            
            # Check node references exist
            for ref in nd_refs:
                if ref not in node_ids:
                    way_issues.append(
                        f"  Way {way_id}: references missing node {ref}"
                    )
                    report['ways']['issues'] += 1
            
            # Check for highway tag (warning only)
            tags = way.findall('tag')
            has_highway = False
            for tag in tags:
                report['tags']['total'] += 1
                k = tag.get('k')
                v = tag.get('v')
                
                if k == 'highway':
                    has_highway = True
                
                # Check for empty values
                if v is not None and v.strip() == '':
                    report['tags']['empty_values'] += 1
                    way_issues.append(
                        f"  Way {way_id}: tag '{k}' has empty value"
                    )
                
                # Check for suspicious characters
                if v and ('<' in v or '>' in v or '&' in v):
                    report['tags']['suspicious_keys'] += 1
                    way_issues.append(
                        f"  Way {way_id}: tag '{k}' contains XML special characters"
                    )
            
            if not has_highway:
                report['warnings'].append(
                    f"Way {way_id}: missing 'highway' tag (may be intentional)"
                )
            
            if way_issues:
                report['issues'].extend(way_issues)
            else:
                report['ways']['valid'] += 1
        
        # Find orphan nodes
        orphan_nodes = node_ids - visited_nodes
        report['nodes']['orphans'] = len(orphan_nodes)
        
        print(f"  Ways: {report['ways']['total']} "
              f"({report['ways']['valid']} valid, "
              f"{report['ways']['issues']} with issues)")
        print(f"  Orphan nodes: {len(orphan_nodes)}")
        
        if progress_callback:
            progress_callback(80, "Counting relations...")
        
        # === STAGE 4: Count relations ===
        for relation in root.findall('relation'):
            report['relations']['total'] += 1
        
        print(f"  Relations: {report['relations']['total']}")
        
        if progress_callback:
            progress_callback(100, "Validation complete!")
        
        # === FINAL SUMMARY ===
        report['validation_time'] = (datetime.now() - start_time).total_seconds()
        
        # Determine overall validity
        if report['errors']:
            report['is_valid'] = False
        
        print(f"\n{'='*60}")
        print(f"VALIDATION SUMMARY")
        print(f"{'='*60}")
        
        if report['is_valid']:
            print(f"✓ OSM XML is VALID")
        else:
            print(f"✗ OSM XML has ISSUES")
        
        print(f"  Nodes: {report['nodes']['total']} "
              f"({report['nodes']['duplicates']} duplicates)")
        print(f"  Ways: {report['ways']['total']} "
              f"({report['ways']['valid']} valid)")
        print(f"  Tags: {report['tags']['total']}")
        print(f"  Issues found: {len(report['issues'])}")
        print(f"  Warnings: {len(report['warnings'])}")
        print(f"  Errors: {len(report['errors'])}")
        
        if report['issues']:
            print(f"\n  First 5 issues:")
            for issue in report['issues'][:5]:
                print(f"    - {issue}")
        
        return report
    
    except ET.ParseError as e:
        report['errors'].append(f"XML Parse Error: {str(e)}")
        report['is_valid'] = False
        return report
    except Exception as e:
        report['errors'].append(f"Unexpected error: {str(e)}")
        report['is_valid'] = False
        return report


if __name__ == "__main__":
    import argparse
    
    parser = argparse.ArgumentParser(description="Validate OSM XML file")
    parser.add_argument("file", help="Path to OSM XML file")
    parser.add_argument("--verbose", action='store_true',
                       help="Print all issues (not just summary)")
    
    args = parser.parse_args()
    
    report = validate_osm_xml(
        args.file,
        progress_callback=lambda p, m: print(f"  [{p}%] {m}")
    )
    
    if args.verbose and report['issues']:
        print(f"\nAll Issues:")
        for issue in report['issues']:
            print(f"  - {issue}")