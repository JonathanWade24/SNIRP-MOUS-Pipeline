from __future__ import annotations

from pathlib import Path

from mous_pipeline.config import PipelineConfig
from mous_pipeline.m0_intake.bids_convert import convert_subject_to_bids


def test_convert_subject_to_bids_writes_for_task_and_rest(monkeypatch, tmp_path: Path):
    data_root = tmp_path / "data"
    meg_dir = data_root / "sub-A2002" / "meg"
    meg_dir.mkdir(parents=True)
    (meg_dir / "sub-A2002_task-auditory_meg.ds").mkdir()
    (meg_dir / "sub-A2002_task-rest_meg.ds").mkdir()

    class DummyRaw:
        pass

    written = []

    def fake_read_raw_ctf(*args, **kwargs):
        return DummyRaw()

    def fake_write_raw_bids(raw, bids_path, **kwargs):
        written.append(bids_path)
        sidecar = (
            Path(bids_path.root)
            / f"sub-{bids_path.subject}"
            / "meg"
            / f"sub-{bids_path.subject}_task-{bids_path.task}_meg.json"
        )
        sidecar.parent.mkdir(parents=True, exist_ok=True)
        sidecar.write_text("{}")

    monkeypatch.setattr("mous_pipeline.m0_intake.bids_convert.mne.io.read_raw_ctf", fake_read_raw_ctf)
    monkeypatch.setattr("mous_pipeline.m0_intake.bids_convert.write_raw_bids", fake_write_raw_bids)

    cfg = PipelineConfig(data_root=data_root)
    bids_paths = convert_subject_to_bids("A2002", cfg)
    assert len(bids_paths) == 2
    # When CTF is already at the BIDS path, the converter skips `write_raw_bids` and only
    # normalizes sidecars. Non-zero "written" would require a legacy source path != target.
    assert len(written) == 0
    assert (data_root / "dataset_description.json").exists()
