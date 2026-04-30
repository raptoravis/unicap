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
import configparser
import ctypes
import shutil
import subprocess
import sys
import time
from datetime import datetime
from pathlib import Path

import tools.capture.capture_all as capture_all
import tools.capture.pack_hdf5 as pack_hdf5
from tools.capture.config import DATASET_ROOT, FRAMES_DIR, GAME_PATH, HDF5_OUT, INPUTS_OUT

ROOT = Path(__file__).parent

_user32 = ctypes.WinDLL("user32")

# F1–F12 → VK 0x70–0x7B; also support scroll lock (0x91) as a non-intrusive default
_KEY_NAMES = {f"F{i}": 0x70 + i - 1 for i in range(1, 13)}
_KEY_NAMES["SCROLLLOCK"] = 0x91


def _wait_for_hotkey(key_name: str):
    vk = _KEY_NAMES.get(key_name.upper())
    if vk is None:
        sys.exit(f"[错误] 不支持的 --start-key '{key_name}'，可用按键：{', '.join(_KEY_NAMES)}")
    print(f"[LAUNCH] 在游戏中按 {key_name.upper()} 开始采集 (Ctrl+C 取消)...")
    # drain any current press so we don't false-trigger immediately
    while _user32.GetAsyncKeyState(vk) & 0x8000:
        time.sleep(0.05)
    while True:
        if _user32.GetAsyncKeyState(vk) & 0x8000:
            print(f"[LAUNCH] {key_name.upper()} 已按下，开始采集\n")
            return
        time.sleep(0.05)


_SKIP_EXE = {
    "crashreportclient.exe",
    "ue4prereqsetup_x64.exe",
    "ueprereqsetup_x64.exe",
    "dxsetup.exe",
    "uninstall.exe",
    "uninst.exe",
    "vcredist_x64.exe",
    "vc_redist.x64.exe",
    "dotnetfx.exe",
}


def _resolve_game_path(path_str: str):
    p = Path(path_str)
    if p.is_file():
        if p.suffix.lower() != ".exe":
            sys.exit(f"[错误] --game-path 指定的文件不是 .exe：{p}")
        return p.parent, p
    if p.is_dir():
        candidates = [f for f in p.glob("*.exe") if f.name.lower() not in _SKIP_EXE]
        if not candidates:
            sys.exit(f"[错误] 在 {p} 中未找到可执行文件")
        exe = max(candidates, key=lambda f: f.stat().st_size)
        if len(candidates) > 1:
            print(f"[提示] 找到多个 exe，自动选择最大的：{exe.name}")
        return p, exe
    sys.exit(f"[错误] --game-path 路径不存在：{p}")


def _sources(mode: str):
    """Returns (src_dll, src_addon, shader_src, deploy_shaders).

    Shaders always need to be deployed: the addon enumerates `DepthToAddon_ExportTex`
    by name and depends on DepthToAddon.fx + ReShade.fxh + UIRemove.fx being present.
    """
    shader_src = ROOT / "shaders"
    if mode == "custom":
        dist = ROOT / "dist"
        return dist / "dxgi.dll", dist / "frame_capture.addon", shader_src, True
    addon = ROOT / "vendor" / "addon_official" / "frame_capture.addon"
    if mode == "official592":
        return ROOT / "vendor" / "reshade592" / "dxgi.dll", addon, shader_src, True
    return ROOT / "vendor" / "reshade673" / "dxgi.dll", addon, shader_src, True


def _ensure_addon_enabled(game_dir: Path):
    ini = game_dir / "ReShade.ini"
    cfg = configparser.RawConfigParser()
    cfg.optionxform = str  # preserve key case
    if ini.exists():
        cfg.read(ini, encoding="utf-8")
    for section, key, value in [
        ("ADDON", "FC_EnableCapture", "1"),
        ("ADDON", "FC_ExportDepth", "1"),
        ("ADDON", "FC_ExportNormal", "0"),
        ("OVERLAY", "ShowScreenshotMessage", "0"),  # 不在画面里显示截图通知
        ("INPUT", "KeyScreenshot", "0,0,0,0"),  # 清空截图快捷键，避免与 F10 冲突
        ("GENERAL", "EffectSearchPaths", ".\\reshade-shaders\\Shaders\\"),
        ("GENERAL", "TextureSearchPaths", ".\\reshade-shaders\\Textures\\"),
    ]:
        if not cfg.has_section(section):
            cfg.add_section(section)
        cfg.set(section, key, value)
    with open(ini, "w", encoding="utf-8") as f:
        cfg.write(f)


