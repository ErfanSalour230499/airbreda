"""Ingest NO2 readings for Luchtmeetnet station NL10240 into PostgreSQL."""
import os
import sys
import time

import pandas as pd
import psycopg2
import requests
from dotenv import load_dotenv

load_dotenv()

STATION = "NL10240"
URL = f"https://api.luchtmeetnet.nl/open_api/stations/{STATION}/measurements"

# CAP trade-off: the sensor network behaves as AP (available, partition tolerant).
# If a station loses connectivity, the API still answers, but the value may be
# null or stale instead of returning an error. Consistency is sacrificed.
# Production handling: never silently drop or forward-fill nulls. Store them as
# NULL, flag them in logs, alert if too many arrive in a row, and let
# downstream code (the model) decide how to treat missing values.


def fetch_measurements(formula="NO2", retries=3, timeout=10):
    """Call the live API. Retries with backoff, then raises if still failing."""
    params = {
        "formula": formula,
        "order_by": "timestamp_measured",
        "order_direction": "desc",
        "page": 1,
    }
    for attempt in range(1, retries + 1):
        try:
            r = requests.get(URL, params=params, timeout=timeout)
            r.raise_for_status()
            return r.json().get("data", [])
        except requests.RequestException as e:
            print(f"Attempt {attempt}/{retries} failed: {e}", file=sys.stderr)
            if attempt == retries:
                raise
            time.sleep(2 ** attempt)


def to_dataframe(records):
    return pd.DataFrame(
        {
            "component": [r["formula"] for r in records],
            "value": [r["value"] for r in records],
            "timestamp": [r["timestamp_measured"] for r in records],
        }
    )


def filter_no2_readings(df):
    """Keep NO2 rows only. Null values are kept, not silently dropped."""
    return df[df["component"] == "NO2"].reset_index(drop=True)


def save_to_db(df, station=STATION):
    """Idempotent write: ON CONFLICT DO NOTHING on the primary key
    (station_id, timestamp, component), so running twice adds no duplicates."""
    rows = [
        (station, row.timestamp, row.component, None if pd.isnull(row.value) else float(row.value))
        for row in df.itertuples()
    ]
    conn = psycopg2.connect(os.environ["DATABASE_URL"])
    try:
        with conn, conn.cursor() as cur:
            cur.executemany(
                """INSERT INTO sensor_readings (station_id, timestamp, component, value)
                   VALUES (%s, %s, %s, %s)
                   ON CONFLICT DO NOTHING""",
                rows,
            )
            cur.execute("SELECT count(*) FROM sensor_readings WHERE station_id = %s", (station,))
            total = cur.fetchone()[0]
    finally:
        conn.close()
    return len(rows), total


def main():
    try:
        records = fetch_measurements()
    except requests.RequestException:
        print("ERROR: Luchtmeetnet API unreachable after retries", file=sys.stderr)
        sys.exit(1)
    df = filter_no2_readings(to_dataframe(records))
    if df.empty:
        print("No NO2 readings returned")
        sys.exit(1)
    latest = df.iloc[0]
    if pd.isnull(latest["value"]):
        print(f"WARNING: latest NO2 value is null at {latest['timestamp']}")
    else:
        print(f"Latest NO2: {latest['value']} ug/m3 at {latest['timestamp']}")
    sent, total = save_to_db(df)
    print(f"Sent {sent} rows. Table now has {total} rows for {STATION}.")


if __name__ == "__main__":
    main()
