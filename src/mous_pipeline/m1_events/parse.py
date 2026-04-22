"""Module 1: event parsing and event-array construction."""

from __future__ import annotations

import numpy as np
import pandas as pd


CONDITION_IDS = {"ZINNEN": 1, "WOORDEN": 2}


def parse_events(tsv_path: str) -> pd.DataFrame:
    df = pd.read_csv(tsv_path, sep="\t").sort_values("onset").reset_index(drop=True)
    conds: list[str | None] = []
    current: str | None = None
    for _, row in df.iterrows():
        if row["type"] == "Picture" and row["value"] in CONDITION_IDS:
            current = row["value"]
        conds.append(current)
    df["condition"] = conds

    audio = df[(df["type"] == "Nothing") & (df["value"].str.contains("Audio onset", na=False))].copy()
    audio = audio.dropna(subset=["condition"]).reset_index(drop=True)
    return audio[["onset", "sample", "condition"]]


def make_events_array(trials: pd.DataFrame, sfreq: float) -> np.ndarray:
    return np.column_stack(
        [
            (trials["onset"] * sfreq).round().astype(int),
            np.zeros(len(trials), dtype=int),
            trials["condition"].map(CONDITION_IDS).astype(int),
        ]
    )
