"""Module 1 QA checks."""

from __future__ import annotations

import pandas as pd


def event_summary(trials: pd.DataFrame) -> dict[str, int]:
    counts = trials["condition"].value_counts().to_dict()
    counts["TOTAL"] = len(trials)
    return counts


def validate_min_trials(trials: pd.DataFrame, minimum: int = 50) -> None:
    counts = trials["condition"].value_counts()
    for cond, n in counts.items():
        if n < minimum:
            raise ValueError(f"Condition {cond} has only {n} trials < {minimum}")
