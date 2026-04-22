"""Module 8 lightweight HTML reporting."""

from __future__ import annotations

import json
from pathlib import Path

from ..io import stage_output_dir


def render_subject(subject: str, cfg, payload: dict) -> Path:
    out_dir = stage_output_dir(cfg, subject, "m8_reports")
    out_path = out_dir / f"{subject}_report.html"
    pretty = json.dumps(payload, indent=2)
    out_path.write_text(
        f"<html><body>"
        f"<h1>Subject {subject} report</h1>"
        f"<p>Pipeline stage summary, QA metrics, and gating verdict.</p>"
        f"<pre>{pretty}</pre>"
        f"</body></html>"
    )
    return out_path
