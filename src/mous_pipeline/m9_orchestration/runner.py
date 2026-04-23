"""Module 9 subject runner."""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from time import perf_counter
import time
from typing import Callable

import mne
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
from ..m7_stats.trialwise import lme_block_control, logreg_condition_from_prestim, n400m_condition_t
from ..m8_reports.quarto_report import render_quarto_suite
from ..m8_reports.dashboard import render_subject
from ..m8_reports.export import export_subject_payload
from ..m11_coupling.regress import run_coupling_models
from ..m12_wave_validation.compare import confound_null_dci
from ..m12_wave_validation.simulate import simulate_two_dipoles
from ..provenance import build_run_manifest, config_fingerprint, write_manifest
from ..stage_dependencies import STAGE_ORDER, list_missing_stage_dependencies
from .gating import PilotGate
from .memory_probe import StageRSSProbe

@dataclass
class RunResult:
    subject: str
    metrics: dict = field(default_factory=dict)
    outputs: list[Path] = field(default_factory=list)
    stage_timings_s: dict[str, float] = field(default_factory=dict)
    skipped_stages: list[str] = field(default_factory=list)

    def summary(self) -> str:
        verdict = self.metrics.get("pilot_verdict", "unknown")
        skipped = f", skipped={','.join(self.skipped_stages)}" if self.skipped_stages else ""
        return f"Subject {self.subject}: pilot verdict={verdict}{skipped}"


def _stage_selected(stage: str, only: set[str] | None, skip: set[str] | None) -> bool:
    if only and stage not in only:
        return False
    if skip and stage in skip:
        return False
    return True


def _resolve_path(cfg, subject: str, key: str, fallback: Path) -> Path:
    custom = cfg.paths.get(key)
    return cfg.data_root / custom if custom else fallback


def _validate_stage_dependencies(selected: list[str]) -> None:
    errs = list_missing_stage_dependencies(selected)
    if errs:
        raise ValueError("Invalid stage selection: " + "; ".join(errs))


def _write_run_state(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(payload, indent=2))
    tmp.replace(path)


