"""CLI entrypoint."""

from __future__ import annotations

import argparse
import importlib.util
import json
import os
import shlex
import shutil
import subprocess
import sys
import time
from pathlib import Path
from urllib.parse import urlsplit

import pandas as pd

from .config import RuntimeOverrides, apply_runtime_overrides, load_config, resolve_runtime_overrides
from .m0_intake.cyberduck import build_duck_download_command, duck_available, execute_duck_command
from .m0_intake.bids_convert import convert_subject_to_bids
from .m0_intake.repocli_rdr import (
    build_repocli_get_command,
    build_repocli_ls_command,
    execute_repocli_command,
    is_valid_mous_subject_id,
    normalize_subject_id,
    parse_repocli_ls_subjects,
    parse_subjects_arg,
    remote_subject_path,
    repocli_available,
)
from .m7_stats.group import run_group_model
from .m8_reports.quarto_report import render_group_quarto
from .m9_orchestration.parallelization_plan import (
    dag_parallelism_report,
    intra_subject_pilot_protocol,
    recommend_subject_parallelism,
)
from .m9_orchestration.runner import run_subject
from .ops.actions import (
    build_bem_submit_cmd,
    build_recon_submit_cmd,
    build_submit_cmd,
    execute_submit_cmd,
    run_cmd,
)
from .ops.models import WorkflowPreset
from .ops.monitor import classify_failure, squeue_jobs, tail_text
from .ops.state import load_state, save_state
from .stage_dependencies import STAGE_ORDER, parallel_execution_fronts


_STAGE_LABELS: dict[str, str] = {
    "m1":       "Parse events",
    "m2":       "Preprocess  (notch · ICA · filter)",
    "m3":       "Epoch",
    "m4":       "Analytic signal + PSD",
    "m4_trial": "Trial features (pre-stim β, N400m)",
    "m5":       "Source reconstruction",
    "m6a":      "Phase-gradient waves + DCI",
    "m6_extra": "CFC / FFT2D / rotational detectors",
    "m10":      "fMRI prep + trial-wise GLM",
    "m11":      "MEG–fMRI coupling",
    "m12":      "Wave-validation null model",
    "m7":       "Statistics (Rayleigh · permutation)",
    "m8":       "Reports + exports",
    "m9":       "Pilot gate (GO / MARGINAL / NO-GO)",
}

_stage_start_times: dict[str, float] = {}
_QUARTO_REQUIRED_R_PACKAGES: tuple[str, ...] = (
    "ggplot2",
    "dplyr",
    "knitr",
    "jsonlite",
    "lmerTest",
    "readr",
    "rmarkdown",
    "reticulate",
)
_GUI_DEPRECATION_MESSAGE = (
    "DEPRECATION: `mous-pipeline gui` (Streamlit/JupyterHub workflow) is deprecated and "
    "scheduled for removal in v0.3.0. Prefer `mous-pipeline run` + `watch` + `verify-run`."
)


def _make_cli_progress_callback(selected_stages: list[str]):
    total = len(selected_stages)
    _t0 = time.time()
    _exec_index_by_stage: dict[str, int] = {}
    _next_exec_index = 0

    def _cb(event: str, stage: str) -> None:
        nonlocal _next_exec_index
        label = _STAGE_LABELS.get(stage, stage)
        elapsed = time.time() - _t0
        elapsed_str = f"{int(elapsed // 60)}m {int(elapsed % 60):02d}s" if elapsed >= 60 else f"{elapsed:.1f}s"
        if event == "start":
            _next_exec_index += 1
            _exec_index_by_stage[stage] = _next_exec_index
            idx = _next_exec_index
            _stage_start_times[stage] = time.time()
            print(
                f"\r  ┌ [{idx:02d}/{total:02d}] {label} …",
                file=sys.stderr, flush=True,
            )
        else:
            idx = _exec_index_by_stage.get(stage)
            if idx is None:
                return
            stage_dur = time.time() - _stage_start_times.pop(stage, time.time())
            dur_str = f"{int(stage_dur // 60)}m {int(stage_dur % 60):02d}s" if stage_dur >= 60 else f"{stage_dur:.1f}s"
            pct = int(idx / total * 100)
            remaining = total - idx
            print(
                f"  └ [{idx:02d}/{total:02d}] {label}  "
                f"{dur_str}  (total {elapsed_str}, {remaining} stage{'s' if remaining != 1 else ''} left)",
                file=sys.stderr, flush=True,
            )

    return _cb


def _run_state_candidates(derivatives_root: Path, subject: str) -> list[Path]:
    sid = subject.removeprefix("sub-")
    return [
        derivatives_root / sid / "m9_orchestration" / f"sub-{sid}_run_state.json",
        derivatives_root / f"sub-{sid}" / "m9_orchestration" / f"sub-{sid}_run_state.json",
    ]


def _run_log_candidates(derivatives_root: Path, subject: str) -> list[Path]:
    sid = subject.removeprefix("sub-")
    return [
        derivatives_root / sid / "m9_orchestration" / f"sub-{sid}_run_live.log",
        derivatives_root / f"sub-{sid}" / "m9_orchestration" / f"sub-{sid}_run_live.log",
    ]


def _failed_run_state_payload(
    existing: dict | None,
    *,
    subject: str,
    selected_stages: list[str],
    error: Exception,
    now: float | None = None,
) -> dict:
    """Build a failed run_state payload while preserving stage progress."""
    payload = dict(existing or {})
    timestamp = time.time() if now is None else now
    payload.update(
        {
            "subject": payload.get("subject") or subject,
            "status": "failed",
            "selected_stages": payload.get("selected_stages") or selected_stages,
            "current_stage": None,
            "current_stage_description": None,
            "current_stage_started_at": None,
            "stage_index": payload.get("stage_index") or 0,
            "stage_total": payload.get("stage_total") or len(selected_stages),
            "completed_stages": payload.get("completed_stages") or [],
            "stage_timings_s": payload.get("stage_timings_s") or {},
            "error": str(error),
            "started_at": payload.get("started_at") or timestamp,
            "updated_at": timestamp,
            "last_event": "failed",
        }
    )
    return payload


def _run_manifest_candidates(derivatives_root: Path, subject: str) -> list[Path]:
    sid = subject.removeprefix("sub-")
    return [
        derivatives_root / sid / "m9_orchestration" / f"sub-{sid}_run_manifest.json",
        derivatives_root / f"sub-{sid}" / "m9_orchestration" / f"sub-{sid}_run_manifest.json",
    ]


def _latest_existing_path(candidates: list[Path]) -> Path | None:
    existing = [p for p in candidates if p.exists()]
    if not existing:
        return None
    return max(existing, key=lambda p: p.stat().st_mtime_ns)


def _ordered_unique(values: list[str]) -> list[str]:
    seen: set[str] = set()
    result: list[str] = []
    for value in values:
        if value and value not in seen:
            seen.add(value)
            result.append(value)
    return result


def _write_subject_manifest(path: Path, *, collection_path: str, subjects: list[str], skipped_invalid: list[str]) -> None:
    payload = {
        "collection_path": collection_path,
        "n_subjects": len(subjects),
        "subjects": subjects,
        "skipped_invalid": skipped_invalid,
        "generated_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
    }
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2) + "\n")


