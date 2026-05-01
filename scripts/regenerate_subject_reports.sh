#!/usr/bin/env bash
# Rebuild m8 HTML/Quarto/Aim2 subject reports from existing derivatives (no m10/m11/m12
# recompute). Requires prior pipeline outputs under derivatives_root from the same config
# (at minimum m6a direction/DCI caches so m7 can run; joined CSV for fMRI sections).
set -euo pipefail

usage() {
  cat <<'EOF'
Regenerate per-subject reports (stage m8 only): exports, dashboard HTML, Quarto HTML,
and Aim2 subject summary — using cached upstream artifacts.

Does NOT rerun preprocessing, GLM (m10), coupling (m11), or wave validation (m12).

Usage:
  regenerate_subject_reports.sh --config <config.yaml> --subjects-file <path> [options]

Options:
  --deriv-root <path>   If set with --with-group, run mous-pipeline group after all subjects.
  --with-group          Run group aggregation once after subjects (needs --deriv-root).
  --force               Pass through to mous-pipeline run (recompute m8 outputs).
  --dry-run             Print commands only.
  --skip-quarto-preflight
                        Skip mous-pipeline check-quarto-env (not recommended on first run).
  -h, --help            Show this help.

Environment:
  MOUS_R_MODULE   R module to load when Rscript is not on PATH (default: r/4.5.0)

Example:
  scripts/regenerate_subject_reports.sh \\
    --config configs/palmetto_hpcnirc_fmri.yaml \\
    --subjects-file path/to/subjects.txt \\
    --with-group --deriv-root /scratch/you/mous_derivatives
EOF
}

CONFIG=""
SUBJECTS_FILE=""
DERIV_ROOT=""
DRY_RUN=0
WITH_GROUP=0
FORCE=0
SKIP_QUARTO_PREFLIGHT=0
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
    --with-group)
      WITH_GROUP=1
      shift
      ;;
    --force)
      FORCE=1
      shift
      ;;
    --skip-quarto-preflight)
      SKIP_QUARTO_PREFLIGHT=1
      shift
      ;;
    -h|--help)
      usage
      exit 0
      ;;
    *)
      echo "[regen-reports][error] Unknown argument: $1" >&2
      usage >&2
      exit 2
      ;;
  esac
done

if [[ -z "$CONFIG" || -z "$SUBJECTS_FILE" ]]; then
  echo "[regen-reports][error] --config and --subjects-file are required." >&2
  usage >&2
  exit 2
fi

if [[ "$WITH_GROUP" -eq 1 && -z "$DERIV_ROOT" ]]; then
  echo "[regen-reports][error] --with-group requires --deriv-root." >&2
  exit 2
fi

if [[ ! -f "$SUBJECTS_FILE" ]]; then
  echo "[regen-reports][error] subjects file not found: $SUBJECTS_FILE" >&2
  exit 1
fi

if ! command -v mous-pipeline >/dev/null 2>&1; then
  echo "[regen-reports][error] mous-pipeline is not on PATH." >&2
  exit 1
fi

load_r_runtime() {
  if command -v Rscript >/dev/null 2>&1; then
    echo "[regen-reports][r] Rscript already on PATH: $(command -v Rscript)"
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
    echo "[regen-reports][error] Rscript is not on PATH and the module command is unavailable." >&2
    exit 1
  fi

  echo "[regen-reports][r] Loading R module: $R_MODULE"
  if ! module load "$R_MODULE"; then
    echo "[regen-reports][error] Failed to load R module: $R_MODULE" >&2
    exit 1
  fi

  if ! command -v Rscript >/dev/null 2>&1; then
    echo "[regen-reports][error] Loaded $R_MODULE, but Rscript is still not on PATH." >&2
    exit 1
  fi
  echo "[regen-reports][r] Rscript: $(command -v Rscript)"
}

if [[ "$DRY_RUN" -eq 1 ]]; then
  echo "[dry-run][regen-reports][r] would load R module if needed: $R_MODULE"
else
  load_r_runtime
  if [[ "$SKIP_QUARTO_PREFLIGHT" -eq 0 ]]; then
    echo "[regen-reports][r] Checking Quarto/R runtime"
    mous-pipeline check-quarto-env
  fi
fi

run_subject_cmd() {
  local subject="$1"
  local -a cmd=(
    mous-pipeline run
    --config "$CONFIG"
    --subject "$subject"
    --only m8
    --assume-upstream-done
  )
  if [[ "$SKIP_QUARTO_PREFLIGHT" -eq 0 ]]; then
    cmd+=(--preflight-quarto-env)
  fi
  if [[ "$FORCE" -eq 1 ]]; then
    cmd+=(--force)
  fi
  if [[ "$DRY_RUN" -eq 1 ]]; then
    cmd+=(--dry-run)
    echo "[dry-run][regen-reports][subject] ${cmd[*]}"
  else
    echo "[regen-reports][subject] sub-${subject}"
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

if [[ "$WITH_GROUP" -eq 1 ]]; then
  group_cmd=(mous-pipeline group --derivatives-root "$DERIV_ROOT")
  if [[ "$DRY_RUN" -eq 1 ]]; then
    echo "[dry-run][regen-reports][group] ${group_cmd[*]}"
  else
    echo "[regen-reports][group] mous-pipeline group"
    "${group_cmd[@]}"
  fi
fi

echo "[regen-reports][done] Finished report regeneration."
