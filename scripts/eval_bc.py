"""eval_bc.py — load an exported BC ONNX + held-out HDF5 dataset(s), run
inference, and emit a metrics.json with the same schema train-bc produces.

Usage:
    python scripts/eval_bc.py --model models/<game>/model.onnx \\
                              --dataset DATASET_ROOT/<game>/<ts>/dataset.h5 [...] \\
                              --out metrics_eval.json

Reuses tools.train.bc_dataset for label extraction (so train-time and eval-time
schemas can never drift). Inference uses onnxruntime — no torch dependency at
eval time, so this script can run on a host without [train] extras installed.
"""

from __future__ import annotations

import argparse
import json
import logging
import sys
from pathlib import Path

import numpy as np

# Ensure repo root is importable when run as `python scripts/eval_bc.py ...`
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from tools.train.bc_common import (
    ActionSpace,
    MOUSE_DIR_BINS_PER_AXIS,
    derive_action_space,
)


def _per_key_f1(probs: np.ndarray, targets: np.ndarray, thresh: float = 0.5) -> dict:
    if probs.size == 0:
        return {"per_key": [], "macro": 0.0}
    active = targets.sum(axis=1) > 0
    if active.sum() == 0:
        return {"per_key": [0.0] * targets.shape[1], "macro": 0.0}
    p = probs[active]
    t = targets[active]
    pred = (p >= thresh).astype(np.float32)
    tp = (pred * t).sum(axis=0)
    fp = (pred * (1 - t)).sum(axis=0)
    fn = ((1 - pred) * t).sum(axis=0)
    f1 = np.where((tp + 0.5 * (fp + fn)) > 0,
                  tp / (tp + 0.5 * (fp + fn) + 1e-9), 0.0)
    return {"per_key": f1.astype(float).tolist(), "macro": float(f1.mean())}


def _kl_action(probs: np.ndarray, targets: np.ndarray) -> float:
    if probs.size == 0:
        return 0.0
    hum = targets.mean(axis=0).clip(1e-6, 1 - 1e-6)
    mod = (probs > 0.5).mean(axis=0).clip(1e-6, 1 - 1e-6)
    return float((hum * np.log(hum / mod) + (1 - hum) * np.log((1 - hum) / (1 - mod))).sum())


