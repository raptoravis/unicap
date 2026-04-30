"""
Pre-UI skip 自动扫描工具。

在游戏运行且采集已激活（F9 已按下）的状态下，自动扫描 skip 值范围，
找到 UI 消失的临界点，并返回推荐的 FC_PreUISkipCount 值。

工作原理：
  1. 写入 fc_skip_count.txt sidecar → addon 在下一帧更新 g_pre_ui_skip
  2. 等待 survey_skip_NNN_BackBuffer.bmp 出现（命名包含 skip 值方便匹配）
  3. 对相邻 skip 值的帧求加权差分（HUD 区域权重更高）
  4. 差分最大处 = UI 合成 pass → 高一侧的 skip 值即为推荐值

1-frame lag 说明：
  fc_skip_count.txt 在 on_reshade_present 中读取（Present 后），
  因此更新后的 skip 从下一帧的 on_bind_rts_dsv 起生效。
  每个 skip 值等待时间 ≥ 2 倍采集间隔可保证拿到正确帧。
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


def _wait_for_bmp(survey_dir: Path, skip: int, timeout: float) -> Path | None:
    """等待 survey_skip_NNN_BackBuffer.bmp 出现；先删除旧文件防止误读。"""
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
    """相邻 skip 帧的加权差分均值；HUD 典型区域（边缘条带）权重加倍。"""
    h, w = img_a.shape[:2]
    diff = np.abs(img_a.astype(float) - img_b.astype(float)).mean(axis=2)
    weight = np.ones((h, w), dtype=float)
    weight[: h // 8, :]     = 2.0   # 顶部（状态栏、路径点）
    weight[7 * h // 8 :, :] = 2.0   # 底部（行动栏）
    weight[:, : w // 10]    = 2.0   # 左侧（HP/MP）
    weight[:, 9 * w // 10 :] = 2.0  # 右侧（小地图）
    return float((diff * weight).mean())


def _find_boundary(captured: dict) -> int:
    """
    从高 skip → 低 skip（早 pass → 晚 pass）顺序比较相邻帧差分，
    差分最大处为 UI 合成点；返回其高侧的 skip 值作为推荐值。

    captured: {skip_value: bmp_path}
    """
    ordered = sorted(captured.keys(), reverse=True)  # 高 skip 在前
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
        s_hi = ordered[i]
        s_lo = ordered[i + 1]
        if s_hi not in images or s_lo not in images:
            continue
        d = _weighted_diff(images[s_hi], images[s_lo])
        if d > best_diff:
            best_diff = d
            boundary_hi = s_hi  # 这一帧是 UI 合成前的最后干净帧

    return boundary_hi


def run(
    game_dir: Path | None = None,
    survey_dir: Path | None = None,
    max_skip: int = 70,
    step: int = 5,
    fps: float = 1.0,
    timeout_per_skip: float = 10.0,
) -> int | None:
    """
    扫描 [0, max_skip] 范围内的 skip 值（步长 step），返回推荐 skip 值。

    Args:
        game_dir:          游戏 exe 所在目录（sidecar 写入位置）
        survey_dir:        扫描帧保存目录（默认 DATASET_ROOT/survey）
        max_skip:          最大 skip 值（默认 70）
        step:              步长（默认 5）
        fps:               扫描时的采集帧率（默认 1fps，每个 skip 值约需 2-3 秒）
        timeout_per_skip:  每个 skip 值等待超时秒数
    """
    game_dir   = game_dir   or GAME_WIN64
    survey_dir = survey_dir or (DATASET_ROOT / "survey")
    survey_dir.mkdir(parents=True, exist_ok=True)

    capture_interval = 1.0 / max(fps, 0.1)
    # 需要等待 ≥2 倍采集间隔（1-frame lag + 实际采集）
    wait_per_skip = max(2.5 * capture_interval, 2.0)

    skip_values = list(range(max_skip, -1, -step))
    if skip_values[-1] != 0:
        skip_values.append(0)

    print(f"[SURVEY] 扫描 {len(skip_values)} 个 skip 值 ({max_skip}→0，步长 {step})")
    print(f"         帧保存至: {survey_dir}")
    print(f"         每 skip 值等待 {wait_per_skip:.1f}s (timeout {timeout_per_skip}s)")
    print()

    fc_output_dir = game_dir / "fc_output_dir.txt"
    fc_output_dir.write_text(str(survey_dir), encoding="utf-8")

    captured: dict[int, Path] = {}

    try:
        for skip in skip_values:
            _write_skip(game_dir, skip)
            # 先等 wait_per_skip 秒让 1-frame lag 过去并完成采集
            time.sleep(wait_per_skip)

            bmp = _wait_for_bmp(survey_dir, skip, timeout_per_skip)
            if bmp is None:
                print(f"  skip={skip:3d}: ✗ TIMEOUT")
                continue

            captured[skip] = bmp
            # 简单进度：显示文件大小作为"有内容"的确认
            kb = bmp.stat().st_size // 1024
            print(f"  skip={skip:3d}: ✓ {kb} KB  →  {bmp.name}")

    finally:
        _clear_skip(game_dir)
        try:
            fc_output_dir.unlink(missing_ok=True)
        except OSError:
            fc_output_dir.write_text("", encoding="utf-8")

    if not captured:
        print("\n[SURVEY] 未收到任何帧，请确认游戏正在运行且已按 F9 激活采集")
        return None

    print("\n[SURVEY] 分析中…")
    recommended = _find_boundary(captured)

    # 打印差分概览
    ordered = sorted(captured.keys(), reverse=True)
    images  = {s: cv2.imread(str(captured[s])) for s in ordered if cv2.imread(str(captured[s])) is not None}
    print(f"\n  {'skip':>5}  {'与前一值的加权差分':>20}")
    prev_skip: int | None = None
    for s in ordered:
        if prev_skip is not None and prev_skip in images and s in images:
            d = _weighted_diff(images[prev_skip], images[s])
            marker = "  ← UI 合成点" if s == recommended or prev_skip == recommended else ""
            print(f"  {s:5d}  {d:20.2f}{marker}")
        else:
            print(f"  {s:5d}  {'(基准)':>20}")
        prev_skip = s

    print(f"\n[SURVEY] 推荐 skip = {recommended}")
    print(f"         部署命令:")
    print(f"           uv run main.py deploy --mode official592 --pre-ui --pre-ui-skip {recommended}")

    return recommended
