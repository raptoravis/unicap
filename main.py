#!/usr/bin/env python3
"""
unicap main controller

Usage:
  python main.py deploy   [--mode custom|official592|official673] [--game-dir PATH]
  python main.py launch   [--mode custom|official592|official673] [--fps N] [--duration SEC] [--deploy-only]
  python main.py capture  [--fps N] [--duration SEC]
  python main.py pack     [--frames-dir PATH] [--inputs PATH] [--output PATH]
  python main.py pack     --spot-check PATH [--check-frames 0,99,499] [--check-out PATH]
"""

import argparse
import ctypes
from datetime import datetime
import shutil
import subprocess
import sys
import time
from pathlib import Path

_user32 = ctypes.WinDLL("user32")

# F1–F12 → VK 0x70–0x7B; also support scroll lock (0x91) as a non-intrusive default
_KEY_NAMES = {f"F{i}": 0x70 + i - 1 for i in range(1, 13)}
_KEY_NAMES["SCROLLLOCK"] = 0x91


def _wait_for_hotkey(key_name: str):
    vk = _KEY_NAMES.get(key_name.upper())
    if vk is None:
        sys.exit(f"[ERROR] unsupported --start-key '{key_name}'. Valid: {', '.join(_KEY_NAMES)}")
    print(f"[LAUNCH] 在游戏中按 {key_name.upper()} 开始采集 (Ctrl+C 取消)...")
    # drain any current press so we don't false-trigger immediately
    while _user32.GetAsyncKeyState(vk) & 0x8000:
        time.sleep(0.05)
    while True:
        if _user32.GetAsyncKeyState(vk) & 0x8000:
            print(f"[LAUNCH] {key_name.upper()} 已按下，开始采集\n")
            return
        time.sleep(0.05)

ROOT = Path(__file__).parent

from tools.capture.config import GAME_WIN64, GAME_EXE, FRAMES_DIR, INPUTS_OUT, HDF5_OUT, DATASET_ROOT
import tools.capture.capture_all as capture_all
import tools.capture.pack_hdf5 as pack_hdf5


def _sources(mode: str):
    """Returns (src_dll, src_addon, shader_src_or_None, deploy_shaders)."""
    if mode == "custom":
        dist = ROOT / "dist"
        return dist / "dxgi.dll", dist / "frame_capture.addon", dist / "reshade-shaders" / "Shaders", True
    addon = ROOT / "vendor" / "addon_official" / "frame_capture.addon"
    if mode == "official592":
        return ROOT / "vendor" / "reshade592" / "dxgi.dll", addon, None, False
    return ROOT / "vendor" / "reshade673" / "dxgi.dll", addon, None, False


def cmd_deploy(args):
    src_dll, src_addon, shader_src, deploy_shaders = _sources(args.mode)
    game_dir = Path(args.game_dir)

    for f in [src_dll, src_addon]:
        if not f.exists():
            sys.exit(f"[ERROR] not found: {f}\n        custom mode requires building first (scripts\\build.ps1)")

    if not game_dir.exists():
        sys.exit(f"[ERROR] game directory not found: {game_dir}")

    dst_dll = game_dir / "dxgi.dll"
    if dst_dll.exists() and not (game_dir / "dxgi.dll.bak").exists():
        shutil.copy2(dst_dll, game_dir / "dxgi.dll.bak")
        print("[DEPLOY] backed up dxgi.dll -> dxgi.dll.bak")

    shutil.copy2(src_dll,   dst_dll)
    shutil.copy2(src_addon, game_dir / "frame_capture.addon")
    print(f"[DEPLOY] mode={args.mode} -> {game_dir}")
    print(f"         dxgi.dll + frame_capture.addon deployed")

    if deploy_shaders:
        shader_dst = game_dir / "reshade-shaders" / "Shaders"
        shader_dst.mkdir(parents=True, exist_ok=True)
        shutil.copy2(shader_src / "DepthToAddon.fx", shader_dst)
        shutil.copy2(shader_src / "UIRemove.fx",     shader_dst)
        print(f"         Shaders -> {shader_dst}")


def cmd_capture(args):
    tag        = datetime.now().strftime("%Y%m%d_%H%M%S")
    frames_dir = DATASET_ROOT / f"frames_{tag}"
    inputs_out = DATASET_ROOT / f"inputs_{tag}.jsonl"
    hdf5_out   = DATASET_ROOT / f"dataset_{tag}.h5"
    capture_all.run(
        fps=args.fps,
        duration=args.duration if args.duration > 0 else None,
        frames_dir=frames_dir,
        inputs_out=inputs_out,
    )
    video_out = DATASET_ROOT / f"video_{tag}.mp4"
    _make_video(frames_dir, video_out, args.fps)
    print(f"\n[SESSION] tag={tag}")
    print(f"          打包命令: uv run main.py pack --frames-dir {frames_dir} --inputs {inputs_out} --output {hdf5_out}")


