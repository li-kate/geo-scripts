import argparse
import pandas as pd
import gpxpy
import gpxpy.gpx
from datetime import datetime, timezone


def _build_gpx(df: pd.DataFrame) -> gpxpy.gpx.GPX:
    """Build a GPX object from a DataFrame with GPS Tracks CSV columns."""
    gpx = gpxpy.gpx.GPX()
    track = gpxpy.gpx.GPXTrack()
    gpx.tracks.append(track)
    segment = gpxpy.gpx.GPXTrackSegment()
    track.segments.append(segment)

    for _, row in df.iterrows():
        lat = row["Latitude"]
        lon = row["Longitude"]
        ele = row.get("Altitude(m)", None)
        time_str = row["Date(GMT)"]
        # GPS Tracks exports ISO 8601 UTC timestamps ending in 'Z'
        time_obj = datetime.strptime(time_str, "%Y-%m-%dT%H:%M:%SZ").replace(
            tzinfo=timezone.utc
        )
        segment.points.append(
            gpxpy.gpx.GPXTrackPoint(lat, lon, elevation=ele, time=time_obj)
        )

    return gpx


def convert_csv_to_gpx(csv_path: str, gpx_file: str = "output.gpx") -> str:
    """
    Convert a GPS Tracks CSV file to a GPX file on disk.

    The GPS Tracks CSV format has 4 metadata/waypoint rows before the column
    header row, so skiprows=[0,1,2,3] is used.  The resulting GPX file path
    is returned so callers can pass it on to map-matching or further processing.
    """
    df = pd.read_csv(csv_path, skiprows=4)
    gpx = _build_gpx(df)
    with open(gpx_file, "w") as f:
        f.write(gpx.to_xml())
    return gpx_file


def convert_csv_to_gpx_bytes(csv_path: str) -> bytes:
    """
    Convert a GPS Tracks CSV file to GPX and return the content as bytes.

    Used by the Streamlit conversion page where the result must be passed
    directly to st.download_button without writing a permanent file.
    """
    df = pd.read_csv(csv_path, skiprows=4)
    gpx = _build_gpx(df)
    return gpx.to_xml().encode("utf-8")

def main() -> None:
    parser = argparse.ArgumentParser(description="Convert GPS Tracks CSV to GPX")
    parser.add_argument("csv_path", help="Path to the input CSV file")
    parser.add_argument(
        "gpx_output",
        nargs="?",
        default="output.gpx",
        help="Output GPX filename (default: output.gpx)",
    )
    args = parser.parse_args()
    convert_csv_to_gpx(args.csv_path, args.gpx_output)


if __name__ == "__main__":
    main()