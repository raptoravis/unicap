#!/usr/bin/env python3
"""
unicap main controller — interactive in-game workflow.

Hotkeys (game window must have focus):
  F6  开始 survey（自动扫描 pre-UI skip）
  F8  开始采集（如未 survey 过会先自动 survey）
  F9  停止当前 survey/采集

Usage:
  uv run main.py launch [--game-path P] [--game-name N]
                        [--dataset-root R] [--ui-mode {no-ui,ui-only,both}]
                        [--no-hints]
  uv run main.py video  --frames-dir P [--output P] [--fps N]
  uv run main.py pack   [--frames-dir P] [--inputs P] [--output P]

ui-mode:
  no-ui    只输出 pre-UI 帧（默认；F6 survey 必需）
  ui-only  只输出 post-UI BackBuffer 帧（不需 survey；F6 无效）
  both     两路并行输出（pre-UI + post-UI；F6 survey 必需）
"""

import argparse
import configparser
import ctypes
import os
import shutil
import subprocess
import sys
import tempfile
import threading
import time
from datetime import datetime
from pathlib import Path

import tools.capture.capture_all as capture_all
import tools.capture.pack_hdf5 as pack_hdf5
import tools.capture.survey as survey_mod
from tools.capture.config import DATASET_ROOT, FRAMES_DIR, GAME_PATH, HDF5_OUT, INPUTS_OUT

ROOT = Path(__file__).parent
CONFIG_DIR = ROOT / "config"
UNICAP_TEMP = Path(tempfile.gettempdir()) / "unicap"

# Capture defaults — change here if a different rate/resolution is needed.
# 1920×1080 matches FF7R's native scene RT — skipping the worker resize cuts
# ~40 ms/frame off the save path, and avoids the 16:9 → 4:3 horizontal stretch
# the old 1600×1200 default introduced.
CAP_WIDTH  = 1920
CAP_HEIGHT = 1080
CAP_FPS    = 30
SURVEY_FPS = 1.0   # Python wait cadence during survey sweep

VK_F6, VK_F8, VK_F9 = 0x75, 0x77, 0x78
_user32 = ctypes.WinDLL("user32")


# ── State sidecar (Python → addon) ────────────────────────────────────────────

def _set_state(game_dir: Path, state: str) -> None:
    """Write current high-level state to fc_state.txt for the addon overlay."""
    try:
        (game_dir / "fc_state.txt").write_text(state, encoding="utf-8")
    except OSError:
        pass


def _set_hints_flag(game_dir: Path, enabled: bool) -> None:
    try:
        (game_dir / "fc_hints.txt").write_text("1" if enabled else "0", encoding="utf-8")
    except OSError:
        pass


# ── Hotkey polling ────────────────────────────────────────────────────────────

def _key_down(vk: int) -> bool:
    return bool(_user32.GetAsyncKeyState(vk) & 0x8000)


def _drain_keys(vks, poll: float = 0.05) -> None:
    while any(_key_down(vk) for vk in vks):
        time.sleep(poll)


def _wait_for_keys(vks, abort: threading.Event = None, poll: float = 0.05):
    """Edge-detected wait for any of `vks`. Returns the pressed VK, or None on abort."""
    _drain_keys(vks, poll)
    while True:
        if abort is not None and abort.is_set():
            return None
        for vk in vks:
            if _key_down(vk):
                _drain_keys([vk], poll)
                return vk
        time.sleep(poll)


def _spawn_f9_watcher(stop_event: threading.Event) -> threading.Event:
    """Background thread that sets stop_event when F9 is pressed.
    Returns a quit-event the caller can set to release the watcher early."""
    quit_evt = threading.Event()

    def watcher():
        _drain_keys([VK_F9])
        while not quit_evt.is_set() and not stop_event.is_set():
            if _key_down(VK_F9):
                stop_event.set()
                return
            time.sleep(0.05)

    threading.Thread(target=watcher, daemon=True).start()
    return quit_evt


# ── Survey result lookup ──────────────────────────────────────────────────────

