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

Branch from `main`, run `pytest`, and open a PR with a short description of the change and how you tested it.

Questions: [Issues](https://github.com/JonathanWade24/MOUS/issues).
