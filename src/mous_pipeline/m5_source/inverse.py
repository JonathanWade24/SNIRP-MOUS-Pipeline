"""Module 5 source reconstruction inverse solver."""

from __future__ import annotations

import mne


def compute_inverse(epochs, forward, cfg):
    """Compute source estimates using an LCMV beamformer."""
    source_cfg = getattr(cfg, "source", None)
    reg = float(getattr(source_cfg, "reg", 0.05)) if source_cfg else 0.05
    pick_ori = str(getattr(source_cfg, "pick_ori", "max-power")) if source_cfg else "max-power"
    weight_norm = str(getattr(source_cfg, "weight_norm", "unit-noise-gain")) if source_cfg else "unit-noise-gain"

    noise_cov = mne.compute_covariance(epochs, tmin=None, tmax=0.0, method="shrunk", rank=None, verbose="WARNING")
    data_cov = mne.compute_covariance(epochs, tmin=0.0, tmax=None, method="shrunk", rank=None, verbose="WARNING")
    filters = mne.beamformer.make_lcmv(
        epochs.info,
        forward,
        data_cov=data_cov,
        noise_cov=noise_cov,
        reg=reg,
        pick_ori=pick_ori,
        weight_norm=weight_norm,
        rank="info",
    )
    return mne.beamformer.apply_lcmv_epochs(epochs, filters, return_generator=False)
