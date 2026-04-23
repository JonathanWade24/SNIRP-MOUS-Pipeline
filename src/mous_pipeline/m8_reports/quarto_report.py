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


def render_quarto_suite(subject: str, cfg) -> list[Path]:
    """Render subject + aim-specific Quarto reports when templates exist."""
    if shutil.which("quarto") is None:
        return []
    root = Path.cwd()
    out_dir = stage_output_dir(cfg, subject, "m8_reports")
    exports_dir = out_dir / "exports"
    templates = [
        ("subject_report.qmd", f"{subject}_quarto_report.html"),
        ("aim1_trial_report.qmd", f"{subject}_aim1_report.html"),
        ("aim2_meg_fmri.qmd", f"{subject}_aim2_report.html"),
        ("aim3_waves.qmd", f"{subject}_aim3_report.html"),
    ]
    outputs: list[Path] = []
    for qmd_name, output_name in templates:
        qmd_path = root / "reports" / qmd_name
        if not qmd_path.exists():
            continue
        out_html = out_dir / output_name
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
        if out_html.exists():
            outputs.append(out_html)
    return outputs
