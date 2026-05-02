from __future__ import annotations

import subprocess
import os
from dataclasses import dataclass
from pathlib import Path


@dataclass
class SlurmJobStatus:
    job_id: str
    name: str
    state: str
    exit_code: str
    elapsed: str


def _run_text(cmd: list[str]) -> str:
    proc = subprocess.run(cmd, check=False, text=True, capture_output=True)
    return proc.stdout


def recent_jobs(hours: int = 24) -> list[SlurmJobStatus]:
    user = os.environ.get("USER", "")
    out = _run_text(
        [
            "sacct",
            "-u",
            user,
            "--starttime",
            f"now-{hours}hours",
            "-o",
            "JobID,JobName%25,State,ExitCode,Elapsed",
            "--parsable2",
            "--noheader",
        ]
    )
    rows: list[SlurmJobStatus] = []
    for line in out.splitlines():
        parts = line.split("|")
        if len(parts) < 5:
            continue
        rows.append(
            SlurmJobStatus(
                job_id=parts[0].strip(),
                name=parts[1].strip(),
                state=parts[2].strip(),
                exit_code=parts[3].strip(),
                elapsed=parts[4].strip(),
            )
        )
    return rows


def squeue_jobs() -> list[SlurmJobStatus]:
    out = _run_text(["squeue", "--noheader", "-o", "%i|%j|%T|%M"])
    rows: list[SlurmJobStatus] = []
    for line in out.splitlines():
        parts = line.split("|")
        if len(parts) < 4:
            continue
        rows.append(
            SlurmJobStatus(
                job_id=parts[0].strip(),
                name=parts[1].strip(),
                state=parts[2].strip(),
                exit_code="-",
                elapsed=parts[3].strip(),
            )
        )
    return rows


def sinfo_partition(partition: str) -> dict[str, int | str] | None:
    part = partition.strip()
    if not part:
        return None
    try:
        out = _run_text(["sinfo", "--noheader", "-o", "%n|%C|%m", "-p", part])
    except Exception:
        return None
    if not out.strip():
        return None
    max_mem_gb = 0
    max_cpus = 0
    nodes = 0
    for line in out.splitlines():
        fields = line.split("|")
        if len(fields) < 3:
            continue
        cpu_fields = fields[1].split("/")
        if len(cpu_fields) != 4:
            continue
        try:
            total_cpus = int(cpu_fields[3])
            mem_mb = int(fields[2].strip())
        except ValueError:
            continue
        nodes += 1
        max_cpus = max(max_cpus, total_cpus)
        max_mem_gb = max(max_mem_gb, int(mem_mb / 1024))
    if nodes == 0 or max_mem_gb <= 0 or max_cpus <= 0:
        return None
    return {
        "partition": part,
        "nodes": nodes,
        "max_node_mem_gb": max_mem_gb,
        "max_node_cpus": max_cpus,
    }


def classify_failure(log_text: str) -> str:
    msg = log_text.lower()
    if "out of memory" in msg or "oom" in msg:
        return "oom"
    if "time limit" in msg or "timeout" in msg:
        return "timeout"
    if "bids-validator" in msg or "skip_bids_validation" in msg:
        return "validation"
    if "no such file" in msg or "not found" in msg:
        return "missing_file"
    if "permission denied" in msg:
        return "permission"
    if "container" in msg or "apptainer" in msg or "singularity" in msg:
        return "container"
    return "unknown"


def tail_text(path: Path, lines: int = 80) -> str:
    if not path.exists():
        return ""
    data = path.read_text(errors="replace").splitlines()
    return "\n".join(data[-lines:])


def latest_log(slurm_dir: Path, pattern: str) -> Path | None:
    matches = sorted(slurm_dir.glob(pattern), key=lambda p: p.stat().st_mtime, reverse=True)
    return matches[0] if matches else None
