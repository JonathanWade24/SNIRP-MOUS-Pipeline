#!/bin/bash
#SBATCH -J mous_driver
#SBATCH -p hpcnirc
#SBATCH -A rcd_project_jabsher_hpcnirc
#SBATCH -t 12:00:00
#SBATCH --cpus-per-task=8
#SBATCH --mem=128G
#SBATCH -o /scratch/jonathanwade/mous_derivatives/slurm/mous_driver_%j.out
#SBATCH -e /scratch/jonathanwade/mous_derivatives/slurm/mous_driver_%j.err

set -euo pipefail
cd /scratch/jonathanwade/MOUS

# Opt-in sync: only runs when MOUS_SYNC_ON_START=1 is set in the job environment.
# Requires a clean working tree to prevent silent data loss.
# Usage: add '#SBATCH --export=ALL,MOUS_SYNC_ON_START=1' or set in your submission env.
if [[ "${MOUS_SYNC_ON_START:-0}" == "1" ]]; then
  echo "[sync] MOUS_SYNC_ON_START=1: syncing from origin/HPC..."
  _dirty="$(git status --porcelain 2>/dev/null)"
  if [[ -n "$_dirty" ]]; then
    echo "[sync] ERROR: working tree is dirty; refusing to reset --hard." >&2
    echo "[sync] Commit or stash changes, or unset MOUS_SYNC_ON_START." >&2
    git status --short >&2
    exit 1
  fi
  git fetch origin
  git reset --hard origin/HPC
  echo "[sync] Now at: $(git log -1 --oneline)"
fi

source "$HOME/.venvs/mous-palmetto/bin/activate"

scripts/palmetto_submit.sh \
  --config configs/palmetto_hpcnirc_fmri.yaml \
  --subjects A2002 \
  --account rcd_project_jabsher_hpcnirc \
  --time 12:00:00 \
  --mem 128G \
  --cpus-per-task 8
