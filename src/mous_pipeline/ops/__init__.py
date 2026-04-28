from __future__ import annotations


def run_ops_app() -> None:
    from .app import run_ops_app as _run

    _run()


__all__ = ["run_ops_app"]
