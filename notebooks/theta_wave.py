#!/usr/bin/env python
"""
theta_wave.py — Theta-band (4–8 Hz) traveling wave analysis for sub-A2002

Rationale: beta-band DCI was near noise floor at both sensor and source level.
Theta is motivated by the ~3–4 Hz syllable/word rate in Dutch sentences (MOUS).
If traveling waves exist during language processing, theta is the more likely
carrier band for hierarchical temporal integration.

This script runs the full pipeline independently of the beta notebook:
  1. Load raw CTF data
  2. Preprocessing (gradient comp, notch, resample, ICA)
  3. Theta bandpass (4–8 Hz)
  4. Epoch at Audio onset  (same windows as beta: -0.5 → 3.0 s)
  5. Sensor-level DCI  (same planar wave model)
  6. Source-level DCI  (LCMV beamformer, fsaverage template)
  7. Compare theta vs beta results (loads saved beta .npy files if present)
  8. Rose plots → sub-A2002_theta_wave_directions.png

Run from inside sub-A2002/:
    python ../notebooks/theta_wave.py
"""
import os
import sys
import subprocess
import gc
import numpy as np
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
from pathlib import Path
from scipy.signal import hilbert
from scipy.stats import circmean

# Ensure required packages are available
subprocess.run([sys.executable, '-m', 'pip', 'install', 'mne', 'mne-bids',
                'scikit-learn', 'pycircstat'], capture_output=True)

import mne
from mne.preprocessing import ICA
from mne.coreg import Coregistration
from mne.beamformer import make_lcmv, apply_lcmv_epochs
from sklearn.decomposition import PCA as _PCA

# ── Config ─────────────────────────────────────────────────────────────────
SUBJECT   = 'A2002'
MEG_DIR   = Path('meg')
TASK_DS   = MEG_DIR / f'sub-{SUBJECT}_task-auditory_meg.ds'
REST_DS   = MEG_DIR / f'sub-{SUBJECT}_task-rest_meg.ds'
EVENTS_TSV = MEG_DIR / f'sub-{SUBJECT}_task-auditory_events.tsv'

FREQ_BAND    = (4.0, 8.0)     # Hz — theta
TMIN, TMAX   = -0.5, 3.0
BASELINE     = (-0.5, 0.0)
CONDITION_IDS = {'ZINNEN': 1, 'WOORDEN': 2}

for p in [TASK_DS, REST_DS, EVENTS_TSV]:
    if not p.exists():
        sys.exit(f"ERROR: {p} not found. Run from inside sub-A2002/.")

# ── Helper functions (copied from pilot notebook) ──────────────────────────

def parse_events(tsv_path):
    import pandas as pd
    df = pd.read_csv(tsv_path, sep='\t').sort_values('onset').reset_index(drop=True)
    cond_col, current = [], None
    for _, row in df.iterrows():
        if row['type'] == 'Picture' and row['value'] in ('ZINNEN', 'WOORDEN'):
            current = row['value']
        cond_col.append(current)
    df['condition'] = cond_col
    audio = df[(df['type'] == 'Nothing') &
               (df['value'].str.contains('Audio onset', na=False))].copy()
    audio = audio.dropna(subset=['condition']).reset_index(drop=True)
    return audio[['onset', 'sample', 'condition']]


def get_sensor_positions(info):
    picks = mne.pick_types(info, meg=True, exclude='bads')
    pos = np.array([info['chs'][p]['loc'][:3] for p in picks])
    return pos[:, :2], picks


def compute_wave_directions(data, sensor_xy):
    analytic   = hilbert(data, axis=1)
    phase      = np.angle(analytic)
    A          = np.column_stack([sensor_xy[:, 0], sensor_xy[:, 1],
                                   np.ones(len(sensor_xy))])
    k_vec      = np.linalg.pinv(A) @ phase
    kx, ky     = k_vec[0], k_vec[1]
    directions = np.arctan2(ky, kx)
    k_mag      = np.sqrt(kx**2 + ky**2)
    f_centre   = np.mean(FREQ_BAND)
    with np.errstate(divide='ignore', invalid='ignore'):
        speeds = np.where(k_mag > 1e-6, 2 * np.pi * f_centre / k_mag, np.nan)
    return directions, speeds


