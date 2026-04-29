# Example configs

| File | Notes |
|------|--------|
| `palmetto_hpcnirc_fmri.yaml` | Canonical Palmetto config for pilot/current runs |
| `palmetto_hpcnirc_A2004_A2014.yaml` | Canonical Palmetto cohort config |
| `mne_bids_pipeline/mous_config.py` | MNE-BIDS-Pipeline backend config |

Top-level keys: `data_root`, `derivatives_root`, optional `subjects`, `rdr`, `preprocess`, `epoching`, `features`, `source`, `fmri`, `wave_validation`, `pipeline`.

Useful `pipeline` knobs:
- `strict_stage_failures`: hard-fail critical stage errors (`m10`, `m11`) instead of permissive degrade.
- `m10_n_jobs`: configure m10 GLM nilearn worker count.
- `m10_force_gc`: force an explicit cleanup pass after m10.

```bash
mous-pipeline run --config configs/palmetto_hpcnirc_fmri.yaml --subject A2002
```

See the root `README.md` for full CLI usage.
