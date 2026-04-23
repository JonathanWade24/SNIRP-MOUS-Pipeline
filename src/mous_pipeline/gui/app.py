"""Top-level GUI app assembly."""

from __future__ import annotations

from pathlib import Path

import ipywidgets as widgets
from IPython.display import display

from ..config import PipelineConfig, load_config
from .fetch_panel import create_fetch_panel
from .results_panel import create_results_panel
from .run_panel import create_run_panel
from .setup_panel import create_setup_panel


def launch(initial_config_path: str = "configs/pilot_A2002.yaml") -> widgets.Widget:
    state: dict[str, object] = {
        "config_path": Path(initial_config_path),
        "config": None,
    }

    def on_config_loaded(config_path: Path, cfg: PipelineConfig) -> None:
        state["config_path"] = config_path
        state["config"] = cfg

    def get_config() -> tuple[Path, PipelineConfig] | None:
        cfg = state.get("config")
        cfg_path = state.get("config_path")
        if isinstance(cfg, PipelineConfig) and isinstance(cfg_path, Path):
            return cfg_path, cfg
        try:
            path = Path(initial_config_path)
            loaded = load_config(path)
            state["config_path"] = path
            state["config"] = loaded
            return path, loaded
        except Exception:
            return None

    setup_panel = create_setup_panel(initial_config_path=initial_config_path, on_config_loaded=on_config_loaded)
    fetch_panel = create_fetch_panel(get_config=get_config)
    run_panel = create_run_panel(get_config=get_config)
    results_panel = create_results_panel(get_config=get_config)

    tabs = widgets.Tab(children=[setup_panel, fetch_panel, run_panel, results_panel])
    tabs.set_title(0, "Setup")
    tabs.set_title(1, "Fetch")
    tabs.set_title(2, "Run")
    tabs.set_title(3, "Results")
    display(tabs)
    return tabs
