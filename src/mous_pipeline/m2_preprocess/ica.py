"""Module 2 ICA helpers."""

from __future__ import annotations

import mne
from mne.preprocessing import ICA

from ..config import PipelineConfig


def fit_and_apply(raw: mne.io.BaseRaw, cfg: PipelineConfig) -> tuple[mne.io.BaseRaw, ICA]:
    if cfg.preprocess.backend == "mne_bids_pipeline":
        raise NotImplementedError("mne_bids_pipeline backend is declared but not implemented yet.")

    ica = ICA(
        n_components=cfg.preprocess.ica_n_components,
        random_state=42,
        method="fastica",
        max_iter="auto",
    )
    raw_fit = raw.copy().filter(1, 100, method="fir", fir_window="hamming", verbose="WARNING")
    ica.fit(raw_fit, picks="meg")

    ecg_indices, ecg_scores = ica.find_bads_ecg(raw, method="correlation", threshold=cfg.preprocess.ecg_threshold)
    if ecg_indices and len(ecg_indices) > cfg.preprocess.ecg_max_components:
        top = sorted(range(len(ecg_indices)), key=lambda i: abs(ecg_scores[i]), reverse=True)[
            : cfg.preprocess.ecg_max_components
        ]
        ecg_indices = [ecg_indices[i] for i in sorted(top)]

    try:
        eog_indices, _ = ica.find_bads_eog(raw)
    except RuntimeError:
        eog_indices = []

    ica.exclude = list(set(ecg_indices + eog_indices))
    ica.apply(raw)
    return raw, ica
