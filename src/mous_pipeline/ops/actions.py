from __future__ import annotations

import os
import re
import shlex
import subprocess
from pathlib import Path

from ..config import RuntimeOverrides, load_config, resolve_runtime_overrides
from ..m0_intake.repocli_rdr import build_repocli_ls_command, parse_repocli_ls_subjects, repocli_available
from .models import JobRecord, WorkflowPreset

MODE_TO_PRESET_DEFAULTS: dict[str, WorkflowPreset] = {
    "full_pipeline": WorkflowPreset(
        name="full_submit",
        description="Multimodal driver with detached fMRI preprocessing",
        mode="submit",
    ),
    "meg_only": WorkflowPreset(
        name="meg_only",
        description="MEG-focused submit mode",
        mode="submit",
    ),
    "fmri_only": WorkflowPreset(
        name="fmriprep_only_submit",
        description="fMRI preprocessing only",
        mode="submit",
        extra_args=["--subjects"],
    ),
    "download_only": WorkflowPreset(
        name="download_only",
        description="Download only",
        mode="download",
        fetch_missing=True,
    ),
}


def _is_repo_root(path: Path) -> bool:
    return (
        (path / "pyproject.toml").is_file()
        and (path / "scripts" / "palmetto_submit.sh").is_file()
        and (path / "src" / "mous_pipeline").is_dir()
    )


def _find_repo_root(start: Path) -> Path | None:
    current = start.expanduser()
    if current.is_file():
        current = current.parent
    current = current.resolve()
    for candidate in (current, *current.parents):
        if _is_repo_root(candidate):
            return candidate
    return None


def resolve_repo_root(*, repo_root: Path | None = None, config_path: str | None = None) -> Path:
    """Resolve the project checkout that owns the Palmetto helper scripts."""
    starts: list[Path] = []
    env_root = os.environ.get("MOUS_REPO_ROOT")
    if repo_root is not None:
        starts.append(repo_root)
    if env_root:
        starts.append(Path(env_root))
    if config_path:
        cfg = Path(config_path).expanduser()
        starts.append(cfg if cfg.is_absolute() else Path.cwd() / cfg)
    starts.extend([Path.cwd(), Path(__file__).resolve()])
    for start in starts:
        found = _find_repo_root(start)
        if found is not None:
            return found
    return (repo_root or Path.cwd()).expanduser().resolve()


def _anchor_repo_script(cmd: list[str], repo_root: Path) -> list[str]:
    if not cmd:
        return cmd
    executable = Path(cmd[0]).expanduser()
    if executable.is_absolute():
        return cmd
    if executable.parts[:1] == ("scripts",):
        anchored = repo_root / executable
        if anchored.exists():
            return [str(anchored), *cmd[1:]]
    return cmd


def _preserve_config_path(cmd: list[str], original_cwd: Path, repo_root: Path) -> list[str]:
    if "--config" not in cmd:
        return cmd
    index = cmd.index("--config") + 1
    if index >= len(cmd):
        return cmd
    config = Path(cmd[index]).expanduser()
    if config.is_absolute():
        return cmd
    if (repo_root / config).exists():
        return cmd
    original_config = (original_cwd / config).resolve()
    if original_config.exists():
        updated = list(cmd)
        updated[index] = str(original_config)
        return updated
    return cmd


def prepare_repo_command(cmd: list[str], repo_root: Path, *, original_cwd: Path | None = None) -> list[str]:
    """Anchor repo helper scripts while preserving relative config semantics."""
    prepared = _preserve_config_path(cmd, original_cwd or Path.cwd(), repo_root)
    return _anchor_repo_script(prepared, repo_root)


def discover_subjects(config_path: str, data_root: str | None = None) -> list[str]:
    subjects: set[str] = set()
    cfg_path = Path(config_path).expanduser()
    cfg_obj = None
    if cfg_path.exists():
        try:
            cfg_obj = load_config(cfg_path)
        except Exception:
            cfg_obj = None
    effective_data_root = data_root
    if not effective_data_root and cfg_obj is not None:
        effective_data_root = str(cfg_obj.data_root)
    if effective_data_root:
        for p in Path(effective_data_root).expanduser().glob("sub-*"):
            if p.is_dir():
                subjects.add(p.name.removeprefix("sub-"))
    if cfg_obj is not None:
        subjects.update(s.removeprefix("sub-") for s in cfg_obj.subjects)
    elif cfg_path.exists():
        txt = cfg_path.read_text()
        for m in re.findall(r'^\s*-\s*"?([A-Za-z0-9_-]+)"?\s*$', txt, flags=re.M):
            if m.startswith("A") or m.startswith("sub-"):
                subjects.add(m.removeprefix("sub-"))
    return sorted(subjects)


