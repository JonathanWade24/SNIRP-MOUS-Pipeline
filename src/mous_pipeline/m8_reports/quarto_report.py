"""Optional Quarto rendering for subject reports."""

from __future__ import annotations

import shutil
import subprocess
from pathlib import Path

from ..io import stage_output_dir


def render_quarto(subject: str, cfg) -> Path | None:
    """Render the subject Quarto report when quarto is available."""
    if shutil.which("quarto") is None:
        return None
    root = Path.cwd()
    qmd_path = root / "reports" / "subject_report.qmd"
    if not qmd_path.exists():
        return None
    out_dir = stage_output_dir(cfg, subject, "m8_reports")
    exports_dir = out_dir / "exports"
    out_html = out_dir / f"{subject}_quarto_report.html"
    cmd = [
        "quarto",
        "render",
        str(qmd_path),
        "-P",
        f"subject:{subject}",
        "-P",
        f"export_dir:{exports_dir}",
        "--output",
        str(out_html),
    ]
    subprocess.run(cmd, check=False, capture_output=True, text=True)
    return out_html if out_html.exists() else None
