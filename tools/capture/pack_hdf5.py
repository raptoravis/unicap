"""
FF7 Remake 帧数据 HDF5 打包脚本

输入：
  frames_dir/   — BackBuffer.bmp + DepthBuffer.exr + NormalMap.exr 三元组
                  或纯 BMP 文件（color-only 模式）
  inputs.jsonl  — 输入录制（~120 Hz，UTC 纳秒）

输出：
  dataset.h5
  HDF5 结构：
    /color       uint8   (N, H, W, 3)   RGB 画面
    /depth       float32 (N, H, W)      深度（仅 triplet 模式）
    /normal      float32 (N, H, W, 3)   法线 RGB（仅 triplet 模式）
    /frame_ts    int64   (N,)           帧时间戳（UTC 纳秒）
    /input_ts    int64   (N,)           最近输入时间戳（UTC 纳秒）
    /input_dt_ms float32 (N,)           对齐误差（ms，正值=输入在帧之后）
    /kb          uint8   (N, 256)       键盘状态（GetKeyboardState 字节数组）
    /mouse       int32   (N, 2)         鼠标坐标 [x, y]
    /gamepad     float32 (N, 7)         [buttons, lt, rt, lx, ly, rx, ry]

  attrs: n_frames, mode, width, height, fps_est, created_at, timezone

支持的文件名格式：
  A: "ff7remake_.exe 2026-04-28 19-17-06 805 BackBuffer.bmp"   (triplet)
  B: "ff7remake_ 2026-04-28 19-10-10_523.bmp"                  (color-only)

时区：文件名为本地时间（UTC+8），inputs.jsonl 为 UTC 纳秒。
      转换：local_dt(UTC+8).timestamp() * 1e9 + ms * 1e6 → UTC ns

用法：
  python pack_hdf5.py
  python pack_hdf5.py --frames-dir D:/ff7_dataset/frames \\
                      --inputs D:/ff7_dataset/inputs.jsonl \\
                      --output D:/ff7_dataset/dataset.h5
  python pack_hdf5.py --spot-check D:/ff7_dataset/dataset.h5
"""

import os
import sys
import re
import json
import bisect
import argparse
import datetime
from pathlib import Path

# 必须在 import cv2 之前设置，否则 EXR 编解码器被禁用
os.environ['OPENCV_IO_ENABLE_OPENEXR'] = '1'

import cv2
import numpy as np
import h5py
from .config import FRAMES_DIR, INPUTS_OUT, HDF5_OUT, DATASET_ROOT

# ─── 常量 ────────────────────────────────────────────────────────────────────

UTC8 = datetime.timezone(datetime.timedelta(hours=8))
GAMEPAD_DIM = 7  # [buttons, lt, rt, lx, ly, rx, ry]

# ─── 文件名解析 ───────────────────────────────────────────────────────────────

# 格式 A：前缀 日期 时间 毫秒 帧类型.扩展名
# 例：ff7remake_.exe 2026-04-28 19-17-06 805 BackBuffer.bmp
_RE_A = re.compile(
    r'^.+ (\d{4}-\d{2}-\d{2}) (\d{2}-\d{2}-\d{2}) (\d+)'
    r' (BackBuffer|DepthBuffer|NormalMap)\.(bmp|exr)$'
)

# 格式 B：前缀 日期 时间_毫秒.扩展名
# 例：ff7remake_ 2026-04-28 19-10-10_523.bmp
_RE_B = re.compile(
    r'^.+ (\d{4}-\d{2}-\d{2}) (\d{2}-\d{2}-\d{2})_(\d+)\.(bmp|exr)$'
)


def _parse_name(name: str):
    """
    Returns (date_str, time_str, ms_str, frame_type) or None.
    frame_type: 'BackBuffer'/'DepthBuffer'/'NormalMap' for format A, None for B.
    """
    m = _RE_A.match(name)
    if m:
        return m.group(1), m.group(2), m.group(3), m.group(4)
    m = _RE_B.match(name)
    if m:
        return m.group(1), m.group(2), m.group(3), None
    return None


