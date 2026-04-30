"""Compare real wave metrics to confound null simulations."""

from __future__ import annotations

import numpy as np


def confound_null_dci(
    real_dci: np.ndarray,
    null_dci: np.ndarray,
    *,
    z_threshold: float = 1.645,
) -> dict[str, float | bool]:
    """Return real-vs-null DCI summary with z-score and threshold decision."""
    real_mean = float(np.mean(real_dci))
    null_mean = float(np.mean(null_dci))
    null_std = float(np.std(null_dci, ddof=1)) if len(null_dci) > 1 else 0.0
    z = 0.0 if null_std == 0.0 else float((real_mean - null_mean) / null_std)
    ci_low = float(np.quantile(null_dci, 0.025))
    ci_hi = float(np.quantile(null_dci, 0.975))
    return {
        "real_dci": real_mean,
        "null_dci_mean": null_mean,
        "null_dci_ci95_low": ci_low,
        "null_dci_ci95_high": ci_hi,
        "z": z,
        "z_threshold": float(z_threshold),
        "wave_detected": bool(z >= float(z_threshold)),
    }
