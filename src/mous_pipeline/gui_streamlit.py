"""Streamlit GUI for MOUS pipeline workflow."""

from __future__ import annotations

import json
import re
import shutil
import subprocess
from pathlib import Path
from typing import Any

import matplotlib.pyplot as plt
import streamlit as st

from mous_pipeline.config import PipelineConfig, load_config
from mous_pipeline.m0_intake.repocli_rdr import build_repocli_get_command, remote_subject_path
from mous_pipeline.m9_orchestration.runner import run_subject

# ── Stage catalogue ──────────────────────────────────────────────────────────

CORE_STAGES = ["m1", "m2", "m3", "m4", "m4_trial", "m6a", "m7", "m8", "m9"]
OPTIONAL_STAGES = ["m5", "m6_extra", "m10", "m11", "m12"]
STAGES = CORE_STAGES + OPTIONAL_STAGES

STAGE_LABELS = {
    "m1":       "m1 — Parse events",
    "m2":       "m2 — Preprocess (notch / ICA / filter)",
    "m3":       "m3 — Epoch",
    "m4":       "m4 — Analytic signal + PSD",
    "m4_trial": "m4_trial — Pre-stim beta / N400m / trial table",
    "m5":       "m5 — Source reconstruction (needs FreeSurfer)",
    "m6a":      "m6a — Phase-gradient waves + DCI",
    "m6_extra": "m6_extra — CFC / FFT2D / rotational / flow-field detectors",
    "m10":      "m10 — fMRI (fMRIPrep + trial-wise GLM + MTG)",
    "m11":      "m11 — MEG-fMRI coupling regressions",
    "m12":      "m12 — Two-dipole null / source-space DCI validation",
    "m7":       "m7 — Permutation + circular stats",
    "m8":       "m8 — HTML + Quarto reports",
    "m9":       "m9 — Pilot gate (GO / MARGINAL / NO-GO)",
}

STAGE_DESCRIPTIONS = {
    "m1":       "Parse events TSV and validate trial structure.",
    "m2":       "Preprocess task/rest data: notch, resample, ICA, beta-band filter.",
    "m3":       "Epoch task data around event onsets.",
    "m4":       "Hilbert analytic signal + Welch PSD summaries.",
    "m4_trial": "Trial-level MEG metrics: pre-stim beta, N400m amplitude, block-aware trial table for R.",
    "m5":       "LCMV beamformer source reconstruction. Requires source.subjects_dir + FreeSurfer.",
    "m6a":      "Planar phase-gradient wave directions and directional consistency index (DCI).",
    "m6_extra": "Extra wave detectors: CFC (tensorpac), FFT2D, rotational, optical-flow.",
    "m10":      "Run fMRIPrep container + nilearn trial-wise GLM + left-MTG beta extraction.",
    "m11":      "Partial-Spearman + OLS coupling of MEG features against MTG BOLD betas.",
    "m12":      "Two-dipole confound null: compares real DCI to simulated sensor-mixing baseline.",
    "m7":       "Rayleigh + permutation significance for wave consistency across conditions.",
    "m8":       "Embedded-figure HTML dashboard + aim-specific Quarto reports.",
    "m9":       "Evaluate pilot gate criteria and return GO / MARGINAL / NO-GO verdict.",
}


# ── Session helpers ──────────────────────────────────────────────────────────

def _init_state() -> None:
    st.session_state.setdefault("config_path", "configs/pilot_A2002.yaml")
    st.session_state.setdefault("cfg", None)
    st.session_state.setdefault("cfg_loaded_path", None)
    st.session_state.setdefault("run_history", [])
    st.session_state.setdefault("remote_subject_options", [])
    st.session_state.setdefault("remote_subject_error", "")


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


def _smart_defaults(cfg: PipelineConfig) -> list[str]:
    """Return sensible default stage selection based on what is configured."""
    defaults = list(CORE_STAGES)
    if getattr(cfg, "wave_validation", None) and getattr(cfg.wave_validation, "enabled", False):
        defaults.append("m12")
    if getattr(cfg, "source", None) and getattr(cfg.source, "subjects_dir", ""):
        defaults.append("m5")
    fmri_cfg = getattr(cfg, "fmri", None)
    if fmri_cfg and getattr(fmri_cfg, "bold_path", ""):
        defaults += ["m10", "m11"]
    return [s for s in STAGES if s in defaults]


# ── Sidebar ──────────────────────────────────────────────────────────────────

