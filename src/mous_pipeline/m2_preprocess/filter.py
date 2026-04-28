"""Module 2 filtering/resampling helpers."""

from __future__ import annotations

import mne

from ..config import PipelineConfig


def apply_notch_and_resample(raw: mne.io.BaseRaw, cfg: PipelineConfig) -> mne.io.BaseRaw:
    raw.notch_filter(freqs=cfg.preprocess.notch_freqs, picks="meg", verbose="WARNING")

    # Drop stim/trigger channels before resampling.
    #
    # MNE warns that resampling stim channels makes event timing unreliable:
    # integer pulse edges can alias at the new sample rate, corrupting event
    # arrays derived from stim-channel edge detection.
    #
    # This pipeline builds all event arrays from the trial-metadata TSV
    # (see m1_events.parse.make_events_array), so stim channels are never
    # read downstream.  Dropping them here silences the warning correctly
    # rather than just suppressing it, and slightly reduces memory usage.
    stim_idx = mne.pick_types(raw.info, meg=False, stim=True, exclude=[])
    if len(stim_idx):
        stim_names = [raw.ch_names[i] for i in stim_idx]
        raw.drop_channels(stim_names)

    raw.resample(cfg.preprocess.resample_hz, npad="auto")
    return raw


def apply_band(raw: mne.io.BaseRaw, low: float, high: float) -> mne.io.BaseRaw:
    raw.filter(low, high, picks="meg", method="fir", fir_window="hamming", verbose="WARNING")
    return raw
