#!/bin/bash

# ============================================================
# analysis_00_hpc_setup.sh
#
# Prepare the HPC working tree for the M5 full-cohort workflow.
# This script creates expected directories, checks local prerequisites,
# and can optionally submit the FreeSurfer and cohort SLURM jobs.
#
# Usage:
#   bash scripts/analysis_00_hpc_setup.sh --check-data
#   bash scripts/analysis_00_hpc_setup.sh --check-freesurfer
#   bash scripts/analysis_00_hpc_setup.sh --submit-recon
#   bash scripts/analysis_00_hpc_setup.sh --submit-cohort
# ============================================================

set -euo pipefail

CONFIG="${CONFIG:-configs/cohort_15subjects_fmri.yaml}"
DATA_ROOT="${DATA_ROOT:-${HOME}/mous_data}"
SUBJECTS_DIR="${SUBJECTS_DIR:-derivatives/freesurfer}"
FS_LICENSE="${FS_LICENSE:-/data/freesurfer/license.txt}"

CHECK_DATA=false
CHECK_FREESURFER=false
SUBMIT_RECON=false
SUBMIT_COHORT=false
DRY_RUN=false

SUBJECTS=(
  A2002 A2003 A2004 A2005 A2006
  A2007 A2008 A2009 A2010 A2013
  A2014 A2015 A2027
)

usage() {
  sed -n '3,18p' "$0"
}

while [[ $# -gt 0 ]]; do
  case "$1" in
    --check-data)
      CHECK_DATA=true
      ;;
    --check-freesurfer)
      CHECK_FREESURFER=true
      ;;
    --submit-recon)
      SUBMIT_RECON=true
      ;;
    --submit-cohort)
      SUBMIT_COHORT=true
      ;;
    --dry-run)
      DRY_RUN=true
      ;;
    -h|--help)
      usage
      exit 0
      ;;
    *)
      echo "ERROR: unknown argument: $1" >&2
      usage >&2
      exit 1
      ;;
  esac
  shift
done

run_cmd() {
  if [[ "${DRY_RUN}" == true ]]; then
    printf '[dry-run]'
    printf ' %q' "$@"
    printf '\n'
  else
    "$@"
  fi
}

warn() {
  echo "WARNING: $*" >&2
}

echo "[setup] Preparing MOUS M5 HPC workflow"
echo "[setup] CONFIG=${CONFIG}"
echo "[setup] DATA_ROOT=${DATA_ROOT}"
echo "[setup] SUBJECTS_DIR=${SUBJECTS_DIR}"
echo "[setup] FS_LICENSE=${FS_LICENSE}"

run_cmd mkdir -p logs "${SUBJECTS_DIR}" derivatives/mous_pipeline derivatives/fmriprep derivatives/coreg
run_cmd chmod +x scripts/analysis_01_cohort_fetch_and_run.sh scripts/analysis_02_freesurfer_recon.sh

if [[ ! -f "${CONFIG}" ]]; then
  echo "ERROR: config not found: ${CONFIG}" >&2
  exit 1
fi

if [[ ! -f "${FS_LICENSE}" ]]; then
  warn "FreeSurfer license not found at ${FS_LICENSE}; set FS_LICENSE or place the license before submitting recon-all."
fi

if ! command -v sbatch >/dev/null 2>&1; then
  warn "sbatch is not on PATH; run submission steps from a SLURM login node."
fi

if command -v module >/dev/null 2>&1; then
  if ! module avail freesurfer/7.4.1 >/dev/null 2>&1; then
    warn "module system is available, but freesurfer/7.4.1 was not found by 'module avail'."
  fi
else
  warn "environment modules are not available in this shell; batch scripts will try 'module load freesurfer/7.4.1' on compute nodes."
fi

if ! command -v mous-pipeline >/dev/null 2>&1; then
  warn "mous-pipeline is not on PATH; activate the project environment or run 'pip install -e .' before cohort submission."
fi

if command -v python >/dev/null 2>&1; then
  python - "${CONFIG}" "${SUBJECTS_DIR}" <<'PY' || warn "Could not validate source.subjects_dir from config."
import sys
from pathlib import Path

try:
    import yaml
except Exception as exc:
    raise SystemExit(f"PyYAML unavailable: {exc}")

config_path = Path(sys.argv[1])
expected = sys.argv[2]
raw = yaml.safe_load(config_path.read_text()) or {}
actual = str((raw.get("source") or {}).get("subjects_dir") or "")
if actual != expected:
    raise SystemExit(f"source.subjects_dir is {actual!r}, expected {expected!r}")
print(f"[setup] config source.subjects_dir OK: {actual}")
PY
else
  warn "python is not on PATH; skipping config validation."
fi

if [[ "${CHECK_DATA}" == true ]]; then
  missing=0
  for sid in "${SUBJECTS[@]}"; do
    t1w="${DATA_ROOT}/sub-${sid}/anat/sub-${sid}_T1w.nii"
    if [[ ! -f "${t1w}" ]]; then
      echo "MISSING T1w: ${t1w}" >&2
      missing=$((missing + 1))
    fi
  done
  if [[ "${missing}" -gt 0 ]]; then
    echo "ERROR: ${missing} required T1w image(s) are missing." >&2
    exit 1
  fi
  echo "[setup] All subject T1w images are present."
fi

if [[ "${CHECK_FREESURFER}" == true ]]; then
  missing=0
  for sid in "${SUBJECTS[@]}"; do
    for required in \
      "${SUBJECTS_DIR}/sub-${sid}/mri/brain.mgz" \
      "${SUBJECTS_DIR}/sub-${sid}/surf/lh.white" \
      "${SUBJECTS_DIR}/sub-${sid}/surf/rh.white"
    do
      if [[ ! -f "${required}" ]]; then
        echo "MISSING FreeSurfer output: ${required}" >&2
        missing=$((missing + 1))
      fi
    done
  done
  if [[ "${missing}" -gt 0 ]]; then
    echo "ERROR: ${missing} required FreeSurfer output file(s) are missing." >&2
    exit 1
  fi
  echo "[setup] All required FreeSurfer outputs are present."
fi

if [[ "${SUBMIT_RECON}" == true ]]; then
  run_cmd sbatch scripts/analysis_02_freesurfer_recon.sh
fi

if [[ "${SUBMIT_COHORT}" == true ]]; then
  run_cmd sbatch scripts/analysis_01_cohort_fetch_and_run.sh
fi

cat <<EOF

[setup] Next steps:
  1. Check raw T1w inputs:      bash scripts/analysis_00_hpc_setup.sh --check-data
  2. Submit FreeSurfer:         sbatch scripts/analysis_02_freesurfer_recon.sh
  3. Verify FreeSurfer outputs: bash scripts/analysis_00_hpc_setup.sh --check-freesurfer
  4. Submit full M5 cohort:     sbatch scripts/analysis_01_cohort_fetch_and_run.sh
  5. Run group inference:       mous-pipeline group --derivatives-root derivatives/mous_pipeline

EOF
