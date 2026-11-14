"""Episode-aware partitions and descriptive evaluation safeguards."""
from __future__ import annotations
from collections.abc import Iterator
import numpy as np
import pandas as pd


def leave_one_episode_out(episode_ids) -> Iterator[tuple[np.ndarray,np.ndarray,str]]:
    ids = pd.Series(episode_ids, dtype="string")
    if ids.isna().any() or ids.empty:
        raise ValueError("Each row must belong to an episode")
    unique = list(dict.fromkeys(ids.tolist()))
    if len(unique) < 2:
        raise ValueError("At least two independent episodes are required")
    for held_out in unique:
        test = np.flatnonzero(ids.to_numpy() == held_out)
        train = np.flatnonzero(ids.to_numpy() != held_out)
        if not len(train) or not len(test):
            raise ValueError("Invalid episode partition")
        yield train, test, held_out


def episode_inventory(catalog: pd.DataFrame) -> pd.DataFrame:
    """Count independent episodes, not action rows; no model gate implied."""
    return (catalog[["episode_id","severity"]].drop_duplicates()
        .groupby("severity").size().rename("independent_episodes").reset_index())
