from __future__ import annotations

import importlib.util
import json
from pathlib import Path

from mous_pipeline.config import PipelineConfig
from mous_pipeline.m0_intake.bids_convert import (
    _ensure_dataset_level_files,
    _normalize_subject_anat_filenames,
    convert_subject_to_bids,
    normalize_channel_type,
)


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


def test_normalize_channel_type_matches_bids_policy():
    assert normalize_channel_type("eeg") == "EEG"
    assert normalize_channel_type("trigger") == "TRIG"
    assert normalize_channel_type("refgrad") == "MEGREFGRADAXIAL"
    assert normalize_channel_type("clock") == "MISC"
    assert normalize_channel_type("adc") == "MISC"
    assert normalize_channel_type("totally-unknown-label") == "MISC"


def test_normalize_script_parity_with_module_mapping(tmp_path: Path):
    script_path = Path(__file__).resolve().parents[1] / "scripts" / "normalize_channels_tsv.py"
    spec = importlib.util.spec_from_file_location("normalize_channels_tsv_module", script_path)
    assert spec and spec.loader
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)

    tsv = tmp_path / "channels.tsv"
    tsv.write_text("name\ttype\nA\teeg\nB\ttrigger\nC\tclock\nD\tweirdthing\n")
    changed, non_canonical = mod.normalise_file(tsv)
    assert changed is True
    assert set(non_canonical) == {"clock", "eeg", "trigger", "weirdthing"}
    assert tsv.read_text().splitlines() == [
        "name\ttype",
        "A\tEEG",
        "B\tTRIG",
        "C\tMISC",
        "D\tMISC",
    ]


def test_normalize_subject_anat_filenames_updates_scans_tsv(tmp_path: Path):
    root = tmp_path
    anat = root / "sub-A2002" / "anat"
    anat.mkdir(parents=True)
    (anat / "sub-A2002_space-CTF_T1w.nii").write_text("nii")
    (anat / "sub-A2002_space-CTF_T1w.json").write_text("{}")
    scans = root / "sub-A2002" / "sub-A2002_scans.tsv"
    scans.write_text("filename\tacq_time\nanat/sub-A2002_space-CTF_T1w.nii\t2020-01-01T00:00:00\n")

    renamed = _normalize_subject_anat_filenames("A2002", root)
    assert (anat / "sub-A2002_acq-CTF_T1w.nii").exists()
    assert (anat / "sub-A2002_acq-CTF_T1w.json").exists()
    assert "anat/sub-A2002_acq-CTF_T1w.nii" in scans.read_text()
    assert any(p.name == "sub-A2002_acq-CTF_T1w.nii" for p in renamed)


def test_ensure_dataset_level_files_patches_missing_required_fields(tmp_path: Path):
    desc = tmp_path / "dataset_description.json"
    desc.write_text(json.dumps({"Name": "", "BIDSVersion": ""}))
    _ensure_dataset_level_files(tmp_path)
    payload = json.loads(desc.read_text())
    assert payload["Name"] == "MOUS dataset"
    assert payload["BIDSVersion"] == "1.8.0"
    assert payload["DatasetType"] == "raw"
    assert payload["Authors"] == ["MOUS team"]
    assert (tmp_path / "README").exists()
