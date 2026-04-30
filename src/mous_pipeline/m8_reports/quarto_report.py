"""Optional Quarto rendering for subject reports."""

from __future__ import annotations

import logging
import shutil
import subprocess
from pathlib import Path

from ..io import stage_output_dir

_LOG = logging.getLogger(__name__)
_REQUIRED_R_PACKAGES = ("ggplot2", "dplyr", "knitr", "lmerTest", "readr")


def _write_quarto_log(out_dir: Path, lines: list[str]) -> Path:
    """Persist Quarto diagnostics so failures are visible post-run."""
    log_path = out_dir / "quarto_render.log"
    log_path.write_text("\n".join(lines).rstrip() + "\n", encoding="utf-8")
    return log_path


def _check_r_dependencies(out_dir: Path) -> bool:
    """Return True when required R packages are installed and loadable."""
    check_cmd = [
        "Rscript",
        "-e",
        (
            "pkgs <- c('ggplot2','dplyr','knitr','lmerTest','readr'); "
            "missing <- pkgs[!vapply(pkgs, requireNamespace, logical(1), quietly=TRUE)]; "
            "if (length(missing) > 0) {"
            "  cat(paste(missing, collapse=',')); "
            "  quit(status=2)"
            "}"
        ),
    ]
    proc = subprocess.run(check_cmd, check=False, capture_output=True, text=True)
    if proc.returncode == 0:
        return True
    missing = proc.stdout.strip()
    reason = (
        f"Missing required R packages: {missing}."
        if missing
        else "R package dependency check failed."
    )
    log_path = _write_quarto_log(
        out_dir,
        [
            "Quarto render failed before execution.",
            f"Reason: {reason}",
            f"Checked packages: {', '.join(_REQUIRED_R_PACKAGES)}",
            "",
            "[dependency-check stderr]",
            proc.stderr.strip() or "<empty>",
        ],
    )
    _LOG.error("Quarto render failed (R deps) for output dir %s. See %s", out_dir, log_path)
    return False


def render_quarto(subject: str, cfg) -> Path | None:
    """Render the cumulative subject Quarto report when quarto is available."""
    if shutil.which("quarto") is None:
        return None
    root = Path.cwd()
    qmd_path = root / "reports" / "subject_full_report.qmd"
    if not qmd_path.exists():
        return None
    out_dir = stage_output_dir(cfg, subject, "m8_reports")
    exports_dir = out_dir / "exports"
    output_name = f"{subject}_quarto_report.html"
    out_html = out_dir / f"{subject}_quarto_report.html"
    if shutil.which("Rscript") is None:
        log_path = _write_quarto_log(
            out_dir,
            [
                "Quarto render failed before execution.",
                "Reason: Rscript was not found in PATH.",
                f"Template: {qmd_path}",
                f"Output directory: {out_dir}",
            ],
        )
        _LOG.error("Quarto render failed for %s (missing Rscript). See %s", subject, log_path)
        return None
    if not _check_r_dependencies(out_dir):
        return None
    cmd = [
        "quarto",
        "render",
        str(qmd_path),
        "-P",
        f"subject:{subject}",
        "-P",
        f"export_dir:{exports_dir}",
        "--output",
        output_name,
        "--output-dir",
        str(out_dir),
    ]
    proc = subprocess.run(cmd, check=False, capture_output=True, text=True)
    if proc.returncode != 0:
        log_path = _write_quarto_log(
            out_dir,
            [
                f"Command: {' '.join(cmd)}",
                f"Return code: {proc.returncode}",
                "",
                "[stderr]",
                proc.stderr.strip() or "<empty>",
                "",
                "[stdout]",
                proc.stdout.strip() or "<empty>",
            ],
        )
        _LOG.error("Quarto render failed for %s. See %s", subject, log_path)
    return out_html if out_html.exists() else None


def render_quarto_suite(subject: str, cfg) -> list[Path]:
    """Render the cumulative Quarto report and return one output when present."""
    out = render_quarto(subject, cfg)
    return [out] if out is not None else []
