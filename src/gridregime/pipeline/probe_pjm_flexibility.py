"""Probe PJM Data Miner metadata and a tiny historical sample, locally.

Run:
  export PJM_API_KEY='your-production-key'
  python -m gridregime.pipeline.probe_pjm_flexibility

Never paste a key into GitHub, command arguments, URLs, or output.
This script only requests metadata and at most 3 rows per feed; it does
not infer operational reserve margins or publish downloaded data.
"""
from __future__ import annotations

import json
import os
import time
from datetime import datetime, timezone

import requests

from gridregime.pipeline.fit_temperature_regimes import ROOT

OUT = ROOT / "results/pjm_flexibility_probe_v1"
BASE = "https://api.pjm.com/api/v1"
FEEDS = (
    "gen_outages_by_type",
    "day_gen_capacity",
    "ops_sum_prev_period",
    "ops_sum_frcst_peak_rto",
    "operational_reserves",
)
# 6 calls/minute non-member limit; use conservative spacing.
WAIT_SECONDS = 12


def request(session, url, params=None):
    try:
        r = session.get(url, params=params, timeout=45)
        if r.status_code == 429:
            raise RuntimeError("PJM rate limit reached; stop and retry later")
        return r
    except requests.RequestException as e:
        return {"transport_error": type(e).__name__, "message": str(e)[:300]}


def describe(response):
    if isinstance(response, dict):
        return response
    info = {"status": response.status_code,
            "content_type": response.headers.get("content-type", ""),
            "bytes": len(response.content)}
    if response.status_code != 200:
        info["error_excerpt"] = response.text[:250]
        return info
    try:
        payload = response.json()
    except ValueError:
        info["body_excerpt"] = response.text[:200]
        return info
    if isinstance(payload, dict):
        info["top_level_keys"] = list(payload)[:30]
        if "fields" in payload and isinstance(payload["fields"], list):
            info["fields"] = payload["fields"][:100]
        if "items" in payload and isinstance(payload["items"], list):
            info["item_count"] = len(payload["items"])
            info["sample_rows"] = payload["items"][:3]
        if "totalRows" in payload:
            info["totalRows"] = payload["totalRows"]
        if "links" in payload:
            info["links_present"] = True
    elif isinstance(payload, list):
        info["item_count"] = len(payload)
        info["sample_rows"] = payload[:3]
    return info


def run():
    key = os.getenv("PJM_API_KEY", "").strip()
    if not key:
        raise SystemExit(
            "PJM_API_KEY is not set. Obtain a production Data Miner API key "
            "and set it locally; do not commit or paste it.")
    OUT.mkdir(parents=True, exist_ok=True)
    results = {"retrieved_utc": datetime.now(timezone.utc).isoformat(),
               "base": BASE, "feeds": {}}
    with requests.Session() as session:
        session.headers.update({
            "Ocp-Apim-Subscription-Key": key,
            "Accept": "application/json",
        })
        for index, feed in enumerate(FEEDS):
            if index:
                time.sleep(WAIT_SECONDS)
            metadata = request(session, f"{BASE}/{feed}/metadata")
            record = {"metadata": describe(metadata)}
            # Only query sample if metadata succeeds, to avoid unnecessary calls.
            if not isinstance(metadata, dict) and metadata.status_code == 200:
                time.sleep(WAIT_SECONDS)
                sample = request(session, f"{BASE}/{feed}",
                                 params={"rowCount": 3, "startRow": 1})
                record["sample"] = describe(sample)
            results["feeds"][feed] = record
            print(f"{feed}: metadata={record['metadata'].get('status', 'error')}, "
                  f"sample={record.get('sample', {}).get('status', 'not attempted')}",
                  flush=True)
    # Metadata and small samples may be subject to PJM redistribution limits:
    # keep results local, outside Git; don't print full records by default.
    destination = OUT / "feed_probe.json"
    destination.write_text(json.dumps(results, indent=2, default=str) + "\n")
    print(f"Saved local diagnostic: {destination}")
    print("Do not commit the diagnostic file or share licensed PJM raw data.")
    return results


if __name__ == "__main__":
    run()
