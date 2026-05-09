"""Behavior-cloning trainer entry point.

Produces:
  <output>/model.onnx
  <output>/meta.json       — schema for runtime BCDriver
  <output>/metrics.json    — held-out validation metrics (G-005)
  <output>/train_log.txt   — per-epoch loss + val + timing
"""

from __future__ import annotations

import json
import logging
import math
import time
from dataclasses import asdict
from pathlib import Path
from typing import Sequence

import numpy as np
import torch
import torch.nn.functional as F
from torch.utils.data import DataLoader, WeightedRandomSampler

from tools.train.bc_common import (
    ActionSpace,
    MOUSE_DIR_BINS_PER_AXIS,
    derive_action_space,
)
from tools.train.bc_dataset import (
    BCConfig, BCDataset, BCRawDataset,
    collect_hdf5_paths, collect_session_dirs,
)
from tools.train.bc_model import BCModel, BCModelConfig


log = logging.getLogger("unicap.train")


# ── Metrics ──────────────────────────────────────────────────────────────────

def _per_key_f1(probs: np.ndarray, targets: np.ndarray, thresh: float = 0.5) -> dict:
    """probs/targets shape (N, K). Returns per-key F1 + macro F1.
    Idle frames (no key down anywhere) are excluded from per-key F1 to avoid
    inflating numbers with the dominant 'all zeros' class."""
    if probs.size == 0:
        return {"per_key": [], "macro": 0.0}
    active_mask = targets.sum(axis=1) > 0
    if active_mask.sum() == 0:
        return {"per_key": [0.0] * targets.shape[1], "macro": 0.0}
    p = probs[active_mask]
    t = targets[active_mask]
    pred = (p >= thresh).astype(np.float32)
    tp = (pred * t).sum(axis=0)
    fp = (pred * (1 - t)).sum(axis=0)
    fn = ((1 - pred) * t).sum(axis=0)
    f1 = np.where((tp + 0.5 * (fp + fn)) > 0,
                  tp / (tp + 0.5 * (fp + fn) + 1e-9),
                  0.0)
    return {"per_key": f1.astype(float).tolist(), "macro": float(f1.mean())}


def _classification_top1(logits: np.ndarray, target: np.ndarray) -> float:
    if logits.size == 0:
        return 0.0
    pred = logits.argmax(axis=1)
    return float((pred == target).mean())


def _kl_action_distribution(probs: np.ndarray, targets: np.ndarray) -> float:
    """KL(human || model) on per-key Bernoulli marginals. Good 'style match'
    summary: lower → model's per-key activation rate matches human's."""
    if probs.size == 0:
        return 0.0
    hum = targets.mean(axis=0).clip(1e-6, 1 - 1e-6)
    mod = (probs > 0.5).mean(axis=0).clip(1e-6, 1 - 1e-6)
    kl = (hum * np.log(hum / mod) + (1 - hum) * np.log((1 - hum) / (1 - mod)))
    return float(kl.sum())


def _idle_ratio(targets: np.ndarray, mouse_btn: np.ndarray | None,
                mouse_dx: np.ndarray | None, mouse_dy: np.ndarray | None) -> float:
    if targets.size == 0:
        return 0.0
    n = targets.shape[0]
    idle = (targets.sum(axis=1) == 0)
    if mouse_btn is not None and mouse_btn.size:
        idle = idle & (mouse_btn.sum(axis=1) == 0)
    center = MOUSE_DIR_BINS_PER_AXIS // 2
    if mouse_dx is not None:
        idle = idle & (mouse_dx == center - 1) | (mouse_dx == center)  # neutral bins 7/8
    return float(idle.mean())


# ── Eval pass ────────────────────────────────────────────────────────────────

