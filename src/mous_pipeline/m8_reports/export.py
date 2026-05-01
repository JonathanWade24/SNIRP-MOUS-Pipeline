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
    trials_df: pd.DataFrame | None = None,
    joined_df: pd.DataFrame | None = None,
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
    if trials_df is not None and not trials_df.empty:
        trials_df.to_csv(out_dir / f"{subject}_trials.csv", index=False)
    if joined_df is not None and not joined_df.empty:
        joined_df.to_csv(out_dir / f"{subject}_trials_joined.csv", index=False)

    qc_row = {
        "subject_id": subject,
        "n_trials_zinnen": metrics.get("n_zinnen"),
        "n_trials_woorden": metrics.get("n_woorden"),
        "mean_FD": metrics.get("m10_mean_fd"),
        "n_motion_outliers": metrics.get("m10_n_motion_outliers"),
        "ICA_components_removed": metrics.get("m2_ica_n_components_removed"),
        "DCI_zinnen": metrics.get("dci_zinnen"),
        "DCI_rest": metrics.get("dci_rest"),
        "p_task_vs_rest": metrics.get("p_task_vs_rest"),
        "prestim_beta_t": metrics.get("aim1_prestim_auc"),
        "N400m_r": metrics.get("aim1_n400m_zinnen_vs_woorden_t"),
        "MTG_spearman_r": (
            (metrics.get("m11_coupling") or {}).get("zinnen_prestim_beta_vs_mtg", {}) or {}
        ).get("r")
        if isinstance(metrics.get("m11_coupling"), dict)
        else None,
    }
    pd.DataFrame([qc_row]).to_csv(out_dir / f"{subject}_qc_summary.csv", index=False)

    # Optional m5 exports (when source reconstruction ran and wrote arrays).
    m5_dir = stage_output_dir(cfg, subject, "m5_source")
    source_dirs_path = m5_dir / f"sub-{subject}_source_dirs.npy"
    source_dci_path = m5_dir / f"sub-{subject}_source_dci.npy"
    if source_dirs_path.exists():
        source_dirs = np.load(source_dirs_path)
        pd.DataFrame(
            {
                "epoch": np.arange(len(source_dirs)),
                "source_direction_rad": source_dirs,
            }
        ).to_csv(out_dir / f"{subject}_source_directions.csv", index=False)
    if source_dci_path.exists():
        source_dci = np.load(source_dci_path)
        pd.DataFrame(
            {
                "epoch": np.arange(len(source_dci)),
                "source_dci": source_dci,
            }
        ).to_csv(out_dir / f"{subject}_source_dci.csv", index=False)

    roi_ts_path = m5_dir / f"sub-{subject}_source_roi_ts.npz"
    roi_labels_path = m5_dir / f"sub-{subject}_source_roi_labels.json"
    if roi_ts_path.exists() and roi_labels_path.exists():
        roi_matrix = np.load(roi_ts_path)["roi_matrix"]  # (n_epochs, n_labels, n_times)
        roi_labels = json.loads(roi_labels_path.read_text())
        rows = [
            {"epoch": ep, "label": label, "mean_beta": float(np.mean(roi_matrix[ep, li, :]))}
            for ep in range(roi_matrix.shape[0])
            for li, label in enumerate(roi_labels)
        ]
        pd.DataFrame(rows).to_csv(out_dir / f"{subject}_source_roi_summary.csv", index=False)

    return out_dir
