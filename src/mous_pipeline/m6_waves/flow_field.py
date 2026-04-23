"""Module 6C flow-field detector."""

from __future__ import annotations

import numpy as np

from .base import WaveDetector, register


@register("flow_field")
class FlowFieldDetector(WaveDetector):
    name = "flow_field"
    required_inputs = {"phase"}

    def detect(self, features):
        phase = np.asarray(features["phase"])
        if phase.ndim != 3:
            raise ValueError("FlowFieldDetector expects phase with shape (epochs, channels, times).")
        n_epochs, n_channels, n_times = phase.shape
        side = int(np.sqrt(n_channels))
        keep = side * side
        phase_sq = phase[:, :keep, :].reshape(n_epochs, side, side, n_times)
        flow_mags = []
        for ep in range(n_epochs):
            # Finite-difference surrogate for optical flow magnitude.
            delta = np.diff(phase_sq[ep], axis=-1)
            gy, gx = np.gradient(delta[:, :, n_times // 4], axis=(0, 1))
            flow_mags.append(float(np.mean(np.sqrt(gx**2 + gy**2))))
        flow_arr = np.asarray(flow_mags)
        return {
            "flow_magnitude_per_epoch": flow_arr,
            "flow_magnitude_mean": float(np.mean(flow_arr)),
        }
