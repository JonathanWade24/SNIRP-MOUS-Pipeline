"""Helpers to add BIDS metadata in-place for MOUS subjects."""

from __future__ import annotations

import csv
import json
from pathlib import Path

import mne
from mne_bids import BIDSPath, write_raw_bids

from .naming import rest_ds, task_ds


def _subject_label(subject: str) -> str:
    return subject.removeprefix("sub-")


_CHANNEL_TYPE_MAP = {
    "eeg": "EEG",
    "eog": "EOG",
    "ecg": "ECG",
    "emg": "EMG",
    "trigger": "TRIG",
    "stim": "TRIG",
    "refmag": "MEGREFMAG",
    "refgrad": "MEGREFGRAD",
    "megmag": "MEGMAG",
    "meggrad": "MEGGRAD",
    "misc": "MISC",
    "unknown": "MISC",
    "adc": "MISC",
    "clock": "MISC",
}
_ALLOWED_CHANNEL_TYPES = {
    "EEG",
    "EOG",
    "ECG",
    "EMG",
    "TRIG",
    "MEGREFMAG",
    "MEGREFGRAD",
    "MEGMAG",
    "MEGGRAD",
    "MISC",
}


def _normalize_channels_tsv(channels_tsv: Path) -> bool:
    """Normalize channels.tsv types to BIDS-friendly uppercase values."""
    if not channels_tsv.exists():
        return False
    with channels_tsv.open("r", newline="") as f:
        reader = csv.DictReader(f, delimiter="\t")
        rows = list(reader)
        fieldnames = reader.fieldnames or []
    if not rows or "type" not in fieldnames:
        return False

    changed = False
    for row in rows:
        original = str(row.get("type", "")).strip()
        mapped = _CHANNEL_TYPE_MAP.get(original.lower(), original.upper())
        if mapped not in _ALLOWED_CHANNEL_TYPES:
            mapped = "MISC"
        if mapped != original:
            row["type"] = mapped
            changed = True

    if changed:
        with channels_tsv.open("w", newline="") as f:
            writer = csv.DictWriter(f, fieldnames=fieldnames, delimiter="\t")
            writer.writeheader()
            writer.writerows(rows)
    return changed


def _ensure_dataset_level_files(root: Path) -> None:
    desc = root / "dataset_description.json"
    if not desc.exists():
        desc.write_text(
            json.dumps(
                {
                    "Name": "MOUS dataset",
                    "BIDSVersion": "1.8.0",
                    "DatasetType": "raw",
                    "Authors": ["MOUS team"],
                },
                indent=2,
            )
        )
    readme = root / "README"
    if not readme.exists():
        readme.write_text("MOUS BIDS dataset for MEG/fMRI pipeline processing.\n")


def _normalize_subject_anat_filenames(subject: str, root: Path) -> list[Path]:
    """Rename non-BIDS `space-CTF` T1w files to BIDS-compatible `acq-CTF`."""
    sub = _subject_label(subject)
    anat_dir = root / f"sub-{sub}" / "anat"
    if not anat_dir.exists():
        return []
    renamed: list[Path] = []
    for ext in (".nii.gz", ".nii", ".json"):
        src = anat_dir / f"sub-{sub}_space-CTF_T1w{ext}"
        if not src.exists():
            continue
        dst = anat_dir / f"sub-{sub}_acq-CTF_T1w{ext}"
        if src == dst:
            continue
        src.rename(dst)
        renamed.append(dst)
    return renamed


def convert_subject_to_bids(subject: str, cfg) -> list[BIDSPath]:
    """
    Add BIDS sidecars/metadata in-place for task and rest recordings.

    This assumes data are already laid out under ``data_root/sub-<id>/meg/`` with
    CTF datasets named in BIDS style (``*_meg.ds``).
    """
    subj = _subject_label(subject)
    root = Path(cfg.data_root)
    _ensure_dataset_level_files(root)
    _normalize_subject_anat_filenames(subj, root)
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
            root=root,
            subject=subj,
            task=task_name,
            datatype="meg",
            suffix="meg",
            extension=".ds",
        )
        # mne-bids >= current accepts meg format as "FIF"/"auto" only.
        # Use auto-detection so CTF source data are handled correctly.
        write_raw_bids(raw, bids_path=bids_path, overwrite=True, allow_preload=False, format="auto", verbose=False)
        channels_tsv = root / f"sub-{subj}" / "meg" / f"sub-{subj}_task-{task_name}_channels.tsv"
        _normalize_channels_tsv(channels_tsv)
        bids_paths.append(bids_path)
    if not bids_paths:
        raise FileNotFoundError(f"No CTF MEG datasets found for subject sub-{subj} in {cfg.data_root}.")
    return bids_paths
