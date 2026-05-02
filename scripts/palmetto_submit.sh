#!/usr/bin/env bash
set -euo pipefail

usage() {
  cat <<'EOF'
Palmetto submission wrapper for Aim priority orchestration.

Usage:
  scripts/palmetto_submit.sh --config configs/palmetto_hpcnirc_fmri.yaml [options]

Options:
  --subjects A2002,A2003
  --fetch-missing
  --dry-run
  --include-m5
  --skip-m5
  --meg-skip <csv>
  --skip-fmriprep-submit
  --skip-fmri-stages-submit
  --skip-group
  --skip-aim1-audit
  --partition <name>       (default: hpcnirc)
  --account <account>
  --qos <qos>
  --time <HH:MM:SS>
  --mem <value>
  --cpus-per-task <n>
  --freesurfer-module <name>
  --freesurfer-container <sif>
  --freesurfer-license <path>
EOF
}

CONFIG=""
SUBJECTS=""
FETCH_MISSING=0
DRY_RUN=0
INCLUDE_M5=0
SKIP_M5=0
MEG_SKIP_OVERRIDE=""
SKIP_FMRIPREP_SUBMIT=0
SKIP_FMRI_STAGES_SUBMIT=0
SKIP_GROUP=0
SKIP_AIM1_AUDIT=0
PARTITION="${MOUS_PARTITION:-hpcnirc}"
ACCOUNT="${MOUS_ACCOUNT:-}"
QOS="${MOUS_QOS:-}"
TIME_LIMIT="${MOUS_TIME:-}"
MEMORY="${MOUS_MEM:-}"
CPUS_PER_TASK="${MOUS_CPUS_PER_TASK:-}"
FS_MODULE="${MOUS_FREESURFER_MODULE:-}"
FS_CONTAINER="${MOUS_FREESURFER_CONTAINER:-}"
FS_LICENSE="${MOUS_FREESURFER_LICENSE:-}"

while [[ $# -gt 0 ]]; do
  case "$1" in
    --config)
      CONFIG="${2:-}"
      shift 2
      ;;
    --subjects)
      SUBJECTS="${2:-}"
      shift 2
      ;;
    --fetch-missing)
      FETCH_MISSING=1
      shift
      ;;
    --dry-run)
      DRY_RUN=1
      shift
      ;;
    --include-m5)
      INCLUDE_M5=1
      shift
      ;;
    --skip-m5)
      SKIP_M5=1
      shift
      ;;
    --meg-skip)
      MEG_SKIP_OVERRIDE="${2:-}"
      shift 2
      ;;
    --skip-fmriprep-submit)
      SKIP_FMRIPREP_SUBMIT=1
      shift
      ;;
    --skip-fmri-stages-submit)
      SKIP_FMRI_STAGES_SUBMIT=1
      shift
      ;;
    --skip-group)
      SKIP_GROUP=1
      shift
      ;;
    --skip-aim1-audit)
      SKIP_AIM1_AUDIT=1
      shift
      ;;
    --partition)
      PARTITION="${2:-}"
      shift 2
      ;;
    --account)
      ACCOUNT="${2:-}"
      shift 2
      ;;
    --qos)
      QOS="${2:-}"
      shift 2
      ;;
    --time)
      TIME_LIMIT="${2:-}"
      shift 2
      ;;
    --mem)
      MEMORY="${2:-}"
      shift 2
      ;;
    --cpus-per-task)
      CPUS_PER_TASK="${2:-}"
      shift 2
      ;;
    --freesurfer-module)
      FS_MODULE="${2:-}"
      shift 2
      ;;
    --freesurfer-container)
      FS_CONTAINER="${2:-}"
      shift 2
      ;;
    --freesurfer-license)
      FS_LICENSE="${2:-}"
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

if [[ -z "$CONFIG" ]]; then
  echo "--config is required" >&2
  usage >&2
  exit 2
fi

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
if [[ -n "$FS_MODULE" ]]; then
  export MOUS_FREESURFER_MODULE="$FS_MODULE"
fi
if [[ -n "$FS_CONTAINER" ]]; then
  export MOUS_FREESURFER_CONTAINER="$FS_CONTAINER"
fi
if [[ -n "$FS_LICENSE" ]]; then
  export MOUS_FREESURFER_LICENSE="$FS_LICENSE"
fi
CMD=("$REPO_ROOT/scripts/run_aims_priority.sh" --config "$CONFIG" --partition "$PARTITION")

if [[ -n "$SUBJECTS" ]]; then
  CMD+=(--subjects "$SUBJECTS")
fi
if [[ "$FETCH_MISSING" -eq 1 ]]; then
  CMD+=(--fetch-missing)
fi
if [[ "$DRY_RUN" -eq 1 ]]; then
  CMD+=(--dry-run)
fi
if [[ "$INCLUDE_M5" -eq 1 ]]; then
  CMD+=(--include-m5)
fi
if [[ "$SKIP_M5" -eq 1 ]]; then
  CMD+=(--skip-m5)
fi
if [[ -n "$MEG_SKIP_OVERRIDE" ]]; then
  CMD+=(--meg-skip "$MEG_SKIP_OVERRIDE")
fi
if [[ "$SKIP_FMRIPREP_SUBMIT" -eq 1 ]]; then
  CMD+=(--skip-fmriprep-submit)
fi
if [[ "$SKIP_FMRI_STAGES_SUBMIT" -eq 1 ]]; then
  CMD+=(--skip-fmri-stages-submit)
fi
if [[ "$SKIP_GROUP" -eq 1 ]]; then
  CMD+=(--skip-group)
fi
if [[ "$SKIP_AIM1_AUDIT" -eq 1 ]]; then
  CMD+=(--skip-aim1-audit)
fi
if [[ -n "$ACCOUNT" ]]; then
  CMD+=(--account "$ACCOUNT")
fi
if [[ -n "$QOS" ]]; then
  CMD+=(--qos "$QOS")
fi
if [[ -n "$TIME_LIMIT" ]]; then
  CMD+=(--time "$TIME_LIMIT")
fi
if [[ -n "$MEMORY" ]]; then
  CMD+=(--mem "$MEMORY")
fi
if [[ -n "$CPUS_PER_TASK" ]]; then
  CMD+=(--cpus-per-task "$CPUS_PER_TASK")
fi

echo "[palmetto] launching with partition=$PARTITION account=${ACCOUNT:-none} qos=${QOS:-none} include_m5=$INCLUDE_M5"
"${CMD[@]}"
