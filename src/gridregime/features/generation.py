"""Generation mix and availability features."""

from __future__ import annotations

import pandas as pd

FUEL_TYPES = ["coal", "gas", "nuclear", "hydro", "wind", "solar", "oil", "other"]


def fuel_mix_fractions(df: pd.DataFrame) -> pd.DataFrame:
    """Compute fractional generation share for each fuel type."""
    fuel_cols = [c for c in df.columns if c.startswith("gen_") and c.split("_")[1] in FUEL_TYPES]
    total = df[fuel_cols].sum(axis=1)
    fractions = df[fuel_cols].div(total, axis=0)
    fractions.columns = [c.replace("gen_", "frac_") for c in fuel_cols]
    return fractions


def thermal_fraction(df: pd.DataFrame) -> pd.Series:
    """Combined thermal (coal + gas + oil) generation fraction."""
    thermal = ["gen_coal", "gen_gas", "gen_oil"]
    available = [c for c in thermal if c in df.columns]
    total = df[[c for c in df.columns if c.startswith("gen_")]].sum(axis=1)
    return df[available].sum(axis=1) / total
