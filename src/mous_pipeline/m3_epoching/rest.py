"""Module 3 rest pseudo-epoching."""

from __future__ import annotations

import mne


def make_pseudo_epochs(raw_rest: mne.io.BaseRaw, epoch_len_s: float) -> mne.Epochs:
    rest_events = mne.make_fixed_length_events(raw_rest, id=99, duration=epoch_len_s, overlap=0.0)
    epochs_rest = mne.Epochs(
        raw_rest,
        rest_events,
        event_id={"rest": 99},
        tmin=0,
        tmax=epoch_len_s - 1 / raw_rest.info["sfreq"],
        baseline=None,
        picks="meg",
        preload=True,
        reject={"mag": 4e-12},
        verbose="WARNING",
    )
    return epochs_rest
