# SSH-First Ops TUI

`mous-pipeline ops` provides a single-terminal operations interface for Palmetto workflows.

## Install

```bash
pip install -e ".[ops]"
```

## Launch interactive TUI

```bash
mous-pipeline ops ui
```

Tabs:
- `Env`: startup checks for `python3`, `sbatch`, `sacct`, optional container/runtime tools, and venv activation hints.
- `Subjects`: load subjects from config/filesystem, multi-select, save/load named subject sets.
- `Workflows`: choose built-in preset (download-only, BIDS convert+validate, dry-run submit, full submit, m5-enabled, fMRIPrep-only), preview commands, run commands, save manual presets.
- `Monitor`: poll SLURM state and classify recent failures from log tails.

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