def _fmt_dur(seconds: float) -> str:
    if seconds < 60:
        return f"{seconds:.0f}s"
    m, s = divmod(int(seconds), 60)
    return f"{m}m {s:02d}s"


def _collect_stage_warnings(metrics: dict) -> list[str]:
    """Return human-readable warnings for degraded per-stage failures.

    Accepts a metrics dict (from run_manifest.json → metrics, or from
    SubjectResult.metrics).  These are errors that don't necessarily abort the pipeline
    but must be visible to the operator after the run completes.
    """
    warnings: list[str] = []
    m5_err = metrics.get("m5_error")
    if m5_err:
        warnings.append(
            f"m5 (source reconstruction) failed - m5_error={m5_err!r}. "
            "Source-space outputs were not produced."
        )
    m5_skip = metrics.get("m5_skipped_reason")
    if m5_skip:
        warnings.append(f"m5 skipped - {m5_skip}")
    m10_err = metrics.get("m10_error")
    if m10_err:
        warnings.append(
            f"m10 (fMRI GLM) failed — m10_error={m10_err!r}. "
            "MEG-fMRI trial table was not produced; downstream stages may be blocked."
        )
    m10_skip = metrics.get("m10_skipped_reason")
    if m10_skip:
        warnings.append(f"m10 skipped — {m10_skip}")
    m11_skip = metrics.get("m11_skipped_reason")
    if m11_skip:
        warnings.append(f"m11 skipped — {m11_skip}")
    return warnings


def _verify_run_manifest(
    manifest_payload: dict,
    *,
    require_skip_m5: bool = False,
    require_m5: bool = False,
    strict_mode: bool = False,
) -> list[str]:
    errors: list[str] = []
    metrics = manifest_payload.get("metrics", {}) if isinstance(manifest_payload, dict) else {}
    run_status = str(metrics.get("run_status") or "")
    if run_status not in {"done", "completed_with_skips"}:
        errors.append(f"run_status must be done/completed_with_skips, got {run_status!r}")
    skipped = metrics.get("skipped_stages") or []
    if require_skip_m5 and "m5" not in skipped:
        errors.append("m5 must be present in skipped_stages (--require-skip-m5)")
    if require_m5:
        if "m5" in skipped:
            errors.append("m5 must not be skipped (--require-m5)")
        m5_err = metrics.get("m5_error")
        if m5_err:
            errors.append(f"m5 completed with error (--require-m5): {m5_err!r}")
        if not metrics.get("source_dci_zinnen") and not metrics.get("m5_n_stcs"):
            errors.append(
                "m5 produced no source-space outputs: source_dci_zinnen and m5_n_stcs both absent"
            )
    if strict_mode:
        if metrics.get("m10_error"):
            errors.append("strict verification failed: m10_error present")
        if metrics.get("m11_error"):
            errors.append("strict verification failed: m11_error present")
    # Top-level outputs may be omitted depending on manifest shape/version.
    # Validate type only when present; do not fail solely on missing outputs.
    outputs = manifest_payload.get("outputs", None)
    if outputs is not None and not isinstance(outputs, list):
        errors.append("manifest outputs must be a list when present")
    return errors


def _print_watch_line(payload: dict, *, use_carriage_return: bool = True) -> None:
    idx = int(payload.get("stage_index") or 0)
    total = int(payload.get("stage_total") or 0)
    status = str(payload.get("status") or "unknown")
    current_id = payload.get("current_stage") or ""
    current_desc = str(payload.get("current_stage_description") or "").strip()
    done = len(payload.get("completed_stages") or [])
    started_at = float(payload.get("started_at") or time.time())
    stage_started_at = payload.get("current_stage_started_at")
    elapsed = max(0.0, time.time() - started_at)
    stage_elapsed = max(0.0, time.time() - float(stage_started_at)) if stage_started_at else 0.0

    # Unicode block-element bar
    bar_w = 24
    filled_f = (done / max(total, 1)) * bar_w
    filled = int(filled_f)
    partial_eighths = int((filled_f - filled) * 8)
    partial_chars = " ▏▎▍▌▋▊▉█"
    bar = "█" * filled + (partial_chars[partial_eighths] if filled < bar_w else "") + " " * max(0, bar_w - filled - 1)
    pct = int((done / max(total, 1)) * 100)

    # Human-readable labels
    current_label = _STAGE_LABELS.get(current_id, current_id) if current_id else "—"
    status_icon = {
        "running": "⏳",
        "done": "✓",
        "completed_with_skips": "!",
        "failed": "✗",
        "dry_run": "⊙",
    }.get(status, "·")

    if status == "done":
        line = f"{status_icon} Done  [{bar}] {pct}%  {done}/{total} stages  total {_fmt_dur(elapsed)}"
    elif status == "failed":
        err = payload.get("error") or ""
        first_line = err.splitlines()[-1][:60] if err else "unknown error"
        line = f"{status_icon} Failed after {_fmt_dur(elapsed)} — {first_line}"
    else:
        line = (
            f"{status_icon} [{bar}] {pct:3d}%  {done}/{total}  "
            f"now: {current_label}  ({_fmt_dur(stage_elapsed)})  "
            f"total {_fmt_dur(elapsed)}"
        )
        if current_desc:
            line += f"  — {current_desc}"

    if use_carriage_return and status == "running":
        print(f"\r{line}", end="", flush=True)
    else:
        print(line)


def _run_bids_validate(root: Path, *, subject: str | None = None, verbose: bool = False) -> None:
    """Validate a BIDS dataset using mne_bids (no Node/external tools required).

    Checks:
    - Required top-level files (dataset_description.json, README).
    - File naming via bids_validator.BIDSValidator.is_bids() on every file.
    - Subject layout via mne_bids.get_entity_vals().
    - Prints mne_bids.make_report() summary paragraph.
    - Exits non-zero on any naming error.
    """
    try:
        import mne_bids
        from bids_validator import BIDSValidator
    except ImportError as exc:
        print(f"Missing dependency for mne_bids-based validation: {exc}", file=sys.stderr)
        sys.exit(1)

    print(f"Validating BIDS dataset at: {root}")
    errors: list[str] = []
    warnings_list: list[str] = []

    # ── Required top-level files ──────────────────────────────────────────────
    for required in ("dataset_description.json",):
        if not (root / required).exists():
            errors.append(f"Missing required file: {required}")
    for recommended in ("README", "participants.tsv"):
        if not (root / recommended).exists():
            warnings_list.append(f"Missing recommended file: {recommended}")

    # ── File naming via BIDSValidator ─────────────────────────────────────────
    bv = BIDSValidator()
    subject_filter = subject.removeprefix("sub-") if subject else None
    n_checked = 0
    n_valid = 0
    for f in sorted(root.rglob("*")):
        if not f.is_file():
            continue
        rel_parts = f.relative_to(root).parts
        # Skip derivatives, hidden files, and files inside CTF .ds containers
        # (those are raw data internals, not BIDS-level files).
        if any(
            part.startswith(".")
            or part == "derivatives"
            or part.endswith(".ds")
            for part in rel_parts
        ):
            continue
        rel = "/" + f.relative_to(root).as_posix()
        if subject_filter and f"sub-{subject_filter}" not in rel:
            continue
        n_checked += 1
        if bv.is_bids(rel):
            n_valid += 1
        elif verbose:
            warnings_list.append(f"Non-BIDS filename: {rel}")

    # ── Subject layout ────────────────────────────────────────────────────────
    try:
        subjects = mne_bids.get_entity_vals(root, "subject", verbose=False)
        print(f"Subjects found   : {len(subjects)} — {subjects}")
        # Infer datatypes from directory names (anat, meg, func, eeg, ieeg).
        _known_datatypes = {"anat", "meg", "func", "eeg", "ieeg", "dwi", "fmap", "beh", "pet"}
        datatypes = sorted({
            p.name for p in root.rglob("*")
            if p.is_dir() and p.name in _known_datatypes
        })
        if datatypes:
            print(f"Datatypes found  : {datatypes}")
    except Exception as exc:
        warnings_list.append(f"mne_bids layout scan warning: {exc}")

    # ── make_report summary ───────────────────────────────────────────────────
    import warnings as _warnings
    try:
        with _warnings.catch_warnings():
            _warnings.simplefilter("ignore")
            report = mne_bids.make_report(root, verbose=False)
        scope = f"subject {subject_filter}" if subject_filter else "full dataset"
        print(f"\n── Dataset report ({scope}) ──")
        print(report)
    except Exception as exc:
        warnings_list.append(f"make_report skipped: {exc}")

    # ── Results ───────────────────────────────────────────────────────────────
    print(f"\n── Naming check: {n_valid}/{n_checked} files pass BIDS naming rules ──")
    if warnings_list:
        print("\nWarnings:")
        for w in warnings_list:
            print(f"  ⚠  {w}")
    if errors:
        print("\nErrors:")
        for e in errors:
            print(f"  ✗  {e}", file=sys.stderr)
        sys.exit(1)
    print("\n✓ No hard BIDS errors detected by mne_bids validation.")


