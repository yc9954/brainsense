"""ROI groups over the Glasser HCP-MMP1 parcellation, and vertex-index resolution on fsaverage5.

TRIBE v2 predicts (T, 20484) on fsaverage5 (lh 0..10241, rh 10242..20483), 1 Hz, z-scored,
already shifted 5 s to undo hemodynamic lag. We collapse that to a handful of functional
groups the agent can talk about in plain words.

Group names are deliberately functional, not anatomical: they are what the agent says.
"""
from __future__ import annotations

from pathlib import Path

import numpy as np

# HCP-MMP1 area names (without hemisphere prefix). Fixed on day 1; do not tune on test data.
ROI_GROUPS: dict[str, list[str]] = {
    "visual_early":     ["V1", "V2", "V3", "V4"],
    "visual_motion":    ["MT", "MST", "V3A", "V3B", "V4t", "FST", "LO1", "LO2", "LO3"],
    "face_body":        ["FFC", "PIT", "VVC", "STSva", "STSvp", "STSda", "TPOJ1"],
    "scene_place":      ["VMV1", "VMV2", "VMV3", "PHA1", "PHA2", "PHA3", "RSC", "POS1", "POS2"],
    "attention_dorsal": ["IP0", "IP1", "IP2", "LIPv", "LIPd", "VIP", "AIP", "FEF", "PEF"],
    "value_vmpfc":      ["10r", "10v", "10d", "25", "s32", "p32", "a24", "OFC", "pOFC", "13l", "11l"],
    "language":         ["44", "45", "55b", "STGa", "A4", "A5", "TE1a", "TE1m", "TE1p", "STSdp", "PSL", "SFL"],
    "default_mode":     ["31pv", "31pd", "23d", "v23ab", "d23ab", "7m", "PCV", "9m", "8BM"],
    "control_dlpfc":    ["46", "9-46d", "p9-46v", "a9-46v", "IFSa", "IFSp", "IFJa", "IFJp", "8C", "8Av"],
}

# Plain-language labels the agent uses when explaining (Korean).
ROI_GROUP_KO: dict[str, str] = {
    "visual_early": "기본 시각 반응",
    "visual_motion": "움직임/형태 반응",
    "face_body": "얼굴·사람 반응",
    "scene_place": "장소·배경 반응",
    "attention_dorsal": "시각 주의",
    "value_vmpfc": "보상·가치",
    "language": "언어 처리",
    "default_mode": "자기 참조·딴생각",
    "control_dlpfc": "집중·통제",
}

N_VERT_FS5 = 20484
N_HEMI_FS5 = 10242

TIME_STATS = ("mean", "max", "early", "late", "slope", "std")


def resolve_group_vertices(subjects_dir: str | None = None) -> dict[str, np.ndarray]:
    """Return {group: vertex indices on fsaverage5 (both hemis)} using MNE's HCPMMP1 annot.

    Tries tribev2's own helper first (it ships get_hcp_roi_indices); falls back to reading
    the annotation from MNE directly. fsaverage5 vertices are the first 10242 of fsaverage per
    hemisphere (nested icosahedra), so we filter fsaverage label vertices to < 10242.
    """
    import os

    local_annot = Path(subjects_dir or os.environ.get("SUBJECTS_DIR", "")) / "fsaverage" / "label" / "lh.HCPMMP1.annot"
    try:  # preferred: repo-native helper (API per tribev2/utils.py) — unless the atlas is already
        # on disk, in which case skip it (the helper pulls MNE's 1.5 GB sample dataset at startup).
        if local_annot.exists():
            raise RuntimeError("local HCPMMP1 annot present; using MNE directly")
        from tribev2.utils import get_hcp_roi_indices  # type: ignore

        out = {}
        for g, areas in ROI_GROUPS.items():
            idx = get_hcp_roi_indices(areas, hemi="both", mesh="fsaverage5")
            out[g] = np.asarray(idx, dtype=np.int64)
        return out
    except Exception:
        pass

    import mne  # fallback

    subjects_dir = subjects_dir or os.environ.get("SUBJECTS_DIR") or str(mne.datasets.fetch_fsaverage(verbose=False).parent)
    if not local_annot.exists():
        mne.datasets.fetch_hcp_mmp_parcellation(subjects_dir=subjects_dir, accept=True, verbose=False)
    labels = mne.read_labels_from_annot("fsaverage", "HCPMMP1", subjects_dir=subjects_dir, verbose=False)
    by_name = {lab.name: lab for lab in labels}  # e.g. "L_V1_ROI-lh"
    out = {}
    for g, areas in ROI_GROUPS.items():
        verts = []
        for a in areas:
            for hemi, prefix, offset in (("lh", "L", 0), ("rh", "R", N_HEMI_FS5)):
                lab = by_name.get(f"{prefix}_{a}_ROI-{hemi}")
                if lab is None:
                    continue
                v = lab.vertices[lab.vertices < N_HEMI_FS5] + offset
                verts.append(v)
        out[g] = np.unique(np.concatenate(verts)) if verts else np.zeros(0, dtype=np.int64)
    return out


