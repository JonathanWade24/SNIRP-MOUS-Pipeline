"""
Template MNE-BIDS-Pipeline config for MOUS.

This file is primarily a reference. Runtime configs are generated dynamically by
`src/mous_pipeline/m2_preprocess/bids_pipeline_backend.py` so values match the
active YAML configuration and selected subject(s).
"""

# Paths (filled dynamically at runtime)
bids_root = "REPLACE_BIDS_ROOT"
deriv_root = "REPLACE_DERIV_ROOT"
subjects = ["REPLACE_SUBJECT"]

# Dataset selection
task = "auditory"
ch_types = ["meg"]

# Preprocessing (aligned with PipelineConfig defaults)
l_freq = 1.0
h_freq = None
raw_resample_sfreq = 300.0
spatial_filter = "ica"
ica_n_components = 40

# Epoching
epochs_tmin = -0.5
epochs_tmax = 3.0
baseline = (-0.5, 0.0)
conditions = ["ZINNEN", "WOORDEN"]

# Source-level defaults
use_template_mri = "fsaverage"
spacing = "oct6"
