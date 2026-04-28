from __future__ import annotations

import os
import shutil
from dataclasses import dataclass
from pathlib import Path


@dataclass
class EnvCheck:
    name: str
    required: bool
    ok: bool
    detail: str


def check_binary(name: str, *, required: bool = True) -> EnvCheck:
    path = shutil.which(name)
    ok = path is not None
    detail = path or "not found"
    return EnvCheck(name=name, required=required, ok=ok, detail=detail)


def detect_venv_active() -> bool:
    return bool(os.environ.get("VIRTUAL_ENV"))


def venv_activate_hint(venv_path: str) -> str:
    p = Path(venv_path).expanduser()
    return f"source \"{p}/bin/activate\""


def run_env_preflight(venv_path: str) -> list[EnvCheck]:
    checks = [
        check_binary("python3"),
        check_binary("sbatch"),
        check_binary("sacct"),
        check_binary("repocli", required=False),
        check_binary("apptainer", required=False),
        check_binary("singularity", required=False),
    ]
    if detect_venv_active():
        checks.append(EnvCheck(name="venv", required=True, ok=True, detail=os.environ["VIRTUAL_ENV"]))
    else:
        checks.append(EnvCheck(name="venv", required=True, ok=False, detail=venv_activate_hint(venv_path)))
    return checks
