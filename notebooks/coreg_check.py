#!/usr/bin/env python
"""
coreg_check.py — Coregistration quality check for sub-A2002

Loads the saved task epochs (just needs dig info), re-runs the fsaverage
template coregistration, and reports two quality metrics:

  1. Sensor-to-scalp distances  (the main numeric QC metric)
  2. 3D alignment figure         →  sub-A2002_coreg_alignment.png

Run from inside sub-A2002/:
    python ../notebooks/coreg_check.py

Interpretation of sensor-to-scalp distances:
  < 15 mm  → good; template coreg is usable for beamforming
  15-30 mm → marginal; forward model will have some localisation error
  > 30 mm  → poor; consider ICP fitting or subject-specific MRI
"""
import os
import sys
import numpy as np
import mne
from mne.coreg import Coregistration
from mne.transforms import apply_trans
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt

# ── Config (edit if running from a different directory) ────────────────────
SUBJECT    = 'A2002'
EPOCHS_FIF = f'sub-{SUBJECT}_task-auditory_beta-epo.fif'
OUT_PNG    = f'sub-{SUBJECT}_coreg_alignment.png'

# ── Load epochs (preload=False — only need info/dig) ───────────────────────
if not os.path.exists(EPOCHS_FIF):
    sys.exit(f"ERROR: {EPOCHS_FIF} not found.\n"
             "Run this script from inside sub-A2002/ after completing Section 9 "
             "of MOUS_A2002_pilot.ipynb.")

print(f"Loading {EPOCHS_FIF} ...")
epochs = mne.read_epochs(EPOCHS_FIF, preload=False, verbose='WARNING')

from mne.io.constants import FIFF as _F
ident_names = {_F.FIFFV_POINT_LPA: 'LPA',
               _F.FIFFV_POINT_NASION: 'Nasion',
               _F.FIFFV_POINT_RPA: 'RPA'}
print(f"  Digitization points: {len(epochs.info['dig'])}")
for d in epochs.info['dig']:
    if d['kind'] == _F.FIFFV_POINT_CARDINAL:
        name = ident_names.get(d['ident'], f"cardinal-{d['ident']}")
        pos_mm = np.round(d['r'] * 1000, 1)
        print(f"    {name}: {pos_mm} mm (head coords)")

# ── fsaverage path ─────────────────────────────────────────────────────────
_fs_path = mne.datasets.fetch_fsaverage(verbose='WARNING')
if os.path.basename(_fs_path) == 'fsaverage':
    fsaverage_dir  = _fs_path
    coreg_subj_dir = os.path.dirname(_fs_path)
else:
    coreg_subj_dir = _fs_path
    fsaverage_dir  = os.path.join(_fs_path, 'fsaverage')
bem_dir = os.path.join(fsaverage_dir, 'bem')

# Ensure head surface file exists (same fix as notebook cell 42fafbcc)
head_fif = os.path.join(bem_dir, 'fsaverage-head.fif')
if not os.path.exists(head_fif):
    print("Creating fsaverage-head.fif from BEM model ...")
    bem_model_path = os.path.join(bem_dir, 'fsaverage-5120-5120-5120-bem.fif')
    _surfs = mne.read_bem_surfaces(bem_model_path, verbose='WARNING')
    _head  = next((s for s in _surfs if s['id'] == _F.FIFFV_BEM_SURF_ID_HEAD), _surfs[0])
    mne.write_bem_surfaces(head_fif, [_head], verbose='WARNING')

# ── Coregistration ─────────────────────────────────────────────────────────
print("\nRunning coregistration (fit_fiducials) ...")
coreg = Coregistration(epochs.info, 'fsaverage', subjects_dir=coreg_subj_dir)
coreg.fit_fiducials(verbose='WARNING')
trans = coreg.trans

print("\nTransformation matrix (head → MRI, metres):")
T = trans['trans']
print(f"  Rotation:\n{np.round(T[:3,:3], 4)}")
print(f"  Translation (mm): {np.round(T[:3, 3] * 1000, 1)}")

# Rotation angle from identity — a rough sense of how much the head was rotated
import scipy.spatial.transform as _sst
rot_angle_deg = np.degrees(
    _sst.Rotation.from_matrix(T[:3, :3]).magnitude()
)
trans_mm = np.linalg.norm(T[:3, 3]) * 1000
print(f"\n  Net rotation : {rot_angle_deg:.1f}°")
print(f"  Net translation: {trans_mm:.1f} mm")

# ── Sensor-to-scalp distances ──────────────────────────────────────────────
print("\nComputing sensor-to-scalp distances ...")

