#!/usr/bin/env bash
set -euo pipefail

usage() {
  cat <<'EOF'
Submit a Palmetto recon-all array job for cohort subjects.

Usage:
  scripts/palmetto_recon_all.sh --config <config.yaml> [options]

Options:
  --subjects A2002,A2003
  --partition <name>       (default: hpcnirc)
  --account <account>
  --qos <qos>
  --time <HH:MM:SS>        (default: 12:00:00)
  --mem <value>            (default: 16G)
  --cpus-per-task <n>      (default: 4)
  --dry-run

Environment:
  MOUS_FREESURFER_MODULE    Optional module name (e.g. freesurfer/7.4.1).
  MOUS_FREESURFER_CONTAINER Optional apptainer/singularity image for recon-all.
  MOUS_FREESURFER_LICENSE   Optional FreeSurfer license path.
EOF
}

CONFIG=""
SUBJECTS_OVERRIDE=""
DRY_RUN=0
PARTITION="${MOUS_PARTITION:-hpcnirc}"
ACCOUNT="${MOUS_ACCOUNT:-}"
QOS="${MOUS_QOS:-}"
TIME_LIMIT="${MOUS_RECON_TIME:-12:00:00}"
MEMORY="${MOUS_RECON_MEM:-16G}"
CPUS_PER_TASK="${MOUS_RECON_CPUS_PER_TASK:-4}"

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
if [[ "$DRY_RUN" -ne 1 ]] && ! command -v sbatch >/dev/null 2>&1; then
  echo "sbatch not found. This script targets SLURM clusters." >&2
  exit 1
fi

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
CONFIG_ABS="$(python -c 'from pathlib import Path; import sys; print(Path(sys.argv[1]).expanduser().resolve())' "$CONFIG")"

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
DERIV_ROOT="$(python - <<'PY' "$RESOLVED_JSON"
import json,sys
print(json.loads(sys.argv[1])["derivatives_root"])
PY
)"

FS_SUBJECTS_DIR="$DERIV_ROOT/freesurfer"
SLURM_DIR="$DERIV_ROOT/slurm"
ARRAY_MAX=$(( ${#SUBJECTS[@]} - 1 ))

if [[ "$DRY_RUN" -eq 1 ]]; then
  SUBJECTS_FILE="$SLURM_DIR/recon_subjects_dryrun.txt"
else
  mkdir -p "$SLURM_DIR" "$FS_SUBJECTS_DIR"
  SUBJECTS_FILE="$SLURM_DIR/recon_subjects_$(date +%Y%m%d_%H%M%S).txt"
  printf "%s\n" "${SUBJECTS[@]}" > "$SUBJECTS_FILE"
fi

SBATCH_OUTPUT="$SLURM_DIR/recon_%A_%a.out"
SBATCH_ERROR="$SLURM_DIR/recon_%A_%a.err"
SBATCH_EXTRA=(--partition "$PARTITION" --time "$TIME_LIMIT" --mem "$MEMORY" --cpus-per-task "$CPUS_PER_TASK")
if [[ -n "$ACCOUNT" ]]; then
  SBATCH_EXTRA+=(--account "$ACCOUNT")
fi
if [[ -n "$QOS" ]]; then
  SBATCH_EXTRA+=(--qos "$QOS")
fi

echo "[plan] config=$CONFIG_ABS"
echo "[plan] subjects=${SUBJECTS[*]}"
echo "[plan] freesurfer_subjects_dir=$FS_SUBJECTS_DIR"

if [[ "$DRY_RUN" -eq 1 ]]; then
  EXTRA_STR="$(printf ' %q' "${SBATCH_EXTRA[@]}")"
  echo "[dry-run][slurm] sbatch --job-name mous_recon --array 0-$ARRAY_MAX --output $SBATCH_OUTPUT --error $SBATCH_ERROR${EXTRA_STR} --export=ALL,MOUS_FREESURFER_MODULE=${MOUS_FREESURFER_MODULE:-},MOUS_FREESURFER_CONTAINER=${MOUS_FREESURFER_CONTAINER:-},MOUS_FREESURFER_LICENSE=${MOUS_FREESURFER_LICENSE:-} $REPO_ROOT/scripts/run_recon_all_subject.sh --config $CONFIG_ABS --subjects-file $SUBJECTS_FILE --subjects-dir $FS_SUBJECTS_DIR"
  exit 0
fi

sbatch \
  --job-name "mous_recon" \
  --array "0-$ARRAY_MAX" \
  --output "$SBATCH_OUTPUT" \
  --error "$SBATCH_ERROR" \
  "${SBATCH_EXTRA[@]}" \
  --export=ALL,MOUS_FREESURFER_MODULE="${MOUS_FREESURFER_MODULE:-}",MOUS_FREESURFER_CONTAINER="${MOUS_FREESURFER_CONTAINER:-}",MOUS_FREESURFER_LICENSE="${MOUS_FREESURFER_LICENSE:-}" \
  "$REPO_ROOT/scripts/run_recon_all_subject.sh" \
  --config "$CONFIG_ABS" \
  --subjects-file "$SUBJECTS_FILE" \
  --subjects-dir "$FS_SUBJECTS_DIR"