def _ensure_preset(game_dir: Path):
    # ReShade 不会因为 technique 上的 `enabled = 1` annotation 自动激活技术，
    # 必须在 preset 里显式列出。顺序也要锁定：DepthToAddon 在前写自定义 RT，
    # UIRemove 在后把原始 BackBuffer 写回真实后备缓冲，capture_screenshot 才能拿到正确画面。
    preset = game_dir / "ReShadePreset.ini"
    techniques = "DepthToAddon@DepthToAddon.fx,UIRemove@UIRemove.fx"
    content = f"Techniques={techniques}\nTechniqueSorting={techniques}\n"
    if not preset.exists() or "DepthToAddon@DepthToAddon.fx" not in preset.read_text(encoding="utf-8"):
        preset.write_text(content, encoding="utf-8")


def cmd_deploy(args):
    src_dll, src_addon, shader_src, deploy_shaders = _sources(args.mode)
    game_dir, _ = _resolve_game_path(args.game_path)

    for f in [src_dll, src_addon]:
        if not f.exists():
            sys.exit(f"[错误] 文件不存在：{f}\n       custom 模式需先执行 scripts\\build.ps1")

    dst_dll = game_dir / "dxgi.dll"
    if dst_dll.exists() and not (game_dir / "dxgi.dll.bak").exists():
        shutil.copy2(dst_dll, game_dir / "dxgi.dll.bak")

    shutil.copy2(src_dll, dst_dll)
    shutil.copy2(src_addon, game_dir / "frame_capture.addon")
    _ensure_addon_enabled(game_dir)
    _ensure_preset(game_dir)

    if deploy_shaders:
        shader_dst = game_dir / "reshade-shaders" / "Shaders"
        shader_dst.mkdir(parents=True, exist_ok=True)
        shutil.copy2(shader_src / "ReShade.fxh", shader_dst)
        shutil.copy2(shader_src / "DepthToAddon.fx", shader_dst)
        shutil.copy2(shader_src / "UIRemove.fx", shader_dst)


def cmd_capture(args):
    tag = datetime.now().strftime("%Y%m%d_%H%M%S")
    game_name = getattr(args, "game_name", "") or ""
    watch_dir = getattr(args, "watch_dir", None)
    if watch_dir is None:
        game_dir, game_exe = _resolve_game_path(args.game_path)
        watch_dir = game_dir
        if not game_name:
            game_name = game_exe.stem
    game_name = game_name or "capture"
    session_dir = DATASET_ROOT / f"{game_name}_{tag}"
    frames_dir = session_dir / "frames"
    inputs_out = session_dir / "inputs.jsonl"
    hdf5_out = session_dir / "dataset.h5"
    video_out = session_dir / "video.mp4"
    session_dir.mkdir(parents=True, exist_ok=True)
    capture_all.run(
        fps=args.fps,
        duration=args.duration if args.duration > 0 else None,
        frames_dir=frames_dir,
        inputs_out=inputs_out,
        watch_dir=watch_dir,
    )
    _make_video(frames_dir, video_out, args.fps)
    print(f"\n[会话] {session_dir}")
    print(f"       打包命令: uv run main.py pack --frames-dir {frames_dir} --inputs {inputs_out} --output {hdf5_out}")


def cmd_launch(args):
    cmd_deploy(args)
    if args.deploy_only:
        print("\n[完成] 仅部署，未启动采集")
        return

    game_dir, game_exe = _resolve_game_path(args.game_path)
    if not args.game_name:
        args.game_name = game_exe.stem
    args.watch_dir = game_dir
    print(f"\n[启动] {game_exe}")
    subprocess.Popen([str(game_exe)], cwd=str(game_dir))
    _wait_for_hotkey(args.start_key)
    cmd_capture(args)


