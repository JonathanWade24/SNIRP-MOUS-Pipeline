# SSH-First Ops TUI

`mous-pipeline ops` provides a single-terminal operations interface for Palmetto workflows.
The UI treats `mous_driver` as an orchestrator that can launch independent tracks
(MEG outputs, optional m5 source models, and fMRI preprocessing).

## Install

```bash
pip install -e ".[ops]"
```

## Launch interactive TUI

```bash
mous-pipeline ops ui
```

Screens:
- `Dashboard`: active jobs + tracked runs.
- `New Run`: subject selection, workflow selection, and resource submission.
- `Run Results`: quick links to driver/fMRIPrep logs and manifest paths.
- `Log Viewer`: newest logs grouped by Driver/fMRI/Download/BIDS.

Built-in workflow presets:
- `Download Only`: fetch from RDR; no processing.
- `BIDS Convert + Validate`: normalize and validate data only.
- `Dry Run (No Submit)`: preview submit commands.
- `Multimodal Driver (MEG + fMRI preprocess)`: runs subject/group MEG outputs and submits detached fMRI preprocessing array jobs.
- `Multimodal Driver + Anatomical Source Models (m5)`: same as above, with source-model generation.
- `fMRI Preprocessing Only`: submits only the detached fMRIPrep array path.

Why this matters:
- The driver job can finish before `mous_fmriprep_*` jobs finish. This is expected behavior.
- Monitor both `mous_driver_*` and `fmriprep_*` logs for full completion.

Aim2 report artifacts (written during `m8`):
- Subject HTML: `<derivatives_root>/<subject>/m8_reports/<subject>_aim2_summary.html`
- Group HTML: `<derivatives_root>/group_aim2_summary.html`

## Non-interactive mode

Preview:

```bash
mous-pipeline ops run \
  --preset full_submit \
  --config configs/palmetto_hpcnirc_fmri.yaml \
  --subjects A2002,A2003 \
  --account YOUR_ACCOUNT
```

Execute:

```bash
mous-pipeline ops run \
  --preset m5_enabled_submit \
  --config configs/palmetto_hpcnirc_fmri.yaml \
  --subjects A2002,A2003 \
  --account YOUR_ACCOUNT \
  --execute
```

Recent tracked jobs:

```bash
mous-pipeline ops status --limit 20
```

Queue + log classifier:

```bash
mous-pipeline ops monitor --job-id 12345678 --log-file /scratch/$USER/mous_derivatives/slurm/mous_driver_12345678.err
```

## Persistent state

State is stored in:

`~/.config/mous_ops/state.json`

Includes:
- defaults (`account`, `partition`, resource knobs, venv path)
- named subject sets
- preset catalog (built-in + saved custom presets)
- recent tracked jobs
