"""fMRI preprocessing utilities (fMRIPrep container orchestration)."""

from __future__ import annotations

import json
import subprocess
from pathlib import Path


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
    out_dir = Path(cfg.fmri.fmriprep_output).expanduser()
    if cfg.fmri.skip_fmriprep:
        if not str(cfg.fmri.fmriprep_output).strip():
            raise ValueError("fmri.fmriprep_output is required when skip_fmriprep=true.")
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
