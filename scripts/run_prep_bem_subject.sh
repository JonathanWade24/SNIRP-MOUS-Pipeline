#!/usr/bin/env bash
set -euo pipefail

usage() {
  cat <<'EOF'
Usage:
  run_prep_bem_subject.sh --subjects-file <path> --subjects-dir <path>

Environment:
  SLURM_ARRAY_TASK_ID       0-based index into subjects-file lines.
  MOUS_FREESURFER_MODULE    Optional module to load before BEM prep.
  MOUS_FREESURFER_CONTAINER Optional apptainer/singularity image that has MNE.
  MOUS_FREESURFER_LICENSE   Optional FreeSurfer license path to use for BEM prep.
  MOUS_VENV_PATH            Optional venv to activate before running mne.
EOF
}

SUBJECTS_FILE=""
SUBJECTS_DIR=""

while [[ $# -gt 0 ]]; do
  case "$1" in
    --subjects-file) SUBJECTS_FILE="${2:-}"; shift 2 ;;
    --subjects-dir) SUBJECTS_DIR="${2:-}"; shift 2 ;;
    -h|--help) usage; exit 0 ;;
    *) echo "Unknown argument: $1" >&2; usage >&2; exit 2 ;;
  esac
done

if [[ -z "$SUBJECTS_FILE" || -z "$SUBJECTS_DIR" ]]; then
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

if [[ -n "${MOUS_FREESURFER_MODULE:-}" ]] && command -v module >/dev/null 2>&1; then
  if ! module load "$MOUS_FREESURFER_MODULE" >/dev/null 2>&1; then
    module load neurocommand >/dev/null 2>&1 || true
    module load "$MOUS_FREESURFER_MODULE"
  fi
fi

if [[ -n "${MOUS_VENV_PATH:-}" ]]; then
  VENV_ACTIVATE="$(python - <<'PY' "$MOUS_VENV_PATH"
from pathlib import Path
import sys
print((Path(sys.argv[1]).expanduser() / "bin" / "activate").as_posix())
PY
)"
  if [[ -f "$VENV_ACTIVATE" ]]; then
    # shellcheck disable=SC1090
    source "$VENV_ACTIVATE"
  fi
fi

if [[ -n "${MOUS_FREESURFER_LICENSE:-}" ]]; then
  FS_LICENSE="$(python - <<'PY' "$MOUS_FREESURFER_LICENSE"
from pathlib import Path
import sys
print(Path(sys.argv[1]).expanduser().resolve())
PY
)"
  export FS_LICENSE
  if [[ ! -f "$FS_LICENSE" ]]; then
    echo "[bem] ERROR: FreeSurfer license not found at FS_LICENSE=$FS_LICENSE" >&2
    exit 1
  fi
fi

LINE_NO=$((SLURM_ARRAY_TASK_ID + 1))
SUBJECT="$(sed -n "${LINE_NO}p" "$SUBJECTS_FILE" | tr -d '[:space:]')"
if [[ -z "$SUBJECT" ]]; then
  echo "No subject resolved for SLURM_ARRAY_TASK_ID=$SLURM_ARRAY_TASK_ID" >&2
  exit 1
fi
SUBJECT="sub-${SUBJECT#sub-}"

INNER="$SUBJECTS_DIR/$SUBJECT/bem/inner_skull.surf"
OUTER_SKULL="$SUBJECTS_DIR/$SUBJECT/bem/outer_skull.surf"
OUTER_SKIN="$SUBJECTS_DIR/$SUBJECT/bem/outer_skin.surf"

if [[ -f "$INNER" && -f "$OUTER_SKULL" && -f "$OUTER_SKIN" ]]; then
  echo "[bem] skip subject=$SUBJECT reason=already_present inner_skull.surf/outer_skull.surf/outer_skin.surf"
  exit 0
fi

echo "[bem] host=$(hostname) job_id=${SLURM_JOB_ID:-na} task_id=${SLURM_ARRAY_TASK_ID:-na}"
echo "[bem] subject=$SUBJECT subjects_dir=$SUBJECTS_DIR"

BEM_DIR="$SUBJECTS_DIR/$SUBJECT/bem"
WS_DIR="$BEM_DIR/watershed"
T1_MGZ="$SUBJECTS_DIR/$SUBJECT/mri/T1.mgz"
mkdir -p "$WS_DIR"

if [[ ! -f "$T1_MGZ" ]]; then
  echo "[bem] ERROR: T1.mgz not found at $T1_MGZ — has recon-all finished for $SUBJECT?" >&2
  exit 1
fi

