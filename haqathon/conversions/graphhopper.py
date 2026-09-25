import pandas as pd
import gpxpy
import gpxpy.gpx
import requests
from polyline import decode

GPX_FILE = "Marietta_GPS.gpx"
MATCH_URL = "http://localhost:8989/match?profile=foot"
HEADERS = {"Content-Type": "application/gpx+xml"}

# Load GPX file
with open(GPX_FILE, "r") as f:
    gpx = gpxpy.parse(f)

# Create GPX for merged snapped path
merged_gpx = gpxpy.gpx.GPX()

for track in gpx.tracks:
    for segment in track.segments:
        # Build GPX for GraphHopper
        gpx_to_snap = gpxpy.gpx.GPX()
        track_snap = gpxpy.gpx.GPXTrack()
        gpx_to_snap.tracks.append(track_snap)
        segment_snap = gpxpy.gpx.GPXTrackSegment()
        track_snap.segments.append(segment_snap)

        for point in segment.points:
            segment_snap.points.append(gpxpy.gpx.GPXTrackPoint(point.latitude, point.longitude))

        gpx_data = gpx_to_snap.to_xml()
        resp = requests.post(MATCH_URL, params={"type": "json"},
                             data=gpx_data.encode("utf-8"), headers=HEADERS)

        if resp.status_code != 200:
            print("Failed snapping segment:", resp.status_code)
            continue

        # Decode snapped polyline
        path = resp.json()["paths"][0]
        snapped_coords = decode(path["points"], precision=5)

        # Add snapped points to merged GPX with timestamps
        track_out = gpxpy.gpx.GPXTrack()
        merged_gpx.tracks.append(track_out)
        seg_out = gpxpy.gpx.GPXTrackSegment()
        track_out.segments.append(seg_out)

        # Map original timestamps to snapped points
        orig_times = [pt.time for pt in segment.points]
        n_snapped = len(snapped_coords)
        n_orig = len(orig_times)

        for i, (lat, lon) in enumerate(snapped_coords):
            # Interpolate time if number of snapped points != original points
            if n_snapped == n_orig:
                time = orig_times[i]
            else:
                # linear interpolation
                idx = i * (n_orig - 1) / (n_snapped - 1)
                lower = int(idx)
                upper = min(lower + 1, n_orig - 1)
                t_frac = idx - lower
                t_lower = orig_times[lower]
                t_upper = orig_times[upper]
                # Interpolate datetime
                delta = (t_upper - t_lower).total_seconds()
                time = t_lower + pd.to_timedelta(delta * t_frac, unit='s')

            seg_out.points.append(gpxpy.gpx.GPXTrackPoint(lat, lon, time=time))

# Save merged snapped GPX
with open("marietta.gpx", "w") as f:
    f.write(merged_gpx.to_xml())

print("Saved .gpx with original timestamps!")