def _evaluate(model: BCModel, loader: DataLoader, device: torch.device,
              has_mouse_btn: bool) -> dict:
    model.eval()
    all_kb_p, all_kb_t = [], []
    all_btn_p, all_btn_t = [], []
    all_dx_logit, all_dx_t = [], []
    all_dy_logit, all_dy_t = [], []
    with torch.no_grad():
        for batch in loader:
            frames = batch["frames"].to(device)
            out = model(frames)
            all_kb_p.append(torch.sigmoid(out["kb"]).cpu().numpy())
            all_kb_t.append(batch["kb"].numpy())
            all_dx_logit.append(out["mouse_dx"].cpu().numpy())
            all_dx_t.append(batch["mouse_dx"].numpy())
            all_dy_logit.append(out["mouse_dy"].cpu().numpy())
            all_dy_t.append(batch["mouse_dy"].numpy())
            if has_mouse_btn and "mouse_btn" in out:
                all_btn_p.append(torch.sigmoid(out["mouse_btn"]).cpu().numpy())
                all_btn_t.append(batch["mouse_btn"].numpy())

    kb_p = np.concatenate(all_kb_p) if all_kb_p else np.zeros((0, 1))
    kb_t = np.concatenate(all_kb_t) if all_kb_t else np.zeros((0, 1))
    dx_l = np.concatenate(all_dx_logit) if all_dx_logit else np.zeros((0, 16))
    dx_t = np.concatenate(all_dx_t) if all_dx_t else np.zeros((0,), dtype=np.int64)
    dy_l = np.concatenate(all_dy_logit) if all_dy_logit else np.zeros((0, 16))
    dy_t = np.concatenate(all_dy_t) if all_dy_t else np.zeros((0,), dtype=np.int64)
    btn_p = np.concatenate(all_btn_p) if all_btn_p else None
    btn_t = np.concatenate(all_btn_t) if all_btn_t else None

    f1 = _per_key_f1(kb_p, kb_t)
    return {
        "per_key_f1": f1["per_key"],
        "macro_kb_f1": f1["macro"],
        "mouse_dx_top1": _classification_top1(dx_l, dx_t),
        "mouse_dy_top1": _classification_top1(dy_l, dy_t),
        "mouse_dir_top1": 0.5 * (_classification_top1(dx_l, dx_t)
                                 + _classification_top1(dy_l, dy_t)),
        "mouse_btn_macro_f1": (_per_key_f1(btn_p, btn_t)["macro"]
                               if btn_p is not None else None),
        "kl_action_dist": _kl_action_distribution(kb_p, kb_t),
        "idle_ratio_human": _idle_ratio(
            kb_t, btn_t, np.full(kb_t.shape[0], -1) if kb_t.size else None,
            np.full(kb_t.shape[0], -1) if kb_t.size else None,
        ),
        "idle_ratio_model": _idle_ratio(
            (kb_p > 0.5).astype(np.float32), None,
            None, None,
        ),
        "n_val_frames": int(kb_t.shape[0]),
    }


# ── Training loop ────────────────────────────────────────────────────────────

