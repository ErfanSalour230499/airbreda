"""Ingest NO2 readings for Luchtmeetnet station NL10240 into PostgreSQL."""
import json
import logging
import os
import sys
import time

import pandas as pd
import psycopg2
import redis
import requests
from dotenv import load_dotenv

import quality

load_dotenv()
logging.basicConfig(level=logging.INFO, format="%(message)s", stream=sys.stdout)

STATION = "NL10240"
URL = f"https://api.luchtmeetnet.nl/open_api/stations/{STATION}/measurements"

# CAP trade-off: the sensor network behaves as AP (available, partition tolerant).
# If a station loses connectivity, the API still answers, but the value may be
# null or stale instead of returning an error. Consistency is sacrificed.
# Production handling: never silently drop or forward-fill nulls. Store them as
# NULL, flag them in logs, alert if too many arrive in a row, and let
# downstream code (the model) decide how to treat missing values.


# Polling interval: Luchtmeetnet publishes ONE value per hour, so we poll hourly
# (at :05, after the new hour is published). Polling every minute would return the
# same value 59 times out of 60, waste requests (fair-use limit is 100 per 5 min)
# and add duplicate work for the database to reject.


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


def build_rows(df, station=STATION):
    """Turn the dataframe into DB rows. Stale/null readings are KEPT but flagged
    (a gap in the time series is worse than a flagged value)."""
    df = df.sort_values("timestamp").reset_index(drop=True)
    values = [None if pd.isnull(v) else float(v) for v in df["value"]]
    flags = quality.flag_readings(values)
    rows = []
    for (ts, comp), v, flagged in zip(zip(df["timestamp"], df["component"]), values, flags):
        if flagged:
            quality.record_bad("luchtmeetnet")
            logging.warning(json.dumps({
                "event": "DATA_QUALITY_ERROR", "source": "Luchtmeetnet",
                "station_id": station, "field": "NO2",
                "reason": "stale_or_null", "value": v, "timestamp": ts}))
        rows.append((station, ts, comp, v, flagged))
    return rows


def save_to_db(df, station=STATION):
    """Idempotent write on the primary key (station_id, timestamp, component)."""
    rows = build_rows(df, station)
    conn = psycopg2.connect(os.environ["DATABASE_URL"])
    try:
        with conn, conn.cursor() as cur:
            cur.executemany(
                """INSERT INTO sensor_readings (station_id, timestamp, component, value, is_flagged)
                   VALUES (%s, %s, %s, %s, %s)
                   ON CONFLICT (station_id, timestamp, component)
                   DO UPDATE SET is_flagged = sensor_readings.is_flagged OR EXCLUDED.is_flagged""",
                rows,
            )
            cur.execute("SELECT count(*) FROM sensor_readings WHERE station_id = %s", (station,))
            total = cur.fetchone()[0]
    finally:
        conn.close()
    return len(rows), total


def publish_readings(df):
    """Publish each NO2 reading to the Redis list 'readings' (producer side of the queue).
    Redis is optional here: if the broker is down we log and carry on, because the
    database write below does not depend on it."""
    if not os.environ.get("REDIS_HOST"):
        return  # no broker configured (e.g. on the VM)
    try:
        r = redis.Redis(host=os.environ.get("REDIS_HOST", "redis"), port=6379, socket_connect_timeout=2)
        for row in df.itertuples():
            r.rpush("readings", json.dumps({
                "station_id": STATION, "timestamp": row.timestamp,
                "component": row.component,
                "value": None if pd.isnull(row.value) else float(row.value)}))
    except redis.RedisError as e:
        logging.warning(json.dumps({"event": "redis_unavailable", "error": str(e)}))


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
        logging.info(json.dumps({
            "event": "fetch_success", "source": "Luchtmeetnet",
            "station_id": STATION, "value": float(latest["value"]),
            "timestamp": latest["timestamp"]}))
    publish_readings(df)
    sent, total = save_to_db(df)
    print(f"Sent {sent} rows. Table now has {total} rows for {STATION}.")


if __name__ == "__main__":
    main()