def discover_remote_subjects(config_path: str) -> tuple[list[str], str | None]:
    """Query RDR via repocli and return available subject IDs."""
    if not repocli_available():
        return [], "repocli is not on PATH."
    cfg = load_config(Path(config_path).expanduser().resolve())
    collection = str(getattr(cfg.rdr, "collection_path", "")).strip()
    if not collection:
        return [], "rdr.collection_path is empty in config."
    proc = run_cmd(build_repocli_ls_command(collection), cwd=Path.cwd())
    if proc.returncode != 0:
        err = (proc.stderr or "").strip() or (proc.stdout or "").strip() or "unknown repocli error"
        return [], f"Failed to list RDR subjects: {err}"
    return parse_repocli_ls_subjects(proc.stdout or ""), None


def compute_undownloaded_subjects(local_subjects: list[str], remote_subjects: list[str]) -> list[str]:
    local = {s.removeprefix("sub-") for s in local_subjects}
    remote = {s.removeprefix("sub-") for s in remote_subjects}
    return sorted(remote - local)


def build_submit_cmd(
    preset: WorkflowPreset,
    *,
    config: str,
    subjects: list[str],
    account: str,
    partition: str,
    time_limit: str,
    mem: str,
    cpus_per_task: str,
    overrides: RuntimeOverrides | None = None,
) -> list[str]:
    preset_overrides = RuntimeOverrides(
        fetch_missing=preset.fetch_missing,
        include_m5=preset.include_m5,
        dry_run=preset.dry_run,
    )
    resolved = resolve_runtime_overrides(preset_overrides, overrides)
    cmd = [
        "scripts/palmetto_submit.sh",
        "--config",
        config,
        "--subjects",
        ",".join(subjects),
        "--account",
        account,
        "--partition",
        partition,
        "--time",
        time_limit,
        "--mem",
        mem,
        "--cpus-per-task",
        cpus_per_task,
    ]
    if resolved.fetch_missing:
        cmd.append("--fetch-missing")
    if resolved.include_m5:
        cmd.append("--include-m5")
    if resolved.dry_run:
        cmd.append("--dry-run")
    cmd.extend(preset.extra_args)
    return cmd


def build_download_cmd(config: str, subject: str) -> list[str]:
    return ["mous-pipeline", "fetch-rdr", "--config", config, "--subject", subject, "--execute"]


def build_bids_convert_cmd(config: str, subject: str) -> list[str]:
    return ["mous-pipeline", "bids-convert", "--config", config, "--subject", subject]


def build_bids_validate_cmd(root: str, subject: str) -> list[str]:
    return ["mous-pipeline", "bids-validate", "--root", root, "--subject", subject, "--verbose"]


def build_recon_submit_cmd(
    *,
    config: str,
    subjects: list[str],
    account: str,
    partition: str,
    time_limit: str,
    mem: str,
    cpus_per_task: str,
    dry_run: bool = False,
) -> list[str]:
    cmd = [
        "scripts/palmetto_recon_all.sh",
        "--config",
        config,
        "--subjects",
        ",".join(subjects),
        "--partition",
        partition,
        "--account",
        account,
        "--time",
        time_limit,
        "--mem",
        mem,
        "--cpus-per-task",
        cpus_per_task,
    ]
    if dry_run:
        cmd.append("--dry-run")
    return cmd


def build_bem_submit_cmd(
    *,
    config: str,
    subjects: list[str],
    account: str,
    partition: str,
    time_limit: str,
    mem: str,
    cpus_per_task: str,
    dependency: str = "",
    dry_run: bool = False,
) -> list[str]:
    cmd = [
        "scripts/palmetto_prep_bem.sh",
        "--config",
        config,
        "--subjects",
        ",".join(subjects),
        "--partition",
        partition,
        "--account",
        account,
        "--time",
        time_limit,
        "--mem",
        mem,
        "--cpus-per-task",
        cpus_per_task,
    ]
    if dependency:
        cmd.extend(["--dependency", dependency])
    if dry_run:
        cmd.append("--dry-run")
    return cmd


def run_cmd(cmd: list[str], *, cwd: Path | None = None) -> subprocess.CompletedProcess[str]:
    return subprocess.run(cmd, check=False, text=True, capture_output=True, cwd=str(cwd) if cwd else None)


def parse_sbatch_job_id(text: str) -> str:
    m = re.search(r"Submitted batch job (\d+)", text or "")
    return m.group(1) if m else ""


def submit_sbatch(script_path: str) -> JobRecord:
    proc = run_cmd(["sbatch", script_path])
    out = proc.stdout.strip()
    job_id = parse_sbatch_job_id(out)
    return JobRecord(
        job_id=job_id or "unknown",
        job_name="mous_driver",
        kind="driver",
        config_path="configs/palmetto_hpcnirc_fmri.yaml",
        subjects=[],
        status="SUBMITTED" if job_id else "UNKNOWN",
    )


