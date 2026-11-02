"""Render TRIBE v2 vertex predictions as cortex heatmaps (fsaverage5, inflated, lateral+medial)
with nilearn/matplotlib (no OpenGL needed inside the container). Returns base64 PNG frames.

Same surface space as tribev2.plotting.PlotBrain (fsaverage5, lh then rh) but headless-safe."""
from __future__ import annotations

import base64
import io
import os
from functools import lru_cache

import numpy as np

N_HEMI = 10242


@lru_cache(maxsize=1)
def _mesh(data_dir: str | None = None):
    from nilearn import datasets

    return datasets.fetch_surf_fsaverage("fsaverage5", data_dir=data_dir or os.environ.get("NILEARN_DATA", "/cache/nilearn"))


def render_frames(preds: np.ndarray, max_frames: int = 8, views: tuple[str, ...] = ("lateral", "medial"),
                  vmax: float | None = None, dpi: int = 60) -> list[str]:
    """preds: (T, 20484). One PNG per timestep (left hemisphere, chosen views side by side).
    Values are z-scored; we show the positive tail with a symmetric scale across frames so the
    animation is comparable frame to frame."""
    import matplotlib

    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    from nilearn import plotting

    fs = _mesh()
    T = min(preds.shape[0], max_frames)
    idx = np.linspace(0, preds.shape[0] - 1, T).round().astype(int) if preds.shape[0] > max_frames else range(T)
    scale = vmax or float(max(0.15, np.percentile(np.abs(preds[:, :N_HEMI]), 99)))
    frames: list[str] = []
    for t in idx:
        lh = preds[t, :N_HEMI]
        fig, axes = plt.subplots(1, len(views), figsize=(3.2 * len(views), 3.0), dpi=dpi,
                                 subplot_kw={"projection": "3d"})
        axes = np.atleast_1d(axes)
        for ax, view in zip(axes, views):
            plotting.plot_surf_stat_map(fs["infl_left"], lh, hemi="left", view=view, bg_map=fs["sulc_left"],
                                        cmap="hot", threshold=0.25 * scale, vmax=scale, colorbar=False,
                                        axes=ax, figure=fig)
            ax.set_facecolor("white")
        fig.patch.set_facecolor("white")
        fig.subplots_adjust(left=0, right=1, top=1, bottom=0, wspace=0)
        buf = io.BytesIO()
        fig.savefig(buf, format="png", dpi=dpi, facecolor="white")
        plt.close(fig)
        frames.append(base64.b64encode(buf.getvalue()).decode())
    return frames
