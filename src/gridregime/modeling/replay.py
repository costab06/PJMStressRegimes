"""Local descriptive replay of frozen-v1 artifacts, with fail-closed coverage checks."""
from __future__ import annotations
import argparse
import json
from pathlib import Path
import pandas as pd
from .datasets import load_feature_sequence, load_episode_catalog, load_feature_snapshot
from .runner import run_descriptive_hmm_experiment


def prepare_episodes(*, feature_dir: str | Path, events_csv: str | Path, min_hours: int = 4):
    """Load real immutable feature reports, assigning only fully covered episodes.

    Reports from different source revisions at the same observation hour are
    rejected, not silently selected. Episode windows are taken from the catalog;
    overlapping event rows within one episode are consolidated by min/max.
    """
    root = Path(feature_dir)
    paths = sorted(root.rglob("features-*.json")) if root.exists() else []
    if not paths:
        raise ValueError(f"No frozen-v1 feature reports under {root}; cannot run real replay")
    by_hour = {}
    for path in paths:
        p = load_feature_snapshot(path)
        if p["ba"] != "PJM":
            continue
        t = pd.Timestamp(p["as_of"])
        if t.tzinfo is None:
            raise ValueError("Feature observation time lacks timezone")
        t = t.tz_convert("UTC")
        key = t.isoformat()
        if key in by_hour:
            prior = by_hour[key][1]
            if prior != p:
                raise ValueError(f"Conflicting feature revisions at {key}")
        else:
            by_hour[key] = (path, p)
    catalog = load_episode_catalog(events_csv)
    episodes = []
    report = []
    for episode_id, group in catalog.groupby("episode_id", sort=True):
        start = pd.to_datetime(group["window_start"], utc=True).min().ceil("h")
        end = pd.to_datetime(group["event_end"], utc=True).max().floor("h")
        expected = pd.date_range(start, end, freq="h", tz="UTC")
        available = [by_hour.get(t.isoformat()) for t in expected]
        missing = sum(item is None for item in available)
        entry = {"episode_id":str(episode_id),"severity":str(group["severity"].iloc[0]),
                 "expected_hours":len(expected),"missing_hours":missing,
                 "status":"incomplete"}
        if len(expected) < min_hours:
            entry["status"] = "too_short"
        elif not missing:
            paths = [item[0] for item in available]
            episodes.append(load_feature_sequence(paths,episode_id=str(episode_id)))
            entry["status"] = "ready"
        report.append(entry)
    return episodes, pd.DataFrame(report)


def main(argv=None):
    parser = argparse.ArgumentParser(description="Descriptive frozen-v1 historical HMM replay")
    parser.add_argument("--feature-dir",required=True)
    parser.add_argument("--events-csv",default="metadata/events.csv")
    parser.add_argument("--output-dir",required=True)
    parser.add_argument("--code-revision",required=True)
    parser.add_argument("--n-components",type=int,default=3)
    args = parser.parse_args(argv)
    episodes, coverage = prepare_episodes(feature_dir=args.feature_dir,events_csv=args.events_csv)
    destination = Path(args.output_dir)
    destination.mkdir(parents=True,exist_ok=True)
    coverage.to_csv(destination / "episode_coverage.csv",index=False)
    print(coverage.to_string(index=False))
    if len(episodes) < 3:
        raise SystemExit("Insufficient fully covered independent episodes for descriptive LOEO HMM; no model run")
    result = run_descriptive_hmm_experiment(episodes,output_dir=destination,
        code_revision=args.code_revision,n_components=args.n_components)
    print(json.dumps(result,indent=2,default=str))

if __name__ == "__main__":
    main()
