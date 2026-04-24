#!/usr/bin/env python3
"""Post-merge Aim 1 regression/QC audit for one subject.

Checks:
- Event/epoch onset alignment against Audio onset rows.
- Condition split sanity (ZINNEN/WOORDEN present and non-empty).
- Regression guard: make_events_metadata must retain onset for m10.
- Pre-stim beta quicklook means + histogram artifact.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

import numpy as np
import pandas as pd

from mous_pipeline.config import load_config
from mous_pipeline.m0_intake.naming import events_tsv, task_ds
from mous_pipeline.m1_events.parse import make_events_metadata, parse_events
from mous_pipeline.m2_preprocess.filter import apply_band, apply_notch_and_resample
from mous_pipeline.m2_preprocess.ica import fit_and_apply
from mous_pipeline.m3_epoching.task import make_epochs


def _resolve_path(cfg, subject: str, key: str, fallback: Path) -> Path:
    custom = cfg.paths.get(key)
    return cfg.data_root / custom if custom else fallback


def _save_quicklook(
    out_dir: Path,
    *,
    z_power: np.ndarray,
    w_power: np.ndarray,
    trials: pd.DataFrame,
    subject: str,
) -> None:
    out_dir.mkdir(parents=True, exist_ok=True)
    quicklook_csv = out_dir / f"sub-{subject}_aim1_quicklook.csv"
    pd.DataFrame(
        {
            "trial_id": np.arange(len(trials), dtype=int),
            "condition": trials["condition"].to_numpy(dtype=str),
            "onset": trials["onset"].to_numpy(dtype=float),
        }
    ).to_csv(quicklook_csv, index=False)

    try:
        import matplotlib.pyplot as plt

        fig, ax = plt.subplots(figsize=(7, 4))
        ax.hist(z_power, bins=20, alpha=0.6, label="ZINNEN")
        ax.hist(w_power, bins=20, alpha=0.6, label="WOORDEN")
        ax.set_title(f"sub-{subject} pre-stim beta power quicklook")
        ax.set_xlabel("Mean beta power (-0.8 to 0 s)")
        ax.set_ylabel("Count")
        ax.legend(loc="best")
        fig.tight_layout()
        fig.savefig(out_dir / f"sub-{subject}_aim1_quicklook.png", dpi=150)
        plt.close(fig)
    except Exception:
        # Plot is best-effort; CSV + JSON are still emitted.
        pass


def run_audit(config_path: Path, subject_raw: str) -> int:
    cfg = load_config(config_path)
    subject = subject_raw.removeprefix("sub-")
    out_dir = cfg.derivatives_root / f"sub-{subject}" / "audit"
    out_dir.mkdir(parents=True, exist_ok=True)

    ev_path = _resolve_path(cfg, subject, "events_tsv", events_tsv(subject, cfg.data_root))
    ds_path = _resolve_path(cfg, subject, "task_ds", task_ds(subject, cfg.data_root))

    failures: list[str] = []
    warnings: list[str] = []

    trials = parse_events(str(ev_path), strict=True)
    if trials.empty:
        failures.append("No audio-onset trials parsed from events TSV.")
    if set(trials["condition"].unique()) != {"ZINNEN", "WOORDEN"}:
        failures.append("Expected both ZINNEN and WOORDEN in parsed audio-onset trials.")

    # Regression guard for merged m10 onset metadata behavior.
    trial_meta = make_events_metadata(trials)
    if "onset" not in trial_meta.columns:
        failures.append("Regression detected: make_events_metadata output lacks 'onset' column required by m10.")

    import mne

    raw = mne.io.read_raw_ctf(str(ds_path), preload=True, system_clock="truncate", verbose="WARNING")
    raw.apply_gradient_compensation(3)
    raw = apply_notch_and_resample(raw, cfg)
    raw, _ica = fit_and_apply(raw, cfg)
    raw = apply_band(raw, 13, 30)
    epochs = make_epochs(raw, trials, cfg)

    # Alignment check: event samples generated from onset should match epoch events.
    n_cmp = min(5, len(trials), len(epochs.events))
    onset_samples = (trials["onset"].to_numpy(dtype=float)[:n_cmp] * raw.info["sfreq"]).round().astype(int)
    epoch_samples = epochs.events[:n_cmp, 0]
    if not np.array_equal(onset_samples, epoch_samples):
        failures.append(
            "Epoch event samples do not match trial onsets for first events "
            f"(onset={onset_samples.tolist()} epoch={epoch_samples.tolist()})."
        )

    z_epochs = epochs["ZINNEN"]
    w_epochs = epochs["WOORDEN"]
    if len(z_epochs) == 0 or len(w_epochs) == 0:
        failures.append("Condition epoch split invalid: ZINNEN/WOORDEN epochs must both be non-empty.")

    z_power = z_epochs.copy().crop(tmin=-0.8, tmax=0.0).get_data(picks="meg").mean(axis=(1, 2))
    w_power = w_epochs.copy().crop(tmin=-0.8, tmax=0.0).get_data(picks="meg").mean(axis=(1, 2))
    mean_z = float(np.mean(z_power)) if len(z_power) else float("nan")
    mean_w = float(np.mean(w_power)) if len(w_power) else float("nan")
    delta = abs(mean_z - mean_w)
    if np.isfinite(delta) and delta < 1e-12:
        warnings.append("Pre-stim beta means are nearly identical; review quicklook artifacts for potential label issues.")

    _save_quicklook(out_dir, z_power=z_power, w_power=w_power, trials=trials, subject=subject)
    summary = {
        "subject": subject,
        "n_trials": int(len(trials)),
        "n_zinnen": int((trials["condition"] == "ZINNEN").sum()),
        "n_woorden": int((trials["condition"] == "WOORDEN").sum()),
        "prestim_mean_zinnen": mean_z,
        "prestim_mean_woorden": mean_w,
        "prestim_abs_diff": delta,
        "failures": failures,
        "warnings": warnings,
        "status": "fail" if failures else "pass",
    }
    (out_dir / f"sub-{subject}_aim1_audit_summary.json").write_text(json.dumps(summary, indent=2))
    print(json.dumps(summary, indent=2))
    return 1 if failures else 0


def main() -> int:
    parser = argparse.ArgumentParser(description="Run post-merge Aim 1 regression/QC audit.")
    parser.add_argument("--config", required=True, help="Pipeline YAML config path.")
    parser.add_argument("--subject", required=True, help="Subject ID with or without sub- prefix.")
    args = parser.parse_args()
    return run_audit(Path(args.config).expanduser().resolve(), args.subject)


if __name__ == "__main__":
    raise SystemExit(main())
