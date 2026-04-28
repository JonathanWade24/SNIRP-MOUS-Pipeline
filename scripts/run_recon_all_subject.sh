#!/usr/bin/env bash
set -euo pipefail

usage() {
  cat <<'EOF'
Usage:
  run_recon_all_subject.sh --config <config.yaml> --subjects-file <path> --subjects-dir <path>

Environment:
  SLURM_ARRAY_TASK_ID      0-based index into subjects-file lines.
  MOUS_FREESURFER_MODULE   Optional module to load before running recon-all.
  MOUS_FREESURFER_CONTAINER Optional apptainer/singularity image for recon-all.
  MOUS_FREESURFER_LICENSE  Optional FreeSurfer license path.
EOF
}

CONFIG=""
SUBJECTS_FILE=""
SUBJECTS_DIR=""

while [[ $# -gt 0 ]]; do
  case "$1" in
    --config)
      CONFIG="${2:-}"
      shift 2
      ;;
    --subjects-file)
      SUBJECTS_FILE="${2:-}"
      shift 2
      ;;
    --subjects-dir)
      SUBJECTS_DIR="${2:-}"
      shift 2
      ;;
    -h|--help)
      usage
      exit 0
      ;;
    *)
      echo "Unknown argument: $1" >&2
      usage >&2
      exit 2
      ;;
  esac
done

if [[ -z "$CONFIG" || -z "$SUBJECTS_FILE" || -z "$SUBJECTS_DIR" ]]; then
  echo "Missing required args." >&2
  usage >&2
  exit 2
fi
if [[ ! -f "$SUBJECTS_FILE" ]]; then
  echo "subjects file not found: $SUBJECTS_FILE" >&2
  exit 1
fi
if [[ -z "${SLURM_ARRAY_TASK_ID:-}" ]]; then
  echo "SLURM_ARRAY_TASK_ID is required for array execution." >&2
  exit 1
fi

if [[ -n "${MOUS_FREESURFER_MODULE:-}" ]]; then
  # Some Palmetto environments gate FreeSurfer behind a parent module
  # (e.g. `ml neurocommand` before `ml freesurfer/8.2.0`).
  if command -v module >/dev/null 2>&1; then
    # Try direct load first.
    if ! module load "$MOUS_FREESURFER_MODULE" >/dev/null 2>&1; then
      # Retry with neurocommand pre-load when present.
      module load neurocommand >/dev/null 2>&1 || true
      module load "$MOUS_FREESURFER_MODULE"
    fi
  fi
fi
if [[ -n "${MOUS_FREESURFER_LICENSE:-}" ]]; then
  export FS_LICENSE="$MOUS_FREESURFER_LICENSE"
fi

LINE_NO=$((SLURM_ARRAY_TASK_ID + 1))
SUBJECT="$(sed -n "${LINE_NO}p" "$SUBJECTS_FILE" | tr -d '[:space:]')"
if [[ -z "$SUBJECT" ]]; then
  echo "No subject resolved for SLURM_ARRAY_TASK_ID=$SLURM_ARRAY_TASK_ID" >&2
  exit 1
fi
SUBJECT="sub-${SUBJECT#sub-}"

T1_PATH="$(python - <<'PY' "$CONFIG" "$SUBJECT"
from pathlib import Path
import sys
from mous_pipeline.config import load_config

cfg = load_config(Path(sys.argv[1]).expanduser().resolve())
subject = sys.argv[2]
print((cfg.data_root.expanduser().resolve() / subject / "anat" / f"{subject}_T1w.nii").as_posix())
PY
)"

if [[ ! -f "$T1_PATH" ]]; then
  echo "T1 file not found for $SUBJECT: $T1_PATH" >&2
  exit 1
fi

mkdir -p "$SUBJECTS_DIR"
SAFE_INPUT_ROOT="${MOUS_FREESURFER_SAFE_INPUT_ROOT:-$SUBJECTS_DIR/_inputs}"
SAFE_INPUT_DIR="${SAFE_INPUT_ROOT}/${SUBJECT}/anat"
SAFE_T1_PATH="${SAFE_INPUT_DIR}/${SUBJECT}_T1w.nii"
mkdir -p "$SAFE_INPUT_DIR"
cp -f "$T1_PATH" "$SAFE_T1_PATH"
echo "[recon-all] host=$(hostname) job_id=${SLURM_JOB_ID:-na} task_id=${SLURM_ARRAY_TASK_ID:-na}"
echo "[recon-all] subject=$SUBJECT t1=$T1_PATH staged_t1=$SAFE_T1_PATH subjects_dir=$SUBJECTS_DIR"
OPENMP_THREADS="${MOUS_FREESURFER_OPENMP:-${SLURM_CPUS_PER_TASK:-1}}"
export OMP_NUM_THREADS="$OPENMP_THREADS"
export ITK_GLOBAL_DEFAULT_NUMBER_OF_THREADS="$OPENMP_THREADS"
echo "[recon-all] openmp_threads=$OPENMP_THREADS omp_num_threads=$OMP_NUM_THREADS"

if [[ -n "${MOUS_FREESURFER_CONTAINER:-}" ]]; then
  APPTAINER_BIN="$(command -v apptainer || command -v singularity || true)"
  if [[ -z "$APPTAINER_BIN" ]]; then
    echo "apptainer/singularity not found for containerized recon-all." >&2
    exit 1
  fi
  if [[ -d "$SUBJECTS_DIR/$SUBJECT" ]]; then
    echo "[recon-all] existing subject directory detected; resuming without -i"
    "$APPTAINER_BIN" exec \
      -B "$SUBJECTS_DIR:$SUBJECTS_DIR" \
      -B "$SAFE_INPUT_DIR:$SAFE_INPUT_DIR" \
      "${MOUS_FREESURFER_CONTAINER}" \
      recon-all -s "$SUBJECT" -sd "$SUBJECTS_DIR" -all -openmp "$OPENMP_THREADS"
  else
    "$APPTAINER_BIN" exec \
      -B "$SUBJECTS_DIR:$SUBJECTS_DIR" \
      -B "$SAFE_INPUT_DIR:$SAFE_INPUT_DIR" \
      "${MOUS_FREESURFER_CONTAINER}" \
      recon-all -s "$SUBJECT" -i "$SAFE_T1_PATH" -sd "$SUBJECTS_DIR" -all -openmp "$OPENMP_THREADS"
  fi
else
  if ! command -v recon-all >/dev/null 2>&1; then
    echo "recon-all not found. On Palmetto this may require: module load neurocommand && module load freesurfer/<version>." >&2
    echo "Set MOUS_FREESURFER_MODULE to your concrete module (e.g. freesurfer/8.2.0), or set MOUS_FREESURFER_CONTAINER." >&2
    exit 1
  fi
  if [[ -d "$SUBJECTS_DIR/$SUBJECT" ]]; then
    echo "[recon-all] existing subject directory detected; resuming without -i"
    recon-all -s "$SUBJECT" -sd "$SUBJECTS_DIR" -all -openmp "$OPENMP_THREADS"
  else
    recon-all -s "$SUBJECT" -i "$SAFE_T1_PATH" -sd "$SUBJECTS_DIR" -all -openmp "$OPENMP_THREADS"
  fi
fi
