"""fMRI preprocessing utilities (fMRIPrep container orchestration)."""

from __future__ import annotations

import json
import os
import shutil
import subprocess
from pathlib import Path


def _resolve_output_dir(path_value: str, bids_root: Path) -> Path:
    out_dir = Path(path_value).expanduser()
    if not out_dir.is_absolute():
        out_dir = (bids_root / out_dir).resolve()
    return out_dir


def resolve_subject_bold_path(subject: str, cfg, *, bids_root: Path, fmriprep_out_dir: Path | None = None) -> Path | None:
    """Resolve subject BOLD path from config or nearby standard locations."""
    configured = str(getattr(cfg.fmri, "bold_path", "")).strip()
    if configured:
        path = Path(configured).expanduser()
        if not path.is_absolute():
            path = (bids_root / path).resolve()
        return path if path.exists() else None

    sub = subject.removeprefix("sub-")
    sub_dir = f"sub-{sub}"

    # fMRIPrep preprocessed outputs take priority over raw BIDS (better for GLM).
    if fmriprep_out_dir is not None:
        func_dir = fmriprep_out_dir / sub_dir / "func"
        for patt in (
            f"{sub_dir}_task-auditory*_desc-preproc_bold.nii.gz",
            f"{sub_dir}_task-auditory*_desc-preproc_bold.nii",
            f"{sub_dir}_task-language*_desc-preproc_bold.nii.gz",
            f"{sub_dir}_task-language*_desc-preproc_bold.nii",
            f"{sub_dir}_task-*_desc-preproc_bold.nii.gz",
            f"{sub_dir}_task-*_desc-preproc_bold.nii",
        ):
            matches = sorted(func_dir.glob(patt))
            if matches:
                return matches[0]

    # Fall back to raw BIDS BOLD (both .nii.gz and .nii).
    bids_func = bids_root / sub_dir / "func"
    for stem in (f"{sub_dir}_task-auditory_bold", f"{sub_dir}_task-language_bold"):
        for ext in (".nii.gz", ".nii"):
            cand = bids_func / (stem + ext)
            if cand.exists():
                return cand

    return None


def validate_tr_from_sidecar(sidecar_json: Path, cfg_tr: float, *, atol: float = 1e-3) -> float:
    payload = json.loads(sidecar_json.read_text())
    tr = float(payload.get("RepetitionTime", cfg_tr))
    if abs(tr - cfg_tr) > atol:
        raise ValueError(f"Config TR ({cfg_tr}) does not match sidecar TR ({tr}) in {sidecar_json}.")
    return tr


def _fmriprep_cmd(subject: str, bids_root: Path, out_dir: Path, work_dir: Path, cfg) -> list[str]:
    """Build the fMRIPrep command list, choosing between container, module, or PATH binary."""
    fmriprep_args = [
        str(bids_root),
        str(out_dir),
        "participant",
        "--participant-label",
        subject.removeprefix("sub-"),
        "-w",
        str(work_dir),
        "--fs-no-reconall",
    ]
    container_path = str(getattr(cfg.fmri, "fmriprep_container", "")).strip()
    if container_path:
        container = Path(container_path).expanduser()
        if not container.exists():
            raise FileNotFoundError(f"fMRIPrep container not found: {container}")
        return ["singularity", "exec", str(container), "fmriprep"] + fmriprep_args

    # No container — use binary on PATH (works after `ml fmriprep` in Neurodesk).
    if not shutil.which("fmriprep"):
        raise FileNotFoundError(
            "fmriprep binary not found on PATH. "
            "In Neurodesk run `ml fmriprep` first, or set fmri.fmriprep_container."
        )
    return ["fmriprep"] + fmriprep_args


def run_fmriprep(subject: str, cfg, *, bids_root: Path) -> Path:
    """Run fMRIPrep for a subject, with Neurodesk module and container support.

    Execution modes (checked in order):
    1. skip_fmriprep=true  — return output dir immediately (preprocessed data assumed present).
    2. fmri.fmriprep_container set — run via ``singularity exec <container> fmriprep``.
    3. fmriprep on PATH — run directly (e.g. after ``ml fmriprep`` in Neurodesk).

    If fmri.neurodesk_module is set, ``ml <module>`` is sourced before running so the
    binary becomes available within the same shell environment.
    """
    out_dir = _resolve_output_dir(cfg.fmri.fmriprep_output, bids_root)
    if cfg.fmri.skip_fmriprep:
        if not str(cfg.fmri.fmriprep_output).strip():
            raise ValueError("fmri.fmriprep_output is required when skip_fmriprep=true.")
        out_dir.mkdir(parents=True, exist_ok=True)
        return out_dir

    out_dir.mkdir(parents=True, exist_ok=True)
    work_dir = out_dir / "work"
    work_dir.mkdir(parents=True, exist_ok=True)

    neurodesk_module = str(getattr(cfg.fmri, "neurodesk_module", "")).strip()
    fs_license = str(getattr(cfg.fmri, "fs_license_file", "")).strip()
    fmriprep_args = [
        str(bids_root),
        str(out_dir),
        "participant",
        "--participant-label",
        subject.removeprefix("sub-"),
        "-w",
        str(work_dir),
        "--fs-no-reconall",
    ]
    if fs_license:
        fmriprep_args += ["--fs-license-file", fs_license]
    container_path = str(getattr(cfg.fmri, "fmriprep_container", "")).strip()

    if container_path:
        container = Path(container_path).expanduser()
        if not container.exists():
            raise FileNotFoundError(f"fMRIPrep container not found: {container}")
        cmd = ["singularity", "exec", str(container), "fmriprep"] + fmriprep_args
        subprocess.run(cmd, check=True)
    elif neurodesk_module:
        # Load Neurodesk/Lmod module and run fmriprep in the same shell.
        shell_cmd = f"ml {neurodesk_module} && fmriprep {' '.join(fmriprep_args)}"
        subprocess.run(shell_cmd, shell=True, check=True, executable="/bin/bash",
                       env={**os.environ, "MODULEPATH": os.environ.get("MODULEPATH", "")})
    else:
        if not shutil.which("fmriprep"):
            raise FileNotFoundError(
                "fmriprep binary not found on PATH. "
                "In Neurodesk run `ml fmriprep` before launching the pipeline, "
                "or set fmri.neurodesk_module: fmriprep in your config."
            )
        subprocess.run(["fmriprep"] + fmriprep_args, check=True)

    return out_dir