def execute_submit_cmd(
    cmd: list[str],
    *,
    config_path: str,
    subjects: list[str],
    kind: str = "palmetto_submit",
    job_name: str = "mous_fmriprep",
) -> tuple[JobRecord | None, subprocess.CompletedProcess[str]]:
    original_cwd = Path.cwd()
    root = resolve_repo_root(config_path=config_path)
    proc = run_cmd(prepare_repo_command(cmd, root, original_cwd=original_cwd), cwd=root)
    job_id = parse_sbatch_job_id((proc.stdout or "") + "\n" + (proc.stderr or ""))
    if not job_id:
        return None, proc
    return (
        JobRecord(
            job_id=job_id,
            job_name=job_name,
            kind=kind,
            config_path=config_path,
            subjects=subjects,
            status="SUBMITTED",
        ),
        proc,
    )


def submit_detached_driver(
    submit_cmd: list[str],
    *,
    config_path: str,
    subjects: list[str],
    account: str,
    partition: str,
    time_limit: str,
    mem: str,
    cpus_per_task: str,
    venv_path: str,
    derivatives_root: str,
    repo_root: Path | None = None,
) -> tuple[JobRecord | None, subprocess.CompletedProcess[str]]:
    original_cwd = Path.cwd()
    root = resolve_repo_root(repo_root=repo_root, config_path=config_path)
    slurm_dir = Path(derivatives_root).expanduser().resolve() / "slurm"
    slurm_dir.mkdir(parents=True, exist_ok=True)
    anchored_submit_cmd = prepare_repo_command(submit_cmd, root, original_cwd=original_cwd)
    wrapped = (
        f"cd {shlex.quote(str(root))} && "
        f"source {shlex.quote(str(Path(venv_path).expanduser() / 'bin/activate'))} && "
        + " ".join(shlex.quote(part) for part in anchored_submit_cmd)
    )
    sbatch_cmd = [
        "sbatch",
        "--job-name",
        "mous_driver",
        "--partition",
        partition,
        "--account",
        account,
        "--time",
        time_limit,
        "--mem",
        mem,
        "--cpus-per-task",
        cpus_per_task,
        "--output",
        str(slurm_dir / "mous_driver_%j.out"),
        "--error",
        str(slurm_dir / "mous_driver_%j.err"),
        "--wrap",
        wrapped,
    ]
    proc = run_cmd(sbatch_cmd, cwd=root)
    job_id = parse_sbatch_job_id((proc.stdout or "") + "\n" + (proc.stderr or ""))
    if not job_id:
        return None, proc
    return (
        JobRecord(
            job_id=job_id,
            job_name="mous_driver",
            kind="detached_driver",
            config_path=config_path,
            subjects=subjects,
            status="SUBMITTED",
        ),
        proc,
    )


def submit_detached_wrap(
    wrapped_cmd: list[str],
    *,
    job_name: str,
    kind: str,
    config_path: str,
    subjects: list[str],
    account: str,
    partition: str,
    time_limit: str,
    mem: str,
    cpus_per_task: str,
    derivatives_root: str,
    repo_root: Path | None = None,
) -> tuple[JobRecord | None, subprocess.CompletedProcess[str]]:
    original_cwd = Path.cwd()
    root = resolve_repo_root(repo_root=repo_root, config_path=config_path)
    slurm_dir = Path(derivatives_root).expanduser().resolve() / "slurm"
    slurm_dir.mkdir(parents=True, exist_ok=True)
    anchored_wrapped_cmd = prepare_repo_command(wrapped_cmd, root, original_cwd=original_cwd)
    wrapped = f"cd {shlex.quote(str(root))} && " + " ".join(shlex.quote(part) for part in anchored_wrapped_cmd)
    sbatch_cmd = [
        "sbatch",
        "--job-name",
        job_name,
        "--partition",
        partition,
        "--account",
        account,
        "--time",
        time_limit,
        "--mem",
        mem,
        "--cpus-per-task",
        cpus_per_task,
        "--output",
        str(slurm_dir / f"{job_name}_%j.out"),
        "--error",
        str(slurm_dir / f"{job_name}_%j.err"),
        "--wrap",
        wrapped,
    ]
    proc = run_cmd(sbatch_cmd, cwd=root)
    job_id = parse_sbatch_job_id((proc.stdout or "") + "\n" + (proc.stderr or ""))
    if not job_id:
        return None, proc
    return (
        JobRecord(
            job_id=job_id,
            job_name=job_name,
            kind=kind,
            config_path=config_path,
            subjects=subjects,
            status="SUBMITTED",
        ),
        proc,
    )