def roi_timeseries(preds: np.ndarray, groups: dict[str, np.ndarray]) -> dict[str, np.ndarray]:
    """(T, 20484) -> {group: (T,)} mean over the group's vertices."""
    assert preds.ndim == 2 and preds.shape[1] == N_VERT_FS5, preds.shape
    return {g: preds[:, idx].mean(axis=1) if len(idx) else np.zeros(preds.shape[0]) for g, idx in groups.items()}


def pool_features(ts: dict[str, np.ndarray], early_s: int = 3) -> tuple[np.ndarray, list[str]]:
    """Flatten ROI time series into a fixed-length vector + names (group__stat)."""
    feats, names = [], []
    for g, x in ts.items():
        T = len(x)
        early = x[:early_s].mean() if T else 0.0
        late = x[early_s:].mean() if T > early_s else early
        vals = {"mean": x.mean() if T else 0.0, "max": x.max() if T else 0.0, "early": early,
                "late": late, "slope": late - early, "std": x.std() if T else 0.0}
        for s in TIME_STATS:
            feats.append(float(vals[s])); names.append(f"{g}__{s}")
    return np.asarray(feats, dtype=np.float32), names


def feature_names() -> list[str]:
    return [f"{g}__{s}" for g in ROI_GROUPS for s in TIME_STATS]


# ---------------------------------------------------------------------------------------------
# Richer features: every HCP-MMP1 area (180 per hemisphere) instead of 9 functional groups.
# The 54-d group features saturate below a width-matched PCA of the raw embedding (AADB 0.69 vs
# 0.73); per-area means keep far more of the predicted cortex while staying nameable.

def resolve_area_vertices(subjects_dir: str | None = None) -> dict[str, np.ndarray]:
    """{"L_V1": idx, ..., "R_V1": idx, ...} on fsaverage5 (both hemispheres, 360 areas)."""
    import os

    import mne

    subjects_dir = subjects_dir or os.environ.get("SUBJECTS_DIR") or str(mne.datasets.fetch_fsaverage(verbose=False).parent)
    labels = mne.read_labels_from_annot("fsaverage", "HCPMMP1", subjects_dir=subjects_dir, verbose=False)
    out: dict[str, np.ndarray] = {}
    for lab in labels:
        name = lab.name  # e.g. "L_V1_ROI-lh"
        if "???" in name:
            continue
        hemi_off = 0 if name.endswith("-lh") else N_HEMI_FS5
        area = name.split("_ROI")[0]
        v = lab.vertices[lab.vertices < N_HEMI_FS5] + hemi_off
        if len(v):
            out[area] = v.astype(np.int64)
    return dict(sorted(out.items()))


def area_features(preds: np.ndarray, areas: dict[str, np.ndarray]) -> tuple[np.ndarray, list[str]]:
    """(T, 20484) -> per-area time-mean (360-d) + per-area early/late slope (360-d) = 720-d."""
    T = preds.shape[0]
    means, slopes, names = [], [], []
    for a, idx in areas.items():
        ts = preds[:, idx].mean(axis=1)
        means.append(ts.mean())
        early = ts[:3].mean() if T else 0.0
        late = ts[3:].mean() if T > 3 else early
        slopes.append(late - early)
        names.append(a)
    feats = np.concatenate([np.asarray(means), np.asarray(slopes)]).astype(np.float32)
    return feats, [f"{n}__mean" for n in names] + [f"{n}__slope" for n in names]