def _check_quarto_env() -> tuple[bool, list[str]]:
    """Check Quarto + R runtime needed by cumulative subject report."""
    messages: list[str] = []
    r_packages = ",".join(f"'{pkg}'" for pkg in _QUARTO_REQUIRED_R_PACKAGES)
    r_package_label = ", ".join(_QUARTO_REQUIRED_R_PACKAGES)
    quarto_path = shutil.which("quarto")
    if quarto_path is None:
        messages.append("missing binary: quarto (install Quarto >=1.5 and ensure it is on PATH)")
    else:
        messages.append(f"quarto: {quarto_path}")

    rscript_path = shutil.which("Rscript")
    if rscript_path is None:
        messages.append("missing binary: Rscript (install R and ensure it is on PATH)")
        return False, messages
    messages.append(f"Rscript: {rscript_path}")

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
        messages.append(f"R packages: OK ({r_package_label})")
    else:
        missing = proc.stdout.strip()
        if missing:
            messages.append(f"missing R packages: {missing}")
        else:
            messages.append("R package check failed (could not resolve missing package list)")
        if proc.stderr.strip():
            messages.append(f"Rscript stderr: {proc.stderr.strip()}")

    ok = quarto_path is not None and rscript_path is not None and proc.returncode == 0
    return ok, messages


