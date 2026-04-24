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
    block_ids: list[int | None] = []
    block_positions: list[int | None] = []
    current: str | None = None
    current_block_id = -1
    current_pos = 0
    seen_conditions: set[str] = set()
    for _, row in df.iterrows():
        if row["type"] == "Picture" and row["value"] in CONDITION_IDS:
            current = row["value"]
            current_block_id += 1
            current_pos = 0
            seen_conditions.add(current)
        conds.append(current)
        if current is None:
            block_ids.append(None)
            block_positions.append(None)
        else:
            block_ids.append(current_block_id)
            block_positions.append(current_pos)
            if row["type"] == "Nothing" and isinstance(row["value"], str) and "Audio onset" in row["value"]:
                current_pos += 1
    df["condition"] = conds
    df["block_id"] = block_ids
    df["pos_in_block"] = block_positions

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

    return audio[["onset", "sample", "condition", "block_id", "pos_in_block"]]


def make_events_array(trials: pd.DataFrame, sfreq: float) -> np.ndarray:
    return np.column_stack(
        [
            (trials["onset"] * sfreq).round().astype(int),
            np.zeros(len(trials), dtype=int),
            trials["condition"].map(CONDITION_IDS).astype(int),
        ]
    )


def make_events_metadata(trials: pd.DataFrame) -> pd.DataFrame:
    """Return event-aligned trial metadata for epoch-level analyses."""
    return trials.reset_index(drop=True).assign(trial_id=lambda d: np.arange(len(d), dtype=int))[
        ["trial_id", "onset", "condition", "block_id", "pos_in_block"]
    ]