def dci(directions):
    return float(np.abs(np.mean(np.exp(1j * directions))))


def epochs_to_dci(epochs_obj, sensor_xy, picks, label=''):
    data = epochs_obj.get_data(picks=picks)
    all_dci, all_dirs = [], []
    for ep in data:
        dirs, _ = compute_wave_directions(ep, sensor_xy)
        all_dirs.append(dirs)
        all_dci.append(dci(dirs))
    dci_arr = np.array(all_dci)
    dirs_pooled = np.concatenate(all_dirs)
    print(f"  {label}: {len(data)} epochs  DCI = {dci_arr.mean():.4f} ± "
          f"{dci_arr.std()/np.sqrt(len(dci_arr)):.4f}")
    return dirs_pooled, dci_arr


def permutation_test(a, b, n=5000, seed=42):
    rng = np.random.default_rng(seed)
    obs = a.mean() - b.mean()
    pooled = np.concatenate([a, b])
    null = [rng.permutation(pooled)[:len(a)].mean() -
            rng.permutation(pooled)[len(a):].mean() for _ in range(n)]
    return obs, float(np.mean(np.array(null) >= obs))


def rose_plot(ax, angles, title, color, n_bins=36):
    bin_edges   = np.linspace(-np.pi, np.pi, n_bins + 1)
    counts, _   = np.histogram(angles, bins=bin_edges)
    centres     = 0.5 * (bin_edges[:-1] + bin_edges[1:])
    width       = 2 * np.pi / n_bins
    ax.bar(centres, counts / counts.max(), width=width * 0.9,
           color=color, alpha=0.7, edgecolor='white', linewidth=0.5)
    mean_dir = circmean(angles)
    dci_val  = dci(angles)
    ax.annotate('', xy=(mean_dir, dci_val), xytext=(0, 0),
                arrowprops=dict(arrowstyle='->', color='black', lw=2))
    ax.set_theta_zero_location('E')
    ax.set_theta_direction(1)
    ax.set_title(f'{title}\nDCI={dci_val:.4f}', pad=12, fontsize=9)
    ax.set_rticks([])
    ax.set_xticks(np.radians([0, 90, 180, 270]))
    ax.set_xticklabels(['Ant', 'L', 'Post', 'R'], fontsize=7)

# ── 1. Load + preprocess task raw ─────────────────────────────────────────
print("=" * 60)
print("THETA WAVE ANALYSIS — sub-A2002")
print(f"Band: {FREQ_BAND[0]}–{FREQ_BAND[1]} Hz")
print("=" * 60)

print("\n[1] Loading task raw ...")
raw = mne.io.read_raw_ctf(str(TASK_DS), preload=True,
                            system_clock='truncate', verbose='WARNING')
raw.apply_gradient_compensation(3)
raw.notch_filter(freqs=[50, 100, 150], picks='meg', verbose='WARNING')
raw.resample(300, npad='auto')
print(f"    Resampled → {raw.info['sfreq']} Hz")

# ICA on broadband copy
print("\n[2] Fitting ICA ...")
raw_ica = raw.copy()
raw_ica.filter(1, 100, method='fir', fir_window='hamming', verbose='WARNING')
ica = ICA(n_components=40, random_state=42, method='fastica', max_iter='auto')
ica.fit(raw_ica, picks='meg')

ecg_idx, ecg_scores = ica.find_bads_ecg(raw, method='correlation', threshold=0.9)
if len(ecg_idx) > 3:
    top3 = sorted(range(len(ecg_scores)),
                  key=lambda i: abs(ecg_scores[i]), reverse=True)[:3]
    ecg_idx = [ecg_idx[i] for i in sorted(top3)]
try:
    eog_idx, _ = ica.find_bads_eog(raw)
except RuntimeError:
    eog_idx = []
ica.exclude = list(set(ecg_idx + eog_idx))
print(f"    Excluded {len(ica.exclude)} components: {ica.exclude}")

del raw_ica
gc.collect()
ica.apply(raw)

