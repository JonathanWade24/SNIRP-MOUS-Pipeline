"""Module 4 spectral summaries."""

from __future__ import annotations

import numpy as np

from ..io import stage_output_dir


def psd(epochs, subject: str, cfg, band_name: str, fmin: float, fmax: float) -> tuple[np.ndarray, np.ndarray]:
    spec = epochs.compute_psd(method="welch", fmin=fmin, fmax=fmax, picks="meg", verbose="WARNING")
    data = spec.get_data()
    freqs = spec.freqs
    out_dir = stage_output_dir(cfg, subject, "m4_features")
    np.savez(out_dir / f"{subject}_{band_name}_psd.npz", psd=data, freqs=freqs)
    return data, freqs
