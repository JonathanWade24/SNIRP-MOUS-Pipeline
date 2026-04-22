"""Module 4 Hilbert analytic signal extraction."""

from __future__ import annotations

from pathlib import Path

import numpy as np
from scipy.signal import hilbert

from ..io import stage_output_dir


def analytic_signal(epochs, subject: str, cfg, band_name: str) -> dict[str, np.ndarray]:
    data = epochs.get_data(picks="meg")
    analytic = hilbert(data, axis=-1)
    out = {
        "analytic": analytic,
        "phase": np.angle(analytic),
        "amplitude": np.abs(analytic),
    }
    out_dir = stage_output_dir(cfg, subject, "m4_features")
    np.savez(out_dir / f"{subject}_{band_name}_analytic.npz", **out)
    return out