# Theta filter
print(f"\n[3] Theta bandpass ({FREQ_BAND[0]}–{FREQ_BAND[1]} Hz) ...")
raw.filter(FREQ_BAND[0], FREQ_BAND[1], picks='meg',
           method='fir', fir_window='hamming', verbose='WARNING')
raw_theta = raw

# ── 2. Parse events + epoch ────────────────────────────────────────────────
import pandas as pd
print("\n[4] Parsing events ...")
all_trials = parse_events(EVENTS_TSV)
print(f"    {len(all_trials)} audio onsets  "
      f"({all_trials['condition'].value_counts().to_dict()})")

events_array = np.column_stack([
    (all_trials['onset'] * raw_theta.info['sfreq']).round().astype(int),
    np.zeros(len(all_trials), dtype=int),
    all_trials['condition'].map(CONDITION_IDS).astype(int)
])

print("\n[5] Epoching ...")
epochs = mne.Epochs(
    raw_theta, events_array, event_id=CONDITION_IDS,
    tmin=TMIN, tmax=TMAX, baseline=BASELINE,
    picks='meg', preload=True,
    reject={'mag': 4e-12}, flat={'mag': 1e-15},
    reject_by_annotation=False, verbose='WARNING'
)
for cond in ('ZINNEN', 'WOORDEN'):
    n = len(epochs[cond])
    flag = '' if n >= 50 else '  ⚠ LOW'
    print(f"    {cond}: {n} epochs{flag}")

del raw, raw_theta
gc.collect()

# ── 3. Load + preprocess rest raw ─────────────────────────────────────────
print("\n[6] Loading rest raw ...")
raw_rest = mne.io.read_raw_ctf(str(REST_DS), preload=True,
                                 system_clock='truncate', verbose='WARNING')
raw_rest.apply_gradient_compensation(3)
raw_rest.notch_filter(freqs=[50, 100, 150], picks='meg', verbose='WARNING')
raw_rest.resample(300, npad='auto')
ica.apply(raw_rest)
raw_rest.filter(FREQ_BAND[0], FREQ_BAND[1], picks='meg',
                method='fir', fir_window='hamming', verbose='WARNING')

epoch_len = TMAX - TMIN
rest_events = mne.make_fixed_length_events(raw_rest, id=99,
                                             duration=epoch_len, overlap=0.0)
epochs_rest = mne.Epochs(
    raw_rest, rest_events, event_id={'rest': 99},
    tmin=0, tmax=epoch_len - 1/raw_rest.info['sfreq'],
    baseline=None, picks='meg', preload=True,
    reject={'mag': 4e-12}, verbose='WARNING'
)
print(f"    REST: {len(epochs_rest)} epochs")

del raw_rest
gc.collect()

# ── 4. Sensor-level DCI ────────────────────────────────────────────────────
print("\n[7] Sensor-level DCI ...")
sensor_xy, meg_picks = get_sensor_positions(epochs.info)

dirs_z, dci_z = epochs_to_dci(epochs['ZINNEN'],  sensor_xy, meg_picks, 'ZINNEN ')
dirs_w, dci_w = epochs_to_dci(epochs['WOORDEN'], sensor_xy, meg_picks, 'WOORDEN')
dirs_r, dci_r = epochs_to_dci(epochs_rest,        sensor_xy, meg_picks, 'REST   ')

diff_zr, p_zr = permutation_test(dci_z, dci_r)
diff_zw, p_zw = permutation_test(dci_z, dci_w)
print(f"\n  ZINNEN vs REST:    ΔDCI={diff_zr:+.4f}  p={p_zr:.4f}")
print(f"  ZINNEN vs WOORDEN: ΔDCI={diff_zw:+.4f}  p={p_zw:.4f}")

# ── 5. Source-level DCI ────────────────────────────────────────────────────
print("\n[8] Building forward model ...")
_fs_path = mne.datasets.fetch_fsaverage(verbose='WARNING')
if os.path.basename(_fs_path) == 'fsaverage':
    fsaverage_dir  = _fs_path
    coreg_subj_dir = os.path.dirname(_fs_path)
