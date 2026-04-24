# Contributing

## Setup

```bash
git clone https://github.com/JonathanWade24/MOUS.git
cd MOUS
python3 -m venv .venv
source .venv/bin/activate
pip install -e ".[gui,bids,fmri]"   # trim extras to what you need
pytest tests/ -v
```

Pipeline code belongs under `src/mous_pipeline/`. Configs live in `configs/`, tests in `tests/`.

## New stage

1. Add a package under `src/mous_pipeline/m<n>_<name>/`.
2. Update `stage_dependencies.py` and `m9_orchestration/runner.py` (same patterns as existing stages: `_emit`, caching, `only`/`skip`).
3. Add tests and update the stage table in `README.md` if the stage is user-facing.

## PRs

Branch from `main`, run the checks below, and open a focused PR with clear test evidence.

### Required pre-PR checks

```bash
pytest tests/ -v
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
