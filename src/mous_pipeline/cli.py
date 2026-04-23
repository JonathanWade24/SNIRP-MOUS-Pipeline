"""CLI entrypoint."""

from __future__ import annotations

import argparse
import json
import os
import shlex
import subprocess
import sys
from pathlib import Path

import pandas as pd

from .config import load_config
from .m0_intake.cyberduck import build_duck_download_command, duck_available, execute_duck_command
from .m0_intake.repocli_rdr import (
    build_repocli_get_command,
    execute_repocli_command,
    remote_subject_path,
    repocli_available,
)
from .m7_stats.group import run_group_model
from .m9_orchestration.runner import run_subject


def main() -> None:
    parser = argparse.ArgumentParser(description="MOUS pipeline")
    sub = parser.add_subparsers(dest="cmd", required=True)

    run_parser = sub.add_parser("run", help="Run subject pipeline")
    run_parser.add_argument("--config", required=True)
    run_parser.add_argument("--subject", required=True)
    run_parser.add_argument("--only", default="", help="Comma-separated stage names to run")
    run_parser.add_argument("--skip", default="", help="Comma-separated stage names to skip")
    run_parser.add_argument("--force", action="store_true", help="Ignore existing outputs and recompute")
    run_parser.add_argument("--dry-run", action="store_true", help="Print resolved run plan without processing data")
    run_parser.add_argument("--include-fmri", action="store_true", help="Include m10/m11 stages")
    run_parser.add_argument("--include-waves-validation", action="store_true", help="Include m12 stage")

    fetch_parser = sub.add_parser("fetch-subject", help="Build or execute Cyberduck duck download command")
    fetch_parser.add_argument("--subject", required=True, help="Subject ID without sub- prefix, e.g., A2003")
    fetch_parser.add_argument("--protocol", default="sftp", help="Remote protocol, e.g., sftp, ftp, webdav")
    fetch_parser.add_argument("--host", required=True, help="Remote host")
    fetch_parser.add_argument("--remote-root", required=True, help="Remote directory containing subject tarballs")
    fetch_parser.add_argument("--local-root", default=".", help="Local destination directory")
    fetch_parser.add_argument("--username", default=None, help="Optional remote username")
    fetch_parser.add_argument(
        "--execute",
        action="store_true",
        help="Execute duck command immediately (requires duck installed and authentication configured)",
    )

    rdr_parser = sub.add_parser(
        "fetch-rdr",
        help="Download a subject folder from RDR via repocli (run `repocli config` once; base URL https://webdav.data.ru.nl)",
    )
    rdr_parser.add_argument("--config", default=None, help="YAML config with rdr.collection_path and data_root")
    rdr_parser.add_argument("--subject", required=True, help="Subject ID, e.g., A2002 or sub-A2002")
    rdr_parser.add_argument(
        "--collection-path",
        default=None,
        help="RDR path under WebDAV root, e.g., dccn/DSC_3011020.09_236_v1 (overrides config)",
    )
    rdr_parser.add_argument(
        "--dest",
        default=None,
        help="Local directory where sub-*/ will be placed (default: config data_root or current directory)",
    )
    rdr_parser.add_argument(
        "--execute",
        action="store_true",
        help="Run repocli immediately (otherwise print the command only)",
    )
    group_parser = sub.add_parser("group", help="Run group-level stats across subject manifests")
    group_parser.add_argument(
        "--derivatives-root",
        default="derivatives/mous_pipeline",
        help="Derivatives root containing <subject>/m9_orchestration/*_run_manifest.json",
    )
    group_parser.add_argument("--test", default="wilcoxon", choices=["wilcoxon", "lme"])
    gui_parser = sub.add_parser("gui", help="Launch Streamlit GUI with printed access URLs")
    gui_parser.add_argument("--port", type=int, default=8501, help="Port to run Streamlit on")
    gui_parser.add_argument(
        "--config",
        default="configs/pilot_A2002.yaml",
        help="Config path preloaded in GUI via MOUS_GUI_CONFIG env var",
    )
    gui_parser.add_argument(
        "--base-url-path",
        default=None,
        help="Override Streamlit base URL path. Default auto-detects from JupyterHub service prefix.",
    )

    args = parser.parse_args()

    if args.cmd == "run":
        cfg = load_config(args.config)
        only = {s.strip() for s in args.only.split(",") if s.strip()} or None
        skip = {s.strip() for s in args.skip.split(",") if s.strip()} or None
        if args.include_fmri:
            only = (only or set()) | {"m10", "m11"}
        if args.include_waves_validation:
            only = (only or set()) | {"m12"}
        result = run_subject(
            args.subject,
            cfg,
            only=only,
            skip=skip,
            force=args.force,
            dry_run=args.dry_run,
            config_path=Path(args.config),
        )
        print(result.summary())
    elif args.cmd == "fetch-subject":
        cmd = build_duck_download_command(
            protocol=args.protocol,
            host=args.host,
            remote_root=args.remote_root,
            subject=args.subject,
            local_root=args.local_root,
            username=args.username,
        )
        print("Duck command:")
        print(" ".join(shlex.quote(c) for c in cmd))
        if not args.execute:
            print("Preview only. Add --execute to run this command.")
            return
        if not duck_available():
            print("duck is not installed or not on PATH. Install Cyberduck CLI first.", file=sys.stderr)
            sys.exit(1)
        proc = execute_duck_command(cmd)
        if proc.stdout:
            print(proc.stdout)
        if proc.returncode != 0:
            if proc.stderr:
                print(proc.stderr, file=sys.stderr)
            sys.exit(proc.returncode)
    elif args.cmd == "fetch-rdr":
        collection_path = args.collection_path
        dest: Path
        if args.config:
            cfg = load_config(args.config)
            if not collection_path:
                collection_path = cfg.rdr.collection_path
            dest = Path(args.dest) if args.dest else cfg.data_root
        else:
            dest = Path(args.dest) if args.dest else Path(".")
        if not collection_path:
            print(
                "Missing collection path: set rdr.collection_path in config or pass --collection-path.",
                file=sys.stderr,
            )
            sys.exit(1)
        remote = remote_subject_path(collection_path, args.subject)
        cmd = build_repocli_get_command(remote_path=remote, local_dir=dest.resolve())
        print("Repocli command (credentials: repocli config; base URL https://webdav.data.ru.nl):")
        print(" ".join(shlex.quote(c) for c in cmd))
        if not args.execute:
            print("Preview only. Add --execute to run.")
            return
        if not repocli_available():
            print("repocli is not on PATH. Install from Donders-Institute/dr-tools releases.", file=sys.stderr)
            sys.exit(1)
        dest.mkdir(parents=True, exist_ok=True)
        proc = execute_repocli_command(cmd)
        if proc.stdout:
            print(proc.stdout)
        if proc.returncode != 0:
            if proc.stderr:
                print(proc.stderr, file=sys.stderr)
            sys.exit(proc.returncode)
    elif args.cmd == "group":
        root = Path(args.derivatives_root)
        metrics_list = []
        trial_tables = []
        for mf in root.glob("*/m9_orchestration/*_run_manifest.json"):
            try:
                payload = json.loads(mf.read_text())
                metrics = payload.get("metrics", {})
                if metrics:
                    metrics_list.append(metrics)
            except Exception:
                continue
        for tf in root.glob("*/m8_reports/exports/*_trials.csv"):
            try:
                df = pd.read_csv(tf)
                if not df.empty:
                    df["subject"] = tf.parts[-4].removeprefix("sub-")
                    trial_tables.append(df)
            except Exception:
                continue
        if not metrics_list:
            print("No subject manifests found for group analysis.", file=sys.stderr)
            sys.exit(1)
        summary = run_group_model(metrics_list, test=args.test)
        out_path = root / "group_summary.json"
        out_path.write_text(json.dumps(summary, indent=2))
        print(f"Wrote group summary: {out_path}")
        if trial_tables:
            group_trials = pd.concat(trial_tables, ignore_index=True)
            trial_path = root / "group_trials.csv"
            group_trials.to_csv(trial_path, index=False)
            print(f"Wrote group trials: {trial_path}")
    elif args.cmd == "gui":
        service_prefix = os.environ.get("JUPYTERHUB_SERVICE_PREFIX", "/")
        if args.base_url_path:
            base_url_path = args.base_url_path
        else:
            base_url_path = f"{service_prefix.rstrip('/')}/proxy/{args.port}"
        cfg_path = str(Path(args.config).expanduser().resolve())
        os.environ["MOUS_GUI_CONFIG"] = cfg_path
        cmd = [
            "streamlit",
            "run",
            "src/mous_pipeline/gui_streamlit.py",
            "--server.headless",
            "true",
            "--server.port",
            str(args.port),
            "--server.baseUrlPath",
            base_url_path,
            "--browser.gatherUsageStats",
            "false",
        ]
        print("Launching MOUS GUI...")
        print(f"Config: {cfg_path}")
        print(f"Port: {args.port}")
        print(f"baseUrlPath: {base_url_path}")
        print("")
        print("Open one of these URLs:")
        print(f"- Relative proxy path: {base_url_path}/")
        hub_host = os.environ.get("JUPYTERHUB_HOST")
        if hub_host:
            print(f"- Full URL: {hub_host.rstrip('/')}{base_url_path}/")
        print("- If using local browser from same machine: http://localhost:8501")
        print("")
        print("Tip: stop old instances with `lsof -ti :8501 | xargs -r kill -9`.")
        subprocess.run(cmd, check=False)
