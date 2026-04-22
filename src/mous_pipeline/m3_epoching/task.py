"""Module 3 task epoching."""

from __future__ import annotations

import mne
import pandas as pd

from ..config import PipelineConfig
from ..m1_events.parse import CONDITION_IDS, make_events_array


def make_epochs(raw: mne.io.BaseRaw, trials: pd.DataFrame, cfg: PipelineConfig) -> mne.Epochs:
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
    return epochs
