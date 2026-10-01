import pandas as pd

import quality
from ingest_air import build_rows
from ingest_traffic import summarise


def test_stale_or_null_luchtmeetnet_is_kept_and_flagged():
    df = pd.DataFrame({
        "component": ["NO2"] * 5,
        "value": [10.0, 20.0, 20.0, 20.0, None],
        "timestamp": [f"2024-01-15T0{h}:00:00Z" for h in range(5)],
    })
    rows = build_rows(df)
    assert len(rows) == 5                       # nothing dropped
    flags = [r[4] for r in rows]
    assert flags == [False, False, False, True, True]   # 3rd identical and null are flagged
    assert rows[4][3] is None                   # null stored as NULL


def test_ndw_speed_minus_one_not_stored_and_counted():
    rows = [
        {"metric": "flow", "value": 600.0},
        {"metric": "speed", "value": -1.0},
        {"metric": "flow", "value": 300.0},
        {"metric": "speed", "value": 90.0},
    ]
    total_flow, avg_speed, bad = summarise(rows)
    assert bad == 1
    assert avg_speed == 90.0                    # -1 never reaches the stored speed
    before = quality.bad_data_count["ndw"]
    quality.record_bad("ndw", bad)
    assert quality.bad_data_count["ndw"] == before + 1
