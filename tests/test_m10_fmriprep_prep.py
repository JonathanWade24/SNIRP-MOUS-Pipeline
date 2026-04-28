from __future__ import annotations

import subprocess
from pathlib import Path
from types import SimpleNamespace

import pytest

from mous_pipeline.m10_fmri import prep


def _cfg(fmriprep_output: Path) -> SimpleNamespace:
    return SimpleNamespace(
        fmri=SimpleNamespace(
            fmriprep_output=str(fmriprep_output),
            skip_fmriprep=False,
            neurodesk_module="fmriprep",
            fs_license_file="",
            skip_bids_validation=False,
            fmriprep_container="",
        ),
        derivatives_root=fmriprep_output.parent / "derivatives",
    )


def _bids_root(tmp_path: Path, subject: str = "sub-01") -> Path:
    bids_root = tmp_path / "bids"
    (bids_root / subject / "func").mkdir(parents=True)
    return bids_root


def _raise_fmriprep_warning_exit(*args, **kwargs) -> None:
    raise subprocess.CalledProcessError(1, "fmriprep")


def test_run_fmriprep_treats_nonzero_exit_as_success_when_preproc_bold_exists(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    out_dir = tmp_path / "fmriprep"
    subject_func = out_dir / "sub-01" / "func"
    subject_func.mkdir(parents=True)
    (subject_func / "sub-01_task-auditory_desc-preproc_bold.nii.gz").touch()
    monkeypatch.setattr(prep, "_run_shell_streaming", _raise_fmriprep_warning_exit)

    result = prep.run_fmriprep("sub-01", _cfg(out_dir), bids_root=_bids_root(tmp_path))

    assert result == out_dir


def test_run_fmriprep_reraises_nonzero_exit_when_preproc_bold_is_missing(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    out_dir = tmp_path / "fmriprep"
    monkeypatch.setattr(prep, "_run_shell_streaming", _raise_fmriprep_warning_exit)

    with pytest.raises(subprocess.CalledProcessError):
        prep.run_fmriprep("sub-01", _cfg(out_dir), bids_root=_bids_root(tmp_path))


def test_run_fmriprep_reuse_existing_skips_execution(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    out_dir = tmp_path / "fmriprep"
    subject_func = out_dir / "sub-01" / "func"
    subject_func.mkdir(parents=True)
    (subject_func / "sub-01_task-auditory_desc-preproc_bold.nii.gz").touch()

    called = {"value": False}

    def _should_not_run(*args, **kwargs):
        called["value"] = True
        raise AssertionError("fMRIPrep execution should be skipped when reuse_existing=True")

    monkeypatch.setattr(prep, "_run_shell_streaming", _should_not_run)
    monkeypatch.setattr(prep, "_run_cmd_streaming", _should_not_run)

    result = prep.run_fmriprep(
        "sub-01",
        _cfg(out_dir),
        bids_root=_bids_root(tmp_path),
        reuse_existing=True,
    )

    assert result == out_dir
    assert called["value"] is False