else:
    coreg_subj_dir = _fs_path
    fsaverage_dir  = os.path.join(_fs_path, 'fsaverage')
bem_dir = os.path.join(fsaverage_dir, 'bem')

# Ensure head surface exists
head_fif = os.path.join(bem_dir, 'fsaverage-head.fif')
if not os.path.exists(head_fif):
    from mne.io.constants import FIFF as _FIFF
    _surfs = mne.read_bem_surfaces(
        os.path.join(bem_dir, 'fsaverage-5120-5120-5120-bem.fif'), verbose='WARNING')
    _head  = next((s for s in _surfs if s['id'] == _FIFF.FIFFV_BEM_SURF_ID_HEAD), _surfs[0])
    mne.write_bem_surfaces(head_fif, [_head], verbose='WARNING')

coreg = Coregistration(epochs.info, 'fsaverage', subjects_dir=coreg_subj_dir)
coreg.fit_fiducials(verbose='WARNING')
trans = coreg.trans

src_path = os.path.join(bem_dir, 'fsaverage-ico-5-src.fif')
src = (mne.read_source_spaces(src_path, verbose='WARNING')
       if os.path.exists(src_path)
       else mne.setup_source_space('fsaverage', spacing='oct5',
                                    subjects_dir=coreg_subj_dir, verbose='WARNING'))

bem_sol_path = os.path.join(bem_dir, 'fsaverage-5120-5120-5120-bem-sol.fif')
bem_sol = (mne.read_bem_solution(bem_sol_path, verbose='WARNING')
           if os.path.exists(bem_sol_path)
           else mne.make_bem_solution(
               mne.make_bem_model('fsaverage', ico=4,
                                   subjects_dir=coreg_subj_dir, verbose='WARNING'),
               verbose='WARNING'))

fwd = mne.make_forward_solution(
    epochs.info, trans=trans, src=src, bem=bem_sol,
    meg=True, eeg=False, verbose='WARNING')
fwd = mne.convert_forward_solution(fwd, surf_ori=True, verbose='WARNING')
print(f"    Forward model: {fwd['nsource']} sources")

noise_cov = mne.compute_covariance(epochs, tmax=0.0, method='empirical', verbose='WARNING')
data_cov  = mne.compute_covariance(epochs, tmin=0.0, tmax=TMAX, method='empirical', verbose='WARNING')
filters   = make_lcmv(epochs.info, fwd, data_cov, reg=0.05,
                       noise_cov=noise_cov, pick_ori='max-power',
                       weight_norm='unit-noise-gain', verbose='WARNING')

src_pos    = np.vstack([s['rr'][s['inuse'].astype(bool)] for s in fwd['src']])
src_xy_2d  = _PCA(n_components=2).fit_transform(src_pos)

print("\n[9] Source-level DCI ...")

def source_epochs_to_dci(epochs_obj, filters, src_xy, label=''):
    all_dci, all_dirs = [], []
    for stc in apply_lcmv_epochs(epochs_obj, filters,
                                   return_generator=True, verbose=False):
        dirs, _ = compute_wave_directions(stc.data, src_xy)
        all_dci.append(dci(dirs))
        all_dirs.append(dirs)
    dci_arr = np.array(all_dci)
    dirs_out = np.concatenate(all_dirs)
    print(f"  {label}: {len(all_dci)} epochs  DCI = {dci_arr.mean():.4f} ± "
          f"{dci_arr.std()/np.sqrt(len(dci_arr)):.4f}")
    return dirs_out, dci_arr

dirs_src_z, dci_src_z = source_epochs_to_dci(epochs['ZINNEN'],  filters, src_xy_2d, 'ZINNEN  (src)')
dirs_src_w, dci_src_w = source_epochs_to_dci(epochs['WOORDEN'], filters, src_xy_2d, 'WOORDEN (src)')
dirs_src_r, dci_src_r = source_epochs_to_dci(epochs_rest,        filters, src_xy_2d, 'REST    (src)')

diff_zr_src, p_zr_src = permutation_test(dci_src_z, dci_src_r)
diff_zw_src, p_zw_src = permutation_test(dci_src_z, dci_src_w)

