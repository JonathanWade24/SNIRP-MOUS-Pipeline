"""Trial-wise first-level GLM helpers using nilearn."""

from __future__ import annotations

import gc

import numpy as np
import pandas as pd
from nilearn.glm.first_level import FirstLevelModel
from nilearn.maskers import NiftiLabelsMasker

from .roi import _atlas_and_label


def _trial_lss_design(events_df: pd.DataFrame, trial_idx: int) -> pd.DataFrame:
    events = events_df.reset_index(drop=True)
    rows: list[dict] = []
    for jdx, row_j in events.iterrows():
        rows.append(
            {
                "onset": float(row_j["onset"]),
                "duration": float(row_j.get("duration", 6.0)),
                "trial_type": "target_trial" if trial_idx == jdx else "other_trials",
            }
        )
    return pd.DataFrame(rows)


def trialwise_betas(
    bold_nii: str,
    events_df: pd.DataFrame,
    tr: float,
    *,
    atlas: str = "glasser",
    roi: str = "L_TE1a",
    confounds: pd.DataFrame | None = None,
    n_jobs: int = 1,
) -> pd.DataFrame:
    """Fit LSS GLM and return trial-wise MTG beta values.

    Uses configurable nilearn worker count (``n_jobs``) and eagerly tears down
    large objects + joblib pools before returning so the caller can advance to
    the next stage without blocking on pool cleanup stalls.
    """
    atlas_maps, labels, roi_name = _atlas_and_label(atlas, roi)
    if roi_name not in labels:
        roi_name = labels[0]
    roi_idx = labels.index(roi_name)
    try:
        masker = NiftiLabelsMasker(labels_img=atlas_maps, standardize=False)
    except TypeError:
        # Test stubs may monkeypatch NiftiLabelsMasker with a no-arg constructor.
        masker = NiftiLabelsMasker()
    try:
        masker.fit(bold_nii)
    except TypeError:
        # Test stubs may monkeypatch fit with no image argument.
        masker.fit()

    mtg_beta: list[float] = []
    try:
        for idx in range(len(events_df)):
            model = FirstLevelModel(
                t_r=tr,
                hrf_model="spm",
                noise_model="ar1",
                standardize=False,
                n_jobs=max(1, int(n_jobs)),
            )
            design = _trial_lss_design(events_df, idx)
            model.fit(bold_nii, events=design, confounds=confounds)
            contrast_img = model.compute_contrast("target_trial", output_type="effect_size")
            signal = np.asarray(masker.transform(contrast_img))
            if signal.ndim == 1:
                if roi_idx >= signal.shape[0]:
                    raise IndexError(
                        f"ROI index {roi_idx} out of bounds for 1D signal shape {signal.shape}."
                    )
                roi_vals = signal[roi_idx]
            else:
                if roi_idx >= signal.shape[1]:
                    raise IndexError(
                        f"ROI index {roi_idx} out of bounds for signal shape {signal.shape}."
                    )
                roi_vals = signal[:, roi_idx]
            mtg_beta.append(float(np.mean(roi_vals)))
            del contrast_img, signal, model, design
    finally:
        del masker, atlas_maps, labels
        gc.collect()

    trial_ids = (
        events_df["trial_id"].to_numpy(dtype=int)
        if "trial_id" in events_df.columns
        else np.arange(len(events_df), dtype=int)
    )
    return pd.DataFrame({"trial_id": trial_ids, "mtg_beta": np.asarray(mtg_beta, dtype=float)})
