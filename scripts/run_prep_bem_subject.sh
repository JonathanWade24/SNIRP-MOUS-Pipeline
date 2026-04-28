#!/usr/bin/env bash
set -euo pipefail

usage() {
  cat <<'EOF'
Usage:
  run_prep_bem_subject.sh --subjects-file <path> --subjects-dir <path>

Environment:
  SLURM_ARRAY_TASK_ID       0-based index into subjects-file lines.
  MOUS_FREESURFER_MODULE    Optional module to load before BEM prep.
  MOUS_FREESURFER_CONTAINER Optional apptainer/singularity image that has MNE.
  MOUS_VENV_PATH            Optional venv to activate before running mne.
EOF
}

SUBJECTS_FILE=""
SUBJECTS_DIR=""

while [[ $# -gt 0 ]]; do
  case "$1" in
    --subjects-file) SUBJECTS_FILE="${2:-}"; shift 2 ;;
    --subjects-dir) SUBJECTS_DIR="${2:-}"; shift 2 ;;
    -h|--help) usage; exit 0 ;;
    *) echo "Unknown argument: $1" >&2; usage >&2; exit 2 ;;
  esac
done

if [[ -z "$SUBJECTS_FILE" || -z "$SUBJECTS_DIR" ]]; then
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

if [[ -n "${MOUS_FREESURFER_MODULE:-}" ]] && command -v module >/dev/null 2>&1; then
  if ! module load "$MOUS_FREESURFER_MODULE" >/dev/null 2>&1; then
    module load neurocommand >/dev/null 2>&1 || true
    module load "$MOUS_FREESURFER_MODULE"
  fi
fi

if [[ -n "${MOUS_VENV_PATH:-}" ]]; then
  VENV_ACTIVATE="$(python - <<'PY' "$MOUS_VENV_PATH"
from pathlib import Path
import sys
print((Path(sys.argv[1]).expanduser() / "bin" / "activate").as_posix())
PY
)"
  if [[ -f "$VENV_ACTIVATE" ]]; then
    # shellcheck disable=SC1090
    source "$VENV_ACTIVATE"
  fi
fi

LINE_NO=$((SLURM_ARRAY_TASK_ID + 1))
SUBJECT="$(sed -n "${LINE_NO}p" "$SUBJECTS_FILE" | tr -d '[:space:]')"
if [[ -z "$SUBJECT" ]]; then
  echo "No subject resolved for SLURM_ARRAY_TASK_ID=$SLURM_ARRAY_TASK_ID" >&2
  exit 1
fi
SUBJECT="sub-${SUBJECT#sub-}"

INNER="$SUBJECTS_DIR/$SUBJECT/bem/inner_skull.surf"
OUTER_SKULL="$SUBJECTS_DIR/$SUBJECT/bem/outer_skull.surf"
OUTER_SKIN="$SUBJECTS_DIR/$SUBJECT/bem/outer_skin.surf"

if [[ -f "$INNER" && -f "$OUTER_SKULL" && -f "$OUTER_SKIN" ]]; then
  echo "[bem] skip subject=$SUBJECT reason=already_present inner_skull.surf/outer_skull.surf/outer_skin.surf"
  exit 0
fi

echo "[bem] host=$(hostname) job_id=${SLURM_JOB_ID:-na} task_id=${SLURM_ARRAY_TASK_ID:-na}"
echo "[bem] subject=$SUBJECT subjects_dir=$SUBJECTS_DIR"

if [[ -n "${MOUS_FREESURFER_CONTAINER:-}" ]]; then
  APPTAINER_BIN="$(command -v apptainer || command -v singularity || true)"
  if [[ -z "$APPTAINER_BIN" ]]; then
    echo "apptainer/singularity not found for containerized BEM prep." >&2
    exit 1
  fi
  "$APPTAINER_BIN" exec \
    -B "$SUBJECTS_DIR:$SUBJECTS_DIR" \
    "${MOUS_FREESURFER_CONTAINER}" \
    mne watershed_bem --overwrite --subject "$SUBJECT" --subjects-dir "$SUBJECTS_DIR"
else
  if ! command -v mne >/dev/null 2>&1; then
    echo "mne CLI not found. Activate env with mne-python or set MOUS_FREESURFER_CONTAINER." >&2
    exit 1
  fi
  mne watershed_bem --overwrite --subject "$SUBJECT" --subjects-dir "$SUBJECTS_DIR"
fi

if [[ ! -f "$INNER" ]]; then
  echo "BEM prep completed but inner_skull.surf is still missing for $SUBJECT" >&2
  exit 1
fi
echo "[bem] done subject=$SUBJECT"
