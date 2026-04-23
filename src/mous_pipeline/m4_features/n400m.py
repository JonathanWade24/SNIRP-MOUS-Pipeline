"""Trial-wise N400m proxy extraction."""

from __future__ import annotations

import numpy as np

from ..io import stage_output_dir


def n400m_amplitude(
    epochs,
    subject: str,
    cfg,
    trial_meta,
    *,
    sensor_prefix: str = "MLT",
    tmin: float = 0.3,
    tmax: float = 0.5,
) -> np.ndarray:
    """
    Compute trial-wise N400m proxy over left temporal sensors.

    For CTF naming, channels beginning with MLT* are used as a pragmatic
    left-temporal ROI proxy.
    """
    picks = [idx for idx, name in enumerate(epochs.ch_names) if name.startswith(sensor_prefix)]
    if not picks:
        picks = None
    data = epochs.copy().crop(tmin=tmin, tmax=tmax).get_data(picks=picks)
    # Mean over channels and time. Sign-inverted so more negative deflections
    # produce larger positive amplitudes (N400-like effect size convention).
    n400m = -data.mean(axis=(1, 2))

    out_dir = stage_output_dir(cfg, subject, "m4_features")
    np.savez(
        out_dir / f"{subject}_n400m.npz",
        n400m=n400m,
        trial_id=trial_meta["trial_id"].to_numpy(dtype=int),
        condition=trial_meta["condition"].to_numpy(dtype=str),
        block_id=trial_meta["block_id"].to_numpy(dtype=int),
        pos_in_block=trial_meta["pos_in_block"].to_numpy(dtype=int),
    )
    return n400m