def main() -> None:
    parser = argparse.ArgumentParser(description="MOUS pipeline")
    sub = parser.add_subparsers(dest="cmd", required=True)

    run_parser = sub.add_parser("run", help="Run subject pipeline")
    run_parser.add_argument("--config", required=True)
    run_parser.add_argument("--subject", required=True)
    run_parser.add_argument("--only", default="", help="Comma-separated stage names to run")
    run_parser.add_argument("--skip", default="", help="Comma-separated stage names to skip")
    run_parser.add_argument("--force", action="store_true", help="Ignore existing outputs and recompute")
    run_parser.add_argument("--dry-run", action="store_true", help="Print resolved run plan without processing data")
    run_parser.add_argument("--include-fmri", action="store_true", help="Include m10/m11 stages")
    run_parser.add_argument("--include-waves-validation", action="store_true", help="Include m12 stage")
    run_parser.add_argument(
        "--reuse-fmriprep",
        action="store_true",
        help="When m10 is selected, reuse existing fMRIPrep derivatives instead of rerunning fMRIPrep.",
    )
    run_parser.add_argument(
        "--allow-m11-from-cached-joined",
        action="store_true",
        help="Allow m11 to load an existing m10 joined table when m10 does not produce one in this run.",
    )
    run_parser.add_argument(
        "--assume-upstream-done",
        action="store_true",
        help="Bypass stage dependency validation when selected stages rely on upstream outputs completed externally.",
    )
    run_parser.add_argument(
        "--memory-profile",
        action="store_true",
        help="Log RSS at stage boundaries and poll for peak RSS (Linux: /proc/self/status; see memory_rss_summary in manifest)",
    )
    run_parser.add_argument(
        "--memory-profile-interval",
        type=float,
        default=0.5,
        help="Seconds between background RSS samples when --memory-profile is set",
    )
    run_parser.add_argument(
        "--preflight-quarto-env",
        action="store_true",
        help="Before running, verify Quarto + R dependencies used by m8 cumulative reports.",
    )

    plan_parser = sub.add_parser(
        "parallelization-plan",
        help="Print DAG parallel fronts, subject-parallel cap from peak RSS, and intra-subject pilot protocol",
    )
    plan_parser.add_argument(
        "--only",
        default="",
        help="Comma-separated stages (subset of pipeline); default is full STAGE_ORDER",
    )
    plan_parser.add_argument("--total-ram-gb", type=float, default=32.0, help="Machine RAM budget (default 32)")
    plan_parser.add_argument(
        "--os-reserve-gb",
        type=float,
        default=6.0,
        help="RAM to reserve for OS / buffers (default 6)",
    )
    plan_parser.add_argument(
        "--peak-rss-gb",
        type=float,
        default=None,
        help="Peak RSS for one full subject run (from memory_rss_summary); if omitted, only DAG + pilot text are printed",
    )
    plan_parser.add_argument("--n-cpus", type=int, default=6, help="CPU count for OMP hint (default 6)")
    watch_parser = sub.add_parser("watch", help="Watch live run state from run_state.json")
    watch_parser.add_argument("--config", required=True)
    watch_parser.add_argument("--subject", required=True)
    watch_parser.add_argument("--interval", type=float, default=2.0, help="Polling interval in seconds")
    watch_parser.add_argument("--verbose", action="store_true", help="Tail live run log while watching state")
    verify_parser = sub.add_parser("verify-run", help="Verify run manifest invariants")
    verify_parser.add_argument("--config", required=True)
    verify_parser.add_argument("--subject", required=True)
    verify_parser.add_argument("--require-skip-m5", action="store_true", help="Require m5 to be skipped")
    verify_parser.add_argument(
        "--require-m5",
        action="store_true",
        help="Require m5 (source reconstruction) to have run and produced outputs",
    )
    verify_parser.add_argument(
        "--strict-mode",
        action="store_true",
        help="Fail verification when m10_error/m11_error are present",
    )

    fetch_parser = sub.add_parser("fetch-subject", help="Build or execute Cyberduck duck download command")
    fetch_parser.add_argument("--subject", required=True, help="Subject ID without sub- prefix, e.g., A2003")
    fetch_parser.add_argument("--protocol", default="sftp", help="Remote protocol, e.g., sftp, ftp, webdav")
    fetch_parser.add_argument("--host", required=True, help="Remote host")
    fetch_parser.add_argument("--remote-root", required=True, help="Remote directory containing subject tarballs")
    fetch_parser.add_argument("--local-root", default=".", help="Local destination directory")
    fetch_parser.add_argument("--username", default=None, help="Optional remote username")
    fetch_parser.add_argument(
        "--execute",
        action="store_true",
        help="Execute duck command immediately (requires duck installed and authentication configured)",
    )

    rdr_parser = sub.add_parser(
        "fetch-rdr",
        help="Download a subject folder from RDR via repocli (run `repocli config` once; base URL https://webdav.data.ru.nl)",
    )
    rdr_parser.add_argument("--config", default=None, help="YAML config with rdr.collection_path and data_root")
    rdr_parser.add_argument("--subject", default=None, help="Subject ID, e.g., A2002 or sub-A2002")
    rdr_parser.add_argument("--subjects", default="", help="Comma/whitespace-separated subject IDs")
    rdr_parser.add_argument(
        "--all-config-subjects",
        action="store_true",
        help="Fetch every subject listed under config subjects:",
    )
    rdr_parser.add_argument(
        "--all-remote-subjects",
        action="store_true",
        help="List rdr.collection_path with repocli and fetch every valid sub-A#### subject found",
    )
    rdr_parser.add_argument(
        "--manifest-out",
        default=None,
        help="Optional JSON path where the resolved valid subject manifest is written",
    )
    rdr_parser.add_argument(
        "--skip-invalid",
        action="store_true",
        help="Skip invalid subject IDs and failed per-subject downloads instead of aborting the whole fetch batch",
    )
    rdr_parser.add_argument(
        "--collection-path",
        default=None,
        help="RDR path under WebDAV root, e.g., dccn/DSC_3011020.09_236_v1 (overrides config)",
    )
    rdr_parser.add_argument(
        "--dest",
        default=None,
        help="Local directory where sub-*/ will be placed (default: config data_root or current directory)",
    )
    rdr_parser.add_argument(
        "--execute",
        action="store_true",
        help="Run repocli immediately (otherwise print the command only)",
    )
    group_parser = sub.add_parser("group", help="Run group-level stats across subject manifests")
    group_parser.add_argument(
        "--derivatives-root",
        default="derivatives/mous_pipeline",
        help="Derivatives root containing <subject>/m9_orchestration/*_run_manifest.json",
    )
    group_parser.add_argument("--test", default="wilcoxon", choices=["wilcoxon", "lme"])
    group_parser.add_argument(
        "--subjects",
        default="",
        help="Optional comma-separated subject IDs to include (e.g. A2002,A2003)",
    )
    group_parser.add_argument(
        "--quarto-only",
        action="store_true",
        help="Skip group model recompute and only render group Quarto from existing group_summary.json",
    )
    bids_convert_parser = sub.add_parser("bids-convert", help="Add in-place BIDS metadata sidecars for a subject")
    bids_convert_parser.add_argument("--config", required=True)
    bids_convert_parser.add_argument("--subject", required=True, help="Subject ID, e.g., A2002 or sub-A2002")
    bids_validate_parser = sub.add_parser(
        "bids-validate",
        help="Check BIDS layout with mne_bids and bids_validator (not the Node CLI)",
    )
    bids_validate_parser.add_argument("--config", default=None, help="YAML config path (uses data_root when set)")
    bids_validate_parser.add_argument("--root", default=None, help="Override BIDS root path")
    bids_validate_parser.add_argument("--subject", default=None, help="Optional subject filter, e.g., A2003")
    bids_validate_parser.add_argument(
        "--verbose",
        action="store_true",
        help="Log each non-BIDS filename under the naming check",
    )
    quarto_check_parser = sub.add_parser(
        "check-quarto-env",
        help="Check Quarto + R runtime dependencies for cumulative report rendering",
    )
    gui_parser = sub.add_parser(
        "gui",
        help="Launch Streamlit GUI with printed access URLs (deprecated; remove in v0.3.0)",
    )
    gui_parser.add_argument("--port", type=int, default=8501, help="Port to run Streamlit on")
    gui_parser.add_argument(
        "--config",
        default="configs/pilot_A2002.yaml",
        help="Config path preloaded in GUI via MOUS_GUI_CONFIG env var",
    )
    gui_parser.add_argument(
        "--base-url-path",
        default="",
        help="Optional Streamlit base URL path override. "
        "Default is empty, which is correct for JupyterHub proxy rewrite setups.",
    )
    gui_parser.add_argument(
        "--public-base-url",
        default=None,
        help="Optional public host URL (e.g. https://snirp24.neurodesk.org). "
        "When omitted, the CLI auto-detects host from JupyterHub env vars.",
    )
    ops_parser = sub.add_parser("ops", help="SSH-first operations interface")
    ops_sub = ops_parser.add_subparsers(dest="ops_cmd")
    ops_sub.add_parser("ui", help="Launch full-screen TUI")
    ops_run = ops_sub.add_parser("run", help="Non-interactive ops runner")
    ops_run.add_argument("--preset", required=True)
    ops_run.add_argument("--config", default="configs/palmetto_hpcnirc_fmri.yaml")
    ops_run.add_argument("--subjects", required=True, help="Comma-separated subject IDs")
    ops_run.add_argument("--account", default="")
    ops_run.add_argument("--partition", default="hpcnirc")
    ops_run.add_argument("--time", default="12:00:00")
    ops_run.add_argument("--mem", default="128G")
    ops_run.add_argument("--cpus-per-task", default="8")
    ops_run.add_argument("--fetch-missing", dest="fetch_missing", action="store_true")
    ops_run.add_argument("--no-fetch-missing", dest="fetch_missing", action="store_false")
    ops_run.add_argument("--include-m5", dest="include_m5", action="store_true")
    ops_run.add_argument("--no-include-m5", dest="include_m5", action="store_false")
    ops_run.add_argument("--dry-run", dest="ops_dry_run", action="store_true")
    ops_run.add_argument("--no-dry-run", dest="ops_dry_run", action="store_false")
    ops_run.set_defaults(fetch_missing=None, include_m5=None, ops_dry_run=None)
    ops_run.add_argument("--execute", action="store_true")
    ops_status = ops_sub.add_parser("status", help="Show persisted recent jobs")
    ops_status.add_argument("--limit", type=int, default=20)
    ops_monitor = ops_sub.add_parser("monitor", help="Poll queue/accounting and classify log snippets")
    ops_monitor.add_argument("--job-id", default="")
    ops_monitor.add_argument("--log-file", default="")
    ops_config = ops_sub.add_parser("config", help="List/select ops config files")
    ops_config_sub = ops_config.add_subparsers(dest="ops_config_cmd")
    ops_config_sub.add_parser("list", help="List config YAML files under ./configs")
    ops_config_show = ops_config_sub.add_parser("show", help="Show currently selected ops config")
    ops_config_use = ops_config_sub.add_parser("use", help="Set default ops config path")
    ops_config_use.add_argument("--path", required=True, help="Path to config YAML")
    ops_recon = ops_sub.add_parser("prep-m5", help="Submit recon-all array job to build source subjects_dir")
    ops_recon.add_argument("--config", default="configs/palmetto_hpcnirc_fmri.yaml")
    ops_recon.add_argument("--subjects", required=True, help="Comma-separated subject IDs")
    ops_recon.add_argument("--account", default="")
    ops_recon.add_argument("--partition", default="hpcnirc")
    ops_recon.add_argument("--time", default="12:00:00")
    ops_recon.add_argument("--mem", default="16G")
    ops_recon.add_argument("--cpus-per-task", default="4")
    ops_recon.add_argument("--with-bem", action="store_true", help="Chain BEM prep after recon-all succeeds")
    ops_recon.add_argument("--bem-time", default="04:00:00")
    ops_recon.add_argument("--bem-mem", default="16G")
    ops_recon.add_argument("--bem-cpus-per-task", default="2")
    ops_recon.add_argument("--execute", action="store_true")
    ops_bem = ops_sub.add_parser("prep-bem", help="Submit BEM generation array job (inner/outer skull/skin surfaces)")
    ops_bem.add_argument("--config", default="configs/palmetto_hpcnirc_fmri.yaml")
    ops_bem.add_argument("--subjects", required=True, help="Comma-separated subject IDs")
    ops_bem.add_argument("--account", default="")
    ops_bem.add_argument("--partition", default="hpcnirc")
    ops_bem.add_argument("--time", default="04:00:00")
    ops_bem.add_argument("--mem", default="16G")
    ops_bem.add_argument("--cpus-per-task", default="2")
    ops_bem.add_argument("--dependency", default="", help="Optional sbatch dependency (e.g. afterok:12345)")
    ops_bem.add_argument("--execute", action="store_true")

    args = parser.parse_args()

    if args.cmd == "run":
        cfg = load_config(args.config)
        sid = args.subject.removeprefix("sub-")
        state_candidates = _run_state_candidates(cfg.derivatives_root, sid)
        only = {s.strip() for s in args.only.split(",") if s.strip()} or None
        skip = {s.strip() for s in args.skip.split(",") if s.strip()} or None
        # --include-fmri / --include-waves-validation are additive: they expand an
        # explicit --only list.  When --only was not given (only=None) the runner
        # already selects every stage, so the flags are a no-op.
        if args.include_fmri and only is not None:
            only = only | {"m10", "m11"}
        if args.include_waves_validation and only is not None:
            only = only | {"m12"}
        resolved_overrides = resolve_runtime_overrides(
            RuntimeOverrides(),
            RuntimeOverrides(
                dry_run=True if args.dry_run else None,
                reuse_fmriprep=True if args.reuse_fmriprep else None,
                allow_m11_cached_joined=True if args.allow_m11_from_cached_joined else None,
            ),
        )
        apply_runtime_overrides(cfg, resolved_overrides)
        selected = [s for s in STAGE_ORDER if (not only or s in only) and (not skip or s not in skip)]
        if args.preflight_quarto_env and "m8" in selected:
            ok, messages = _check_quarto_env()
            print("Quarto preflight:")
            for msg in messages:
                print(f"- {msg}")
            if not ok:
                print(
                    "Quarto preflight failed. Install R/R packages before full run.",
                    file=sys.stderr,
                )
                sys.exit(2)
        try:
            result = run_subject(
                args.subject,
                cfg,
                only=only,
                skip=skip,
                force=args.force,
                dry_run=bool(resolved_overrides.dry_run),
                config_path=Path(args.config),
                progress_event_callback=_make_cli_progress_callback(selected),
                memory_profile=args.memory_profile,
                memory_profile_interval_s=args.memory_profile_interval,
                assume_upstream_done=args.assume_upstream_done,
            )
        except Exception as exc:
            state_path = next((p for p in state_candidates if p.exists()), state_candidates[0])
            state_path.parent.mkdir(parents=True, exist_ok=True)
            existing_state = None
            if state_path.exists():
                try:
                    loaded = json.loads(state_path.read_text())
                    if isinstance(loaded, dict):
                        existing_state = loaded
                except Exception:
                    existing_state = None
            failed_payload = _failed_run_state_payload(
                existing_state,
                subject=sid,
                selected_stages=selected,
                error=exc,
            )
            state_path.write_text(json.dumps(failed_payload, indent=2))
            raise
        print(result.summary())
    elif args.cmd == "parallelization-plan":
        only_set = {s.strip() for s in args.only.split(",") if s.strip()} or None
        selected = [s for s in STAGE_ORDER if not only_set or s in only_set]
        try:
            fronts = parallel_execution_fronts(selected)
        except ValueError as exc:
            print(str(exc), file=sys.stderr)
            sys.exit(2)
        print("Parallel execution fronts (DAG layers; same layer may overlap in time if rescheduled):\n")
        for i, front in enumerate(fronts, start=1):
            print(f"  Front {i}: {', '.join(front)}")
        print("\n" + json.dumps(dag_parallelism_report(selected), indent=2))
        if args.peak_rss_gb is not None:
            rec = recommend_subject_parallelism(
                total_ram_gb=args.total_ram_gb,
                os_reserve_gb=args.os_reserve_gb,
                peak_rss_gb=args.peak_rss_gb,
                n_cpus=args.n_cpus,
            )
            print("\nSubject-parallel recommendation:\n" + json.dumps(rec, indent=2))
        else:
            print(
                "\n(Re-run with --peak-rss-gb <value> after a subject run with --memory-profile "
                "to print N_subjects_max_conservative and OMP hint.)",
                file=sys.stderr,
            )
        print("\nIntra-subject two-worker pilot protocol:\n" + json.dumps(intra_subject_pilot_protocol(), indent=2))
    elif args.cmd == "watch":
        cfg = load_config(args.config)
        candidates = _run_state_candidates(cfg.derivatives_root, args.subject)
        log_candidates = _run_log_candidates(cfg.derivatives_root, args.subject)
        state_path = _latest_existing_path(candidates) or candidates[0]
        log_path = _latest_existing_path(log_candidates) or log_candidates[0]
        print(f"Watching: {state_path}")
        last_mtime_ns = -1
        log_offset = 0
        while True:
            state_path = _latest_existing_path(candidates) or candidates[0]
            log_path = _latest_existing_path(log_candidates) or log_candidates[0]
            if not state_path.exists():
                print("\rWaiting for run_state.json...", end="", flush=True)
                time.sleep(max(0.2, args.interval))
                continue
            stat = state_path.stat()
            if stat.st_mtime_ns == last_mtime_ns:
                time.sleep(max(0.2, args.interval))
                continue
            last_mtime_ns = stat.st_mtime_ns
            try:
                payload = json.loads(state_path.read_text())
            except Exception:
                time.sleep(max(0.2, args.interval))
                continue
            status = payload.get("status")
            use_cr = not args.verbose and status == "running"
            _print_watch_line(payload, use_carriage_return=use_cr)
            if args.verbose and log_path.exists():
                with log_path.open("r") as f:
                    f.seek(log_offset)
                    chunk = f.read()
                    log_offset = f.tell()
                if chunk:
                    for line in chunk.rstrip().splitlines():
                        print(f"  {line}")
            if status in {"done", "completed_with_skips", "failed", "dry_run"}:
                if use_cr:
                    print()
                err = payload.get("error")
                if err:
                    print(f"error: {err}", file=sys.stderr)
                # Surface silent per-stage warnings from the run manifest metrics
                manifest_candidates = _run_manifest_candidates(cfg.derivatives_root, args.subject)
                manifest_path = _latest_existing_path(manifest_candidates)
                if manifest_path and manifest_path.exists():
                    try:
                        manifest_metrics = json.loads(manifest_path.read_text()).get("metrics", {})
                        for w in _collect_stage_warnings(manifest_metrics):
                            print(f"warning: {w}", file=sys.stderr)
                    except Exception:
                        pass
                break
    elif args.cmd == "verify-run":
        cfg = load_config(args.config)
        candidates = _run_manifest_candidates(cfg.derivatives_root, args.subject)
        manifest_path = _latest_existing_path(candidates)
        if manifest_path is None or not manifest_path.exists():
            print("No run manifest found for subject.", file=sys.stderr)
            sys.exit(2)
        try:
            payload = json.loads(manifest_path.read_text())
        except Exception as exc:
            print(f"Could not parse manifest: {exc}", file=sys.stderr)
            sys.exit(2)
        errors = _verify_run_manifest(
            payload,
            require_skip_m5=args.require_skip_m5,
            require_m5=args.require_m5,
            strict_mode=args.strict_mode,
        )
        if errors:
            for err in errors:
                print(f"verify-run: {err}", file=sys.stderr)
            sys.exit(1)
        print(f"verify-run: OK ({manifest_path})")
    elif args.cmd == "fetch-subject":
        cmd = build_duck_download_command(
            protocol=args.protocol,
            host=args.host,
            remote_root=args.remote_root,
            subject=args.subject,
            local_root=args.local_root,
            username=args.username,
        )
        print("Duck command:")
        print(" ".join(shlex.quote(c) for c in cmd))
        if not args.execute:
            print("Preview only. Add --execute to run this command.")
            return
        if not duck_available():
            print("duck is not installed or not on PATH. Install Cyberduck CLI first.", file=sys.stderr)
            sys.exit(1)
        proc = execute_duck_command(cmd)
        if proc.stdout:
            print(proc.stdout)
        if proc.returncode != 0:
            if proc.stderr:
                print(proc.stderr, file=sys.stderr)
            sys.exit(proc.returncode)
    elif args.cmd == "fetch-rdr":
        collection_path = args.collection_path
        dest: Path
        cfg = None
        if args.config:
            cfg = load_config(args.config)
            if not collection_path:
                collection_path = cfg.rdr.collection_path
            dest = Path(args.dest) if args.dest else cfg.data_root
        else:
            dest = Path(args.dest) if args.dest else Path(".")
        if not collection_path:
            print(
                "Missing collection path: set rdr.collection_path in config or pass --collection-path.",
                file=sys.stderr,
            )
            sys.exit(1)

        requested: list[str] = []
        if args.subject:
            requested.append(normalize_subject_id(args.subject))
        requested.extend(parse_subjects_arg(args.subjects))
        if args.all_config_subjects:
            if cfg is None:
                print("--all-config-subjects requires --config.", file=sys.stderr)
                sys.exit(2)
            requested.extend(normalize_subject_id(str(s)) for s in cfg.subjects)
        if args.all_remote_subjects:
            if not repocli_available():
                print("repocli is not on PATH. Install from Donders-Institute/dr-tools releases.", file=sys.stderr)
                sys.exit(1)
            ls_cmd = build_repocli_ls_command(collection_path)
            print("Repocli manifest command:")
            print(" ".join(shlex.quote(c) for c in ls_cmd))
            ls_proc = execute_repocli_command(ls_cmd)
            if ls_proc.returncode != 0:
                err = (ls_proc.stderr or "").strip() or (ls_proc.stdout or "").strip() or "unknown repocli error"
                print(f"Failed to list RDR subjects: {err}", file=sys.stderr)
                sys.exit(ls_proc.returncode)
            requested.extend(parse_repocli_ls_subjects(ls_proc.stdout or ""))

        valid_subjects: list[str] = []
        skipped_invalid: list[str] = []
        for subject in _ordered_unique(requested):
            if is_valid_mous_subject_id(subject):
                valid_subjects.append(subject)
            else:
                skipped_invalid.append(subject)

        if skipped_invalid:
            msg = "Skipping invalid subject IDs: " + ", ".join(skipped_invalid)
            if args.skip_invalid:
                print(msg, file=sys.stderr)
            else:
                print(msg + " (pass --skip-invalid to continue)", file=sys.stderr)
                sys.exit(2)

        if args.manifest_out:
            _write_subject_manifest(
                Path(args.manifest_out),
                collection_path=collection_path,
                subjects=valid_subjects,
                skipped_invalid=skipped_invalid,
            )
            print(f"Wrote subject manifest: {args.manifest_out}")

        if not valid_subjects:
            print(
                "No valid subjects resolved. Pass --subject, --subjects, --all-config-subjects, or --all-remote-subjects.",
                file=sys.stderr,
            )
            if args.skip_invalid:
                return
            sys.exit(2)

        print("Repocli command(s) (credentials: repocli config; base URL https://webdav.data.ru.nl):")
        commands = [
            build_repocli_get_command(
                remote_path=remote_subject_path(collection_path, subject),
                local_dir=dest.resolve(),
            )
            for subject in valid_subjects
        ]
        for cmd in commands:
            print(" ".join(shlex.quote(c) for c in cmd))
        if not args.execute:
            print("Preview only. Add --execute to run.")
            return
        if not repocli_available():
            print("repocli is not on PATH. Install from Donders-Institute/dr-tools releases.", file=sys.stderr)
            sys.exit(1)
        dest.mkdir(parents=True, exist_ok=True)
        successes: list[str] = []
        failures: list[tuple[str, int]] = []
        for subject, cmd in zip(valid_subjects, commands):
            proc = execute_repocli_command(cmd)
            if proc.stdout:
                print(proc.stdout)
            if proc.returncode != 0:
                if proc.stderr:
                    print(proc.stderr, file=sys.stderr)
                failures.append((subject, proc.returncode))
                if not args.skip_invalid:
                    sys.exit(proc.returncode)
                print(f"Skipping sub-{subject}: repocli exited {proc.returncode}", file=sys.stderr)
                continue
            successes.append(subject)
        if successes:
            print(f"Downloaded {len(successes)} subject(s): {', '.join(successes)}")
        if failures:
            failed = ", ".join(f"{sid}({code})" for sid, code in failures)
            print(f"Skipped {len(failures)} failed subject fetch(es): {failed}", file=sys.stderr)
    elif args.cmd == "group":
        root = Path(args.derivatives_root)
        selected_subjects = {s.strip().removeprefix("sub-") for s in args.subjects.split(",") if s.strip()}
        out_path = root / "group_summary.json"
        if args.quarto_only:
            if not out_path.exists():
                print(f"group_summary.json not found for --quarto-only: {out_path}", file=sys.stderr)
                sys.exit(2)
            try:
                group_report = render_group_quarto(derivatives_root=root, summary_json=out_path)
                if group_report is not None:
                    print(f"Wrote group report: {group_report}")
            except Exception as exc:
                print(f"Group Quarto report render failed (non-fatal): {exc}", file=sys.stderr)
                sys.exit(1)
            return
        metrics_list = []
        trial_tables = []
        qc_tables = []
        for mf in root.glob("*/m9_orchestration/*_run_manifest.json"):
            try:
                sid = mf.parent.parent.name.removeprefix("sub-")
                if selected_subjects and sid not in selected_subjects:
                    continue
                payload = json.loads(mf.read_text())
                metrics = payload.get("metrics", {})
                if metrics:
                    metrics = dict(metrics)
                    metrics.setdefault("subject_id", sid)
                    metrics_list.append(metrics)
            except Exception:
                continue
        for tf in root.glob("*/m8_reports/exports/*_trials.csv"):
            try:
                df = pd.read_csv(tf)
                if not df.empty:
                    sid = tf.parts[-4].removeprefix("sub-")
                    if selected_subjects and sid not in selected_subjects:
                        continue
                    df["subject"] = sid
                    trial_tables.append(df)
            except Exception:
                continue
        for qf in root.glob("*/m8_reports/exports/*_qc_summary.csv"):
            try:
                qd = pd.read_csv(qf)
                if not qd.empty:
                    sid = qf.parts[-4].removeprefix("sub-")
                    if selected_subjects and sid not in selected_subjects:
                        continue
                    qc_tables.append(qd)
            except Exception:
                continue
        if not metrics_list:
            print("No subject manifests found for group analysis.", file=sys.stderr)
            sys.exit(1)
        summary = run_group_model(metrics_list, test=args.test)
        out_path.write_text(json.dumps(summary, indent=2))
        print(f"Wrote group summary: {out_path}")
        if trial_tables:
            group_trials = pd.concat(trial_tables, ignore_index=True)
            trial_path = root / "group_trials.csv"
            group_trials.to_csv(trial_path, index=False)
            print(f"Wrote group trials: {trial_path}")
        if qc_tables:
            group_qc = pd.concat(qc_tables, ignore_index=True)
            qc_path = root / "group_qc_summary.csv"
            group_qc.to_csv(qc_path, index=False)
            print(f"Wrote group QC summary: {qc_path}")
        try:
            group_report = render_group_quarto(derivatives_root=root, summary_json=out_path)
            if group_report is not None:
                print(f"Wrote group report: {group_report}")
        except Exception as exc:
            print(f"Group Quarto report render failed (non-fatal): {exc}", file=sys.stderr)
    elif args.cmd == "bids-convert":
        cfg = load_config(args.config)
        bids_paths = convert_subject_to_bids(args.subject, cfg)
        print(f"Created/updated BIDS metadata for {len(bids_paths)} recording(s):")
        for bp in bids_paths:
            print(f"- {bp}")
    elif args.cmd == "bids-validate":
        if args.root:
            bids_root = Path(args.root).expanduser().resolve()
        elif args.config:
            bids_root = load_config(args.config).data_root.resolve()
        else:
            bids_root = Path(".").resolve()
        if not bids_root.exists():
            print(f"BIDS root does not exist: {bids_root}", file=sys.stderr)
            sys.exit(1)
        _run_bids_validate(bids_root, subject=args.subject, verbose=args.verbose)
    elif args.cmd == "check-quarto-env":
        ok, messages = _check_quarto_env()
        print("Quarto preflight:")
        for msg in messages:
            print(f"- {msg}")
        if not ok:
            sys.exit(1)
    elif args.cmd == "gui":
        print(_GUI_DEPRECATION_MESSAGE, file=sys.stderr)
        service_prefix = os.environ.get("JUPYTERHUB_SERVICE_PREFIX", "/")
        if args.base_url_path:
            base_url_path = args.base_url_path
        else:
            # Default behavior for Neurodesk/JupyterHub: proxy rewrites path,
            # Streamlit serves at root (no baseUrlPath).
            base_url_path = ""
        cfg_path = str(Path(args.config).expanduser().resolve())
        os.environ["MOUS_GUI_CONFIG"] = cfg_path
        streamlit_bin = shutil.which("streamlit")
        if streamlit_bin:
            cmd = [streamlit_bin]
        else:
            # Prefer the active interpreter when the console-script is missing.
            if importlib.util.find_spec("streamlit") is None:
                print(
                    "Streamlit is not installed in this environment.\n"
                    "Install it with: python -m pip install streamlit",
                    file=sys.stderr,
                )
                sys.exit(1)
            cmd = [sys.executable, "-m", "streamlit"]
        cmd += [
            "run",
            "src/mous_pipeline/gui_streamlit.py",
            "--server.headless",
            "true",
            "--server.port",
            str(args.port),
            "--browser.gatherUsageStats",
            "false",
        ]
        if base_url_path:
            cmd.extend(["--server.baseUrlPath", base_url_path])
        print("Launching MOUS GUI...")
        print(f"Config: {cfg_path}")
        print(f"Port: {args.port}")
        print(f"baseUrlPath: {base_url_path or '(empty)'}")
        print("")
        print("Open one of these URLs:")
        proxy_path = f"{service_prefix.rstrip('/')}/proxy/{args.port}/"
        print(f"- Relative proxy path: {proxy_path}")
        full_urls: list[str] = []
        if args.public_base_url:
            full_urls.append(f"{args.public_base_url.rstrip('/')}{proxy_path}")
        else:
            host_candidates = [
                os.environ.get("JUPYTERHUB_PUBLIC_URL"),
                os.environ.get("JUPYTER_SERVER_URL"),
                os.environ.get("JUPYTERHUB_HOST"),
                os.environ.get("JUPYTERHUB_BASE_URL"),
            ]
            for host in host_candidates:
                if not host:
                    continue
                parsed = urlsplit(host)
                if parsed.scheme and parsed.netloc:
                    full_urls.append(f"{parsed.scheme}://{parsed.netloc}{proxy_path}")
                elif host.startswith("http://") or host.startswith("https://"):
                    full_urls.append(f"{host.rstrip('/')}{proxy_path}")
        for url in dict.fromkeys(full_urls):
            print(f"- Full URL: {url}")
        print(f"- If using local browser from same machine: http://localhost:{args.port}")
        print("")
        print(f"Tip: stop old instances with `lsof -ti :{args.port} | xargs -r kill -9`.")
        subprocess.run(cmd, check=False)
    elif args.cmd == "ops":
        if args.ops_cmd in {None, "ui"}:
            try:
                from .ops import run_ops_app
            except ImportError:
                print(
                    "Textual UI dependency missing.\n"
                    "Install with: python -m pip install textual\n"
                    "Then rerun: mous-pipeline ops ui",
                    file=sys.stderr,
                )
                sys.exit(1)
            run_ops_app()
        elif args.ops_cmd == "status":
            st = load_state()
            for row in st.recent_jobs[: max(1, args.limit)]:
                print(
                    f"{row.submitted_at}  {row.job_id:>10}  {row.job_name:<14}  "
                    f"{row.status:<10}  subjects={','.join(row.subjects) or '-'}"
                )
        elif args.ops_cmd == "run":
            st = load_state()
            preset = st.workflow_presets.get(args.preset)
            if preset is None:
                # allow quick ad-hoc run presets from CLI
                preset = WorkflowPreset(name=args.preset, description="ad-hoc", mode="submit")
            subjects = [s.strip().removeprefix("sub-") for s in args.subjects.split(",") if s.strip()]
            if not subjects:
                print("No subjects specified.", file=sys.stderr)
                sys.exit(2)
            cmd = build_submit_cmd(
                preset,
                config=args.config,
                subjects=subjects,
                account=args.account,
                partition=args.partition,
                time_limit=args.time,
                mem=args.mem,
                cpus_per_task=args.cpus_per_task,
                overrides=RuntimeOverrides(
                    fetch_missing=args.fetch_missing,
                    include_m5=args.include_m5,
                    dry_run=args.ops_dry_run,
                ),
            )
            print("Command:")
            print(" ".join(shlex.quote(c) for c in cmd))
            if not args.execute:
                print("Preview only. Add --execute to run.")
                return
            job, proc = execute_submit_cmd(
                cmd,
                config_path=args.config,
                subjects=subjects,
                kind=f"preset:{preset.name}",
                job_name="mous_driver",
            )
            if proc.stdout:
                print(proc.stdout)
            if proc.stderr:
                print(proc.stderr, file=sys.stderr)
            if proc.returncode != 0:
                sys.exit(proc.returncode)
            if job is not None:
                st.recent_jobs.insert(0, job)
                st.recent_jobs = st.recent_jobs[:40]
                print(f"Tracked job {job.job_id} in ops state.")
            save_state(st)
        elif args.ops_cmd == "monitor":
            queued = squeue_jobs()
            if args.job_id:
                queued = [j for j in queued if j.job_id == args.job_id]
            if queued:
                print("squeue:")
                for j in queued:
                    print(f"{j.job_id:>10}  {j.name:<25}  {j.state:<10}  elapsed={j.elapsed}")
            else:
                print("No matching active jobs in squeue.")
            if args.log_file:
                text = tail_text(Path(args.log_file), lines=120)
                print(f"\nlog tail: {args.log_file}")
                print(text)
                print(f"\nclassification: {classify_failure(text)}")
        elif args.ops_cmd == "config":
            st = load_state()
            subcmd = args.ops_config_cmd or "show"
            if subcmd == "list":
                cfg_dir = Path.cwd() / "configs"
                if not cfg_dir.exists():
                    print(f"No configs directory found at {cfg_dir}")
                    return
                files = sorted(cfg_dir.glob("*.yaml")) + sorted(cfg_dir.glob("*.yml"))
                if not files:
                    print("No config YAML files found in ./configs")
                    return
                print("Available configs:")
                for f in files:
                    rel = f.relative_to(Path.cwd())
                    marker = "  *" if str(rel) == st.last_config else "   "
                    print(f"{marker} {rel}")
            elif subcmd == "show":
                print(f"Current ops config: {st.last_config}")
            elif subcmd == "use":
                p = Path(args.path).expanduser()
                if not p.is_absolute():
                    p = (Path.cwd() / p).resolve()
                if not p.exists():
                    print(f"Config not found: {p}", file=sys.stderr)
                    sys.exit(2)
                try:
                    rel = p.relative_to(Path.cwd())
                    st.last_config = str(rel)
                except ValueError:
                    st.last_config = str(p)
                st.recent_configs = [st.last_config] + [c for c in st.recent_configs if c != st.last_config]
                st.recent_configs = st.recent_configs[:10]
                save_state(st)
                print(f"Set ops default config to: {st.last_config}")
        elif args.ops_cmd == "prep-m5":
            subjects = [s.strip().removeprefix("sub-") for s in args.subjects.split(",") if s.strip()]
            if not subjects:
                print("No subjects specified.", file=sys.stderr)
                sys.exit(2)
            cmd = build_recon_submit_cmd(
                config=args.config,
                subjects=subjects,
                account=args.account,
                partition=args.partition,
                time_limit=args.time,
                mem=args.mem,
                cpus_per_task=args.cpus_per_task,
                dry_run=not args.execute,
            )
            bem_cmd: list[str] | None = None
            if args.with_bem:
                bem_cmd = build_bem_submit_cmd(
                    config=args.config,
                    subjects=subjects,
                    account=args.account,
                    partition=args.partition,
                    time_limit=args.bem_time,
                    mem=args.bem_mem,
                    cpus_per_task=args.bem_cpus_per_task,
                    dry_run=not args.execute,
                )
            print("Command:")
            print(" ".join(shlex.quote(c) for c in cmd))
            if bem_cmd:
                print("Follow-up command (BEM prep):")
                print(" ".join(shlex.quote(c) for c in bem_cmd))
            if not args.execute:
                print("Preview only. Add --execute to run.")
                return
            st = load_state()
            job, proc = execute_submit_cmd(
                cmd,
                config_path=args.config,
                subjects=subjects,
                kind="prep_m5",
                job_name="mous_recon",
            )
            if proc.stdout:
                print(proc.stdout)
            if proc.stderr:
                print(proc.stderr, file=sys.stderr)
            if proc.returncode != 0:
                sys.exit(proc.returncode)
            if job is not None:
                st.recent_jobs.insert(0, job)
                st.recent_jobs = st.recent_jobs[:40]
                print(f"Tracked job {job.job_id} in ops state.")
                save_state(st)
            if args.with_bem:
                dep = f"afterok:{job.job_id}" if job is not None else ""
                bem_cmd_exec = build_bem_submit_cmd(
                    config=args.config,
                    subjects=subjects,
                    account=args.account,
                    partition=args.partition,
                    time_limit=args.bem_time,
                    mem=args.bem_mem,
                    cpus_per_task=args.bem_cpus_per_task,
                    dependency=dep,
                    dry_run=False,
                )
                bem_job, bem_proc = execute_submit_cmd(
                    bem_cmd_exec,
                    config_path=args.config,
                    subjects=subjects,
                    kind="prep_bem",
                    job_name="mous_bem",
                )
                if bem_proc.stdout:
                    print(bem_proc.stdout)
                if bem_proc.stderr:
                    print(bem_proc.stderr, file=sys.stderr)
                if bem_proc.returncode != 0:
                    sys.exit(bem_proc.returncode)
                if bem_job is not None:
                    st.recent_jobs.insert(0, bem_job)
                    st.recent_jobs = st.recent_jobs[:40]
                    print(f"Tracked BEM job {bem_job.job_id} in ops state.")
                    save_state(st)
        elif args.ops_cmd == "prep-bem":
            subjects = [s.strip().removeprefix("sub-") for s in args.subjects.split(",") if s.strip()]
            if not subjects:
                print("No subjects specified.", file=sys.stderr)
                sys.exit(2)
            cmd = build_bem_submit_cmd(
                config=args.config,
                subjects=subjects,
                account=args.account,
                partition=args.partition,
                time_limit=args.time,
                mem=args.mem,
                cpus_per_task=args.cpus_per_task,
                dependency=args.dependency,
                dry_run=not args.execute,
            )
            print("Command:")
            print(" ".join(shlex.quote(c) for c in cmd))
            if not args.execute:
                print("Preview only. Add --execute to run.")
                return
            st = load_state()
            job, proc = execute_submit_cmd(
                cmd,
                config_path=args.config,
                subjects=subjects,
                kind="prep_bem",
                job_name="mous_bem",
            )
            if proc.stdout:
                print(proc.stdout)
            if proc.stderr:
                print(proc.stderr, file=sys.stderr)
            if proc.returncode != 0:
                sys.exit(proc.returncode)
            if job is not None:
                st.recent_jobs.insert(0, job)
                st.recent_jobs = st.recent_jobs[:40]
                print(f"Tracked job {job.job_id} in ops state.")
                save_state(st)


if __name__ == "__main__":
    main()
