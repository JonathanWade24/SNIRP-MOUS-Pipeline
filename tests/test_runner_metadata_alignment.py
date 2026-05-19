from __future__ import annotations

import numpy as np
import pandas as pd

from mous_pipeline.config import PipelineConfig
from mous_pipeline.m9_orchestration.runner import run_subject


class _DummyRaw:
    def apply_gradient_compensation(self, *_args, **_kwargs):
        return self

    def copy(self):
        return self


class _DummyEpochs:
    info = {}

    def __init__(self, n_epochs: int):
        self.n_epochs = n_epochs

    def __len__(self) -> int:
        return self.n_epochs

    def copy(self):
        return self

    def crop(self, *_args, **_kwargs):
        return self

    def get_data(self, picks=None):
        return np.ones((self.n_epochs, 3, 5), dtype=float)


def test_run_subject_m4_trial_uses_post_rejection_trial_metadata(tmp_path, monkeypatch):
    subject = "A2009"
    cfg = PipelineConfig(data_root=tmp_path / "data", derivatives_root=tmp_path / "derivatives")
    trials = pd.DataFrame({"condition": ["ZINNEN", "WOORDEN", "ZINNEN", "WOORDEN"]})
    full_meta = pd.DataFrame(
        {
            "trial_id": [100, 101, 102, 103],
            "condition": ["ZINNEN", "WOORDEN", "ZINNEN", "WOORDEN"],
            "block_id": [0, 0, 0, 0],
            "pos_in_block": [0, 1, 2, 3],
        }
    )
    kept_meta = full_meta.iloc[[1, 3]].reset_index(drop=True)
    captured: dict[str, list[int]] = {}

    monkeypatch.setattr("mous_pipeline.m9_orchestration.runner.parse_events", lambda *_a, **_k: trials)
    monkeypatch.setattr("mous_pipeline.m9_orchestration.runner.make_events_metadata", lambda *_a, **_k: full_meta)
    monkeypatch.setattr("mous_pipeline.m9_orchestration.runner.mne.io.read_raw_ctf", lambda *_a, **_k: _DummyRaw())
    monkeypatch.setattr("mous_pipeline.m9_orchestration.runner.apply_notch_and_resample", lambda raw, _cfg: raw)
    monkeypatch.setattr("mous_pipeline.m9_orchestration.runner.fit_and_apply", lambda raw, _cfg: (raw, None))
    monkeypatch.setattr("mous_pipeline.m9_orchestration.runner.apply_band", lambda raw, *_a, **_k: raw)
    monkeypatch.setattr(
        "mous_pipeline.m9_orchestration.runner.make_epochs",
        lambda *_a, **_k: (_DummyEpochs(len(kept_meta)), kept_meta.copy()),
    )
    monkeypatch.setattr("mous_pipeline.m9_orchestration.runner.get_sensor_positions", lambda *_a, **_k: (np.zeros((3, 2)), None))

    def fake_prestim(epochs, _subject, _cfg, trial_meta):
        captured["prestim_trial_ids"] = trial_meta["trial_id"].tolist()
        assert len(trial_meta) == len(epochs)
        return np.array([0.1, 0.2])

    def fake_n400m(epochs, _subject, _cfg, trial_meta, **_kwargs):
        captured["n400m_trial_ids"] = trial_meta["trial_id"].tolist()
        assert len(trial_meta) == len(epochs)
        return np.array([1.0, 2.0])

    monkeypatch.setattr("mous_pipeline.m9_orchestration.runner.prestim_beta_power", fake_prestim)
    monkeypatch.setattr("mous_pipeline.m9_orchestration.runner.n400m_amplitude", fake_n400m)

    result = run_subject(subject, cfg, only={"m1", "m2", "m3", "m4_trial"}, force=True)

    assert result.status in {"done", "completed_with_skips"}
    assert captured["prestim_trial_ids"] == [101, 103]
    assert captured["n400m_trial_ids"] == [101, 103]
    dist = np.load(tmp_path / "derivatives" / subject / "m4_features" / f"{subject}_prestim_distribution.npz")
    assert dist["trial_id"].tolist() == [101, 103]
