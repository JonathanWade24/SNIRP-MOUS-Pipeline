#!/usr/bin/env bash
set -euo pipefail

usage() {
  cat <<'EOF'
Usage:
  run_fmriprep_subject.sh --config <config.yaml> --subjects-file <path>

Environment:
  SLURM_ARRAY_TASK_ID 0-based index into subjects-file lines.
EOF
}

CONFIG=""
SUBJECTS_FILE=""

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

if [[ -z "$CONFIG" || -z "$SUBJECTS_FILE" ]]; then
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

LINE_NO=$((SLURM_ARRAY_TASK_ID + 1))
SUBJECT="$(sed -n "${LINE_NO}p" "$SUBJECTS_FILE" | tr -d '[:space:]')"

if [[ -z "$SUBJECT" ]]; then
  echo "No subject resolved for SLURM_ARRAY_TASK_ID=$SLURM_ARRAY_TASK_ID" >&2
  exit 1
fi

echo "[fmriprep-array] subject=$SUBJECT config=$CONFIG"
python - "$CONFIG" "$SUBJECT" <<'PY'
from pathlib import Path
import sys

from mous_pipeline.config import load_config
from mous_pipeline.m10_fmri.prep import run_fmriprep

cfg = load_config(Path(sys.argv[1]).expanduser().resolve())
subject = sys.argv[2].removeprefix("sub-")
out_dir = run_fmriprep(subject, cfg, bids_root=cfg.data_root)
print(f"[fmriprep-array] done subject={subject} out_dir={out_dir}")
PY
