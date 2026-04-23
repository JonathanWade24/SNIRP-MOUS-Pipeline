"""Setup panel for config and repocli readiness checks."""

from __future__ import annotations

import shutil
from pathlib import Path
from typing import Callable

import ipywidgets as widgets

from ..config import PipelineConfig, load_config


def create_setup_panel(
    *,
    initial_config_path: str = "configs/pilot_A2002.yaml",
    on_config_loaded: Callable[[Path, PipelineConfig], None] | None = None,
) -> widgets.Widget:
    config_path = widgets.Text(
        value=initial_config_path,
        description="Config",
        layout=widgets.Layout(width="100%"),
    )
    data_root_label = widgets.HTML(value="<b>data_root:</b> <code>(not loaded)</code>")
    collection_label = widgets.HTML(value="<b>rdr.collection_path:</b> <code>(not loaded)</code>")
    repocli_label = widgets.HTML()
    output = widgets.Output(layout=widgets.Layout(border="1px solid #ddd", max_height="200px", overflow="auto"))

    load_btn = widgets.Button(description="Load config", button_style="primary")
    instructions_btn = widgets.Button(description="Open repocli config instructions")

    def repocli_badge() -> str:
        ok = shutil.which("repocli") is not None
        color = "#2e7d32" if ok else "#b71c1c"
        text = "repocli on PATH" if ok else "repocli missing on PATH"
        return f'<span style="color: white; background: {color}; padding: 2px 8px; border-radius: 8px;">{text}</span>'

    def load_current_config(_: object | None = None) -> None:
        output.clear_output()
        repocli_label.value = repocli_badge()
        try:
            cfg_path = Path(config_path.value).expanduser()
            cfg = load_config(cfg_path)
            data_root_label.value = f"<b>data_root:</b> <code>{cfg.data_root}</code>"
            collection_label.value = f"<b>rdr.collection_path:</b> <code>{cfg.rdr.collection_path or '(empty)'}</code>"
            if on_config_loaded:
                on_config_loaded(cfg_path, cfg)
        except Exception as exc:  # pragma: no cover - notebook UX path
            with output:
                print(f"Failed to load config: {exc}")

    def show_instructions(_: object) -> None:
        output.clear_output()
        with output:
            print("Step 2 (one-time): repocli config")
            print("  baseurl: https://webdav.data.ru.nl")
            print("  username/password: RDR Data Access Credentials")

    load_btn.on_click(load_current_config)
    instructions_btn.on_click(show_instructions)
    load_current_config(None)

    return widgets.VBox(
        [
            widgets.HTML("<h3>Environment setup</h3>"),
            config_path,
            widgets.HBox([load_btn, instructions_btn]),
            repocli_label,
            data_root_label,
            collection_label,
            output,
        ]
    )
