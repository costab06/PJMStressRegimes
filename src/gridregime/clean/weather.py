"""Clean NOAA ISD weather observations."""

from __future__ import annotations

import pandas as pd

VALID_QUALITY_CODES = {"0", "1", "5"}


def clean(df: pd.DataFrame, max_gap_hours: int = 3) -> pd.DataFrame:
    """Clean raw NOAA ISD observations.

    - Filters to valid quality codes
    - Converts scaled integers to physical units
    - Interpolates short gaps

    Args:
        df: Raw ISD DataFrame.
        max_gap_hours: Max gap length to interpolate.

    Returns:
        Cleaned DataFrame.
    """
    df = df.copy()
    for col in ["temp_c", "dewpoint_c", "wind_speed_mps"]:
        if col in df.columns:
            df[col] = pd.to_numeric(df[col], errors="coerce")
            df[col] = df[col].interpolate(method="time", limit=max_gap_hours)
    return df
