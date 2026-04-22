"""Filesystem helpers for deterministic outputs."""

from __future__ import annotations

from pathlib import Path

from .config import PipelineConfig


def stage_output_dir(cfg: PipelineConfig, subject: str, module_name: str) -> Path:
    path = cfg.derivatives_root / subject / module_name
    path.mkdir(parents=True, exist_ok=True)
    return path


def subject_derivatives_dir(cfg: PipelineConfig, subject: str) -> Path:
    path = cfg.derivatives_root / subject
    path.mkdir(parents=True, exist_ok=True)
    return path
