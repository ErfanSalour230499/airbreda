"""Shared data-quality helpers for both ingestion scripts."""
import json
import logging

THRESHOLD = 10
bad_data_count = {"luchtmeetnet": 0, "ndw": 0}
_alerted = set()


def record_bad(source, n=1):
    """Increment the per-source bad data counter. Log ONE error when it passes the threshold."""
    bad_data_count[source] += n
    if bad_data_count[source] > THRESHOLD and source not in _alerted:
        _alerted.add(source)
        logging.error(json.dumps({
            "event": "BAD_DATA_THRESHOLD_EXCEEDED",
            "source": source, "count": bad_data_count[source]}))


def flag_readings(values):
    """values: list of floats/None in CHRONOLOGICAL order.
    A reading is flagged if it is null, or equal to the previous 2 readings
    (3+ identical consecutive hours = stale / interpolated)."""
    flags = []
    for i, v in enumerate(values):
        null = v is None or v != v
        stale = i >= 2 and v is not None and v == values[i - 1] == values[i - 2]
        flags.append(bool(null or stale))
    return flags