# ── 6. Summary table ───────────────────────────────────────────────────────
print("\n" + "=" * 60)
print("THETA RESULTS SUMMARY")
print("=" * 60)

print(f"\n{'Condition':<10} {'Sensor':>10} {'Source':>10}")
for label, ds, dsr in [('ZINNEN',  dci_z, dci_src_z),
                        ('WOORDEN', dci_w, dci_src_w),
                        ('REST',    dci_r, dci_src_r)]:
    print(f"{label:<10} {ds.mean():>10.4f} {dsr.mean():>10.4f}")

print(f"\nPermutation tests (source-level):")
print(f"  ZINNEN vs REST:    ΔDCI={diff_zr_src:+.4f}  p={p_zr_src:.4f}")
print(f"  ZINNEN vs WOORDEN: ΔDCI={diff_zw_src:+.4f}  p={p_zw_src:.4f}")

# Compare with beta results if available
beta_z_path = f'sub-{SUBJECT}_dirs_zinnen.npy'
if os.path.exists(beta_z_path):
    beta_z = np.load(beta_z_path)
    beta_w = np.load(f'sub-{SUBJECT}_dirs_woorden.npy')
    beta_r = np.load(f'sub-{SUBJECT}_dirs_rest.npy')
    print(f"\nBeta vs Theta sensor DCI comparison:")
    print(f"  {'Condition':<10} {'Beta':>8} {'Theta':>8}")
    for label, bd, td in [('ZINNEN',  dci(beta_z), dci_z.mean()),
                           ('WOORDEN', dci(beta_w), dci_w.mean()),
                           ('REST',    dci(beta_r), dci_r.mean())]:
        diff_flag = '↑' if td > bd + 0.001 else ('↓' if td < bd - 0.001 else '~')
        print(f"  {label:<10} {bd:>8.4f} {td:>8.4f}  {diff_flag}")

# ── 7. Save results ────────────────────────────────────────────────────────
np.save(f'sub-{SUBJECT}_theta_dirs_zinnen.npy',  dirs_z)
np.save(f'sub-{SUBJECT}_theta_dirs_woorden.npy', dirs_w)
np.save(f'sub-{SUBJECT}_theta_dirs_rest.npy',    dirs_r)
np.save(f'sub-{SUBJECT}_theta_src_dirs_zinnen.npy',  dirs_src_z)
np.save(f'sub-{SUBJECT}_theta_src_dirs_woorden.npy', dirs_src_w)
np.save(f'sub-{SUBJECT}_theta_src_dirs_rest.npy',    dirs_src_r)

# ── 8. Rose plots ──────────────────────────────────────────────────────────
fig, axes = plt.subplots(2, 3, figsize=(12, 8), subplot_kw={'projection': 'polar'})

rose_plot(axes[0, 0], dirs_z,     'ZINNEN\n(sensor)',  '#2166ac')
rose_plot(axes[0, 1], dirs_w,     'WOORDEN\n(sensor)', '#92c5de')
rose_plot(axes[0, 2], dirs_r,     'REST\n(sensor)',     '#d6604d')
rose_plot(axes[1, 0], dirs_src_z, 'ZINNEN\n(source)',  '#2166ac')
rose_plot(axes[1, 1], dirs_src_w, 'WOORDEN\n(source)', '#92c5de')
rose_plot(axes[1, 2], dirs_src_r, 'REST\n(source)',     '#d6604d')

for ax, row_label in zip([axes[0, 0], axes[1, 0]], ['Sensor', 'Source']):
    ax.set_ylabel(row_label, labelpad=30, fontsize=9)

fig.suptitle(
    f'Theta-band ({FREQ_BAND[0]}–{FREQ_BAND[1]} Hz) traveling wave directions — sub-{SUBJECT}\n'
    f'ZINNEN vs REST (src): ΔDCI={diff_zr_src:+.4f}  p={p_zr_src:.4f}',
    fontsize=11, fontweight='bold'
)
plt.tight_layout()
out_fig = f'sub-{SUBJECT}_theta_wave_directions.png'
plt.savefig(out_fig, dpi=150, bbox_inches='tight')
print(f"\nSaved: {out_fig}")
print("Done.")
