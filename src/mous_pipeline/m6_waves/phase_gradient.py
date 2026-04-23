"""Module 6A planar phase-gradient detector."""

from __future__ import annotations

import mne
import numpy as np
from scipy.signal import hilbert

from .base import WaveDetector, register


def get_sensor_positions(info):
    meg_picks = mne.pick_types(info, meg=True, exclude="bads")
    pos = np.array([info["chs"][p]["loc"][:3] for p in meg_picks])
    return pos[:, :2], meg_picks


def compute_wave_directions(data_beta: np.ndarray, sensor_xy: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    analytic = hilbert(data_beta, axis=1)
    phase = np.angle(analytic)
    A = np.column_stack([sensor_xy[:, 0], sensor_xy[:, 1], np.ones(len(sensor_xy))])
    k_vec = np.linalg.pinv(A) @ phase
    kx, ky = k_vec[0], k_vec[1]
    directions = np.arctan2(ky, kx)
    k_mag = np.sqrt(kx**2 + ky**2)
    f_centre = 21.5
    with np.errstate(divide="ignore", invalid="ignore"):
        speeds = np.where(k_mag > 1e-6, 2 * np.pi * f_centre / k_mag, np.nan)
    return directions, speeds


def directional_consistency_index(directions: np.ndarray) -> float:
    return float(np.abs(np.mean(np.exp(1j * directions))))


def epochs_to_directions(epochs_obj, sensor_xy, meg_picks=None, data_override: np.ndarray | None = None):
    all_dirs = []
    all_dci = []
    if data_override is None:
        data = epochs_obj.get_data(picks=meg_picks)
    else:
        data = data_override
    for ep_data in data:
        dirs, _ = compute_wave_directions(ep_data, sensor_xy)
        all_dirs.append(dirs)
        all_dci.append(directional_consistency_index(dirs))
    return np.concatenate(all_dirs), np.array(all_dci)


def sliding_dci(data: np.ndarray, sensor_xy: np.ndarray, times: np.ndarray, win: int, step: int):
    centers = []
    dci_ts = []
    for start in range(0, data.shape[-1] - win, step):
        seg = data[:, :, start : start + win]
        ep_dci = []
        for ep in seg:
            dirs, _ = compute_wave_directions(ep, sensor_xy)
            ep_dci.append(directional_consistency_index(dirs))
        centers.append(times[start + win // 2])
        dci_ts.append(np.mean(ep_dci))
    return np.array(centers), np.array(dci_ts)


@register("phase_gradient")
class PlanarPhaseGradient(WaveDetector):
    name = "phase_gradient"
    required_inputs = {"epochs"}

    def detect(self, features):
        epochs_obj = features["epochs"]
        sensor_xy, meg_picks = get_sensor_positions(epochs_obj.info)
        dirs, dci = epochs_to_directions(epochs_obj, sensor_xy, meg_picks)
        return {"directions": dirs, "dci_per_epoch": dci, "dci_mean": float(np.mean(dci))}
