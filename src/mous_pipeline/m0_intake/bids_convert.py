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
    # Standard sensor types
    "eeg": "EEG",
    "eog": "EOG",
    "ecg": "ECG",
    "emg": "EMG",
    "trigger": "TRIG",
    "stim": "TRIG",
    # CTF MEG sensor types — BIDS requires fully qualified gradiometer subtypes.
    # CTF uses axial gradiometers for both primary sensors and reference channels.
    "megmag": "MEGMAG",
    "meggrad": "MEGGRADAXIAL",
    "refmag": "MEGREFMAG",
    "refgrad": "MEGREFGRADAXIAL",
    # Catch-all for non-standard / vendor-specific labels
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
    "MEGMAG",
    "MEGGRADAXIAL",
    "MEGGRADPLANAR",
    "MEGREFMAG",
    "MEGREFGRADAXIAL",
    "MEGREFGRADPLANAR",
    "MISC",
}


def normalize_channel_type(channel_type: str) -> str:
    """Return a BIDS-compliant channel type label."""
    original = str(channel_type or "").strip()
    mapped = _CHANNEL_TYPE_MAP.get(original.lower(), original.upper())
    if mapped not in _ALLOWED_CHANNEL_TYPES:
        return "MISC"
    return mapped


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
        mapped = normalize_channel_type(original)
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
    expected = {
        "Name": "MOUS dataset",
        "BIDSVersion": "1.8.0",
        "DatasetType": "raw",
        "Authors": ["MOUS team"],
    }
    payload: dict[str, object] = {}
    if desc.exists():
        try:
            payload = json.loads(desc.read_text())
            if not isinstance(payload, dict):
                payload = {}
        except Exception:
            payload = {}
    for k, v in expected.items():
        if k not in payload or payload[k] in ("", None, []):
            payload[k] = v
    desc.write_text(json.dumps(payload, indent=2))
    readme = root / "README"
    if not readme.exists() or not readme.read_text().strip():
        readme.write_text("MOUS BIDS dataset for MEG/fMRI pipeline processing.\n")


def _normalize_subject_anat_filenames(subject: str, root: Path) -> list[Path]:
    """Rename non-BIDS `space-CTF` T1w files to BIDS-compatible `acq-CTF`.

    Also updates any subject-level scans.tsv that references the old filename,
    which fMRIPrep's bids-validator checks via SCANS_FILENAME_NOT_MATCH_DATASET.
    """
    sub = _subject_label(subject)
    anat_dir = root / f"sub-{sub}" / "anat"
    if not anat_dir.exists():
        return []
    renamed: list[Path] = []
    renames: list[tuple[str, str]] = []  # (old_rel, new_rel) for scans.tsv update
    for ext in (".nii.gz", ".nii", ".json"):
        src = anat_dir / f"sub-{sub}_space-CTF_T1w{ext}"
        if not src.exists():
            continue
        dst = anat_dir / f"sub-{sub}_acq-CTF_T1w{ext}"
        if src == dst:
            continue
        src.rename(dst)
        renamed.append(dst)
        if ext in (".nii.gz", ".nii"):
            old_rel = f"anat/{src.name}"
            new_rel = f"anat/{dst.name}"
            renames.append((old_rel, new_rel))

    # Update sub-*_scans.tsv unconditionally — patch any residual space-CTF
    # references even when the file rename already happened on a prior run.
    _ANAT_RENAME_PAIRS = [
        (f"anat/sub-{sub}_space-CTF_T1w.nii.gz", f"anat/sub-{sub}_acq-CTF_T1w.nii.gz"),
        (f"anat/sub-{sub}_space-CTF_T1w.nii",    f"anat/sub-{sub}_acq-CTF_T1w.nii"),
    ]
    for scans_tsv in (root / f"sub-{sub}").glob("*_scans.tsv"):
        try:
            text = scans_tsv.read_text()
            updated = text
            for old_rel, new_rel in _ANAT_RENAME_PAIRS:
                updated = updated.replace(old_rel, new_rel)
            if updated != text:
                scans_tsv.write_text(updated)
        except Exception:
            pass

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
        ds_path_obj = Path(ds_path)
        if not ds_path_obj.exists():
            continue
        raw = mne.io.read_raw_ctf(str(ds_path_obj), preload=False, system_clock="truncate", verbose="ERROR")
        bids_path = BIDSPath(
            root=root,
            subject=subj,
            task=task_name,
            datatype="meg",
            suffix="meg",
            extension=".ds",
        )
        target_ds = root / f"sub-{subj}" / "meg" / f"sub-{subj}_task-{task_name}_meg.ds"
        if target_ds.resolve() != ds_path_obj.resolve():
            # mne-bids >= current accepts meg format as "FIF"/"auto" only.
            # Use auto-detection so CTF source data are handled correctly.
            write_raw_bids(raw, bids_path=bids_path, overwrite=True, allow_preload=False, format="auto", verbose=False)
        channels_tsv = root / f"sub-{subj}" / "meg" / f"sub-{subj}_task-{task_name}_channels.tsv"
        _normalize_channels_tsv(channels_tsv)
        bids_paths.append(bids_path)
    if not bids_paths:
        raise FileNotFoundError(f"No CTF MEG datasets found for subject sub-{subj} in {cfg.data_root}.")
    return bids_paths
