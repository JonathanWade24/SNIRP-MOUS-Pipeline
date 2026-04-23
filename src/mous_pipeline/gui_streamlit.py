"""Streamlit GUI for MOUS pipeline workflow."""

from __future__ import annotations

import json
import shutil
import subprocess
from pathlib import Path
from typing import Any

import matplotlib.pyplot as plt
import streamlit as st

from mous_pipeline.config import PipelineConfig, load_config
from mous_pipeline.m0_intake.repocli_rdr import build_repocli_get_command, remote_subject_path
from mous_pipeline.m9_orchestration.runner import run_subject

STAGES = ["m1", "m2", "m3", "m6a", "m7", "m8", "m9"]
STAGE_DESCRIPTIONS = {
    "m1": "Parse events TSV and validate trial structure.",
    "m2": "Preprocess task/rest data: notch, resample, ICA, beta-band filter.",
    "m3": "Epoch task data around event onsets.",
    "m6a": "Compute phase-gradient directions and directional consistency indices.",
    "m7": "Run circular/permutation statistics for wave consistency and significance.",
    "m8": "Generate the subject HTML report.",
    "m9": "Evaluate pilot gate and derive GO/MARGINAL/NO-GO verdict.",
}


def _init_state() -> None:
    st.session_state.setdefault("config_path", "configs/pilot_A2002.yaml")
    st.session_state.setdefault("cfg", None)
    st.session_state.setdefault("cfg_loaded_path", None)
    st.session_state.setdefault("last_run_summary", None)


def _load_cfg(path_value: str) -> tuple[Path, PipelineConfig] | None:
    try:
        cfg_path = Path(path_value).expanduser()
        cfg = load_config(cfg_path)
        st.session_state["cfg"] = cfg
        st.session_state["cfg_loaded_path"] = cfg_path
        return cfg_path, cfg
    except Exception as exc:
        st.error(f"Failed to load config: {exc}")
        return None


def _active_cfg() -> tuple[Path, PipelineConfig] | None:
    cfg = st.session_state.get("cfg")
    cfg_path = st.session_state.get("cfg_loaded_path")
    if isinstance(cfg, PipelineConfig) and isinstance(cfg_path, Path):
        return cfg_path, cfg
    return _load_cfg(st.session_state["config_path"])


def _setup_section() -> None:
    st.subheader("Setup")
    st.session_state["config_path"] = st.text_input("Config path", value=st.session_state["config_path"])
    if st.button("Load config"):
        _load_cfg(st.session_state["config_path"])

    cfg_bundle = _active_cfg()
    repocli_ok = shutil.which("repocli") is not None
    st.markdown(f"**repocli:** {'on PATH' if repocli_ok else 'missing on PATH'}")
    st.code(
        "Step 2 (one-time): repocli config\n"
        "  baseurl: https://webdav.data.ru.nl\n"
        "  username/password: RDR Data Access Credentials"
    )
    if cfg_bundle:
        _, cfg = cfg_bundle
        st.markdown(f"**data_root:** `{cfg.data_root}`")
        st.markdown(f"**rdr.collection_path:** `{cfg.rdr.collection_path or '(empty)'}`")


def _fetch_section() -> None:
    st.subheader("Fetch from RDR")
    cfg_bundle = _active_cfg()
    subject = st.text_input("Subject ID", value="A2002", key="fetch_subject")
    st.caption("e.g. A2002 - a leading 'sub-' prefix is stripped automatically.")
    repocli_ok = shutil.which("repocli") is not None
    if not repocli_ok:
        st.warning("repocli is not on PATH. Run setup.sh or fix PATH before fetching.")
    if st.button("Download subject"):
        if not cfg_bundle:
            st.error("Load a valid config first.")
            return
        if not repocli_ok:
            st.error("repocli is not on PATH.")
            return
        _, cfg = cfg_bundle
        if not cfg.rdr.collection_path:
            st.error("rdr.collection_path is empty in config.")
            return
        normalized_subject = subject.strip().removeprefix("sub-")
        if not normalized_subject:
            st.error("Subject ID is required.")
            return
        cmd = build_repocli_get_command(
            remote_path=remote_subject_path(cfg.rdr.collection_path, normalized_subject),
            local_dir=cfg.data_root.resolve(),
        )
        log_box = st.empty()
        logs: list[str] = [f"$ {' '.join(cmd)}\n"]
        with st.spinner("Downloading..."):
            proc = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True)
            assert proc.stdout is not None
            for line in proc.stdout:
                logs.append(line)
                log_box.code("".join(logs), language="bash")
            code = proc.wait()
        if code == 0:
            st.success("Download complete.")
        else:
            st.error(f"Download failed (exit {code}).")
        log_box.code("".join(logs), language="bash")


