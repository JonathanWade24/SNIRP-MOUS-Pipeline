from pathlib import Path

import pytest

from mous_pipeline.config import FmriConfig, PipelineConfig
from mous_pipeline.m10_fmri import prep


def _base_cfg(tmp_path: Path, *, container_runtime: str = "", container_binds: list[str] | None = None) -> PipelineConfig:
    return PipelineConfig(
        derivatives_root=tmp_path / "derivatives",
        fmri=FmriConfig(
            fmriprep_container=str(tmp_path / "containers" / "fmriprep.sif"),
            fmriprep_output=str(tmp_path / "derivatives" / "fmriprep"),
            skip_fmriprep=False,
            neurodesk_module="",
            fs_license_file=str(tmp_path / "licenses" / "license.txt"),
            container_runtime=container_runtime,
            container_binds=container_binds or [],
        ),
    )


def test_run_fmriprep_prefers_apptainer_with_binds(monkeypatch, tmp_path: Path):
    bids_root = tmp_path / "bids"
    bids_root.mkdir()
    container = tmp_path / "containers" / "fmriprep.sif"
    container.parent.mkdir(parents=True)
    container.write_text("stub")

    cfg = _base_cfg(tmp_path, container_binds=["/scratch:/scratch", "/scratch/jonathanwade:/scratch/jonathanwade"])
    calls: list[list[str]] = []

    def _fake_which(binary: str) -> str | None:
        if binary == "apptainer":
            return "/usr/bin/apptainer"
        if binary == "singularity":
            return "/usr/bin/singularity"
        return None

    monkeypatch.setattr(prep.shutil, "which", _fake_which)
    monkeypatch.setattr(prep, "_run_cmd_streaming", lambda cmd, log_callback=None: calls.append(cmd))

    prep.run_fmriprep("A2003", cfg, bids_root=bids_root)

    assert calls, "expected fMRIPrep command invocation"
    cmd = calls[0]
    assert cmd[0:2] == ["apptainer", "exec"]
    assert "-B" in cmd
    assert "/scratch:/scratch" in cmd
    assert "/scratch/jonathanwade:/scratch/jonathanwade" in cmd
    assert "--fs-license-file" in cmd
    assert str(tmp_path / "licenses" / "license.txt") in cmd


def test_run_fmriprep_falls_back_to_singularity(monkeypatch, tmp_path: Path):
    bids_root = tmp_path / "bids"
    bids_root.mkdir()
    container = tmp_path / "containers" / "fmriprep.sif"
    container.parent.mkdir(parents=True)
    container.write_text("stub")

    cfg = _base_cfg(tmp_path)
    calls: list[list[str]] = []

    def _fake_which(binary: str) -> str | None:
        if binary == "singularity":
            return "/usr/bin/singularity"
        return None

    monkeypatch.setattr(prep.shutil, "which", _fake_which)
    monkeypatch.setattr(prep, "_run_cmd_streaming", lambda cmd, log_callback=None: calls.append(cmd))

    prep.run_fmriprep("A2003", cfg, bids_root=bids_root)

    assert calls[0][0:2] == ["singularity", "exec"]


def test_run_fmriprep_respects_configured_container_runtime(monkeypatch, tmp_path: Path):
    bids_root = tmp_path / "bids"
    bids_root.mkdir()
    container = tmp_path / "containers" / "fmriprep.sif"
    container.parent.mkdir(parents=True)
    container.write_text("stub")

    cfg = _base_cfg(tmp_path, container_runtime="singularity")
    calls: list[list[str]] = []

    monkeypatch.setattr(prep.shutil, "which", lambda _: "/usr/bin/apptainer")
    monkeypatch.setattr(prep, "_run_cmd_streaming", lambda cmd, log_callback=None: calls.append(cmd))

    prep.run_fmriprep("A2003", cfg, bids_root=bids_root)

    assert calls[0][0:2] == ["singularity", "exec"]


def test_run_fmriprep_container_requires_runtime(monkeypatch, tmp_path: Path):
    bids_root = tmp_path / "bids"
    bids_root.mkdir()
    container = tmp_path / "containers" / "fmriprep.sif"
    container.parent.mkdir(parents=True)
    container.write_text("stub")

    cfg = _base_cfg(tmp_path)
    monkeypatch.setattr(prep.shutil, "which", lambda _: None)

    with pytest.raises(FileNotFoundError, match="No container runtime found"):
        prep.run_fmriprep("A2003", cfg, bids_root=bids_root)
