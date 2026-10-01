"""Download NDW feeds, extract the 4 A27 sites near Breda, save one CSV per
site per measurement hour to Blob Storage, and write a per-site summary row
to PostgreSQL (traffic_readings)."""
import io
import json
import logging
import os
import sys

import pandas as pd
import psycopg2
import redis
from azure.identity import DefaultAzureCredential
from azure.storage.blob import BlobServiceClient
from dotenv import load_dotenv

import quality
from getTrafficReadings import (
    CONFIG_URL,
    MEASURED_URL,
    build_index_map,
    download_and_decompress,
    extract_measurements,
)

load_dotenv()
logging.basicConfig(level=logging.INFO, format="%(message)s", stream=sys.stdout)
logging.getLogger("azure").setLevel(logging.WARNING)

SITES = {
    "hrl": "RWS01_MONIBAS_0271hrl0063ra",
    "hrr": "RWS01_MONIBAS_0271hrr0063ra",
    "vwd": "RWS01_MONIBAS_0270vwd0063ra",
    "vwa": "RWS01_MONIBAS_0270vwa0063ra",
}
CONTAINER = "ndw"

# Why both a database AND a bucket?
# - Database (PostgreSQL): parsed, structured readings with a primary key and
#   indexes. It gives fast time-range queries and joins (air quality vs traffic)
#   for the dashboard and the model. It cannot cheaply keep every raw file.
# - Bucket (Blob Storage): the raw, untouched source data. It is cheap, durable
#   and works as an audit trail. The database cannot give us the original files.
# In six months, when I retrain the model, I may want new features or find a bug
# in my parser. With the raw files in the bucket I can re-parse everything and
# rebuild the training set. With only the database, that history is lost.


def parse_site(config_bytes, measured_bytes, site_id):
    """Return (rows, timestamp) for one site. Raw values are kept as they are,
    including speed = -1 (bad data), which is handled in summarise()."""
    index_map = build_index_map(io.BytesIO(config_bytes), site_id)
    kinds = {}
    for idx, info in index_map.items():
        if info["vehicle"] == "anyVehicle":
            if info["type"] == "trafficFlow":
                kinds[idx] = "flow"
            elif info["type"] == "trafficSpeed":
                kinds[idx] = "speed"

    readings = extract_measurements(io.BytesIO(measured_bytes), site_id)
    readings = [r for r in readings if r["index"] in kinds]
    if not readings:
        return [], None
    ts = pd.to_datetime(readings[0]["timestamp"], utc=True)
    rows = [
        {
            "site_id": site_id,
            "timestamp": ts.isoformat(),
            "lane_index": r["index"],
            "metric": kinds[r["index"]],
            "value": float(r["value"]),
        }
        for r in readings
    ]
    return rows, ts


def summarise(rows):
    """Total flow (sum over lanes), average valid speed, and bad speed count.
    speed = -1 means 'no measurement', so it is never used as a real speed."""
    flows = [r["value"] for r in rows if r["metric"] == "flow"]
    speeds = [r["value"] for r in rows if r["metric"] == "speed"]
    good = [s for s in speeds if s > 0]
    bad = len(speeds) - len(good)
    avg_speed = sum(good) / len(good) if good else None
    return sum(flows), avg_speed, bad


def save_summary(label, ts, total_flow, avg_speed, bad_count):
    conn = psycopg2.connect(os.environ["DATABASE_URL"])
    try:
        with conn, conn.cursor() as cur:
            cur.execute("""
                CREATE TABLE IF NOT EXISTS traffic_readings (
                    site_label       VARCHAR(10) NOT NULL,
                    timestamp        TIMESTAMPTZ NOT NULL,
                    total_flow       FLOAT,
                    avg_speed        FLOAT,
                    bad_speed_count  INT DEFAULT 0,
                    PRIMARY KEY (site_label, timestamp)
                )""")
            cur.execute(
                """INSERT INTO traffic_readings
                   (site_label, timestamp, total_flow, avg_speed, bad_speed_count)
                   VALUES (%s, %s, %s, %s, %s) ON CONFLICT DO NOTHING""",
                (label, ts.isoformat(), total_flow, avg_speed, bad_count),
            )
    finally:
        conn.close()


def main():
    logging.info(json.dumps({"event": "ndw_download_start"}))
    config_bytes = download_and_decompress(CONFIG_URL).read()
    measured_bytes = download_and_decompress(MEASURED_URL).read()

    # On the VM: managed identity (no secret stored). Locally: falls back to the key in .env.
    if os.environ.get("AZURE_STORAGE_CONNECTION_STRING"):
        service = BlobServiceClient.from_connection_string(os.environ["AZURE_STORAGE_CONNECTION_STRING"])
    else:
        service = BlobServiceClient(
            account_url=f"https://{os.environ['STORAGE_ACCOUNT']}.blob.core.windows.net",
            credential=DefaultAzureCredential())
    container = service.get_container_client(CONTAINER)

    for label, site_id in SITES.items():
        rows, ts = parse_site(config_bytes, measured_bytes, site_id)
        if not rows:
            logging.warning(json.dumps({"event": "ndw_no_data", "location": site_id}))
            continue
        # File name uses the MEASUREMENT time from the data, not today's date.
        path = f"{ts:%Y-%m-%d}/{ts:%H-%M}-{label}.csv"
        local = os.path.join("ndw", path)
        os.makedirs(os.path.dirname(local), exist_ok=True)
        pd.DataFrame(rows).to_csv(local, index=False)
        with open(local, "rb") as f:
            container.upload_blob(name=path, data=f, overwrite=True)

        total_flow, avg_speed, bad = summarise(rows)
        if bad:
            logging.warning(json.dumps({
                "event": "DATA_QUALITY_ERROR", "source": "NDW",
                "location": site_id, "field": "speed", "value": -1, "count": bad}))
        if bad:
            quality.record_bad("ndw", bad)   # speed=-1 is never stored as a speed
        try:
            if not os.environ.get("REDIS_HOST"):
                raise KeyError  # no broker configured
            redis.Redis(host=os.environ.get("REDIS_HOST", "redis"), port=6379,
                        socket_connect_timeout=2).rpush("readings", json.dumps({
                "source": "NDW", "site": label, "timestamp": ts.isoformat(),
                "total_flow": total_flow, "avg_speed": avg_speed}))
        except KeyError:
            pass
        except redis.RedisError as e:
            logging.warning(json.dumps({"event": "redis_unavailable", "error": str(e)}))
        save_summary(label, ts, total_flow, avg_speed, bad)
        logging.info(json.dumps({
            "event": "fetch_success", "source": "NDW", "site": label,
            "total_flow": total_flow, "avg_speed": avg_speed,
            "timestamp": ts.isoformat()}))


if __name__ == "__main__":
    main()