def run(
    profile_name: str,
    dataset_paths: Sequence[Path],
    output_dir: Path,
    epochs: int = 20,
    batch_size: int = 16,
    lr: float = 3e-4,
    device: str = "cpu",
    backbone: str = "resnet18",
    frame_window: int = 8,
    input_h: int = 144,
    input_w: int = 256,
    recovery_weight: float = 2.0,
    seed: int = 42,
    raw: bool = False,
    color: str = "no-ui",
) -> dict:
    """Train BC for one game profile. Returns the metrics dict.

    raw=False (默认): dataset_paths 是 dataset.h5 文件 → BCDataset
    raw=True: dataset_paths 是 session 目录（含 frames/ + inputs.jsonl）→ BCRawDataset
    """
    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    log_path = output_dir / "train_log.txt"
    log_fh = log_path.open("w", encoding="utf-8")
    train_started_at = time.perf_counter()
    def _flog(msg: str) -> None:
        log_fh.write(msg + "\n")
        log_fh.flush()
        log.info(msg)
        print(msg, flush=True)

    torch.manual_seed(seed)
    np.random.seed(seed)

    from tools.auto_play.profile import load_profile
    profile = load_profile(profile_name, fallback=False)
    action_space = derive_action_space(profile.controls)
    if action_space.num_kb == 0 and action_space.num_mouse_btn == 0:
        raise RuntimeError(
            f"profile {profile_name!r} 没有可建模的 keyboard/mouse 控制 — "
            f"检查 controls (gamepad-only profile 暂不支持 BC)"
        )

    cfg = BCConfig(
        frame_window=frame_window,
        input_h=input_h,
        input_w=input_w,
        recovery_weight=recovery_weight,
    )

    _flog(f"[BC-TRAIN] profile={profile_name} sessions={len(dataset_paths)} device={device}")
    _flog(f"[BC-TRAIN] action_space: kb={action_space.num_kb} mouse_btns={action_space.num_mouse_btn}")
    _flog(f"[BC-TRAIN]   kb_keys={[c for c, _ in action_space.kb_keys]}")
    _flog(f"[BC-TRAIN]   mouse_btns={action_space.mouse_btns}")
    _flog(f"[BC-TRAIN] window={frame_window} input={input_h}x{input_w} backbone={backbone}")

    if raw:
        _flog(f"[BC-TRAIN] 模式=raw（直读 frames/ + inputs.jsonl，跳过 pack）  color={color}")
        train_ds = BCRawDataset(dataset_paths, action_space, cfg, split="train", color=color)
        val_ds   = BCRawDataset(dataset_paths, action_space, cfg, split="val",   color=color)
    else:
        _flog(f"[BC-TRAIN] 模式=h5（dataset.h5）")
        train_ds = BCDataset(dataset_paths, action_space, cfg, split="train")
        val_ds   = BCDataset(dataset_paths, action_space, cfg, split="val")

    sampler = WeightedRandomSampler(
        weights=torch.from_numpy(train_ds.weights).double(),
        num_samples=len(train_ds),
        replacement=True,
    )
    train_loader = DataLoader(
        train_ds, batch_size=batch_size, sampler=sampler,
        num_workers=0, pin_memory=False,
    )
    val_loader = DataLoader(
        val_ds, batch_size=batch_size, shuffle=False,
        num_workers=0, pin_memory=False,
    )

    if device == "cuda" and not torch.cuda.is_available():
        _flog("")
        _flog("=" * 72)
        _flog("[BC-TRAIN] ✗ 选了 --device cuda 但当前 torch 不支持 CUDA")
        _flog(f"           torch={torch.__version__} (CPU-only build)")
        _flog("")
        _flog("           解决：装 CUDA 版 torch（pyproject.toml 已配好 cu128 index）")
        _flog("")
        _flog("             uv sync --extra train")
        _flog("")
        _flog("           然后验证：")
        _flog("")
        _flog("             uv run python -c \"import torch; print(torch.cuda.is_available())\"")
        _flog("")
        _flog("           期望输出 True；显示 False 说明 PyTorch wheel 还是 CPU 版，")
        _flog("           手动装：")
        _flog("")
        _flog("             uv pip install --upgrade --reinstall \\")
        _flog("               --index-url https://download.pytorch.org/whl/cu128 \\")
        _flog("               torch torchvision")
        _flog("")
        _flog("           或先回退 CPU 训练（慢但能跑）：--device cpu")
        _flog("=" * 72)
        log_fh.close()
        raise SystemExit(2)

    dev = torch.device(device)
    model_cfg = BCModelConfig(
        num_kb=action_space.num_kb,
        num_mouse_btn=action_space.num_mouse_btn,
        backbone=backbone,
    )
    model = BCModel(model_cfg).to(dev)
    optimizer = torch.optim.AdamW(
        [p for p in model.parameters() if p.requires_grad], lr=lr,
    )

    has_mouse_btn = action_space.num_mouse_btn > 0
    best_macro_f1 = -1.0

    for epoch in range(1, epochs + 1):
        epoch_started_at = time.perf_counter()
        model.train()
        # Re-freeze backbone batchnorm running stats (eval mode for BN).
        model.backbone.eval()
        total_loss = 0.0
        n_batches = 0
        for batch in train_loader:
            frames = batch["frames"].to(dev)
            kb_t = batch["kb"].to(dev)
            mb_t = batch["mouse_btn"].to(dev)
            dx_t = batch["mouse_dx"].to(dev)
            dy_t = batch["mouse_dy"].to(dev)
            w = batch["weight"].to(dev)

            out = model(frames)
            # KB loss: sample-weighted BCE
            kb_loss = F.binary_cross_entropy_with_logits(
                out["kb"], kb_t, reduction="none"
            ).mean(dim=1)
            kb_loss = (kb_loss * w).mean()
            dx_loss = (F.cross_entropy(out["mouse_dx"], dx_t, reduction="none") * w).mean()
            dy_loss = (F.cross_entropy(out["mouse_dy"], dy_t, reduction="none") * w).mean()
            loss = kb_loss + 0.5 * (dx_loss + dy_loss)
            if has_mouse_btn and "mouse_btn" in out:
                mb_loss = F.binary_cross_entropy_with_logits(
                    out["mouse_btn"], mb_t, reduction="none"
                ).mean(dim=1)
                loss = loss + (mb_loss * w).mean()

            optimizer.zero_grad()
            loss.backward()
            optimizer.step()
            total_loss += float(loss.item())
            n_batches += 1

        avg_loss = total_loss / max(n_batches, 1)
        metrics = _evaluate(model, val_loader, dev, has_mouse_btn)
        now = time.perf_counter()
        epoch_elapsed = now - epoch_started_at
        total_elapsed = now - train_started_at
        _flog(
            f"[BC-TRAIN] epoch={epoch:2d}/{epochs} "
            f"train_loss={avg_loss:.4f} "
            f"val_kb_f1={metrics['macro_kb_f1']:.3f} "
            f"val_dx_top1={metrics['mouse_dx_top1']:.3f} "
            f"val_dy_top1={metrics['mouse_dy_top1']:.3f} "
            f"epoch_time={epoch_elapsed:.1f}s "
            f"total_elapsed={total_elapsed:.1f}s"
        )
        if metrics["macro_kb_f1"] > best_macro_f1:
            best_macro_f1 = metrics["macro_kb_f1"]

        # 每 epoch 末覆盖式存 last.pt — 防止后续 ONNX export / OOM 等崩溃把
        # 几小时训练全丢。文件不大（resnet18 ~45MB），覆盖写不占空间。
        ckpt_path = output_dir / "last.pt"
        torch.save({
            "model_state": model.state_dict(),
            "epoch": epoch,
            "frame_window": frame_window,
            "input_h": input_h,
            "input_w": input_w,
        }, ckpt_path)

    # Final ONNX export — 失败也保留 last.pt，可用 --resume-export 重做
    onnx_path = output_dir / "model.onnx"
    model.eval()
    try:
        model.export_onnx(onnx_path, frame_window=frame_window,
                          input_h=input_h, input_w=input_w)
        _flog(f"[BC-TRAIN] ONNX 写入: {onnx_path} ({onnx_path.stat().st_size/1024/1024:.1f} MB)")
    except Exception as e:
        _flog(f"[BC-TRAIN] ONNX export 失败: {e}")
        _flog(f"[BC-TRAIN] last.pt 已保留: {output_dir / 'last.pt'}")
        raise

    # Final metrics + meta
    final_metrics = _evaluate(model, val_loader, dev, has_mouse_btn)
    metrics_path = output_dir / "metrics.json"
    metrics_path.write_text(json.dumps(final_metrics, indent=2), encoding="utf-8")

    meta = {
        "profile_name": profile_name,
        "backbone_id": backbone,
        "frame_window": frame_window,
        "input_resolution": [input_h, input_w],
        "action_space": action_space.to_meta(),
        "ui_mode": None,            # filled by --ui-mode arg in run() caller
        "trained_at": time.strftime("%Y-%m-%d %H:%M:%S"),
        "n_train_samples": len(train_ds),
        "n_val_samples": len(val_ds),
        "best_macro_kb_f1": best_macro_f1,
    }
    (output_dir / "meta.json").write_text(json.dumps(meta, indent=2), encoding="utf-8")
    log_fh.close()
    return final_metrics


