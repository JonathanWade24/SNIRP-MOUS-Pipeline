# Example configs

| File | Notes |
|------|--------|
| `default.yaml` | Baseline parameters |
| `pilot_A2002.yaml` | Single subject, MEG |
| `pilot_A2003_fmri.yaml` | fMRI-related stages (m10/m11) |
| `test_multi_A2003_A2006.yaml` | Multi-subject list |
| `mne_bids_pipeline/mous_config.py` | MNE-BIDS-Pipeline backend config |

Top-level keys: `data_root`, `derivatives_root`, optional `subjects`, `rdr`, `preprocess`, `epoching`, `features`, `source`, `fmri`, `wave_validation`.

```bash
mous-pipeline run --config configs/pilot_A2002.yaml --subject A2002
```

See the root `README.md` for full CLI usage.
