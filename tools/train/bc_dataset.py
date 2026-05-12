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
        # Per-sample labels (for pos_weight 计算 — 避免训练前再扫一遍)
        self._kb_labels: list[np.ndarray] = []
        self._mb_labels: list[np.ndarray] = []

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
                self._kb_labels.append(kb_l)
                self._mb_labels.append(mb_l)

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

    def label_pos_freq(self) -> tuple[np.ndarray, np.ndarray]:
        """Returns (kb_pos_freq, mouse_btn_pos_freq) over indexed samples.
        Both shape (K,) float64 in [0, 1]. Empty arrays if no labels."""
        kb = (np.stack(self._kb_labels, axis=0).astype(np.float64).mean(axis=0)
              if self._kb_labels else np.zeros((0,), dtype=np.float64))
        mb = (np.stack(self._mb_labels, axis=0).astype(np.float64).mean(axis=0)
              if self._mb_labels else np.zeros((0,), dtype=np.float64))
        return kb, mb

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


def collect_session_dirs(dataset_root: Path, profile_name: str) -> list[Path]:
    """Scan DATASET_ROOT/<profile>/<ts>/ for raw sessions (frames/ + inputs.jsonl).

    Skips the fixed `survey/` subdir. A session dir is valid if it contains
    a `frames/` directory and an `inputs.jsonl` file."""
    game_dir = Path(dataset_root) / profile_name
    if not game_dir.is_dir():
        return []
    out: list[Path] = []
    for sub in sorted(game_dir.iterdir()):
        if not sub.is_dir() or sub.name == "survey":
            continue
        if (sub / "frames").is_dir() and (sub / "inputs.jsonl").is_file():
            out.append(sub)
    return out


# ── Raw (pre-pack) dataset ────────────────────────────────────────────────────

