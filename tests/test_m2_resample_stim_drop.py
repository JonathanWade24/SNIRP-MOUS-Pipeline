"""Regression test: apply_notch_and_resample must drop stim channels before
resampling so that MNE's "resampling of stim channels caused event info to
become unreliable" RuntimeWarning is never raised.

Background
----------
MNE warns when integer stim-pulse edges are resampled because the pulse
boundaries can alias at the new sample rate, corrupting event arrays derived
from find_events().  The MOUS pipeline builds event arrays from trial-metadata
TSV (make_events_array), so stim channels are never consulted downstream.
The correct fix is to drop stim channels before resampling rather than
suppressing the warning.
"""

from __future__ import annotations

import sys
import warnings
from pathlib import Path

import numpy as np
import pytest

# Ensure the local src/ is used even when a worktree editable install exists.
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

import mne

from mous_pipeline.m2_preprocess.filter import apply_notch_and_resample


def _make_raw_with_stim(sfreq: float = 1200.0, duration: float = 10.0) -> mne.io.RawArray:
    """Return a synthetic Raw with 3 MEG + 2 stim channels.

    duration=10s ensures the notch filter kernel fits within the signal length
    and avoids a separate "filter_length longer than signal" warning.
    """
    n_times = int(sfreq * duration)
    rng = np.random.default_rng(0)
    meg_data = rng.standard_normal((3, n_times)) * 1e-13
    stim_data = np.zeros((2, n_times))
    stim_data[0, int(sfreq * 0.5)] = 1
    stim_data[0, int(sfreq * 1.0)] = 2

    data = np.vstack([meg_data, stim_data])
    ch_names = ["MEG001", "MEG002", "MEG003", "UPPT001", "UPPT002"]
    ch_types = ["mag", "mag", "mag", "stim", "stim"]
    info = mne.create_info(ch_names=ch_names, sfreq=sfreq, ch_types=ch_types)
    return mne.io.RawArray(data, info, verbose=False)


class _FakePreprocessCfg:
    notch_freqs = [50.0]
    resample_hz = 300.0


class _FakeCfg:
    preprocess = _FakePreprocessCfg()


def test_no_stim_channels_after_resample():
    raw = _make_raw_with_stim()
    assert "stim" in [mne.channel_type(raw.info, i) for i in range(raw.info["nchan"])], \
        "precondition: raw must have stim channels"

    result = apply_notch_and_resample(raw, _FakeCfg())

    remaining_types = {mne.channel_type(result.info, i) for i in range(result.info["nchan"])}
    assert "stim" not in remaining_types, \
        "stim channels should be dropped before resampling"


def test_no_stim_resample_warning():
    """No 'resampling of stim channels' RuntimeWarning should be emitted."""
    raw = _make_raw_with_stim()
    with warnings.catch_warnings(record=True) as caught:
        warnings.simplefilter("always")
        apply_notch_and_resample(raw, _FakeCfg())
    stim_warnings = [
        w for w in caught
        if issubclass(w.category, RuntimeWarning)
        and "stim" in str(w.message).lower()
    ]
    assert not stim_warnings, (
        f"Expected no stim-channel resample warnings, got: {stim_warnings}"
    )


def test_meg_channels_preserved_and_resampled():
    raw = _make_raw_with_stim(sfreq=1200.0)
    result = apply_notch_and_resample(raw, _FakeCfg())

    meg_idx = mne.pick_types(result.info, meg=True)
    assert len(meg_idx) == 3, "all 3 MEG channels should remain"
    assert result.info["sfreq"] == pytest.approx(300.0), "should be resampled to 300 Hz"


def test_no_stim_raw_is_unaffected_by_drop():
    """If there are no stim channels, the function should not raise."""
    raw = _make_raw_with_stim()
    raw.drop_channels(["UPPT001", "UPPT002"])
    result = apply_notch_and_resample(raw, _FakeCfg())
    assert result.info["sfreq"] == pytest.approx(300.0)

