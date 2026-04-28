#!/usr/bin/env bash
set -euo pipefail

usage() {
  cat <<'EOF'
One-time setup for Clemson Palmetto (hpcnirc-friendly defaults).

Environment overrides:
  MOUS_PYTHON_MODULE      Optional module to load before venv creation.
  MOUS_APPTAINER_MODULE   Optional module to load for apptainer.
  MOUS_FREESURFER_MODULE  Optional module to load for recon-all.
  MOUS_FREESURFER_LICENSE Optional path to FreeSurfer license.txt.
  MOUS_VENV_PATH          Virtualenv path (default: .venv-palmetto).
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

if [[ -n "${MOUS_PYTHON_MODULE:-}" ]]; then
  module load "$MOUS_PYTHON_MODULE"
fi
if [[ -n "${MOUS_APPTAINER_MODULE:-}" ]]; then
  module load "$MOUS_APPTAINER_MODULE"
fi
if [[ -n "${MOUS_FREESURFER_MODULE:-}" ]]; then
  if ! module load "$MOUS_FREESURFER_MODULE" >/dev/null 2>&1; then
    module load neurocommand >/dev/null 2>&1 || true
    module load "$MOUS_FREESURFER_MODULE"
  fi
fi

PYTHON_BIN="$(command -v python3 || true)"
if [[ -z "$PYTHON_BIN" ]]; then
  echo "python3 not found. Load a Python module first (MOUS_PYTHON_MODULE)." >&2
  exit 1
fi

VENV_PATH="${MOUS_VENV_PATH:-$ROOT_DIR/.venv-palmetto}"
INSTALL_EXTRAS="${MOUS_INSTALL_EXTRAS:-[fmri,bids]}"
CONTAINER_DIR="${MOUS_CONTAINER_DIR:-$HOME/containers}"
PULL_FMRIPREP="${MOUS_PULL_FMRIPREP:-0}"
FMRIPREP_REF="${MOUS_FMRIPREP_REF:-docker://nipreps/fmriprep:24.0.1}"
FREESURFER_LICENSE="${MOUS_FREESURFER_LICENSE:-}"

if [[ ! -d "$VENV_PATH" ]]; then
  "$PYTHON_BIN" -m venv "$VENV_PATH"
fi
source "$VENV_PATH/bin/activate"
python -m pip install --upgrade pip
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
echo "  python: $PYTHON_BIN"
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
echo "  source \"$VENV_PATH/bin/activate\""
echo "Suggested smoke test:"
echo "  mous-pipeline --help"
echo ""
echo "If you pulled an image, set in config:"
echo "  fmri.fmriprep_container: \"$CONTAINER_DIR/fmriprep.sif\""
