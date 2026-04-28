from __future__ import annotations

import re
import shlex
import subprocess
from pathlib import Path

from ..config import load_config
from ..m0_intake.repocli_rdr import build_repocli_ls_command, parse_repocli_ls_subjects, repocli_available
from .models import JobRecord, WorkflowPreset


def discover_subjects(config_path: str, data_root: str | None = None) -> list[str]:
    subjects: set[str] = set()
    if data_root:
        for p in Path(data_root).expanduser().glob("sub-*"):
            if p.is_dir():
                subjects.add(p.name.removeprefix("sub-"))
    cfg = Path(config_path).expanduser()
    if cfg.exists():
        txt = cfg.read_text()
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
) -> list[str]:
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
    if preset.fetch_missing:
        cmd.append("--fetch-missing")
    if preset.include_m5:
        cmd.append("--include-m5")
    if preset.dry_run:
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
    proc = run_cmd(cmd, cwd=Path.cwd())
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
    root = (repo_root or Path.cwd()).resolve()
    slurm_dir = Path(derivatives_root).expanduser().resolve() / "slurm"
    slurm_dir.mkdir(parents=True, exist_ok=True)
    wrapped = (
        f"cd {shlex.quote(str(root))} && "
        f"source {shlex.quote(str(Path(venv_path).expanduser() / 'bin/activate'))} && "
        + " ".join(shlex.quote(part) for part in submit_cmd)
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
    root = (repo_root or Path.cwd()).resolve()
    slurm_dir = Path(derivatives_root).expanduser().resolve() / "slurm"
    slurm_dir.mkdir(parents=True, exist_ok=True)
    wrapped = f"cd {shlex.quote(str(root))} && " + " ".join(shlex.quote(part) for part in wrapped_cmd)
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
