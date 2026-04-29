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
    def __init__(self, *args, **kwargs):
        pass

    def fit(self, *args, **kwargs):
        return self

    def transform(self, img):
        return np.ones((1, 3))


class _DummyMasker1D:
    def __init__(self, *args, **kwargs):
        pass

    def fit(self, *args, **kwargs):
        return self

    def transform(self, img):
        return np.ones(3)


class _SpyModel:
    fit_calls: list[dict] = []
    contrast_calls: list[str] = []

    def __init__(self, *args, **kwargs):
        pass

    def fit(self, bold_nii, events=None, confounds=None):
        _SpyModel.fit_calls.append(
            {
                "bold_nii": bold_nii,
                "events": events.copy() if events is not None else None,
                "confounds": confounds,
            }
        )
        return self

    def compute_contrast(self, contrast_def, output_type="effect_size"):
        _SpyModel.contrast_calls.append(str(contrast_def))
        return "dummy_img"


class _SpyMasker:
    fit_args: list[tuple] = []

    def __init__(self, *args, **kwargs):
        pass

    def fit(self, *args, **kwargs):
        _SpyMasker.fit_args.append(args)
        return self

    def transform(self, img):
        return np.ones((1, 1))


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


def test_trialwise_betas_accepts_1d_masker_output(monkeypatch):
    """Regression: tolerate 1D ROI signal arrays from masker stubs/backends."""
    monkeypatch.setattr("mous_pipeline.m10_fmri.glm.FirstLevelModel", _DummyModel)
    monkeypatch.setattr("mous_pipeline.m10_fmri.glm.NiftiLabelsMasker", _DummyMasker1D)
    monkeypatch.setattr(
        "mous_pipeline.m10_fmri.glm._atlas_and_label",
        lambda *a, **k: ("dummy_atlas", ["L_TE1a"], "L_TE1a"),
    )
    events = pd.DataFrame({"onset": [0.0, 6.0], "duration": [6.0, 6.0]})
    out = trialwise_betas("dummy_bold.nii.gz", events, tr=2.0)
    assert list(out.columns) == ["trial_id", "mtg_beta"]
    assert len(out) == 2


def test_trialwise_betas_uses_per_trial_lss_fit(monkeypatch):
    _SpyModel.fit_calls = []
    _SpyModel.contrast_calls = []
    monkeypatch.setattr("mous_pipeline.m10_fmri.glm.FirstLevelModel", _SpyModel)
    monkeypatch.setattr("mous_pipeline.m10_fmri.glm.NiftiLabelsMasker", _SpyMasker)
    monkeypatch.setattr(
        "mous_pipeline.m10_fmri.glm._atlas_and_label",
        lambda *a, **k: ("dummy_atlas", ["L_TE1a"], "L_TE1a"),
    )
    events = pd.DataFrame({"onset": [0.0, 6.0, 12.0], "duration": [6.0, 6.0, 6.0]})

    out = trialwise_betas("dummy_bold.nii.gz", events, tr=2.0)

    assert len(out) == 3
    assert len(_SpyModel.fit_calls) == len(events)
    assert _SpyModel.contrast_calls == ["target_trial", "target_trial", "target_trial"]
    for idx, fit_call in enumerate(_SpyModel.fit_calls):
        design = fit_call["events"]
        assert list(design["trial_type"]) == ["target_trial" if j == idx else "other_trials" for j in range(len(events))]


def test_trialwise_betas_masker_fit_uses_bold_image(monkeypatch):
    _SpyMasker.fit_args = []
    monkeypatch.setattr("mous_pipeline.m10_fmri.glm.FirstLevelModel", _DummyModel)
    monkeypatch.setattr("mous_pipeline.m10_fmri.glm.NiftiLabelsMasker", _SpyMasker)
    monkeypatch.setattr(
        "mous_pipeline.m10_fmri.glm._atlas_and_label",
        lambda *a, **k: ("dummy_atlas", ["L_TE1a"], "L_TE1a"),
    )
    events = pd.DataFrame({"onset": [0.0, 6.0], "duration": [6.0, 6.0]})

    trialwise_betas("dummy_bold.nii.gz", events, tr=2.0)

    assert _SpyMasker.fit_args
    assert _SpyMasker.fit_args[0] == ("dummy_bold.nii.gz",)