def _sidebar() -> None:
    with st.sidebar:
        st.header("MOUS Pipeline")
        cfg_bundle = _active_cfg()

        if cfg_bundle:
            _, cfg = cfg_bundle
            data_ok = cfg.data_root.exists()
            st.success("Config loaded")
            st.markdown(f"**Config:** `{st.session_state['cfg_loaded_path'].name}`")
            st.markdown(
                f"**data\\_root:** {'✓' if data_ok else '⚠'} `{cfg.data_root}`",
            )
            st.markdown(f"**derivatives:** `{cfg.derivatives_root}`")
            if cfg.subjects:
                st.markdown(f"**subjects in config:** {', '.join(cfg.subjects)}")

            wave_ok = getattr(cfg, "wave_validation", None) and getattr(cfg.wave_validation, "enabled", False)
            fmri_ok = getattr(cfg, "fmri", None) and bool(getattr(cfg.fmri, "bold_path", ""))
            src_ok = getattr(cfg, "source", None) and bool(getattr(cfg.source, "subjects_dir", ""))
            st.markdown("**Optional stages ready:**")
            st.markdown(f"- m12 wave validation: {'enabled' if wave_ok else 'disabled'}")
            st.markdown(f"- m10/m11 fMRI: {'configured' if fmri_ok else 'not configured'}")
            st.markdown(f"- m5 source: {'configured' if src_ok else 'not configured'}")
        else:
            st.warning("No config loaded")
            st.markdown("Go to **Setup** tab to load a config.")

        st.divider()
        history = st.session_state.get("run_history", [])
        if history:
            st.markdown("**Recent runs:**")
            for entry in reversed(history[-5:]):
                color = "🟢" if entry["verdict"] == "GO" else ("🟡" if entry["verdict"] == "MARGINAL" else "🔴")
                st.markdown(f"{color} `{entry['subject']}` — {entry['verdict']}")


# ── Setup tab ────────────────────────────────────────────────────────────────

def _setup_section() -> None:
    st.header("Setup")

    col1, col2 = st.columns([3, 1])
    with col1:
        path_input = st.text_input(
            "Config file path",
            value=st.session_state["config_path"],
            help="Relative to repo root, or absolute. Tilde (~) is supported.",
        )
        st.session_state["config_path"] = path_input
    with col2:
        st.write("")
        st.write("")
        load_clicked = st.button("Load config", use_container_width=True)

    if load_clicked:
        result = _load_cfg(path_input)
        if result:
            st.success(f"Loaded: {result[0]}")

    cfg_bundle = _active_cfg()
    if cfg_bundle:
        _, cfg = cfg_bundle
        data_ok = cfg.data_root.exists()
        if not data_ok:
            st.warning(f"data_root does not exist yet: `{cfg.data_root}`  \nEnsure subjects are fetched or the path is correct in the YAML.")
        else:
            st.info(f"data_root exists: `{cfg.data_root}`")

    st.divider()
    st.subheader("One-time RDR credentials setup")
    repocli_ok = shutil.which("repocli") is not None
    st.markdown(f"**repocli on PATH:** {'yes' if repocli_ok else 'no — run `setup.sh` first'}")
    with st.expander("repocli one-time setup commands"):
        st.code(
            "repocli config\n"
            "  # baseurl: https://webdav.data.ru.nl\n"
            "  # Enter your RDR Data Access Credentials when prompted",
            language="bash",
        )

    st.divider()
    st.subheader("Quick-start configs")
    st.markdown(
        "| Config | Purpose |\n"
        "| --- | --- |\n"
        "| `configs/pilot_A2002.yaml` | Single pilot subject |\n"
        "| `configs/test_multi_A2003_A2006.yaml` | Multi-subject batch with wave validation |"
    )


# ── Fetch tab ────────────────────────────────────────────────────────────────

