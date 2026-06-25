# Example configs

| File | Notes |
|------|--------|
| `example_local.yaml` | Relative `./data` and `./derivatives` for local dev |
| `example_container.yaml` | Docker/Apptainer mount points `/data` and `/derivatives` |
| `pilot_A2002.yaml` | Single-subject default for CLI/GUI examples |
| `cohort_15subjects_fmri.yaml` | 13-subject HPC cohort (M5 workflow) |
| `palmetto_hpcnirc_fmri.yaml` | Palmetto pilot template (uses `${MOUS_*}` env vars) |
| `palmetto_hpcnirc_A2003_A2012.yaml` | Palmetto 10-subject cohort |
| `palmetto_hpcnirc_A2004_A2014.yaml` | Palmetto 11-subject cohort |
| `mne_bids_pipeline/mous_config.py` | MNE-BIDS-Pipeline backend config |

Palmetto and cohort configs expect environment variables such as `MOUS_DATA_ROOT`, `MOUS_DERIVATIVES_ROOT`, `MOUS_CONTAINER_DIR`, and `FS_LICENSE`. See [docs/reproducibility.md](../docs/reproducibility.md).

Top-level keys: `data_root`, `derivatives_root`, optional `subjects`, `rdr`, `preprocess`, `epoching`, `features`, `source`, `fmri`, `wave_validation`, `pipeline`.

Useful `pipeline` knobs:
- `strict_stage_failures`: hard-fail critical stage errors (`m10`, `m11`) instead of permissive degrade.
- `m10_n_jobs`: configure m10 GLM nilearn worker count.
- `m10_force_gc`: force an explicit cleanup pass after m10.

```bash
mous-pipeline run --config configs/pilot_A2002.yaml --subject A2002
```

See the root `README.md` for full CLI usage.
