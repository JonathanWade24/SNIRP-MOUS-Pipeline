#!/usr/bin/env bash
set -euo pipefail

usage() {
  cat <<'EOF'
Build/Run Aim 1/2/3 SLURM orchestration.

Usage:
  scripts/run_aims_priority.sh --config <config.yaml> [--subjects A2002,A2003] [--fetch-missing] [--dry-run]

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

for sub in "${SUBJECTS[@]}"; do
  if [[ ! -d "$DATA_ROOT/sub-$sub" ]]; then
    if [[ "$FETCH_MISSING" -eq 1 ]]; then
      if [[ "$DRY_RUN" -eq 1 ]]; then
        echo "[dry-run][fetch] mous-pipeline fetch-rdr --config $CONFIG_ABS --subject $sub --execute"
        continue
      fi
      echo "[fetch] sub-$sub missing; fetching via RDR..."
      mous-pipeline fetch-rdr --config "$CONFIG_ABS" --subject "$sub" --execute
    else
      echo "Missing subject directory: $DATA_ROOT/sub-$sub (use --fetch-missing to auto-fetch)" >&2
      exit 1
    fi
  fi
done

FIRST_SUBJECT="${SUBJECTS[0]}"
echo "[audit] Running Aim1 regression/QC audit for sub-$FIRST_SUBJECT"
if [[ "$DRY_RUN" -eq 1 ]]; then
  echo "[dry-run][audit] python $REPO_ROOT/scripts/aim1_audit.py --config $CONFIG_ABS --subject $FIRST_SUBJECT"
else
python "$REPO_ROOT/scripts/aim1_audit.py" --config "$CONFIG_ABS" --subject "$FIRST_SUBJECT"
fi

SLURM_DIR="$DERIV_ROOT/slurm"
mkdir -p "$SLURM_DIR"
SUBJECTS_FILE="$SLURM_DIR/fmriprep_subjects_$(date +%Y%m%d_%H%M%S).txt"
printf "%s\n" "${SUBJECTS[@]}" > "$SUBJECTS_FILE"
ARRAY_MAX=$(( ${#SUBJECTS[@]} - 1 ))

echo "[slurm] submitting fMRIPrep array: 0-$ARRAY_MAX"
SBATCH_OUTPUT="$SLURM_DIR/fmriprep_%A_%a.out"
SBATCH_ERROR="$SLURM_DIR/fmriprep_%A_%a.err"
SBATCH_LOG="$SLURM_DIR/fmriprep_submit_$(date +%Y%m%d_%H%M%S).log"

if [[ "$DRY_RUN" -eq 1 ]]; then
  echo "[dry-run][slurm] sbatch --job-name mous_fmriprep --array 0-$ARRAY_MAX --output $SBATCH_OUTPUT --error $SBATCH_ERROR $REPO_ROOT/scripts/run_fmriprep_subject.sh --config $CONFIG_ABS --subjects-file $SUBJECTS_FILE"
else
  sbatch \
    --job-name "mous_fmriprep" \
    --array "0-$ARRAY_MAX" \
    --output "$SBATCH_OUTPUT" \
    --error "$SBATCH_ERROR" \
    "$REPO_ROOT/scripts/run_fmriprep_subject.sh" \
    --config "$CONFIG_ABS" \
    --subjects-file "$SUBJECTS_FILE" | tee "$SBATCH_LOG"
fi

for sub in "${SUBJECTS[@]}"; do
  echo "[meg] Running MEG pipeline for sub-$sub (Aim1/Aim3 path)"
  if [[ "$DRY_RUN" -eq 1 ]]; then
    echo "[dry-run][meg] mous-pipeline run --config $CONFIG_ABS --subject $sub --skip m5,m10,m11"
    continue
  fi
  mous-pipeline run --config "$CONFIG_ABS" --subject "$sub" --skip m5,m10,m11
done

echo "[group] Running group aggregation"
if [[ "$DRY_RUN" -eq 1 ]]; then
  echo "[dry-run][group] mous-pipeline group --derivatives-root $DERIV_ROOT"
  echo "[dry-run][aim3] python $REPO_ROOT/scripts/aim3_null_summary.py --derivatives-root $DERIV_ROOT --out-md $REPO_ROOT/reports/aim3_null_summary.md --out-json $REPO_ROOT/reports/aim3_null_summary.json"
  echo "[done] Dry run complete."
  exit 0
fi
mous-pipeline group --derivatives-root "$DERIV_ROOT"

echo "[aim3] Writing null summary artifacts"
python "$REPO_ROOT/scripts/aim3_null_summary.py" \
  --derivatives-root "$DERIV_ROOT" \
  --out-md "$REPO_ROOT/reports/aim3_null_summary.md" \
  --out-json "$REPO_ROOT/reports/aim3_null_summary.json"

echo "[done] Priority order complete: Aim1 audit -> fMRIPrep launch -> MEG/group -> Aim3 null summary."