def _run_section() -> None:
    st.subheader("Run pipeline")
    cfg_bundle = _active_cfg()
    subject = st.text_input("Subject ID", value="A2002", key="run_subject")
    st.caption("e.g. A2002 - a leading 'sub-' prefix is stripped automatically.")
    force = st.checkbox("Force recompute", value=False)
    selected = st.multiselect("Stages", STAGES, default=STAGES)
    with st.expander("Stage reference"):
        st.table([{"stage": s, "description": STAGE_DESCRIPTIONS[s]} for s in STAGES])
    normalized_subject = subject.strip().removeprefix("sub-")
    if not normalized_subject:
        st.warning("Subject field is empty.")
    if cfg_bundle:
        _, cfg = cfg_bundle
        if not cfg.data_root.exists():
            st.warning(f"data_root does not exist yet: {cfg.data_root}")
    if st.button("Run pipeline"):
        if not cfg_bundle:
            st.error("Load a valid config first.")
            return
        if not normalized_subject:
            st.error("Subject ID is required.")
            return
        if not selected:
            st.error("Select at least one stage.")
            return
        cfg_path, cfg = cfg_bundle
        skip = set(STAGES) - set(selected)
        progress = st.progress(0, text="Starting...")
        status = st.empty()
        log_box = st.empty()
        logs: list[str] = [f"Running sub-{subject.strip()} with stages: {', '.join(selected)}\n"]
        completed: set[str] = set()

        def callback(stage_name: str) -> None:
            if stage_name in selected and stage_name not in completed:
                completed.add(stage_name)
                pct = int((len(completed) / len(selected)) * 100)
                progress.progress(pct, text=f"Completed {len(completed)}/{len(selected)} stages")
                logs.append(f"[stage complete] {stage_name}\n")
                log_box.code("".join(logs))

        try:
            status.info("Pipeline running...")
            result = run_subject(
                normalized_subject,
                cfg,
                skip=skip if skip else None,
                force=force,
                config_path=cfg_path,
                progress_callback=callback,
            )
            logs.append(result.summary() + "\n")
            progress.progress(100, text="Done")
            status.success("Pipeline completed.")
            log_box.code("".join(logs))
            st.session_state["last_run_summary"] = {
                "subject": normalized_subject,
                "verdict": result.metrics.get("pilot_verdict", "unknown"),
                "n_trials": result.metrics.get("n_trials"),
                "dci_zinnen": result.metrics.get("dci_zinnen"),
                "p_task_vs_rest": result.metrics.get("p_task_vs_rest"),
            }
        except Exception as exc:
            status.error(f"Pipeline failed: {exc}")
            logs.append(str(exc) + "\n")
            log_box.code("".join(logs))

    summary = st.session_state.get("last_run_summary")
    if isinstance(summary, dict):
        st.markdown("### Last run summary")
        st.write(
            {
                "subject": summary.get("subject"),
                "pilot_verdict": summary.get("verdict"),
                "n_trials": summary.get("n_trials"),
                "dci_zinnen": summary.get("dci_zinnen"),
                "p_task_vs_rest": summary.get("p_task_vs_rest"),
            }
        )


def _results_section() -> None:
    st.subheader("Results")
    cfg_bundle = _active_cfg()
    if not cfg_bundle:
        st.info("Load a valid config first.")
        return
    _, cfg = cfg_bundle
    root = cfg.derivatives_root
    subjects = sorted([p.name.replace("sub-", "", 1) for p in root.glob("sub-*") if p.is_dir()]) if root.exists() else []
    if not subjects:
        st.info("No processed subjects found.")
        return
    default_subject = st.session_state.get("last_run_summary", {}).get("subject")
    default_index = subjects.index(default_subject) if default_subject in subjects else 0
    subject = st.selectbox("Subject", subjects, index=default_index)
    manifest_path = root / f"sub-{subject}" / "m9_orchestration" / f"sub-{subject}_run_manifest.json"
    if not manifest_path.exists():
        st.warning(f"Manifest not found: {manifest_path}")
        return

    manifest: dict[str, Any] = json.loads(manifest_path.read_text())
    metrics = manifest.get("metrics", {})
    verdict = metrics.get("pilot_verdict", "unknown")
    if verdict == "GO":
        st.success(f"Pilot verdict: {verdict}")
    elif verdict == "MARGINAL":
        st.warning(f"Pilot verdict: {verdict}")
    else:
        st.error(f"Pilot verdict: {verdict}")

    key_metrics = [
        "n_trials",
        "n_zinnen",
        "n_woorden",
        "n_rest",
        "dci_zinnen",
        "dci_woorden",
        "dci_rest",
        "p_task_vs_rest",
        "p_rayleigh_zinnen",
    ]
    rows = [{"metric": key, "value": metrics.get(key)} for key in key_metrics]
    st.table(rows)

    timings = manifest.get("params", {}).get("stage_timings_s", {})
    if timings:
        names = list(timings.keys())
        vals = [float(timings[k]) for k in names]
        fig, ax = plt.subplots(figsize=(8, 3))
        ax.bar(names, vals)
        ax.set_ylabel("seconds")
        ax.set_title(f"sub-{subject} stage timings")
        st.pyplot(fig)

    report_path = root / f"sub-{subject}" / "m8_reports" / f"sub-{subject}_report.html"
    st.markdown(f"**HTML report:** `{report_path}`")


def main() -> None:
    st.set_page_config(page_title="MOUS GUI", layout="wide")
    st.title("MOUS pipeline GUI (Streamlit)")
    _init_state()

    setup_tab, fetch_tab, run_tab, results_tab = st.tabs(["Setup", "Fetch", "Run", "Results"])
    with setup_tab:
        _setup_section()
    with fetch_tab:
        _fetch_section()
    with run_tab:
        _run_section()
    with results_tab:
        _results_section()


if __name__ == "__main__":
    main()
