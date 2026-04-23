from __future__ import annotations

from pathlib import Path

from mous_pipeline.config import EpochingConfig, PipelineConfig, PreprocessConfig
from mous_pipeline.m2_preprocess import bids_pipeline_backend as backend
from mous_pipeline.m2_preprocess import ica as ica_mod


def test_run_preprocessing_calls_pipeline_and_returns_epochs(monkeypatch, tmp_path: Path):
    class DummyEpochs:
        pass

    class DummyRaw:
        ica_applied = False

        def apply_gradient_compensation(self, _):
            return None

        def copy(self):
            return self

        def filter(self, *args, **kwargs):
            return self

    class DummyICA:
        def __init__(self, *args, **kwargs):
            self.exclude = []

        def fit(self, raw, picks):
            return self

        def find_bads_ecg(self, raw, method, threshold):
            return [0], [0.9]

        def find_bads_eog(self, raw):
            return [], []

        def apply(self, raw):
            raw.ica_applied = True
            return raw

    calls: list[list[str]] = []

    monkeypatch.setattr(backend, "convert_subject_to_bids", lambda subject, cfg: [])
    monkeypatch.setattr(backend, "make_pseudo_epochs", lambda raw, epoch_len: "rest-epochs")
    monkeypatch.setattr(backend, "apply_notch_and_resample", lambda raw, cfg: raw)
    monkeypatch.setattr(backend, "apply_band", lambda raw, lo, hi: raw)
    monkeypatch.setattr(ica_mod, "ICA", DummyICA)
    monkeypatch.setattr(backend.mne, "read_epochs", lambda *args, **kwargs: DummyEpochs())
    rest_raw = DummyRaw()

    def fake_read_raw_ctf(path, *args, **kwargs):
        if "task-auditory" in str(path):
            return DummyRaw()
        return rest_raw

    monkeypatch.setattr(backend.mne.io, "read_raw_ctf", fake_read_raw_ctf)
    monkeypatch.setattr(backend, "_find_task_epochs", lambda deriv_root, subject: tmp_path / "dummy-epo.fif")

    def fake_run(cmd, check, capture_output, text):
        calls.append(cmd)
        return None

    monkeypatch.setattr(backend.subprocess, "run", fake_run)

    cfg = PipelineConfig(
        data_root=tmp_path / "raw",
        derivatives_root=tmp_path / "deriv",
        preprocess=PreprocessConfig(backend="mne_bids_pipeline", bids_pipeline_deriv_root=str(tmp_path / "mbp")),
        epoching=EpochingConfig(tmin=-0.5, tmax=3.0),
    )

    task_epochs, rest_epochs = backend.run_preprocessing("A2002", cfg)
    assert isinstance(task_epochs, DummyEpochs)
    assert rest_epochs == "rest-epochs"
    assert rest_raw.ica_applied is True
    assert cfg.preprocess.backend == "mne_bids_pipeline"
    assert calls
    assert calls[0][0] == "mne_bids_pipeline"
    assert any("--steps=preprocessing" in part for part in calls[0])
