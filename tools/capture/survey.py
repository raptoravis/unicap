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

import threading
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


def _wait_for_bmp(survey_dir: Path, skip: int, timeout: float,
                  mtime_floor: float,
                  abort: threading.Event | None = None) -> Path | None:
    """等待 survey_skip_NNN_BackBuffer.bmp 出现。

    用 mtime_floor 排除上轮 survey 的同名残留：addon 在 wait_per_skip 期间
    会重复覆盖同一文件，主动 unlink 会和 addon 写盘抢锁导致 WinError 32。
    """
    target = survey_dir / f"survey_skip_{skip:03d}_BackBuffer.bmp"
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if abort is not None and abort.is_set():
            return None
        try:
            if target.stat().st_mtime >= mtime_floor:
                return target
        except OSError:
            pass
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
    找到"渲染稳定区"的低 skip 边界，即 UI 合成点之上的最后干净帧。

    策略：
      场景渲染分三段（高→低 skip）：
        ① 极早期（大 skip）：几乎空/黑，帧间差小
        ② 主渲染区（中段）：大量几何/光照出现，帧间差大
        ③ 稳定后处理区（小 skip）：场景已完整，帧间差小；末尾几个 pass 才合成 UI

      用 threshold = 3× 中位差分 将所有相邻帧对分成"稳定"和"不稳定"两类，
      然后把所有连续稳定对聚成若干"稳定段"。
      排除完全落在 skip 范围上半段（极早期空场景）的稳定段，
      取剩余稳定段中 s_lo 最小的那个段，其最小 s_lo 即为推荐 skip。

    captured: {skip_value: bmp_path}
    """
    ordered = sorted(captured.keys(), reverse=True)
    images: dict[int, np.ndarray] = {}
    for s in ordered:
        img = cv2.imread(str(captured[s]))
        if img is not None:
            images[s] = img

    if len(images) < 2:
        return max(images.keys()) if images else 0

    # 计算所有相邻对的差分
    pairs: list[tuple[int, int, float]] = []
    for i in range(len(ordered) - 1):
        s_hi, s_lo = ordered[i], ordered[i + 1]
        if s_hi in images and s_lo in images:
            d = _weighted_diff(images[s_hi], images[s_lo])
            pairs.append((s_hi, s_lo, d))

    if not pairs:
        return ordered[-1]

    all_diffs = sorted(d for _, _, d in pairs)
    threshold = max(all_diffs[len(all_diffs) // 2] * 3.0, 3.0)  # 3× 中位差分，最小 3.0

    # FF7R-类管线特例：如果最大跳变恰好在最小那对 skip 之间，且明显大于其他差分，
    # 说明 UI 是合成在最后一个非 BB RT 之内（不是 BB），这时 skip=0 才是干净的
    # pre-UI 帧。默认算法假设"稳定区=pre-UI"在这种情况下会推荐错的一侧。
    median_diff = all_diffs[len(all_diffs) // 2]
    largest = max(pairs, key=lambda p: p[2])
    if largest[1] == ordered[-1] and largest[2] > 5.0 * max(median_diff, 1.0):
        return largest[1]

    # 将连续"稳定对"聚成段（d < threshold 为稳定）
    groups: list[list[tuple[int, int, float]]] = []
    current: list[tuple[int, int, float]] = []
    for pair in pairs:
        if pair[2] < threshold:
            current.append(pair)
        else:
            if current:
                groups.append(current)
            current = []
    if current:
        groups.append(current)

    if not groups:
        return ordered[0]

    # 排除完全落在 skip 范围上半段的段（极早期空场景段）
    mid = (ordered[0] + ordered[-1]) / 2
    late_groups = [g for g in groups if max(s_hi for s_hi, _, _ in g) < mid]
    if not late_groups:
        late_groups = groups  # 降级：保留全部

    # 取稳定段中 s_lo 最小的那个，其最小 s_lo = 推荐 skip
    best = min(late_groups, key=lambda g: min(s_lo for _, s_lo, _ in g))
    return min(s_lo for _, s_lo, _ in best)


def run(
    game_dir: Path | None = None,
    survey_dir: Path | None = None,
    step: int = 5,
    fps: float = 1.0,
    timeout_per_skip: float = 10.0,
    abort_event: threading.Event | None = None,
) -> int | None:
    """
    自动探测 pass 总数并扫描全范围，返回推荐 skip 值。

    Args:
        game_dir:          游戏 exe 所在目录（sidecar 写入位置）
        survey_dir:        扫描帧保存目录（默认 DATASET_ROOT/<game>/survey）
        step:              扫描步长（默认 5）
        fps:               采集帧率（默认 1fps）
        timeout_per_skip:  每个 skip 值等待超时秒数
        abort_event:       外部中止信号（F9 等热键），set 后尽快返回 None
    """
    game_dir   = game_dir   or GAME_WIN64
    survey_dir = survey_dir or (DATASET_ROOT / "survey")
    survey_dir.mkdir(parents=True, exist_ok=True)

    capture_interval = 1.0 / max(fps, 0.1)
    wait_per_skip = max(2.5 * capture_interval, 2.0)

    fc_output_dir = game_dir / "fc_output_dir.txt"
    fc_pass_total = game_dir / "fc_pass_total.txt"
    fc_pass_total.unlink(missing_ok=True)

    # mtime 基线：本轮开始之后 addon 写出的帧才算数（排除上轮残留同名 BMP）
    mtime_floor = time.time()

    # ── Phase 1: 探测帧（skip=0）→ 获取 pass 总数 ─────────────────────────────
    print("[SURVEY] Phase 1: 探测帧，获取 pass 总数…")
    _write_skip(game_dir, 0)
    fc_output_dir.write_text(str(survey_dir), encoding="utf-8")

    bmp_0 = _wait_for_bmp(survey_dir, 0, timeout_per_skip + wait_per_skip,
                          mtime_floor, abort_event)
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
        print(f"         (期望文件: {game_dir / 'fc_pass_total.txt'})")
        print("         可能原因：游戏不在 3D 场景中（logo/主菜单/加载界面/cutscene 都没有 DSV pass）。")
        print("         请进入实际游戏画面（角色可移动、看得到 3D 场景）后再按 F6 重试。")
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
            if abort_event is not None and abort_event.is_set():
                print("[SURVEY] 收到中止信号，提前停止扫描")
                break
            _write_skip(game_dir, skip)
            # interruptible wait
            t_end = time.monotonic() + wait_per_skip
            while time.monotonic() < t_end:
                if abort_event is not None and abort_event.is_set():
                    break
                time.sleep(0.1)

            bmp = _wait_for_bmp(survey_dir, skip, timeout_per_skip,
                                mtime_floor, abort_event)
            if bmp is None:
                if abort_event is not None and abort_event.is_set():
                    break
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

    if abort_event is not None and abort_event.is_set():
        print("\n[SURVEY] 已中止，跳过分析")
        return None
    if len(captured) < 2:
        print("\n[SURVEY] 帧数不足，无法分析")
        return None

    # ── Phase 3: 分析 ─────────────────────────────────────────────────────────
    print("\n[SURVEY] 分析差分…")
    recommended = _find_boundary(captured)

    rec_file = survey_dir / "recommended_skip.txt"
    rec_file.write_text(str(recommended), encoding="utf-8")

    ordered = sorted(captured.keys(), reverse=True)
    images = {s: cv2.imread(str(captured[s])) for s in ordered}
    images = {s: img for s, img in images.items() if img is not None}

    print(f"\n  {'skip':>5}  {'差分':>10}  说明")
    prev = None
    for s in ordered:
        if prev is not None and prev in images and s in images:
            d = _weighted_diff(images[prev], images[s])
            if s == recommended:
                note = "← 推荐（稳定区下边界，无 UI）"
            elif prev == recommended:
                note = "← UI 合成出现在此范围内"
            else:
                note = ""
            print(f"  {s:5d}  {d:10.2f}  {note}")
        else:
            note = "← 推荐（稳定区下边界，无 UI）" if s == recommended else "(基准)"
            print(f"  {s:5d}  {'':>10}  {note}")
        prev = s

    step = args_step if (args_step := ordered[-2] - ordered[-1] if len(ordered) >= 2 else 5) > 0 else 5
    print(f"\n[SURVEY] 推荐 skip = {recommended}")
    print(f"         已写入 {rec_file}")
    print(f"         下次 launch 时会自动使用此 skip 值")

    return recommended
