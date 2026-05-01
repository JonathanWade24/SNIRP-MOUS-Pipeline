#!/usr/bin/env bash
set -euo pipefail

usage() {
  cat <<'EOF'
Assemble the A2002/A2003 MOUS result bundle and zip.

Usage:
  scripts/assemble_a2002_a2003_results.sh [options]

Options:
  --config <path>            Config to snapshot and use for derivatives_root.
                             Default: configs/palmetto_hpcnirc_fmri.yaml
  --subjects <A,B>           Subjects to package. Default: use driver log
                             subject order when available, otherwise A2002,A2003
  --deriv-root <path>        Override derivatives root from config.
  --driver-job-id <id>       Driver SLURM job id. Default: active mous_driver
                             from squeue, otherwise latest driver log.
  --fmriprep-job-id <id>     fMRIPrep array job id. Default: parse driver log.
  --fmri-job-id <id>         fMRI-stage job id. Default: parse driver log.
  --output-dir <path>        Bundle directory. Default:
                             run_results_<subjects>_<YYYYMMDD>_<fmri_job_id>.
                             If that default already exists, a timestamp suffix
                             is added. Explicit --output-dir paths never
                             overwrite.
  --no-zip                   Build directory only.
  --skip-verify              Do not run mous-pipeline verify-run.
  --dry-run                  Print resolved inputs and exit before copying.
  -h, --help                 Show this help.

The script intentionally copies compact reports, manifests, joined CSVs, fMRIPrep
HTML/figure reports, logs, config snapshots, and checks. It does not copy large
NIfTI outputs, fMRIPrep work directories, or broad intermediate caches.
EOF
}

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
CONFIG="$REPO_ROOT/configs/palmetto_hpcnirc_fmri.yaml"
CONFIG_GIVEN=0
SUBJECTS_CSV=""
SUBJECTS_GIVEN=0
DERIV_ROOT_OVERRIDE=""
DRIVER_JOB_ID=""
DRIVER_JOB_ID_GIVEN=0
FMRIPREP_JOB_ID=""
FMRI_JOB_ID=""
FMRI_JOB_PENDING=0
OUTPUT_DIR=""
OUTPUT_DIR_GIVEN=0
MAKE_ZIP=1
SKIP_VERIFY=0
DRY_RUN=0

while [[ $# -gt 0 ]]; do
  case "$1" in
    --config)
      CONFIG="${2:-}"
      CONFIG_GIVEN=1
      shift 2
      ;;
    --subjects)
      SUBJECTS_CSV="${2:-}"
      SUBJECTS_GIVEN=1
      shift 2
      ;;
    --deriv-root)
      DERIV_ROOT_OVERRIDE="${2:-}"
      shift 2
      ;;
    --driver-job-id)
      DRIVER_JOB_ID="${2:-}"
      DRIVER_JOB_ID_GIVEN=1
      shift 2
      ;;
    --fmriprep-job-id)
      FMRIPREP_JOB_ID="${2:-}"
      shift 2
      ;;
    --fmri-job-id)
      FMRI_JOB_ID="${2:-}"
      shift 2
      ;;
    --output-dir)
      OUTPUT_DIR="${2:-}"
      OUTPUT_DIR_GIVEN=1
      shift 2
      ;;
    --no-zip)
      MAKE_ZIP=0
      shift
      ;;
    --skip-verify)
      SKIP_VERIFY=1
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
      echo "[assemble][error] Unknown argument: $1" >&2
      usage >&2
      exit 2
      ;;
  esac
done

CONFIG_ABS="$(python -c 'from pathlib import Path; import sys; print(Path(sys.argv[1]).expanduser().resolve())' "$CONFIG")"
if [[ ! -f "$CONFIG_ABS" ]]; then
  echo "[assemble][error] Config not found: $CONFIG_ABS" >&2
  exit 1
fi