def _to_utc_ns(date_str: str, time_str: str, ms_str: str) -> int:
    """
    Local (UTC+8) filename timestamp → Unix nanoseconds (UTC).
    Explicit timezone — no reliance on system tz setting.
    """
    dt_naive = datetime.datetime.strptime(
        f"{date_str} {time_str.replace('-', ':')}", "%Y-%m-%d %H:%M:%S"
    )
    dt_aware = dt_naive.replace(tzinfo=UTC8)
    # dt_aware.timestamp() returns UTC epoch seconds
    return int(dt_aware.timestamp() * 1_000_000_000) + int(ms_str) * 1_000_000


# ─── 帧目录扫描 ───────────────────────────────────────────────────────────────

def scan_frames(frames_dir: Path):
    """
    Scans frames_dir and returns (mode, frames).

    mode: 'triplet' | 'color-only'
    frames: list of dicts, sorted by ts ascending
      {'ts': int, 'bmp': Path, 'depth': Path|None, 'normal': Path|None}

    Triplet mode activates when any file with BackBuffer/DepthBuffer/NormalMap suffix exists.
    Incomplete triplets (missing BackBuffer) are silently skipped.
    """
    triplets = {}  # (date, time, ms) → {'BackBuffer': Path, ...}
    simples  = {}  # (date, time, ms) → Path

    for f in frames_dir.iterdir():
        parsed = _parse_name(f.name)
        if parsed is None:
            continue
        date_s, time_s, ms_s, ftype = parsed
        key = (date_s, time_s, ms_s)
        if ftype is not None:
            triplets.setdefault(key, {})[ftype] = f
        else:
            simples[key] = f

    if triplets:
        frames = []
        skipped = 0
        for key, parts in triplets.items():
            if 'BackBuffer' not in parts:
                skipped += 1
                continue
            frames.append({
                'ts':     _to_utc_ns(*key),
                'bmp':    parts['BackBuffer'],
                'depth':  parts.get('DepthBuffer'),
                'normal': parts.get('NormalMap'),
            })
        if skipped:
            print(f"[SCAN] 跳过 {skipped} 个不完整三元组（缺少 BackBuffer）")
        frames.sort(key=lambda x: x['ts'])
        return 'triplet', frames
    else:
        frames = []
        for key, path in simples.items():
            if path.suffix.lower() != '.bmp':
                continue
            frames.append({'ts': _to_utc_ns(*key), 'bmp': path, 'depth': None, 'normal': None})
        frames.sort(key=lambda x: x['ts'])
        return 'color-only', frames


# ─── 输入加载与对齐 ───────────────────────────────────────────────────────────

def load_inputs(inputs_path: Path):
    """Load inputs.jsonl → (ts_list, inputs), sorted by ts ascending."""
    records = []
    with open(inputs_path, 'r', encoding='utf-8') as f:
        for line in f:
            line = line.strip()
            if line:
                records.append(json.loads(line))
    records.sort(key=lambda x: x['ts'])
    return [r['ts'] for r in records], records


def nearest_input(frame_ts: int, ts_list: list, inputs: list):
    """
    Bisect nearest-neighbor: finds the input record whose ts is closest to frame_ts.
    Returns (record, dt_ms) where dt_ms = input_ts - frame_ts in milliseconds.
    Returns (None, None) if inputs is empty.
    """
    if not ts_list:
        return None, None
    idx = bisect.bisect_left(ts_list, frame_ts)
    # Compare bracketing candidates: idx-1 and idx
    best = idx
    if idx > 0 and (idx == len(ts_list) or
                    abs(ts_list[idx - 1] - frame_ts) <= abs(ts_list[idx] - frame_ts)):
        best = idx - 1
    dt_ms = (ts_list[best] - frame_ts) / 1_000_000.0  # ns → ms
    return inputs[best], dt_ms


