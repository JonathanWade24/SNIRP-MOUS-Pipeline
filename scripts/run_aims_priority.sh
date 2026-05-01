#!/usr/bin/env bash
set -euo pipefail

usage() {
  cat <<'EOF'
Build/Run Aim 1/2/3 SLURM orchestration.

Usage:
  scripts/run_aims_priority.sh --config <config.yaml> [--subjects A2002,A2003] [--fetch-missing] [--dry-run]
                               [--partition hpcnirc] [--account acct] [--qos qos]
                               [--time 08:00:00] [--mem 32G] [--cpus-per-task 8]
                               [--include-m5]

Behavior:
  1) Resolve subjects from config `subjects:` or --subjects override.
  2) Optionally fetch missing subjects via `mous-pipeline fetch-rdr --execute`.
  3) Run post-merge Aim1 regression/QC audit for first subject.
  4) Submit SLURM fMRIPrep array job (one task per subject).
  5) Run MEG pipeline per subject for Aim1/Aim3 metrics.
  6) Run group aggregation and write Aim3 null summary artifacts.
EOF
}

CONFIG=""
SUBJECTS_OVERRIDE=""
FETCH_MISSING=0
DRY_RUN=0
PARTITION=""
ACCOUNT=""
QOS=""
TIME_LIMIT=""
MEMORY=""
CPUS_PER_TASK=""
INCLUDE_M5=0

while [[ $# -gt 0 ]]; do
  case "$1" in
    --config)
      CONFIG="${2:-}"
      shift 2
      ;;
    --subjects)
      SUBJECTS_OVERRIDE="${2:-}"
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
    --include-m5)
      INCLUDE_M5=1
      shift
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
CONFIG_ABS="$(python -c 'from pathlib import Path; import sys; print(Path(sys.argv[1]).expanduser().resolve())' "$CONFIG")"

if [[ ! -f "$CONFIG_ABS" ]]; then
  echo "Config not found: $CONFIG_ABS" >&2
  exit 1
fi

if ! command -v mous-pipeline >/dev/null 2>&1; then
  echo "mous-pipeline is not on PATH. Activate your environment first." >&2
  exit 1
fi
if [[ "$DRY_RUN" -ne 1 ]] && ! command -v sbatch >/dev/null 2>&1; then
  echo "sbatch not found. This script targets SLURM clusters." >&2
  exit 1
fi

RESOLVED_JSON="$(python - "$CONFIG_ABS" "$SUBJECTS_OVERRIDE" <<'PY'
import json
import sys
from pathlib import Path
from mous_pipeline.config import load_config

cfg = load_config(Path(sys.argv[1]).expanduser().resolve())
override = [s.strip().removeprefix("sub-") for s in (sys.argv[2] or "").split(",") if s.strip()]
subjects = override if override else [str(s).removeprefix("sub-") for s in cfg.subjects]
subjects = [s for s in subjects if s]
if not subjects:
    raise SystemExit("No subjects resolved. Provide --subjects or set config subjects:.")
payload = {
    "subjects": subjects,
    "data_root": str(cfg.data_root.expanduser().resolve()),
    "derivatives_root": str(cfg.derivatives_root.expanduser().resolve()),
}
print(json.dumps(payload))
PY
)"

SUBJECTS=()
while IFS= read -r line; do
  SUBJECTS+=("$line")
done < <(python - <<'PY' "$RESOLVED_JSON"
import json,sys
payload=json.loads(sys.argv[1])
for s in payload["subjects"]:
    print(s)
PY
)
DATA_ROOT="$(python - <<'PY' "$RESOLVED_JSON"
import json,sys
print(json.loads(sys.argv[1])["data_root"])
PY
)"
DERIV_ROOT="$(python - <<'PY' "$RESOLVED_JSON"
import json,sys
print(json.loads(sys.argv[1])["derivatives_root"])
PY
)"

echo "[plan] config=$CONFIG_ABS"
echo "[plan] data_root=$DATA_ROOT"
echo "[plan] derivatives_root=$DERIV_ROOT"
echo "[plan] subjects=${SUBJECTS[*]}"

