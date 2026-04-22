"""Module 0: dataset intake and manifest generation."""

from __future__ import annotations

from pathlib import Path

import pandas as pd


def build_manifest(data_root: str | Path) -> tuple[pd.DataFrame, pd.DataFrame]:
    root = Path(data_root)
    ds_paths = list(root.glob("**/sub-*_task-*_meg.ds"))
    event_paths = list(root.glob("**/sub-*_task-auditory_events.tsv"))
    t1_paths = list(root.glob("**/sub-*_T1w.nii"))

    subjects = sorted({p.name.split("_")[0].replace("sub-", "") for p in ds_paths})
    subjects_df = pd.DataFrame({"subject": subjects})

    rows: list[dict[str, str]] = []
    for p in ds_paths:
        rows.append({"kind": "meg_ds", "path": str(p)})
    for p in event_paths:
        rows.append({"kind": "events_tsv", "path": str(p)})
    for p in t1_paths:
        rows.append({"kind": "t1_nii", "path": str(p)})
    files_df = pd.DataFrame(rows)
    return subjects_df, files_df
