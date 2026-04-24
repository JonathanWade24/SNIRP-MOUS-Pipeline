"""Stub tests for trialwise_betas that run without real fMRI data.

These tests monkeypatch nilearn internals so the GLM logic can be exercised
locally.  Nilearn itself must be importable (skipped otherwise).

Columns expected from trialwise_betas:  ["trial_id", "mtg_beta"]
(the old stub incorrectly expected "contrast_name" which was never a real col).
"""

import numpy as np
import pandas as pd
import pytest

nilearn = pytest.importorskip("nilearn")

from mous_pipeline.m10_fmri.glm import trialwise_betas


# ── minimal stubs ──────────────────────────────────────────────────────────────

class _DummyModel:
    def __init__(self, *args, **kwargs):
        self.fitted = False
        self._events: pd.DataFrame | None = None

    def fit(self, bold_nii, events=None, confounds=None):
        self.fitted = True
        self.bold_nii = bold_nii
        self._events = events
        return self

    def compute_contrast(self, contrast_def, output_type="effect_size"):
        return "dummy_img"


class _DummyMasker:
    def fit(self, *args, **kwargs):
        return self

    def transform(self, img):
        return np.ones((1, 3))


# ── tests ──────────────────────────────────────────────────────────────────────

def test_trialwise_betas_output_columns(monkeypatch):
    """trialwise_betas must return exactly ['trial_id', 'mtg_beta']."""
    monkeypatch.setattr("mous_pipeline.m10_fmri.glm.FirstLevelModel", _DummyModel)
    monkeypatch.setattr("mous_pipeline.m10_fmri.glm.NiftiLabelsMasker", _DummyMasker)
    monkeypatch.setattr(
        "mous_pipeline.m10_fmri.glm._atlas_and_label",
        lambda *a, **k: ("dummy_atlas", ["L_TE1a", "R_TE1a"], "L_TE1a"),
    )
    events = pd.DataFrame({"onset": [0.0, 6.0, 12.0], "duration": [6.0, 6.0, 6.0]})
    out = trialwise_betas("dummy_bold.nii.gz", events, tr=2.0, confounds=None)
    assert list(out.columns) == ["trial_id", "mtg_beta"]
    assert len(out) == 3


def test_trialwise_betas_trial_id_sequential(monkeypatch):
    """trial_id must be 0-based sequential when events_df has no trial_id col."""
    monkeypatch.setattr("mous_pipeline.m10_fmri.glm.FirstLevelModel", _DummyModel)
    monkeypatch.setattr("mous_pipeline.m10_fmri.glm.NiftiLabelsMasker", _DummyMasker)
    monkeypatch.setattr(
        "mous_pipeline.m10_fmri.glm._atlas_and_label",
        lambda *a, **k: ("dummy_atlas", ["L_TE1a"], "L_TE1a"),
    )
    events = pd.DataFrame({"onset": [0.0, 6.0], "duration": [6.0, 6.0]})
    out = trialwise_betas("dummy_bold.nii.gz", events, tr=2.0)
    assert list(out["trial_id"]) == [0, 1]


def test_trialwise_betas_preserves_trial_id_from_input(monkeypatch):
    """trial_id col in events_df must be passed through to output."""
    monkeypatch.setattr("mous_pipeline.m10_fmri.glm.FirstLevelModel", _DummyModel)
    monkeypatch.setattr("mous_pipeline.m10_fmri.glm.NiftiLabelsMasker", _DummyMasker)
    monkeypatch.setattr(
        "mous_pipeline.m10_fmri.glm._atlas_and_label",
        lambda *a, **k: ("dummy_atlas", ["L_TE1a"], "L_TE1a"),
    )
    events = pd.DataFrame(
        {"trial_id": [10, 20, 30], "onset": [0.0, 6.0, 12.0], "duration": [6.0, 6.0, 6.0]}
    )
    out = trialwise_betas("dummy_bold.nii.gz", events, tr=2.0)
    assert list(out["trial_id"]) == [10, 20, 30]


def test_trialwise_betas_accepts_trial_meta_dataframe(monkeypatch):
    """Regression: must accept a DataFrame shaped like make_events_metadata output.

    The runner passes trial_df (which has onset, trial_id, condition, block_id,
    pos_in_block) — extra columns must not crash the function.
    """
    monkeypatch.setattr("mous_pipeline.m10_fmri.glm.FirstLevelModel", _DummyModel)
    monkeypatch.setattr("mous_pipeline.m10_fmri.glm.NiftiLabelsMasker", _DummyMasker)
    monkeypatch.setattr(
        "mous_pipeline.m10_fmri.glm._atlas_and_label",
        lambda *a, **k: ("dummy_atlas", ["L_TE1a"], "L_TE1a"),
    )
    # Shape matching make_events_metadata() output (now includes onset)
    events = pd.DataFrame(
        {
            "trial_id": [0, 1, 2],
            "onset": [0.0, 6.0, 12.0],
            "condition": ["ZINNEN", "WOORDEN", "ZINNEN"],
            "block_id": [0, 1, 2],
            "pos_in_block": [0, 0, 1],
        }
    )
    out = trialwise_betas("dummy_bold.nii.gz", events, tr=2.0)
    assert list(out.columns) == ["trial_id", "mtg_beta"]
    assert len(out) == 3