if [[ -n "$DERIV_ROOT_OVERRIDE" ]]; then
  DERIV_ROOT="$(python -c 'from pathlib import Path; import sys; print(Path(sys.argv[1]).expanduser().resolve())' "$DERIV_ROOT_OVERRIDE")"
else
  DERIV_ROOT="$(python - <<'PY' "$CONFIG_ABS"
from pathlib import Path
import sys
from mous_pipeline.config import load_config

cfg = load_config(Path(sys.argv[1]))
print(cfg.derivatives_root.expanduser().resolve())
PY
)"
fi
SLURM_DIR="$DERIV_ROOT/slurm"
FMRIPREP_ROOT="$DERIV_ROOT/fmriprep"

if [[ ! -d "$DERIV_ROOT" ]]; then
  echo "[assemble][error] Derivatives root not found: $DERIV_ROOT" >&2
  exit 1
fi

join_by_underscore() {
  local IFS="_"
  echo "$*"
}

latest_job_id_for_prefix() {
  local prefix="$1"
  local latest
  latest="$(find "$SLURM_DIR" -maxdepth 1 -type f -name "${prefix}_[0-9]*.out" -printf '%T@ %f\n' 2>/dev/null \
    | sort -n \
    | tail -1 \
    | awk '{print $2}')"
  if [[ -z "$latest" ]]; then
    return 1
  fi
  sed -E "s/^${prefix}_([0-9]+).*$/\1/" <<< "$latest"
}

latest_fmriprep_job_id() {
  local latest
  latest="$(find "$SLURM_DIR" -maxdepth 1 -type f -name 'fmriprep_[0-9]*_0.out' -printf '%T@ %f\n' 2>/dev/null \
    | sort -n \
    | tail -1 \
    | awk '{print $2}')"
  if [[ -z "$latest" ]]; then
    return 1
  fi
  sed -E 's/^fmriprep_([0-9]+)_0\.out$/\1/' <<< "$latest"
}

running_driver_job_id() {
  if ! command -v squeue >/dev/null 2>&1; then
    return 1
  fi
  squeue -h -u "${USER:-}" -n mous_driver -t RUNNING,COMPLETING -o '%i' 2>/dev/null \
    | sed 's/_.*//' \
    | sort -V \
    | tail -1
}

driver_log_path() {
  local driver_id="$1"
  echo "$SLURM_DIR/mous_driver_${driver_id}.out"
}

config_from_driver_log() {
  local driver_log="$1"
  awk -F= '/^\[plan\] config=/{print $2}' "$driver_log" 2>/dev/null | tail -1
}

subjects_from_driver_log() {
  local driver_log="$1"
  awk -F= '/^\[plan\] subjects=/{print $2}' "$driver_log" 2>/dev/null \
    | tail -1 \
    | tr ' ' '\n' \
    | sed 's/^sub-//' \
    | awk 'NF'
}

fmriprep_job_from_driver_log() {
  local driver_log="$1"
  awk '/\[fmri\] submitted detached array job id:/{print $NF}' "$driver_log" 2>/dev/null | tail -1
}

fmri_job_from_driver_log() {
  local driver_log="$1"
  awk '/\[fmri-stages\] submitted job id:/{print $NF}' "$driver_log" 2>/dev/null | tail -1
}

if [[ -z "$DRIVER_JOB_ID" ]]; then
  DRIVER_JOB_ID="$(running_driver_job_id || true)"
  if [[ -z "$DRIVER_JOB_ID" ]]; then
    DRIVER_JOB_ID="$(latest_job_id_for_prefix "mous_driver" || true)"
  fi
fi

DRIVER_LOG=""
if [[ -n "$DRIVER_JOB_ID" ]]; then
  DRIVER_LOG="$(driver_log_path "$DRIVER_JOB_ID")"
fi