def _load_recommended_skip(dataset_root: Path, game_name: str) -> int | None:
    p = dataset_root / game_name / "survey" / "recommended_skip.txt"
    try:
        v = int(p.read_text(encoding="utf-8").strip())
        return v if v >= 0 else None
    except (OSError, ValueError):
        return None


# ── Game path resolution ──────────────────────────────────────────────────────

_SKIP_EXE = {
    "crashreportclient.exe", "ue4prereqsetup_x64.exe", "ueprereqsetup_x64.exe",
    "dxsetup.exe", "uninstall.exe", "uninst.exe",
    "vcredist_x64.exe", "vc_redist.x64.exe", "dotnetfx.exe",
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


DXGI_DLL = ROOT / "dist" / "dxgi.dll"
ADDON_BIN = ROOT / "dist" / "frame_capture.addon"
SHADER_SRC = ROOT / "shaders"


# ── unicap.ini / preset writers ───────────────────────────────────────────────

def _ensure_addon_enabled(addon_dir: Path, pre_ui_skip: int = 0, ui_mode: str = "no-ui"):
    """ui_mode: 'no-ui' (pre-UI only) | 'ui-only' (post-UI BB only) | 'both' (pre-UI + post-UI)."""
    pre_ui_flag  = "0" if ui_mode == "ui-only" else "1"
    both_flag    = "1" if ui_mode == "both" else "0"
    UNICAP_TEMP.mkdir(parents=True, exist_ok=True)
    ini = UNICAP_TEMP / "unicap.ini"
    cfg = configparser.RawConfigParser()
    cfg.optionxform = str
    if ini.exists():
        cfg.read(ini, encoding="utf-8")
    settings = [
        ("ADDON", "AddonPath", str(addon_dir)),
        ("ADDON", "FC_EnableCapture", "1"),
        ("ADDON", "FC_ExportDepth", "1"),
        ("ADDON", "FC_ExportNormal", "0"),
        ("ADDON", "FC_CaptureWidth", str(CAP_WIDTH)),
        ("ADDON", "FC_CaptureHeight", str(CAP_HEIGHT)),
        ("ADDON", "FC_TargetFPS", str(CAP_FPS)),
        ("ADDON", "FC_PreUICapture", pre_ui_flag),
        ("ADDON", "FC_PreUISkipCount", str(pre_ui_skip)),
        ("ADDON", "FC_BothCapture", both_flag),
        ("GENERAL", "EffectSearchPaths", str(ROOT / "shaders")),
        ("GENERAL", "IntermediateCachePath", str(UNICAP_TEMP)),
        ("GENERAL", "TextureSearchPaths", str(ROOT / "shaders")),
        ("GENERAL", "PresetPath", str(CONFIG_DIR / "unicapPreset.ini")),
        ("OVERLAY", "ShowScreenshotMessage", "0"),
        ("OVERLAY", "TutorialProgress", "4"),
        ("INPUT", "KeyOverlay", "0,0,0,0"),
        ("INPUT", "KeyScreenshot", "0,0,0,0"),
        ("INPUT", "KeyEffects", "0,0,0,0"),
        ("INPUT", "KeyReload", "0,0,0,0"),
        ("INPUT", "KeyNextPreset", "0,0,0,0"),
        ("INPUT", "KeyPreviousPreset", "0,0,0,0"),
    ]
    for section, key, value in settings:
        if not cfg.has_section(section):
            cfg.add_section(section)
        cfg.set(section, key, value)
    with open(ini, "w", encoding="utf-8") as f:
        cfg.write(f)


def _ensure_preset():
    CONFIG_DIR.mkdir(exist_ok=True)
    preset = CONFIG_DIR / "unicapPreset.ini"
    # CaptureStatus runs last so the indicator overlays the displayed backbuffer
    # without affecting UIRemove_ColorTex (taken in UIRemove's first pass).
    techniques = "DepthToAddon@DepthToAddon.fx,UIRemove@UIRemove.fx,CaptureStatus@CaptureStatus.fx"
    content = f"Techniques={techniques}\nTechniqueSorting={techniques}\n"
    existing = preset.read_text(encoding="utf-8") if preset.exists() else ""
    if "CaptureStatus@CaptureStatus.fx" not in existing:
        preset.write_text(content, encoding="utf-8")


def _symlink_file(src: Path, dst: Path):
    if dst.is_symlink() or dst.exists():
        dst.unlink()
    try:
        os.symlink(str(src), str(dst))
    except OSError as e:
        print(f"[警告] 无法创建符号链接（{e.strerror}），改用复制（可启用 Windows 开发者模式）")
        shutil.copy2(src, dst)
        print(f"[COPY]  {dst.name}")


# ── Subcommand: deploy ────────────────────────────────────────────────────────

def cmd_deploy(args):
    game_dir, game_exe = _resolve_game_path(args.game_path)

    for f in [DXGI_DLL, ADDON_BIN]:
        if not f.exists():
            sys.exit(f"[错误] 文件不存在：{f}\n       请先执行 scripts\\build.ps1")

    dst_dll = game_dir / "dxgi.dll"
    bak = game_dir / "dxgi.dll.bak"
    if dst_dll.exists() and not dst_dll.is_symlink() and not bak.exists():
        shutil.copy2(dst_dll, bak)
    _symlink_file(DXGI_DLL, dst_dll)

    dataset_root_arg = getattr(args, "dataset_root", "") or ""
    dataset_root = Path(dataset_root_arg) if dataset_root_arg else DATASET_ROOT
    game_name = getattr(args, "game_name", "") or game_exe.stem
    ui_mode = getattr(args, "ui_mode", "no-ui")
    pre_ui_skip = _load_recommended_skip(dataset_root, game_name)
    if pre_ui_skip is not None:
        print(f"[DEPLOY] 自动加载 survey 推荐 pre_ui_skip={pre_ui_skip}（{game_name}）")
    else:
        pre_ui_skip = 0

    _ensure_addon_enabled(ADDON_BIN.parent, pre_ui_skip=pre_ui_skip, ui_mode=ui_mode)
    _ensure_preset()
    return game_dir, game_exe, game_name, dataset_root


# ── Subcommand: launch (interactive) ──────────────────────────────────────────

def cmd_launch(args):
    game_dir, game_exe, game_name, dataset_root = cmd_deploy(args)

    print(f"\n[启动] {game_exe}")
    env = {**os.environ, "RESHADE_BASE_PATH_OVERRIDE": str(UNICAP_TEMP)}
    subprocess.Popen([str(game_exe)], cwd=str(game_dir), env=env)

    _set_hints_flag(game_dir, args.hints)
    _set_state(game_dir, "idle")

    if args.hints:
        ui_mode = getattr(args, "ui_mode", "no-ui")
        print()
        print(f"┌─ 操作提示 (ui-mode={ui_mode}) ────────────────────────┐")
        if ui_mode == "ui-only":
            print("│  F8  开始采集 post-UI BackBuffer（无需 survey）       │")
        elif ui_mode == "both":
            print("│  F6  开始 survey（自动扫描无 UI 的 skip 值）          │")
            print("│  F8  开始采集（pre-UI + post-UI 双流）                │")
        else:
            print("│  F6  开始 survey（自动扫描无 UI 的 skip 值）          │")
            print("│  F8  开始采集（首次会先自动 survey）                  │")
        print("│  F9  停止当前 survey 或采集                           │")
        print("│  Ctrl+C  退出 main.py（不会关闭游戏）                 │")
        print("└──────────────────────────────────────────────────────┘\n")

    try:
        _interactive_loop(args, game_dir, game_name, dataset_root)
    except KeyboardInterrupt:
        print("\n[退出] Ctrl+C，main.py 退出。游戏继续运行。")
    finally:
        _set_state(game_dir, "idle")


def _interactive_loop(args, game_dir: Path, game_name: str, dataset_root: Path):
    ui_mode = getattr(args, "ui_mode", "no-ui")
    needs_survey = ui_mode != "ui-only"  # ui-only 直接抓 BackBuffer，无需 skip

    while True:
        _set_state(game_dir, "idle")
        if needs_survey:
            print("[等待] 按 F6 = survey   F8 = 采集   (Ctrl+C 退出)")
            key = _wait_for_keys([VK_F6, VK_F8])
        else:
            print(f"[等待] 按 F8 = 采集（mode={ui_mode}，无需 survey）   (Ctrl+C 退出)")
            key = _wait_for_keys([VK_F8])

        if key == VK_F6:
            if not needs_survey:
                print(f"[F6] mode={ui_mode}，本模式不需要 survey，已忽略")
                continue
            _run_survey(args, game_dir, game_name, dataset_root)

        elif key == VK_F8:
            ran_survey = False
            if needs_survey and _load_recommended_skip(dataset_root, game_name) is None:
                print("[F8] 未检测到 survey 推荐值，先自动 survey…")
                ok = _run_survey(args, game_dir, game_name, dataset_root)
                ran_survey = True
                if not ok:
                    print("[F8] survey 未完成，已取消采集。再次按 F8 重试")
                    continue
            _run_capture(args, game_dir, game_name, dataset_root, just_surveyed=ran_survey)


def _run_survey(args, game_dir: Path, game_name: str, dataset_root: Path) -> bool:
    """Returns True if survey produced a recommendation."""
    _set_state(game_dir, "surveying")
    print("\n[SURVEY] 开始扫描…（F9 中止）")

    abort = threading.Event()
    quit_watcher = _spawn_f9_watcher(abort)

    survey_dir = dataset_root / game_name / "survey"
    try:
        recommended = survey_mod.run(
            game_dir=game_dir,
            survey_dir=survey_dir,
            step=5,
            fps=SURVEY_FPS,
            timeout_per_skip=10.0,
            abort_event=abort,
        )
    finally:
        quit_watcher.set()
        _set_state(game_dir, "idle")

    if abort.is_set():
        print("[SURVEY] F9 中止")
        return False
    if recommended is None:
        return False

    # Persist recommendation to ini for next deploy
    _ensure_addon_enabled(ADDON_BIN.parent, pre_ui_skip=recommended,
                          ui_mode=getattr(args, "ui_mode", "no-ui"))

    # Make the new skip take effect immediately in the running game:
    # one-shot survey-mode write so the addon picks up `recommended`,
    # then clear so subsequent capture frames use normal filenames.
    _write_skip_pulse(game_dir, recommended)
    return True


def _write_skip_pulse(game_dir: Path, skip: int):
    """Write fc_skip_count.txt = skip; wait one capture interval; clear it.
    Causes the addon to update g_pre_ui_skip and exit survey filename mode."""
    p = game_dir / "fc_skip_count.txt"
    try:
        p.write_text(str(skip), encoding="utf-8")
        time.sleep(max(2.0 / max(CAP_FPS, 1), 0.5))  # ≥ 2 frames at CAP_FPS
        try:
            p.unlink(missing_ok=True)
        except OSError:
            p.write_text("", encoding="utf-8")
    except OSError as e:
        print(f"[WARN] 无法写 fc_skip_count.txt: {e}")


def _run_capture(args, game_dir: Path, game_name: str, dataset_root: Path, just_surveyed: bool):
    _set_state(game_dir, "capturing")
    tag = datetime.now().strftime("%Y%m%d_%H%M%S")
    session_dir = dataset_root / game_name / tag
    frames_dir = session_dir / "frames"
    inputs_out = session_dir / "inputs.jsonl"
    hdf5_out   = session_dir / "dataset.h5"
    video_out  = session_dir / "video.mp4"
    session_dir.mkdir(parents=True, exist_ok=True)

    print(f"\n[CAPTURE] 开始采集 (F9 停止) → {session_dir}")
    if just_surveyed:
        time.sleep(0.5)  # let the post-survey skip pulse settle

    stop_event = threading.Event()
    quit_watcher = _spawn_f9_watcher(stop_event)
    try:
        capture_all.run(
            fps=CAP_FPS,
            duration=None,
            frames_dir=frames_dir,
            inputs_out=inputs_out,
            watch_dir=game_dir,
            stop_event=stop_event,
        )
    finally:
        quit_watcher.set()
        _set_state(game_dir, "idle")

    _make_video(frames_dir, video_out, CAP_FPS, glob_pat="*BackBuffer.bmp")
    # "both" mode: 也生成 post-UI 视频
    if any(frames_dir.glob("*BackBufferUI.bmp")):
        _make_video(frames_dir, session_dir / "video_ui.mp4", CAP_FPS,
                    glob_pat="*BackBufferUI.bmp")
    print(f"[会话] {session_dir}")
    print("[PACK] 开始打包 HDF5…")
    pack_hdf5.pack(frames_dir=frames_dir, inputs_path=inputs_out, output_path=hdf5_out)


# ── Video + pack ──────────────────────────────────────────────────────────────

def _make_video(frames_dir: Path, output: Path, fps: int, glob_pat: str = "*BackBuffer.bmp"):
    import cv2

    bmps = sorted(frames_dir.glob(glob_pat))
    if not bmps and glob_pat == "*BackBuffer.bmp":
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
        w_enc = w - (w % 2)
        h_enc = h - (h % 2)
        cmd = [
            ffmpeg, "-y",
            "-f", "rawvideo", "-vcodec", "rawvideo",
            "-s", f"{w_enc}x{h_enc}", "-pix_fmt", "bgr24",
            "-r", str(fps), "-i", "pipe:",
            "-c:v", "libx264", "-pix_fmt", "yuv420p", "-crf", "18",
            str(output),
        ]
        proc = subprocess.Popen(cmd, stdin=subprocess.PIPE, stderr=subprocess.PIPE)
        ok = True
        for i, bmp in enumerate(bmps):
            img = cv2.imread(str(bmp))
            if img is not None:
                if (w_enc, h_enc) != (w, h):
                    img = img[:h_enc, :w_enc]
                try:
                    proc.stdin.write(img.tobytes())
                except OSError:
                    ok = False
                    break
            if (i + 1) % fps == 0:
                print(f"[VIDEO] {i + 1}/{len(bmps)} 帧", flush=True)
        proc.stdin.close()
        stderr_out = proc.stderr.read()
        proc.wait()
        if not ok or proc.returncode != 0:
            print(f"[VIDEO] ffmpeg 失败 (code {proc.returncode}):\n{stderr_out.decode(errors='replace')}")
            return
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


# ── CLI ───────────────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(prog="main.py")
    sub = parser.add_subparsers(dest="cmd", required=True)

    p = sub.add_parser("launch", help="部署 + 启动游戏 + 进入交互式 F6/F8/F9 工作流")
    p.add_argument("--game-path", default=str(GAME_PATH))
    p.add_argument("--game-name", default="", help="游戏名（输出路径第一级，默认从 exe 推导）")
    p.add_argument("--dataset-root", default="", metavar="PATH")
    p.add_argument("--ui-mode", choices=["no-ui", "ui-only", "both"], default="no-ui",
                   help="输出: no-ui=只 pre-UI（默认）, ui-only=只 post-UI BB（无需 survey）, both=双流")
    p.add_argument("--hints", action=argparse.BooleanOptionalAction, default=True,
                   help="显示控制台 + addon overlay 操作提示（默认开启）")

    p = sub.add_parser("video", help="从 frames 目录生成 MP4")
    p.add_argument("--frames-dir", default=str(FRAMES_DIR))
    p.add_argument("--output", default=str(DATASET_ROOT / "video.mp4"))
    p.add_argument("--fps", type=int, default=CAP_FPS)

    p = sub.add_parser("pack", help="把 frames + inputs 打包成 HDF5")
    p.add_argument("--frames-dir", default=str(FRAMES_DIR))
    p.add_argument("--inputs", default=str(INPUTS_OUT))
    p.add_argument("--output", default=str(HDF5_OUT))
    p.add_argument("--spot-check", metavar="H5_PATH")
    p.add_argument("--check-frames", default="0,99,499")
    p.add_argument("--check-out", default=str(DATASET_ROOT / "spot_checks"))

    args = parser.parse_args()
    {"launch": cmd_launch, "video": cmd_video, "pack": cmd_pack}[args.cmd](args)


if __name__ == "__main__":
    main()
