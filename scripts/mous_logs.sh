#!/bin/bash
# mous_logs.sh — interactively browse MOUS SLURM run logs
#
# Usage:
#   bash scripts/mous_logs.sh           # show last 3 runs, pick one, pick subject
#   bash scripts/mous_logs.sh <jobid>   # jump straight to a specific job ID
#
# Subjects are read from configs/cohort_15subjects_fmri.yaml (no hardcoding).
# Task-index→subject mapping is derived from the log filenames themselves, so
# partial-array retry jobs (e.g. --array=7) display correctly.

set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
LOGS_DIR="${LOGS_DIR:-${REPO_ROOT}/logs}"
CONFIG="${MOUS_CONFIG:-${REPO_ROOT}/configs/cohort_15subjects_fmri.yaml}"

# ── Read cohort subjects from YAML (no hardcoded list) ───────────────────────
# Extracts lines like `  - "A2002"` or `  - A2002` from the subjects block.
_read_subjects_from_config() {
  local in_subjects=0
  while IFS= read -r line; do
    if [[ "$line" =~ ^subjects: ]]; then
      in_subjects=1; continue
    fi
    if (( in_subjects )); then
      # Stop at next top-level key
      [[ "$line" =~ ^[a-zA-Z] ]] && break
      if [[ "$line" =~ ^[[:space:]]*-[[:space:]]+(\"?)([A-Za-z0-9_-]+)(\"?) ]]; then
        echo "${BASH_REMATCH[2]}"
      fi
    fi
  done < "$1"
}

if [[ ! -f "$CONFIG" ]]; then
  echo "Config not found: $CONFIG" >&2
  echo "Set MOUS_CONFIG=/path/to/cohort.yaml to override." >&2
  exit 1
fi

mapfile -t SUBJECTS < <(_read_subjects_from_config "$CONFIG")
if [[ ${#SUBJECTS[@]} -eq 0 ]]; then
  echo "No subjects found in $CONFIG" >&2; exit 1
fi

# Build a subject→canonical-index map (position in config list).
declare -A SUBJECT_IDX
for i in "${!SUBJECTS[@]}"; do
  SUBJECT_IDX["${SUBJECTS[$i]}"]="$i"
done

# ── helpers ───────────────────────────────────────────────────────────────────

_pick_from_list() {
  local prompt="$1"; shift
  local -a items=("$@")
  echo ""
  echo "${prompt}"
  local i=0
  for item in "${items[@]}"; do
    printf "  [%d] %s\n" "$i" "$item"
    (( i++ )) || true
  done
  echo ""
  local choice
  while true; do
    read -rp "Enter number (or q to quit): " choice
    [[ "$choice" == "q" ]] && return 1
    if [[ "$choice" =~ ^[0-9]+$ ]] && (( choice < ${#items[@]} )); then
      PICK="${items[$choice]}"
      return 0
    fi
    echo "  Invalid — enter a number between 0 and $(( ${#items[@]} - 1 ))"
  done
}

_job_summary() {
  local jobid="$1"
  local jobname task_count mtime
  # Derive job name from the first available log for this job id
  local first_log
  first_log=$(ls -t "${LOGS_DIR}"/*_"${jobid}"_*.out 2>/dev/null | head -1) || true
  if [[ -z "$first_log" ]]; then
    printf "  job %-8s  (no logs found)\n" "$jobid"; return
  fi
  jobname=$(basename "$first_log" .out | sed "s/_${jobid}_[0-9]*$//")
  task_count=$(ls "${LOGS_DIR}"/*_"${jobid}"_*.out 2>/dev/null | wc -l | tr -d ' ')
  mtime=$(date -r "$first_log" "+%Y-%m-%d %H:%M" 2>/dev/null \
          || stat -c "%y" "$first_log" | cut -d. -f1)
  printf "  job %-8s  %-26s  %2d task log(s)   %s\n" \
    "$jobid" "$jobname" "$task_count" "$mtime"
}

# ── Discover jobs ─────────────────────────────────────────────────────────────

mapfile -t ALL_JOBS < <(
  ls -t "${LOGS_DIR}"/*.out 2>/dev/null \
  | xargs -I{} basename {} .out \
  | grep -oP '_\K[0-9]+(?=_[0-9]+$)' \
  | awk '!seen[$0]++' \
  | head -3
)

if [[ ${#ALL_JOBS[@]} -eq 0 ]]; then
  echo "No SLURM log files found in ${LOGS_DIR}" >&2; exit 1
fi

# ── Select job ────────────────────────────────────────────────────────────────

if [[ "${1:-}" =~ ^[0-9]+$ ]]; then
  SELECTED_JOB="$1"
else
  echo ""
  echo "Last ${#ALL_JOBS[@]} run(s) (subjects from: $(basename "$CONFIG")):"
  for jid in "${ALL_JOBS[@]}"; do
    _job_summary "$jid"
  done
  PICK=""
  if ! _pick_from_list "Select a run:" "${ALL_JOBS[@]}"; then
    echo "Aborted."; exit 0
  fi
  SELECTED_JOB="$PICK"
fi

# ── Build subject list from actual log files for this job ─────────────────────
# Enumerate every task index that has a log, resolve subject id from config,
# fall back to "task-N" for indices outside the config list (e.g. extra retries).

echo ""
echo "Job ${SELECTED_JOB} — task logs found:"

AVAIL_SUBJECTS=()   # display label
AVAIL_TASK_IDX=()   # actual task index in the log filename

mapfile -t _RAW_LOGS < <(
  ls "${LOGS_DIR}"/*_"${SELECTED_JOB}"_*.out 2>/dev/null | sort -V
)

if [[ ${#_RAW_LOGS[@]} -eq 0 ]]; then
  echo "  No logs found for job ${SELECTED_JOB}." >&2; exit 1
fi

for logfile in "${_RAW_LOGS[@]}"; do
  base=$(basename "$logfile" .out)
  task_idx=$(echo "$base" | grep -oP '_\K[0-9]+$')
  # Resolve subject from config by task index; fallback to "task-N"
  if (( task_idx < ${#SUBJECTS[@]} )); then
    sid="${SUBJECTS[$task_idx]}"
  else
    sid="task-${task_idx}"
  fi

  last=$(tail -1 "$logfile" 2>/dev/null || echo "(empty)")
  errfile="${LOGS_DIR}/${base}.err"
  err_flag=""
  if [[ -f "$errfile" ]]; then
    has_traceback=$(grep -c "Traceback\|^ERROR\|FAILED" "$errfile" 2>/dev/null || true)
    (( has_traceback > 0 )) && err_flag=" [ERR]"
  fi

  AVAIL_SUBJECTS+=("${sid}${err_flag}  — ${last:0:80}")
  AVAIL_TASK_IDX+=("$task_idx")
done

echo ""
for i in "${!AVAIL_SUBJECTS[@]}"; do
  printf "  [%d] %s\n" "$i" "${AVAIL_SUBJECTS[$i]}"
done
echo ""

# ── Select subject ────────────────────────────────────────────────────────────

SELECTED_TASK_IDX=""
while true; do
  read -rp "Select subject (number), 'a' for all .out, or q to quit: " choice
  [[ "$choice" == "q" ]] && echo "Aborted." && exit 0
  if [[ "$choice" == "a" ]]; then
    SELECTED_TASK_IDX="__ALL__"; break
  fi
  if [[ "$choice" =~ ^[0-9]+$ ]] && (( choice < ${#AVAIL_TASK_IDX[@]} )); then
    SELECTED_TASK_IDX="${AVAIL_TASK_IDX[$choice]}"
    SELECTED_LABEL="${AVAIL_SUBJECTS[$choice]}"
    break
  fi
  echo "  Invalid choice."
done

# ── Display log ───────────────────────────────────────────────────────────────

PAGER="${PAGER:-less}"

if [[ "$SELECTED_TASK_IDX" == "__ALL__" ]]; then
  {
    for logfile in "${_RAW_LOGS[@]}"; do
      echo "══════════════════════════════════════════════════════"
      echo " $(basename "$logfile")"
      echo "══════════════════════════════════════════════════════"
      cat "$logfile"
      echo ""
    done
  } | ${PAGER}
else
  base_prefix="${LOGS_DIR}/*_${SELECTED_JOB}_${SELECTED_TASK_IDX}"
  echo ""
  echo "Task ${SELECTED_TASK_IDX}: ${SELECTED_LABEL%%  —*}"
  echo ""

  OPTIONS=(".out (stdout)" ".err (stderr)" "both (stdout then stderr)")
  PICK=""
  if ! _pick_from_list "Which log?" "${OPTIONS[@]}"; then
    echo "Aborted."; exit 0
  fi

  case "$PICK" in
    ".out (stdout)")
      compgen -G "${base_prefix}.out" >/dev/null || { echo "No .out found."; exit 1; }
      ${PAGER} ${base_prefix}.out
      ;;
    ".err (stderr)")
      compgen -G "${base_prefix}.err" >/dev/null || { echo "No .err found."; exit 1; }
      ${PAGER} ${base_prefix}.err
      ;;
    "both (stdout then stderr)")
      {
        echo "=== STDOUT ==="; cat ${base_prefix}.out 2>/dev/null || echo "(none)"
        echo ""; echo "=== STDERR ==="; cat ${base_prefix}.err 2>/dev/null || echo "(none)"
      } | ${PAGER}
      ;;
  esac
fi
