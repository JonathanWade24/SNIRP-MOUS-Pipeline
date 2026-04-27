#!/bin/bash
# mous_logs.sh — interactively browse MOUS SLURM run logs
#
# Usage:
#   bash scripts/mous_logs.sh           # show last 3 runs, pick one, pick subject
#   source scripts/mous_logs.sh         # same but keeps you in current shell
#   bash scripts/mous_logs.sh <jobid>   # jump straight to a specific job ID

set -euo pipefail

LOGS_DIR="${LOGS_DIR:-$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)/logs}"
SUBJECTS=(
  A2002 A2003 A2004 A2005 A2006
  A2007 A2008 A2009 A2010 A2013
  A2014 A2015 A2027
)

# ── helpers ──────────────────────────────────────────────────────────────────

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
  # Print one-line summary for a job: name, id, task count, date of first log
  local jobid="$1"
  local first_log
  first_log=$(ls -t "${LOGS_DIR}"/*_"${jobid}"_*.out 2>/dev/null | tail -1) || true
  local jobname task_count mtime
  jobname=$(ls "${LOGS_DIR}"/*_"${jobid}"_*.out 2>/dev/null | head -1 \
            | xargs -I{} basename {} .out \
            | sed "s/_${jobid}_[0-9]*$//") 2>/dev/null || jobname="unknown"
  task_count=$(ls "${LOGS_DIR}"/*_"${jobid}"_*.out 2>/dev/null | wc -l | tr -d ' ')
  if [[ -n "$first_log" ]]; then
    mtime=$(date -r "$first_log" "+%Y-%m-%d %H:%M" 2>/dev/null || stat -c "%y" "$first_log" | cut -d. -f1)
  else
    mtime="(no logs)"
  fi
  printf "  job %-8s  %-22s  %2d tasks   %s\n" "$jobid" "$jobname" "$task_count" "$mtime"
}

_task_index_for_subject() {
  local sid="$1"
  for i in "${!SUBJECTS[@]}"; do
    [[ "${SUBJECTS[$i]}" == "$sid" ]] && echo "$i" && return
  done
  echo ""
}

# ── main ─────────────────────────────────────────────────────────────────────

# Collect unique job IDs from logs dir, sorted newest-first (by mtime of any log file)
mapfile -t ALL_JOBS < <(
  ls -t "${LOGS_DIR}"/*.out 2>/dev/null \
  | xargs -I{} basename {} .out \
  | grep -oP '_\K[0-9]+(?=_[0-9]+$)' \
  | awk '!seen[$0]++' \
  | head -3
)

if [[ ${#ALL_JOBS[@]} -eq 0 ]]; then
  echo "No SLURM log files found in ${LOGS_DIR}" >&2
  exit 1
fi

# If jobid supplied on command line, use it directly; else pick interactively
if [[ "${1:-}" =~ ^[0-9]+$ ]]; then
  SELECTED_JOB="$1"
else
  echo ""
  echo "Last ${#ALL_JOBS[@]} run(s):"
  for jid in "${ALL_JOBS[@]}"; do
    _job_summary "$jid"
  done

  PICK=""
  if ! _pick_from_list "Select a run:" "${ALL_JOBS[@]}"; then
    echo "Aborted."
    exit 0
  fi
  SELECTED_JOB="$PICK"
fi

echo ""
echo "Job ${SELECTED_JOB} — available subject logs:"

# Build list of subjects that have a .out log for this job
AVAIL_SUBJECTS=()
AVAIL_LABELS=()
for i in "${!SUBJECTS[@]}"; do
  sid="${SUBJECTS[$i]}"
  outfile="${LOGS_DIR}"/*_"${SELECTED_JOB}"_"${i}".out
  # glob — check if file exists
  if compgen -G "${LOGS_DIR}/*_${SELECTED_JOB}_${i}.out" >/dev/null 2>&1; then
    # Peek at last line of .out for quick status
    last=$(tail -1 ${LOGS_DIR}/*_"${SELECTED_JOB}"_"${i}".out 2>/dev/null || echo "(empty)")
    # Check if .err has content
    errsize=0
    if compgen -G "${LOGS_DIR}/*_${SELECTED_JOB}_${i}.err" >/dev/null 2>&1; then
      errsize=$(wc -c < ${LOGS_DIR}/*_"${SELECTED_JOB}"_"${i}".err 2>/dev/null || echo 0)
    fi
    err_flag=""
    (( errsize > 0 )) && err_flag=" [ERR]"
    AVAIL_SUBJECTS+=("$sid")
    AVAIL_LABELS+=("${sid}${err_flag}  — ${last:0:80}")
  else
    AVAIL_SUBJECTS+=("$sid")
    AVAIL_LABELS+=("${sid}  (no log yet)")
  fi
done

# Display and pick subject
echo ""
for i in "${!AVAIL_LABELS[@]}"; do
  printf "  [%d] %s\n" "$i" "${AVAIL_LABELS[$i]}"
done
echo ""

PICK=""
while true; do
  read -rp "Select subject (number), or 'a' for all .out, or q to quit: " choice
  [[ "$choice" == "q" ]] && echo "Aborted." && exit 0
  if [[ "$choice" == "a" ]]; then
    SELECTED_SUBJECT="__ALL__"
    break
  fi
  if [[ "$choice" =~ ^[0-9]+$ ]] && (( choice < ${#AVAIL_SUBJECTS[@]} )); then
    SELECTED_SUBJECT="${AVAIL_SUBJECTS[$choice]}"
    SELECTED_IDX="$choice"
    break
  fi
  echo "  Invalid choice."
done

# ── display log ───────────────────────────────────────────────────────────────

PAGER="${PAGER:-less}"

if [[ "$SELECTED_SUBJECT" == "__ALL__" ]]; then
  # Concatenate all .out files for this job
  all_outs=( $(compgen -G "${LOGS_DIR}/*_${SELECTED_JOB}_*.out" | sort -V) )
  if [[ ${#all_outs[@]} -eq 0 ]]; then
    echo "No .out files found for job ${SELECTED_JOB}."
    exit 1
  fi
  echo ""
  echo "Showing all ${#all_outs[@]} .out files for job ${SELECTED_JOB} ..."
  echo ""
  { for f in "${all_outs[@]}"; do
      echo "══════════════════════════════════════════════════════"
      echo " $(basename "$f")"
      echo "══════════════════════════════════════════════════════"
      cat "$f"
      echo ""
    done
  } | ${PAGER}
else
  OUT_GLOB="${LOGS_DIR}/*_${SELECTED_JOB}_${SELECTED_IDX}.out"
  ERR_GLOB="${LOGS_DIR}/*_${SELECTED_JOB}_${SELECTED_IDX}.err"

  echo ""
  echo "Subject ${SELECTED_SUBJECT} — task index ${SELECTED_IDX}"
  echo ""

  # Offer .out or .err
  OPTIONS=(".out (stdout)" ".err (stderr)" "both (side-by-side in less)")
  PICK=""
  if ! _pick_from_list "Which log?" "${OPTIONS[@]}"; then
    echo "Aborted."
    exit 0
  fi

  case "$PICK" in
    ".out (stdout)")
      compgen -G "$OUT_GLOB" >/dev/null 2>&1 || { echo "No .out found."; exit 1; }
      ${PAGER} ${OUT_GLOB}
      ;;
    ".err (stderr)")
      compgen -G "$ERR_GLOB" >/dev/null 2>&1 || { echo "No .err found."; exit 1; }
      ${PAGER} ${ERR_GLOB}
      ;;
    "both (side-by-side in less)")
      { echo "=== STDOUT ==="; cat ${OUT_GLOB} 2>/dev/null || echo "(none)"
        echo ""; echo "=== STDERR ==="; cat ${ERR_GLOB} 2>/dev/null || echo "(none)"
      } | ${PAGER}
      ;;
  esac
fi
