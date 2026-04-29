#!/usr/bin/env python3
"""
reshade-custom main controller

Usage:
  python main.py deploy   [--mode custom|official592|official673] [--game-dir PATH]
  python main.py launch   [--mode custom|official592|official673] [--fps N] [--duration SEC] [--deploy-only]
  python main.py capture  [--fps N] [--duration SEC]
  python main.py pack     [--frames-dir PATH] [--inputs PATH] [--output PATH]
  python main.py pack     --spot-check PATH [--check-frames 0,99,499] [--check-out PATH]
"""

import argparse
import shutil
import sys
from pathlib import Path

ROOT        = Path(__file__).parent
CAPTURE_DIR = ROOT / "tools" / "capture"
sys.path.insert(0, str(CAPTURE_DIR))

from config import GAME_WIN64, FRAMES_DIR, INPUTS_OUT, HDF5_OUT, DATASET_ROOT


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
    import capture_all
    capture_all.run(fps=args.fps, duration=args.duration if args.duration > 0 else None)


def cmd_launch(args):
    cmd_deploy(args)
    if args.deploy_only:
        print("\n[DONE] deploy only, capture pipeline not started")
        return
    print()
    cmd_capture(args)


def cmd_pack(args):
    import pack_hdf5
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

    p = sub.add_parser("launch", help="deploy + start capture pipeline")
    p.add_argument("--mode",        choices=["custom", "official592", "official673"], default="custom")
    p.add_argument("--game-dir",    default=str(GAME_WIN64))
    p.add_argument("--fps",         type=int,   default=30)
    p.add_argument("--duration",    type=float, default=0, metavar="SEC")
    p.add_argument("--deploy-only", action="store_true")

    p = sub.add_parser("pack", help="pack frame data into HDF5")
    p.add_argument("--frames-dir",   default=str(FRAMES_DIR))
    p.add_argument("--inputs",       default=str(INPUTS_OUT))
    p.add_argument("--output",       default=str(HDF5_OUT))
    p.add_argument("--spot-check",   metavar="H5_PATH")
    p.add_argument("--check-frames", default="0,99,499")
    p.add_argument("--check-out",    default=str(DATASET_ROOT / "spot_checks"))

    args = parser.parse_args()
    {"deploy": cmd_deploy, "capture": cmd_capture, "launch": cmd_launch, "pack": cmd_pack}[args.cmd](args)


if __name__ == "__main__":
    main()
