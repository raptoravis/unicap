"""Torch Dataset wrapping one or more unicap HDF5 capture sessions for BC.

Each item is an (8-frame window, last-frame action labels, sample_weight) tuple.
Reading is lazy (h5py keeps file handles open and slices on access) so memory
stays bounded even with many sessions.

Multi-session: pass a list of HDF5 paths; the dataset concatenates indices.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from pathlib import Path
from typing import Sequence

import h5py
import numpy as np
import torch
from torch.utils.data import Dataset

from tools.train.bc_common import (
    ActionSpace,
    derive_action_space,
    kb_label_from_row,
    mouse_btn_label_from_row,
    mouse_dir_label,
    is_active_frame,
    quality_weight,
)


log = logging.getLogger("unicap.train.dataset")


@dataclass(slots=True)
class BCConfig:
    frame_window: int = 8
    input_h: int = 144
    input_w: int = 256
    mouse_motion_thresh: float = 3.0
    recovery_weight: float = 2.0
    holdout_fraction: float = 0.1   # last 10% of each session = val


def _resize(img: np.ndarray, h: int, w: int) -> np.ndarray:
    """Bilinear resize; img: (H, W, 3) uint8 → (h, w, 3) float32 [0, 1]."""
    import cv2
    out = cv2.resize(img, (w, h), interpolation=cv2.INTER_AREA)
    return out.astype(np.float32) / 255.0


class BCDataset(Dataset):
    """Concatenated multi-session BC dataset.

    Each frame index i in a session yields a window [i-T+1 .. i] (clamped at
    the start) of input frames, with the action labels taken at frame i.
    """

    def __init__(
        self,
        hdf5_paths: Sequence[Path],
        action_space: ActionSpace,
        config: BCConfig,
        split: str = "train",  # "train" | "val"
    ) -> None:
        if split not in ("train", "val"):
            raise ValueError(f"split must be 'train' or 'val', got {split!r}")

        self.action_space = action_space
        self.config = config
        self.split = split

        # Each entry: (h5_path, frame_index_within_session)
        self._index: list[tuple[Path, int]] = []
        # Pre-computed per-sample weight (for WeightedRandomSampler)
        self._weights: list[float] = []

        # Open files and build flat index. Keep no h5 handles in __init__ —
        # they're cached lazily in __getitem__ (worker-safe).
        for path in hdf5_paths:
            with h5py.File(path, "r") as hf:
                n = int(hf.attrs["n_frames"])
                if n < config.frame_window:
                    log.warning(
                        "[BC-DS] %s 帧数 %d < frame_window %d，跳过",
                        path, n, config.frame_window,
                    )
                    continue
                # demo_quality is optional (G-001): legacy captures lack it
                quality = (hf["demo_quality"][:]
                           if "demo_quality" in hf
                           else np.zeros(n, dtype=np.uint8))
                kb = hf["kb"][:]            # (n, 256) uint8
                mouse = hf["mouse"][:]      # (n, 2) int32

            split_cut = int(n * (1.0 - config.holdout_fraction))
            if split == "train":
                rng_lo, rng_hi = config.frame_window - 1, split_cut
            else:
                rng_lo, rng_hi = max(split_cut, config.frame_window - 1), n

            # mouse delta: dx[i] = mouse[i].x - mouse[i-1].x; index 0 = 0.
            dxdy = np.zeros((n, 2), dtype=np.float32)
            if n >= 2:
                dxdy[1:] = (mouse[1:] - mouse[:-1]).astype(np.float32)

            for i in range(rng_lo, rng_hi):
                q = int(quality[i])
                w_q = quality_weight(q, recovery_weight=config.recovery_weight)
                if w_q == 0.0:
                    continue  # bad samples dropped entirely
                kb_l = kb_label_from_row(kb[i], action_space)
                mb_l = mouse_btn_label_from_row(kb[i], action_space)
                active = is_active_frame(
                    kb_l, mb_l, dxdy[i, 0], dxdy[i, 1],
                    mouse_motion_thresh=config.mouse_motion_thresh,
                )
                # Active frames sampled 5× more than idle; demo_quality multiplied.
                w = (1.0 if active else 0.2) * w_q
                self._index.append((path, i))
                self._weights.append(w)

        if not self._index:
            raise RuntimeError(
                f"[BC-DS] split={split} 没有任何样本 — 检查 HDF5 帧数 / "
                f"demo_quality / frame_window 配置"
            )
        log.info("[BC-DS] split=%s 样本数=%d", split, len(self._index))

        # Per-worker h5py handle cache, populated on first access.
        self._h5_handles: dict[Path, h5py.File] = {}

    @property
    def weights(self) -> np.ndarray:
        return np.asarray(self._weights, dtype=np.float64)

    def __len__(self) -> int:
        return len(self._index)

    def _h5(self, path: Path) -> h5py.File:
        f = self._h5_handles.get(path)
        if f is None:
            f = h5py.File(path, "r", swmr=False)
            self._h5_handles[path] = f
        return f

    def __getitem__(self, idx: int) -> dict:
        h5_path, frame_i = self._index[idx]
        cfg = self.config
        T = cfg.frame_window
        hf = self._h5(h5_path)

        color_ds = hf["color"]              # (N, H, W, 3) uint8
        kb_ds = hf["kb"]                    # (N, 256) uint8
        mouse_ds = hf["mouse"]              # (N, 2) int32

        lo = max(0, frame_i - T + 1)
        # frame indices: pad by repeating first if window crosses session start
        idxs = list(range(lo, frame_i + 1))
        while len(idxs) < T:
            idxs.insert(0, idxs[0])

        # Read frames + resize one-by-one (avoids loading all of /color into RAM).
        frames = np.empty((T, cfg.input_h, cfg.input_w, 3), dtype=np.float32)
        for t, j in enumerate(idxs):
            img = color_ds[j]               # (H, W, 3) uint8 RGB
            frames[t] = _resize(img, cfg.input_h, cfg.input_w)

        # Labels at last frame (frame_i)
        kb_row = kb_ds[frame_i]
        kb_l = kb_label_from_row(kb_row, self.action_space)
        mb_l = mouse_btn_label_from_row(kb_row, self.action_space)

        if frame_i > 0:
            dx = float(mouse_ds[frame_i, 0] - mouse_ds[frame_i - 1, 0])
            dy = float(mouse_ds[frame_i, 1] - mouse_ds[frame_i - 1, 1])
        else:
            dx = dy = 0.0
        dx_bin, dy_bin = mouse_dir_label(dx, dy)

        # Convert frames (T, H, W, 3) → (T, 3, H, W) for torch conv input
        frames_t = torch.from_numpy(frames).permute(0, 3, 1, 2).contiguous()

        return {
            "frames": frames_t,
            "kb": torch.from_numpy(kb_l),
            "mouse_btn": torch.from_numpy(mb_l),
            "mouse_dx": torch.tensor(dx_bin, dtype=torch.long),
            "mouse_dy": torch.tensor(dy_bin, dtype=torch.long),
            "weight": torch.tensor(self._weights[idx], dtype=torch.float32),
        }


def collect_hdf5_paths(dataset_root: Path, profile_name: str,
                       pattern: str | None = None) -> list[Path]:
    """Scan DATASET_ROOT/<profile>/<*ts*>/dataset.h5. If pattern given, treat
    it as a glob relative to dataset_root."""
    if pattern:
        return sorted(Path(dataset_root).glob(pattern))
    game_dir = Path(dataset_root) / profile_name
    if not game_dir.is_dir():
        return []
    return sorted(p for p in game_dir.glob("*/dataset.h5") if p.is_file())
