from __future__ import annotations

import re
import subprocess
from pathlib import Path

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
    cmd: list[str], *, config_path: str, subjects: list[str], kind: str = "palmetto_submit"
) -> tuple[JobRecord | None, subprocess.CompletedProcess[str]]:
    proc = run_cmd(cmd, cwd=Path.cwd())
    job_id = parse_sbatch_job_id((proc.stdout or "") + "\n" + (proc.stderr or ""))
    if not job_id:
        return None, proc
    return (
        JobRecord(
            job_id=job_id,
            job_name="mous_fmriprep",
            kind=kind,
            config_path=config_path,
            subjects=subjects,
            status="SUBMITTED",
        ),
        proc,
    )
