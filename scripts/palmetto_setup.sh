#!/usr/bin/env bash
set -euo pipefail

usage() {
  cat <<'EOF'
One-time setup for Clemson Palmetto (hpcnirc-friendly defaults).

Environment overrides:
  MOUS_CONDA_MODULE       Conda module to load (default: miniforge3/24.3.0-0).
  MOUS_APPTAINER_MODULE   Optional module to load for apptainer.
  MOUS_FREESURFER_MODULE  Optional module to load for recon-all.
  MOUS_FREESURFER_LICENSE Optional path to FreeSurfer license.txt.
  MOUS_CONDA_ENV_NAME     Conda environment name (default: mous-palmetto).
  MOUS_CONDA_ENV_FILE     Conda environment.yml path (default: $ROOT_DIR/environment.yml).
  MOUS_INSTALL_EXTRAS     Editable extras (default: [fmri,bids]).
  MOUS_CONTAINER_DIR      Directory for SIF images (default: $HOME/containers).
  MOUS_PULL_FMRIPREP      1 to pull image, 0 to skip (default: 0).
  MOUS_FMRIPREP_REF       Image reference for apptainer pull
                          (default: docker://nipreps/fmriprep:24.0.1)
EOF
}

if [[ "${1:-}" == "-h" || "${1:-}" == "--help" ]]; then
  usage
  exit 0
fi

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT_DIR"

CONDA_MODULE="${MOUS_CONDA_MODULE:-miniforge3/24.3.0-0}"
module load "$CONDA_MODULE"
if [[ -n "${MOUS_APPTAINER_MODULE:-}" ]]; then
  module load "$MOUS_APPTAINER_MODULE"
fi
if [[ -n "${MOUS_FREESURFER_MODULE:-}" ]]; then
  if ! module load "$MOUS_FREESURFER_MODULE" >/dev/null 2>&1; then
    module load neurocommand >/dev/null 2>&1 || true
    module load "$MOUS_FREESURFER_MODULE"
  fi
fi

CONDA_BIN="$(command -v conda || true)"
MAMBA_BIN="$(command -v mamba || true)"
if [[ -z "$CONDA_BIN" ]]; then
  echo "conda not found after module load ($CONDA_MODULE)." >&2
  exit 1
fi

CONDA_ENV_NAME="${MOUS_CONDA_ENV_NAME:-mous-palmetto}"
CONDA_ENV_FILE="${MOUS_CONDA_ENV_FILE:-$ROOT_DIR/environment.yml}"
INSTALL_EXTRAS="${MOUS_INSTALL_EXTRAS:-[fmri,bids]}"
CONTAINER_DIR="${MOUS_CONTAINER_DIR:-$HOME/containers}"
PULL_FMRIPREP="${MOUS_PULL_FMRIPREP:-0}"
FMRIPREP_REF="${MOUS_FMRIPREP_REF:-docker://nipreps/fmriprep:24.0.1}"
FREESURFER_LICENSE="${MOUS_FREESURFER_LICENSE:-}"

if [[ ! -f "$CONDA_ENV_FILE" ]]; then
  echo "Conda environment file not found: $CONDA_ENV_FILE" >&2
  exit 1
fi

eval "$("$CONDA_BIN" shell.bash hook)"
if conda env list | awk -v target="$CONDA_ENV_NAME" '($1 !~ /^#/ && $1 == target) {found=1} END {exit(found ? 0 : 1)}'; then
  if [[ -n "$MAMBA_BIN" ]]; then
    "$MAMBA_BIN" env update -n "$CONDA_ENV_NAME" -f "$CONDA_ENV_FILE" --prune
  else
    "$CONDA_BIN" env update -n "$CONDA_ENV_NAME" -f "$CONDA_ENV_FILE" --prune
  fi
else
  if [[ -n "$MAMBA_BIN" ]]; then
    "$MAMBA_BIN" env create -n "$CONDA_ENV_NAME" -f "$CONDA_ENV_FILE"
  else
    "$CONDA_BIN" env create -n "$CONDA_ENV_NAME" -f "$CONDA_ENV_FILE"
  fi
fi

conda activate "$CONDA_ENV_NAME"
python -m pip install -e ".${INSTALL_EXTRAS}"

if [[ "$PULL_FMRIPREP" == "1" ]]; then
  if ! command -v apptainer >/dev/null 2>&1 && ! command -v singularity >/dev/null 2>&1; then
    echo "apptainer/singularity not found. Load a container module before pulling images." >&2
    exit 1
  fi
  mkdir -p "$CONTAINER_DIR"
  APPTAINER_BIN="$(command -v apptainer || command -v singularity)"
  "$APPTAINER_BIN" pull "$CONTAINER_DIR/fmriprep.sif" "$FMRIPREP_REF"
fi

echo ""
echo "Palmetto setup complete."
echo "Status:"
echo "  conda_module: $CONDA_MODULE"
echo "  conda_env: $CONDA_ENV_NAME"
echo "  python: $(command -v python)"
if command -v apptainer >/dev/null 2>&1; then
  echo "  container_runtime: apptainer ($(command -v apptainer))"
elif command -v singularity >/dev/null 2>&1; then
  echo "  container_runtime: singularity ($(command -v singularity))"
else
  echo "  container_runtime: not found (load module if needed)"
fi
if command -v recon-all >/dev/null 2>&1; then
  echo "  freesurfer: recon-all available ($(command -v recon-all))"
else
  echo "  freesurfer: recon-all not found (optional; load MOUS_FREESURFER_MODULE when enabling m5)"
fi
if [[ -n "$FREESURFER_LICENSE" ]]; then
  if [[ -f "$FREESURFER_LICENSE" ]]; then
    echo "  freesurfer_license: $FREESURFER_LICENSE"
  else
    echo "  freesurfer_license: path not found -> $FREESURFER_LICENSE"
  fi
fi
echo "Activate env:"
echo "  module load \"$CONDA_MODULE\""
echo "  eval \"\$(conda shell.bash hook)\""
echo "  conda activate \"$CONDA_ENV_NAME\""
echo "Suggested smoke test:"
echo "  mous-pipeline --help"
echo ""
echo "If you pulled an image, set in config:"
echo "  fmri.fmriprep_container: \"$CONTAINER_DIR/fmriprep.sif\""
