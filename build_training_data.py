"""Join hourly NO2 (sensor_readings) with hourly-averaged traffic (traffic_readings)."""
import os

import pandas as pd
import psycopg2
from dotenv import load_dotenv

load_dotenv()
conn = psycopg2.connect(os.environ["DATABASE_URL"])
no2 = pd.read_sql(
    "SELECT date_trunc('hour', timestamp) AS hour, value AS no2_ug_m3 FROM sensor_readings "
    "WHERE station_id='NL10240' AND component='NO2' AND value IS NOT NULL", conn)
traf = pd.read_sql(
    "SELECT site_label, date_trunc('hour', timestamp) AS hour, avg(total_flow) AS flow "
    "FROM traffic_readings GROUP BY 1, 2", conn)
conn.close()

pivot = traf.pivot(index="hour", columns="site_label", values="flow").reset_index()
df = no2.merge(pivot, on="hour", how="inner").dropna()
df["total_intensity_veh_per_hr"] = df[["hrl", "hrr", "vwd", "vwa"]].sum(axis=1)
df["hour_of_day"] = pd.to_datetime(df["hour"]).dt.hour
df.to_csv("training_data.csv", index=False)
print(df.to_string())
print("joined rows:", len(df))
