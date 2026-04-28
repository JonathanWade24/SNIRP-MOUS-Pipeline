#!/usr/bin/env bash
set -euo pipefail

usage() {
  cat <<'EOF'
Submit a Palmetto BEM-prep array job for cohort subjects.

Usage:
  scripts/palmetto_prep_bem.sh --config <config.yaml> [options]

Options:
  --subjects A2002,A2003
  --partition <name>       (default: hpcnirc)
  --account <account>
  --qos <qos>
  --dependency <expr>      e.g. afterok:12345
  --time <HH:MM:SS>        (default: 04:00:00)
  --mem <value>            (default: 16G)
  --cpus-per-task <n>      (default: 2)
  --dry-run
EOF
}

CONFIG=""
SUBJECTS_OVERRIDE=""
DRY_RUN=0
PARTITION="${MOUS_PARTITION:-hpcnirc}"
ACCOUNT="${MOUS_ACCOUNT:-}"
QOS="${MOUS_QOS:-}"
DEPENDENCY="${MOUS_BEM_DEPENDENCY:-}"
TIME_LIMIT="${MOUS_BEM_TIME:-04:00:00}"
MEMORY="${MOUS_BEM_MEM:-16G}"
CPUS_PER_TASK="${MOUS_BEM_CPUS_PER_TASK:-2}"

while [[ $# -gt 0 ]]; do
  case "$1" in
    --config) CONFIG="${2:-}"; shift 2 ;;
    --subjects) SUBJECTS_OVERRIDE="${2:-}"; shift 2 ;;
    --partition) PARTITION="${2:-}"; shift 2 ;;
    --account) ACCOUNT="${2:-}"; shift 2 ;;
    --qos) QOS="${2:-}"; shift 2 ;;
    --dependency) DEPENDENCY="${2:-}"; shift 2 ;;
    --time) TIME_LIMIT="${2:-}"; shift 2 ;;
    --mem) MEMORY="${2:-}"; shift 2 ;;
    --cpus-per-task) CPUS_PER_TASK="${2:-}"; shift 2 ;;
    --dry-run) DRY_RUN=1; shift ;;
    -h|--help) usage; exit 0 ;;
    *) echo "Unknown argument: $1" >&2; usage >&2; exit 2 ;;
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
fmriprep_container = ""
fmri = getattr(cfg, "fmri", None)
if fmri:
    fmriprep_container = str(getattr(fmri, "fmriprep_container", "") or "")
payload = {
    "subjects": subjects,
    "derivatives_root": str(cfg.derivatives_root.expanduser().resolve()),
    "subjects_dir": str(Path(cfg.source.subjects_dir).expanduser().resolve()) if getattr(cfg.source, "subjects_dir", "") else "",
    "fmriprep_container": fmriprep_container,
}
print(json.dumps(payload))
PY
)"

SUBJECTS=()
while IFS= read -r line; do
  SUBJECTS+=("$line")
done < <(python - <<'PY' "$RESOLVED_JSON"
import json,sys
for s in json.loads(sys.argv[1])["subjects"]:
    print(s)
PY
)
DERIV_ROOT="$(python - <<'PY' "$RESOLVED_JSON"
import json,sys
print(json.loads(sys.argv[1])["derivatives_root"])
PY
)"
FS_SUBJECTS_DIR="$(python - <<'PY' "$RESOLVED_JSON"
import json,sys
print(json.loads(sys.argv[1])["subjects_dir"])
PY
)"
if [[ -z "$FS_SUBJECTS_DIR" ]]; then
  FS_SUBJECTS_DIR="$DERIV_ROOT/freesurfer"
fi

# Auto-detect FreeSurfer container from config when env var not already set.
if [[ -z "${MOUS_FREESURFER_CONTAINER:-}" ]]; then
  _CFG_CONTAINER="$(python - <<'PY' "$RESOLVED_JSON"
import json,sys
print(json.loads(sys.argv[1]).get("fmriprep_container",""))
PY
)"
  if [[ -n "$_CFG_CONTAINER" && -f "$_CFG_CONTAINER" ]]; then
    export MOUS_FREESURFER_CONTAINER="$_CFG_CONTAINER"
    echo "[plan] auto-detected freesurfer_container=$MOUS_FREESURFER_CONTAINER"
  fi
fi

SLURM_DIR="$DERIV_ROOT/slurm"
ARRAY_MAX=$(( ${#SUBJECTS[@]} - 1 ))
mkdir -p "$SLURM_DIR" "$FS_SUBJECTS_DIR"

if [[ "$DRY_RUN" -eq 1 ]]; then
  SUBJECTS_FILE="$SLURM_DIR/bem_subjects_dryrun.txt"
else
  SUBJECTS_FILE="$SLURM_DIR/bem_subjects_$(date +%Y%m%d_%H%M%S).txt"
  printf "%s\n" "${SUBJECTS[@]}" > "$SUBJECTS_FILE"
fi

SBATCH_OUTPUT="$SLURM_DIR/bem_%A_%a.out"
SBATCH_ERROR="$SLURM_DIR/bem_%A_%a.err"
SBATCH_EXTRA=(--partition "$PARTITION" --time "$TIME_LIMIT" --mem "$MEMORY" --cpus-per-task "$CPUS_PER_TASK")
if [[ -n "$ACCOUNT" ]]; then SBATCH_EXTRA+=(--account "$ACCOUNT"); fi
if [[ -n "$QOS" ]]; then SBATCH_EXTRA+=(--qos "$QOS"); fi
if [[ -n "$DEPENDENCY" ]]; then SBATCH_EXTRA+=(--dependency "$DEPENDENCY"); fi

echo "[plan] config=$CONFIG_ABS"
echo "[plan] subjects=${SUBJECTS[*]}"
echo "[plan] freesurfer_subjects_dir=$FS_SUBJECTS_DIR"

if [[ "$DRY_RUN" -eq 1 ]]; then
  EXTRA_STR="$(printf ' %q' "${SBATCH_EXTRA[@]}")"
  echo "[dry-run][slurm] sbatch --job-name mous_bem --array 0-$ARRAY_MAX --output $SBATCH_OUTPUT --error $SBATCH_ERROR${EXTRA_STR} --export=ALL,MOUS_FREESURFER_MODULE=${MOUS_FREESURFER_MODULE:-},MOUS_FREESURFER_CONTAINER=${MOUS_FREESURFER_CONTAINER:-},MOUS_VENV_PATH=${MOUS_VENV_PATH:-} $REPO_ROOT/scripts/run_prep_bem_subject.sh --subjects-file $SUBJECTS_FILE --subjects-dir $FS_SUBJECTS_DIR"
  exit 0
fi

sbatch \
  --job-name "mous_bem" \
  --array "0-$ARRAY_MAX" \
  --output "$SBATCH_OUTPUT" \
  --error "$SBATCH_ERROR" \
  "${SBATCH_EXTRA[@]}" \
  --export=ALL,MOUS_FREESURFER_MODULE="${MOUS_FREESURFER_MODULE:-}",MOUS_FREESURFER_CONTAINER="${MOUS_FREESURFER_CONTAINER:-}",MOUS_VENV_PATH="${MOUS_VENV_PATH:-}" \
  "$REPO_ROOT/scripts/run_prep_bem_subject.sh" \
  --subjects-file "$SUBJECTS_FILE" \
  --subjects-dir "$FS_SUBJECTS_DIR"