class BCRawDataset(Dataset):
    """Same interface as BCDataset, but reads BMP + inputs.jsonl directly —
    skipping the HDF5 pack step.

    Pros: F9 停下立刻可训；省盘（不写一份 raw uint8 副本）。
    Cons: __getitem__ cv2.imread 单帧解码 ≈ ms 级，比 h5 chunk slice 慢一截 —
    建议 DataLoader 配 num_workers≥2 抵消。

    Inputs are aligned to frames once at __init__ (bisect nearest-neighbor),
    same logic as pack_hdf5.py — so the resulting samples are identical to
    what BCDataset would yield from the packed h5.
    """

    def __init__(
        self,
        session_dirs: Sequence[Path],
        action_space: ActionSpace,
        config: BCConfig,
        split: str = "train",
        color: str = "no-ui",  # 'no-ui' | 'ui' — 决定挑哪份 BMP
    ) -> None:
        if split not in ("train", "val"):
            raise ValueError(f"split must be 'train' or 'val', got {split!r}")
        if color not in ("no-ui", "ui"):
            raise ValueError(f"color must be 'no-ui' or 'ui', got {color!r}")

        self.action_space = action_space
        self.config = config
        self.split = split
        self.color = color

        # Lazy import to keep pack-side deps (cv2, h5py) optional at import time
        from tools.capture.pack_hdf5 import scan_frames, load_inputs, nearest_input

        # Per-session aligned arrays + bmp paths
        self._sessions: list[dict] = []
        # Flat sample index: (session_idx, frame_i)
        self._index: list[tuple[int, int]] = []
        self._weights: list[float] = []
        self._kb_labels: list[np.ndarray] = []
        self._mb_labels: list[np.ndarray] = []

        for sess_dir in session_dirs:
            sess_dir = Path(sess_dir)
            frames_dir = sess_dir / "frames"
            inputs_path = sess_dir / "inputs.jsonl"
            if not frames_dir.is_dir() or not inputs_path.is_file():
                log.warning("[BC-DS-RAW] %s 缺 frames/ 或 inputs.jsonl，跳过", sess_dir)
                continue

            _mode, frames = scan_frames(frames_dir)
            n = len(frames)
            if n < config.frame_window:
                log.warning("[BC-DS-RAW] %s 帧数 %d < frame_window %d，跳过",
                            sess_dir, n, config.frame_window)
                continue

            ts_list, inputs = load_inputs(inputs_path)

            kb_arr = np.zeros((n, 256), dtype=np.uint8)
            mouse_arr = np.zeros((n, 2), dtype=np.int32)
            quality_arr = np.zeros((n,), dtype=np.uint8)
            bmp_paths: list[Path] = []

            for i, frame in enumerate(frames):
                inp, _ = nearest_input(frame['ts'], ts_list, inputs)
                if inp is not None:
                    kb_list = inp.get('kb') or [0] * 256
                    if len(kb_list) >= 256:
                        kb_arr[i] = np.asarray(kb_list[:256], dtype=np.uint8)
                    m = inp.get('mouse') or [0, 0]
                    mouse_arr[i] = (int(m[0]), int(m[1]))
                    quality_arr[i] = int(inp.get('demo_quality', 0))
                # color='ui' 优先 BackBufferUI.bmp；不存在 fallback BackBuffer.bmp
                bmp = (frame.get('bmp_ui') if color == 'ui' and frame.get('bmp_ui')
                       else frame['bmp'])
                bmp_paths.append(bmp)

            dxdy = np.zeros((n, 2), dtype=np.float32)
            if n >= 2:
                dxdy[1:] = (mouse_arr[1:] - mouse_arr[:-1]).astype(np.float32)

            sess_idx = len(self._sessions)
            self._sessions.append({
                'dir': sess_dir,
                'bmp_paths': bmp_paths,
                'kb': kb_arr,
                'mouse': mouse_arr,
                'dxdy': dxdy,
                'quality': quality_arr,
            })

            split_cut = int(n * (1.0 - config.holdout_fraction))
            if split == "train":
                rng_lo, rng_hi = config.frame_window - 1, split_cut
            else:
                rng_lo, rng_hi = max(split_cut, config.frame_window - 1), n

            for i in range(rng_lo, rng_hi):
                q = int(quality_arr[i])
                w_q = quality_weight(q, recovery_weight=config.recovery_weight)
                if w_q == 0.0:
                    continue
                kb_l = kb_label_from_row(kb_arr[i], action_space)
                mb_l = mouse_btn_label_from_row(kb_arr[i], action_space)
                active = is_active_frame(
                    kb_l, mb_l, dxdy[i, 0], dxdy[i, 1],
                    mouse_motion_thresh=config.mouse_motion_thresh,
                )
                w = (1.0 if active else 0.2) * w_q
                self._index.append((sess_idx, i))
                self._weights.append(w)
                self._kb_labels.append(kb_l)
                self._mb_labels.append(mb_l)

        if not self._index:
            raise RuntimeError(
                f"[BC-DS-RAW] split={split} 没有任何样本 — 检查 session 目录 / "
                f"inputs.jsonl / frame_window 配置"
            )
        log.info("[BC-DS-RAW] split=%s 样本数=%d sessions=%d",
                 split, len(self._index), len(self._sessions))

    @property
    def weights(self) -> np.ndarray:
        return np.asarray(self._weights, dtype=np.float64)

    def label_pos_freq(self) -> tuple[np.ndarray, np.ndarray]:
        """Returns (kb_pos_freq, mouse_btn_pos_freq) over indexed samples."""
        kb = (np.stack(self._kb_labels, axis=0).astype(np.float64).mean(axis=0)
              if self._kb_labels else np.zeros((0,), dtype=np.float64))
        mb = (np.stack(self._mb_labels, axis=0).astype(np.float64).mean(axis=0)
              if self._mb_labels else np.zeros((0,), dtype=np.float64))
        return kb, mb

    def __len__(self) -> int:
        return len(self._index)

    def __getitem__(self, idx: int) -> dict:
        import cv2
        sess_idx, frame_i = self._index[idx]
        cfg = self.config
        T = cfg.frame_window
        sess = self._sessions[sess_idx]

        lo = max(0, frame_i - T + 1)
        idxs = list(range(lo, frame_i + 1))
        while len(idxs) < T:
            idxs.insert(0, idxs[0])

        frames = np.empty((T, cfg.input_h, cfg.input_w, 3), dtype=np.float32)
        cache_subdir = f".bc_cache_{cfg.input_h}x{cfg.input_w}"
        for t, j in enumerate(idxs):
            path = sess['bmp_paths'][j]
            cache_path = path.parent / cache_subdir / (path.stem + ".npy")
            small: np.ndarray | None = None
            if cache_path.is_file():
                try:
                    small = np.load(cache_path)
                    if small.shape != (cfg.input_h, cfg.input_w, 3) or small.dtype != np.uint8:
                        small = None
                except Exception:
                    small = None
            if small is None:
                img = cv2.imread(str(path), cv2.IMREAD_COLOR)
                if img is None:
                    raise RuntimeError(f"[BC-DS-RAW] 无法读取: {path}")
                img = cv2.cvtColor(img, cv2.COLOR_BGR2RGB)
                small = cv2.resize(
                    img, (cfg.input_w, cfg.input_h),
                    interpolation=cv2.INTER_AREA,
                )  # (h, w, 3) uint8
                try:
                    cache_path.parent.mkdir(parents=True, exist_ok=True)
                    # 原子写：先写 .tmp 再 rename，避免并发 worker 读到半文件
                    # np.save 会自动追加 .npy；用 .tmp.npy 后缀保证不被改名
                    tmp = cache_path.with_name(cache_path.stem + ".tmp.npy")
                    np.save(tmp, small, allow_pickle=False)
                    tmp.replace(cache_path)
                except OSError:
                    pass  # 写缓存失败不影响训练
            frames[t] = small.astype(np.float32) / 255.0

        kb_row = sess['kb'][frame_i]
        kb_l = kb_label_from_row(kb_row, self.action_space)
        mb_l = mouse_btn_label_from_row(kb_row, self.action_space)
        dx = float(sess['dxdy'][frame_i, 0])
        dy = float(sess['dxdy'][frame_i, 1])
        dx_bin, dy_bin = mouse_dir_label(dx, dy)

        frames_t = torch.from_numpy(frames).permute(0, 3, 1, 2).contiguous()
        return {
            "frames": frames_t,
            "kb": torch.from_numpy(kb_l),
            "mouse_btn": torch.from_numpy(mb_l),
            "mouse_dx": torch.tensor(dx_bin, dtype=torch.long),
            "mouse_dy": torch.tensor(dy_bin, dtype=torch.long),
            "weight": torch.tensor(self._weights[idx], dtype=torch.float32),
        }
