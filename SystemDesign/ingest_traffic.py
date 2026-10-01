"""Download NDW feeds, extract the 4 A27 sites near Breda, save one CSV per
site per measurement hour, and upload each file to Azure Blob Storage."""
import io
import os

import pandas as pd
from azure.storage.blob import BlobServiceClient
from dotenv import load_dotenv

from getTrafficReadings import (
    CONFIG_URL,
    MEASURED_URL,
    build_index_map,
    download_and_decompress,
    extract_measurements,
)

load_dotenv()

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
    including speed = -1 (bad data), which is handled later in the pipeline."""
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


def main():
    print("Downloading NDW config feed...")
    config_bytes = download_and_decompress(CONFIG_URL).read()
    print("Downloading NDW measured-data feed...")
    measured_bytes = download_and_decompress(MEASURED_URL).read()

    service = BlobServiceClient.from_connection_string(os.environ["AZURE_STORAGE_CONNECTION_STRING"])
    container = service.get_container_client(CONTAINER)

    for label, site_id in SITES.items():
        rows, ts = parse_site(config_bytes, measured_bytes, site_id)
        if not rows:
            print(f"{label}: no data found, skipping")
            continue
        # File name uses the MEASUREMENT time from the data, not today's date.
        path = f"{ts:%Y-%m-%d}/{ts:%H}-{label}.csv"
        local = os.path.join("ndw", path)
        os.makedirs(os.path.dirname(local), exist_ok=True)
        pd.DataFrame(rows).to_csv(local, index=False)
        with open(local, "rb") as f:
            container.upload_blob(name=path, data=f, overwrite=True)
        print(f"{label}: {len(rows)} rows -> {local} (uploaded to container '{CONTAINER}')")


if __name__ == "__main__":
    main()
