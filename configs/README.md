# Configuration Examples

This directory contains example YAML configuration files for the MOUS pipeline.

## Available configs

| File | Description |
|------|-------------|
| `default.yaml` | Minimal baseline config with standard preprocessing and epoching parameters |
| `pilot_A2002.yaml` | Config for pilot subject A2002 (task + rest MEG only) |
| `pilot_A2003_fmri.yaml` | Pilot config with optional **fMRI** stages (m10, m11) enabled |
| `test_multi_A2003_A2006.yaml` | Multi-subject test config (A2003, A2006) |
| `mne_bids_pipeline/mous_config.py` | MNE-BIDS-Pipeline backend configuration (alternative preprocessing path) |

## Config structure

All YAML configs support these top-level sections:

### Required
- `data_root`: Path to BIDS-like data (CTF `.ds` + events TSV)
- `derivatives_root`: Where pipeline outputs land (default: `derivatives/mous_pipeline`)

### Optional
- `subjects`: List of subject IDs (used by multi-subject workflows)
- `rdr`: RDR/WebDAV settings (`collection_path` for `fetch-rdr`)
- `preprocess`: Backend (`inhouse` or `mne_bids_pipeline`), notch freqs, ICA params
- `epoching`: Time window (`tmin`, `tmax`), baseline, trial count thresholds
- `features`: Frequency bands (theta, alpha, beta, gamma)
- `source`: FreeSurfer paths (`subjects_dir`, `use_fsaverage`, beamformer settings)
- `fmri`: BOLD paths, TR, atlas/ROI for m10/m11 coupling stages
- `wave_validation`: Enable m12 simulation (`enabled`, `n_trials`, `snr`)

## Usage

```bash
mous-pipeline run --config configs/pilot_A2002.yaml --subject A2002
mous-pipeline run --config configs/pilot_A2003_fmri.yaml --subject A2003
```

See `README.md` at repo root for full CLI documentation.
