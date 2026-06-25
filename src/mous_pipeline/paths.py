"""Portable path resolution helpers (repo root, derivatives, reports)."""

from __future__ import annotations

import os
from pathlib import Path


def _is_repo_root(path: Path) -> bool:
    return (
        (path / "pyproject.toml").is_file()
        and (path / "reports").is_dir()
        and (path / "src" / "mous_pipeline").is_dir()
    )


def find_repo_root(*, start: Path | None = None) -> Path:
    """Walk upward from *start* (or CWD) to locate the MOUS repository root."""
    env_root = os.environ.get("MOUS_REPO_ROOT", "").strip()
    if env_root:
        candidate = Path(env_root).expanduser().resolve()
        if _is_repo_root(candidate):
            return candidate

    current = (start or Path.cwd()).expanduser()
    if current.is_file():
        current = current.parent
    current = current.resolve()
    for candidate in (current, *current.parents):
        if _is_repo_root(candidate):
            return candidate
    return current


def resolve_derivatives_root(defaults: dict | None = None) -> Path:
    """Resolve derivatives root from persisted defaults, env, or home."""
    if defaults:
        raw = str(defaults.get("derivatives_root", "")).strip()
        if raw:
            return Path(raw).expanduser()
    env = os.environ.get("MOUS_DERIVATIVES_ROOT", "").strip()
    if env:
        return Path(env).expanduser()
    return Path.home() / "mous_derivatives"


def reports_dir() -> Path:
    """Return the ``reports/`` directory relative to the repo root."""
    return find_repo_root() / "reports"