AVAILABLE_SUBJECTS=()
SKIPPED_SUBJECTS=()
for sub in "${SUBJECTS[@]}"; do
  if [[ ! -d "$DATA_ROOT/sub-$sub" ]]; then
    if [[ "$FETCH_MISSING" -eq 1 ]]; then
      if [[ "$DRY_RUN" -eq 1 ]]; then
        echo "[dry-run][fetch] mous-pipeline fetch-rdr --config $CONFIG_ABS --subject $sub --execute --skip-invalid"
        AVAILABLE_SUBJECTS+=("$sub")
        continue
      fi
      echo "[fetch] sub-$sub missing; fetching via RDR..."
      if ! mous-pipeline fetch-rdr --config "$CONFIG_ABS" --subject "$sub" --execute --skip-invalid; then
        echo "[fetch][skip] sub-$sub fetch failed; excluding from this run." >&2
        SKIPPED_SUBJECTS+=("$sub")
        continue
      fi
      if [[ ! -d "$DATA_ROOT/sub-$sub" ]]; then
        echo "[fetch][skip] sub-$sub still missing after fetch; excluding from this run." >&2
        SKIPPED_SUBJECTS+=("$sub")
        continue
      fi
    else
      echo "Missing subject directory: $DATA_ROOT/sub-$sub (use --fetch-missing to auto-fetch)" >&2
      exit 1
    fi
  fi
  AVAILABLE_SUBJECTS+=("$sub")
