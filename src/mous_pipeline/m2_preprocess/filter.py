"""Module 2 filtering/resampling helpers."""

from __future__ import annotations

import mne

from ..config import PipelineConfig


def apply_notch_and_resample(raw: mne.io.BaseRaw, cfg: PipelineConfig) -> mne.io.BaseRaw:
    raw.notch_filter(freqs=cfg.preprocess.notch_freqs, picks="meg", verbose="WARNING")
    raw.resample(cfg.preprocess.resample_hz, npad="auto")
    return raw


def apply_band(raw: mne.io.BaseRaw, low: float, high: float) -> mne.io.BaseRaw:
    raw.filter(low, high, picks="meg", method="fir", fir_window="hamming", verbose="WARNING")
    return raw
