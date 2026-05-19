# Repository Guidelines

## Project Structure & Module Organization

This is a Python 3.10+ package for the MOUS analysis pipeline. Core code lives in `src/mous_pipeline/`, organized by pipeline stage (`m1_events`, `m2_preprocess`, `m5_source`, `m9_orchestration`, etc.). Tests live in `tests/` and generally mirror stage or CLI behavior. Runtime configuration is in `configs/`, Quarto report templates and styles are in `reports/`, cluster and data-management helpers are in `scripts/`, and operational notes are in `docs/`. Generated derivatives, subject reports, zip archives, and run-result directories should not be treated as source changes unless the task explicitly requires them.

## Build, Test, and Development Commands

Set up a local editable install from the repository root:

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -e ".[gui,bids,fmri,ops]"
```

Use `make test-quick` for the default fast suite, excluding `integration` and `slow` tests. Use `make test-full` or `pytest tests/` before PRs. `make test-parallel` and `make test-quick-parallel` use `pytest-xdist` when available and fall back to serial pytest. Run the CLI with examples such as:

```bash
mous-pipeline run --config configs/palmetto_hpcnirc_fmri.yaml --subject A2002 --dry-run
mous-pipeline check-quarto-env
```

## Coding Style & Naming Conventions

Follow the existing Python style: 4-space indentation, type annotations where useful, `pathlib.Path` for paths, and small functions with explicit error handling. Stage packages use `m<n>_<name>` naming, and tests use `test_<feature>.py`. Keep CLI-visible stage names aligned with `src/mous_pipeline/stage_dependencies.py` and orchestration code. There is no project-wide formatter configured in `pyproject.toml`; keep edits consistent with nearby code.

## Testing Guidelines

Pytest is the test framework. Mark tests with `integration` or `slow` when they touch workspace data, external-like paths, or longer runtimes. Bug fixes should include a regression test that captures the failure mode. For pipeline behavior changes, include dry-run or manifest-based evidence, for example `mous-pipeline verify-run --config <cfg> --subject <id> --strict-mode`.

## Commit & Pull Request Guidelines

Git history uses concise imperative messages, often Conventional Commit style such as `fix(ops): ...` or `refactor(ops): ...`; keep subjects specific and scoped. Branch from `main` using short-lived `feat/`, `fix/`, `wip/`, or `cursor/` branches. PRs should follow `.github/pull_request_template.md`: summary, risk assessment, rollback plan, validation checklist, and notes about any intentional permissive-mode behavior.

## Security & Configuration Tips

Do not commit credentials, RDR tokens, SSH keys, or user-specific cluster secrets. Keep Palmetto resource changes modest and explicit in `scripts/*.sbatch` or config files, and document any required modules or external tools such as FreeSurfer, Quarto, `repocli`, or Cyberduck `duck`.
