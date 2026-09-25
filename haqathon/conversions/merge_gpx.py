import requests
import gpxpy
import gpxpy.gpx
from polyline import decode  # pip install polyline

# Example: the JSON response you posted
response_json = {...}  # your JSON here
path = response_json['paths'][0]

# Decode polyline to list of (lat, lon)
coords = decode(path['points'], precision=5)  # returns [(lat, lon), ...]

# Convert to GPX
gpx = gpxpy.gpx.GPX()
gpx_track = gpxpy.gpx.GPXTrack()
gpx.tracks.append(gpx_track)
gpx_segment = gpxpy.gpx.GPXTrackSegment()
gpx_track.segments.append(gpx_segment)

for lat, lon in coords:
    gpx_segment.points.append(gpxpy.gpx.GPXTrackPoint(lat, lon))

# Save GPX
with open("matched_route.gpx", "w") as f:
    f.write(gpx.to_xml())

print("Saved matched_route.gpx")
