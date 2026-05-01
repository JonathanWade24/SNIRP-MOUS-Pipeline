# Palmetto Workspace Map

This guide is for a Git-first workflow where the laptop is the main editing
environment and Palmetto is the compute target. Use Git for source changes,
then copy back only the reports, logs, manifests, and packaged outputs you
actually need locally.

## Daily Git Loop

On the laptop:

```bash
git switch -c <branch>
# edit, test, commit
git push -u origin <branch>
```

On Palmetto:

```bash
cd /scratch/jonathanwade/MOUS
git status --short --branch
git fetch origin
git switch <branch>
git pull --ff-only
source "${MOUS_VENV_PATH:-$HOME/.venvs/mous-palmetto}/bin/activate"
mous-pipeline run --config configs/palmetto_hpcnirc_fmri.yaml --subject A2002 --dry-run
```

Before leaving either machine:

```bash
git status --short --branch
```

Commit source/docs changes that should persist. Stash or discard experiments
explicitly so the laptop and Palmetto do not drift silently.

## Directory Map

| Path | Role | Git policy |
| --- | --- | --- |
| `/scratch/jonathanwade/MOUS` | Git checkout and command root | Track source, configs, scripts, and docs |
| `/scratch/jonathanwade/mous_data` | Raw BIDS-like subject data | Do not commit |
| `/scratch/jonathanwade/mous_derivatives` | Main pipeline outputs and Slurm logs | Do not commit |
| `/scratch/jonathanwade/mous_derivatives/freesurfer` | FreeSurfer recon-all and BEM outputs | Do not commit |
| `/scratch/jonathanwade/mous_derivatives/fmriprep` | fMRIPrep outputs | Do not commit |
| `/scratch/jonathanwade/containers` | Apptainer/Singularity images | Do not commit |
| `/scratch/jonathanwade/licenses` | License files such as FreeSurfer | Do not commit |
| `/scratch/jonathanwade/templateflow` | TemplateFlow cache/bind target | Do not commit |

The Palmetto YAML configs currently point at the `/scratch/jonathanwade/...`
paths above. If those paths change, update the relevant fields in
`configs/palmetto_hpcnirc_fmri.yaml` or the cohort config:

- `data_root`
- `derivatives_root`
- `source.subjects_dir`
- `fmri.fmriprep_container`
- `fmri.fmriprep_output`
- `fmri.fs_license_file`
- `fmri.container_binds`

## Repo Root Triage

These are source or source-adjacent and should usually be edited through Git:

- `src/mous_pipeline/`
- `tests/`
- `configs/`
- `scripts/`
- `docs/`
- `reports/`
- `README.md`, `pyproject.toml`, `Makefile`

These are generated or machine-local and should usually only be inspected or
copied out:

- `derivatives/`
- `run_results_*`
- `*.zip`
- `*_report.html`
- `.pytest_cache/`
- `.venv/`, `.venv-palmetto/`
- `.DS_Store`, editor caches

The root `.gitignore` already excludes these generated outputs.

## Dotfiles Setup

Keep reusable shell setup in a personal dotfiles repo, not in this project and
not only in ad hoc `~/.bashrc` edits. A minimal Palmetto shell file can look
like this. A tracked copy lives at `docs/dotfiles/mous-palmetto.sh`:

```bash
# ~/.config/shell/mous-palmetto.sh
export MOUS_REPO="/scratch/jonathanwade/MOUS"
export MOUS_VENV_PATH="$HOME/.venvs/mous-palmetto"
export MOUS_CONTAINER_DIR="/scratch/jonathanwade/containers"
export MPLCONFIGDIR="${TMPDIR:-/tmp}/mous-matplotlib-${USER:-user}"
mkdir -p "$MPLCONFIGDIR" 2>/dev/null || true

cdmous() { cd "$MOUS_REPO" || return; }
mousenv() { . "$MOUS_VENV_PATH/bin/activate"; }
mousq() { squeue -u "$USER" "$@"; }
```

Then keep `~/.bashrc` small:

```bash
if [ -f "$HOME/.config/shell/mous-palmetto.sh" ]; then
  . "$HOME/.config/shell/mous-palmetto.sh"
fi
```

Do not commit SSH keys, RDR credentials, tokens, `repocli` auth state, or
FreeSurfer license files.

## Pull Selected Results To Laptop

Use Git for source and `rsync` only for selected outputs. The examples assume
your laptop SSH config has a host alias named `palmetto`.

Reports and run packages:

```bash
mkdir -p ~/MOUS/palmetto_results
rsync -av --progress \
  'palmetto:/scratch/jonathanwade/MOUS/run_results_*.zip' \
  ~/MOUS/palmetto_results/
```

Slurm logs:

```bash
mkdir -p ~/MOUS/palmetto_results/slurm
rsync -av --progress \
  'palmetto:/scratch/jonathanwade/mous_derivatives/slurm/' \
  ~/MOUS/palmetto_results/slurm/
```

Subject reports only:

```bash
mkdir -p ~/MOUS/palmetto_results/reports
rsync -av --progress \
  --include='*/' \
  --include='*_report.html' \
  --include='*_quarto_report.html' \
  --include='group_aim2_summary.html' \
  --exclude='*' \
  'palmetto:/scratch/jonathanwade/mous_derivatives/' \
  ~/MOUS/palmetto_results/reports/
```

Avoid syncing raw data or full derivative trees unless you need them for a
specific local analysis.

## Useful Palmetto Commands

```bash
cd /scratch/jonathanwade/MOUS
source "${MOUS_VENV_PATH:-$HOME/.venvs/mous-palmetto}/bin/activate"

mous-pipeline run --config configs/palmetto_hpcnirc_fmri.yaml --subject A2002 --dry-run
scripts/palmetto_submit.sh --config configs/palmetto_hpcnirc_fmri.yaml --subjects A2002,A2003 --account YOUR_ACCOUNT --dry-run
mous-pipeline watch --config configs/palmetto_hpcnirc_fmri.yaml --subject A2002 --verbose
mous-pipeline verify-run --config configs/palmetto_hpcnirc_fmri.yaml --subject A2002 --strict-mode
squeue -u "$USER"
```
