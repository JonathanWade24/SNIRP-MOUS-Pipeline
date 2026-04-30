"""Trial-wise pre-stimulus beta summaries."""

from __future__ import annotations

import warnings

import numpy as np
from scipy.signal import welch
from scipy.stats import ks_2samp

from ..io import stage_output_dir


def prestim_beta_power(
    epochs,
    subject: str,
    cfg,
    trial_meta,
    *,
    sensor_prefixes: tuple[str, ...] = ("MLF", "MLP", "MLT"),
    tmin: float = -0.8,
    tmax: float = 0.0,
    fmin: float = 13.0,
    fmax: float = 30.0,
) -> np.ndarray:
    """Compute trial-wise beta power over a pre-stimulus window."""
    picks = [idx for idx, name in enumerate(epochs.ch_names) if any(name.startswith(prefix) for prefix in sensor_prefixes)]
    if not picks:
        picks = "meg"
    crop = epochs.copy().crop(tmin=tmin, tmax=tmax)
    data = crop.get_data(picks=picks)  # (n_trials, n_channels, n_times)
    sfreq = float(crop.info["sfreq"])

    power = np.empty(data.shape[0], dtype=float)
    channel_beta = np.empty((data.shape[0], data.shape[1]), dtype=float)
    for trial_idx in range(data.shape[0]):
        trial = data[trial_idx]
        freqs, psd = welch(trial, fs=sfreq, axis=-1, nperseg=min(256, trial.shape[-1]))
        beta_mask = (freqs >= fmin) & (freqs <= fmax)
        beta_channel = np.nanmean(psd[:, beta_mask], axis=1)
        channel_beta[trial_idx] = beta_channel
        power[trial_idx] = float(np.nanmean(beta_channel))

    if len(trial_meta) != len(power):
        raise ValueError(
            "trial_meta length does not match epoch count for prestim_beta_power. "
            "Align metadata to kept epochs (for example, with epochs.selection) before calling."
        )

    conditions = trial_meta["condition"].to_numpy(dtype=str)
    cond_names = np.unique(conditions)
    cond_means: list[float] = []
    cond_stds: list[float] = []
    cond_counts: list[int] = []
    for cond_name in cond_names:
        cond_vals = power[conditions == cond_name]
        cond_means.append(float(np.mean(cond_vals)) if len(cond_vals) else np.nan)
        cond_stds.append(float(np.std(cond_vals, ddof=1)) if len(cond_vals) > 1 else 0.0)
        cond_counts.append(int(len(cond_vals)))

    ks_p = np.nan
    if {"ZINNEN", "WOORDEN"}.issubset(set(cond_names)):
        z = power[conditions == "ZINNEN"]
        w = power[conditions == "WOORDEN"]
        if len(z) > 1 and len(w) > 1:
            ks_p = float(ks_2samp(z, w, alternative="two-sided", method="auto").pvalue)

    per_channel_mean = np.mean(channel_beta, axis=0)
    contrast_map = np.zeros(channel_beta.shape[1], dtype=float)
    t_map = np.zeros(channel_beta.shape[1], dtype=float)
    if {"ZINNEN", "WOORDEN"}.issubset(set(cond_names)):
        z_ch = channel_beta[conditions == "ZINNEN"]
        w_ch = channel_beta[conditions == "WOORDEN"]
        if len(z_ch) and len(w_ch):
            contrast_map = np.mean(z_ch, axis=0) - np.mean(w_ch, axis=0)
            z_var = np.var(z_ch, axis=0, ddof=1) if len(z_ch) > 1 else np.zeros(z_ch.shape[1], dtype=float)
            w_var = np.var(w_ch, axis=0, ddof=1) if len(w_ch) > 1 else np.zeros(w_ch.shape[1], dtype=float)
            se = np.sqrt((z_var / max(1, len(z_ch))) + (w_var / max(1, len(w_ch))))
            valid = se > 0.0
            t_map[valid] = contrast_map[valid] / se[valid]

    global_var = float(np.var(power, ddof=1)) if len(power) > 1 else 0.0
    near_zero_var_eps = 1e-10
    near_zero_variance = bool(global_var <= near_zero_var_eps)
    if near_zero_variance:
        warnings.warn(
            "Prestim beta distribution is near-degenerate (variance <= 1e-10).",
            RuntimeWarning,
            stacklevel=2,
        )

    out_dir = stage_output_dir(cfg, subject, "m4_features")
    np.savez(
        out_dir / f"{subject}_prestim_beta.npz",
        prestim_beta=power,
        prestim_beta_by_channel=channel_beta,
        prestim_beta_channel_mean=per_channel_mean,
        aim1_prestim_condition_contrast_topography=contrast_map,
        aim1_prestim_condition_t_map=t_map,
        trial_id=trial_meta["trial_id"].to_numpy(dtype=int),
        condition=conditions,
        block_id=trial_meta["block_id"].to_numpy(dtype=int),
        pos_in_block=trial_meta["pos_in_block"].to_numpy(dtype=int),
        condition_diag_names=cond_names.astype(str),
        condition_diag_mean=np.asarray(cond_means, dtype=float),
        condition_diag_std=np.asarray(cond_stds, dtype=float),
        condition_diag_n=np.asarray(cond_counts, dtype=int),
        condition_diag_ks_p=np.asarray(ks_p, dtype=float),
        near_zero_variance=np.asarray(near_zero_variance, dtype=bool),
        near_zero_variance_eps=np.asarray(near_zero_var_eps, dtype=float),
        prestim_beta_variance=np.asarray(global_var, dtype=float),
    )
    return power
