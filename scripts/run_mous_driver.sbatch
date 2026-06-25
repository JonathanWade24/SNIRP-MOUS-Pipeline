#!/bin/bash
#SBATCH -J mous_driver
#SBATCH -p hpcnirc
#SBATCH -A ${MOUS_ACCOUNT}
#SBATCH -t 12:00:00
#SBATCH --cpus-per-task=8
#SBATCH --mem=128G
#SBATCH -o ${MOUS_DERIV_ROOT}/slurm/mous_driver_%j.out
#SBATCH -e ${MOUS_DERIV_ROOT}/slurm/mous_driver_%j.err

set -euo pipefail
: "${MOUS_REPO:?Set MOUS_REPO to the MOUS checkout path}"
: "${MOUS_ACCOUNT:?Set MOUS_ACCOUNT to your Slurm allocation}"
MOUS_DERIV_ROOT="${MOUS_DERIV_ROOT:-${MOUS_DERIVATIVES_ROOT:-}}"
: "${MOUS_DERIV_ROOT:?Set MOUS_DERIV_ROOT or MOUS_DERIVATIVES_ROOT}"

cd "${MOUS_REPO}"
mkdir -p "${MOUS_DERIV_ROOT}/slurm"

# Opt-in sync: only runs when MOUS_SYNC_ON_START=1 is set in the job environment.
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

VENV="${MOUS_VENV_PATH:-${HOME}/.venvs/mous-palmetto}"
source "${VENV}/bin/activate"

scripts/palmetto_submit.sh \
  --config "${MOUS_CONFIG:-configs/palmetto_hpcnirc_fmri.yaml}" \
  --subjects "${MOUS_SUBJECTS:-A2002}" \
  --account "${MOUS_ACCOUNT}" \
  --time "${MOUS_TIME:-12:00:00}" \
  --mem "${MOUS_MEM:-128G}" \
  --cpus-per-task "${MOUS_CPUS_PER_TASK:-8}"