if [[ -n "${MOUS_FREESURFER_CONTAINER:-}" ]]; then
  APPTAINER_BIN="$(command -v apptainer || command -v singularity || true)"
  if [[ -z "$APPTAINER_BIN" ]]; then
    echo "apptainer/singularity not found for containerized BEM prep." >&2
    exit 1
  fi
  echo "[bem] running mri_watershed inside container=$MOUS_FREESURFER_CONTAINER"
  APPTAINER_BIND_ARGS=(-B "$SUBJECTS_DIR:$SUBJECTS_DIR")
  APPTAINER_ENV_ARGS=(
    --env "FREESURFER_HOME=/opt/freesurfer"
    --env "SUBJECTS_DIR=$SUBJECTS_DIR"
  )
  if [[ -n "${FS_LICENSE:-}" ]]; then
    FS_LICENSE_DIR="$(dirname "$FS_LICENSE")"
    APPTAINER_BIND_ARGS+=(-B "$FS_LICENSE_DIR:$FS_LICENSE_DIR")
    APPTAINER_ENV_ARGS+=(--env "FS_LICENSE=$FS_LICENSE")
  fi
  # Run mri_watershed directly; fMRIPrep container has FreeSurfer at /opt/freesurfer.
  # Syntax: mri_watershed [opts] -surf <prefix> <invol> <outvol>
  "$APPTAINER_BIN" exec \
    "${APPTAINER_BIND_ARGS[@]}" \
    "${APPTAINER_ENV_ARGS[@]}" \
    "${MOUS_FREESURFER_CONTAINER}" \
    bash -c "
      export FREESURFER_HOME=/opt/freesurfer
      export PATH=\"/opt/freesurfer/bin:\$PATH\"
      mri_watershed -useSRAS -surf '${WS_DIR}/${SUBJECT}' '${T1_MGZ}' '${WS_DIR}/ws.mgz'
    "
  # Rename watershed outputs to MNE-expected BEM surface names.
  python - <<PY
from pathlib import Path
import shutil

subj = "${SUBJECT}"
ws = Path("${WS_DIR}")
bem = Path("${BEM_DIR}")
mapping = [
    ([f"{subj}_inner_skull_surface", f"{subj}__inner_skull_surface"], "inner_skull.surf"),
    ([f"{subj}_outer_skull_surface", f"{subj}__outer_skull_surface"], "outer_skull.surf"),
    ([f"{subj}_outer_skin_surface", f"{subj}__outer_skin_surface"], "outer_skin.surf"),
]
for src_names, dst_name in mapping:
    dst = bem / dst_name
    for src_name in src_names:
        src = ws / src_name
        if src.exists():
            shutil.copy2(src, dst)
            print(f"[bem] renamed {src_name} -> {dst_name}")
            break
    else:
        print(f"[bem] WARNING: expected watershed output not found for {dst_name}: {src_names}")
PY
else
  # No container: rely on module-loaded FreeSurfer + venv mne.
  if [[ -n "${FS_LICENSE:-}" && ! -f "$FS_LICENSE" ]]; then
    echo "[bem] ERROR: FreeSurfer license not found at FS_LICENSE=$FS_LICENSE" >&2
    exit 1
  fi
  if ! command -v mri_watershed >/dev/null 2>&1; then
    echo "[bem] ERROR: mri_watershed not found and MOUS_FREESURFER_CONTAINER is not set." >&2
    echo "  Fix: set MOUS_FREESURFER_CONTAINER to your fMRIPrep/FreeSurfer .sif path, or load a FreeSurfer module." >&2
    exit 1
  fi
  echo "[bem] running mri_watershed from host PATH"
  mri_watershed -useSRAS -surf "${WS_DIR}/${SUBJECT}" "${T1_MGZ}" "${WS_DIR}/ws.mgz"
  python - <<PY
from pathlib import Path
import shutil

subj = "${SUBJECT}"
ws = Path("${WS_DIR}")
bem = Path("${BEM_DIR}")
mapping = [
    ([f"{subj}_inner_skull_surface", f"{subj}__inner_skull_surface"], "inner_skull.surf"),
    ([f"{subj}_outer_skull_surface", f"{subj}__outer_skull_surface"], "outer_skull.surf"),
    ([f"{subj}_outer_skin_surface", f"{subj}__outer_skin_surface"], "outer_skin.surf"),
]
for src_names, dst_name in mapping:
    dst = bem / dst_name
    for src_name in src_names:
        src = ws / src_name
        if src.exists():
            shutil.copy2(src, dst)
            print(f"[bem] renamed {src_name} -> {dst_name}")
            break
    else:
        print(f"[bem] WARNING: expected watershed output not found for {dst_name}: {src_names}")
PY
fi

if [[ ! -f "$INNER" ]]; then
  echo "[bem] ERROR: inner_skull.surf still missing after BEM prep for $SUBJECT" >&2
  exit 1
fi
echo "[bem] done subject=$SUBJECT"
