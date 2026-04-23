"""Helpers to add BIDS metadata in-place for MOUS subjects."""

from __future__ import annotations

from pathlib import Path

import mne
from mne_bids import BIDSPath, write_raw_bids

from .naming import rest_ds, task_ds


def _subject_label(subject: str) -> str:
    return subject.removeprefix("sub-")


def convert_subject_to_bids(subject: str, cfg) -> list[BIDSPath]:
    """
    Add BIDS sidecars/metadata in-place for task and rest recordings.

    This assumes data are already laid out under ``data_root/sub-<id>/meg/`` with
    CTF datasets named in BIDS style (``*_meg.ds``).
    """
    subj = _subject_label(subject)
    bids_paths: list[BIDSPath] = []
    runs = [
        ("auditory", task_ds(subj, cfg.data_root)),
        ("rest", rest_ds(subj, cfg.data_root)),
    ]
    for task_name, ds_path in runs:
        if not Path(ds_path).exists():
            continue
        raw = mne.io.read_raw_ctf(str(ds_path), preload=False, system_clock="truncate", verbose="ERROR")
        bids_path = BIDSPath(
            root=Path(cfg.data_root),
            subject=subj,
            task=task_name,
            datatype="meg",
            suffix="meg",
            extension=".ds",
        )
        write_raw_bids(raw, bids_path=bids_path, overwrite=True, allow_preload=False, format="CTF", verbose=False)
        bids_paths.append(bids_path)
    if not bids_paths:
        raise FileNotFoundError(f"No CTF MEG datasets found for subject sub-{subj} in {cfg.data_root}.")
    return bids_paths
