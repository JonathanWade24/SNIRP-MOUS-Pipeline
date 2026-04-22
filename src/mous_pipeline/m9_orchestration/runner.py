"""Module 9 subject runner."""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from time import perf_counter

import mne
import numpy as np

from ..io import stage_output_dir
from ..m8_reports.dashboard import render_subject
from ..m0_intake.naming import events_tsv, rest_ds, task_ds
from ..m1_events.parse import parse_events
from ..m2_preprocess.filter import apply_band, apply_notch_and_resample
from ..m2_preprocess.ica import fit_and_apply
from ..m3_epoching.rest import make_pseudo_epochs
from ..m3_epoching.task import make_epochs
from ..m6_waves.phase_gradient import directional_consistency_index, epochs_to_directions, get_sensor_positions
from ..m7_stats.circular import rayleigh_p
from ..m7_stats.permutation import perm_test_dci
from ..provenance import build_run_manifest, config_fingerprint, write_manifest
from .gating import PilotGate


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
) -> RunResult:
    result = RunResult(subject=subject)
    selected = [s for s in ["m1", "m2", "m3", "m6a", "m7", "m8", "m9"] if _stage_selected(s, only, skip)]
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
    result.metrics["n_trials"] = len(trials)
    result.metrics["n_zinnen"] = int((trials["condition"] == "ZINNEN").sum())
    result.metrics["n_woorden"] = int((trials["condition"] == "WOORDEN").sum())

    out_dir = stage_output_dir(cfg, subject, "m9_orchestration")
    out_files = [
        out_dir / f"sub-{subject}_dirs_zinnen.npy",
        out_dir / f"sub-{subject}_dirs_woorden.npy",
        out_dir / f"sub-{subject}_dirs_rest.npy",
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

    t0 = perf_counter()
    epochs = make_epochs(task_raw, trials, cfg)
    result.stage_timings_s["m3"] = perf_counter() - t0

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
    result.stage_timings_s["m6a"] = perf_counter() - t0
    result.metrics["dci_zinnen"] = float(np.mean(dci_z))
    result.metrics["dci_woorden"] = float(np.mean(dci_w))
    result.metrics["dci_rest"] = float(np.mean(dci_r))

    t0 = perf_counter()
    _, p_sz = perm_test_dci(dci_z, dci_r)
    result.metrics["p_task_vs_rest"] = p_sz
    result.metrics["p_rayleigh_zinnen"] = rayleigh_p(dirs_z)
    result.metrics["dci_zinnen_pooled"] = directional_consistency_index(dirs_z)
    result.metrics["dci_woorden_pooled"] = directional_consistency_index(dirs_w)
    result.metrics["dci_rest_pooled"] = directional_consistency_index(dirs_r)
    result.stage_timings_s["m7"] = perf_counter() - t0

    t0 = perf_counter()
    gate = PilotGate().evaluate(result.metrics)
    result.metrics["pilot_verdict"] = gate["verdict"]
    result.metrics["pilot_gate"] = gate
    result.stage_timings_s["m9"] = perf_counter() - t0

    np.save(out_dir / f"sub-{subject}_dirs_zinnen.npy", dirs_z)
    np.save(out_dir / f"sub-{subject}_dirs_woorden.npy", dirs_w)
    np.save(out_dir / f"sub-{subject}_dirs_rest.npy", dirs_r)
    result.outputs.extend(out_files)

    if _stage_selected("m8", only, skip):
        t0 = perf_counter()
        report_path = render_subject(
            subject,
            cfg,
            {
                "metrics": result.metrics,
                "stage_timings_s": result.stage_timings_s,
                "outputs": [str(p) for p in result.outputs],
            },
        )
        result.stage_timings_s["m8"] = perf_counter() - t0
        result.outputs.append(report_path)
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
