"""Module 5 source reconstruction forward model."""

from __future__ import annotations

from pathlib import Path

import mne


def resolve_trans_path(trans: str, subject: str) -> str:
    """Resolve a configured MNE trans value for a subject."""
    if trans == "fsaverage":
        return trans
    sid = subject.removeprefix("sub-")
    return str(Path(trans.format(subject=sid, subject_bids=f"sub-{sid}")).expanduser())


def build_forward_model(subject: str, raw, cfg) -> tuple[mne.Forward, mne.SourceSpaces]:
    """Build a forward model for subject-level source analysis.

    This function requires `cfg.source.subjects_dir` to be set and readable.
    """
    source_cfg = getattr(cfg, "source", None)
    if source_cfg is None or not source_cfg.subjects_dir:
        raise ValueError("cfg.source.subjects_dir is required for Module 5.")
    subjects_dir = Path(source_cfg.subjects_dir).expanduser()
    if not subjects_dir.exists():
        raise FileNotFoundError(f"subjects_dir does not exist: {subjects_dir}")

    sid = subject.removeprefix("sub-")
    use_fsaverage = bool(getattr(source_cfg, "use_fsaverage", True))
    mri_subject = "fsaverage" if use_fsaverage else f"sub-{sid}"
    spacing = str(getattr(source_cfg, "spacing", "oct6"))
    trans = resolve_trans_path(str(getattr(source_cfg, "trans", "fsaverage")), subject)
    conductivity = tuple(getattr(source_cfg, "conductivity", (0.3,)))

    src = mne.setup_source_space(
        subject=mri_subject,
        spacing=spacing,
        add_dist=False,
        subjects_dir=str(subjects_dir),
    )
    bem_model = mne.make_bem_model(subject=mri_subject, ico=4, conductivity=conductivity, subjects_dir=str(subjects_dir))
    bem = mne.make_bem_solution(bem_model)
    fwd = mne.make_forward_solution(
        info=raw.info,
        trans=trans,
        src=src,
        bem=bem,
        meg=True,
        eeg=False,
        mindist=5.0,
        n_jobs=1,
    )
    return fwd, src