def _fetch_section() -> None:
    st.header("Fetch subjects from RDR")
    cfg_bundle = _active_cfg()
    repocli_ok = shutil.which("repocli") is not None

    if not repocli_ok:
        st.error("repocli is not on PATH. Run `bash setup.sh` and re-open the GUI.")
        return
    if not cfg_bundle:
        st.warning("Load a config first (Setup tab).")
        return

    _, cfg = cfg_bundle

    col_l, col_r = st.columns([1, 1])
    with col_l:
        if st.button("Load subject list from RDR", use_container_width=True):
            st.session_state["remote_subject_options"] = []
            st.session_state["remote_subject_error"] = ""
            if not cfg.rdr.collection_path:
                st.session_state["remote_subject_error"] = "rdr.collection_path is empty in config."
            else:
                cmd = ["repocli", "ls", cfg.rdr.collection_path.strip().strip("/")]
                proc = subprocess.run(cmd, capture_output=True, text=True, check=False)
                if proc.returncode != 0:
                    err = proc.stderr.strip() or proc.stdout.strip() or "unknown repocli error"
                    st.session_state["remote_subject_error"] = f"Failed to list subjects: {err}"
                else:
                    matches = sorted(set(re.findall(r"sub-[A-Za-z0-9_-]+", proc.stdout)))
                    st.session_state["remote_subject_options"] = [m.removeprefix("sub-") for m in matches]
        if st.session_state["remote_subject_error"]:
            st.warning(st.session_state["remote_subject_error"])

    with col_r:
        selected_from_list = st.multiselect(
            "Available subjects (from RDR list)",
            st.session_state["remote_subject_options"],
            default=[],
            key="selected_remote_subjects",
        )

    st.divider()
    manual = st.text_input("Or type subject ID manually", value="", placeholder="A2007")
    st.caption("Leading `sub-` is stripped automatically.")

    if st.button("Download selected", use_container_width=True, type="primary"):
        if not cfg.rdr.collection_path:
            st.error("rdr.collection_path is empty in config.")
            return
        chosen = [s.strip().removeprefix("sub-") for s in selected_from_list if s.strip()]
        if manual.strip():
            chosen.append(manual.strip().removeprefix("sub-"))
        if not chosen:
            st.error("Select at least one subject from the list or type an ID.")
            return

        log_box = st.empty()
        logs: list[str] = []
        failures: list[str] = []
        with st.spinner(f"Downloading {len(chosen)} subject(s)…"):
            for subj in chosen:
                cmd = build_repocli_get_command(
                    remote_path=remote_subject_path(cfg.rdr.collection_path, subj),
                    local_dir=cfg.data_root.resolve(),
                )
                logs.append(f"$ {' '.join(cmd)}\n")
                log_box.code("".join(logs), language="bash")
                proc = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True)
                assert proc.stdout is not None
                for line in proc.stdout:
                    logs.append(line)
                    log_box.code("".join(logs), language="bash")
                if proc.wait() != 0:
                    failures.append(subj)
                    logs.append(f"[error] sub-{subj} failed\n")
                else:
                    logs.append(f"[done] sub-{subj}\n")
                log_box.code("".join(logs), language="bash")
        if failures:
            st.error(f"Failed for: {', '.join(failures)}")
        else:
            st.success(f"Downloaded {len(chosen)} subject(s).")


# ── Run tab ──────────────────────────────────────────────────────────────────

def _run_one(subject: str, cfg, cfg_path: Path, skip: set[str], selected: list[str], force: bool) -> dict:
    """Run a single subject and return a summary dict."""
    progress = st.progress(0, text=f"Running sub-{subject}…")
    log_box = st.empty()
    logs: list[str] = [f"▶ sub-{subject}  stages: {', '.join(selected)}\n"]
    completed: set[str] = set()

    def callback(stage_name: str) -> None:
        if stage_name not in completed:
            completed.add(stage_name)
            pct = int(len(completed) / max(len(selected), 1) * 100)
            progress.progress(pct, text=f"sub-{subject}: {stage_name} done ({len(completed)}/{len(selected)})")
            logs.append(f"  ✓ {stage_name}\n")
            log_box.code("".join(logs))

    try:
        result = run_subject(
            subject, cfg,
            skip=skip if skip else None,
            force=force,
            config_path=cfg_path,
            progress_callback=callback,
        )
        logs.append(result.summary() + "\n")
        progress.progress(100, text=f"sub-{subject} — done")
        log_box.code("".join(logs))
        return {
            "subject": subject,
            "verdict": result.metrics.get("pilot_verdict", "unknown"),
            "n_trials": result.metrics.get("n_trials"),
            "n_zinnen": result.metrics.get("n_zinnen"),
            "n_woorden": result.metrics.get("n_woorden"),
            "dci_zinnen": result.metrics.get("dci_zinnen"),
            "dci_zinnen_pooled": result.metrics.get("dci_zinnen_pooled"),
            "p_task_vs_rest": result.metrics.get("p_task_vs_rest"),
            "p_rayleigh_zinnen": result.metrics.get("p_rayleigh_zinnen"),
            "aim1_prestim_auc": result.metrics.get("aim1_prestim_auc"),
            "aim1_n400m_t": result.metrics.get("aim1_n400m_zinnen_vs_woorden_t"),
            "aim3_two_dipole_z": result.metrics.get("aim3_two_dipole_z"),
            "ok": True,
            "error": None,
        }
    except Exception as exc:
        progress.empty()
        logs.append(f"[ERROR] {exc}\n")
        log_box.code("".join(logs))
        return {"subject": subject, "verdict": "ERROR", "ok": False, "error": str(exc)}


