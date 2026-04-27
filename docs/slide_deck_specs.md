# Slide Deck Specs: MOUS Pipeline — 10-Minute Talk

**Format:** ~12 slides, 45–60 seconds each  
**Audience:** Researchers / lab members familiar with MEG/fMRI but not necessarily the codebase  
**Tone:** Technical but accessible — show the tool working, not just describe it

---

## Slide 1 — Title
**"MOUS Pipeline: Automated MEG–fMRI Analysis from Raw Data to Group Inference"**

- Subtitle: *From RDR download to cohort-level stats in a single command*
- Your name, date, lab affiliation

---

## Slide 2 — The Problem
**What we had to do by hand**

- Download subjects one at a time from Radboud Data Repository
- Run MEG preprocessing, epoching, feature extraction in separate scripts
- Manually track which subjects passed QC
- No standardised coupling analysis between MEG and fMRI
- No way to run the whole cohort reproducibly overnight

**One sentence:** *Every step was a manual handoff, and nothing was reproducible end-to-end.*

---

## Slide 3 — What the Pipeline Does
**13 stages, one command**

Show a simple linear diagram:

```
Raw RDR data
    ↓ fetch-rdr
m1  Events parsing
m2  MEG preprocessing + ICA
m3  Epoching
m4  Feature extraction (prestim beta, N400m, DCI)
[m5 Source reconstruction — skipped until FreeSurfer]
m6  Wave analysis (DCI, Rayleigh test)
m7  Subject-level statistics
m8  Reports + exports
m9  Orchestration / manifest
m10 fMRI preprocessing (fMRIPrep)
m11 MEG–fMRI coupling (partial Spearman)
m12 Wave-validation null model
    ↓
Pilot gate: GO / MARGINAL / NO-GO
```

*Each stage writes a manifest entry — every run is traceable.*

---

## Slide 4 — The Data
**MOUS: Mother Of all Unification Studies**

- Radboud University, Donders Institute
- Simultaneous MEG + fMRI during auditory language task
- Two conditions: **ZINNEN** (sentences) and **WOORDEN** (word lists)
- Plus a resting-state run
- 13 subjects in this cohort (A2002–A2027)
- Data fetched directly from RDR via `repocli`

*Key ROI: left MTG (Glasser atlas, L_TE1a) — language-responsive region*

---

## Slide 5 — Running It
**One script, 13 subjects in parallel**

```bash
sbatch scripts/analysis_01_cohort_fetch_and_run.sh
```

Show the SLURM array structure:
- `--array=0-12` → 13 independent jobs, one per subject
- Each job: fetch if missing → run all stages → verify manifest
- 4–45 min per subject depending on whether fMRIPrep needs to run
- Email notification on completion/failure

*Demo or screenshot: `squeue -u $USER` showing 13 tasks running*

---

## Slide 6 — The Pilot Gate
**Automated GO / MARGINAL / NO-GO per subject**

Four criteria, all must pass for GO:

| Criterion | What it checks |
|-----------|---------------|
| `dci_significant` | DCI p-value < 0.05 (task-evoked neural response) |
| `min_zinnen_epochs` | ≥ 50 clean sentence trials survived preprocessing |
| `task_gt_rest` | Task DCI > rest DCI (not just noise) |
| `task_nonuniform_direction` | Rayleigh test: consistent phase across trials |

Current cohort: **10 MARGINAL, 1 NO-GO (A2004), 0 GO**  
→ Interpretation: pilot data, synthetic/stub fMRI; expect GO verdicts with real fMRIPrep outputs

---

## Slide 7 — MEG–fMRI Coupling (m11)
**The core scientific question**

Does pre-stimulus beta power / N400m amplitude / trial-level DCI predict MTG BOLD response?

- Per subject: **partial Spearman correlation** (feature vs MTG beta, controlling for position in block)
- Computed separately for ZINNEN and WOORDEN
- 6 coupling coefficients per subject (3 features × 2 conditions)
- Plus a pooled OLS with subject fixed effect at group level

```
zinnen_prestim_beta_vs_mtg  →  r, p
zinnen_n400m_vs_mtg         →  r, p
zinnen_dci_trial_vs_mtg     →  r, p
woorden_...                 →  r, p  (×3)
```

---

## Slide 8 — Group Inference (m7 group)
**One command after all subjects complete**

```bash
run-group   # alias for: mous-pipeline group --derivatives-root derivatives/mous_pipeline
```

Outputs:
- One-sample **Wilcoxon signed-rank** test on each coupling r across subjects (H₀: r = 0)
- **Pooled OLS** with subject fixed effect across all trial rows
- m12 wave-validation z-score aggregation
- Pilot verdict counts (GO/MARGINAL/NO-GO)

*This is what tells us whether the coupling effects are consistent across the cohort.*

---

## Slide 9 — Reproducibility & BIDS
**Built for replication**

- Full **BIDS-compliant** dataset structure — validated with `bids-validator` before every fMRIPrep run
- Config fingerprint stored in every manifest (SHA of the YAML at run time)
- Stage-level caching: re-run from any stage without redoing upstream work
- `force=True` flag to override cache when needed
- `verify-run` command checks manifest completeness post-hoc
- All scripts follow `analysis_NN_description.sh` naming convention

*Show: a manifest JSON snippet with timestamp, config fingerprint, stage timings*

---

## Slide 10 — What We Fixed Along the Way
**Honest engineering slide**

Real issues encountered and resolved during the cohort run:

| Issue | Fix |
|-------|-----|
| BIDS validator rejecting MEG channel types | `normalize_channels_tsv.py` — batch-fixed 27 files |
| `space-CTF` T1w not valid BIDS | `.bidsignore` (CTF-space MRI is for MEG coregistration, not fMRIPrep) |
| ICA crash when no ECG components found | Guard + index fix in `ica.py` |
| Stale feature cache after epoch count change | Cache now validates array length vs trial metadata |
| `nilearn` missing from pipeline environment | `pip install nilearn` |

*Point: the pipeline surfaces these problems clearly rather than silently producing bad results.*

---

## Slide 11 — Current Results Snapshot
**13-subject cohort, job 46 in progress**

| Metric | Value |
|--------|-------|
| Subjects attempted | 13 |
| Manifests produced | 12 (A2009 pending) |
| Pilot verdicts | 10 MARGINAL, 1 NO-GO |
| Mean DCI (ZINNEN) | ~0.017–0.019 |
| Mean m12 z-score | −0.01 to −0.34 (inside null CI) |
| fMRIPrep | Running for first time with clean BIDS validation |

*Next step: run `run-group` once job 46 completes for cohort-level coupling statistics*

---

## Slide 12 — What's Next
**Roadmap**

- **m5 source reconstruction** — once FreeSurfer recon-all is available
- **Real fMRIPrep outputs** → coupling r values with actual variance (currently stub zeros)
- **Group inference results** — Wilcoxon on coupling r, pooled OLS
- **Expand cohort** — full MOUS N (multiple subsets available on RDR)
- **Streamlit GUI** (`mous-pipeline gui`) — point-and-click interface for non-coders

---

## Presenter Notes

- **Slide 5** is the best place for a live terminal demo if the job happens to be running
- **Slide 7** is the most scientifically interesting — linger here if audience is research-focused
- **Slide 10** is good for a methods/reproducibility-focused audience; can be cut for a pure science talk
- Total runtime target: 10 min + 2 min questions
