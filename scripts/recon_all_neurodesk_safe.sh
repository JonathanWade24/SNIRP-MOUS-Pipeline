#!/usr/bin/env bash
set -euo pipefail

usage() {
  cat <<'EOF'
Usage:
  scripts/recon_all_neurodesk_safe.sh --subject <A####|sub-A####> [options]

Options:
  --subject <id>           Required subject id.
  --data-root <path>       Root containing sub-*/anat/*_T1w.nii (default: /home/jovyan/mous_data).
  --subjects-dir <path>    FreeSurfer SUBJECTS_DIR output (default: derivatives/freesurfer).
  --openmp <n>             OpenMP threads for recon-all (default: 3).
  -h, --help               Show this help.

Notes:
  - Run from repo root.
  - Script always stages input into a no-space path under <subjects-dir>/_inputs.
EOF
}

SUBJECT=""
DATA_ROOT="${DATA_ROOT:-/home/jovyan/mous_data}"
SUBJECTS_DIR="${SUBJECTS_DIR:-derivatives/freesurfer}"
OPENMP="${OPENMP:-3}"

while [[ $# -gt 0 ]]; do
  case "$1" in
    --subject)
      SUBJECT="${2:-}"
      shift 2
      ;;
    --data-root)
      DATA_ROOT="${2:-}"
      shift 2
      ;;
    --subjects-dir)
      SUBJECTS_DIR="${2:-}"
      shift 2
      ;;
    --openmp)
      OPENMP="${2:-}"
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

if [[ -z "$SUBJECT" ]]; then
  echo "Missing required --subject" >&2
  usage >&2
  exit 2
fi

SUBJECT="sub-${SUBJECT#sub-}"
T1W="${DATA_ROOT}/${SUBJECT}/anat/${SUBJECT}_T1w.nii"

if [[ ! -f "${T1W}" ]]; then
  echo "ERROR: T1w image not found: ${T1W}" >&2
  exit 1
fi

if ! command -v recon-all >/dev/null 2>&1; then
  echo "ERROR: recon-all not found on PATH" >&2
  exit 1
fi

mkdir -p "${SUBJECTS_DIR}"
SAFE_INPUT_DIR="${SUBJECTS_DIR}/_inputs/${SUBJECT}/anat"
SAFE_T1W="${SAFE_INPUT_DIR}/${SUBJECT}_T1w.nii"
mkdir -p "${SAFE_INPUT_DIR}"
cp -f "${T1W}" "${SAFE_T1W}"

echo "[config] SUBJECT=${SUBJECT}"
echo "[config] DATA_ROOT=${DATA_ROOT}"
echo "[config] T1W=${T1W}"
echo "[config] SAFE_T1W=${SAFE_T1W}"
echo "[config] SUBJECTS_DIR=${SUBJECTS_DIR}"
echo "[config] OPENMP=${OPENMP}"

recon-all \
  -s "${SUBJECT}" \
  -i "${SAFE_T1W}" \
  -sd "${SUBJECTS_DIR}" \
  -all \
  -parallel \
  -openmp "${OPENMP}"

echo "Done: ${SUBJECT}"
