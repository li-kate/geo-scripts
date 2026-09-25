EXPECTED_YEAR = 2026

column_map = {
    "dategmt": "utc_date_time",
    "formatted_date_time": "utc_date_time",
    "utcdatetime": "utc_date_time",
    "time": "utc_date_time",
    "latitude": "latitude",
    "longitude": "longitude",
}

# Dataset-specific columns to keep after loading
columns_to_keep = {
    "gps": ["utc_date_time", "latitude", "longitude", "osm_way_id", "gh_edge_id", "geometry", "edge_geometry"],
    "kestrel": ["utc_date_time", "temperature", "relative_humidity", "calculated_heat_index", "wet_bulb_temp", "wind_speed"],
    "purpleair": [
        "utc_date_time", "pm2_5_cf_1", "pm10_0_cf_1", "pm2_5_atm", "pm10_0_atm",
        "pm2_5_cf_1_b", "pm10_0_cf_1_b", "pm2_5_atm_b", "pm10_0_atm_b",
        "pm25_aqi_cf_1", "pm25_aqi_atm", "pm25_aqi_cf_1_b", "pm25_aqi_atm_b"
    ]
}

thresholds = {
    "temperature_min": -40,
    "temperature_max": 60,
    "heat_index_diff": 4,  # °C
}

# Ordered, deduplicated column list for the final merged output
final_columns = list(dict.fromkeys(
    columns_to_keep["gps"] + columns_to_keep["purpleair"] + columns_to_keep["kestrel"]
))
