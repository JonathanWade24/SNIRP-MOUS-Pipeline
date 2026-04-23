"""Module 6D rotational detector."""

from __future__ import annotations

import numpy as np

from .base import WaveDetector, register


@register("rotational")
class RotationalDetector(WaveDetector):
    name = "rotational"
    required_inputs = {"phase"}

    def detect(self, features):
        phase = np.asarray(features["phase"])
        if phase.ndim != 3:
            raise ValueError("RotationalDetector expects phase with shape (epochs, channels, times).")
        n_epochs, n_channels, n_times = phase.shape
        side = int(np.sqrt(n_channels))
        keep = side * side
        phase_sq = phase[:, :keep, :].reshape(n_epochs, side, side, n_times)
        curls = []
        for ep in range(n_epochs):
            snap = phase_sq[ep, :, :, n_times // 2]
            gy, gx = np.gradient(snap)
            curl_z = np.gradient(gy, axis=1) - np.gradient(gx, axis=0)
            curls.append(float(np.mean(np.abs(curl_z))))
        curls_arr = np.asarray(curls)
        return {
            "rotational_index_per_epoch": curls_arr,
            "rotational_index_mean": float(np.mean(curls_arr)),
        }
