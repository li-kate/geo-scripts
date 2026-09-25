import pandas as pd
import re
import os
from collections import defaultdict

txt_file = "../data/raw_data/test w new freq - sensor 06.TXT"
csv_file = os.path.splitext(txt_file)[0] + ".csv"

# Same as the 2-minute CSV header
headers = [
    "UTCDateTime","mac_address","firmware_ver","hardware",
    "current_temp_f","current_humidity","current_dewpoint_f","pressure",
    "adc","mem","rssi","uptime",
    "pm1_0_cf_1","pm2_5_cf_1","pm10_0_cf_1",
    "pm1_0_atm","pm2_5_atm","pm10_0_atm",
    "pm2.5_aqi_cf_1","pm2.5_aqi_atm",
    "p_0_3_um","p_0_5_um","p_1_0_um","p_2_5_um","p_5_0_um","p_10_0_um",
    "pm1_0_cf_1_b","pm2_5_cf_1_b","pm10_0_cf_1_b",
    "pm1_0_atm_b","pm2_5_atm_b","pm10_0_atm_b",
    "pm2.5_aqi_cf_1_b","pm2.5_aqi_atm_b",
    "p_0_3_um_b","p_0_5_um_b","p_1_0_um_b","p_2_5_um_b","p_5_0_um_b","p_10_0_um_b",
    "gas"
]

data_cols = [
    "current_temp_f","current_humidity","current_dewpoint_f","pressure",
    "adc","mem","rssi","uptime",
    "pm1_0_cf_1","pm2_5_cf_1","pm10_0_cf_1",
    "pm1_0_atm","pm2_5_atm","pm10_0_atm",
    "pm2.5_aqi_cf_1","pm2.5_aqi_atm",
    "p_0_3_um","p_0_5_um","p_1_0_um","p_2_5_um","p_5_0_um","p_10_0_um","gas"
]

pattern = re.compile(r"^(\S+)\s+(\S+):\s+DATA\s+([AB])\(\d+\),(.*)$")
records = defaultdict(dict)

with open(txt_file,"r",encoding="utf-8") as f:
    for line in f:
        m = pattern.match(line.strip())
        if not m:
            continue
        _, utc, channel, values = m.groups()
        vals = values.split(",")
        records[utc][channel] = dict(zip(data_cols, vals))

rows = []
for utc, chans in sorted(records.items()):
    rowdict = {h: "" for h in headers}
    rowdict["UTCDateTime"] = utc

    if "A" in chans:
        for k,v in chans["A"].items():
            rowdict[k] = v

    if "B" in chans:
        for k,v in chans["B"].items():
            if k == "gas":
                rowdict[k] = v
            else:
                rowdict[f"{k}_b"] = v

    rows.append([rowdict[h] for h in headers])

df = pd.DataFrame(rows, columns=headers)
df["UTCDateTime"] = pd.to_datetime(df["UTCDateTime"], errors="coerce")
for col in headers:
    if col != "UTCDateTime":
        df[col] = pd.to_numeric(df[col], errors="coerce")

df.set_index("UTCDateTime", inplace=True)
df_agg = df.resample("15s").median().reset_index()

df_agg.to_csv(csv_file, index=False)
print(f"✅ Saved to {csv_file}")
print(df.head())