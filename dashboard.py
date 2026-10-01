"""AirBreda: GET /site/{id}, GET /history, GET /health, GET / (HTML dashboard)."""
import json
import logging
import os
import sys
from pathlib import Path

import psycopg2
from dotenv import load_dotenv
from fastapi import FastAPI, HTTPException
from fastapi.responses import HTMLResponse

import predict as predictor

load_dotenv()
logging.basicConfig(level=logging.INFO, format="%(message)s", stream=sys.stdout)
app = FastAPI(title="AirBreda")

SITES = ["hrl", "hrr", "vwd", "vwa"]
STATION = "NL10240"
MIN_SAMPLES = 3          # same rule idea as training: a site-hour needs several snapshots
HERE = Path(__file__).parent
PAGE = (HERE / "index.html").read_text()
try:
    MODEL_INFO = json.loads((HERE / "model_info.json").read_text())
except Exception:
    MODEL_INFO = {}

# Where each field in /site/{id} comes from:
# - no2_ug_m3, timestamp: latest non-null NO2 row in sensor_readings (PostgreSQL).
#   One real station (NL10240) covers all four sites at this interchange.
# - intensity_veh_per_hr: HOURLY MEAN of that site's total_flow in traffic_readings,
#   for the newest hour where all four sites have >= 3 snapshots. This matches how
#   the model was trained (hourly means), which avoids training-serving skew.
# - no2_ug_m3_predicted, no2_exceedance_risk: predict() from predict.py, fed with the
#   TOTAL of the four hourly means plus that hour of day.
# If predict() raises, the route does NOT fail: it returns the real NO2 and intensity
# with the prediction fields set to null, and logs an ERROR. A real reading is more
# useful than a 500.


def db():
    return psycopg2.connect(os.environ["DATABASE_URL"], connect_timeout=5)


def hourly_traffic(cur, hours):
    cur.execute("""SELECT date_trunc('hour', timestamp), site_label, avg(total_flow), count(*)
                   FROM traffic_readings
                   WHERE timestamp > now() - make_interval(hours => %s)
                   GROUP BY 1, 2 ORDER BY 1""", (hours,))
    out = {}
    for h, s, f, n in cur.fetchall():
        out.setdefault(h, {})[s] = (float(f), n)
    return out


def pick_hour(hourly):
    for h in sorted(hourly, reverse=True):
        d = hourly[h]
        if all(s in d and d[s][1] >= MIN_SAMPLES for s in SITES):
            return h
    return max(hourly) if hourly else None


@app.get("/site/{site_id}")
def site(site_id: str):
    if site_id not in SITES:
        raise HTTPException(404, f"unknown site, use one of {SITES}")
    try:
        conn = db()
        try:
            with conn.cursor() as cur:
                cur.execute("""SELECT value, timestamp FROM sensor_readings
                               WHERE station_id=%s AND component='NO2' AND value IS NOT NULL
                               ORDER BY timestamp DESC LIMIT 1""", (STATION,))
                no2 = cur.fetchone()
                hourly = hourly_traffic(cur, 6)
                cur.execute("SELECT max(timestamp) FROM traffic_readings")
                last_traffic = cur.fetchone()[0]
        finally:
            conn.close()
    except psycopg2.Error as e:
        logging.error(json.dumps({"event": "db_error", "error": str(e)}))
        raise HTTPException(503, "database unavailable")
    hour = pick_hour(hourly)
    if no2 is None or hour is None or site_id not in hourly[hour]:
        raise HTTPException(503, "no data yet")
    flow, samples = hourly[hour][site_id]
    out = {
        "site_id": site_id,
        "no2_ug_m3": no2[0],
        "intensity_veh_per_hr": round(flow, 1),
        "samples": samples,
        "traffic_hour": hour.isoformat(),
        "no2_ug_m3_predicted": None,
        "no2_exceedance_risk": None,
        "timestamp": no2[1].isoformat(),
        "traffic_timestamp": last_traffic.isoformat(),
    }
    try:
        total = sum(f for f, _ in hourly[hour].values())
        out.update(predictor.predict(total, hour.hour))
    except Exception as e:  # degrade gracefully, see comment above
        logging.error(json.dumps({"event": "predict_failed", "error": str(e)}))
    return out


@app.get("/history")
def history():
    """Last 24 hours: hourly NO2 and total hourly traffic (for the charts)."""
    try:
        conn = db()
        try:
            with conn.cursor() as cur:
                cur.execute("""SELECT timestamp, value FROM sensor_readings
                               WHERE station_id=%s AND component='NO2'
                               AND timestamp > now() - interval '24 hours' ORDER BY timestamp""", (STATION,))
                no2 = {t: v for t, v in cur.fetchall()}
                traffic = hourly_traffic(cur, 24)
        finally:
            conn.close()
    except psycopg2.Error as e:
        logging.error(json.dumps({"event": "db_error", "error": str(e)}))
        raise HTTPException(503, "database unavailable")
    hours = sorted(set(no2) | set(traffic))
    rows = []
    for h in hours:
        d = traffic.get(h, {})
        total = round(sum(f for f, _ in d.values())) if len(d) == len(SITES) else None
        pred = None
        if total is not None:
            try:
                pred = round(predictor.predict(total, h.hour)["no2_ug_m3_predicted"], 1)
            except Exception:
                pred = None
        rows.append({"hour": h.isoformat(), "no2": no2.get(h), "traffic": total,
                     "pred": pred, "sites": {k: round(v[0]) for k, v in d.items()}})
    return {"hours": rows, "model": MODEL_INFO, "threshold": predictor.THRESHOLD}


@app.get("/health")
def health():
    """Last data per source plus bad-data counts over the last 24 hours.
    The ingestion containers run once and exit (cron), so health is derived from
    what they wrote to the database."""
    try:
        conn = db()
        try:
            with conn.cursor() as cur:
                cur.execute("SELECT max(timestamp) FROM sensor_readings WHERE station_id=%s", (STATION,))
                air_last = cur.fetchone()[0]
                cur.execute("""SELECT count(*) FROM sensor_readings WHERE is_flagged
                               AND timestamp > now() - interval '24 hours'""")
                air_bad = cur.fetchone()[0]
                cur.execute("SELECT max(timestamp) FROM traffic_readings")
                ndw_last = cur.fetchone()[0]
                cur.execute("""SELECT coalesce(sum(bad_speed_count),0) FROM traffic_readings
                               WHERE timestamp > now() - interval '24 hours'""")
                ndw_bad = int(cur.fetchone()[0])
        finally:
            conn.close()
    except psycopg2.Error as e:
        logging.error(json.dumps({"event": "db_error", "error": str(e)}))
        raise HTTPException(503, "database unavailable")
    iso = lambda d: d.isoformat() if d else None
    body = {"status": "ok", "window_hours": 24, "sources": [
        {"source": "Luchtmeetnet", "last_successful_fetch": iso(air_last), "bad_data_count": air_bad},
        {"source": "NDW", "last_successful_fetch": iso(ndw_last), "bad_data_count": ndw_bad},
    ]}
    body["luchtmeetnet"] = body["sources"][0]
    body["ndw"] = body["sources"][1]
    return body


@app.get("/", response_class=HTMLResponse)
def index():
    return PAGE
