"""Module 5 source ROI extraction."""

from __future__ import annotations

import mne
import numpy as np


def extract_roi_timeseries(stcs, src, labels: list[mne.Label]) -> dict[str, np.ndarray]:
    """Extract ROI time series for each label across source estimates."""
    if not labels:
        raise ValueError("At least one label is required for ROI extraction.")
    roi_values = mne.extract_label_time_course(stcs, labels, src, mode="mean", return_generator=False)
    # roi_values shape: (n_epochs, n_labels, n_times)
    return {label.name: roi_values[:, idx, :] for idx, label in enumerate(labels)}


def source_positions_xy(src) -> np.ndarray:
    """Return source-space XY coordinates for both hemispheres."""
    rr = []
    for hemi in src:
        verts = hemi["vertno"]
        rr.append(hemi["rr"][verts][:, :2])
    return np.vstack(rr)


def stcs_to_matrix(stcs) -> np.ndarray:
    """Convert SourceEstimate list to (epochs, vertices, times) matrix."""
    return np.stack([stc.data for stc in stcs], axis=0)