if [[ "$CONFIG_GIVEN" -eq 0 && -f "$DRIVER_LOG" ]]; then
  DRIVER_CONFIG="$(config_from_driver_log "$DRIVER_LOG" || true)"
  if [[ -n "$DRIVER_CONFIG" && -f "$DRIVER_CONFIG" ]]; then
    CONFIG_ABS="$(python -c 'from pathlib import Path; import sys; print(Path(sys.argv[1]).expanduser().resolve())' "$DRIVER_CONFIG")"
    if [[ -z "$DERIV_ROOT_OVERRIDE" ]]; then
      DERIV_ROOT="$(python - <<'PY' "$CONFIG_ABS"
from pathlib import Path
import sys
from mous_pipeline.config import load_config

cfg = load_config(Path(sys.argv[1]))
print(cfg.derivatives_root.expanduser().resolve())
PY
)"
      SLURM_DIR="$DERIV_ROOT/slurm"
      FMRIPREP_ROOT="$DERIV_ROOT/fmriprep"
      DRIVER_LOG="$(driver_log_path "$DRIVER_JOB_ID")"
    fi
  fi
fi

if [[ "$SUBJECTS_GIVEN" -eq 0 && -f "$DRIVER_LOG" ]]; then
  SUBJECTS_CSV="$(subjects_from_driver_log "$DRIVER_LOG" | paste -sd, -)"
fi
if [[ -z "$SUBJECTS_CSV" ]]; then
  SUBJECTS_CSV="A2002,A2003"
fi

SUBJECTS=()
while IFS= read -r subject; do
  [[ -n "$subject" ]] && SUBJECTS+=("$subject")
