"""Trial-wise N400m proxy extraction."""

from __future__ import annotations

import logging
import warnings

import numpy as np

from ..io import stage_output_dir

LOGGER = logging.getLogger(__name__)


def n400m_amplitude(
    epochs,
    subject: str,
    cfg,
    trial_meta,
    *,
    sensor_prefix: str = "MLT",
    tmin: float = 0.3,
    tmax: float = 0.5,
    topography_weights: np.ndarray | None = None,
) -> np.ndarray:
    """
    Compute trial-wise N400m proxy over a reproducible left-temporal sensor ROI.

    Channel selection is deterministic via ``sensor_prefix`` under CTF naming
    (e.g., ``MLT*``). If no channels match, all channels are used. The default
    window is 300-500 ms post word onset (sensor space) and the summary
    collapses selected channels and time, then inverts sign so larger values
    represent stronger N400-like negativity.

    ``topography_weights`` optionally applies a fixed channel weighting before
    temporal averaging. The provided vector must match the selected channel
    count exactly.
    """
    picks = [idx for idx, name in enumerate(epochs.ch_names) if name.startswith(sensor_prefix)]
    if not picks:
        picks = list(range(len(epochs.ch_names)))
    n_channels_used = len(picks)
    LOGGER.info("N400m extraction uses %d channels (prefix=%s).", n_channels_used, sensor_prefix)
    if n_channels_used < 5:
        warnings.warn(
            f"N400m extraction selected only {n_channels_used} channel(s); ROI may be too sparse.",
            RuntimeWarning,
            stacklevel=2,
        )
    data = epochs.copy().crop(tmin=tmin, tmax=tmax).get_data(picks=picks)
    if topography_weights is not None:
        weights = np.asarray(topography_weights, dtype=float)
        if weights.ndim != 1 or weights.shape[0] != n_channels_used:
            raise ValueError(
                "topography_weights must be 1D with one entry per selected channel "
                f"(expected {n_channels_used}, got shape {weights.shape})."
            )
        weight_sum = float(np.sum(weights))
        if weight_sum == 0.0:
            raise ValueError("topography_weights sum must be non-zero.")
        weighted = np.tensordot(data, weights, axes=([1], [0])) / weight_sum
        n400m = -weighted.mean(axis=1)
    else:
        # Mean over channels and time. Sign-inverted so more negative deflections
        # produce larger positive amplitudes (N400-like effect size convention).
        n400m = -data.mean(axis=(1, 2))

    if len(trial_meta) != len(n400m):
        raise ValueError(
            "trial_meta length does not match epoch count for n400m_amplitude. "
            "Align metadata to kept epochs (for example, with epochs.selection) before calling."
        )

    out_dir = stage_output_dir(cfg, subject, "m4_features")
    np.savez(
        out_dir / f"{subject}_n400m.npz",
        n400m=n400m,
        n_channels_used=np.asarray(n_channels_used, dtype=int),
        trial_id=trial_meta["trial_id"].to_numpy(dtype=int),
        condition=trial_meta["condition"].to_numpy(dtype=str),
        block_id=trial_meta["block_id"].to_numpy(dtype=int),
        pos_in_block=trial_meta["pos_in_block"].to_numpy(dtype=int),
    )
    return n400m
