"""Module 9 subject runner."""

from __future__ import annotations

import json
import os
from dataclasses import dataclass, field
from pathlib import Path
from time import perf_counter
import time
from typing import Callable

import mne
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd

from ..io import stage_output_dir
from ..m4_features.hilbert import analytic_signal
from ..m4_features.n400m import n400m_amplitude
from ..m4_features.prestim import prestim_beta_power
from ..m4_features.spectral import psd
from ..m0_intake.naming import events_tsv, rest_ds, task_ds
from ..m1_events.parse import make_events_metadata, parse_events
from ..m2_preprocess.filter import apply_band, apply_notch_and_resample
from ..m2_preprocess.ica import fit_and_apply
from ..m3_epoching.rest import make_pseudo_epochs
from ..m3_epoching.task import make_epochs
from ..m5_source.forward import build_forward_model
from ..m5_source.inverse import compute_inverse
from ..m5_source.roi import extract_roi_timeseries, source_positions_xy, stcs_to_matrix
from ..m6_waves.phase_gradient import (
    directional_consistency_index,
    epochs_to_directions,
    get_sensor_positions,
    sliding_dci,
)
from ..m6_waves.cfc import CFCDetector
from ..m6_waves.fft2d import FFT2DDetector
from ..m6_waves.flow_field import FlowFieldDetector
from ..m6_waves.rotational import RotationalDetector
from ..m7_stats.circular import rayleigh_p
from ..m7_stats.permutation import perm_test_dci
from ..m7_stats.trialwise import (
    add_first_trial_control_columns,
    lme_block_control,
    logreg_condition_from_prestim,
    n400m_condition_t,
)
from ..m8_reports.quarto_report import render_quarto
from ..m8_reports.dashboard import render_subject
from ..m8_reports.aim2_report import render_aim2_group, render_aim2_subject
from ..m8_reports.export import export_subject_payload
from ..m11_coupling.regress import MEG_COUPLING_FEATURES, hydrate_meg_features, run_coupling_models
from ..m12_wave_validation.compare import confound_null_dci
from ..m12_wave_validation.simulate import simulate_two_dipoles
from ..provenance import build_run_manifest, config_fingerprint, write_manifest
from ..stage_dependencies import STAGE_ORDER, list_missing_stage_dependencies
from .gating import PilotGate
from .memory_probe import StageRSSProbe

_STAGE_BRIEFS: dict[str, str] = {
    "m1": "Reads event timings and trial labels.",
    "m2": "Cleans MEG data (noise, artifacts, filtering).",
    "m3": "Cuts cleaned MEG into trial-sized chunks.",
    "m4": "Computes beta-band signal and power summaries.",
    "m4_trial": "Builds trial-level MEG features for stats.",
    "m5": "Estimates source-space activity in the brain.",
    "m6a": "Measures traveling-wave direction consistency.",
    "m6_extra": "Runs extra wave detectors for QA metrics.",
    "m7": "Tests whether effects are statistically reliable.",
    "m8": "Builds exports and visual reports.",
    "m9": "Applies pilot decision rules (GO/MARGINAL/NO-GO).",
    "m10": "Runs fMRI preprocessing and trial-level GLM.",
    "m11": "Fits MEG-fMRI coupling models.",
    "m12": "Checks wave effects against a simulation null.",
}

@dataclass
class RunResult:
    subject: str
    metrics: dict = field(default_factory=dict)
    outputs: list[Path] = field(default_factory=list)
    stage_timings_s: dict[str, float] = field(default_factory=dict)
    skipped_stages: list[str] = field(default_factory=list)
    status: str = "done"

    def summary(self) -> str:
        verdict = self.metrics.get("pilot_verdict", "unknown")
        skipped = f", skipped={','.join(self.skipped_stages)}" if self.skipped_stages else ""
        return f"Subject {self.subject}: status={self.status}, pilot verdict={verdict}{skipped}"


def _prestim_n_unique_scale_aware(finite_vals: np.ndarray, sig_figs: int = 8) -> int:
    """Count distinct prestim values without fixed-decimal rounding (scale-free vs ~1e-28 PSD)."""
    v = np.asarray(finite_vals, dtype=float).ravel()
    if v.size == 0:
        return 0
    ax = float(np.max(np.abs(v)))
    if ax == 0.0:
        return int(np.unique(v).size)
    exp = np.floor(np.log10(ax))
    factor = 10 ** (sig_figs - 1 - exp)
    return int(np.unique(np.round(v * factor)).size)


def _prestim_diagnostics(prestim_beta: np.ndarray, y: np.ndarray) -> dict[str, float | int | bool]:
    arr = np.asarray(prestim_beta, dtype=float)
    labels = np.asarray(y, dtype=int)
    finite = np.isfinite(arr)
    finite_vals = arr[finite]
    if finite_vals.size == 0:
        return {
            "n_total": int(arr.size),
            "n_finite": 0,
            "n_unique_finite": 0,
            "std_finite": 0.0,
            "is_degenerate": True,
            "n_class0": int((labels == 0).sum()),
            "n_class1": int((labels == 1).sum()),
        }
    std = float(np.std(finite_vals))
    scale_ref = max(float(np.max(np.abs(finite_vals))), float(np.mean(np.abs(finite_vals))), np.finfo(float).tiny)
    cv = std / scale_ref
    n_unique = _prestim_n_unique_scale_aware(finite_vals)
    n0 = int((labels == 0).sum())
    n1 = int((labels == 1).sum())
    # Absolute 1e-12 was scale-blind (flagged real ~1e-28 PSD spread); use CV + sig-fig uniqueness.
    is_low_variance = (std == 0.0) or (cv <= 1e-14)
    is_degenerate = is_low_variance or (n_unique <= 1) or (min(n0, n1) == 0)
    return {
        "n_total": int(arr.size),
        "n_finite": int(finite_vals.size),
        "n_unique_finite": n_unique,
        "std_finite": std,
        "prestim_cv": float(cv),
        "min_finite": float(np.min(finite_vals)),
        "max_finite": float(np.max(finite_vals)),
        "is_degenerate": bool(is_degenerate),
        "n_class0": n0,
        "n_class1": n1,
    }


def _guarded_prestim_auc(prestim_beta: np.ndarray, y: np.ndarray) -> tuple[float, str | None, dict[str, float | int | bool]]:
    diag = _prestim_diagnostics(prestim_beta, y)
    if bool(diag.get("is_degenerate", False)):
        return float("nan"), "degenerate_prestim_distribution_or_labels", diag
    try:
        return float(logreg_condition_from_prestim(prestim_beta, y)), None, diag
    except Exception as exc:
        return float("nan"), f"auc_error:{exc}", diag


def _m12_z_threshold_decision(z_value: float, z_threshold: float) -> dict[str, float | bool]:
    z = float(z_value)
    threshold = float(z_threshold)
    return {
        "z_value": z,
        "z_threshold": threshold,
        "passes_z_threshold": bool(z >= threshold),
        "z_margin": float(z - threshold),
    }


def _strict_stage_failures_enabled(cfg) -> bool:
    pipeline_cfg = getattr(cfg, "pipeline", {}) or {}
    configured = pipeline_cfg.get("strict_stage_failures")
    if configured is not None:
        return bool(configured)
    # Default to strict in CI; permissive for interactive/local unless explicitly enabled.
    return bool(os.getenv("CI"))


def _is_critical_stage(stage: str, cfg) -> bool:
    pipeline_cfg = getattr(cfg, "pipeline", {}) or {}
    configured = pipeline_cfg.get("critical_failure_stages")
    if isinstance(configured, list) and configured:
        return stage in {str(s) for s in configured}
    return stage in {"m10", "m11"}


def _mark_critical_failure(
    *,
    result: RunResult,
    state: dict[str, object],
    stage: str,
    error: Exception,
    only: set[str] | None,
    skip: set[str] | None,
) -> list[str]:
    blocked_by_stage: dict[str, tuple[str, ...]] = {
        "m10": ("m11", "m12", "m8"),
        "m11": ("m12", "m8"),
    }
    blocked = [s for s in blocked_by_stage.get(stage, ()) if _stage_selected(s, only, skip)]
    result.metrics["failed_stage"] = stage
    result.metrics["blocked_stages"] = blocked
    result.metrics["error"] = str(error)
    result.status = "failed"
    result.skipped_stages.extend([s for s in blocked if s not in result.skipped_stages])
    state["error"] = f"{stage} failed: {error}"
    return blocked


def _stage_selected(stage: str, only: set[str] | None, skip: set[str] | None) -> bool:
    if only and stage not in only:
        return False
    if skip and stage in skip:
        return False
    return True