def _encode_gamepad(gamepad) -> np.ndarray:
    out = np.zeros(GAMEPAD_DIM, dtype=np.float32)
    if gamepad is not None:
        out[0] = float(gamepad.get('buttons', 0))
        out[1] = float(gamepad.get('lt', 0.0))
        out[2] = float(gamepad.get('rt', 0.0))
        out[3] = float(gamepad.get('lx', 0.0))
        out[4] = float(gamepad.get('ly', 0.0))
        out[5] = float(gamepad.get('rx', 0.0))
        out[6] = float(gamepad.get('ry', 0.0))
    return out


# ─── 图像加载 ─────────────────────────────────────────────────────────────────

def _load_bmp(path: Path) -> np.ndarray:
    """Load BMP → RGB uint8 (H, W, 3)."""
    img = cv2.imread(str(path), cv2.IMREAD_COLOR)
    if img is None:
        raise RuntimeError(f"无法读取 BMP: {path}")
    return cv2.cvtColor(img, cv2.COLOR_BGR2RGB)


def _load_depth(path: Path) -> np.ndarray:
    """Load depth EXR → float32 (H, W). All channels identical; take ch 0."""
    img = cv2.imread(str(path), cv2.IMREAD_UNCHANGED)
    if img is None:
        raise RuntimeError(f"无法读取深度 EXR: {path}")
    return (img[:, :, 0] if img.ndim == 3 else img).astype(np.float32)


def _load_normal(path: Path) -> np.ndarray:
    """Load normal EXR → float32 (H, W, 3) in RGB order."""
    img = cv2.imread(str(path), cv2.IMREAD_UNCHANGED)
    if img is None:
        raise RuntimeError(f"无法读取法线 EXR: {path}")
    if img.ndim == 3:
        return img[:, :, ::-1].astype(np.float32)  # BGR → RGB
    return img.astype(np.float32)


# ─── HDF5 打包 ────────────────────────────────────────────────────────────────

