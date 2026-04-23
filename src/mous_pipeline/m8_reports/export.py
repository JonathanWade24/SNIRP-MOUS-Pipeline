"""Export subject artifacts for downstream Quarto/R reporting."""

from __future__ import annotations

import json
from pathlib import Path

import numpy as np
import pandas as pd

from ..io import stage_output_dir


def export_subject_payload(
    subject: str,
    cfg,
    *,
    dirs_z: np.ndarray,
    dirs_w: np.ndarray,
    dirs_r: np.ndarray,
    sliding_t: np.ndarray,
    sliding_dci_z: np.ndarray,
    metrics: dict,
) -> Path:
    out_dir = stage_output_dir(cfg, subject, "m8_reports") / "exports"
    out_dir.mkdir(parents=True, exist_ok=True)

    directions_df = pd.DataFrame(
        {
            "epoch": np.arange(len(dirs_z) + len(dirs_w) + len(dirs_r)),
            "condition": (["ZINNEN"] * len(dirs_z)) + (["WOORDEN"] * len(dirs_w)) + (["REST"] * len(dirs_r)),
            "direction_rad": np.concatenate([dirs_z, dirs_w, dirs_r]),
        }
    )
    directions_df.to_csv(out_dir / f"{subject}_directions.csv", index=False)

    sliding_df = pd.DataFrame(
        {
            "time_s": sliding_t,
            "dci": sliding_dci_z,
            "condition": "ZINNEN",
        }
    )
    sliding_df.to_csv(out_dir / f"{subject}_sliding_dci.csv", index=False)

    (out_dir / f"{subject}_metrics.json").write_text(json.dumps(metrics, indent=2))
    return out_dir
