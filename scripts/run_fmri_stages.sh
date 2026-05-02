#!/usr/bin/env bash
set -euo pipefail

usage() {
  cat <<'EOF'
Run fMRI-dependent stages (m8,m10,m11,m12) per subject, then group aggregation.

Usage:
  run_fmri_stages.sh --config <config.yaml> --subjects-file <path> --deriv-root <path> [--dry-run] [--force]

Environment:
  MOUS_R_MODULE  R module to load when Rscript is not already on PATH
                 (default: r/4.5.0)
EOF
}

CONFIG=""
SUBJECTS_FILE=""
DERIV_ROOT=""
DRY_RUN=0
FORCE_PIPELINE=0
R_MODULE="${MOUS_R_MODULE:-r/4.5.0}"

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
    --force)
      FORCE_PIPELINE=1
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

load_r_runtime() {
  if command -v Rscript >/dev/null 2>&1; then
    echo "[fmri-stages][r] Rscript already on PATH: $(command -v Rscript)"
    return
  fi

  if ! command -v module >/dev/null 2>&1; then
    for module_init in /etc/profile.d/modules.sh /usr/share/Modules/init/bash; do
      if [[ -r "$module_init" ]]; then
        # shellcheck source=/dev/null
        source "$module_init"
        break
      fi
    done
  fi

  if ! command -v module >/dev/null 2>&1; then
    echo "[fmri-stages][error] Rscript is not on PATH and the module command is unavailable." >&2
    echo "[fmri-stages][error] Load R before running or set MOUS_R_MODULE to an available Palmetto R module." >&2
    exit 1
  fi

  echo "[fmri-stages][r] Loading R module: $R_MODULE"
  if ! module load "$R_MODULE"; then
    echo "[fmri-stages][error] Failed to load R module: $R_MODULE" >&2
    echo "[fmri-stages][error] Set MOUS_R_MODULE to an available module, for example r/4.4.0 or r/4.5.0." >&2
    exit 1
  fi

  if ! command -v Rscript >/dev/null 2>&1; then
    echo "[fmri-stages][error] Loaded $R_MODULE, but Rscript is still not on PATH." >&2
    exit 1
  fi
  echo "[fmri-stages][r] Rscript: $(command -v Rscript)"
}

if [[ "$DRY_RUN" -eq 1 ]]; then
  echo "[dry-run][fmri-stages][r] would load R module if needed: $R_MODULE"
else
  load_r_runtime
  echo "[fmri-stages][r] Checking Quarto/R runtime"
  mous-pipeline check-quarto-env
fi

run_subject_cmd() {
  local subject="$1"
  local -a cmd=(
    mous-pipeline run
    --config "$CONFIG"
    --subject "$subject"
    --only "m8,m10,m11,m12"
    --reuse-fmriprep
    --allow-m11-from-cached-joined
    --assume-upstream-done
    --preflight-quarto-env
  )
  if [[ "$FORCE_PIPELINE" -eq 1 ]]; then
    cmd+=(--force)
  fi
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
