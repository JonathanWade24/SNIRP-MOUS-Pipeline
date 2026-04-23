# Contributor Guide

## Module ownership

- Team A: `m0_intake`, `m1_events`
- Team B: `m2_preprocess`
- Team C: `m3_epoching`, `m4_features`
- Team D: `m5_source`, `m10_fmri` (optional fMRI / GLM join)
- Team E: `m6_waves`, `m12_wave_validation` (optional null / simulation validation)
- Team F: `m7_stats`, `m8_reports`, `m9_orchestration`, `m11_coupling` (optional MEG–fMRI coupling)

Stage IDs in the runner: `m1`–`m4`, `m4_trial`, `m5`, `m6a`, `m6_extra`, `m10`, `m11`, `m12`, `m7`, `m8`, `m9` (see `stage_dependencies.py`).

## Notebook policy

- Use notebooks for exploration, pilot debugging, and figure prototyping.
- Authoritative logic must live in `src/mous_pipeline/`.