done < <(python - <<'PY' "$SUBJECTS_CSV"
import sys

for raw in sys.argv[1].split(","):
    subject = raw.strip().removeprefix("sub-")
    if subject:
        print(subject)
PY
)
if [[ ${#SUBJECTS[@]} -eq 0 ]]; then
  echo "[assemble][error] No subjects resolved." >&2
  exit 1
fi

if [[ -z "$FMRIPREP_JOB_ID" ]]; then
  if [[ -f "$DRIVER_LOG" ]]; then
    FMRIPREP_JOB_ID="$(fmriprep_job_from_driver_log "$DRIVER_LOG" || true)"
  fi
  if [[ -z "$FMRIPREP_JOB_ID" && ! -f "$DRIVER_LOG" ]]; then
    FMRIPREP_JOB_ID="$(latest_fmriprep_job_id || true)"
  fi
fi
if [[ -z "$FMRI_JOB_ID" ]]; then
  if [[ -f "$DRIVER_LOG" ]]; then
    FMRI_JOB_ID="$(fmri_job_from_driver_log "$DRIVER_LOG" || true)"
    if [[ -z "$FMRI_JOB_ID" ]]; then
      FMRI_JOB_PENDING=1
    fi
  else
    FMRI_JOB_ID="$(latest_job_id_for_prefix "fmri_stages" || true)"
  fi
fi

if [[ -z "$DRIVER_JOB_ID" || -z "$FMRIPREP_JOB_ID" || ( -z "$FMRI_JOB_ID" && "$FMRI_JOB_PENDING" -eq 0 ) ]]; then
  echo "[assemble][error] Could not infer all job IDs from $SLURM_DIR." >&2
  echo "  driver=$DRIVER_JOB_ID fmriprep=$FMRIPREP_JOB_ID fmri=$FMRI_JOB_ID" >&2
  echo "  Pass --driver-job-id, --fmriprep-job-id, and --fmri-job-id explicitly, or wait for the driver log to contain the submitted job IDs." >&2
  exit 1
fi

if [[ "$FMRI_JOB_PENDING" -eq 1 ]]; then
  FMRI_JOB_ID="pending"
fi

SUBJECT_TOKEN="$(join_by_underscore "${SUBJECTS[@]}")"
PACKAGE_DATE="$(date +%Y%m%d)"
if [[ -z "$OUTPUT_DIR" ]]; then
  if [[ "$FMRI_JOB_PENDING" -eq 1 ]]; then
    OUTPUT_DIR="$REPO_ROOT/run_results_${SUBJECT_TOKEN}_${PACKAGE_DATE}_driver${DRIVER_JOB_ID}_pending"
  else
    OUTPUT_DIR="$REPO_ROOT/run_results_${SUBJECT_TOKEN}_${PACKAGE_DATE}_${FMRI_JOB_ID}"
  fi
  if [[ -e "$OUTPUT_DIR" || -e "${OUTPUT_DIR}.zip" ]]; then
    OUTPUT_DIR="${OUTPUT_DIR}_assembled_$(date +%H%M%S)"
  fi
else
  OUTPUT_DIR="$(python -c 'from pathlib import Path; import sys; print(Path(sys.argv[1]).expanduser().resolve())' "$OUTPUT_DIR")"
fi
ZIP_PATH="${OUTPUT_DIR}.zip"

echo "[assemble] repo=$REPO_ROOT"
echo "[assemble] config=$CONFIG_ABS"
echo "[assemble] derivatives_root=$DERIV_ROOT"
echo "[assemble] subjects=${SUBJECTS[*]}"
echo "[assemble] driver_job_id=$DRIVER_JOB_ID"
echo "[assemble] fmriprep_job_id=$FMRIPREP_JOB_ID"
echo "[assemble] fmri_job_id=$FMRI_JOB_ID"
if [[ -n "$DRIVER_LOG" ]]; then
  echo "[assemble] driver_log=$DRIVER_LOG"
fi
echo "[assemble] output_dir=$OUTPUT_DIR"
if [[ "$MAKE_ZIP" -eq 1 ]]; then
  echo "[assemble] zip=$ZIP_PATH"
fi

if [[ "$DRY_RUN" -eq 1 ]]; then
  if [[ "$FMRI_JOB_PENDING" -eq 1 ]]; then
    echo "[assemble] current driver has not submitted the matching fMRI-stage job yet; rerun after '[fmri-stages] submitted job id:' appears in the driver log."
  fi
  exit 0
fi

if [[ "$FMRI_JOB_PENDING" -eq 1 ]]; then
  echo "[assemble][error] Driver $DRIVER_JOB_ID has not submitted its matching fMRI-stage job yet." >&2
  echo "  Wait for '[fmri-stages] submitted job id:' in $DRIVER_LOG, then rerun this script." >&2
  exit 1
fi

if [[ -e "$OUTPUT_DIR" ]]; then
  echo "[assemble][error] Output directory already exists: $OUTPUT_DIR" >&2
  if [[ "$OUTPUT_DIR_GIVEN" -eq 1 ]]; then
    echo "  Explicit --output-dir paths never overwrite; choose a new path." >&2
  fi
  exit 1
fi
if [[ "$MAKE_ZIP" -eq 1 && -e "$ZIP_PATH" ]]; then
  echo "[assemble][error] Zip already exists: $ZIP_PATH" >&2
  if [[ "$OUTPUT_DIR_GIVEN" -eq 1 ]]; then
    echo "  Explicit --output-dir paths never overwrite; choose a new path." >&2
  fi
  exit 1
fi

copy_file_if_exists() {
  local src="$1"
  local dest_dir="$2"
  if [[ -f "$src" ]]; then
    cp -a "$src" "$dest_dir/"
  else
    echo "[assemble][warn] Missing file: $src" >&2
  fi
}

copy_dir_if_exists() {
  local src="$1"
  local dest_dir="$2"
  if [[ -d "$src" ]]; then
    cp -a "$src" "$dest_dir/"
  else
    echo "[assemble][warn] Missing directory: $src" >&2
  fi
}

mkdir -p \
  "$OUTPUT_DIR/checks" \
  "$OUTPUT_DIR/configs" \
  "$OUTPUT_DIR/fmriprep/logs" \
  "$OUTPUT_DIR/group" \
  "$OUTPUT_DIR/repo_reports" \
  "$OUTPUT_DIR/slurm" \
  "$OUTPUT_DIR/subjects"

copy_file_if_exists "$CONFIG_ABS" "$OUTPUT_DIR/configs"
for cfg in "$REPO_ROOT"/configs/palmetto_hpcnirc*.yaml; do
  [[ -e "$cfg" ]] && copy_file_if_exists "$cfg" "$OUTPUT_DIR/configs"
done

for subject in "${SUBJECTS[@]}"; do
  mkdir -p "$OUTPUT_DIR/subjects/$subject"
  copy_dir_if_exists "$DERIV_ROOT/$subject/m8_reports" "$OUTPUT_DIR/subjects/$subject"
  copy_dir_if_exists "$DERIV_ROOT/$subject/m9_orchestration" "$OUTPUT_DIR/subjects/$subject"
  copy_dir_if_exists "$DERIV_ROOT/$subject/m10_fmri" "$OUTPUT_DIR/subjects/$subject"
  copy_dir_if_exists "$DERIV_ROOT/$subject/m12_wave_validation" "$OUTPUT_DIR/subjects/$subject"
  copy_dir_if_exists "$DERIV_ROOT/sub-$subject/audit" "$OUTPUT_DIR/subjects/$subject"
done

copy_file_if_exists "$DERIV_ROOT/group_aim2_summary.html" "$OUTPUT_DIR/group"
copy_file_if_exists "$DERIV_ROOT/group_summary.json" "$OUTPUT_DIR/group"
copy_file_if_exists "$DERIV_ROOT/group_trials.csv" "$OUTPUT_DIR/group"

copy_file_if_exists "$REPO_ROOT/reports/aim3_null_summary.json" "$OUTPUT_DIR/repo_reports"
copy_file_if_exists "$REPO_ROOT/reports/aim3_null_summary.md" "$OUTPUT_DIR/repo_reports"

copy_file_if_exists "$FMRIPREP_ROOT/dataset_description.json" "$OUTPUT_DIR/fmriprep"
for citation in "$FMRIPREP_ROOT"/logs/CITATION.*; do
  [[ -e "$citation" ]] && copy_file_if_exists "$citation" "$OUTPUT_DIR/fmriprep/logs"
done
for subject in "${SUBJECTS[@]}"; do
  mkdir -p "$OUTPUT_DIR/fmriprep/sub-$subject"
  copy_file_if_exists "$FMRIPREP_ROOT/sub-$subject.html" "$OUTPUT_DIR/fmriprep"
  copy_dir_if_exists "$FMRIPREP_ROOT/sub-$subject/figures" "$OUTPUT_DIR/fmriprep/sub-$subject"
done

copy_file_if_exists "$SLURM_DIR/mous_driver_${DRIVER_JOB_ID}.out" "$OUTPUT_DIR/slurm"
copy_file_if_exists "$SLURM_DIR/mous_driver_${DRIVER_JOB_ID}.err" "$OUTPUT_DIR/slurm"
copy_file_if_exists "$SLURM_DIR/fmri_stages_${FMRI_JOB_ID}.out" "$OUTPUT_DIR/slurm"
copy_file_if_exists "$SLURM_DIR/fmri_stages_${FMRI_JOB_ID}.err" "$OUTPUT_DIR/slurm"
for idx in "${!SUBJECTS[@]}"; do
  copy_file_if_exists "$SLURM_DIR/fmriprep_${FMRIPREP_JOB_ID}_${idx}.out" "$OUTPUT_DIR/slurm"
  copy_file_if_exists "$SLURM_DIR/fmriprep_${FMRIPREP_JOB_ID}_${idx}.err" "$OUTPUT_DIR/slurm"
done

FMRIPREP_SUBMIT_LOG="$(grep -Rsl "Submitted batch job ${FMRIPREP_JOB_ID}" "$SLURM_DIR"/fmriprep_submit_*.log 2>/dev/null | sort | tail -1 || true)"
if [[ -n "$FMRIPREP_SUBMIT_LOG" ]]; then
  copy_file_if_exists "$FMRIPREP_SUBMIT_LOG" "$OUTPUT_DIR/slurm"
else
  echo "[assemble][warn] Could not find fMRIPrep submit log for job $FMRIPREP_JOB_ID" >&2
fi
FMRIPREP_SUBJECTS_FILE="$(find "$SLURM_DIR" -maxdepth 1 -type f -name 'fmriprep_subjects_*.txt' -printf '%T@ %p\n' 2>/dev/null \
  | sort -n \
  | tail -1 \
  | cut -d' ' -f2-)"
if [[ -n "$FMRIPREP_SUBJECTS_FILE" ]]; then
  copy_file_if_exists "$FMRIPREP_SUBJECTS_FILE" "$OUTPUT_DIR/slurm"
else
  echo "[assemble][warn] Could not find latest fMRIPrep subjects file." >&2
fi

MPLCONFIGDIR="${MPLCONFIGDIR:-/tmp/mous_mplconfig_assemble_${USER:-user}_$$}"
mkdir -p "$MPLCONFIGDIR"
if [[ "$SKIP_VERIFY" -eq 0 ]]; then
  if ! command -v mous-pipeline >/dev/null 2>&1; then
    echo "[assemble][error] mous-pipeline is not on PATH; use --skip-verify to package without verification." >&2
    exit 1
  fi
  for subject in "${SUBJECTS[@]}"; do
    MPLCONFIGDIR="$MPLCONFIGDIR" mous-pipeline verify-run \
      --config "$CONFIG_ABS" \
      --subject "$subject" \
      --strict-mode \
      > "$OUTPUT_DIR/checks/verify_${subject}.txt" 2>&1
  done
else
  echo "Verification skipped by --skip-verify." > "$OUTPUT_DIR/checks/verify_skipped.txt"
fi

python - <<'PY' "$OUTPUT_DIR" "${SUBJECTS[@]}"
import json
import sys
from pathlib import Path

out_dir = Path(sys.argv[1])
subjects = sys.argv[2:]
summary = []
for subject in subjects:
    manifest = out_dir / "subjects" / subject / "m9_orchestration" / f"sub-{subject}_run_manifest.json"
    data = json.loads(manifest.read_text())
    metrics = data.get("metrics", {})
    coupling = metrics.get("m11_coupling", {})
    summary.append(
        {
            "subject": data.get("subject", subject),
            "timestamp_utc": data.get("timestamp_utc"),
            "run_status": metrics.get("run_status"),
            "selected_stages": metrics.get("selected_stages"),
            "skipped_stages": metrics.get("skipped_stages"),
            "n_trials": metrics.get("n_trials"),
            "n_zinnen": metrics.get("n_zinnen"),
            "n_woorden": metrics.get("n_woorden"),
            "n_rest": metrics.get("n_rest"),
            "dci": {
                "zinnen": metrics.get("dci_zinnen"),
                "woorden": metrics.get("dci_woorden"),
                "rest": metrics.get("dci_rest"),
            },
            "m10_n_trials_joined": metrics.get("m10_n_trials_joined"),
            "m11_features_used": coupling.get("features_used"),
            "m11_lme_like": coupling.get("lme_like"),
            "m11_primary": {
                "feature": coupling.get("m11_primary_feature"),
                "r": coupling.get("m11_primary_r"),
                "p_fdr": coupling.get("m11_primary_p_fdr"),
            },
            "m12_null_summary": metrics.get("m12_null_summary"),
        }
    )
(out_dir / "checks" / "manifest_summary.json").write_text(json.dumps(summary, indent=2) + "\n")
PY

if command -v sacct >/dev/null 2>&1; then
  if ! sacct -j "${DRIVER_JOB_ID},${FMRIPREP_JOB_ID},${FMRI_JOB_ID}" \
    --format JobID,JobName,State,ExitCode,Elapsed,MaxRSS \
    --parsable2 > "$OUTPUT_DIR/checks/slurm_accounting.txt" 2>&1; then
    echo "[assemble][warn] sacct query failed; see checks/slurm_accounting.txt" >&2
  fi
else
  echo "sacct not found on PATH." > "$OUTPUT_DIR/checks/slurm_accounting.txt"
fi

python - <<'PY' "$OUTPUT_DIR" "$CONFIG_ABS" "$DERIV_ROOT" "$DRIVER_JOB_ID" "$FMRIPREP_JOB_ID" "$FMRI_JOB_ID" "$(git -C "$REPO_ROOT" branch --show-current 2>/dev/null || true)" "$(git -C "$REPO_ROOT" rev-parse --short HEAD 2>/dev/null || true)"
import json
import sys
from datetime import datetime
from pathlib import Path

out_dir = Path(sys.argv[1])
config = sys.argv[2]
deriv_root = sys.argv[3]
driver_job = sys.argv[4]
fmriprep_job = sys.argv[5]
fmri_job = sys.argv[6]
branch = sys.argv[7] or "unknown"
commit = sys.argv[8] or "unknown"
subjects = json.loads((out_dir / "checks" / "manifest_summary.json").read_text())
group_path = out_dir / "group" / "group_summary.json"
group = json.loads(group_path.read_text()) if group_path.exists() else {}
project_warning = any("/project/jonathanwade" in p.read_text(errors="ignore") for p in (out_dir / "slurm").glob("*.err"))

lines = [
    "# MOUS Run Results: " + "/".join(item["subject"] for item in subjects),
    "",
    f"Collected by `scripts/assemble_a2002_a2003_results.sh` on {datetime.now().strftime('%Y-%m-%d %H:%M:%S %Z')}.",
    "",
    "## Run IDs",
    "",
    f"- Driver: `{driver_job}` (`mous_driver`)",
    f"- fMRIPrep array: `{fmriprep_job}` (`mous_fmriprep`)",
    f"- fMRI stages: `{fmri_job}` (`mous_fmri_stages`)",
    f"- Config snapshot source: `{config}`",
    f"- Derivatives root: `{deriv_root}`",
    f"- Git branch at packaging: `{branch}`",
    f"- Git commit at packaging: `{commit}`",
    "",
    "## Verification Summary",
    "",
    "- Strict verification outputs are in `checks/verify_<subject>.txt`.",
    "- Slurm accounting, when available, is in `checks/slurm_accounting.txt`.",
    "- Manifest summary is in `checks/manifest_summary.json`.",
]
if project_warning:
    lines.append("- Copied stderr logs contain `/project/jonathanwade` bind warnings; inspect `slurm/` logs.")
else:
    lines.append("- No `/project/jonathanwade` bind warnings were found in copied stderr logs.")

lines += ["", "## Subject Results", ""]
for item in subjects:
    subject = item["subject"]
    lme = item.get("m11_lme_like") or {}
    dci = item.get("dci") or {}
    null = item.get("m12_null_summary") or {}
    lines += [
        f"### {subject}",
        "",
        f"- Final manifest: `subjects/{subject}/m9_orchestration/sub-{subject}_run_manifest.json`",
        f"- Run status: `{item.get('run_status')}`",
        f"- Joined fMRI/MEG trial rows: `{item.get('m10_n_trials_joined')}`",
        f"- m11 features used: `{', '.join(item.get('m11_features_used') or [])}`",
        f"- m11 LME-like `p_prestim_beta`: `{lme.get('p_prestim_beta')}`",
        f"- m11 LME-like `p_n400m`: `{lme.get('p_n400m')}`",
        f"- m11 LME-like `p_dci_trial`: `{lme.get('p_dci_trial')}`",
        f"- DCI zinnen/woorden/rest: `{dci.get('zinnen')}`, `{dci.get('woorden')}`, `{dci.get('rest')}`",
        f"- Aim 3 null z: `{null.get('z')}`",
        "",
    ]

pooled = (((group.get("metrics") or {}).get("m11_coupling") or {}).get("pooled_ols") or {})
m12_group = ((group.get("metrics") or {}).get("m12_wave_validation_z") or {})
lines += [
    "## Group Results",
    "",
    f"- Subjects: `{group.get('n_subjects')}`",
    f"- Pilot verdicts: `{group.get('pilot_verdicts')}`",
    f"- Pooled OLS rows: `{pooled.get('n_trials')}`",
    f"- Pooled OLS R2: `{pooled.get('r2')}`",
    f"- Pooled OLS `p_prestim_beta`: `{pooled.get('p_prestim_beta')}`",
    f"- Pooled OLS `p_n400m`: `{pooled.get('p_n400m')}`",
    f"- Pooled OLS `p_dci_trial`: `{pooled.get('p_dci_trial')}`",
    f"- Mean Aim 3 null z: `{m12_group.get('mean')}`",
    "",
    "## Included Artifacts",
    "",
    "- `subjects/*/audit/`: Aim 1 audit summaries and quicklooks.",
    "- `subjects/*/m8_reports/`: subject HTML reports and exported CSV/JSON tables.",
    "- `subjects/*/m9_orchestration/`: final run manifests, run states, live logs, and DCI/phase artifacts.",
    "- `subjects/*/m10_fmri/`: hydrated joined trial CSVs.",
    "- `subjects/*/m12_wave_validation/`: Aim 3 null DCI arrays.",
    "- `group/`: group HTML, group summary JSON, and group trial CSV.",
    "- `fmriprep/`: fMRIPrep subject HTML reports, citation files, and report figures.",
    "- `slurm/`: matching driver, fMRIPrep, fMRI-stage, subject-list, and submit logs.",
    "- `configs/`: run config snapshots copied from the repo.",
    "- `repo_reports/`: Aim 3 null summary artifacts written under repo `reports/`.",
    "- `checks/`: strict verification output, Slurm accounting, and manifest summary.",
    "",
    "Large intermediate caches, NIfTI outputs, and fMRIPrep work directories were intentionally not copied.",
]
(out_dir / "README.md").write_text("\n".join(lines) + "\n")

verification_lines = [
    "# Pipeline Verification Notes",
    "",
    "## Commands Run",
    "",
    "```bash",
]
for item in subjects:
    verification_lines.append(
        f"MPLCONFIGDIR=$MPLCONFIGDIR mous-pipeline verify-run --config {config} --subject {item['subject']} --strict-mode"
    )
verification_lines += [
    f"sacct -j {driver_job},{fmriprep_job},{fmri_job} --format JobID,JobName,State,ExitCode,Elapsed,MaxRSS --parsable2",
    "```",
    "",
    "## Results",
    "",
]
for item in subjects:
    verification_lines.append(f"- {item['subject']} strict verification: see `verify_{item['subject']}.txt`.")
verification_lines += [
    "- Slurm accounting: see `slurm_accounting.txt`.",
    "- Manifest summary: see `manifest_summary.json`.",
]
(out_dir / "checks" / "pipeline_verification.md").write_text("\n".join(verification_lines) + "\n")
PY

if [[ "$MAKE_ZIP" -eq 1 ]]; then
  if ! command -v zip >/dev/null 2>&1; then
    echo "[assemble][error] zip is not on PATH." >&2
    exit 1
  fi
  (
    cd "$(dirname "$OUTPUT_DIR")"
    zip -r -q "$(basename "$ZIP_PATH")" "$(basename "$OUTPUT_DIR")"
  )
  unzip -t "$ZIP_PATH" >/dev/null
  echo "[assemble][done] Wrote $(du -h "$ZIP_PATH" | awk '{print $1}') zip: $ZIP_PATH"
else
  echo "[assemble][done] Wrote bundle directory: $OUTPUT_DIR"
fi
