"""Trial-wise pre-stimulus beta summaries."""

from __future__ import annotations

import numpy as np
from scipy.signal import welch

from ..io import stage_output_dir


def prestim_beta_power(
    epochs,
    subject: str,
    cfg,
    trial_meta,
    *,
    picks: str = "meg",
    tmin: float = -0.5,
    tmax: float = 0.0,
    fmin: float = 13.0,
    fmax: float = 30.0,
) -> np.ndarray:
    """Compute trial-wise beta power over a pre-stimulus window."""
    crop = epochs.copy().crop(tmin=tmin, tmax=tmax)
    data = crop.get_data(picks=picks)  # (n_trials, n_channels, n_times)
    sfreq = float(crop.info["sfreq"])

    power = np.empty(data.shape[0], dtype=float)
    for trial_idx in range(data.shape[0]):
        trial = data[trial_idx]
        freqs, psd = welch(trial, fs=sfreq, axis=-1, nperseg=min(256, trial.shape[-1]))
        beta_mask = (freqs >= fmin) & (freqs <= fmax)
        power[trial_idx] = float(np.nanmean(psd[:, beta_mask]))

    out_dir = stage_output_dir(cfg, subject, "m4_features")
    np.savez(
        out_dir / f"{subject}_prestim_beta.npz",
        prestim_beta=power,
        trial_id=trial_meta["trial_id"].to_numpy(dtype=int),
        condition=trial_meta["condition"].to_numpy(dtype=str),
        block_id=trial_meta["block_id"].to_numpy(dtype=int),
        pos_in_block=trial_meta["pos_in_block"].to_numpy(dtype=int),
    )
    return power
