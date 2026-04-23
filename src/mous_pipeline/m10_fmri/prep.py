"""fMRI preprocessing utilities (fMRIPrep container orchestration)."""

from __future__ import annotations

import json
import os
import shlex
import shutil
import subprocess
from pathlib import Path


def _resolve_output_dir(path_value: str, bids_root: Path, project_root: Path | None = None) -> Path:
    """Resolve *path_value* to an absolute path.

    Relative paths are anchored to *project_root* (the pipeline's working
    directory) rather than *bids_root*, because bids_root may contain spaces
    that FSL/ANTs cannot handle.  If *project_root* is None, falls back to
    ``Path.cwd()``.
    """
    import time
    out_dir = Path(path_value).expanduser()
    cwd = Path.cwd()
    base = project_root if (not out_dir.is_absolute() and project_root is not None) else (cwd if not out_dir.is_absolute() else None)
    resolved = (base / out_dir).resolve() if base is not None else out_dir
    # #region agent log
    try:
        import json as _json
        _dbg = Path(__file__).resolve().parent.parent.parent.parent / ".cursor" / "debug-524377.log"
        _dbg.parent.mkdir(parents=True, exist_ok=True)
        _log = {"sessionId": "524377", "hypothesisId": "A", "location": "prep.py:_resolve_output_dir", "message": "output dir resolution", "data": {"path_value": path_value, "bids_root": str(bids_root), "cwd": str(cwd), "project_root": str(project_root), "resolved": str(resolved), "has_space_in_resolved": " " in str(resolved)}, "timestamp": int(time.time() * 1000)}
        _dbg.open("a").write(_json.dumps(_log) + "\n")
    except Exception:
        pass
    # #endregion
    return resolved


def _ensure_bids_dataset_description(bids_root: Path) -> None:
    """Create a minimal BIDS dataset_description.json when missing."""
    desc = bids_root / "dataset_description.json"
    if desc.exists():
        return
    payload = {
        "Name": "MOUS dataset",
        "BIDSVersion": "1.8.0",
        "DatasetType": "raw",
    }
    desc.write_text(json.dumps(payload, indent=2))


def _safe_work_dir(cfg, subject: str, bids_root: Path, out_dir: Path) -> Path:
    """Return a fMRIPrep work dir guaranteed to be outside bids_root."""
    subject_id = subject.removeprefix("sub-")
    default_work = out_dir / "work"
    try:
        if not default_work.resolve().is_relative_to(bids_root.resolve()):
            return default_work
    except Exception:
        # If resolution/relative checks fail, fall back to external work dir.
        pass
    # Keep work products in project derivatives root, outside data_root/BIDS.
    return cfg.derivatives_root / "_fmriprep_work" / f"sub-{subject_id}"


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
    if bool(getattr(cfg.fmri, "skip_bids_validation", False)):
        fmriprep_args.append("--skip_bids_validation")
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


def _assert_no_spaces(path: Path, label: str) -> None:
    """Raise early if *path* contains spaces — FSL/ANTs cannot handle them."""
    if " " in str(path):
        raise ValueError(
            f"fMRIPrep cannot run because {label} contains a space:\n"
            f"  {path}\n"
            "FSL and ANTs split on spaces in command-line arguments.\n"
            "Fix: set fmri.fmriprep_output to an absolute path with no spaces, e.g.:\n"
            "  fmriprep_output: '~/MOUS/Sandbox/MOUS/derivatives/fmriprep'\n"
            "Or create a symlink:  ln -s '/path/with spaces/data' /path/without/spaces"
        )


def run_fmriprep(subject: str, cfg, *, bids_root: Path) -> Path:
    """Run fMRIPrep for a subject, with Neurodesk module and container support.

    Execution modes (checked in order):
    1. skip_fmriprep=true  — return output dir immediately (preprocessed data assumed present).
    2. fmri.fmriprep_container set — run via ``singularity exec <container> fmriprep``.
    3. fmriprep on PATH — run directly (e.g. after ``ml fmriprep`` in Neurodesk).

    If fmri.neurodesk_module is set, ``ml <module>`` is sourced before running so the
    binary becomes available within the same shell environment.
    """
    if not str(cfg.fmri.fmriprep_output).strip():
        raise ValueError("fmri.fmriprep_output is required.")
    project_root = Path.cwd()
    out_dir = _resolve_output_dir(cfg.fmri.fmriprep_output, bids_root, project_root)
    _ensure_bids_dataset_description(bids_root)
    if cfg.fmri.skip_fmriprep:
        out_dir.mkdir(parents=True, exist_ok=True)
        return out_dir

    out_dir.mkdir(parents=True, exist_ok=True)
    work_dir = _safe_work_dir(cfg, subject, bids_root, out_dir)
    work_dir.mkdir(parents=True, exist_ok=True)

    # #region agent log
    try:
        import time as _t, json as _json
        _dbg = Path(__file__).resolve().parent.parent.parent.parent / ".cursor" / "debug-524377.log"
        _dbg.parent.mkdir(parents=True, exist_ok=True)
        _log = {"sessionId": "524377", "hypothesisId": "B", "location": "prep.py:run_fmriprep", "message": "spaces check before fmriprep", "data": {"bids_root": str(bids_root), "out_dir": str(out_dir), "work_dir": str(work_dir), "bids_has_space": " " in str(bids_root), "out_has_space": " " in str(out_dir), "work_has_space": " " in str(work_dir)}, "timestamp": int(_t.time() * 1000)}
        _dbg.open("a").write(_json.dumps(_log) + "\n")
    except Exception:
        pass
    # #endregion
    _assert_no_spaces(bids_root, "bids_root (data_root)")
    _assert_no_spaces(out_dir, "fmri.fmriprep_output")
    _assert_no_spaces(work_dir, "fmriprep work_dir")

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
    if bool(getattr(cfg.fmri, "skip_bids_validation", False)):
        fmriprep_args.append("--skip_bids_validation")
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
        quoted_args = " ".join(shlex.quote(arg) for arg in fmriprep_args)
        shell_cmd = f"ml {shlex.quote(neurodesk_module)} && fmriprep {quoted_args}"
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
