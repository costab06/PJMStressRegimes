"""Neighboring balance authority stress propagation features."""

from __future__ import annotations

import pandas as pd


def neighbor_stress_index(
    df: pd.DataFrame,
    neighbor_bas: list[str],
    stress_col: str = "demand_z",
    weights: dict[str, float] | None = None,
) -> pd.Series:
    """Weighted mean stress score across neighboring BAs.

    Args:
        df: Wide DataFrame with one column per BA named f"{ba}_{stress_col}".
        neighbor_bas: List of neighboring BA codes.
        stress_col: Suffix of the per-BA stress column.
        weights: Optional dict of {ba: weight}; uniform if None.

    Returns:
        Series of composite neighbor stress scores in [0, 1] (sigmoid-scaled).
    """
    cols = [f"{ba}_{stress_col}" for ba in neighbor_bas if f"{ba}_{stress_col}" in df.columns]
    if not cols:
        raise ValueError(f"None of the expected neighbor columns found in df")

    if weights:
        w = pd.Series({c: weights.get(c.split("_")[0], 1.0) for c in cols})
        w = w / w.sum()
        raw = df[cols].mul(w.values, axis=1).sum(axis=1)
    else:
        raw = df[cols].mean(axis=1)

    # Sigmoid scale to [0, 1]
    return 1 / (1 + (-raw).apply(lambda x: __import__("math").exp(x)))
