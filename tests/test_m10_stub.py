import pandas as pd
import pytest

nilearn = pytest.importorskip("nilearn")

from mous_pipeline.m10_fmri.glm import trialwise_betas


class _DummyModel:
    def __init__(self, *args, **kwargs):
        self.fitted = False

    def fit(self, bold_nii, events=None, confounds=None):
        self.fitted = True
        self.bold_nii = bold_nii
        self.events = events
        return self


def test_trialwise_betas_builds_trial_contrasts(monkeypatch):
    monkeypatch.setattr("mous_pipeline.m10_fmri.glm.FirstLevelModel", _DummyModel)
    events = pd.DataFrame({"onset": [0.0, 6.0, 12.0], "duration": [6.0, 6.0, 6.0]})
    out = trialwise_betas("dummy_bold.nii.gz", events, tr=2.0, confounds=None)
    assert list(out.columns) == ["trial_id", "contrast_name"]
    assert len(out) == 3
    assert out.iloc[0]["contrast_name"] == "trial_0"
