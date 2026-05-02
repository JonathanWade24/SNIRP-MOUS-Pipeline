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

MOUS_CONDA_MODULE="${MOUS_CONDA_MODULE:-miniforge3/24.3.0-0}"
MOUS_CONDA_ENV_NAME="${MOUS_CONDA_ENV_NAME:-mous-palmetto}"

module load "$MOUS_CONDA_MODULE"
eval "$(conda shell.bash hook)"
conda activate "$MOUS_CONDA_ENV_NAME"

scripts/palmetto_submit.sh \
  --config configs/palmetto_hpcnirc_fmri.yaml \
  --subjects A2002 \
  --account rcd_project_jabsher_hpcnirc \
  --time 12:00:00 \
  --mem 256G \
  --cpus-per-task 8