# ── CLI entry ────────────────────────────────────────────────────────────────

def cli(args) -> None:
    """Wired into main.py's `train-bc` subcommand."""
    logging.basicConfig(level=logging.INFO, format="%(message)s")

    profile_name = args.profile
    output_dir = Path(args.output) if args.output else (
        Path("models") / profile_name
    )
    raw = bool(getattr(args, "raw", False))
    color = getattr(args, "color", "no-ui")

    if args.dataset:
        ds = str(args.dataset)
        has_glob = any(c in ds for c in "*?[")
        if has_glob:
            ds_path = Path(ds)
            if ds_path.is_absolute():
                # Python 3.13 禁 Path('.').glob(absolute) — 拆 anchor + relative
                anchor = ds_path.anchor
                rel = ds_path.relative_to(anchor).as_posix()
                paths = [Path(p) for p in Path(anchor).glob(rel)]
            else:
                paths = [Path(p) for p in Path(".").glob(ds)]
            if not paths:
                paths = [Path(ds)]
        else:
            paths = [Path(ds)]
    else:
        from tools.capture.config import DATASET_ROOT
        if raw:
            paths = collect_session_dirs(DATASET_ROOT, profile_name)
        else:
            paths = collect_hdf5_paths(DATASET_ROOT, profile_name)

    if raw:
        paths = [p for p in paths if p.is_dir()
                 and (p / "frames").is_dir()
                 and (p / "inputs.jsonl").is_file()]
        if not paths:
            raise SystemExit(
                f"[BC-TRAIN] --raw 未找到任何 session 目录（需含 frames/ + inputs.jsonl）；"
                f"用 launch --record-demo 录数据，或 --dataset DIR/GLOB"
            )
        print(f"[BC-TRAIN] raw session 目录数 = {len(paths)}", flush=True)
    else:
        paths = [p for p in paths if p.is_file()]
        if not paths:
            raise SystemExit(
                f"[BC-TRAIN] 未找到任何 dataset.h5；先用 launch --record-demo 录数据，"
                f"再 pack；或加 --dataset PATH（或试 --raw 直读未打包数据）"
            )
        print(f"[BC-TRAIN] dataset.h5 文件数 = {len(paths)}", flush=True)
    for p in paths:
        print(f"  - {p}", flush=True)

    metrics = run(
        profile_name=profile_name,
        dataset_paths=paths,
        output_dir=output_dir,
        epochs=args.epochs,
        batch_size=args.batch_size,
        lr=args.lr,
        device=args.device,
        backbone=args.backbone,
        frame_window=args.frame_window,
        input_h=args.input_h,
        input_w=args.input_w,
        recovery_weight=args.recovery_weight,
        raw=raw,
        color=color,
    )
    # patch ui_mode into meta (argparse passes it, but BCDataset doesn't track)
    meta_path = output_dir / "meta.json"
    if meta_path.is_file():
        m = json.loads(meta_path.read_text(encoding="utf-8"))
        m["ui_mode"] = args.ui_mode
        meta_path.write_text(json.dumps(m, indent=2), encoding="utf-8")

    print(f"\n[BC-TRAIN] 完成 → {output_dir}", flush=True)
    print(f"[BC-TRAIN] macro_kb_f1={metrics['macro_kb_f1']:.3f} "
          f"mouse_dir_top1={metrics['mouse_dir_top1']:.3f} "
          f"kl_action={metrics['kl_action_dist']:.3f}", flush=True)
