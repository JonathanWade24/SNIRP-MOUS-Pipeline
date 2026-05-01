# MOUS Palmetto shell helpers.
# Safe to track in a personal dotfiles repo; do not add secrets here.

path_prepend_once() {
  if [ -n "${1:-}" ] && [ -d "$1" ]; then
    case ":$PATH:" in
      *":$1:"*) ;;
      *) PATH="$1:$PATH" ;;
    esac
  fi
}

path_remove_once() {
  if [ -n "${1:-}" ]; then
    while [ "$PATH" != "${PATH#"$1:"}" ]; do
      PATH="${PATH#"$1:"}"
    done
    PATH="${PATH//:"$1":/:}"
    PATH="${PATH%:"$1"}"
  fi
}

export MOUS_REPO="${MOUS_REPO:-/scratch/jonathanwade/MOUS}"
export MOUS_VENV_PATH="${MOUS_VENV_PATH:-$HOME/.venvs/mous-palmetto}"
export MOUS_CONTAINER_DIR="${MOUS_CONTAINER_DIR:-/scratch/jonathanwade/containers}"
export MOUS_PARTITION="${MOUS_PARTITION:-hpcnirc}"

if [ -z "${MPLCONFIGDIR:-}" ]; then
  _mous_mpl_base="${TMPDIR:-/tmp}"
  export MPLCONFIGDIR="${_mous_mpl_base%/}/mous-matplotlib-${USER:-user}"
  mkdir -p "$MPLCONFIGDIR" 2>/dev/null || true
  unset _mous_mpl_base
fi

path_remove_once "/scratch/jonathanwade/neurodesk"
path_remove_once "/scratch/jonathanwade/neurocommand/neurodesk"
path_remove_once "/scratch/jonathanwade/neurocommand/local"
export PATH

cdmous() {
  cd "$MOUS_REPO" || return
}

mousenv() {
  if [ -f "$MOUS_VENV_PATH/bin/activate" ]; then
    . "$MOUS_VENV_PATH/bin/activate"
  else
    echo "Missing MOUS venv: $MOUS_VENV_PATH" >&2
    return 1
  fi
}

mousq() {
  squeue -u "$USER" "$@"
}

mousstat() {
  git -C "$MOUS_REPO" status --short --branch "$@"
}
