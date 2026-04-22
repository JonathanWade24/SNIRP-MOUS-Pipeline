"""Radboud Data Repository (RDR) ingestion via Repocli (WebDAV CLI)."""

from __future__ import annotations

import shutil
import subprocess
from pathlib import Path


def remote_subject_path(collection_path: str, subject_id: str) -> str:
    """Path relative to RDR WebDAV root, e.g. dccn/DSC_.../sub-A2002."""
    sid = subject_id if subject_id.startswith("sub-") else f"sub-{subject_id}"
    base = collection_path.strip().strip("/")
    return f"{base}/{sid}"


def build_repocli_get_command(*, remote_path: str, local_dir: str | Path) -> list[str]:
    """Build `repocli get <remote> <local>` (credentials from `repocli config`)."""
    return ["repocli", "get", remote_path, str(Path(local_dir).resolve())]


def repocli_available() -> bool:
    return shutil.which("repocli") is not None


def execute_repocli_command(cmd: list[str]) -> subprocess.CompletedProcess:
    return subprocess.run(cmd, check=False, capture_output=True, text=True)