done
SUBJECTS=("${AVAILABLE_SUBJECTS[@]}")
if (( ${#SKIPPED_SUBJECTS[@]} > 0 )); then
  echo "[fetch][warn] skipped subjects: ${SKIPPED_SUBJECTS[*]}" >&2
fi
if (( ${#SUBJECTS[@]} == 0 )); then
  echo "No valid/fetched subject directories remain; aborting before SLURM submission." >&2
  exit 1
fi
echo "[plan] runnable_subjects=${SUBJECTS[*]}"

FIRST_SUBJECT="${SUBJECTS[0]}"
echo "[meg-trial] Running MEG trial-metrics regression/QC audit for sub-$FIRST_SUBJECT"
if [[ "$DRY_RUN" -eq 1 ]]; then
  echo "[dry-run][audit] python $REPO_ROOT/scripts/aim1_audit.py --config $CONFIG_ABS --subject $FIRST_SUBJECT"
else
python "$REPO_ROOT/scripts/aim1_audit.py" --config "$CONFIG_ABS" --subject "$FIRST_SUBJECT"
fi

SLURM_DIR="$DERIV_ROOT/slurm"
ARRAY_MAX=$(( ${#SUBJECTS[@]} - 1 ))
if [[ "$DRY_RUN" -eq 1 ]]; then
  SUBJECTS_FILE="$SLURM_DIR/fmriprep_subjects_dryrun.txt"
else
  mkdir -p "$SLURM_DIR"
  SUBJECTS_FILE="$SLURM_DIR/fmriprep_subjects_$(date +%Y%m%d_%H%M%S).txt"
  printf "%s\n" "${SUBJECTS[@]}" > "$SUBJECTS_FILE"
fi

echo "[fmri] submitting fMRI preprocessing array: 0-$ARRAY_MAX"
SBATCH_OUTPUT="$SLURM_DIR/fmriprep_%A_%a.out"
SBATCH_ERROR="$SLURM_DIR/fmriprep_%A_%a.err"
SBATCH_LOG="$SLURM_DIR/fmriprep_submit_$(date +%Y%m%d_%H%M%S).log"
SBATCH_EXTRA=()
if [[ -n "$PARTITION" ]]; then
  SBATCH_EXTRA+=(--partition "$PARTITION")
fi
if [[ -n "$ACCOUNT" ]]; then
  SBATCH_EXTRA+=(--account "$ACCOUNT")
fi
if [[ -n "$QOS" ]]; then
  SBATCH_EXTRA+=(--qos "$QOS")
fi
if [[ -n "$TIME_LIMIT" ]]; then
  SBATCH_EXTRA+=(--time "$TIME_LIMIT")
fi
if [[ -n "$MEMORY" ]]; then
  SBATCH_EXTRA+=(--mem "$MEMORY")
fi
if [[ -n "$CPUS_PER_TASK" ]]; then
  SBATCH_EXTRA+=(--cpus-per-task "$CPUS_PER_TASK")
fi

if [[ "$DRY_RUN" -eq 1 ]]; then
  FMRIPREP_JOB_ID="<fmriprep_job_id>"
  EXTRA_STR=""
  if (( ${#SBATCH_EXTRA[@]} > 0 )); then
    EXTRA_STR="$(printf ' %q' "${SBATCH_EXTRA[@]}")"
  fi
  echo "[dry-run][slurm] sbatch --job-name mous_fmriprep --array 0-$ARRAY_MAX --output $SBATCH_OUTPUT --error $SBATCH_ERROR${EXTRA_STR} $REPO_ROOT/scripts/run_fmriprep_subject.sh --config $CONFIG_ABS --subjects-file $SUBJECTS_FILE"
  echo "[dry-run][fmri] note: fMRI preprocessing runs as detached array jobs and may finish after the driver exits."
else
  SBATCH_REPLY="$(sbatch \
    --job-name "mous_fmriprep" \
    --array "0-$ARRAY_MAX" \
    --output "$SBATCH_OUTPUT" \
    --error "$SBATCH_ERROR" \
    "${SBATCH_EXTRA[@]}" \
    "$REPO_ROOT/scripts/run_fmriprep_subject.sh" \
    --config "$CONFIG_ABS" \
    --subjects-file "$SUBJECTS_FILE")"
  printf "%s\n" "$SBATCH_REPLY" | tee "$SBATCH_LOG"
  FMRIPREP_JOB_ID="$(awk '/Submitted batch job/{print $4}' <<< "$SBATCH_REPLY" | tail -n1)"
  if [[ -n "$FMRIPREP_JOB_ID" ]]; then
    echo "[fmri] submitted detached array job id: $FMRIPREP_JOB_ID"
  fi
  echo "[fmri] note: fMRI preprocessing may continue after mous_driver exits."
fi

for sub in "${SUBJECTS[@]}"; do
  echo "[meg-subject] Running subject MEG outputs for sub-$sub"
  MEG_SKIP="m5,m10,m11"
  if [[ "$INCLUDE_M5" -eq 1 ]]; then
    MEG_SKIP="m10,m11"
  fi
  if [[ "$DRY_RUN" -eq 1 ]]; then
    echo "[dry-run][meg-subject] mous-pipeline run --config $CONFIG_ABS --subject $sub --skip $MEG_SKIP"
    continue
  fi
  mous-pipeline run --config "$CONFIG_ABS" --subject "$sub" --skip "$MEG_SKIP"
done

echo "[meg-group] Running MEG group aggregation"
if [[ "$DRY_RUN" -eq 1 ]]; then
  echo "[dry-run][meg-group] mous-pipeline group --derivatives-root $DERIV_ROOT"
  echo "[dry-run][meg-group] python $REPO_ROOT/scripts/aim3_null_summary.py --derivatives-root $DERIV_ROOT --out-md $REPO_ROOT/reports/aim3_null_summary.md --out-json $REPO_ROOT/reports/aim3_null_summary.json"
  echo "[fmri-stages] submitting dependent m10/m11/m12 + group job"
  FMRI_STAGES_OUTPUT="$SLURM_DIR/fmri_stages_%A.out"
  FMRI_STAGES_ERROR="$SLURM_DIR/fmri_stages_%A.err"
  DEP_STR=""
  EXTRA_STR=""
  FMRI_STAGES_DEP=()
  if [[ -n "${FMRIPREP_JOB_ID:-}" ]]; then
    # Use `afterany` (not `afterok`) and `--kill-on-invalid-dep=no` so a
    # partially-failed or already-cleared fMRIPrep array does not get the whole
    # downstream submission rejected. run_fmri_stages.sh tolerates missing
    # fMRIPrep outputs (--reuse-fmriprep / --allow-m11-from-cached-joined).
    FMRI_STAGES_DEP=(--dependency "afterany:${FMRIPREP_JOB_ID}" --kill-on-invalid-dep=no)
  fi
  if (( ${#FMRI_STAGES_DEP[@]} > 0 )); then
    DEP_STR="$(printf ' %q' "${FMRI_STAGES_DEP[@]}")"
  fi
  if (( ${#SBATCH_EXTRA[@]} > 0 )); then
    EXTRA_STR="$(printf ' %q' "${SBATCH_EXTRA[@]}")"
  fi
  echo "[dry-run][slurm] sbatch --job-name mous_fmri_stages --output $FMRI_STAGES_OUTPUT --error $FMRI_STAGES_ERROR${DEP_STR}${EXTRA_STR} $REPO_ROOT/scripts/run_fmri_stages.sh --config $CONFIG_ABS --subjects-file $SUBJECTS_FILE --deriv-root $DERIV_ROOT --dry-run"
  echo "[done] Dry run complete."
  exit 0
fi
mous-pipeline group --derivatives-root "$DERIV_ROOT"

echo "[meg-group] Writing group summary/null artifacts"
python "$REPO_ROOT/scripts/aim3_null_summary.py" \
  --derivatives-root "$DERIV_ROOT" \
  --out-md "$REPO_ROOT/reports/aim3_null_summary.md" \
  --out-json "$REPO_ROOT/reports/aim3_null_summary.json"

echo "[fmri-stages] submitting dependent m10/m11/m12 + group job"
FMRI_STAGES_OUTPUT="$SLURM_DIR/fmri_stages_%A.out"
FMRI_STAGES_ERROR="$SLURM_DIR/fmri_stages_%A.err"
FMRI_STAGES_DEP=()
if [[ -n "${FMRIPREP_JOB_ID:-}" ]]; then
  # Tolerate per-subject fMRIPrep failures and stale parent jobs:
  #   - `afterany` triggers once the parent terminates in any state.
  #   - `--kill-on-invalid-dep=no` keeps the dependent job held instead of
  #     having sbatch reject the submission outright when the dep can no
  #     longer be satisfied.
  FMRI_STAGES_DEP=(--dependency "afterany:${FMRIPREP_JOB_ID}" --kill-on-invalid-dep=no)
fi

submit_fmri_stages() {
  sbatch \
    --job-name "mous_fmri_stages" \
    --output "$FMRI_STAGES_OUTPUT" \
    --error "$FMRI_STAGES_ERROR" \
    "$@" \
    "${SBATCH_EXTRA[@]}" \
    "$REPO_ROOT/scripts/run_fmri_stages.sh" \
    --config "$CONFIG_ABS" \
    --subjects-file "$SUBJECTS_FILE" \
    --deriv-root "$DERIV_ROOT"
}

set +e
FMRI_STAGES_REPLY="$(submit_fmri_stages "${FMRI_STAGES_DEP[@]}" 2>&1)"
FMRI_STAGES_RC=$?
set -e
printf "%s\n" "$FMRI_STAGES_REPLY"

if [[ $FMRI_STAGES_RC -ne 0 ]]; then
  if (( ${#FMRI_STAGES_DEP[@]} > 0 )) && grep -qiE 'dependency|invalid dep' <<< "$FMRI_STAGES_REPLY"; then
    echo "[fmri-stages][warn] dependency on fMRIPrep job ${FMRIPREP_JOB_ID:-?} is not satisfiable; retrying without dependency." >&2
    set +e
    FMRI_STAGES_REPLY="$(submit_fmri_stages 2>&1)"
    FMRI_STAGES_RC=$?
    set -e
    printf "%s\n" "$FMRI_STAGES_REPLY"
  fi
fi

if [[ $FMRI_STAGES_RC -ne 0 ]]; then
  echo "[fmri-stages][error] sbatch submission failed (rc=$FMRI_STAGES_RC)." >&2
  exit "$FMRI_STAGES_RC"
fi

FMRI_STAGES_JOB_ID="$(awk '/Submitted batch job/{print $4}' <<< "$FMRI_STAGES_REPLY" | tail -n1)"
if [[ -n "$FMRI_STAGES_JOB_ID" ]]; then
  echo "[fmri-stages] submitted job id: $FMRI_STAGES_JOB_ID"
else
  echo "[fmri-stages] submission completed; job id not parsed"
fi

echo "[done] Priority order complete: MEG trial audit -> fMRI preprocessing submit -> MEG subject/group outputs."
