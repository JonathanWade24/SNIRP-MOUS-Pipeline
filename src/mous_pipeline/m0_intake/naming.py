"""Module 0 naming conventions and path helpers."""

from __future__ import annotations

from pathlib import Path


def task_ds(subject: str, root: str | Path = ".") -> Path:
    return Path(root) / f"sub-{subject}" / "meg" / f"sub-{subject}_task-auditory_meg.ds"


def rest_ds(subject: str, root: str | Path = ".") -> Path:
    return Path(root) / f"sub-{subject}" / "meg" / f"sub-{subject}_task-rest_meg.ds"


def events_tsv(subject: str, root: str | Path = ".") -> Path:
    return Path(root) / f"sub-{subject}" / "meg" / f"sub-{subject}_task-auditory_events.tsv"


def t1_nii(subject: str, root: str | Path = ".") -> Path:
    return Path(root) / f"sub-{subject}" / "anat" / f"sub-{subject}_T1w.nii"
