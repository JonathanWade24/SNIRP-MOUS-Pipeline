"""Module 6E cross-frequency detector."""

from __future__ import annotations

import numpy as np
from tensorpac import Pac

from .base import WaveDetector, register


@register("cfc")
class CFCDetector(WaveDetector):
    name = "cfc"
    required_inputs = {"phase", "amplitude"}

    def detect(self, features):
        phase = np.asarray(features["phase"])
        amplitude = np.asarray(features["amplitude"])
        if phase.ndim != 3 or amplitude.ndim != 3:
            raise ValueError("CFCDetector expects phase/amplitude arrays with shape (epochs, channels, times).")

        # Use one representative channel per epoch for a fast, robust summary.
        phase_1d = phase[:, 0, :]
        amp_1d = amplitude[:, 0, :]
        pac = Pac(idpac=(2, 0, 0), f_pha=(4, 8), f_amp=(30, 80), dcomplex="wavelet")
        mi = []
        for ep in range(phase_1d.shape[0]):
            p = phase_1d[ep][None, None, :]
            a = amp_1d[ep][None, None, :]
            val = pac.fit(p, a)
            mi.append(float(np.nanmean(val)))
        mi_arr = np.asarray(mi)
        return {
            "mi_per_epoch": mi_arr,
            "mi_mean": float(np.nanmean(mi_arr)),
        }