# Load scalp mesh
head_surf = mne.read_bem_surfaces(head_fif, verbose='WARNING')[0]
scalp_verts = head_surf['rr']                   # (n_verts, 3), metres, MRI coords

# Sensor positions: head coords → MRI coords via trans
meg_picks = mne.pick_types(epochs.info, meg=True, exclude='bads')
sensor_pos_head = np.array([epochs.info['chs'][p]['loc'][:3] for p in meg_picks])
sensor_pos_mri  = apply_trans(trans, sensor_pos_head)

# Distance from each sensor to its nearest scalp vertex
dists_mm = np.array([
    np.min(np.linalg.norm(scalp_verts - s, axis=1))
    for s in sensor_pos_mri
]) * 1000

print(f"\n=== Sensor-to-scalp distances ({len(dists_mm)} sensors) ===")
print(f"  Mean   : {dists_mm.mean():.1f} mm")
print(f"  Median : {np.median(dists_mm):.1f} mm")
print(f"  Max    : {dists_mm.max():.1f} mm")
print(f"  95th % : {np.percentile(dists_mm, 95):.1f} mm")

if dists_mm.mean() < 15:
    verdict = "GOOD — usable for beamforming"
elif dists_mm.mean() < 30:
    verdict = "MARGINAL — localisation error expected; pilot use only"
else:
    verdict = "POOR — consider ICP fitting or subject-specific MRI"
print(f"\n  Verdict: {verdict}")

# ── 2D sensor position sanity check ───────────────────────────────────────
# Even without 3D rendering, a top-down view of sensor positions shows
# whether the CTF array geometry looks correct.
print("\nGenerating sensor position plot ...")
fig_2d, axes = plt.subplots(1, 2, figsize=(12, 5))

# Top-down (axial) view in head coordinates
ax = axes[0]
ax.scatter(sensor_pos_head[:, 0] * 100,
           sensor_pos_head[:, 1] * 100,
           s=8, c='steelblue', alpha=0.8)
for d in epochs.info['dig']:
    if d['kind'] == _F.FIFFV_POINT_CARDINAL:
        name = ident_names.get(d['ident'], '?')
        ax.scatter(d['r'][0]*100, d['r'][1]*100, s=60, marker='^',
                   c='red', zorder=5)
        ax.annotate(name, (d['r'][0]*100, d['r'][1]*100),
                    textcoords='offset points', xytext=(4, 4), fontsize=8)
ax.set_xlabel('X (cm, head coords)')
ax.set_ylabel('Y (cm, head coords)')
ax.set_title('Sensor layout — top view (head coords)')
ax.set_aspect('equal')
ax.grid(True, alpha=0.3)

# Sensor-to-scalp distance histogram
ax = axes[1]
ax.hist(dists_mm, bins=20, color='steelblue', edgecolor='white', alpha=0.8)
ax.axvline(dists_mm.mean(), color='red', lw=2,
           label=f'Mean = {dists_mm.mean():.1f} mm')
ax.axvline(15, color='orange', lw=1.5, ls='--', label='15 mm threshold')
ax.axvline(30, color='darkred', lw=1.5, ls='--', label='30 mm threshold')
ax.set_xlabel('Distance to nearest scalp vertex (mm)')
ax.set_ylabel('Number of sensors')
ax.set_title('Sensor-to-scalp distances')
ax.legend(fontsize=8)

fig_2d.suptitle(
    f'sub-{SUBJECT} coregistration check\n'
    f'Mean sensor-to-scalp: {dists_mm.mean():.1f} mm  ({verdict})',
    fontsize=10
)
plt.tight_layout()
plt.savefig(OUT_PNG, dpi=150, bbox_inches='tight')
print(f"Saved: {OUT_PNG}")

# ── 3D alignment (requires display / pyvista) ──────────────────────────────
try:
    print("\nAttempting 3D alignment plot (requires display) ...")
    fig_3d = mne.viz.plot_alignment(
        epochs.info,
        trans=trans,
        subject='fsaverage',
        subjects_dir=coreg_subj_dir,
        surfaces={'head': 0.4},
        meg='sensors',
        dig='fiducials',
        verbose='WARNING',
    )
    out_3d = OUT_PNG.replace('.png', '_3d.png')
    fig_3d.plotter.screenshot(out_3d)
    print(f"Saved 3D view: {out_3d}")
except Exception as e:
    print(f"  3D plot skipped ({type(e).__name__}: {e})")
    print("  The 2D plot + distance histogram are sufficient for QC.")

print("\nDone.")
