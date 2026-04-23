"""ROI extraction for trial-wise beta maps."""

from __future__ import annotations

import numpy as np
from nilearn import datasets
from nilearn.maskers import NiftiLabelsMasker


def _atlas_and_label(atlas: str, roi: str):
    atlas_key = atlas.lower().strip()
    if atlas_key == "glasser":
        schaefer = datasets.fetch_atlas_schaefer_2018(n_rois=400, yeo_networks=7, resolution_mm=2)
        labels = [lab.decode("utf-8") if isinstance(lab, bytes) else str(lab) for lab in schaefer.labels]
        return schaefer.maps, labels, roi
    aal = datasets.fetch_atlas_aal()
    labels = [str(l) for l in aal.labels]
    target = roi if roi in labels else "Temporal_Mid_L"
    return aal.maps, labels, target


def extract_mtg_beta(beta_imgs, atlas: str = "glasser", roi: str = "L_TE1a") -> np.ndarray:
    """Extract mean ROI beta value per trial map."""
    atlas_maps, labels, roi_name = _atlas_and_label(atlas, roi)
    if roi_name not in labels:
        # Graceful fallback for atlas naming mismatch.
        roi_name = "Temporal_Mid_L" if "Temporal_Mid_L" in labels else labels[0]
    roi_idx = labels.index(roi_name)
    masker = NiftiLabelsMasker(labels_img=atlas_maps, standardize=False)
    values = []
    for img in beta_imgs:
        signal = masker.fit_transform(img)
        values.append(float(signal[:, roi_idx].mean()))
    return np.asarray(values, dtype=float)
