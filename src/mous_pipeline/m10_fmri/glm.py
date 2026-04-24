"""Trial-wise first-level GLM helpers using nilearn."""

from __future__ import annotations

import gc

import numpy as np
import pandas as pd
from nilearn.glm.first_level import FirstLevelModel
from nilearn.maskers import NiftiLabelsMasker

from .roi import _atlas_and_label


def _lss_design(events_df: pd.DataFrame) -> pd.DataFrame:
    rows: list[dict] = []
    for idx, row in events_df.reset_index(drop=True).iterrows():
        for jdx, row_j in events_df.reset_index(drop=True).iterrows():
            rows.append(
                {
                    "onset": float(row_j["onset"]),
                    "duration": float(row_j.get("duration", 6.0)),
                    "trial_type": f"trial_{idx}" if idx == jdx else "other_trials",
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
) -> pd.DataFrame:
    """Fit LSS GLM and return trial-wise MTG beta values.

    Forces single-process nilearn (``n_jobs=1``) and eagerly tears down large
    objects + joblib pools before returning so the caller can advance to the
    next stage without blocking on a loky/joblib cleanup deadlock (seen on
    containerized fMRI runs where shutdown of worker pools can stall).
    """
    model = FirstLevelModel(
        t_r=tr,
        hrf_model="spm",
        noise_model="ar1",
        standardize=False,
        n_jobs=1,
    )
    design = _lss_design(events_df)
    model.fit(bold_nii, events=design, confounds=confounds)
    atlas_maps, labels, roi_name = _atlas_and_label(atlas, roi)
    if roi_name not in labels:
        roi_name = labels[0]
    roi_idx = labels.index(roi_name)
    masker = NiftiLabelsMasker(labels_img=atlas_maps, standardize=False)
    masker.fit()

    mtg_beta: list[float] = []
    try:
        for idx in range(len(events_df)):
            contrast_img = model.compute_contrast(f"trial_{idx}", output_type="effect_size")
            signal = masker.transform(contrast_img)
            mtg_beta.append(float(signal[:, roi_idx].mean()))
            del contrast_img, signal
    finally:
        del model, masker, design, atlas_maps, labels
        gc.collect()

    trial_ids = (
        events_df["trial_id"].to_numpy(dtype=int)
        if "trial_id" in events_df.columns
        else np.arange(len(events_df), dtype=int)
    )
    return pd.DataFrame({"trial_id": trial_ids, "mtg_beta": np.asarray(mtg_beta, dtype=float)})