def _append_live_log(path: Path, message: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a") as f:
        f.write(message.rstrip() + "\n")


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
) -> RunResult:
    result = RunResult(subject=subject)
    selected = [s for s in STAGE_ORDER if _stage_selected(s, only, skip)]
    _validate_stage_dependencies(selected)
    result.metrics["selected_stages"] = selected
    out_dir = stage_output_dir(cfg, subject, "m9_orchestration")
    m4_out_dir = stage_output_dir(cfg, subject, "m4_features")
    state_path = out_dir / f"sub-{subject}_run_state.json"
    live_log_path = out_dir / f"sub-{subject}_run_live.log"
    stage_index = {s: i + 1 for i, s in enumerate(selected)}
    completed: list[str] = []
    state: dict[str, object] = {
        "subject": subject,
        "status": "running",
        "selected_stages": selected,
        "current_stage": None,
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
    _append_live_log(live_log_path, f"[run] subject={subject} status=running stages={','.join(selected)}")

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
            state["current_stage_started_at"] = time.time()
            state["stage_index"] = stage_index.get(stage, 0)
            _append_live_log(
                live_log_path,
                f"[stage start] {stage} ({state['stage_index']}/{state['stage_total']})",
            )
        elif event == "done":
            if stage not in completed:
                completed.append(stage)
            state["stage_timings_s"] = dict(result.stage_timings_s)
            state["last_event"] = f"done:{stage}"
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
            stage_index,
            completed,
            _emit,
            memory_probe,
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
    stage_index: dict[str, int],
    completed: list[str],
    _emit: Callable[[str, str], None],
    memory_probe: StageRSSProbe | None,
) -> RunResult:
    _ = memory_probe  # reserved for future intra-body hooks
    out_dir = stage_output_dir(cfg, subject, "m9_orchestration")
    m4_out_dir = stage_output_dir(cfg, subject, "m4_features")
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
    trial_meta = make_events_metadata(trials)

    # ── Per-stage output file paths ───────────────────────────────────────────
    _m4_analytic  = m4_out_dir / f"{subject}_beta_analytic.npz"
    _m4_psd       = m4_out_dir / f"{subject}_beta_psd.npz"
    _m4t_prestim  = m4_out_dir / f"{subject}_prestim_beta.npz"
    _m4t_n400m    = m4_out_dir / f"{subject}_n400m.npz"
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
    out_files = list(_m6a_paths.values())

    # ── Per-stage cache flags (all invalidated by force=True) ─────────────────
    _m4_hit      = not force and _m4_analytic.exists() and _m4_psd.exists()
    _m4trial_hit = not force and _m4t_prestim.exists() and _m4t_n400m.exists()
    _m6a_hit     = (
        not force
        and all(p.exists() for p in _m6a_paths.values())
        and _m6a_sensor_xy.exists()
        and _m6a_epoch_shape.exists()
    )

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
    task_raw = None
    ica = None
    if _needs_epochs:
        if backend == "mne_bids_pipeline":
            from ..m2_preprocess.bids_pipeline_backend import run_preprocessing

            epochs, epochs_rest = run_preprocessing(subject, cfg)
        else:
            task_raw = mne.io.read_raw_ctf(str(task_path), preload=True, system_clock="truncate", verbose="WARNING")
            task_raw.apply_gradient_compensation(3)
            task_raw = apply_notch_and_resample(task_raw, cfg)
            task_raw, ica = fit_and_apply(task_raw, cfg)
            task_raw = apply_band(task_raw, 13, 30)
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
        epochs = make_epochs(task_raw, trials, cfg)
    result.stage_timings_s["m3"] = perf_counter() - t0
    _emit("done", "m3")
    if progress_callback and _stage_selected("m3", only, skip):
        progress_callback("m3")

    # ── m4: analytic signal + PSD ─────────────────────────────────────────────
    analytic_features = None
    trial_df = trial_meta.copy()
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
            prestim_beta = np.load(_m4t_prestim)["prestim_beta"]
            n400m        = np.load(_m4t_n400m)["n400m"]
        else:
            assert epochs is not None
            prestim_beta = prestim_beta_power(epochs, subject, cfg, trial_meta)
            n400m        = n400m_amplitude(epochs, subject, cfg, trial_meta)
        y = (trial_meta["condition"] == "ZINNEN").to_numpy(dtype=int)
        result.metrics["aim1_prestim_auc"] = logreg_condition_from_prestim(prestim_beta, y)
        result.metrics["aim1_n400m_zinnen_vs_woorden_t"] = n400m_condition_t(
            n400m,
            trial_meta["condition"].to_numpy(dtype=str),
        )
        trial_df["prestim_beta"] = prestim_beta
        trial_df["n400m"] = n400m
        result.stage_timings_s["m4_trial"] = perf_counter() - t0
        _emit("done", "m4_trial")
        if progress_callback:
            progress_callback("m4_trial")
    else:
        result.skipped_stages.append("m4_trial")

    # ── rest data (only needed when m6a requires fresh computation) ───────────
    if not _m6a_hit and backend != "mne_bids_pipeline":
        rest_raw = mne.io.read_raw_ctf(str(rest_path), preload=True, system_clock="truncate", verbose="WARNING")
        rest_raw.apply_gradient_compensation(3)
        rest_raw = apply_notch_and_resample(rest_raw, cfg)
        assert ica is not None
        ica.apply(rest_raw)
        rest_raw = apply_band(rest_raw, 13, 30)
        epoch_len = cfg.epoching.tmax - cfg.epoching.tmin
        epochs_rest = make_pseudo_epochs(rest_raw, epoch_len)

    # ── m6a: phase-gradient waves + DCI ───────────────────────────────────────
    _emit("start", "m6a")
    t0 = perf_counter()
    sensor_xy = None
    meg_picks: list[int] = []
    if _stage_selected("m6a", only, skip) and _m6a_hit:
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
    else:
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
    result.stage_timings_s["m6a"] = perf_counter() - t0
    _emit("done", "m6a")
    if progress_callback and _stage_selected("m6a", only, skip):
        progress_callback("m6a")
    result.metrics["dci_zinnen"] = float(np.mean(dci_z))
    result.metrics["dci_woorden"] = float(np.mean(dci_w))
    result.metrics["dci_rest"] = float(np.mean(dci_r))
    result.metrics["n_rest"] = len(dci_r)
    if not trial_df.empty:
        n_z = len(dci_z)
        n_w = len(dci_w)
        trial_df.loc[trial_df["condition"] == "ZINNEN", "dci_trial"] = dci_z[:n_z]
        trial_df.loc[trial_df["condition"] == "WOORDEN", "dci_trial"] = dci_w[:n_w]

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
                        "fsaverage" if source_cfg.use_fsaverage else f"sub-{subject}",
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
                    result.outputs += [
                        m5_out / f"sub-{subject}_source_dirs.npy",
                        m5_out / f"sub-{subject}_source_dci.npy",
                    ]
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

    _emit("start", "m7")
    t0 = perf_counter()
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
    if {"dci_trial", "pos_in_block"}.issubset(trial_df.columns):
        model_df = trial_df.dropna(subset=["dci_trial", "pos_in_block"]).copy()
        if not model_df.empty:
            p_block, _ = lme_block_control(model_df, "dci_trial ~ C(condition) + pos_in_block")
            result.metrics["aim1_dci_block_effect_p"] = p_block
    result.stage_timings_s["m7"] = perf_counter() - t0
    _emit("done", "m7")
    if progress_callback and _stage_selected("m7", only, skip):
        progress_callback("m7")

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
    if _stage_selected("m10", only, skip):
        _emit("start", "m10")
        t0 = perf_counter()
        try:
            fmri_cfg = getattr(cfg, "fmri", None)
            if fmri_cfg:
                from ..m10_fmri.glm import trialwise_betas
                from ..m10_fmri.prep import resolve_subject_bold_path, run_fmriprep, validate_tr_from_sidecar

                fmriprep_out = run_fmriprep(subject, cfg, bids_root=cfg.data_root)
                bold_path = resolve_subject_bold_path(
                    subject,
                    cfg,
                    bids_root=cfg.data_root,
                    fmriprep_out_dir=fmriprep_out,
                )
                if bold_path is None:
                    expected_func_dir = cfg.data_root / f"sub-{subject.removeprefix('sub-')}" / "func"
                    expected_func_dir.mkdir(parents=True, exist_ok=True)
                    result.metrics["m10_skipped_reason"] = (
                        "No BOLD file found. Checked config fmri.bold_path, BIDS func paths, and "
                        f"{fmriprep_out}/sub-{subject.removeprefix('sub-')}/func. "
                        f"Created expected directory: {expected_func_dir}"
                    )
                else:
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
                    )
                    joined_df = trial_df.merge(beta_tbl, on="trial_id", how="inner")
                    result.metrics["m10_n_trials_joined"] = int(len(joined_df))
                    m10_out = stage_output_dir(cfg, subject, "m10_fmri")
                    joined_csv = m10_out / f"{subject}_trials_joined.csv"
                    joined_df.to_csv(joined_csv, index=False)
                    result.outputs.append(joined_csv)
            else:
                result.metrics["m10_skipped_reason"] = "fmri configuration missing"
        except Exception as exc:
            result.metrics["m10_error"] = str(exc)
        result.stage_timings_s["m10"] = perf_counter() - t0
        _emit("done", "m10")
        if progress_callback:
            progress_callback("m10")
    else:
        result.skipped_stages.append("m10")

    if _stage_selected("m11", only, skip):
        _emit("start", "m11")
        t0 = perf_counter()
        if joined_df is not None and not joined_df.empty:
            try:
                coupling = run_coupling_models(joined_df)
                result.metrics["m11_coupling"] = coupling
            except Exception as exc:
                result.metrics["m11_error"] = str(exc)
        else:
            result.metrics["m11_skipped_reason"] = "No joined MEG-fMRI trial table."
        result.stage_timings_s["m11"] = perf_counter() - t0
        _emit("done", "m11")
        if progress_callback:
            progress_callback("m11")
    else:
        result.skipped_stages.append("m11")

    if _stage_selected("m12", only, skip):
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
                null_summary = confound_null_dci(dci_z, null_dci)
                result.metrics["aim3_two_dipole_z"] = null_summary["z"]
                result.metrics["m12_null_summary"] = null_summary
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

    if not _m6a_hit:
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
    result.outputs.extend(out_files)

    if _stage_selected("m8", only, skip):
        _emit("start", "m8")
        t0 = perf_counter()
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
        result.stage_timings_s["m8"] = perf_counter() - t0
        _emit("done", "m8")
        result.outputs.append(report_path)
        result.outputs.append(export_dir)
        for quarto_path in render_quarto_suite(subject, cfg):
            result.outputs.append(quarto_path)
        if progress_callback:
            progress_callback("m8")
    else:
        result.skipped_stages.append("m8")

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
    manifest["metrics"] = result.metrics
    write_manifest(out_dir / f"sub-{subject}_run_manifest.json", manifest)
    result.outputs.append(out_dir / f"sub-{subject}_run_manifest.json")
    state["status"] = "done"
    state["current_stage"] = None
    state["current_stage_started_at"] = None
    state["stage_timings_s"] = dict(result.stage_timings_s)
    state["last_event"] = "done:all"
    state["updated_at"] = time.time()
    _write_run_state(state_path, state)
    _append_live_log(live_log_path, "[run] status=done")
    return result
