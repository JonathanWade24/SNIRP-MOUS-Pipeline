# Palmetto `hpcnirc` Setup

This guide covers cloning, environment setup, FreeSurfer recon-all, and SLURM submission for Clemson Palmetto using the `hpcnirc` partition.

## 1) Clone and bootstrap

```bash
git clone https://github.com/JonathanWade24/MOUS.git
cd MOUS

# Optional: set site-specific modules.
export MOUS_PYTHON_MODULE="python/3.11"
export MOUS_APPTAINER_MODULE="apptainer"
export MOUS_FREESURFER_MODULE="freesurfer/7.4.1"

# Optional: set location for venv and container images.
export MOUS_VENV_PATH="$HOME/.venvs/mous-palmetto"
export MOUS_CONTAINER_DIR="/project/$USER/containers"
export MOUS_PULL_FMRIPREP=1

bash scripts/palmetto_setup.sh
source "$MOUS_VENV_PATH/bin/activate"
```

## 2) Configure your YAML

Start from:

- `configs/palmetto_hpcnirc_fmri.yaml`

Set these values for your allocation:

- `data_root`
- `derivatives_root`
- `fmri.fmriprep_container`
- `fmri.fs_license_file`
- `fmri.container_binds`
- `source.subjects_dir` (for m5)

Avoid spaces in all fMRI/source paths (`data_root`, `fmriprep_output`, FreeSurfer output/work paths), otherwise fMRIPrep/FSL/ANTs may fail.

## 3) Optional: run FreeSurfer recon-all for m5

If you want m5 source reconstruction, create FreeSurfer outputs first:

```bash
scripts/palmetto_recon_all.sh \
  --config configs/palmetto_hpcnirc_fmri.yaml \
  --subjects A2002,A2003 \
  --account YOUR_ACCOUNT \
  --dry-run
```

Submit by removing `--dry-run`. Expected outputs per subject:

- `<derivatives_root>/freesurfer/sub-AXXX/mri/brain.mgz`
- `<derivatives_root>/freesurfer/sub-AXXX/surf/lh.white`
- `<derivatives_root>/freesurfer/sub-AXXX/surf/rh.white`

## 4) Dry-run before submit

```bash
scripts/palmetto_submit.sh \
  --config configs/palmetto_hpcnirc_fmri.yaml \
  --subjects A2002,A2003 \
  --account YOUR_ACCOUNT \
  --dry-run
```

The wrapper defaults to `--partition hpcnirc`.

## 5) BIDS compliance gate (pilot A2002/A2003)

Use this checklist before enabling strict fMRIPrep validation:

1. Convert/normalize in place for pilot subjects:

```bash
mous-pipeline bids-convert --config configs/palmetto_hpcnirc_fmri.yaml --subject A2002
mous-pipeline bids-convert --config configs/palmetto_hpcnirc_fmri.yaml --subject A2003
python scripts/normalize_channels_tsv.py /scratch/jonathanwade/mous_data
```

2. Run repo validator:

```bash
mous-pipeline bids-validate --root /scratch/jonathanwade/mous_data --subject A2002 --verbose
mous-pipeline bids-validate --root /scratch/jonathanwade/mous_data --subject A2003 --verbose
```

3. Optional strict Node validator (inside an environment where `bids-validator` exists):

```bash
bids-validator /scratch/jonathanwade/mous_data
```

4. Keep compliance mode enabled:
   - `fmri.skip_bids_validation: false` in `configs/palmetto_hpcnirc_fmri.yaml`.
   - Only use `true` as an emergency fallback.

Pilot completion criteria before scaling:

- `bids-convert` succeeds for both `A2002` and `A2003`.
- `mous-pipeline bids-validate` reports no hard errors for both pilot subjects.
- `scripts/palmetto_submit.sh --subjects A2002,A2003 --dry-run` emits expected sbatch commands.
- One real `A2002` run completes with fMRIPrep launched without `--skip_bids_validation` in command output/logs.

## 6) Submit on `hpcnirc`

```bash
scripts/palmetto_submit.sh \
  --config configs/palmetto_hpcnirc_fmri.yaml \
  --subjects A2002,A2003 \
  --fetch-missing \
  --account YOUR_ACCOUNT \
  --time 08:00:00 \
  --mem 32G \
  --cpus-per-task 8
```

## 7) Logs and monitoring

- Driver logs: `<derivatives_root>/slurm/mous_driver_%j.out` and `.err`
- fMRIPrep array logs: `<derivatives_root>/slurm/fmriprep_%A_%a.out`
- Submission logs: `<derivatives_root>/slurm/fmriprep_submit_*.log`
- Queue status: `squeue -u $USER`

### Why can `mous_driver` finish before fMRIPrep?

`mous_driver` is an orchestrator job. It submits fMRI preprocessing as detached
`mous_fmriprep` array jobs and then continues MEG subject/group work. Because
those are separate SLURM jobs, the driver can complete while fMRI jobs are
still running.

To include m5 after recon-all is ready:

```bash
scripts/palmetto_submit.sh \
  --config configs/palmetto_hpcnirc_fmri.yaml \
  --subjects A2002,A2003 \
  --account YOUR_ACCOUNT \
  --include-m5 \
  --dry-run
```

## Troubleshooting

- `fmriprep container not found`: check `fmri.fmriprep_container` and file permissions.
- `No container runtime found`: load module or set `fmri.container_runtime` (`apptainer` or `singularity`).
- `recon-all not found`: load `MOUS_FREESURFER_MODULE` or set `MOUS_FREESURFER_CONTAINER`.
- FreeSurfer errors: verify `fmri.fs_license_file` or `MOUS_FREESURFER_LICENSE` exists and is readable.
- m5 still skipped: verify `source.subjects_dir` points to completed recon-all outputs and use `--include-m5`.
- `repocli` fetch failures: run `repocli config` once using `https://webdav.data.ru.nl`.

