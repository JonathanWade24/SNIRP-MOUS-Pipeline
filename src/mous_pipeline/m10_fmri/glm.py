"""Trial-wise first-level GLM helpers using nilearn."""

from __future__ import annotations

import pandas as pd
from nilearn.glm.first_level import FirstLevelModel


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
    confounds: pd.DataFrame | None = None,
) -> pd.DataFrame:
    """Fit LSS GLM and return one left-out beta map label per trial."""
    model = FirstLevelModel(t_r=tr, hrf_model="spm", noise_model="ar1", standardize=False)
    design = _lss_design(events_df)
    model.fit(bold_nii, events=design, confounds=confounds)
    # lightweight serializable references; ROI module resolves maps.
    return pd.DataFrame(
        {
            "trial_id": range(len(events_df)),
            "contrast_name": [f"trial_{i}" for i in range(len(events_df))],
        }
    )
