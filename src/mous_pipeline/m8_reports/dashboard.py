"""Module 8 lightweight HTML reporting."""

from __future__ import annotations

import json
from pathlib import Path

from ..io import stage_output_dir


def render_subject(subject: str, cfg, payload: dict) -> Path:
    out_dir = stage_output_dir(cfg, subject, "m8_reports")
    out_path = out_dir / f"{subject}_report.html"
    pretty = json.dumps(payload, indent=2)
    out_path.write_text(f"<html><body><h1>Subject {subject} report</h1><pre>{pretty}</pre></body></html>")
    return out_path
