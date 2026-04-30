"""
Pre-UI skip 自动扫描工具。

工作原理：
  1. 探测帧（skip=0）：写入 fc_skip_count.txt + fc_output_dir.txt，等待第一帧。
     addon 同时写 fc_pass_total.txt（当帧非 BB pass 总数），Python 据此计算扫描范围。
  2. 扫描：从 (total-1) 倒数到 0，每个 skip 值等待对应的 survey_skip_NNN_BackBuffer.bmp。
  3. 分析：对相邻帧做加权差分（HUD 区域权重加倍），差分最大处为 UI 合成点。

1-frame lag 说明：
  fc_skip_count.txt 在 on_reshade_present 中读取（Present 后），
  更新的 skip 从下一帧的 on_bind_rts_dsv 起生效。
  每次等待 ≥ 2 倍采集间隔可确保拿到正确帧。
"""

import time
from pathlib import Path

import cv2
import numpy as np

from .config import DATASET_ROOT, GAME_WIN64


def _write_skip(game_dir: Path, skip: int) -> None:
    (game_dir / "fc_skip_count.txt").write_text(str(skip), encoding="utf-8")


def _clear_skip(game_dir: Path) -> None:
    p = game_dir / "fc_skip_count.txt"
    try:
        p.unlink(missing_ok=True)
    except OSError:
        p.write_text("", encoding="utf-8")


def _read_pass_total(game_dir: Path) -> int | None:
    p = game_dir / "fc_pass_total.txt"
    try:
        v = int(p.read_text(encoding="utf-8").strip())
        return v if v > 0 else None
    except (OSError, ValueError):
        return None


def _wait_for_bmp(survey_dir: Path, skip: int, timeout: float) -> Path | None:
    """等待 survey_skip_NNN_BackBuffer.bmp 出现；先删旧文件防止误读。"""
    target = survey_dir / f"survey_skip_{skip:03d}_BackBuffer.bmp"
    if target.exists():
        target.unlink()
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if target.exists():
            return target
        time.sleep(0.3)
    return None


