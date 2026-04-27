# TODO: Full Pipeline with M5 Source Reconstruction

## Why M5 Matters

Current results show near-identical DCI values across ZINNEN (~0.017), WOORDEN (~0.017),
and REST (~0.017) for all subjects — no condition separation at all. This is expected:
the DCI is computed from sensor-level MEG phase directions across ~300 channels, which
dilutes any region-specific language signal. M5 projects the data into source space using
an LCMV beamformer, letting the DCI be computed from language-relevant cortical vertices
only. This should produce meaningful task vs rest and ZINNEN vs WOORDEN separation.

The pipeline code for M5 is fully implemented. The only blocker is FreeSurfer outputs.

---

## Directory Structure

```
~/mous_data/                          ← BIDS raw data (outside repo)
  sub-A2002/
    anat/sub-A2002_T1w.nii            ← Input to recon-all (1mm isotropic, 192×256×256)
    meg/...
  sub-A2003/
    ...

~/MOUS/Sandbox/MOUS/                  ← Git repo root
  configs/
    cohort_15subjects_fmri.yaml       ← Main cohort config (edit source.subjects_dir here)
  scripts/
    analysis_00_hpc_setup.sh          ← Creates/checks HPC directories and can submit jobs
    analysis_01_cohort_fetch_and_run.sh
    analysis_02_freesurfer_recon.sh   ← FreeSurfer recon-all array job
  derivatives/
    freesurfer/                       ← recon-all outputs go here (create this)
      sub-A2002/
        mri/
        surf/
        label/
        ...
      sub-A2003/
      ...
    fmriprep/                         ← fMRIPrep outputs (already populated for A2002/A2003)
    mous_pipeline/                    ← Per-subject pipeline manifests and features
      A2002/
        m4_features/
        m5_source/                    ← Source dirs + DCI written here after M5 runs
        m9_orchestration/sub-A2002_run_manifest.json
      ...
```

---

## Step 0 — Prepare HPC Workspace

**Script added:** `scripts/analysis_00_hpc_setup.sh`

Run this on the SLURM login node from the repository root:

```bash
bash scripts/analysis_00_hpc_setup.sh --check-data
```

The setup script creates the expected HPC-side directories:

```bash
logs/
derivatives/freesurfer/
derivatives/mous_pipeline/
derivatives/fmriprep/
derivatives/coreg/
```

It also verifies that:
- `configs/cohort_15subjects_fmri.yaml` exists and points `source.subjects_dir` at `derivatives/freesurfer`,
- the FreeSurfer license exists at `$FS_LICENSE` or `/data/freesurfer/license.txt`,
- `sbatch`, `mous-pipeline`, and the `freesurfer/7.4.1` module are visible where possible,
- all subject T1w images exist when `--check-data` is passed.

Optional submission helpers:

```bash
bash scripts/analysis_00_hpc_setup.sh --submit-recon
bash scripts/analysis_00_hpc_setup.sh --check-freesurfer
bash scripts/analysis_00_hpc_setup.sh --submit-cohort
```

Use `--dry-run` with any of those flags to preview filesystem/submission actions.

---

## Step 1 — Run FreeSurfer recon-all (per subject, ~6–8h each)

**Script added:** `scripts/analysis_02_freesurfer_recon.sh`

SLURM array job, one task per subject (array=0-12 matching the cohort list).
Each task runs:
```
recon-all -s sub-AXXX -i ~/mous_data/sub-AXXX/anat/sub-AXXX_T1w.nii \
          -sd derivatives/freesurfer -all
```

Key SLURM resources: `--time=12:00:00`, `--mem=16G`, `--cpus-per-task=4`
Module to load: `freesurfer/7.4.1`

FreeSurfer needs a license file at `$FREESURFER_HOME/license.txt` — the pipeline
already uses `/data/freesurfer/license.txt` for fMRIPrep, same file applies.

**After completion**, verify each subject has:
```
derivatives/freesurfer/sub-AXXX/mri/brain.mgz
derivatives/freesurfer/sub-AXXX/surf/lh.white
derivatives/freesurfer/sub-AXXX/surf/rh.white
```

---

## Step 2 — Update Config

In `configs/cohort_15subjects_fmri.yaml`, set:

