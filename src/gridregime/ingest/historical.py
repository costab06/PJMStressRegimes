"""Load archived historical event data (2003 blackout, 2014 polar vortex)."""

from __future__ import annotations

from pathlib import Path

import pandas as pd

RAW_PATH = Path("data/raw/historical")

EVENTS = {
    "2003_blackout": RAW_PATH / "2003_blackout",
    "2014_polar_vortex": RAW_PATH / "2014_polar_vortex",
}


def load_event(event_name: str) -> dict[str, pd.DataFrame]:
    """Load all available data files for a named historical event.

    Args:
        event_name: Key from EVENTS dict (e.g. "2003_blackout").

    Returns:
        Dict mapping filename stem to DataFrame.
    """
    event_dir = EVENTS[event_name]
    result = {}
    for path in sorted(event_dir.glob("*.parquet")):
        result[path.stem] = pd.read_parquet(path)
    for path in sorted(event_dir.glob("*.csv")):
        if path.stem not in result:
            result[path.stem] = pd.read_csv(path, parse_dates=True)
    return result
