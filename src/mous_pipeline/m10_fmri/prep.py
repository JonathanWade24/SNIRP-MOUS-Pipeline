"""fMRI preprocessing utilities (fMRIPrep container orchestration)."""

from __future__ import annotations

import json
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
    bids_candidates = [
        bids_root / sub_dir / "func" / f"{sub_dir}_task-auditory_bold.nii.gz",
        bids_root / sub_dir / "func" / f"{sub_dir}_task-language_bold.nii.gz",
    ]
    for cand in bids_candidates:
        if cand.exists():
            return cand

    if fmriprep_out_dir is not None:
        func_dir = fmriprep_out_dir / sub_dir / "func"
        for patt in (
            f"{sub_dir}_task-auditory*_desc-preproc_bold.nii.gz",
            f"{sub_dir}_task-language*_desc-preproc_bold.nii.gz",
            f"{sub_dir}_task-*_desc-preproc_bold.nii.gz",
        ):
            matches = sorted(func_dir.glob(patt))
            if matches:
                return matches[0]

    return None


def validate_tr_from_sidecar(sidecar_json: Path, cfg_tr: float, *, atol: float = 1e-3) -> float:
    payload = json.loads(sidecar_json.read_text())
    tr = float(payload.get("RepetitionTime", cfg_tr))
    if abs(tr - cfg_tr) > atol:
        raise ValueError(f"Config TR ({cfg_tr}) does not match sidecar TR ({tr}) in {sidecar_json}.")
    return tr


def run_fmriprep(subject: str, cfg, *, bids_root: Path) -> Path:
    """
    Run fMRIPrep through a Neurodesk-compatible container path.

    If skip_fmriprep is true, simply returns configured output directory.
    """
    out_dir = _resolve_output_dir(cfg.fmri.fmriprep_output, bids_root)
    if cfg.fmri.skip_fmriprep:
        if not str(cfg.fmri.fmriprep_output).strip():
            raise ValueError("fmri.fmriprep_output is required when skip_fmriprep=true.")
        out_dir.mkdir(parents=True, exist_ok=True)
        return out_dir

    container = Path(cfg.fmri.fmriprep_container).expanduser()
    if not container.exists():
        raise FileNotFoundError(f"fMRIPrep container not found: {container}")
    out_dir.mkdir(parents=True, exist_ok=True)
    work_dir = out_dir / "work"
    work_dir.mkdir(parents=True, exist_ok=True)

    cmd = [
        "singularity",
        "exec",
        str(container),
        "fmriprep",
        str(bids_root),
        str(out_dir),
        "participant",
        "--participant-label",
        subject.removeprefix("sub-"),
        "-w",
        str(work_dir),
    ]
    subprocess.run(cmd, check=True)
    return out_dir
