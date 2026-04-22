"""CLI entrypoint."""

from __future__ import annotations

import argparse
import shlex
import sys
from pathlib import Path

from .config import load_config
from .m0_intake.cyberduck import build_duck_download_command, duck_available, execute_duck_command
from .m0_intake.repocli_rdr import (
    build_repocli_get_command,
    execute_repocli_command,
    remote_subject_path,
    repocli_available,
)
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

    args = parser.parse_args()

    if args.cmd == "run":
        cfg = load_config(args.config)
        only = {s.strip() for s in args.only.split(",") if s.strip()} or None
        skip = {s.strip() for s in args.skip.split(",") if s.strip()} or None
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
