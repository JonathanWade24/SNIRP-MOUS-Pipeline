"""CLI entrypoint."""

from __future__ import annotations

import argparse

from .config import load_config
from .m9_orchestration.runner import run_subject


def main() -> None:
    parser = argparse.ArgumentParser(description="MOUS pipeline")
    sub = parser.add_subparsers(dest="cmd", required=True)
    run_parser = sub.add_parser("run", help="Run subject pipeline")
    run_parser.add_argument("--config", required=True)
    run_parser.add_argument("--subject", required=True)
    args = parser.parse_args()

    if args.cmd == "run":
        cfg = load_config(args.config)
        result = run_subject(args.subject, cfg)
        print(result.summary())
