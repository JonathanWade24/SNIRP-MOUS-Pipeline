# Contributing

## Setup

```bash
git clone https://github.com/JonathanWade24/MOUS.git
cd MOUS
python3 -m venv .venv
source .venv/bin/activate
pip install -e ".[gui,bids,fmri]"   # trim extras to what you need
make test-quick
```

Pipeline code belongs under `src/mous_pipeline/`. Configs live in `configs/`, tests in `tests/`.

## New stage

1. Add a package under `src/mous_pipeline/m<n>_<name>/`.
2. Update `stage_dependencies.py` and `m9_orchestration/runner.py` (same patterns as existing stages: `_emit`, caching, `only`/`skip`).
3. Add tests and update the stage table in `README.md` if the stage is user-facing.

## Branch strategy

```
main  ← protected; no direct pushes; the integration branch
  ↑
  └── short-lived feature branches (feat/, fix/, wip/, cursor/)
       merged to main via PR

HPC   ← deploy branch; what Palmetto always runs from
  ↑
  └── explicitly promoted from main with mousdeploy
```

### Everyday local workflow

```bash
# Start work
git switch -c feat/my-thing

# Push and open a PR when done
git push -u origin HEAD
gh pr create --fill
gh pr merge --squash --delete-branch
```

Useful aliases (add to `~/.zshrc` or `~/.bashrc`):

```bash
alias gnb='git switch -c'
alias gpr='git push -u origin HEAD && gh pr create --fill'
alias gpm='gh pr merge --squash --delete-branch'
```

### Promoting code to the cluster

After merging to `main`, advance the `HPC` deploy branch so the next cluster job picks it up:

```bash
mousdeploy   # defined in docs/dotfiles/mous-palmetto.sh
```

This is a fast-forward only — it will fail if `HPC` has diverged from `main`, which surfaces accidental direct commits to `HPC`.

### Cluster sync

To sync the cluster working tree to the latest `HPC` branch from a Palmetto login node:

```bash
mousupdate          # aborts if working tree is dirty
mousupdate --force  # skips dirty-tree check
```

Slurm jobs do **not** auto-sync by default. To opt a job into syncing at startup, export
`MOUS_SYNC_ON_START=1` before submitting — the job will abort if the tree is dirty rather than
silently discarding changes:

```bash
MOUS_SYNC_ON_START=1 sbatch scripts/run_mous_driver.sbatch
```

Only use `MOUS_SYNC_ON_START` when the cluster checkout is a dedicated clean deploy tree.
If you share `/scratch/jonathanwade/MOUS` with active development, use `mousupdate` manually instead.

### One-time: protect main on GitHub

```bash
gh api repos/JonathanWade24/SNIRP-MOUS-Pipeline/branches/main/protection \
  -X PUT \
  -H "Accept: application/vnd.github+json" \
  -f "required_status_checks=null" \
  -f "enforce_admins=false" \
  -f "required_pull_request_reviews=null" \
  -f "restrictions=null" \
  -F "allow_force_pushes=false" \
  -F "allow_deletions=false"
```

## PRs

Branch from `main`, run the checks below, and open a focused PR with clear test evidence.

### Required pre-PR checks

```bash
make test-full
```

Parallel option (falls back to serial if `pytest-xdist` is missing):

```bash
make test-parallel
```

For full-pipeline verification (without source reconstruction), run:

```bash
mous-pipeline run --config <cfg> --subject <id> --skip m5 --dry-run
mous-pipeline run --config <cfg> --subject <id> --skip m5 --force
mous-pipeline verify-run --config <cfg> --subject <id> --require-skip-m5 --strict-mode
```

For SLURM orchestration changes, also include a dry-run proof:

```bash
scripts/run_aims_priority.sh --config <cfg> --subjects <id1,id2> --fetch-missing --dry-run
```

### Quality expectations

- Keep PR scope small and reviewable; avoid mixing unrelated cleanup and behavioral changes.
- Bug fixes must include: reproduction signal, root cause, and a regression test.
- Critical stages (`m10`, `m11` by default) should fail explicitly in strict mode instead of silently degrading.
- If you intentionally run in permissive mode (`pipeline.strict_stage_failures: false`), document why in the PR.

Questions: [Issues](https://github.com/JonathanWade24/MOUS/issues).
