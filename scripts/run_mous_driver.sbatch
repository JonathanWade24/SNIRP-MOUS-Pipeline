#!/bin/bash
#SBATCH -J mous_driver
#SBATCH -p hpcnirc
#SBATCH -A rcd_project_jabsher_hpcnirc
#SBATCH -t 12:00:00
#SBATCH --cpus-per-task=8
#SBATCH --mem=256G
#SBATCH -o /scratch/jonathanwade/mous_derivatives/slurm/mous_driver_%j.out
#SBATCH -e /scratch/jonathanwade/mous_derivatives/slurm/mous_driver_%j.err

set -euo pipefail
cd /scratch/jonathanwade/MOUS

echo "[sync] Fetching origin/HPC..."
git fetch origin
git reset --hard origin/HPC
echo "[sync] Running at: $(git log -1 --oneline)"

source "$HOME/.venvs/mous-palmetto/bin/activate"

scripts/palmetto_submit.sh \
  --config configs/palmetto_hpcnirc_fmri.yaml \
  --subjects A2002 \
  --account rcd_project_jabsher_hpcnirc \
  --time 12:00:00 \
  --mem 256G \
  --cpus-per-task 8