def pack(frames_dir: Path, inputs_path: Path, output_path: Path):
    print(f"[SCAN] 扫描: {frames_dir}")
    mode, frames = scan_frames(frames_dir)
    n = len(frames)
    if n == 0:
        print("[ERROR] 未找到任何有效帧，退出")
        sys.exit(1)
    print(f"[SCAN] 模式={mode}, 帧数={n}")

    # 读取第一帧确定分辨率
    H, W = _load_bmp(frames[0]['bmp']).shape[:2]
    print(f"[SCAN] 分辨率: {W}x{H}")

    print(f"[LOAD] 加载输入: {inputs_path}")
    ts_list, inputs = load_inputs(inputs_path)
    print(f"[LOAD] 输入条数: {len(inputs)}")

    fps_est = 0.0
    if n >= 2:
        dur_s = (frames[-1]['ts'] - frames[0]['ts']) / 1_000_000_000
        fps_est = (n - 1) / dur_s if dur_s > 0 else 0.0
    print(f"[INFO] 估算 fps: {fps_est:.1f}")

    output_path.parent.mkdir(parents=True, exist_ok=True)
    print(f"[PACK] 写入: {output_path}")

    _C = dict(compression='gzip', compression_opts=4)

    with h5py.File(output_path, 'w') as hf:
        # 图像数据集：chunk=(1, H, W, C) 支持高效帧随机访问
        ds_color    = hf.create_dataset('color',       (n, H, W, 3),        dtype='uint8',   chunks=(1, H, W, 3),        **_C)
        ds_frame_ts = hf.create_dataset('frame_ts',    (n,),                dtype='int64',   chunks=(min(256, n),),      **_C)
        ds_input_ts = hf.create_dataset('input_ts',    (n,),                dtype='int64',   chunks=(min(256, n),),      **_C)
        ds_input_dt = hf.create_dataset('input_dt_ms', (n,),                dtype='float32', chunks=(min(256, n),),      **_C)
        ds_kb       = hf.create_dataset('kb',          (n, 256),            dtype='uint8',   chunks=(min(64, n), 256),   **_C)
        ds_mouse    = hf.create_dataset('mouse',       (n, 2),              dtype='int32',   chunks=(min(256, n), 2),    **_C)
        ds_gamepad  = hf.create_dataset('gamepad',     (n, GAMEPAD_DIM),    dtype='float32', chunks=(min(256, n), GAMEPAD_DIM), **_C)

        if mode == 'triplet':
            ds_depth  = hf.create_dataset('depth',  (n, H, W),    dtype='float32', chunks=(1, H, W),    **_C)
            ds_normal = hf.create_dataset('normal', (n, H, W, 3), dtype='float32', chunks=(1, H, W, 3), **_C)

        max_dt = 0.0
        ui_masked_total = 0  # 累计被方案 A 遮罩的像素数（B 已遮罩的为 0，不计入）
        for i, frame in enumerate(frames):
            inp, dt_ms = nearest_input(frame['ts'], ts_list, inputs)

            if inp is None:
                print(f"\n[WARN] 帧 {i}: inputs.jsonl 为空，填零")
                inp = {'ts': 0, 'kb': [0] * 256, 'mouse': [0, 0], 'gamepad': None}
                dt_ms = 0.0

            color = _load_bmp(frame['bmp'])

            if mode == 'triplet':
                if frame['depth']:
                    depth_arr = _load_depth(frame['depth'])
                    # UI 像素在 UE4 Reverse-Z 中深度恒为 0.0（无深度写入）。
                    # 方案 B（ReShade UIRemove.fx）在采集时已将其置黑 → 此处为 no-op。
                    # 方案 B 未启用时，此处作为兜底将其置黑（方案 A）。
                    ui_mask = depth_arr == 0.0
                    masked = int(ui_mask.sum())
                    if masked:
                        color[ui_mask] = 0
                        ui_masked_total += masked
                    ds_depth[i] = depth_arr
                if frame['normal']:
                    ds_normal[i] = _load_normal(frame['normal'])

            ds_color[i]     = color
            ds_frame_ts[i]  = frame['ts']
            ds_input_ts[i]  = inp['ts']
            ds_input_dt[i]  = float(dt_ms)
            ds_kb[i]        = np.array(inp['kb'], dtype='uint8')
            ds_mouse[i]     = np.array(inp['mouse'], dtype='int32')
            ds_gamepad[i]   = _encode_gamepad(inp.get('gamepad'))

            max_dt = max(max_dt, abs(dt_ms))
            if (i + 1) % 10 == 0 or i == n - 1:
                print(f"\r[PACK] {i + 1}/{n}  对齐误差 {dt_ms:+.1f} ms", end='', flush=True)

        print()

        hf.attrs['n_frames']   = n
        hf.attrs['mode']       = mode
        hf.attrs['width']      = W
        hf.attrs['height']     = H
        hf.attrs['fps_est']    = round(fps_est, 2)
        hf.attrs['created_at'] = datetime.datetime.now(UTC8).isoformat()
        hf.attrs['timezone']   = 'UTC+8 (frame filenames are local time)'
        if mode == 'triplet':
            avg_ui = ui_masked_total / n if n else 0
            hf.attrs['ui_mask'] = 'depth==0 → black (fallback A; no-op if ReShade UIRemove.fx was active)'
            hf.attrs['ui_mask_avg_px'] = round(avg_ui, 1)

    size_mb = output_path.stat().st_size / 1024 / 1024
    print(f"[DONE] {output_path}  ({size_mb:.1f} MB)")
    print(f"[DONE] 帧数={n}  分辨率={W}x{H}  fps≈{fps_est:.1f}  最大对齐误差={max_dt:.1f} ms")
    if mode == 'triplet':
        avg_ui = ui_masked_total / n if n else 0
        if avg_ui > 0:
            print(f"[MASK] 方案A兜底：平均每帧遮罩 {avg_ui:.0f} 个 UI 像素（B 已遮罩的不计入）")
        else:
            print(f"[MASK] 未发现 UI 像素（ReShade UIRemove.fx 已生效，或当前帧无 UI）")