def _weighted_diff(img_a: np.ndarray, img_b: np.ndarray) -> float:
    """HUD 典型区域（上下左右边缘）权重加倍的差分均值。"""
    h, w = img_a.shape[:2]
    diff = np.abs(img_a.astype(float) - img_b.astype(float)).mean(axis=2)
    weight = np.ones((h, w), dtype=float)
    weight[: h // 8, :]      = 2.0  # 顶部（路径点、状态栏）
    weight[7 * h // 8 :, :]  = 2.0  # 底部（行动栏）
    weight[:, : w // 10]     = 2.0  # 左侧（HP/MP）
    weight[:, 9 * w // 10 :] = 2.0  # 右侧（小地图）
    return float((diff * weight).mean())


def _find_boundary(captured: dict) -> int:
    """
    按 skip 从高到低（early pass → late pass）比较相邻帧差分，
    差分最大处为 UI 合成点；返回其高侧 skip 值（最后的无 UI 帧）。

    captured: {skip_value: bmp_path}
    """
    ordered = sorted(captured.keys(), reverse=True)
    images = {}
    for s in ordered:
        img = cv2.imread(str(captured[s]))
        if img is not None:
            images[s] = img

    if len(images) < 2:
        return max(images.keys()) if images else 0

    best_diff = -1.0
    boundary_hi = ordered[0]

    for i in range(len(ordered) - 1):
        s_hi, s_lo = ordered[i], ordered[i + 1]
        if s_hi not in images or s_lo not in images:
            continue
        d = _weighted_diff(images[s_hi], images[s_lo])
        if d > best_diff:
            best_diff = d
            boundary_hi = s_hi

    return boundary_hi


def run(
    game_dir: Path | None = None,
    survey_dir: Path | None = None,
    step: int = 5,
    fps: float = 1.0,
    timeout_per_skip: float = 10.0,
) -> int | None:
    """
    自动探测 pass 总数并扫描全范围，返回推荐 skip 值。

    Args:
        game_dir:          游戏 exe 所在目录（sidecar 写入位置）
        survey_dir:        扫描帧保存目录（默认 DATASET_ROOT/<game>/survey）
        step:              扫描步长（默认 5）
        fps:               采集帧率（默认 1fps）
        timeout_per_skip:  每个 skip 值等待超时秒数
    """
    game_dir   = game_dir   or GAME_WIN64
    survey_dir = survey_dir or (DATASET_ROOT / "survey")
    survey_dir.mkdir(parents=True, exist_ok=True)

    capture_interval = 1.0 / max(fps, 0.1)
    wait_per_skip = max(2.5 * capture_interval, 2.0)

    fc_output_dir = game_dir / "fc_output_dir.txt"
    fc_pass_total = game_dir / "fc_pass_total.txt"
    fc_pass_total.unlink(missing_ok=True)

    # ── Phase 1: 探测帧（skip=0）→ 获取 pass 总数 ─────────────────────────────
    print("[SURVEY] Phase 1: 探测帧，获取 pass 总数…")
    _write_skip(game_dir, 0)
    fc_output_dir.write_text(str(survey_dir), encoding="utf-8")

    bmp_0 = _wait_for_bmp(survey_dir, 0, timeout_per_skip + wait_per_skip)
    if bmp_0 is None:
        print("[SURVEY] ✗ 未收到探测帧，请确认游戏正在运行且已按 F9 激活采集")
        _clear_skip(game_dir)
        try:
            fc_output_dir.unlink(missing_ok=True)
        except OSError:
            fc_output_dir.write_text("", encoding="utf-8")
        return None

    # 等 fc_pass_total.txt（在同一帧写出，通常已存在）
    for _ in range(20):
        total = _read_pass_total(game_dir)
        if total:
            break
        time.sleep(0.2)

    if not total:
        print("[SURVEY] ✗ 未读到 fc_pass_total.txt，无法确定 pass 总数")
        _clear_skip(game_dir)
        try:
            fc_output_dir.unlink(missing_ok=True)
        except OSError:
            fc_output_dir.write_text("", encoding="utf-8")
        return None

    max_skip = total - 1
    skip_values = list(range(max_skip, 0, -step))  # skip=0 已在探测帧中采集
    print(f"[SURVEY] 共 {total} 个非 BB pass → 扫描 skip {max_skip}→0，步长 {step}，共 {len(skip_values)+1} 个点")
    print(f"         帧保存至: {survey_dir}")
    print(f"         每 skip 值等待 {wait_per_skip:.1f}s\n")

    captured: dict[int, Path] = {0: bmp_0}

    # ── Phase 2: 扫描 ─────────────────────────────────────────────────────────
    try:
        for skip in skip_values:
            _write_skip(game_dir, skip)
            time.sleep(wait_per_skip)

            bmp = _wait_for_bmp(survey_dir, skip, timeout_per_skip)
            if bmp is None:
                print(f"  skip={skip:3d}: ✗ TIMEOUT")
                continue

            kb = bmp.stat().st_size // 1024
            print(f"  skip={skip:3d}: ✓ {kb} KB")
            captured[skip] = bmp

    finally:
        _clear_skip(game_dir)
        fc_pass_total.unlink(missing_ok=True)
        try:
            fc_output_dir.unlink(missing_ok=True)
        except OSError:
            fc_output_dir.write_text("", encoding="utf-8")

    if len(captured) < 2:
        print("\n[SURVEY] 帧数不足，无法分析")
        return None

    # ── Phase 3: 分析 ─────────────────────────────────────────────────────────
    print("\n[SURVEY] 分析差分…")
    recommended = _find_boundary(captured)

    ordered = sorted(captured.keys(), reverse=True)
    images = {s: cv2.imread(str(captured[s])) for s in ordered}
    images = {s: img for s, img in images.items() if img is not None}

    print(f"\n  {'skip':>5}  {'差分':>10}")
    prev = None
    for s in ordered:
        if prev is not None and prev in images and s in images:
            d = _weighted_diff(images[prev], images[s])
            marker = "  ← 推荐边界" if prev == recommended else ""
            print(f"  {s:5d}  {d:10.2f}{marker}")
        else:
            print(f"  {s:5d}  {'(基准)':>10}")
        prev = s

    print(f"\n[SURVEY] 推荐 skip = {recommended}")
    print(f"         部署命令:")
    print(f"           uv run main.py deploy --mode official592 --pre-ui --pre-ui-skip {recommended}")

    return recommended