```yaml
source:
  subjects_dir: "derivatives/freesurfer"   # was ""
  use_fsaverage: true                       # keep true for now (see note below)
  trans: "fsaverage"                        # keep for now (see note below)
```

The `use_fsaverage: true` + `trans: fsaverage` combination uses the fsaverage template
transform rather than a subject-specific MEG→MRI coregistration. This is an approximation
but avoids needing `.fif` trans files for each subject. For publication-quality results,
do Step 3 below.

---

## Step 3 (Optional but Recommended) — Subject-Specific Coregistration

For each subject, a MEG→MRI transform (`.fif` file) should be computed using MNE's
coregistration GUI or automated head-point fitting. The CTF `.ds` directories contain
head position (`*.hc`) files that MNE can use.

**Script to write:** `scripts/analysis_03_coregister.sh`

Runs `mne coreg` in batch mode per subject, writing:
```
derivatives/coreg/sub-AXXX-trans.fif
```

Then update config:
```yaml
source:
  use_fsaverage: false
  trans: "derivatives/coreg/sub-{subject}-trans.fif"
```

The runner now expands `{subject}` and `{subject_bids}` in the trans path.

---

## Step 4 — Rerun the Full Cohort with M5

`scripts/analysis_01_cohort_fetch_and_run.sh` now runs m5 by default:

```bash
# Change:
mous-pipeline run --config "${CONFIG}" --subject "${SID}" --skip m5

# To:
mous-pipeline run --config "${CONFIG}" --subject "${SID}"
```

The `verify-run` call now uses `--require-m5`.

Resubmit: `sbatch scripts/analysis_01_cohort_fetch_and_run.sh`

M5 adds ~10–20 min per subject on top of the existing runtime. Raise
`--time` to `06:00:00` to be safe.

---

## Step 5 — Run Group Inference

Once all subjects complete:

```bash
mous-pipeline group --derivatives-root derivatives/mous_pipeline
```

With real source-space DCI values, expect:
- `dci_zinnen` and `dci_woorden` clearly above `dci_rest`
- Wilcoxon on coupling r values potentially significant for prestim_beta or n400m

---

## Cloud Contributions — Directory Notes

If contributors are running recon-all remotely (e.g. on a university HPC or cloud VM)
and syncing results back, they only need to transfer the FreeSurfer output directories:

```
derivatives/freesurfer/sub-AXXX/
```

The minimum required subdirectories for the pipeline to run M5 are:
```
sub-AXXX/
  mri/
    brain.mgz         ← BEM surface input
    T1.mgz
  surf/
    lh.white          ← Source space
    rh.white
    lh.pial
    rh.pial
  label/
    lh.aparc.annot    ← For label-based ROI extraction
    rh.aparc.annot
  bem/                ← Optional: pre-computed BEM surfaces speed things up
```

Suggested transfer command (from remote to this machine):
```bash
rsync -avz remote:/path/to/derivatives/freesurfer/sub-AXXX \
      ~/MOUS/Sandbox/MOUS/derivatives/freesurfer/
```

Raw data (`~/mous_data/`) and pipeline derivatives (`derivatives/mous_pipeline/`,
`derivatives/fmriprep/`) should stay local — they are too large and not needed
by collaborators running only M5.

The repo itself (`~/MOUS/Sandbox/MOUS/`) is on GitHub at
`github.com/JonathanWade24/MOUS` — contributors should clone this and point
`configs/cohort_15subjects_fmri.yaml` at their local data paths.

---

## Summary Checklist

- [x] Add `analysis_00_hpc_setup.sh` for HPC directory setup, checks, and optional submission
- [x] Add `analysis_02_freesurfer_recon.sh` (array=0-12, ~6-8h per subject)
- [ ] Verify recon-all outputs: `brain.mgz`, `lh.white`, `rh.white` for all 13 subjects
- [x] Set `source.subjects_dir: "derivatives/freesurfer"` in config
- [x] Remove `--skip m5` from `analysis_01_cohort_fetch_and_run.sh`
- [x] Raise SLURM `--time` to `06:00:00`
- [ ] Resubmit cohort job
- [ ] Run `run-group` for cohort-level inference
- [x] Add subject-specific coregistration trans-path expansion for publication-quality runs
- [ ] (Optional) Generate subject-specific coregistration `.fif` files for publication quality
