"""Optional Quarto rendering for subject and group reports."""

from __future__ import annotations

import logging
import shutil
import subprocess
from pathlib import Path

from ..io import stage_output_dir
from ..paths import reports_dir

_LOG = logging.getLogger(__name__)
_REQUIRED_R_PACKAGES = (
    "ggplot2",
    "dplyr",
    "knitr",
    "jsonlite",
    "lmerTest",
    "readr",
    "rmarkdown",
    "reticulate",
)


def _write_quarto_log(out_dir: Path, lines: list[str]) -> Path:
    """Persist Quarto diagnostics so failures are visible post-run."""
    log_path = out_dir / "quarto_render.log"
    log_path.write_text("\n".join(lines).rstrip() + "\n", encoding="utf-8")
    return log_path


def _check_r_dependencies(out_dir: Path) -> bool:
    """Return True when required R packages are installed and loadable."""
    r_packages = ",".join(f"'{pkg}'" for pkg in _REQUIRED_R_PACKAGES)
    check_cmd = [
        "Rscript",
        "-e",
        (
            f"pkgs <- c({r_packages}); "
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


def _render_quarto_template(
    *,
    qmd_path: Path,
    out_dir: Path,
    output_name: str,
    params: dict[str, str],
    log_context: str,
) -> Path | None:
    if shutil.which("quarto") is None:
        return None
    if not qmd_path.exists():
        return None
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
        _LOG.error("Quarto render failed for %s (missing Rscript). See %s", log_context, log_path)
        return None
    if not _check_r_dependencies(out_dir):
        return None
    log_path = out_dir / "quarto_render.log"
    if log_path.exists():
        log_path.unlink()
    cmd = ["quarto", "render", qmd_path.name]
    for key, value in params.items():
        cmd.extend(["-P", f"{key}:{value}"])
    cmd.extend(["--output", output_name, "--output-dir", str(out_dir)])
    out_html = out_dir / output_name
    proc = subprocess.run(cmd, check=False, capture_output=True, text=True, cwd=qmd_path.parent)
    if proc.returncode != 0:
        log_path = _write_quarto_log(
            out_dir,
            [
                f"Command: {' '.join(cmd)}",
                f"Working directory: {qmd_path.parent}",
                f"Return code: {proc.returncode}",
                "",
                "[stderr]",
                proc.stderr.strip() or "<empty>",
                "",
                "[stdout]",
                proc.stdout.strip() or "<empty>",
            ],
        )
        _LOG.error("Quarto render failed for %s. See %s", log_context, log_path)
    return out_html if out_html.exists() else None


def render_quarto(subject: str, cfg) -> Path | None:
    """Render the cumulative subject Quarto report when quarto is available."""
    qmd_path = reports_dir() / "subject_full_report.qmd"
    out_dir = stage_output_dir(cfg, subject, "m8_reports")
    exports_dir = out_dir / "exports"
    return _render_quarto_template(
        qmd_path=qmd_path,
        out_dir=out_dir,
        output_name=f"{subject}_quarto_report.html",
        params={"subject": subject, "export_dir": str(exports_dir)},
        log_context=subject,
    )


def render_group_quarto(*, derivatives_root: Path, summary_json: Path) -> Path | None:
    """Render the group Quarto report after group summary export."""
    out_dir = derivatives_root / "group_reports"
    out_dir.mkdir(parents=True, exist_ok=True)
    return _render_quarto_template(
        qmd_path=reports_dir() / "group_report.qmd",
        out_dir=out_dir,
        output_name="group_quarto_report.html",
        params={"summary_json": str(summary_json)},
        log_context="group",
    )


def render_quarto_suite(subject: str, cfg) -> list[Path]:
    """Render the cumulative Quarto report and return one output when present."""
    out = render_quarto(subject, cfg)
    return [out] if out is not None else []