def _resolve_path(cfg, subject: str, key: str, fallback: Path) -> Path:
    custom = cfg.paths.get(key)
    return cfg.data_root / custom if custom else fallback


def _resolve_fmriprep_output_dir(cfg) -> Path | None:
    """Resolve fmri.fmriprep_output from config to an absolute path when set."""
    fmri_cfg = getattr(cfg, "fmri", None)
    if fmri_cfg is None:
        return None
    raw = str(getattr(fmri_cfg, "fmriprep_output", "")).strip()
    if not raw:
        return None
    out_dir = Path(raw).expanduser()
    if not out_dir.is_absolute():
        out_dir = (Path.cwd() / out_dir).resolve()
    return out_dir


def _validate_stage_dependencies(selected: list[str], *, assume_upstream_done: bool = False) -> None:
    if assume_upstream_done:
        return
    errs = list_missing_stage_dependencies(selected)
    if errs:
        raise ValueError("Invalid stage selection: " + "; ".join(errs))


def _write_run_state(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(payload, indent=2))
    tmp.replace(path)


def _append_live_log(path: Path, message: str, *, reset_file: bool = False) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    mode = "w" if reset_file else "a"
    with path.open(mode) as f:
        f.write(message.rstrip() + "\n")


def _finalize_run(
    *,
    subject: str,
    cfg,
    result: RunResult,
    out_dir: Path,
    state: dict[str, object],
    state_path: Path,
    live_log_path: Path,
    only: set[str] | None,
    skip: set[str] | None,
    force: bool,
    config_path: Path | None,
) -> RunResult:
    manifest = build_run_manifest(
        subject=subject,
        stage="m9_orchestration",
        params={
            "only": sorted(only) if only else [],
            "skip": sorted(skip) if skip else [],
            "force": force,
            "seed": 42,
            "config_fingerprint": config_fingerprint(config_path) if config_path else "unknown",
            "stage_timings_s": result.stage_timings_s,
        },
    )
    result.metrics["run_status"] = result.status
    result.metrics["skipped_stages"] = list(dict.fromkeys(result.skipped_stages))
    manifest["metrics"] = result.metrics
    write_manifest(out_dir / f"sub-{subject}_run_manifest.json", manifest)
    result.outputs.append(out_dir / f"sub-{subject}_run_manifest.json")
    try:
        aim2_group_report = render_aim2_group(cfg.derivatives_root)
        if aim2_group_report is not None:
            result.outputs.append(aim2_group_report)
    except Exception as exc:
        result.metrics["aim2_group_report_error"] = str(exc)
    state["status"] = result.status
    state["current_stage"] = None
    state["current_stage_description"] = None
    state["current_stage_started_at"] = None
    state["stage_timings_s"] = dict(result.stage_timings_s)
    state["last_event"] = "done:all" if result.status == "done" else "failed"
    state["updated_at"] = time.time()
    _write_run_state(state_path, state)
    _append_live_log(live_log_path, f"[run] status={result.status}")
    return result


_REPORT_PRESERVED_STAGE_PREFIXES: dict[str, tuple[str, ...]] = {
    "m5": ("m5_", "source_", "aim1_source_"),
    "m10": ("m10_",),
    "m11": ("m11_",),
    "m12": ("m12_", "aim3_"),
}


def _load_previous_manifest_metrics(manifest_path: Path) -> dict:
    try:
        payload = json.loads(manifest_path.read_text())
    except (OSError, json.JSONDecodeError):
        return {}
    metrics = payload.get("metrics")
    return dict(metrics) if isinstance(metrics, dict) else {}


def _preserve_unselected_stage_metrics_for_reports(
    current_metrics: dict,
    previous_metrics: dict,
    selected_stages: set[str],
) -> list[str]:
    """Carry prior downstream metrics into report-only runs."""
    if not previous_metrics or "m8" not in selected_stages:
        return []
    prefixes: list[str] = []
    for stage, stage_prefixes in _REPORT_PRESERVED_STAGE_PREFIXES.items():
        if stage not in selected_stages:
            prefixes.extend(stage_prefixes)
    if not prefixes:
        return []
    preserved: list[str] = []
    for key, value in previous_metrics.items():
        if key in current_metrics:
            continue
        if key.startswith(tuple(prefixes)):
            current_metrics[key] = value
            preserved.append(key)
    if preserved:
        current_metrics["m8_preserved_previous_metric_keys"] = preserved
    return preserved


def run_subject(
    subject: str,
    cfg,
    *,
    only: set[str] | None = None,
    skip: set[str] | None = None,
    force: bool = False,
    dry_run: bool = False,
    config_path: Path | None = None,
    progress_callback: Callable[[str], None] | None = None,
    progress_event_callback: Callable[[str, str], None] | None = None,
    memory_profile: bool = False,
    memory_profile_interval_s: float = 0.5,
    assume_upstream_done: bool = False,
) -> RunResult:
    result = RunResult(subject=subject)
    strict_stage_failures = _strict_stage_failures_enabled(cfg)
    selected = [s for s in STAGE_ORDER if _stage_selected(s, only, skip)]
    _validate_stage_dependencies(selected, assume_upstream_done=assume_upstream_done)
    result.metrics["selected_stages"] = selected
    result.metrics["strict_stage_failures"] = strict_stage_failures
    out_dir = stage_output_dir(cfg, subject, "m9_orchestration")
    m4_out_dir = stage_output_dir(cfg, subject, "m4_features")
    state_path = out_dir / f"sub-{subject}_run_state.json"
    live_log_path = out_dir / f"sub-{subject}_run_live.log"
    completed: list[str] = []
    state: dict[str, object] = {
        "subject": subject,
        "status": "running",
        "selected_stages": selected,
        "current_stage": None,
        "current_stage_description": None,
        "current_stage_started_at": None,
        "stage_index": 0,
        "stage_total": len(selected),
        "completed_stages": completed,
        "stage_timings_s": {},
        "error": None,
        "started_at": time.time(),
        "updated_at": time.time(),
        "last_event": None,
    }
    _write_run_state(state_path, state)
    _append_live_log(
        live_log_path,
        f"[run] subject={subject} status=running stages={','.join(selected)}",
        reset_file=True,
    )

    memory_probe: StageRSSProbe | None = None

    def _emit(event: str, stage: str) -> None:
        if progress_event_callback and _stage_selected(stage, only, skip):
            progress_event_callback(event, stage)
        if not _stage_selected(stage, only, skip):
            return
        if memory_probe is not None:
            memory_probe.record(event, stage)
        if event == "start":
            state["current_stage"] = stage
            state["current_stage_description"] = _STAGE_BRIEFS.get(stage, "")
            state["current_stage_started_at"] = time.time()
            # Execution order can differ from STAGE_ORDER (e.g. m7 before m10); index by run position.
            state["stage_index"] = len(completed) + 1
            _append_live_log(
                live_log_path,
                f"[stage start] {stage} ({state['stage_index']}/{state['stage_total']})",
            )
        elif event == "done":
            if stage not in completed:
                completed.append(stage)
            state["stage_timings_s"] = dict(result.stage_timings_s)
            state["last_event"] = f"done:{stage}"
            state["current_stage"] = None
            state["current_stage_description"] = None
            state["current_stage_started_at"] = None
            dur = float(result.stage_timings_s.get(stage, 0.0))
            _append_live_log(
                live_log_path,
                f"[stage done ] {stage} duration_s={dur:.3f} completed={len(completed)}/{state['stage_total']}",
            )
        else:
            state["last_event"] = f"{event}:{stage}"
        state["updated_at"] = time.time()
        _write_run_state(state_path, state)

    if dry_run:
        result.metrics["dry_run"] = True
        state["status"] = "dry_run"
        state["current_stage"] = None
        state["current_stage_description"] = None
        state["current_stage_started_at"] = None
        state["updated_at"] = time.time()
        _write_run_state(state_path, state)
        _append_live_log(live_log_path, "[run] status=dry_run")
        return result

    if memory_profile:
        memory_probe = StageRSSProbe(
            live_log_path=live_log_path,
            sample_interval_s=memory_profile_interval_s,
        )
        memory_probe.start_background_sampler()
        _append_live_log(
            live_log_path,
            f"[rss] memory_profile enabled interval_s={memory_profile_interval_s}",
        )

    try:
        return _run_subject_body(
            subject,
            cfg,
            only,
            skip,
            force,
            config_path,
            progress_callback,
            result,
            state,
            state_path,
            live_log_path,
            completed,
            _emit,
            memory_probe,
            strict_stage_failures,
        )
    finally:
        if memory_probe is not None:
            memory_probe.stop_background_sampler()
            result.metrics["memory_rss_summary"] = memory_probe.summary()
            summ = result.metrics["memory_rss_summary"]
            peak = summ.get("peak_rss_mb")
            _append_live_log(live_log_path, f"[rss] run_end peak_rss_mb={peak}")
            manifest_path = out_dir / f"sub-{subject}_run_manifest.json"
            if manifest_path.is_file():
                try:
                    prev = json.loads(manifest_path.read_text())
                    prev["metrics"] = result.metrics
                    write_manifest(manifest_path, prev)
                except (OSError, json.JSONDecodeError, TypeError):
                    pass


