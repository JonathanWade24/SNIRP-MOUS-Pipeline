#!/bin/bash
#SBATCH --job-name=mous_cohort
#SBATCH --output=logs/mous_cohort_%A_%a.out
#SBATCH --error=logs/mous_cohort_%A_%a.err
#SBATCH --array=0-12
#SBATCH --time=06:00:00
#SBATCH --mem=16G
#SBATCH --cpus-per-task=4
#SBATCH --mail-type=END,FAIL
#SBATCH --mail-user=jonathan.w202013@gmail.com

# ============================================================
# analysis_01_cohort_fetch_and_run.sh
#
# Fetch + run the full MOUS pipeline (m1-m12, including m5 source
# reconstruction) for the configured cohort in a SLURM array job.
#
# Usage:
#   # 1. Make sure repocli is configured (one-time):
#   #      repocli config  (base URL: https://webdav.data.ru.nl)
#   #
#   # 2. Create log directory:
#   #      mkdir -p logs
#   #
#   # 3. Submit:
#   #      sbatch scripts/analysis_01_cohort_fetch_and_run.sh
#   #
#   # 4. Monitor:
#   #      squeue -u $USER
#   #      tail -f logs/mous_cohort_<JOBID>_<TASKID>.out
#   #
#   # To dry-run locally without SLURM (single subject, no fetch):
#   #      SUBJECT=A2003 bash scripts/analysis_01_cohort_fetch_and_run.sh
# ============================================================

set -euo pipefail

CONFIG="configs/cohort_15subjects_fmri.yaml"

SUBJECTS=(
  A2002 A2003 A2004 A2005 A2006
  A2007 A2008 A2009 A2010 A2013
  A2014 A2015 A2027
)

# When running under SLURM, pick subject from array index.
# When running manually, SUBJECT env var overrides.
if [[ -n "${SLURM_ARRAY_TASK_ID:-}" ]]; then
  SID="${SUBJECTS[$SLURM_ARRAY_TASK_ID]}"
elif [[ -n "${SUBJECT:-}" ]]; then
  SID="$SUBJECT"
else
  echo "ERROR: set SUBJECT=<id> or submit via sbatch --array." >&2
  exit 1
fi

DATA_ROOT="${HOME}/mous_data"

echo "[$(date -u +%Y-%m-%dT%H:%M:%SZ)] Starting subject: ${SID}"

# ── Step 1: Fetch from RDR if data not already present ──────────────────────
if [[ ! -d "${DATA_ROOT}/sub-${SID}" ]]; then
  echo "[fetch] sub-${SID} not found locally — fetching from RDR..."
  mous-pipeline fetch-rdr \
    --config "${CONFIG}" \
    --subject "${SID}" \
    --execute
else
  echo "[fetch] sub-${SID} already present, skipping download."
fi

# ── Step 2: Run full pipeline, including m5 source reconstruction ───────────
echo "[run] Launching pipeline for sub-${SID}..."
mous-pipeline run \
  --config "${CONFIG}" \
  --subject "${SID}"

# ── Step 3: Verify run completed cleanly ────────────────────────────────────
echo "[verify] Checking run manifest..."
mous-pipeline verify-run \
  --config "${CONFIG}" \
  --subject "${SID}" \
  --require-m5 \
  --strict-mode

echo "[$(date -u +%Y-%m-%dT%H:%M:%SZ)] Done: ${SID}"
