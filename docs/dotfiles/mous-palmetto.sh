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

# Pull the latest HPC deploy branch into the cluster working tree.
# Aborts if the working tree is dirty unless --force is passed.
# Usage: mousupdate [--force]
mousupdate() {
  local force=0
  [[ "${1:-}" == "--force" ]] && force=1

  local _dirty
  _dirty="$(git -C "$MOUS_REPO" status --porcelain 2>/dev/null)"
  if [[ -n "$_dirty" && "$force" -eq 0 ]]; then
    echo "[mous] ERROR: working tree is dirty. Stash or commit first, or run: mousupdate --force" >&2
    git -C "$MOUS_REPO" status --short >&2
    return 1
  fi

  git -C "$MOUS_REPO" fetch origin
  git -C "$MOUS_REPO" reset --hard origin/HPC
  echo "[mous] cluster repo now at: $(git -C "$MOUS_REPO" log -1 --oneline)"
}

# Promote main → HPC deploy branch and push.
# Fetches first and verifies local main matches origin/main before promoting.
# Always returns to the original branch, even on failure.
# Run after merging a PR to main.
mousdeploy() {
  local _prev _rc=0
  _prev="$(git -C "$MOUS_REPO" symbolic-ref --short HEAD 2>/dev/null || echo "(detached)")"

  git -C "$MOUS_REPO" fetch origin || { echo "[mous] ERROR: fetch failed" >&2; return 1; }

  local _local_main _remote_main
  _local_main="$(git -C "$MOUS_REPO" rev-parse main 2>/dev/null)" \
    || { echo "[mous] ERROR: branch 'main' not found locally" >&2; return 1; }
  _remote_main="$(git -C "$MOUS_REPO" rev-parse origin/main 2>/dev/null)" \
    || { echo "[mous] ERROR: origin/main not found" >&2; return 1; }

  if [[ "$_local_main" != "$_remote_main" ]]; then
    echo "[mous] ERROR: local main is not in sync with origin/main." >&2
    echo "[mous]   local:  $_local_main" >&2
    echo "[mous]   remote: $_remote_main" >&2
    echo "[mous] Run: git -C \$MOUS_REPO pull --ff-only origin main" >&2
    return 1
  fi

  git -C "$MOUS_REPO" switch HPC \
    && git -C "$MOUS_REPO" merge --ff-only main \
    && git -C "$MOUS_REPO" push origin HPC \
    || _rc=$?

  git -C "$MOUS_REPO" switch "$_prev"

  if [[ "$_rc" -eq 0 ]]; then
    echo "[mous] HPC branch promoted: $(git -C "$MOUS_REPO" log -1 --oneline origin/HPC)"
  else
    echo "[mous] ERROR: deploy failed (rc=$_rc); returned to '$_prev'" >&2
    return "$_rc"
  fi
}
