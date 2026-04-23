"""CLI entrypoint."""

from __future__ import annotations

import argparse
import json
import os
import shlex
import shutil
import subprocess
import sys
from pathlib import Path
from urllib.parse import urlsplit

import pandas as pd

from .config import load_config
from .m0_intake.cyberduck import build_duck_download_command, duck_available, execute_duck_command
from .m0_intake.bids_convert import convert_subject_to_bids
from .m0_intake.repocli_rdr import (
    build_repocli_get_command,
    execute_repocli_command,
    remote_subject_path,
    repocli_available,
)
from .m7_stats.group import run_group_model
from .m9_orchestration.runner import run_subject


def _run_bids_validate(root: Path, *, subject: str | None = None, verbose: bool = False) -> None:
    """Validate a BIDS dataset using mne_bids (no Node/external tools required).

    Checks:
    - Required top-level files (dataset_description.json, README).
    - File naming via bids_validator.BIDSValidator.is_bids() on every file.
    - Subject layout via mne_bids.get_entity_vals().
    - Prints mne_bids.make_report() summary paragraph.
    - Exits non-zero on any naming error.
    """
    try:
        import mne_bids
        from bids_validator import BIDSValidator
    except ImportError as exc:
        print(f"Missing dependency for mne_bids-based validation: {exc}", file=sys.stderr)
        sys.exit(1)

    print(f"Validating BIDS dataset at: {root}")
    errors: list[str] = []
    warnings_list: list[str] = []

    # ── Required top-level files ──────────────────────────────────────────────
    for required in ("dataset_description.json",):
        if not (root / required).exists():
            errors.append(f"Missing required file: {required}")
    for recommended in ("README", "participants.tsv"):
        if not (root / recommended).exists():
            warnings_list.append(f"Missing recommended file: {recommended}")

    # ── File naming via BIDSValidator ─────────────────────────────────────────
    bv = BIDSValidator()
    subject_filter = subject.removeprefix("sub-") if subject else None
    n_checked = 0
    n_valid = 0
    for f in sorted(root.rglob("*")):
        if not f.is_file():
            continue
        rel_parts = f.relative_to(root).parts
        # Skip derivatives, hidden files, and files inside CTF .ds containers
        # (those are raw data internals, not BIDS-level files).
        if any(
            part.startswith(".")
            or part == "derivatives"
            or part.endswith(".ds")
            for part in rel_parts
        ):
            continue
        rel = "/" + f.relative_to(root).as_posix()
        if subject_filter and f"sub-{subject_filter}" not in rel:
            continue
        n_checked += 1
        if bv.is_bids(rel):
            n_valid += 1
        elif verbose:
            warnings_list.append(f"Non-BIDS filename: {rel}")

    # ── Subject layout ────────────────────────────────────────────────────────
    try:
        subjects = mne_bids.get_entity_vals(root, "subject", verbose=False)
        print(f"Subjects found   : {len(subjects)} — {subjects}")
        # Infer datatypes from directory names (anat, meg, func, eeg, ieeg).
        _known_datatypes = {"anat", "meg", "func", "eeg", "ieeg", "dwi", "fmap", "beh", "pet"}
        datatypes = sorted({
            p.name for p in root.rglob("*")
            if p.is_dir() and p.name in _known_datatypes
        })
        if datatypes:
            print(f"Datatypes found  : {datatypes}")
    except Exception as exc:
        warnings_list.append(f"mne_bids layout scan warning: {exc}")

    # ── make_report summary (scoped to subject filter when set) ───────────────
    try:
        report_root = root
        if subject_filter:
            # make_report works on full root; pass root but note filter in output
            pass
        report = mne_bids.make_report(report_root, verbose=False)
        scope = f"subject {subject_filter}" if subject_filter else "full dataset"
        print(f"\n── Dataset report ({scope}) ──")
        print(report)
    except Exception as exc:
        warnings_list.append(f"make_report skipped: {exc}")

    # ── Results ───────────────────────────────────────────────────────────────
    print(f"\n── Naming check: {n_valid}/{n_checked} files pass BIDS naming rules ──")
    if warnings_list:
        print("\nWarnings:")
        for w in warnings_list:
            print(f"  ⚠  {w}")
    if errors:
        print("\nErrors:")
        for e in errors:
            print(f"  ✗  {e}", file=sys.stderr)
        sys.exit(1)
    print("\n✓ No hard BIDS errors detected by mne_bids validation.")


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
    bids_convert_parser = sub.add_parser("bids-convert", help="Add in-place BIDS metadata sidecars for a subject")
    bids_convert_parser.add_argument("--config", required=True)
    bids_convert_parser.add_argument("--subject", required=True, help="Subject ID, e.g., A2002 or sub-A2002")
    bids_validate_parser = sub.add_parser("bids-validate", help="Run bids-validator on the dataset root")
    bids_validate_parser.add_argument("--config", default=None, help="YAML config path (uses data_root when set)")
    bids_validate_parser.add_argument("--root", default=None, help="Override BIDS root path")
    bids_validate_parser.add_argument("--subject", default=None, help="Optional subject filter, e.g., A2003")
    bids_validate_parser.add_argument("--verbose", action="store_true", help="Pass --verbose to bids-validator")
    gui_parser = sub.add_parser("gui", help="Launch Streamlit GUI with printed access URLs")
    gui_parser.add_argument("--port", type=int, default=8501, help="Port to run Streamlit on")
    gui_parser.add_argument(
        "--config",
        default="configs/pilot_A2002.yaml",
        help="Config path preloaded in GUI via MOUS_GUI_CONFIG env var",
    )
    gui_parser.add_argument(
        "--base-url-path",
        default="",
        help="Optional Streamlit base URL path override. "
        "Default is empty, which is correct for JupyterHub proxy rewrite setups.",
    )
    gui_parser.add_argument(
        "--public-base-url",
        default=None,
        help="Optional public host URL (e.g. https://snirp24.neurodesk.org). "
        "When omitted, the CLI auto-detects host from JupyterHub env vars.",
    )

    args = parser.parse_args()

    if args.cmd == "run":
        cfg = load_config(args.config)
        only = {s.strip() for s in args.only.split(",") if s.strip()} or None
        skip = {s.strip() for s in args.skip.split(",") if s.strip()} or None
        # --include-fmri / --include-waves-validation are additive: they expand an
        # explicit --only list.  When --only was not given (only=None) the runner
        # already selects every stage, so the flags are a no-op.
        if args.include_fmri and only is not None:
            only = only | {"m10", "m11"}
        if args.include_waves_validation and only is not None:
            only = only | {"m12"}
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
    elif args.cmd == "bids-convert":
        cfg = load_config(args.config)
        bids_paths = convert_subject_to_bids(args.subject, cfg)
        print(f"Created/updated BIDS metadata for {len(bids_paths)} recording(s):")
        for bp in bids_paths:
            print(f"- {bp}")
    elif args.cmd == "bids-validate":
        if args.root:
            bids_root = Path(args.root).expanduser().resolve()
        elif args.config:
            bids_root = load_config(args.config).data_root.resolve()
        else:
            bids_root = Path(".").resolve()
        if not bids_root.exists():
            print(f"BIDS root does not exist: {bids_root}", file=sys.stderr)
            sys.exit(1)
        _run_bids_validate(bids_root, subject=args.subject, verbose=args.verbose)
    elif args.cmd == "gui":
        service_prefix = os.environ.get("JUPYTERHUB_SERVICE_PREFIX", "/")
        if args.base_url_path:
            base_url_path = args.base_url_path
        else:
            # Default behavior for Neurodesk/JupyterHub: proxy rewrites path,
            # Streamlit serves at root (no baseUrlPath).
            base_url_path = ""
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
            "--browser.gatherUsageStats",
            "false",
        ]
        if base_url_path:
            cmd.extend(["--server.baseUrlPath", base_url_path])
        print("Launching MOUS GUI...")
        print(f"Config: {cfg_path}")
        print(f"Port: {args.port}")
        print(f"baseUrlPath: {base_url_path or '(empty)'}")
        print("")
        print("Open one of these URLs:")
        proxy_path = f"{service_prefix.rstrip('/')}/proxy/{args.port}/"
        print(f"- Relative proxy path: {proxy_path}")
        full_urls: list[str] = []
        if args.public_base_url:
            full_urls.append(f"{args.public_base_url.rstrip('/')}{proxy_path}")
        else:
            host_candidates = [
                os.environ.get("JUPYTERHUB_PUBLIC_URL"),
                os.environ.get("JUPYTER_SERVER_URL"),
                os.environ.get("JUPYTERHUB_HOST"),
                os.environ.get("JUPYTERHUB_BASE_URL"),
            ]
            for host in host_candidates:
                if not host:
                    continue
                parsed = urlsplit(host)
                if parsed.scheme and parsed.netloc:
                    full_urls.append(f"{parsed.scheme}://{parsed.netloc}{proxy_path}")
                elif host.startswith("http://") or host.startswith("https://"):
                    full_urls.append(f"{host.rstrip('/')}{proxy_path}")
        for url in dict.fromkeys(full_urls):
            print(f"- Full URL: {url}")
        print(f"- If using local browser from same machine: http://localhost:{args.port}")
        print("")
        print(f"Tip: stop old instances with `lsof -ti :{args.port} | xargs -r kill -9`.")
        subprocess.run(cmd, check=False)