def _make_video(frames_dir: Path, output: Path, fps: int):
    import cv2

    bmps = sorted(frames_dir.glob("*BackBuffer.bmp"))
    if not bmps:
        bmps = sorted(frames_dir.glob("*.bmp"))
    if not bmps:
        print("[VIDEO] 未找到 BMP 文件，跳过")
        return

    first = cv2.imread(str(bmps[0]))
    if first is None:
        print("[VIDEO] 无法读取第一帧，跳过")
        return
    h, w = first.shape[:2]
    output.parent.mkdir(parents=True, exist_ok=True)

    ffmpeg = shutil.which("ffmpeg")
    if ffmpeg:
        cmd = [
            ffmpeg,
            "-y",
            "-f",
            "rawvideo",
            "-vcodec",
            "rawvideo",
            "-s",
            f"{w}x{h}",
            "-pix_fmt",
            "bgr24",
            "-r",
            str(fps),
            "-i",
            "pipe:",
            "-c:v",
            "libx264",
            "-pix_fmt",
            "yuv420p",
            "-crf",
            "18",
            str(output),
        ]
        proc = subprocess.Popen(cmd, stdin=subprocess.PIPE, stderr=subprocess.DEVNULL)
        for i, bmp in enumerate(bmps):
            img = cv2.imread(str(bmp))
            if img is not None:
                proc.stdin.write(img.tobytes())
            if (i + 1) % fps == 0:
                print(f"[VIDEO] {i + 1}/{len(bmps)} 帧", flush=True)
        proc.stdin.close()
        proc.wait()
    else:
        writer = cv2.VideoWriter(str(output), cv2.VideoWriter_fourcc(*"mp4v"), fps, (w, h))
        for i, bmp in enumerate(bmps):
            img = cv2.imread(str(bmp))
            if img is not None:
                writer.write(img)
            if (i + 1) % fps == 0:
                print(f"[VIDEO] {i + 1}/{len(bmps)} 帧", flush=True)
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

    p = sub.add_parser("deploy", help="部署 ReShade DLL + addon 到游戏目录")
    p.add_argument("--mode", choices=["custom", "official592", "official673"], default="custom")
    p.add_argument("--game-path", default=str(GAME_PATH), help="游戏 exe 路径或目录（目录时自动寻找最大 exe）")

    p = sub.add_parser("capture", help="启动采集（不部署）")
    p.add_argument("--game-path", default=str(GAME_PATH), help="游戏 exe 路径或目录，用于确定帧文件监视目录")
    p.add_argument("--game-name", default="", help="输出目录前缀（默认从 --game-path 推导）")
    p.add_argument("--fps", type=int, default=30)
    p.add_argument("--duration", type=float, default=0, metavar="SEC", help="录制秒数，0=无限")

    p = sub.add_parser("launch", help="部署 + 启动游戏 + 采集")
    p.add_argument("--mode", choices=["custom", "official592", "official673"], default="custom")
    p.add_argument("--game-path", default=str(GAME_PATH), help="游戏 exe 路径或目录")
    p.add_argument("--game-name", default="", help="输出目录前缀（默认从 exe 文件名推导）")
    p.add_argument("--start-key", default="F9", help="游戏内按此键触发采集，支持 F1-F12 / ScrollLock（默认 F9）")
    p.add_argument("--fps", type=int, default=30)
    p.add_argument("--duration", type=float, default=10, metavar="SEC")
    p.add_argument("--deploy-only", action="store_true")

    p = sub.add_parser("video", help="从 frames 目录生成 MP4 视频")
    p.add_argument("--frames-dir", default=str(FRAMES_DIR))
    p.add_argument("--output", default=str(DATASET_ROOT / "video.mp4"))
    p.add_argument("--fps", type=int, default=30)

    p = sub.add_parser("pack", help="pack frame data into HDF5")
    p.add_argument("--frames-dir", default=str(FRAMES_DIR))
    p.add_argument("--inputs", default=str(INPUTS_OUT))
    p.add_argument("--output", default=str(HDF5_OUT))
    p.add_argument("--spot-check", metavar="H5_PATH")
    p.add_argument("--check-frames", default="0,99,499")
    p.add_argument("--check-out", default=str(DATASET_ROOT / "spot_checks"))

    args = parser.parse_args()
    {"deploy": cmd_deploy, "capture": cmd_capture, "launch": cmd_launch, "video": cmd_video, "pack": cmd_pack}[
        args.cmd
    ](args)


if __name__ == "__main__":
    main()