def cmd_launch(args):
    cmd_deploy(args)
    if args.deploy_only:
        print("\n[DONE] deploy only, capture pipeline not started")
        return

    game_exe = Path(args.game_exe)
    if not game_exe.is_absolute():
        game_exe = Path(args.game_dir) / game_exe
    if not game_exe.exists():
        sys.exit(f"[ERROR] game executable not found: {game_exe}\n        set --game-exe or edit tools/capture/config.py")

    print(f"\n[LAUNCH] {game_exe}")
    subprocess.Popen([str(game_exe)], cwd=str(game_exe.parent))
    _wait_for_hotkey(args.start_key)
    cmd_capture(args)


def _make_video(frames_dir: Path, output: Path, fps: int):
    import cv2
    bmps = sorted(frames_dir.glob("*BackBuffer.bmp"))
    if not bmps:
        bmps = sorted(frames_dir.glob("*.bmp"))
    if not bmps:
        print(f"[VIDEO] 未找到 BMP 文件，跳过")
        return

    first = cv2.imread(str(bmps[0]))
    if first is None:
        print(f"[VIDEO] 无法读取第一帧，跳过")
        return
    h, w = first.shape[:2]

    output.parent.mkdir(parents=True, exist_ok=True)
    writer = cv2.VideoWriter(str(output), cv2.VideoWriter_fourcc(*"mp4v"), fps, (w, h))
    for i, bmp in enumerate(bmps):
        img = cv2.imread(str(bmp))
        if img is not None:
            writer.write(img)
        if (i + 1) % fps == 0:
            print(f"[VIDEO] {i+1}/{len(bmps)} 帧", flush=True)
    writer.release()
    print(f"[VIDEO] 完成：{len(bmps)} 帧 @ {fps}fps → {output}")


def cmd_video(args):
    _make_video(Path(args.frames_dir), Path(args.output), args.fps)


def cmd_pack(args):
    if args.spot_check:
        indices = [int(x) for x in args.check_frames.split(",")]
        pack_hdf5.spot_check(Path(args.spot_check), indices, Path(args.check_out))
    else:
        pack_hdf5.pack(
            frames_dir=Path(args.frames_dir),
            inputs_path=Path(args.inputs),
            output_path=Path(args.output),
        )


def main():
    parser = argparse.ArgumentParser(prog="main.py")
    sub = parser.add_subparsers(dest="cmd", required=True)

    p = sub.add_parser("deploy", help="deploy ReShade DLL + addon to game directory")
    p.add_argument("--mode",     choices=["custom", "official592", "official673"], default="custom")
    p.add_argument("--game-dir", default=str(GAME_WIN64))

    p = sub.add_parser("capture", help="start capture pipeline (no deploy)")
    p.add_argument("--fps",      type=int,   default=30)
    p.add_argument("--duration", type=float, default=0, metavar="SEC", help="seconds to record, 0=unlimited")

    p = sub.add_parser("launch", help="deploy + launch game + start capture pipeline")
    p.add_argument("--mode",       choices=["custom", "official592", "official673"], default="custom")
    p.add_argument("--game-dir",   default=str(GAME_WIN64))
    p.add_argument("--game-exe",   default=str(GAME_EXE))
    p.add_argument("--start-key",  default="F9",
                   help="在游戏中按此键触发采集开始，支持 F1-F12 / ScrollLock (default: F9)")
    p.add_argument("--fps",        type=int,   default=30)
    p.add_argument("--duration",   type=float, default=10, metavar="SEC")
    p.add_argument("--deploy-only", action="store_true")

    p = sub.add_parser("video", help="从 frames 目录生成 MP4 视频")
    p.add_argument("--frames-dir", default=str(FRAMES_DIR))
    p.add_argument("--output",     default=str(DATASET_ROOT / "video.mp4"))
    p.add_argument("--fps",        type=int, default=30)

    p = sub.add_parser("pack", help="pack frame data into HDF5")
    p.add_argument("--frames-dir",   default=str(FRAMES_DIR))
    p.add_argument("--inputs",       default=str(INPUTS_OUT))
    p.add_argument("--output",       default=str(HDF5_OUT))
    p.add_argument("--spot-check",   metavar="H5_PATH")
    p.add_argument("--check-frames", default="0,99,499")
    p.add_argument("--check-out",    default=str(DATASET_ROOT / "spot_checks"))

    args = parser.parse_args()
    {"deploy": cmd_deploy, "capture": cmd_capture, "launch": cmd_launch, "video": cmd_video, "pack": cmd_pack}[args.cmd](args)


if __name__ == "__main__":
    main()
