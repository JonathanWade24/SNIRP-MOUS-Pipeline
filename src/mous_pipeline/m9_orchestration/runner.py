"""Module 9 subject runner."""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from time import perf_counter
from typing import Callable

import mne
import numpy as np

from ..io import stage_output_dir
from ..m4_features.hilbert import analytic_signal
from ..m4_features.spectral import psd
from ..m0_intake.naming import events_tsv, rest_ds, task_ds
from ..m1_events.parse import parse_events
from ..m2_preprocess.filter import apply_band, apply_notch_and_resample
from ..m2_preprocess.ica import fit_and_apply
from ..m3_epoching.rest import make_pseudo_epochs
from ..m3_epoching.task import make_epochs
from ..m5_source.forward import build_forward_model
from ..m5_source.inverse import compute_inverse
from ..m5_source.roi import extract_roi_timeseries
from ..m6_waves.cfc import CFCDetector
from ..m6_waves.fft2d import FFT2DDetector
from ..m6_waves.flow_field import FlowFieldDetector
from ..m6_waves.phase_gradient import (
    directional_consistency_index,
    epochs_to_directions,
    get_sensor_positions,
    sliding_dci,
)
from ..m6_waves.rotational import RotationalDetector
from ..m7_stats.circular import rayleigh_p
from ..m7_stats.permutation import perm_test_dci
from ..m8_reports.dashboard import render_subject
from ..m8_reports.export import export_subject_payload
from ..m8_reports.quarto_report import render_quarto
from ..provenance import build_run_manifest, config_fingerprint, write_manifest
from .gating import PilotGate

STAGE_ORDER = ["m1", "m2", "m3", "m4", "m5", "m6a", "m6_extra", "m7", "m8", "m9"]


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
) -> RunResult:
    result = RunResult(subject=subject)
    selected = [s for s in STAGE_ORDER if _stage_selected(s, only, skip)]
    result.metrics["selected_stages"] = selected
    if dry_run:
        result.metrics["dry_run"] = True
        return result

    events_path = _resolve_path(cfg, subject, "events_tsv", events_tsv(subject, cfg.data_root))
    task_path = _resolve_path(cfg, subject, "task_ds", task_ds(subject, cfg.data_root))
    rest_path = _resolve_path(cfg, subject, "rest_ds", rest_ds(subject, cfg.data_root))

    t0 = perf_counter()
    trials = parse_events(str(events_path), strict=True)
    result.stage_timings_s["m1"] = perf_counter() - t0
    if progress_callback and _stage_selected("m1", only, skip):
        progress_callback("m1")
    result.metrics["n_trials"] = len(trials)
    result.metrics["n_zinnen"] = int((trials["condition"] == "ZINNEN").sum())
    result.metrics["n_woorden"] = int((trials["condition"] == "WOORDEN").sum())

    out_dir = stage_output_dir(cfg, subject, "m9_orchestration")
    out_files = [
        out_dir / f"sub-{subject}_dirs_zinnen.npy",
        out_dir / f"sub-{subject}_dirs_woorden.npy",
        out_dir / f"sub-{subject}_dirs_rest.npy",
        out_dir / f"sub-{subject}_sliding_dci_zinnen.npy",
    ]
    if not force and all(p.exists() for p in out_files):
        result.metrics["cache_hit"] = True
        result.outputs.extend(out_files)
        return result

    t0 = perf_counter()
    task_raw = mne.io.read_raw_ctf(str(task_path), preload=True, system_clock="truncate", verbose="WARNING")
    task_raw.apply_gradient_compensation(3)
    task_raw = apply_notch_and_resample(task_raw, cfg)
    task_raw, ica = fit_and_apply(task_raw, cfg)
    task_raw = apply_band(task_raw, 13, 30)
    result.stage_timings_s["m2"] = perf_counter() - t0
    if progress_callback and _stage_selected("m2", only, skip):
        progress_callback("m2")

    t0 = perf_counter()
    epochs = make_epochs(task_raw, trials, cfg)
    result.stage_timings_s["m3"] = perf_counter() - t0
    if progress_callback and _stage_selected("m3", only, skip):
        progress_callback("m3")

    analytic_features = None
    if _stage_selected("m4", only, skip):
        t0 = perf_counter()
        analytic_features = analytic_signal(epochs, subject, cfg, "beta")
        psd(epochs, subject, cfg, "beta", 13.0, 30.0)
        result.stage_timings_s["m4"] = perf_counter() - t0
        if progress_callback:
            progress_callback("m4")
    else:
        result.skipped_stages.append("m4")

    rest_raw = mne.io.read_raw_ctf(str(rest_path), preload=True, system_clock="truncate", verbose="WARNING")
    rest_raw.apply_gradient_compensation(3)
    rest_raw = apply_notch_and_resample(rest_raw, cfg)
    ica.apply(rest_raw)
    rest_raw = apply_band(rest_raw, 13, 30)
    epoch_len = cfg.epoching.tmax - cfg.epoching.tmin
    epochs_rest = make_pseudo_epochs(rest_raw, epoch_len)
    result.metrics["n_rest"] = len(epochs_rest)

    t0 = perf_counter()
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
    if progress_callback and _stage_selected("m6a", only, skip):
        progress_callback("m6a")
    result.metrics["dci_zinnen"] = float(np.mean(dci_z))
    result.metrics["dci_woorden"] = float(np.mean(dci_w))
    result.metrics["dci_rest"] = float(np.mean(dci_r))

    if _stage_selected("m5", only, skip):
        source_cfg = getattr(cfg, "source", None)
        if source_cfg and source_cfg.subjects_dir:
            t0 = perf_counter()
            try:
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
            except Exception as exc:
                result.metrics["m5_error"] = str(exc)
            result.stage_timings_s["m5"] = perf_counter() - t0
            if progress_callback:
                progress_callback("m5")
        else:
            result.metrics["m5_skipped_reason"] = "source.subjects_dir not configured"
            result.skipped_stages.append("m5")
    else:
        result.skipped_stages.append("m5")

    if _stage_selected("m6_extra", only, skip):
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
        if progress_callback:
            progress_callback("m6_extra")
    else:
        result.skipped_stages.append("m6_extra")

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
    result.stage_timings_s["m7"] = perf_counter() - t0
    if progress_callback and _stage_selected("m7", only, skip):
        progress_callback("m7")

    t0 = perf_counter()
    gate = PilotGate().evaluate(result.metrics)
    result.metrics["pilot_verdict"] = gate["verdict"]
    result.metrics["pilot_gate"] = gate
    result.stage_timings_s["m9"] = perf_counter() - t0
    if progress_callback and _stage_selected("m9", only, skip):
        progress_callback("m9")

    np.save(out_dir / f"sub-{subject}_dirs_zinnen.npy", dirs_z)
    np.save(out_dir / f"sub-{subject}_dirs_woorden.npy", dirs_w)
    np.save(out_dir / f"sub-{subject}_dirs_rest.npy", dirs_r)
    np.save(out_dir / f"sub-{subject}_sliding_dci_zinnen.npy", sliding_z)
    result.outputs.extend(out_files)

    if _stage_selected("m8", only, skip):
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
        result.outputs.append(report_path)
        result.outputs.append(export_dir)
        quarto_path = render_quarto(subject, cfg)
        if quarto_path:
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
    return result
