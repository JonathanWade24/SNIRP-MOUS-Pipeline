#!/usr/bin/env bash
set -euo pipefail

usage() {
  cat <<'EOF'
Run fMRI-dependent stages (m10,m11,m12) per subject, then group aggregation.

Usage:
  run_fmri_stages.sh --config <config.yaml> --subjects-file <path> --deriv-root <path> [--dry-run]
EOF
}

CONFIG=""
SUBJECTS_FILE=""
DERIV_ROOT=""
DRY_RUN=0

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
    --deriv-root)
      DERIV_ROOT="${2:-}"
      shift 2
      ;;
    --dry-run)
      DRY_RUN=1
      shift
      ;;
    -h|--help)
      usage
      exit 0
      ;;
    *)
      echo "[fmri-stages][error] Unknown argument: $1" >&2
      usage >&2
      exit 2
      ;;
  esac
done

if [[ -z "$CONFIG" || -z "$SUBJECTS_FILE" || -z "$DERIV_ROOT" ]]; then
  echo "[fmri-stages][error] --config, --subjects-file, and --deriv-root are required." >&2
  usage >&2
  exit 2
fi

if [[ ! -f "$SUBJECTS_FILE" ]]; then
  echo "[fmri-stages][error] subjects file not found: $SUBJECTS_FILE" >&2
  exit 1
fi

if ! command -v mous-pipeline >/dev/null 2>&1; then
  echo "[fmri-stages][error] mous-pipeline is not on PATH." >&2
  exit 1
fi

run_subject_cmd() {
  local subject="$1"
  local -a cmd=(
    mous-pipeline run
    --config "$CONFIG"
    --subject "$subject"
    --only "m10,m11,m12"
    --reuse-fmriprep
    --allow-m11-from-cached-joined
    --assume-upstream-done
  )
  if [[ "$DRY_RUN" -eq 1 ]]; then
    cmd+=(--dry-run)
    echo "[dry-run][fmri-stages][subject] ${cmd[*]}"
  else
    echo "[fmri-stages][subject] Running subject sub-${subject}"
    "${cmd[@]}"
  fi
}

while IFS= read -r raw_subject || [[ -n "$raw_subject" ]]; do
  subject="$(tr -d '[:space:]' <<< "$raw_subject")"
  if [[ -z "$subject" ]]; then
    continue
  fi
  subject="${subject#sub-}"
  run_subject_cmd "$subject"
done < "$SUBJECTS_FILE"

group_cmd=(mous-pipeline group --derivatives-root "$DERIV_ROOT")
if [[ "$DRY_RUN" -eq 1 ]]; then
  echo "[dry-run][fmri-stages][group] ${group_cmd[*]}"
else
  echo "[fmri-stages][group] Running group aggregation"
  "${group_cmd[@]}"
fi

echo "[fmri-stages][done] Completed fMRI stage runner."
