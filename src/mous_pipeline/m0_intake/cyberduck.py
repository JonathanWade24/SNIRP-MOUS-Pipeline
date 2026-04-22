"""Cyberduck / duck command helpers."""

from __future__ import annotations

import shutil
import subprocess
from pathlib import Path


def build_duck_download_command(
    *,
    protocol: str,
    host: str,
    remote_root: str,
    subject: str,
    local_root: str | Path,
    username: str | None = None,
) -> list[str]:
    subject_dir = f"sub-{subject}"
    source_url = f"{protocol}://{host}/{remote_root.strip('/')}/{subject_dir}.tar.gz"
    local_path = str(Path(local_root).resolve())
    cmd = ["duck"]
    if username:
        cmd += ["--username", username]
    cmd += ["--download", source_url, local_path]
    return cmd


def duck_available() -> bool:
    return shutil.which("duck") is not None


def execute_duck_command(cmd: list[str]) -> subprocess.CompletedProcess:
    return subprocess.run(cmd, check=False, capture_output=True, text=True)
