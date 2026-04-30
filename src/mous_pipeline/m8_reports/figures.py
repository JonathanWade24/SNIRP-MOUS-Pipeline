"""Module 8 plotting helpers."""

from __future__ import annotations

import matplotlib.pyplot as plt
import numpy as np
from scipy.stats import circmean

from ..m6_waves.phase_gradient import directional_consistency_index


def rose_plot(ax, angles, title, color, n_bins=36):
    bin_edges = np.linspace(-np.pi, np.pi, n_bins + 1)
    counts, _ = np.histogram(angles, bins=bin_edges)
    centers = 0.5 * (bin_edges[:-1] + bin_edges[1:])
    width = 2 * np.pi / n_bins
    ax.bar(centers, counts / max(counts.max(), 1), width=width * 0.9, color=color, alpha=0.7, edgecolor="white")
    mean_dir = circmean(angles)
    dci_val = directional_consistency_index(angles)
    ax.annotate("", xy=(mean_dir, dci_val), xytext=(0, 0), arrowprops=dict(arrowstyle="->", color="black", lw=2))
    ax.set_theta_zero_location("E")
    ax.set_theta_direction(1)
    ax.set_title(f"{title}\nDCI={dci_val:.3f}")
    ax.set_rticks([])


def dci_timecourse(t, dci_a, dci_b=None, label_a="ZINNEN", label_b="WOORDEN"):
    fig, ax = plt.subplots(figsize=(10, 4))
    ax.plot(t, dci_a, lw=2, label=label_a)
    if dci_b is not None:
        ax.plot(t, dci_b, lw=2, label=label_b)
    ax.axvline(0, color="k", ls="--", lw=1, label="Audio onset")
    ax.set_xlabel("Time (s)")
    ax.set_ylabel("Directional Consistency Index")
    ax.legend()
    return fig, ax


def prestim_topography(ax, sensor_xy: np.ndarray, channel_power: np.ndarray, title: str = "Pre-stim topography"):
    """Render a simple 2D sensor-space prestim power topography."""
    sc = ax.scatter(
        sensor_xy[:, 0],
        sensor_xy[:, 1],
        c=channel_power,
        cmap="viridis",
        s=28,
        edgecolors="none",
    )
    ax.set_title(title)
    ax.set_xticks([])
    ax.set_yticks([])
    ax.set_aspect("equal", adjustable="box")
    return sc
