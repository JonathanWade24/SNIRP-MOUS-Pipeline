# Contributing to MOUS Pipeline

Thank you for your interest in contributing to the MOUS pipeline.

## Development setup

1. **Clone and install in editable mode:**

   ```bash
   git clone https://github.com/JonathanWade24/MOUS.git
   cd MOUS
   python3 -m venv .venv
   source .venv/bin/activate
   pip install -e ".[gui,bids,fmri]"
   ```

2. **Run tests:**

   ```bash
   pytest tests/ -v
   ```

## Code organization

- **Authoritative logic:** `src/mous_pipeline/` only. See `AGENTS.md` for module ownership.
- **Notebooks:** Exploration and prototyping only (`notebooks/`). Do not put production code in notebooks.
- **Configs:** YAML examples under `configs/`.
- **Tests:** `tests/` with pytest fixtures in `conftest.py`.

## Adding a new stage

1. Create a module under `src/mous_pipeline/m<N>_<name>/`.
2. Update `stage_dependencies.py` with the stage ID and dependencies.
3. Add stage logic to `m9_orchestration/runner.py` following the existing pattern (`_emit`, `_stage_selected`, caching).
4. Add tests under `tests/test_m<N>_*.py`.
5. Update `README.md` stage table and `AGENTS.md` ownership.

## Submitting changes

1. Create a feature branch: `git checkout -b feature/your-feature-name`
2. Make your changes and add tests.
3. Ensure tests pass: `pytest tests/`
4. Commit with a clear message describing the "why" (not the "what").
5. Push and open a pull request with a summary of changes and test plan.

## Code style

- Follow PEP 8 conventions.
- Use type hints where practical.
- Write docstrings for public functions and classes.
- Keep functions focused and modular.

## Questions or issues?

Open an issue on [GitHub Issues](https://github.com/JonathanWade24/MOUS/issues) or consult `AGENTS.md` for module ownership.
