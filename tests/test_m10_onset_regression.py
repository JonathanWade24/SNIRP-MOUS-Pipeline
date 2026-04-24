"""Regression tests for m10 onset-column bug.

Root cause: make_events_metadata() was dropping the 'onset' column, but
_lss_design() in m10_fmri/glm.py requires it.  The KeyError was silently
caught by runner.py, recorded as m10_error="'onset'", and m11 was skipped
with "No joined MEG-fMRI trial table."

Fix: make_events_metadata() now includes 'onset' in its output columns.
"""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from mous_pipeline.m1_events.parse import make_events_metadata, parse_events


def _make_trials(n: int = 6) -> pd.DataFrame:
    """Minimal trials DataFrame like parse_events() returns."""
    conditions = ["ZINNEN", "WOORDEN"]
    return pd.DataFrame(
        {
            "onset": np.arange(n, dtype=float) * 6.0,
            "sample": np.arange(n, dtype=int) * 300,
            "condition": [conditions[i % 2] for i in range(n)],
            "block_id": list(range(n)),
            "pos_in_block": list(range(n)),
        }
    )


# ── unit: make_events_metadata preserves onset ────────────────────────────────

def test_make_events_metadata_includes_onset():
    """Regression: onset must survive make_events_metadata so m10 can use it."""
    trials = _make_trials(6)
    meta = make_events_metadata(trials)
    assert "onset" in meta.columns, (
        "make_events_metadata dropped 'onset' — _lss_design will KeyError"
    )


def test_make_events_metadata_columns():
    trials = _make_trials(6)
    meta = make_events_metadata(trials)
    expected = {"trial_id", "onset", "condition", "block_id", "pos_in_block"}
    assert expected.issubset(set(meta.columns))


def test_make_events_metadata_trial_id_sequential():
    trials = _make_trials(4)
    meta = make_events_metadata(trials)
    assert list(meta["trial_id"]) == [0, 1, 2, 3]


def test_make_events_metadata_onset_values_preserved():
    trials = _make_trials(3)
    meta = make_events_metadata(trials)
    np.testing.assert_array_equal(meta["onset"].to_numpy(), [0.0, 6.0, 12.0])


# ── nilearn-dependent tests (skipped locally, run on Neurodesk) ───────────────

try:
    import nilearn as _nilearn  # noqa: F401
    from mous_pipeline.m10_fmri.glm import _lss_design
    _has_nilearn = True
except ModuleNotFoundError:
    _has_nilearn = False

_skip_no_nilearn = pytest.mark.skipif(not _has_nilearn, reason="nilearn not installed")


@_skip_no_nilearn
def test_lss_design_accepts_meta_df_with_onset():
    """_lss_design must work with the DataFrame that make_events_metadata returns."""
    trials = _make_trials(3)
    meta = make_events_metadata(trials)
    design = _lss_design(meta)
    # n*n rows: 3 trials × 3 design rows each
    assert len(design) == 9
    assert set(design.columns) >= {"onset", "duration", "trial_type"}


@_skip_no_nilearn
def test_lss_design_trial_type_labelling():
    trials = _make_trials(3)
    meta = make_events_metadata(trials)
    design = _lss_design(meta)
    focal = design[design["trial_type"].str.startswith("trial_")]
    other = design[design["trial_type"] == "other_trials"]
    assert len(focal) == 3   # one focal row per trial
    assert len(other) == 6   # remaining rows marked "other_trials"


@_skip_no_nilearn
def test_parse_to_lss_design_pipeline(events_tsv_path):
    """End-to-end: real events TSV → metadata → LSS design without KeyError."""
    trials = parse_events(str(events_tsv_path))
    meta = make_events_metadata(trials)
    assert "onset" in meta.columns
    design = _lss_design(meta)
    assert len(design) == len(meta) ** 2
    assert (design["onset"] >= 0).all()
