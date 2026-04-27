#!/bin/bash
#SBATCH --job-name=mous_fs_recon
#SBATCH --output=logs/mous_fs_recon_%A_%a.out
#SBATCH --error=logs/mous_fs_recon_%A_%a.err
#SBATCH --array=0-12
#SBATCH --time=12:00:00
#SBATCH --mem=16G
#SBATCH --cpus-per-task=4
#SBATCH --mail-type=END,FAIL
#SBATCH --mail-user=jonathan.w202013@gmail.com

# ============================================================
# analysis_02_freesurfer_recon.sh
#
# Run FreeSurfer recon-all for each subject needed by m5 source
# reconstruction. Submit this before analysis_01_cohort_fetch_and_run.sh.
#
# Usage:
#   mkdir -p logs derivatives/freesurfer
#   sbatch scripts/analysis_02_freesurfer_recon.sh
#
# Dry-run or run one subject without SLURM:
#   SUBJECT=A2003 bash scripts/analysis_02_freesurfer_recon.sh
# ============================================================

set -euo pipefail

SUBJECTS=(
  A2002 A2003 A2004 A2005 A2006
  A2007 A2008 A2009 A2010 A2013
  A2014 A2015 A2027
)

if [[ -n "${SLURM_ARRAY_TASK_ID:-}" ]]; then
  SID="${SUBJECTS[$SLURM_ARRAY_TASK_ID]}"
elif [[ -n "${SUBJECT:-}" ]]; then
  SID="${SUBJECT}"
else
  echo "ERROR: set SUBJECT=<id> or submit via sbatch --array." >&2
  exit 1
fi

DATA_ROOT="${DATA_ROOT:-${HOME}/mous_data}"
SUBJECTS_DIR="${SUBJECTS_DIR:-derivatives/freesurfer}"
T1W="${DATA_ROOT}/sub-${SID}/anat/sub-${SID}_T1w.nii"

echo "[$(date -u +%Y-%m-%dT%H:%M:%SZ)] Starting recon-all for sub-${SID}"
echo "[config] DATA_ROOT=${DATA_ROOT}"
echo "[config] SUBJECTS_DIR=${SUBJECTS_DIR}"

if command -v module >/dev/null 2>&1; then
  module load freesurfer/7.4.1
fi

export FS_LICENSE="${FS_LICENSE:-/data/freesurfer/license.txt}"
if [[ ! -f "${FS_LICENSE}" ]]; then
  echo "ERROR: FreeSurfer license not found at FS_LICENSE=${FS_LICENSE}" >&2
  exit 1
fi

if [[ ! -f "${T1W}" ]]; then
  echo "ERROR: T1w image not found: ${T1W}" >&2
  exit 1
fi

mkdir -p "${SUBJECTS_DIR}"

recon-all \
  -s "sub-${SID}" \
  -i "${T1W}" \
  -sd "${SUBJECTS_DIR}" \
  -all \
  -parallel \
  -openmp "${SLURM_CPUS_PER_TASK:-4}"

for required in \
  "${SUBJECTS_DIR}/sub-${SID}/mri/brain.mgz" \
  "${SUBJECTS_DIR}/sub-${SID}/surf/lh.white" \
  "${SUBJECTS_DIR}/sub-${SID}/surf/rh.white"
do
  if [[ ! -f "${required}" ]]; then
    echo "ERROR: recon-all completed but expected output is missing: ${required}" >&2
    exit 1
  fi
done

echo "[$(date -u +%Y-%m-%dT%H:%M:%SZ)] Done: sub-${SID}"
