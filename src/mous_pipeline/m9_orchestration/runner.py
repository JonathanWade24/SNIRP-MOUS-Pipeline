"""Module 9 subject runner."""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

import mne
import numpy as np

from ..io import stage_output_dir
from ..m0_intake.naming import events_tsv, rest_ds, task_ds
from ..m1_events.parse import parse_events
from ..m2_preprocess.filter import apply_band, apply_notch_and_resample
from ..m2_preprocess.ica import fit_and_apply
from ..m3_epoching.rest import make_pseudo_epochs
from ..m3_epoching.task import make_epochs
from ..m6_waves.phase_gradient import directional_consistency_index, epochs_to_directions, get_sensor_positions
from ..m7_stats.circular import rayleigh_p
from ..m7_stats.permutation import perm_test_dci
from .gating import PilotGate


@dataclass
class RunResult:
    subject: str
    metrics: dict = field(default_factory=dict)
    outputs: list[Path] = field(default_factory=list)

    def summary(self) -> str:
        verdict = self.metrics.get("pilot_verdict", "unknown")
        return f"Subject {self.subject}: pilot verdict={verdict}"


def run_subject(subject: str, cfg) -> RunResult:
    result = RunResult(subject=subject)
    trials = parse_events(str(events_tsv(subject, cfg.data_root)))
    result.metrics["n_trials"] = len(trials)
    result.metrics["n_zinnen"] = int((trials["condition"] == "ZINNEN").sum())
    result.metrics["n_woorden"] = int((trials["condition"] == "WOORDEN").sum())

    task_raw = mne.io.read_raw_ctf(str(task_ds(subject, cfg.data_root)), preload=True, system_clock="truncate", verbose="WARNING")
    task_raw.apply_gradient_compensation(3)
    task_raw = apply_notch_and_resample(task_raw, cfg)
    task_raw, ica = fit_and_apply(task_raw, cfg)
    task_raw = apply_band(task_raw, 13, 30)
    epochs = make_epochs(task_raw, trials, cfg)

    rest_raw = mne.io.read_raw_ctf(str(rest_ds(subject, cfg.data_root)), preload=True, system_clock="truncate", verbose="WARNING")
    rest_raw.apply_gradient_compensation(3)
    rest_raw = apply_notch_and_resample(rest_raw, cfg)
    ica.apply(rest_raw)
    rest_raw = apply_band(rest_raw, 13, 30)
    epoch_len = cfg.epoching.tmax - cfg.epoching.tmin
    epochs_rest = make_pseudo_epochs(rest_raw, epoch_len)
    result.metrics["n_rest"] = len(epochs_rest)

    sensor_xy, meg_picks = get_sensor_positions(epochs.info)
    dirs_z, dci_z = epochs_to_directions(epochs["ZINNEN"], sensor_xy, meg_picks)
    dirs_w, dci_w = epochs_to_directions(epochs["WOORDEN"], sensor_xy, meg_picks)
    dirs_r, dci_r = epochs_to_directions(epochs_rest, sensor_xy, meg_picks)
    result.metrics["dci_zinnen"] = float(np.mean(dci_z))
    result.metrics["dci_woorden"] = float(np.mean(dci_w))
    result.metrics["dci_rest"] = float(np.mean(dci_r))

    _, p_sz = perm_test_dci(dci_z, dci_r)
    result.metrics["p_task_vs_rest"] = p_sz
    result.metrics["p_rayleigh_zinnen"] = rayleigh_p(dirs_z)
    result.metrics["dci_zinnen_pooled"] = directional_consistency_index(dirs_z)
    result.metrics["dci_woorden_pooled"] = directional_consistency_index(dirs_w)
    result.metrics["dci_rest_pooled"] = directional_consistency_index(dirs_r)

    gate = PilotGate().evaluate(result.metrics)
    result.metrics["pilot_verdict"] = gate["verdict"]
    out_dir = stage_output_dir(cfg, subject, "m9_orchestration")
    np.save(out_dir / f"sub-{subject}_dirs_zinnen.npy", dirs_z)
    np.save(out_dir / f"sub-{subject}_dirs_woorden.npy", dirs_w)
    np.save(out_dir / f"sub-{subject}_dirs_rest.npy", dirs_r)
    result.outputs.extend([out_dir / f"sub-{subject}_dirs_zinnen.npy", out_dir / f"sub-{subject}_dirs_woorden.npy", out_dir / f"sub-{subject}_dirs_rest.npy"])
    return result