def _sigmoid(x: np.ndarray) -> np.ndarray:
    return 1.0 / (1.0 + np.exp(-x))


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--model", required=True, help="path to model.onnx")
    ap.add_argument("--dataset", nargs="+", required=True, help="HDF5 path(s)")
    ap.add_argument("--out", default="", help="output metrics.json (default: alongside model)")
    ap.add_argument("--threshold", type=float, default=0.5)
    ap.add_argument("--batch-size", type=int, default=8,
                    help="inference batch size (1 = fastest startup, larger = throughput)")
    args = ap.parse_args()

    model_path = Path(args.model).resolve()
    if not model_path.is_file():
        ap.error(f"model not found: {model_path}")
    meta_path = model_path.parent / "meta.json"
    if not meta_path.is_file():
        ap.error(f"meta.json missing next to model: {meta_path}")
    meta = json.loads(meta_path.read_text(encoding="utf-8"))
    profile_name = meta["profile_name"]
    frame_window = int(meta["frame_window"])
    H, W = (int(x) for x in meta["input_resolution"])

    out_path = Path(args.out) if args.out else (model_path.parent / "metrics_eval.json")

    logging.basicConfig(level=logging.INFO, format="%(message)s")

    # Build a BCDataset over the held-out files in 'val' mode using the trained
    # action space — re-derive from profile.controls to mirror train-time logic.
    from tools.auto_play.profile import load_profile
    profile = load_profile(profile_name, fallback=False)
    action_space = derive_action_space(profile.controls)

    from tools.train.bc_dataset import BCDataset, BCConfig
    cfg = BCConfig(
        frame_window=frame_window, input_h=H, input_w=W,
        holdout_fraction=1.0,            # use 100% of provided files for eval
    )
    # holdout_fraction=1.0 → train range is empty; we want 'val' to be the
    # entire dataset, so reuse split='val'.
    paths = [Path(p) for p in args.dataset]
    ds = BCDataset(paths, action_space, cfg, split="val")
    print(f"[EVAL] frames evaluated: {len(ds)}", flush=True)

    import onnxruntime as ort
    sess = ort.InferenceSession(str(model_path), providers=["CPUExecutionProvider"])
    in_name = sess.get_inputs()[0].name
    out_names = [o.name for o in sess.get_outputs()]
    has_btn = "mouse_btn" in out_names

    kb_p_all, kb_t_all = [], []
    btn_p_all, btn_t_all = [], []
    dx_pred_all, dx_t_all = [], []
    dy_pred_all, dy_t_all = [], []

    n = len(ds)
    bs = max(1, int(args.batch_size))
    progress = max(1, n // 20)
    for i in range(0, n, bs):
        batch_indices = range(i, min(i + bs, n))
        # Stack manually (DataLoader requires torch — we avoid the dep here)
        x = np.stack([ds[j]["frames"].numpy() for j in batch_indices], axis=0).astype(np.float32)
        outs = sess.run(out_names, {in_name: x})
        out_d = dict(zip(out_names, outs))

        kb_p_all.append(_sigmoid(out_d["kb"]))
        dx_pred_all.append(out_d["mouse_dx"].argmax(axis=1))
        dy_pred_all.append(out_d["mouse_dy"].argmax(axis=1))
        if has_btn:
            btn_p_all.append(_sigmoid(out_d["mouse_btn"]))

        for j in batch_indices:
            sample = ds[j]
            kb_t_all.append(sample["kb"].numpy())
            dx_t_all.append(int(sample["mouse_dx"]))
            dy_t_all.append(int(sample["mouse_dy"]))
            if has_btn:
                btn_t_all.append(sample["mouse_btn"].numpy())

        if (i // bs) % progress == 0:
            print(f"[EVAL] {min(i+bs, n)}/{n}", flush=True)

    kb_p = np.concatenate(kb_p_all) if kb_p_all else np.zeros((0, action_space.num_kb))
    kb_t = np.stack(kb_t_all) if kb_t_all else np.zeros((0, action_space.num_kb))
    dx_pred = np.concatenate(dx_pred_all) if dx_pred_all else np.zeros((0,), dtype=np.int64)
    dy_pred = np.concatenate(dy_pred_all) if dy_pred_all else np.zeros((0,), dtype=np.int64)
    dx_t = np.array(dx_t_all, dtype=np.int64)
    dy_t = np.array(dy_t_all, dtype=np.int64)
    btn_p = np.concatenate(btn_p_all) if has_btn and btn_p_all else None
    btn_t = np.stack(btn_t_all) if has_btn and btn_t_all else None

    f1 = _per_key_f1(kb_p, kb_t, thresh=args.threshold)
    btn_f1 = _per_key_f1(btn_p, btn_t, thresh=args.threshold) if btn_p is not None else None
    metrics = {
        "model_path": str(model_path),
        "n_eval_frames": int(n),
        "per_key_f1": f1["per_key"],
        "macro_kb_f1": f1["macro"],
        "mouse_dx_top1": float((dx_pred == dx_t).mean()) if n else 0.0,
        "mouse_dy_top1": float((dy_pred == dy_t).mean()) if n else 0.0,
        "mouse_dir_top1": (
            float((dx_pred == dx_t).mean() + (dy_pred == dy_t).mean()) / 2.0
            if n else 0.0
        ),
        "mouse_btn_macro_f1": btn_f1["macro"] if btn_f1 else None,
        "kl_action_dist": _kl_action(kb_p, kb_t),
        "idle_ratio_human": float((kb_t.sum(axis=1) == 0).mean()) if n else 0.0,
        "idle_ratio_model": (
            float(((kb_p > args.threshold).sum(axis=1) == 0).mean()) if n else 0.0
        ),
        "kb_keys": [k["control"] for k in meta["action_space"]["kb_keys"]],
        "mouse_btns": meta["action_space"]["mouse_btns"],
    }
    out_path.write_text(json.dumps(metrics, indent=2), encoding="utf-8")
    print(f"\n[EVAL] {out_path}")
    print(f"[EVAL] macro_kb_f1={metrics['macro_kb_f1']:.3f} "
          f"mouse_dir_top1={metrics['mouse_dir_top1']:.3f} "
          f"kl_action={metrics['kl_action_dist']:.3f}")


if __name__ == "__main__":
    main()