def _run_subject_body(
    subject: str,
    cfg,
    only: set[str] | None,
    skip: set[str] | None,
    force: bool,
    config_path: Path | None,
    progress_callback: Callable[[str], None] | None,
    result: RunResult,
    state: dict[str, object],
    state_path: Path,
    live_log_path: Path,
    completed: list[str],
    _emit: Callable[[str, str], None],
    memory_probe: StageRSSProbe | None,
    strict_stage_failures: bool,
) -> RunResult:
    _ = memory_probe  # reserved for future intra-body hooks
    out_dir = stage_output_dir(cfg, subject, "m9_orchestration")
    m4_out_dir = stage_output_dir(cfg, subject, "m4_features")
    previous_manifest_metrics = _load_previous_manifest_metrics(
        out_dir / f"sub-{subject}_run_manifest.json"
    )
    events_path = _resolve_path(cfg, subject, "events_tsv", events_tsv(subject, cfg.data_root))
    task_path = _resolve_path(cfg, subject, "task_ds", task_ds(subject, cfg.data_root))
    rest_path = _resolve_path(cfg, subject, "rest_ds", rest_ds(subject, cfg.data_root))

    _emit("start", "m1")
    t0 = perf_counter()
    trials = parse_events(str(events_path), strict=True)
    result.stage_timings_s["m1"] = perf_counter() - t0
    _emit("done", "m1")
    if progress_callback and _stage_selected("m1", only, skip):
        progress_callback("m1")
    result.metrics["n_trials"] = len(trials)
    result.metrics["n_zinnen"] = int((trials["condition"] == "ZINNEN").sum())
    result.metrics["n_woorden"] = int((trials["condition"] == "WOORDEN").sum())
    # Full trial table from events; trimmed to surviving epochs in m3 (inhouse
    # make_epochs / bids epochs.selection) or when restoring from m4_trial cache.
    trial_meta = make_events_metadata(trials)
    trial_meta_aligned = trial_meta.copy()

    # ── Per-stage output file paths ───────────────────────────────────────────
    _m4_analytic  = m4_out_dir / f"{subject}_beta_analytic.npz"
    _m4_psd       = m4_out_dir / f"{subject}_beta_psd.npz"
    _m4t_prestim  = m4_out_dir / f"{subject}_prestim_beta.npz"
    _m4t_n400m    = m4_out_dir / f"{subject}_n400m.npz"
    _m4t_prestim_dist = m4_out_dir / f"{subject}_prestim_distribution.npz"
    _m4t_prestim_topo = m4_out_dir / f"{subject}_prestim_topography.npz"
    _m6a_paths: dict[str, Path] = {
        "dirs_z":    out_dir / f"sub-{subject}_dirs_zinnen.npy",
        "dirs_w":    out_dir / f"sub-{subject}_dirs_woorden.npy",
        "dirs_r":    out_dir / f"sub-{subject}_dirs_rest.npy",
        "sliding_z": out_dir / f"sub-{subject}_sliding_dci_zinnen.npy",
        "dci_z":     out_dir / f"sub-{subject}_dci_zinnen.npy",
        "dci_w":     out_dir / f"sub-{subject}_dci_woorden.npy",
        "dci_r":     out_dir / f"sub-{subject}_dci_rest.npy",
        "sliding_t": out_dir / f"sub-{subject}_sliding_t.npy",
    }
    # sensor_xy + epoch shape cached alongside m6a so m12 can simulate without
    # reloading raw/epoch data.
    _m6a_sensor_xy   = out_dir / f"sub-{subject}_sensor_xy.npy"
    _m6a_epoch_shape = out_dir / f"sub-{subject}_epoch_shape.npz"
    _m6a_alpha_paths: dict[str, Path] = {
        "dirs_z": out_dir / f"sub-{subject}_alpha_dirs_zinnen.npy",
        "dirs_w": out_dir / f"sub-{subject}_alpha_dirs_woorden.npy",
        "dirs_r": out_dir / f"sub-{subject}_alpha_dirs_rest.npy",
        "dci_z": out_dir / f"sub-{subject}_alpha_dci_zinnen.npy",
        "dci_w": out_dir / f"sub-{subject}_alpha_dci_woorden.npy",
        "dci_r": out_dir / f"sub-{subject}_alpha_dci_rest.npy",
    }
    out_files = list(_m6a_paths.values()) + list(_m6a_alpha_paths.values())

    # ── Per-stage output file paths (cont.) ──────────────────────────────────
    _m10_out_dir    = stage_output_dir(cfg, subject, "m10_fmri")
    _m10_joined_csv = _m10_out_dir / f"{subject}_trials_joined.csv"
    _analysis_decisions_path = out_dir / f"sub-{subject}_analysis_decisions.json"

    # ── Per-stage cache flags (all invalidated by force=True) ─────────────────
    _m10_hit     = not force and _m10_joined_csv.exists()
    _m4_hit      = not force and _m4_analytic.exists() and _m4_psd.exists()
    # Cache stores (prestim_beta, n400m, trial_ids_after_rejection).
    # trial_ids let us restore the post-rejection trial_meta slice without
    # re-running make_epochs, keeping trial_meta consistent regardless of path.
    _m4trial_cache: tuple[np.ndarray, np.ndarray, np.ndarray] | None = None
    if not force and _m4t_prestim.exists() and _m4t_n400m.exists():
        _pb_npz = np.load(_m4t_prestim)
        _na_npz = np.load(_m4t_n400m)
        _pb = _pb_npz["prestim_beta"]
        _na = _na_npz["n400m"]
        _cached_ids = _pb_npz.get("trial_id", None)
        if len(_pb) == len(_na) and len(_pb) > 0 and _cached_ids is not None:
            _m4trial_cache = (_pb, _na, _cached_ids)
    _m4trial_hit = _m4trial_cache is not None
    _m6a_hit     = (
        not force
        and all(p.exists() for p in _m6a_paths.values())
        and _m6a_sensor_xy.exists()
        and _m6a_epoch_shape.exists()
    )
    _m6a_alpha_hit = not force and all(p.exists() for p in _m6a_alpha_paths.values())

    # m2/m3 (epochs) are only needed when at least one epoch-dependent stage
    # requires fresh computation.
    # - m6_extra only needs analytic_features (m4 cache satisfies it)
    # - m12 only needs sensor_xy + epoch shape (m6a cache satisfies it)
    _needs_epochs = any([
        _stage_selected("m4",       only, skip) and not _m4_hit,
        _stage_selected("m4_trial", only, skip) and not _m4trial_hit,
        _stage_selected("m6a",      only, skip) and not _m6a_hit,
        _stage_selected("m5",       only, skip),
        _stage_selected("m6_extra", only, skip) and not _m4_hit,
        _stage_selected("m12",      only, skip) and not _m6a_hit,
    ])

    # ── m2: preprocess ────────────────────────────────────────────────────────
    _emit("start", "m2")
    t0 = perf_counter()
    backend = getattr(cfg.preprocess, "backend", "inhouse")
    epochs = None
    epochs_rest = None
    epochs_alpha = None
    epochs_rest_alpha = None
    task_raw = None
    task_raw_clean = None
    ica = None
    if _needs_epochs:
        if backend == "mne_bids_pipeline":
            from ..m2_preprocess.bids_pipeline_backend import run_preprocessing

            epochs, epochs_rest = run_preprocessing(subject, cfg)
        else:
            task_raw = mne.io.read_raw_ctf(str(task_path), preload=True, system_clock="truncate", verbose="WARNING")
            task_raw.apply_gradient_compensation(3)
            task_raw_clean = apply_notch_and_resample(task_raw, cfg)
            task_raw_clean, ica = fit_and_apply(task_raw_clean, cfg)
            task_raw = apply_band(task_raw_clean.copy(), 13, 30)
    else:
        result.metrics["m2_cache_skip"] = True
    result.stage_timings_s["m2"] = perf_counter() - t0
    _emit("done", "m2")
    if progress_callback and _stage_selected("m2", only, skip):
        progress_callback("m2")

    # ── m3: epoch ─────────────────────────────────────────────────────────────
    _emit("start", "m3")
    t0 = perf_counter()
    if _needs_epochs and backend != "mne_bids_pipeline":
        assert task_raw is not None
        epochs, trial_meta = make_epochs(task_raw, trials, cfg)
        if task_raw_clean is not None:
            task_raw_alpha = apply_band(task_raw_clean.copy(), 8, 13)
            epochs_alpha, _ = make_epochs(task_raw_alpha, trials, cfg)
        trial_meta_aligned = trial_meta.copy()
    elif _needs_epochs and backend == "mne_bids_pipeline":
        assert epochs is not None
        trial_meta = make_events_metadata(trials).iloc[list(epochs.selection)].reset_index(drop=True)
        trial_meta_aligned = trial_meta.copy()
    result.stage_timings_s["m3"] = perf_counter() - t0
    _emit("done", "m3")
    if progress_callback and _stage_selected("m3", only, skip):
        progress_callback("m3")

    # ── m4: analytic signal + PSD ─────────────────────────────────────────────
    analytic_features = None
    trial_df = trial_meta_aligned.copy()
    if _stage_selected("m4", only, skip):
        _emit("start", "m4")
        t0 = perf_counter()
        if _m4_hit:
            result.metrics["m4_cache_hit"] = True
            if _stage_selected("m6_extra", only, skip):
                analytic_features = dict(np.load(_m4_analytic))
        else:
            assert epochs is not None
            analytic_features = analytic_signal(epochs, subject, cfg, "beta")
            psd(epochs, subject, cfg, "beta", 13.0, 30.0)
        result.stage_timings_s["m4"] = perf_counter() - t0
        _emit("done", "m4")
        if progress_callback:
            progress_callback("m4")
    else:
        result.skipped_stages.append("m4")

    # ── m4_trial: pre-stim beta / N400m ───────────────────────────────────────
    if _stage_selected("m4_trial", only, skip):
        _emit("start", "m4_trial")
        t0 = perf_counter()
        if _m4trial_hit:
            result.metrics["m4_trial_cache_hit"] = True
            assert _m4trial_cache is not None
            prestim_beta, n400m, _cached_ids = _m4trial_cache
            # Restore trial_meta to the post-rejection subset recorded in the cache.
            trial_meta = trial_meta[trial_meta["trial_id"].isin(_cached_ids)].reset_index(drop=True)
            trial_meta_aligned = trial_meta.copy()
        else:
            assert epochs is not None
            prestim_beta = prestim_beta_power(epochs, subject, cfg, trial_meta_aligned)
            n400_window = tuple(getattr(cfg.features, "n400m_window_s", (0.3, 0.5)))
            n400_prefix = str(getattr(cfg.features, "n400m_sensor_prefix", "MLT"))
            n400_weights_path = str(getattr(cfg.features, "n400m_topography_weights_path", "")).strip()
            n400_weights = np.load(Path(n400_weights_path)) if n400_weights_path else None
            n400m = n400m_amplitude(
                epochs,
                subject,
                cfg,
                trial_meta_aligned,
                sensor_prefix=n400_prefix,
                tmin=float(n400_window[0]),
                tmax=float(n400_window[1]),
                topography_weights=n400_weights,
            )
            result.metrics["aim1_n400m_spec"] = {
                "window_s": [float(n400_window[0]), float(n400_window[1])],
                "sensor_prefix": n400_prefix,
                "topography_weights_path": n400_weights_path or None,
            }
        y = (trial_meta_aligned["condition"] == "ZINNEN").to_numpy(dtype=int)
        auc_value, auc_guard_reason, prestim_diag = _guarded_prestim_auc(prestim_beta, y)
        result.metrics["aim1_prestim_auc"] = auc_value
        if auc_guard_reason is not None:
            result.metrics["aim1_prestim_auc_guard_reason"] = auc_guard_reason
        result.metrics["aim1_prestim_is_degenerate"] = bool(prestim_diag.get("is_degenerate", False))
        result.metrics["aim1_prestim_std"] = float(prestim_diag.get("std_finite", 0.0))
        result.metrics["aim1_prestim_n_unique"] = int(prestim_diag.get("n_unique_finite", 0))
        result.metrics["aim1_prestim_n_finite"] = int(prestim_diag.get("n_finite", 0))
        cond_arr = trial_meta_aligned["condition"].to_numpy(dtype=str)
        z_vals = prestim_beta[cond_arr == "ZINNEN"]
        w_vals = prestim_beta[cond_arr == "WOORDEN"]
        result.metrics["prestim_beta_mean_zinnen"] = float(np.mean(z_vals)) if len(z_vals) else float("nan")
        result.metrics["prestim_beta_mean_woorden"] = float(np.mean(w_vals)) if len(w_vals) else float("nan")
        result.metrics["prestim_beta_std"] = float(np.std(prestim_beta, ddof=1)) if len(prestim_beta) > 1 else 0.0
        if len(z_vals) > 1 and len(w_vals) > 1:
            from scipy.stats import ks_2samp

            result.metrics["prestim_beta_ks_p"] = float(ks_2samp(z_vals, w_vals).pvalue)
        result.metrics["aim1_n400m_zinnen_vs_woorden_t"] = n400m_condition_t(
            n400m,
            trial_meta_aligned["condition"].to_numpy(dtype=str),
        )
        n400_npz = stage_output_dir(cfg, subject, "m4_features") / f"{subject}_n400m.npz"
        if n400_npz.exists():
            try:
                n400_dat = np.load(n400_npz)
                result.metrics["aim1_n400m_n_channels"] = int(n400_dat["n_channels_used"])
            except Exception:
                pass
        if len(prestim_beta):
            np.savez(
                _m4t_prestim_dist,
                prestim_beta=prestim_beta,
                condition=cond_arr,
                trial_id=trial_meta_aligned["trial_id"].to_numpy(dtype=int),
            )
            dist_png = _m4t_prestim_dist.with_suffix(".png")
            try:
                fig, ax = plt.subplots(figsize=(5, 3.5))
                if len(z_vals):
                    ax.hist(z_vals, bins=20, alpha=0.5, label="ZINNEN")
                if len(w_vals):
                    ax.hist(w_vals, bins=20, alpha=0.5, label="WOORDEN")
                ax.set_title("Pre-stim beta distribution")
                ax.set_xlabel("Beta power")
                ax.set_ylabel("Count")
                ax.legend(loc="best")
                fig.tight_layout()
                fig.savefig(dist_png, dpi=140)
                plt.close(fig)
                result.metrics["aim1_prestim_distribution_plot"] = str(dist_png)
                result.outputs.append(dist_png)
            except Exception as exc:
                result.metrics["aim1_prestim_distribution_plot_error"] = str(exc)
            result.metrics["aim1_prestim_distribution_artifact"] = str(_m4t_prestim_dist)
            result.outputs.append(_m4t_prestim_dist)
        if epochs is not None:
            try:
                prestim_crop = epochs.copy().crop(tmin=-0.8, tmax=0.0).get_data(picks="meg")
                # Channel-wise prestim power topography for report-side plotting.
                ch_power = np.nanmean(prestim_crop**2, axis=(0, 2))
                sensor_xy_topo, _ = get_sensor_positions(epochs.info)
                np.savez(_m4t_prestim_topo, sensor_xy=sensor_xy_topo, channel_power=ch_power)
                result.metrics["aim1_prestim_topography_artifact"] = str(_m4t_prestim_topo)
                result.outputs.append(_m4t_prestim_topo)
            except Exception as exc:
                result.metrics["aim1_prestim_topography_error"] = str(exc)
        elif _m4t_prestim_topo.exists():
            result.metrics["aim1_prestim_topography_artifact"] = str(_m4t_prestim_topo)
        trial_df["prestim_beta"] = prestim_beta
        trial_df["n400m"] = n400m
        result.stage_timings_s["m4_trial"] = perf_counter() - t0
        _emit("done", "m4_trial")
        if progress_callback:
            progress_callback("m4_trial")
    else:
        result.skipped_stages.append("m4_trial")

    if _m4t_prestim_dist.exists():
        result.metrics.setdefault("aim1_prestim_distribution_artifact", str(_m4t_prestim_dist))
    if _m4t_prestim_topo.exists():
        result.metrics.setdefault("aim1_prestim_topography_artifact", str(_m4t_prestim_topo))
    if _m4t_prestim.exists():
        result.metrics.setdefault("aim1_prestim_condition_contrast_artifact", str(_m4t_prestim))

    if _m4trial_cache is not None:
        prestim_beta_cached, n400m_cached, cached_trial_ids = _m4trial_cache
        cache_trial_df = pd.DataFrame(
            {
                "trial_id": cached_trial_ids,
                "prestim_beta": prestim_beta_cached,
                "n400m": n400m_cached,
            }
        )
        trial_df, hydrated_features = hydrate_meg_features(
            trial_df,
            cache_trial_df,
            features=("prestim_beta", "n400m"),
        )
        if hydrated_features:
            result.metrics["m4_trial_cache_hydrated_features"] = hydrated_features
            result.metrics["m4_trial_cache_hydrated_rows"] = int(len(cache_trial_df))

    # ── rest data (only needed when m6a requires fresh computation) ───────────
    if not _m6a_hit and _stage_selected("m6a", only, skip) and backend != "mne_bids_pipeline":
        rest_raw = mne.io.read_raw_ctf(str(rest_path), preload=True, system_clock="truncate", verbose="WARNING")
        rest_raw.apply_gradient_compensation(3)
        rest_raw = apply_notch_and_resample(rest_raw, cfg)
        assert ica is not None
        ica.apply(rest_raw)
        epoch_len = cfg.epoching.tmax - cfg.epoching.tmin
        rest_beta = apply_band(rest_raw.copy(), 13, 30)
        rest_alpha = apply_band(rest_raw.copy(), 8, 13)
        epochs_rest = make_pseudo_epochs(rest_beta, epoch_len)
        epochs_rest_alpha = make_pseudo_epochs(rest_alpha, epoch_len)

    # ── m6a: phase-gradient waves + DCI ───────────────────────────────────────
    # Load from cache whenever it exists (regardless of whether m6a is selected),
    # so that downstream stages (m12) can use prior outputs when running fMRI-only.
    #
    # TODO(caching): This is a workaround for the split MEG/fMRI job architecture.
    # The right long-term fix is a proper stage-level cache/artifact registry that
    # lets any stage declare its output artifacts and any downstream stage retrieve
    # them by key — rather than each stage encoding its own cache-hit logic.
    # Tracked in: https://github.com/JonathanWade24/SNIRP-MOUS-Pipeline/issues
    # (open an issue titled "Stage artifact registry for cross-job cache sharing")
    _emit("start", "m6a")
    t0 = perf_counter()
    sensor_xy = None
    meg_picks: list[int] = []
    _m6a_data_available = False
    _m6a_alpha_available = False
    dirs_z = dirs_w = dirs_r = np.array([])
    dci_z = dci_w = dci_r = np.array([])
    sliding_t = sliding_z = np.array([])
    alpha_dirs_z = alpha_dirs_w = alpha_dirs_r = np.array([])
    alpha_dci_z = alpha_dci_w = alpha_dci_r = np.array([])
    if _m6a_hit:
        result.metrics["m6a_cache_hit"] = True
        dirs_z    = np.load(_m6a_paths["dirs_z"])
        dirs_w    = np.load(_m6a_paths["dirs_w"])
        dirs_r    = np.load(_m6a_paths["dirs_r"])
        sliding_z = np.load(_m6a_paths["sliding_z"])
        dci_z     = np.load(_m6a_paths["dci_z"])
        dci_w     = np.load(_m6a_paths["dci_w"])
        dci_r     = np.load(_m6a_paths["dci_r"])
        sliding_t = np.load(_m6a_paths["sliding_t"])
        sensor_xy = np.load(_m6a_sensor_xy)
        _m6a_data_available = True
        if _m6a_alpha_hit:
            alpha_dirs_z = np.load(_m6a_alpha_paths["dirs_z"])
            alpha_dirs_w = np.load(_m6a_alpha_paths["dirs_w"])
            alpha_dirs_r = np.load(_m6a_alpha_paths["dirs_r"])
            alpha_dci_z = np.load(_m6a_alpha_paths["dci_z"])
            alpha_dci_w = np.load(_m6a_alpha_paths["dci_w"])
            alpha_dci_r = np.load(_m6a_alpha_paths["dci_r"])
            _m6a_alpha_available = True
    elif _stage_selected("m6a", only, skip):
        assert epochs is not None and epochs_rest is not None
        sensor_xy, meg_picks = get_sensor_positions(epochs.info)
        dirs_z, dci_z = epochs_to_directions(epochs["ZINNEN"], sensor_xy, meg_picks)
        dirs_w, dci_w = epochs_to_directions(epochs["WOORDEN"], sensor_xy, meg_picks)
        dirs_r, dci_r = epochs_to_directions(epochs_rest, sensor_xy, meg_picks)
        sliding_t, sliding_z = sliding_dci(
            epochs["ZINNEN"].get_data(picks=meg_picks),
            sensor_xy,
            epochs["ZINNEN"].times,
            win=30,
            step=5,
        )
        _m6a_data_available = True
        if epochs_alpha is not None and epochs_rest_alpha is not None:
            alpha_dirs_z, alpha_dci_z = epochs_to_directions(epochs_alpha["ZINNEN"], sensor_xy, meg_picks)
            alpha_dirs_w, alpha_dci_w = epochs_to_directions(epochs_alpha["WOORDEN"], sensor_xy, meg_picks)
            alpha_dirs_r, alpha_dci_r = epochs_to_directions(epochs_rest_alpha, sensor_xy, meg_picks)
            _m6a_alpha_available = True
    else:
        # m6a not selected and no cache: skip gracefully; m12 will also be skipped.
        result.metrics["m6a_skipped_reason"] = "not selected and no prior cache available"
        if _stage_selected("m12", only, skip):
            result.skipped_stages.append("m12")
            result.metrics["m12_skipped_reason"] = "m6a cache not available for fMRI-only run"
    result.stage_timings_s["m6a"] = perf_counter() - t0
    _emit("done", "m6a")
    if progress_callback and _stage_selected("m6a", only, skip):
        progress_callback("m6a")
    if _m6a_data_available:
        result.metrics["dci_zinnen"] = float(np.mean(dci_z))
        result.metrics["dci_woorden"] = float(np.mean(dci_w))
        result.metrics["dci_rest"] = float(np.mean(dci_r))
        result.metrics["n_rest"] = len(dci_r)
        if not trial_df.empty:
            n_z = len(dci_z)
            n_w = len(dci_w)
            trial_df.loc[trial_df["condition"] == "ZINNEN", "dci_trial"] = dci_z[:n_z]
            trial_df.loc[trial_df["condition"] == "WOORDEN", "dci_trial"] = dci_w[:n_w]
    if _m6a_alpha_available:
        result.metrics["alpha_dci_zinnen"] = float(np.mean(alpha_dci_z))
        result.metrics["alpha_dci_woorden"] = float(np.mean(alpha_dci_w))
        result.metrics["alpha_dci_rest"] = float(np.mean(alpha_dci_r))
    else:
        result.metrics["alpha_dci_status"] = "not_available"

    if _stage_selected("m5", only, skip):
        _emit("start", "m5")
        if backend == "mne_bids_pipeline":
            t0 = perf_counter()
            try:
                from ..m2_preprocess.bids_pipeline_backend import run_source

                result.metrics.update(run_source(subject, cfg))
            except Exception as exc:
                result.metrics["m5_error"] = str(exc)
            result.stage_timings_s["m5"] = perf_counter() - t0
            _emit("done", "m5")
            if progress_callback:
                progress_callback("m5")
        else:
            source_cfg = getattr(cfg, "source", None)
            if source_cfg and source_cfg.subjects_dir:
                t0 = perf_counter()
                try:
                    assert task_raw is not None
                    fwd, src = build_forward_model(subject, task_raw, cfg)
                    stcs = compute_inverse(epochs["ZINNEN"], fwd, cfg)
                    labels = mne.read_labels_from_annot(
                        "fsaverage" if source_cfg.use_fsaverage else f"sub-{subject.removeprefix('sub-')}",
                        parc="aparc",
                        subjects_dir=source_cfg.subjects_dir,
                    )
                    roi_ts = extract_roi_timeseries(stcs, src, labels[: min(len(labels), 10)])
                    result.metrics["m5_n_labels"] = len(roi_ts)
                    result.metrics["m5_n_stcs"] = len(stcs)
                    src_xy = source_positions_xy(src)
                    stc_data = stcs_to_matrix(stcs)
                    source_dirs, source_dci = epochs_to_directions(epochs["ZINNEN"], src_xy, data_override=stc_data)
                    result.metrics["source_dci_zinnen"] = float(np.mean(source_dci))
                    result.metrics["source_directions_count"] = int(len(source_dirs))
                    m5_out = stage_output_dir(cfg, subject, "m5_source")
                    np.save(m5_out / f"sub-{subject}_source_dirs.npy", source_dirs)
                    np.save(m5_out / f"sub-{subject}_source_dci.npy", source_dci)
                    source_dirs_path = m5_out / f"sub-{subject}_source_dirs.npy"
                    source_dci_path = m5_out / f"sub-{subject}_source_dci.npy"
                    result.outputs += [
                        source_dirs_path,
                        source_dci_path,
                    ]
                    result.metrics["aim1_source_spatial_summary"] = {
                        "source_dirs_path": str(source_dirs_path),
                        "source_dci_path": str(source_dci_path),
                    }
                    # Save ROI timeseries for downstream export and QA.
                    if roi_ts:
                        roi_labels = list(roi_ts.keys())
                        roi_matrix = np.stack(list(roi_ts.values()), axis=1)  # (n_epochs, n_labels, n_times)
                        roi_ts_path = m5_out / f"sub-{subject}_source_roi_ts.npz"
                        roi_labels_path = m5_out / f"sub-{subject}_source_roi_labels.json"
                        np.savez(roi_ts_path, roi_matrix=roi_matrix)
                        roi_labels_path.write_text(json.dumps(roi_labels))
                        result.outputs += [roi_ts_path, roi_labels_path]
                except Exception as exc:
                    result.metrics["m5_error"] = str(exc)
                result.stage_timings_s["m5"] = perf_counter() - t0
                _emit("done", "m5")
                if progress_callback:
                    progress_callback("m5")
            else:
                result.metrics["m5_skipped_reason"] = "source.subjects_dir not configured"
                result.skipped_stages.append("m5")
    else:
        result.skipped_stages.append("m5")

    if _stage_selected("m6_extra", only, skip):
        _emit("start", "m6_extra")
        t0 = perf_counter()
        if analytic_features is None:
            analytic_features = analytic_signal(epochs, subject, cfg, "beta")
        detectors = [CFCDetector(), FFT2DDetector(), RotationalDetector(), FlowFieldDetector()]
        extra_metrics: dict[str, float | str] = {}
        for detector in detectors:
            try:
                det_out = detector.detect(analytic_features)
                for key, value in det_out.items():
                    if np.isscalar(value):
                        extra_metrics[f"{detector.name}_{key}"] = float(value)
            except Exception as exc:
                extra_metrics[f"{detector.name}_error"] = str(exc)
        result.metrics.update(extra_metrics)
        result.stage_timings_s["m6_extra"] = perf_counter() - t0
        _emit("done", "m6_extra")
        if progress_callback:
            progress_callback("m6_extra")
    else:
        result.skipped_stages.append("m6_extra")

    if _stage_selected("m7", only, skip):
        _emit("start", "m7")
        t0 = perf_counter()
        if _m6a_data_available:
            _, p_sz = perm_test_dci(dci_z, dci_r)
            _, p_wr = perm_test_dci(dci_w, dci_r)
            _, p_zw = perm_test_dci(dci_z, dci_w)
            result.metrics["p_task_vs_rest"] = p_sz
            result.metrics["p_woorden_vs_rest"] = p_wr
            result.metrics["p_zinnen_vs_woorden"] = p_zw
            result.metrics["p_rayleigh_zinnen"] = rayleigh_p(dirs_z)
            result.metrics["p_rayleigh_woorden"] = rayleigh_p(dirs_w)
            result.metrics["dci_zinnen_pooled"] = directional_consistency_index(dirs_z)
            result.metrics["dci_woorden_pooled"] = directional_consistency_index(dirs_w)
            result.metrics["dci_rest_pooled"] = directional_consistency_index(dirs_r)
            if _m6a_alpha_available:
                _, p_alpha_sz = perm_test_dci(alpha_dci_z, alpha_dci_r)
                _, p_alpha_wr = perm_test_dci(alpha_dci_w, alpha_dci_r)
                _, p_alpha_zw = perm_test_dci(alpha_dci_z, alpha_dci_w)
                result.metrics["alpha_p_task_vs_rest"] = p_alpha_sz
                result.metrics["alpha_p_woorden_vs_rest"] = p_alpha_wr
                result.metrics["alpha_p_zinnen_vs_woorden"] = p_alpha_zw
                result.metrics["alpha_p_rayleigh_zinnen"] = rayleigh_p(alpha_dirs_z)
                result.metrics["alpha_p_rayleigh_woorden"] = rayleigh_p(alpha_dirs_w)
                result.metrics["alpha_dci_zinnen_pooled"] = directional_consistency_index(alpha_dirs_z)
                result.metrics["alpha_dci_woorden_pooled"] = directional_consistency_index(alpha_dirs_w)
                result.metrics["alpha_dci_rest_pooled"] = directional_consistency_index(alpha_dirs_r)
            if {"dci_trial", "pos_in_block"}.issubset(trial_df.columns):
                model_df = trial_df.dropna(subset=["dci_trial", "pos_in_block"]).copy()
                model_df = add_first_trial_control_columns(model_df)
                if not model_df.empty:
                    p_block, _ = lme_block_control(model_df, "dci_trial ~ C(condition) + pos_in_block")
                    result.metrics["aim1_dci_block_effect_p"] = p_block
                    p_block_first, _ = lme_block_control(
                        model_df,
                        "dci_trial ~ C(condition) + pos_in_block + is_first_in_block",
                        term="is_first_in_block",
                    )
                    result.metrics["aim1_dci_first_trial_effect_p"] = p_block_first
        else:
            result.metrics["m7_skipped_reason"] = (
                "m6a outputs unavailable; run m6a first or provide cached m6a artifacts"
            )
            result.skipped_stages.append("m7")
            if result.status != "failed":
                result.status = "completed_with_skips"
        if {"prestim_beta", "pos_in_block"}.issubset(trial_df.columns):
            prestim_model_df = trial_df.dropna(subset=["prestim_beta", "pos_in_block"]).copy()
            prestim_model_df = add_first_trial_control_columns(prestim_model_df)
            if not prestim_model_df.empty:
                p_prestim_block, _ = lme_block_control(
                    prestim_model_df,
                    "prestim_beta ~ C(condition) + pos_in_block",
                )
                result.metrics["aim1_prestim_block_effect_p"] = p_prestim_block
                p_prestim_first, _ = lme_block_control(
                    prestim_model_df,
                    "prestim_beta ~ C(condition) + pos_in_block + is_first_in_block",
                    term="is_first_in_block",
                )
                result.metrics["aim1_prestim_first_trial_effect_p"] = p_prestim_first
        result.stage_timings_s["m7"] = perf_counter() - t0
        _emit("done", "m7")
        if progress_callback:
            progress_callback("m7")
    else:
        result.skipped_stages.append("m7")

    _emit("start", "m9")
    t0 = perf_counter()
    gate = PilotGate().evaluate(result.metrics)
    result.metrics["pilot_verdict"] = gate["verdict"]
    result.metrics["pilot_gate"] = gate
    result.stage_timings_s["m9"] = perf_counter() - t0
    _emit("done", "m9")
    if progress_callback and _stage_selected("m9", only, skip):
        progress_callback("m9")

    joined_df: pd.DataFrame | None = None
    lag_model_inputs: dict[str, pd.DataFrame] = {}
    if _stage_selected("m10", only, skip):
        _emit("start", "m10")
        t0 = perf_counter()
        bold_path = None
        fmri_cfg = getattr(cfg, "fmri", None)
        m10_n_jobs = int(getattr(cfg, "pipeline", {}).get("m10_n_jobs", 1))
        try:
            if _m10_hit:
                joined_df = pd.read_csv(_m10_joined_csv)
                joined_df, hydrated_features = hydrate_meg_features(joined_df, trial_df)
                if hydrated_features:
                    result.metrics["m10_joined_hydrated_features"] = hydrated_features
                    joined_df.to_csv(_m10_joined_csv, index=False)
                    _append_live_log(
                        live_log_path,
                        f"[m10:cache] hydrated joined CSV with {','.join(hydrated_features)}",
                    )
                result.metrics["m10_cache_hit"] = True
                result.metrics["m10_n_trials_joined"] = len(joined_df)
                result.outputs.append(_m10_joined_csv)
                _append_live_log(live_log_path, f"[m10:cache] reusing {_m10_joined_csv}")
            else:
                if fmri_cfg:
                    from ..m10_fmri.glm import trialwise_betas
                    from ..m10_fmri.prep import resolve_subject_bold_path, run_fmriprep, validate_tr_from_sidecar

                    verbose_tools = bool(getattr(cfg, "pipeline", {}).get("verbose_tool_logs", True))
                    reuse_existing_fmriprep = bool(getattr(cfg, "pipeline", {}).get("m10_reuse_fmriprep", False))
                    fmriprep_out = run_fmriprep(
                        subject,
                        cfg,
                        bids_root=cfg.data_root,
                        log_callback=(lambda line: _append_live_log(live_log_path, f"[m10:fmriprep] {line}"))
                        if verbose_tools
                        else None,
                        reuse_existing=reuse_existing_fmriprep,
                    )
                else:
                    result.metrics["m10_skipped_reason"] = "fmri configuration missing"

            if fmri_cfg is not None:
                from ..m10_fmri.prep import resolve_subject_bold_path, validate_tr_from_sidecar

                fmriprep_out_dir = _resolve_fmriprep_output_dir(cfg) if _m10_hit else fmriprep_out
                bold_path = resolve_subject_bold_path(
                    subject,
                    cfg,
                    bids_root=cfg.data_root,
                    fmriprep_out_dir=fmriprep_out_dir,
                )
                if bold_path is None:
                    if not _m10_hit:
                        expected_func_dir = cfg.data_root / f"sub-{subject.removeprefix('sub-')}" / "func"
                        expected_func_dir.mkdir(parents=True, exist_ok=True)
                        checked_fmriprep = fmriprep_out_dir if fmriprep_out_dir is not None else "<unset>"
                        result.metrics["m10_skipped_reason"] = (
                            "No BOLD file found. Checked config fmri.bold_path, BIDS func paths, and "
                            f"{checked_fmriprep}/sub-{subject.removeprefix('sub-')}/func. "
                            f"Created expected directory: {expected_func_dir}"
                        )
                elif not _m10_hit:
                    from ..m10_fmri.glm import trialwise_betas

                    sidecar = (
                        bold_path.with_suffix("").with_suffix(".json")
                        if str(bold_path).endswith(".nii.gz")
                        else bold_path.with_suffix(".json")
                    )
                    if sidecar.exists():
                        validate_tr_from_sidecar(sidecar, fmri_cfg.tr)
                    beta_tbl = trialwise_betas(
                        str(bold_path),
                        trial_df,
                        fmri_cfg.tr,
                        atlas=fmri_cfg.atlas,
                        roi=fmri_cfg.roi,
                        n_jobs=m10_n_jobs,
                        onset_shift_s=float(getattr(fmri_cfg, "onset_shift_s", 0.0)),
                    )
                    joined_df = trial_df.merge(beta_tbl, on="trial_id", how="inner")
                    result.metrics["m10_n_trials_joined"] = int(len(joined_df))
                    _m10_out_dir.mkdir(parents=True, exist_ok=True)
                    joined_df.to_csv(_m10_joined_csv, index=False)
                    result.outputs.append(_m10_joined_csv)

            lag_sweep_cfg = getattr(fmri_cfg, "hrf_lag_sweep_s", [])
            lag_sweep_vals = [float(v) for v in lag_sweep_cfg] if isinstance(lag_sweep_cfg, list) else []
            if (
                lag_sweep_vals
                and fmri_cfg is not None
                and joined_df is not None
                and bold_path is not None
                and "trial_id" in trial_df.columns
            ):
                from ..m10_fmri.glm import trialwise_betas

                lag_tables: dict[str, str] = {}
                for lag_s in lag_sweep_vals:
                    lag_beta_tbl = trialwise_betas(
                        str(bold_path),
                        trial_df,
                        fmri_cfg.tr,
                        atlas=fmri_cfg.atlas,
                        roi=fmri_cfg.roi,
                        n_jobs=m10_n_jobs,
                        onset_shift_s=lag_s,
                    )
                    lag_joined = trial_df.merge(lag_beta_tbl, on="trial_id", how="inner")
                    lag_csv = _m10_out_dir / f"{subject}_trials_joined_shift_{lag_s:+.3f}s.csv"
                    lag_joined.to_csv(lag_csv, index=False)
                    lag_tables[f"{lag_s:+.3f}s"] = str(lag_csv)
                    lag_model_inputs[f"{lag_s:+.3f}s"] = lag_joined
                    result.outputs.append(lag_csv)
                lag_ready = sorted(lag_model_inputs.keys())
                result.metrics["m10_hrf_lag_sweep_tables"] = lag_tables
                result.metrics["m10_hrf_lag_sweep_s"] = lag_sweep_vals
                result.metrics["m11_hrf_lag_sweep_ready"] = lag_ready
                result.metrics["m10_hrf_lag_selection"] = {
                    "strategy": "max_abs_condition_prestim_correlation",
                    "candidate_labels": lag_ready,
                }
        except Exception as exc:
            result.metrics["m10_error"] = str(exc)
            if not strict_stage_failures:
                result.status = "completed_with_skips"
            if strict_stage_failures and _is_critical_stage("m10", cfg):
                blocked = _mark_critical_failure(
                    result=result,
                    state=state,
                    stage="m10",
                    error=exc,
                    only=only,
                    skip=skip,
                )
                _append_live_log(live_log_path, f"[run] critical_failure stage=m10 error={exc}")
                return _finalize_run(
                    subject=subject,
                    cfg=cfg,
                    result=result,
                    out_dir=out_dir,
                    state=state,
                    state_path=state_path,
                    live_log_path=live_log_path,
                    only=only,
                    skip=skip,
                    force=force,
                    config_path=config_path,
                )
        result.stage_timings_s["m10"] = perf_counter() - t0
        _emit("done", "m10")
        if progress_callback:
            progress_callback("m10")
        # Release any large fMRI locals before leaving m10 so joblib/nilearn
        # pool teardown happens here (inside m10's wall-clock) instead of
        # stalling the gap between m10 and m11.
        if bool(getattr(cfg, "pipeline", {}).get("m10_force_gc", True)):
            import gc as _gc
            _gc.collect()
            _append_live_log(live_log_path, "[m10:cleanup] released fMRI locals, advancing")
    else:
        result.skipped_stages.append("m10")

    if _stage_selected("m11", only, skip):
        _emit("start", "m11")
        t0 = perf_counter()
        if joined_df is None and bool(getattr(cfg, "pipeline", {}).get("m11_allow_cached_joined", False)):
            if _m10_joined_csv.exists():
                try:
                    joined_df = pd.read_csv(_m10_joined_csv)
                    joined_df, hydrated_features = hydrate_meg_features(joined_df, trial_df)
                    if hydrated_features:
                        result.metrics["m11_cached_joined_hydrated_features"] = hydrated_features
                        joined_df.to_csv(_m10_joined_csv, index=False)
                        _append_live_log(
                            live_log_path,
                            f"[m11:cache] hydrated joined CSV with {','.join(hydrated_features)}",
                        )
                    result.metrics["m11_used_cached_joined"] = True
                    result.metrics["m11_cached_joined_path"] = str(_m10_joined_csv)
                except Exception as exc:
                    result.metrics["m11_cached_joined_error"] = str(exc)
        if joined_df is not None and not joined_df.empty:
            meg_cols_present = [c for c in MEG_COUPLING_FEATURES if c in joined_df.columns]
            if not meg_cols_present:
                result.metrics["m11_skipped_reason"] = (
                    "MEG feature columns (prestim_beta, n400m, dci_trial) absent — "
                    "e.g. m4_trial / m6a not run for this joined table."
                )
            else:
                try:
                    coupling = run_coupling_models(joined_df)
                    result.metrics["m11_coupling"] = coupling
                    result.metrics["m11_trials_rows"] = joined_df.to_dict(orient="records")
                    if lag_model_inputs:
                        lag_coupling: dict[str, dict] = {}
                        for lag_label in sorted(lag_model_inputs.keys()):
                            lag_df = lag_model_inputs[lag_label]
                            if lag_df is not None and not lag_df.empty:
                                lag_coupling[lag_label] = run_coupling_models(lag_df)
                        if lag_coupling:
                            result.metrics["m11_coupling_hrf_lag_sweep"] = lag_coupling
                            best_lag = None
                            best_abs_r = -1.0
                            for lag_label, lag_metrics in lag_coupling.items():
                                for cond_key in ("zinnen_prestim_beta_vs_mtg", "woorden_prestim_beta_vs_mtg"):
                                    row = lag_metrics.get(cond_key)
                                    if isinstance(row, dict):
                                        r_val = abs(float(row.get("r", 0.0)))
                                        if np.isfinite(r_val) and r_val > best_abs_r:
                                            best_abs_r = r_val
                                            best_lag = lag_label
                            if best_lag is not None:
                                result.metrics["m10_best_hrf_lag_s"] = best_lag
                                result.metrics["m10_hrf_lag_selection"] = {
                                    "strategy": "max_abs_condition_prestim_correlation",
                                    "candidate_labels": sorted(lag_coupling.keys()),
                                    "selected_label": best_lag,
                                    "selected_from": "m11_coupling_hrf_lag_sweep",
                                }
                except Exception as exc:
                    result.metrics["m11_error"] = str(exc)
                    if not strict_stage_failures:
                        result.status = "completed_with_skips"
                    if strict_stage_failures and _is_critical_stage("m11", cfg):
                        blocked = _mark_critical_failure(
                            result=result,
                            state=state,
                            stage="m11",
                            error=exc,
                            only=only,
                            skip=skip,
                        )
                        _append_live_log(live_log_path, f"[run] critical_failure stage=m11 error={exc}")
                        return _finalize_run(
                            subject=subject,
                            cfg=cfg,
                            result=result,
                            out_dir=out_dir,
                            state=state,
                            state_path=state_path,
                            live_log_path=live_log_path,
                            only=only,
                            skip=skip,
                            force=force,
                            config_path=config_path,
                        )
        else:
            result.metrics["m11_skipped_reason"] = "No joined MEG-fMRI trial table."
        result.stage_timings_s["m11"] = perf_counter() - t0
        _emit("done", "m11")
        if progress_callback:
            progress_callback("m11")
    else:
        result.skipped_stages.append("m11")

    if _stage_selected("m12", only, skip) and _m6a_data_available:
        _emit("start", "m12")
        t0 = perf_counter()
        try:
            wv = getattr(cfg, "wave_validation", None)
            if wv and getattr(wv, "enabled", False):
                if epochs is not None:
                    _sim_source = epochs["ZINNEN"]
                    _sensor_xy_m12 = sensor_xy
                else:
                    # Use cached epoch shape + sensor positions — no raw reload needed.
                    _shape = np.load(_m6a_epoch_shape)
                    _sensor_xy_m12 = np.load(_m6a_sensor_xy)

                    class _FakeEpochs:
                        def get_data(self, picks=None):
                            return np.zeros((1, int(_shape["n_ch"]), int(_shape["n_t"])))
                        info = {"sfreq": float(_shape["sfreq"])}

                    _sim_source = _FakeEpochs()
                sim_data = simulate_two_dipoles(
                    _sim_source,
                    n_trials=int(getattr(wv, "n_trials", 60)),
                    snr=float(getattr(wv, "snr", 1.0)),
                    random_state=int(getattr(wv, "random_state", 42)),
                )
                _, null_dci = epochs_to_directions(_sim_source, _sensor_xy_m12, data_override=sim_data)
                null_summary = confound_null_dci(
                    dci_z,
                    null_dci,
                    z_threshold=float(getattr(wv, "z_threshold", 1.645)),
                )
                decision = _m12_z_threshold_decision(
                    float(null_summary.get("z", 0.0)),
                    float(null_summary.get("z_threshold", getattr(wv, "z_threshold", 1.645))),
                )
                result.metrics["aim3_two_dipole_z"] = null_summary["z"]
                result.metrics["m12_null_summary"] = null_summary
                result.metrics["aim3_two_dipole_z_threshold"] = decision["z_threshold"]
                result.metrics["aim3_two_dipole_passes_threshold"] = decision["passes_z_threshold"]
                result.metrics["aim3_two_dipole_z_margin"] = decision["z_margin"]
                result.metrics["aim3_wave_detected"] = bool(decision["passes_z_threshold"])
                result.metrics["aim3_z_threshold"] = float(decision["z_threshold"])
                result.metrics["m12_decision"] = decision
                m12_out = stage_output_dir(cfg, subject, "m12_wave_validation")
                np.save(m12_out / f"sub-{subject}_null_dci.npy", null_dci)
                result.outputs.append(m12_out / f"sub-{subject}_null_dci.npy")
            else:
                result.metrics["m12_skipped_reason"] = "wave_validation.enabled is false"
        except Exception as exc:
            result.metrics["m12_error"] = str(exc)
        result.stage_timings_s["m12"] = perf_counter() - t0
        _emit("done", "m12")
        if progress_callback:
            progress_callback("m12")
    else:
        result.skipped_stages.append("m12")

    if not _m6a_hit and _m6a_data_available:
        np.save(_m6a_paths["dirs_z"],    dirs_z)
        np.save(_m6a_paths["dirs_w"],    dirs_w)
        np.save(_m6a_paths["dirs_r"],    dirs_r)
        np.save(_m6a_paths["sliding_z"], sliding_z)
        np.save(_m6a_paths["dci_z"],     dci_z)
        np.save(_m6a_paths["dci_w"],     dci_w)
        np.save(_m6a_paths["dci_r"],     dci_r)
        np.save(_m6a_paths["sliding_t"], sliding_t)
        if sensor_xy is not None:
            np.save(_m6a_sensor_xy, sensor_xy)
        if epochs is not None:
            meg_data = epochs["ZINNEN"].get_data(picks="meg")
            np.savez(_m6a_epoch_shape, n_ch=meg_data.shape[1], n_t=meg_data.shape[2],
                     sfreq=epochs.info["sfreq"])
    if not _m6a_alpha_hit and _m6a_alpha_available:
        np.save(_m6a_alpha_paths["dirs_z"], alpha_dirs_z)
        np.save(_m6a_alpha_paths["dirs_w"], alpha_dirs_w)
        np.save(_m6a_alpha_paths["dirs_r"], alpha_dirs_r)
        np.save(_m6a_alpha_paths["dci_z"], alpha_dci_z)
        np.save(_m6a_alpha_paths["dci_w"], alpha_dci_w)
        np.save(_m6a_alpha_paths["dci_r"], alpha_dci_r)
    result.outputs.extend(out_files)

    if _stage_selected("m8", only, skip):
        _emit("start", "m8")
        t0 = perf_counter()
        preserved_metrics = _preserve_unselected_stage_metrics_for_reports(
            result.metrics,
            previous_manifest_metrics,
            set(result.metrics.get("selected_stages", [])),
        )
        if preserved_metrics:
            _append_live_log(
                live_log_path,
                f"[m8:metrics] preserved previous metrics: {','.join(preserved_metrics)}",
            )
        export_dir = export_subject_payload(
            subject,
            cfg,
            dirs_z=dirs_z,
            dirs_w=dirs_w,
            dirs_r=dirs_r,
            sliding_t=sliding_t,
            sliding_dci_z=sliding_z,
            metrics=result.metrics,
            trials_df=trial_df,
            joined_df=joined_df,
        )
        report_path = render_subject(
            subject,
            cfg,
            {
                "metrics": result.metrics,
                "stage_timings_s": result.stage_timings_s,
                "outputs": [str(p) for p in result.outputs],
            },
            dirs_z=dirs_z,
            dirs_w=dirs_w,
            dirs_r=dirs_r,
            sliding_t=sliding_t,
            sliding_dci_z=sliding_z,
        )
        try:
            aim2_subject_report = render_aim2_subject(
                subject,
                cfg,
                metrics=result.metrics,
                joined_csv=_m10_joined_csv,
            )
            result.outputs.append(aim2_subject_report)
        except Exception as exc:
            result.metrics["aim2_subject_report_error"] = str(exc)
        result.stage_timings_s["m8"] = perf_counter() - t0
        _emit("done", "m8")
        result.outputs.append(report_path)
        result.outputs.append(export_dir)
        quarto_path = render_quarto(subject, cfg)
        if quarto_path is not None:
            result.outputs.append(quarto_path)
        if progress_callback:
            progress_callback("m8")
    else:
        result.skipped_stages.append("m8")

    analysis_decisions = {
        "first_trial_indexing": {
            "column": "is_first_in_block",
            "derivation": "minimum_pos_in_block_per_block",
        },
        "hrf_lag_selection": result.metrics.get("m10_hrf_lag_selection", {"strategy": "none"}),
        "n400m_spec": result.metrics.get("aim1_n400m_spec", {}),
        "m11_correction_mode": "feature_roles_with_bh_fdr",
        "m12_threshold": result.metrics.get("aim3_two_dipole_z_threshold"),
    }
    _analysis_decisions_path.write_text(json.dumps(analysis_decisions, indent=2))
    result.metrics["analysis_decisions_artifact"] = str(_analysis_decisions_path)
    result.outputs.append(_analysis_decisions_path)

    if result.status not in {"failed", "completed_with_skips"}:
        result.status = "done"
    return _finalize_run(
        subject=subject,
        cfg=cfg,
        result=result,
        out_dir=out_dir,
        state=state,
        state_path=state_path,
        live_log_path=live_log_path,
        only=only,
        skip=skip,
        force=force,
        config_path=config_path,
    )