def _run_section() -> None:
    st.header("Run pipeline")
    cfg_bundle = _active_cfg()
    if not cfg_bundle:
        st.warning("Load a config first (Setup tab).")
        return
    cfg_path, cfg = cfg_bundle

    # ── Mode selector ────────────────────────────────────────────────────────
    mode = st.radio("Mode", ["Single subject", "Batch (all config subjects)"], horizontal=True)

    if mode == "Single subject":
        subject_input = st.text_input("Subject ID", value="A2002", help="e.g. A2003 — leading sub- stripped automatically")
        subjects_to_run = [subject_input.strip().removeprefix("sub-")]
    else:
        if not cfg.subjects:
            st.warning("No subjects listed in config. Add a `subjects:` list to the YAML or use Single subject mode.")
            return
        subjects_to_run = [s.strip().removeprefix("sub-") for s in cfg.subjects if s.strip()]
        st.info(f"Will run: {', '.join(subjects_to_run)}")

    st.divider()

    # ── Stage selector ───────────────────────────────────────────────────────
    st.subheader("Stage selection")
    default_stages = _smart_defaults(cfg)
    col_a, col_b = st.columns(2)
    with col_a:
        st.caption("**Core stages**")
        core_sel = st.multiselect(
            "Core", CORE_STAGES,
            default=[s for s in default_stages if s in CORE_STAGES],
            format_func=lambda s: STAGE_LABELS[s],
            key="core_stage_sel",
            label_visibility="collapsed",
        )
    with col_b:
        st.caption("**Optional stages** (auto-selected based on config)")
        opt_sel = st.multiselect(
            "Optional", OPTIONAL_STAGES,
            default=[s for s in default_stages if s in OPTIONAL_STAGES],
            format_func=lambda s: STAGE_LABELS[s],
            key="opt_stage_sel",
            label_visibility="collapsed",
        )
    selected = core_sel + opt_sel

    with st.expander("Stage descriptions"):
        for s in selected:
            st.markdown(f"**{STAGE_LABELS[s]}** — {STAGE_DESCRIPTIONS[s]}")

    force = st.checkbox("Force recompute (ignore cached outputs)", value=False)

    st.divider()
    if st.button("Run pipeline", type="primary", use_container_width=True):
        if not selected:
            st.error("Select at least one stage.")
            return
        if not subjects_to_run or not subjects_to_run[0]:
            st.error("Subject ID is required.")
            return

        skip = set(STAGES) - set(selected)
        history: list[dict] = st.session_state.get("run_history", [])

        for subj in subjects_to_run:
            st.markdown(f"---\n#### sub-{subj}")
            summary = _run_one(subj, cfg, cfg_path, skip, selected, force)
            history.append(summary)
            if summary["ok"]:
                v = summary["verdict"]
                fn = st.success if v == "GO" else (st.warning if v == "MARGINAL" else st.error)
                fn(f"sub-{subj}: {v}")
            else:
                st.error(f"sub-{subj}: pipeline error — {summary['error']}")

        st.session_state["run_history"] = history

        # ── Batch summary table ──────────────────────────────────────────────
        if len(subjects_to_run) > 1:
            st.divider()
            st.subheader("Batch summary")
            rows = []
            for h in [e for e in history if e["subject"] in subjects_to_run]:
                rows.append({
                    "subject": h["subject"],
                    "verdict": h.get("verdict"),
                    "n_trials": h.get("n_trials"),
                    "dci_zinnen": _fmt(h.get("dci_zinnen")),
                    "p_task_vs_rest": _fmt(h.get("p_task_vs_rest")),
                    "aim1_prestim_auc": _fmt(h.get("aim1_prestim_auc")),
                    "aim3_two_dipole_z": _fmt(h.get("aim3_two_dipole_z")),
                })
            st.dataframe(rows, use_container_width=True)


