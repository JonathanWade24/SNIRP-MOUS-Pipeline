"""Module 6B frequency-domain detector."""

from __future__ import annotations

import numpy as np

from .base import WaveDetector, register


@register("fft2d")
class FFT2DDetector(WaveDetector):
    name = "fft2d"
    required_inputs = {"phase"}

    def detect(self, features):
        phase = np.asarray(features["phase"])
        if phase.ndim != 3:
            raise ValueError("FFT2DDetector expects phase with shape (epochs, channels, times).")
        # Approximate 2D surface by reshaping channels into closest square grid.
        n_epochs, n_channels, n_times = phase.shape
        side = int(np.sqrt(n_channels))
        if side * side == 0:
            raise ValueError("Invalid channel dimension for FFT2DDetector.")
        keep = side * side
        phase_sq = phase[:, :keep, :].reshape(n_epochs, side, side, n_times)
        peak_mag = []
        for ep in range(n_epochs):
            snap = phase_sq[ep, :, :, n_times // 2]
            spec = np.fft.fftshift(np.fft.fft2(snap))
            peak_mag.append(float(np.max(np.abs(spec))))
        peak_mag_arr = np.asarray(peak_mag)
        return {
            "peak_fft_magnitude_per_epoch": peak_mag_arr,
            "peak_fft_magnitude_mean": float(np.mean(peak_mag_arr)),
        }
