"""Module 3 task epoching."""

from __future__ import annotations

import mne
import pandas as pd

from ..config import PipelineConfig
from ..m1_events.parse import CONDITION_IDS, make_events_array, make_events_metadata


def make_epochs(
    raw: mne.io.BaseRaw,
    trials: pd.DataFrame,
    cfg: PipelineConfig,
) -> tuple[mne.Epochs, pd.DataFrame]:
    """Return (epochs, trial_meta) aligned to surviving epochs after rejection.

    trial_meta is always a subset of make_events_metadata(trials) containing
    only the rows whose epochs were not dropped by amplitude/flat rejection.
    Callers must not use the original trials DataFrame for per-trial analyses
    after this point — use the returned trial_meta instead.
    """
    events = make_events_array(trials, raw.info["sfreq"])
    epochs = mne.Epochs(
        raw,
        events,
        event_id=CONDITION_IDS,
        tmin=cfg.epoching.tmin,
        tmax=cfg.epoching.tmax,
        baseline=cfg.epoching.baseline,
        picks="meg",
        preload=True,
        reject={"mag": 4e-12},
        flat={"mag": 1e-15},
        reject_by_annotation=False,
        verbose="WARNING",
    )
    trial_meta = make_events_metadata(trials).iloc[epochs.selection].reset_index(drop=True)
    assert len(epochs) == len(trial_meta), (
        f"make_epochs: epoch/trial_meta length mismatch after selection "
        f"({len(epochs)} vs {len(trial_meta)}) — this is a bug in selection indexing"
    )
    return epochs, trial_meta