def _fmt(v: Any) -> str:
    if v is None:
        return "—"
    if isinstance(v, float):
        return f"{v:.4f}"
    return str(v)


# ── Results tab ──────────────────────────────────────────────────────────────

def _results_section() -> None:
    st.header("Results")
    cfg_bundle = _active_cfg()
    if not cfg_bundle:
        st.info("Load a valid config first.")
        return
    _, cfg = cfg_bundle

    root = cfg.derivatives_root
    if not root.exists():
        st.info(f"No derivatives found yet at `{root}`.")
        return

    sub_dirs = sorted([p for p in root.iterdir() if p.is_dir() and p.name.startswith("sub-")])
    if not sub_dirs:
        st.info("No processed subjects found.")
        return

    subjects = [p.name for p in sub_dirs]  # keep full "sub-XXXX" name
    last = st.session_state.get("run_history")
    last_subject = f"sub-{last[-1]['subject']}" if last else None
    default_index = subjects.index(last_subject) if last_subject in subjects else 0

    sub_dir_name = st.selectbox("Subject", subjects, index=default_index)
    sub_dir = root / sub_dir_name
    subject_id = sub_dir_name.removeprefix("sub-")

    manifest_path = sub_dir / "m9_orchestration" / f"{sub_dir_name}_run_manifest.json"
    if not manifest_path.exists():
        st.warning(f"Manifest not found: `{manifest_path}`")
        return

    manifest: dict[str, Any] = json.loads(manifest_path.read_text())
    metrics = manifest.get("metrics", {})

    # ── Verdict banner ───────────────────────────────────────────────────────
    verdict = metrics.get("pilot_verdict", "unknown")
    (st.success if verdict == "GO" else st.warning if verdict == "MARGINAL" else st.error)(
        f"Pilot verdict: **{verdict}**"
    )

    # ── Metrics columns ──────────────────────────────────────────────────────
    st.subheader("Key metrics")
    c1, c2, c3 = st.columns(3)
    with c1:
        st.metric("Trials", metrics.get("n_trials", "—"))
        st.metric("ZINNEN", metrics.get("n_zinnen", "—"))
        st.metric("WOORDEN", metrics.get("n_woorden", "—"))
    with c2:
        st.metric("DCI ZINNEN", _fmt(metrics.get("dci_zinnen_pooled") or metrics.get("dci_zinnen")))
        st.metric("DCI WOORDEN", _fmt(metrics.get("dci_woorden_pooled") or metrics.get("dci_woorden")))
        st.metric("p task vs rest", _fmt(metrics.get("p_task_vs_rest")))
    with c3:
        st.metric("Rayleigh p (ZINNEN)", _fmt(metrics.get("p_rayleigh_zinnen")))
        st.metric("Aim1 prestim AUC", _fmt(metrics.get("aim1_prestim_auc")))
        st.metric("Aim3 two-dipole z", _fmt(metrics.get("aim3_two_dipole_z")))

    # ── Stage timings chart ──────────────────────────────────────────────────
    timings = manifest.get("params", {}).get("stage_timings_s") or metrics.get("stage_timings_s", {})
    if timings:
        st.subheader("Stage timings")
        names = list(timings.keys())
        vals = [float(timings[k]) for k in names]
        fig, ax = plt.subplots(figsize=(9, 3))
        ax.barh(names, vals)
        ax.set_xlabel("seconds")
        ax.set_title(f"{sub_dir_name} stage timings")
        plt.tight_layout()
        st.pyplot(fig)
        plt.close(fig)

    # ── Output links ────────────────────────────────────────────────────────
    st.subheader("Output files")
    report_html = sub_dir / "m8_reports" / f"{sub_dir_name}_report.html"
    trials_csv = sub_dir / "m8_reports" / "exports" / f"{subject_id}_trials.csv"
    metrics_json = sub_dir / "m8_reports" / "exports" / f"{subject_id}_metrics.json"

    for label, path in [
        ("HTML report", report_html),
        ("trials.csv", trials_csv),
        ("metrics.json", metrics_json),
    ]:
        exists = path.exists()
        st.markdown(f"{'✓' if exists else '·'} **{label}:** `{path}`")

    # ── Full metrics expander ────────────────────────────────────────────────
    with st.expander("All metrics"):
        st.json(metrics)


# ── Entry point ──────────────────────────────────────────────────────────────

def main() -> None:
    st.set_page_config(page_title="MOUS Pipeline", layout="wide")
    _init_state()
    _sidebar()

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