# ─── 抽帧目视验证 ─────────────────────────────────────────────────────────────

def spot_check(h5_path: Path, indices: list, out_dir: Path):
    """
    Load frames at given indices from HDF5, overlay depth as pseudocolor on color,
    save as PNG for manual alignment verification.
    """
    out_dir.mkdir(parents=True, exist_ok=True)

    with h5py.File(h5_path, 'r') as hf:
        n      = hf.attrs['n_frames']
        mode   = hf.attrs.get('mode', 'unknown')
        has_depth = 'depth' in hf

        print(f"[CHECK] {h5_path}  n={n}  mode={mode}  has_depth={has_depth}")

        for idx in indices:
            if idx >= n:
                print(f"[CHECK] 跳过帧 {idx}（总帧数仅 {n}）")
                continue

            color_rgb = hf['color'][idx]           # uint8 (H, W, 3) RGB
            color_bgr = cv2.cvtColor(color_rgb, cv2.COLOR_RGB2BGR)

            frame_ts = int(hf['frame_ts'][idx])
            dt_ms    = float(hf['input_dt_ms'][idx])

            if has_depth:
                depth = hf['depth'][idx]           # float32 (H, W)
                # Normalize to 0-255 for colormap
                d_min, d_max = depth.min(), depth.max()
                if d_max > d_min:
                    d_norm = ((depth - d_min) / (d_max - d_min) * 255).astype(np.uint8)
                else:
                    d_norm = np.zeros_like(depth, dtype=np.uint8)
                heat = cv2.applyColorMap(d_norm, cv2.COLORMAP_INFERNO)
                overlay = cv2.addWeighted(color_bgr, 0.6, heat, 0.4, 0)
                label = f"frame={idx}  depth={d_min:.4f}-{d_max:.4f}  dt={dt_ms:+.1f}ms"
            else:
                overlay = color_bgr.copy()
                label = f"frame={idx}  (no depth)  dt={dt_ms:+.1f}ms"

            # Burn label onto image
            cv2.putText(overlay, label, (20, 40),
                        cv2.FONT_HERSHEY_SIMPLEX, 1.0, (0, 255, 0), 2, cv2.LINE_AA)

            out_path = out_dir / f"spot_{idx:05d}.png"
            cv2.imwrite(str(out_path), overlay)
            print(f"[CHECK] 帧 {idx}: ts={frame_ts}  dt={dt_ms:+.1f}ms → {out_path}")


# ─── CLI ─────────────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(
        description='FF7 Remake 帧数据 HDF5 打包 / 目视验证'
    )
    parser.add_argument('--frames-dir', default=str(FRAMES_DIR),
                        help=f'帧文件目录（默认 {FRAMES_DIR}）')
    parser.add_argument('--inputs', default=str(INPUTS_OUT),
                        help=f'输入录制文件（默认 {INPUTS_OUT}）')
    parser.add_argument('--output', default=str(HDF5_OUT),
                        help=f'输出 HDF5 路径（默认 {HDF5_OUT}）')
    parser.add_argument('--spot-check', metavar='H5_PATH',
                        help='跳过打包，直接对已有 HDF5 抽帧验证')
    parser.add_argument('--check-frames', default='0,99,499',
                        help='--spot-check 时要检查的帧编号（逗号分隔，默认 0,99,499）')
    parser.add_argument('--check-out', default=str(DATASET_ROOT / 'spot_checks'),
                        help='目视验证输出目录')
    args = parser.parse_args()

    if args.spot_check:
        indices = [int(x) for x in args.check_frames.split(',')]
        spot_check(Path(args.spot_check), indices, Path(args.check_out))
    else:
        pack(
            frames_dir=Path(args.frames_dir),
            inputs_path=Path(args.inputs),
            output_path=Path(args.output),
        )


if __name__ == '__main__':
    main()
