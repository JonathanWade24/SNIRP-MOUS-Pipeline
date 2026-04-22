# Contributor Guide

## Module ownership

- Team A: `m0_intake`, `m1_events`
- Team B: `m2_preprocess`
- Team C: `m3_epoching`, `m4_features`
- Team D: `m5_source`
- Team E: `m6_waves`
- Team F: `m7_stats`, `m8_reports`, `m9_orchestration`

## Notebook policy

- Use notebooks for exploration, pilot debugging, and figure prototyping.
- Authoritative logic must live in `src/mous_pipeline/`.
