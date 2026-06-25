# Reproducibility guide

This document describes how to run MOUS portably: environment variables, lockfiles, Docker, and Apptainer.

## Environment variable contract

Set these before running cluster configs or submitting Slurm jobs:

| Variable | Purpose |
|----------|---------|
| `MOUS_DATA_ROOT` | Raw BIDS-like subject tree (CTF `.ds`, events TSV, T1w) |
| `MOUS_DERIVATIVES_ROOT` | Pipeline outputs, Slurm logs, FreeSurfer/fMRIPrep derivatives |
| `MOUS_DERIV_ROOT` | Alias used by some Slurm scripts (falls back to `MOUS_DERIVATIVES_ROOT`) |
| `MOUS_REPO` / `MOUS_REPO_ROOT` | Path to this repository checkout |
| `MOUS_CONTAINER_DIR` | Directory containing `fmriprep.sif` (HPC) |
| `MOUS_ACCOUNT` | Slurm allocation account |
| `MOUS_VENV_PATH` | Python virtualenv for HPC driver jobs |
| `FS_LICENSE` | FreeSurfer license file path (required for m5/m10) |

YAML configs support `${VAR}` interpolation (see `configs/palmetto_hpcnirc_fmri.yaml`). Empty `data_root` / `derivatives_root` fall back to `MOUS_DATA_ROOT` / `MOUS_DERIVATIVES_ROOT`.

Example (Palmetto):

```bash
export MOUS_DATA_ROOT=/scratch/$USER/mous_data
export MOUS_DERIVATIVES_ROOT=/scratch/$USER/mous_derivatives
export MOUS_CONTAINER_DIR=/scratch/$USER/containers
export FS_LICENSE=/data/freesurfer/license.txt
export MOUS_REPO=$PWD
export MOUS_ACCOUNT=your_allocation
```

Submit the driver:

```bash
export MOUS_DERIV_ROOT=$MOUS_DERIVATIVES_ROOT
sbatch scripts/run_mous_driver.sbatch
```

## Config templates

| File | Use case |
|------|----------|
| `configs/example_local.yaml` | Relative `./data` and `./derivatives` for local dev |
| `configs/example_container.yaml` | Container mount points `/data` and `/derivatives` |
| `configs/pilot_A2002.yaml` | Single-subject default for CLI examples |
| `configs/palmetto_hpcnirc_*.yaml` | HPC templates (require env vars above) |

## Dependency lockfiles

Pinned transitive dependencies live in:

- `requirements.lock` — runtime (core + `bids`, `fmri`, `ops` extras)
- `requirements-dev.lock` — runtime + `dev` (pytest, ruff)

Regenerate after changing `pyproject.toml`:

```bash
uv pip compile pyproject.toml --extra bids --extra fmri --extra ops -o requirements.lock --python-version 3.11
uv pip compile pyproject.toml --extra bids --extra fmri --extra ops --extra dev -o requirements-dev.lock --python-version 3.11
```

Canonical Python version: **3.11** (see `.python-version`). `requires-python >=3.10` remains supported; CI tests 3.10–3.12.

Install from lockfile:

```bash
pip install -r requirements-dev.lock
pip install --no-deps -e .
```

## Docker

Build:

```bash
docker build -t mous-pipeline:latest .
```

Run (mount data and derivatives; no credentials in the image):

```bash
docker run --rm \
  -v "$PWD/data:/data" \
  -v "$PWD/derivatives:/derivatives" \
  -v "$PWD/configs/example_container.yaml:/config.yaml:ro" \
  mous-pipeline:latest run --config /config.yaml --subject A2002 --dry-run
```

The image includes the Python/MNE pipeline (`m1`–`m9`, `m11`, `m12`) plus optional extras. It does **not** include:

- **FreeSurfer** — run recon-all separately; mount `subjects_dir` under `/derivatives/freesurfer`
- **fMRIPrep** — use the upstream Apptainer image (`nipreps/fmriprep`) as today
- **Quarto + R** — m8 Python reports still run; Quarto HTML is skipped when `quarto` is absent

## Apptainer (HPC)

Build from the local Docker image:

```bash
docker build -t mous-pipeline:latest .
apptainer build mous-pipeline.sif docker-daemon://mous-pipeline:latest
```

Or pull from GHCR after a tagged release:

```bash
apptainer pull mous-pipeline.sif docker://ghcr.io/JonathanWade24/MOUS:latest
```

Run on a compute node:

```bash
apptainer exec \
  -B "$MOUS_DATA_ROOT:/data" \
  -B "$MOUS_DERIVATIVES_ROOT:/derivatives" \
  -B "$PWD/configs:/config:ro" \
  --env MOUS_DATA_ROOT=/data \
  --env MOUS_DERIVATIVES_ROOT=/derivatives \
  mous-pipeline.sif run --config /config/example_container.yaml --subject A2002
```

Keep the existing fMRIPrep `.sif` workflow for stage m10; bind the same data/derivatives roots.
