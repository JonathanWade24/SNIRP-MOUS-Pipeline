"""Module 1: event parsing and event-array construction."""

from __future__ import annotations

import numpy as np
import pandas as pd


CONDITION_IDS = {"ZINNEN": 1, "WOORDEN": 2}


def parse_events(tsv_path: str, *, strict: bool = True) -> pd.DataFrame:
    df = pd.read_csv(tsv_path, sep="\t").sort_values("onset").reset_index(drop=True)
    required_cols = {"onset", "sample", "type", "value"}
    missing = required_cols.difference(df.columns)
    if missing:
        raise ValueError(f"Events TSV missing required columns: {sorted(missing)}")

    conds: list[str | None] = []
    current: str | None = None
    seen_conditions: set[str] = set()
    for _, row in df.iterrows():
        if row["type"] == "Picture" and row["value"] in CONDITION_IDS:
            current = row["value"]
            seen_conditions.add(current)
        conds.append(current)
    df["condition"] = conds

    if strict and seen_conditions != set(CONDITION_IDS):
        raise ValueError(
            "Did not observe both required condition block markers. "
            f"Seen: {sorted(seen_conditions)}; expected: {sorted(CONDITION_IDS)}"
        )

    audio = df[(df["type"] == "Nothing") & (df["value"].str.contains("Audio onset", na=False))].copy()
    dropped_precondition = int(audio["condition"].isna().sum())
    audio = audio.dropna(subset=["condition"]).reset_index(drop=True)
    if strict and dropped_precondition > 0:
        raise ValueError(
            f"Detected {dropped_precondition} Audio onset rows before first condition marker. "
            "Fix event/block ordering before running contrasts."
        )

    unknown_conditions = set(audio["condition"].unique()).difference(CONDITION_IDS)
    if strict and unknown_conditions:
        raise ValueError(f"Audio onset rows contain unknown conditions: {sorted(unknown_conditions)}")

    return audio[["onset", "sample", "condition"]]


def make_events_array(trials: pd.DataFrame, sfreq: float) -> np.ndarray:
    return np.column_stack(
        [
            (trials["onset"] * sfreq).round().astype(int),
            np.zeros(len(trials), dtype=int),
            trials["condition"].map(CONDITION_IDS).astype(int),
        ]
    )
