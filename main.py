#!/usr/bin/env python3
"""
unicap main controller — interactive in-game workflow.

Hotkeys (game window must have focus):
  F6  开始 survey（自动扫描 pre-UI skip）
  F8  开始采集（如未 survey 过会先自动 survey）
  F9  停止当前 survey/采集

Usage:
  uv run main.py launch [--game-path P] [--game-name N]
                        [--dataset-root R] [--ui-mode {no-ui,ui,both}]
                        [--no-hints] [--no-video] [--pack]
  uv run main.py video  --game-dir DIR [--fps N]
  uv run main.py pack   --game-dir DIR [--no-depth]

video / pack: 扫描 --game-dir 下所有采集会话（dataset-root/<game>/<timestamp>/），
              为缺少 video.mp4 / dataset.h5 的会话生成；已存在则跳过。

ui-mode:
  no-ui    只输出 pre-UI 帧（默认；F6 survey 必需）
  ui       只输出 post-UI BackBuffer 帧（不需 survey；F6 无效）
  both     两路并行输出（pre-UI + post-UI；F6 survey 必需）
"""

import argparse
import configparser
import ctypes
import os
import re
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
from tools.capture.config import DATASET_ROOT, GAME_PATH

# Source mode: __file__ → repo root. Nuitka standalone: __file__ → unicap.dist/,
# which contains dist/ shaders/ config/ alongside unicap.exe — same layout, so
# no special-casing needed. Onefile is NOT supported (AV flags the bootloader).
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


# ── Timing helper ─────────────────────────────────────────────────────────────

def _fmt_dur(seconds: float) -> str:
    if seconds >= 60:
        m, s = divmod(seconds, 60)
        return f"{int(m)}m{s:.1f}s"
    return f"{seconds:.1f}s"


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
    """ui_mode: 'no-ui' (pre-UI only) | 'ui' (post-UI BB only) | 'both' (pre-UI + post-UI)."""
    pre_ui_flag  = "0" if ui_mode == "ui" else "1"
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
    except OSError:
        shutil.copy2(src, dst)


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
        if ui_mode == "ui":
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
    needs_survey = ui_mode != "ui"  # ui 模式直接抓 BackBuffer，无需 skip

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
    t0 = time.perf_counter()

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

    elapsed = time.perf_counter() - t0
    if abort.is_set():
        print(f"[SURVEY] F9 中止  耗时 {_fmt_dur(elapsed)}")
        return False
    if recommended is None:
        print(f"[SURVEY] 未推荐 skip  耗时 {_fmt_dur(elapsed)}")
        return False
    print(f"[SURVEY] 完成 推荐 skip={recommended}  耗时 {_fmt_dur(elapsed)}")

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
    video_out  = session_dir / "video.mp4"
    session_dir.mkdir(parents=True, exist_ok=True)

    print(f"\n[CAPTURE] 开始采集 (F9 停止) → {session_dir}")
    if just_surveyed:
        time.sleep(0.5)  # let the post-survey skip pulse settle

    t_cap = time.perf_counter()
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
    print(f"[CAPTURE] 总耗时 {_fmt_dur(time.perf_counter() - t_cap)}")

    if getattr(args, "video", True):
        t_video = time.perf_counter()
        _make_video(frames_dir, video_out, fps=0, glob_pat="*BackBuffer.bmp")
        # "both" mode: 也生成 post-UI 视频
        if any(frames_dir.glob("*BackBufferUI.bmp")):
            _make_video(frames_dir, session_dir / "video_ui.mp4", fps=0,
                        glob_pat="*BackBufferUI.bmp")
        print(f"[VIDEO] 总耗时 {_fmt_dur(time.perf_counter() - t_video)}")
    else:
        print(f"[VIDEO] --no-video 跳过；待会儿运行：")
        print(f"        uv run main.py video \"{dataset_root / game_name}\"")

    print(f"[会话] {session_dir}")
    if getattr(args, "pack", False):
        print("[PACK] 开始打包 HDF5…")
        t_pack = time.perf_counter()
        try:
            pack_hdf5.pack(frames_dir=frames_dir, inputs_path=inputs_out,
                           output_path=session_dir / "dataset.h5")
        except Exception as e:
            print(f"[PACK] 失败：{e}")
        print(f"[PACK] 总耗时 {_fmt_dur(time.perf_counter() - t_pack)}")
    else:
        print(f"[PACK] launch 默认不打包（加 --pack 可即时打包），待会儿运行：")
        print(f"       uv run main.py pack \"{dataset_root / game_name}\"")


# ── Video + pack ──────────────────────────────────────────────────────────────

# BMP 文件名格式：<prefix> YYYY-MM-DD HH-MM-SS <ms> BackBuffer.bmp
_RE_BMP_TS = re.compile(r' (\d{4}-\d{2}-\d{2}) (\d{2}-\d{2}-\d{2}) (\d+) ')


def _bmp_ts_ms(p: Path) -> int | None:
    m = _RE_BMP_TS.search(p.name)
    if not m:
        return None
    try:
        dt = datetime.strptime(f"{m.group(1)} {m.group(2).replace('-', ':')}",
                               "%Y-%m-%d %H:%M:%S")
        return int(dt.timestamp() * 1000) + int(m.group(3))
    except ValueError:
        return None


def _estimate_fps(bmps: list[Path]) -> float | None:
    """从首/末 BMP 文件名时间戳估算实际 fps；不可解析则返回 None。"""
    if len(bmps) < 2:
        return None
    t0, t1 = _bmp_ts_ms(bmps[0]), _bmp_ts_ms(bmps[-1])
    if t0 is None or t1 is None or t1 <= t0:
        return None
    return (len(bmps) - 1) * 1000.0 / (t1 - t0)


def _make_video(frames_dir: Path, output: Path, fps: float = 0,
                glob_pat: str = "*BackBuffer.bmp"):
    """fps=0 时按文件名时间戳自动估算实际采集 fps，避免快进/慢放。"""
    import cv2

    bmps = sorted(frames_dir.glob(glob_pat))
    if not bmps and glob_pat == "*BackBuffer.bmp":
        bmps = sorted(frames_dir.glob("*.bmp"))
    if not bmps:
        print("[VIDEO] 未找到 BMP 文件，跳过")
        return

    if fps <= 0:
        est = _estimate_fps(bmps)
        if est is None:
            fps = CAP_FPS
            print(f"[VIDEO] 时间戳估算失败，回退 fps={fps}")
        else:
            fps = est
            print(f"[VIDEO] 自动 fps={fps:.2f}（{len(bmps)} 帧 / 文件名时间戳）")

    first = cv2.imread(str(bmps[0]))
    if first is None:
        print("[VIDEO] 无法读取第一帧，跳过")
        return
    h, w = first.shape[:2]
    output.parent.mkdir(parents=True, exist_ok=True)

    progress_step = max(int(round(fps)), 1)

    ffmpeg = shutil.which("ffmpeg")
    if ffmpeg:
        w_enc = w - (w % 2)
        h_enc = h - (h % 2)
        cmd = [
            ffmpeg, "-y",
            "-f", "rawvideo", "-vcodec", "rawvideo",
            "-s", f"{w_enc}x{h_enc}", "-pix_fmt", "bgr24",
            "-r", f"{fps:.6f}", "-i", "pipe:",
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
            if (i + 1) % progress_step == 0:
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
            if (i + 1) % progress_step == 0:
                print(f"[VIDEO] {i + 1}/{len(bmps)} 帧", flush=True)
        writer.release()

    print(f"[VIDEO] 完成：{len(bmps)} 帧 @ {fps}fps → {output}")


def cmd_video(args):
    if not args.game_dir:
        sys.exit("[错误] video 需要游戏目录参数：uv run main.py video --game-dir <DIR>")

    game_dir = Path(args.game_dir)
    if not game_dir.is_dir():
        sys.exit(f"[错误] 游戏目录不存在：{game_dir}")

    sessions = sorted(
        d for d in game_dir.iterdir()
        if d.is_dir() and d.name != "survey" and (d / "frames").is_dir()
    )
    if not sessions:
        sys.exit(f"[错误] 在 {game_dir} 下未找到任何采集会话（缺少 <ts>/frames/）")

    print(f"[VIDEO] 找到 {len(sessions)} 个会话（{game_dir}）")
    made = skipped = failed = 0
    t_total = time.perf_counter()
    for sess in sessions:
        frames = sess / "frames"
        # 主流：BackBuffer
        targets = [(sess / "video.mp4", "*BackBuffer.bmp")]
        # post-UI 流（both 模式才存在）
        if any(frames.glob("*BackBufferUI.bmp")):
            targets.append((sess / "video_ui.mp4", "*BackBufferUI.bmp"))

        for out, pat in targets:
            if out.exists():
                print(f"[SKIP] {sess.name}/{out.name}（已存在, {out.stat().st_size/1024/1024:.1f} MB）")
                skipped += 1
                continue
            print(f"\n[VIDEO] {sess.name}/{out.name} ←")
            t0 = time.perf_counter()
            try:
                _make_video(frames, out, args.fps, glob_pat=pat)
            except Exception as e:
                elapsed = time.perf_counter() - t0
                print(f"[ERROR] {sess.name}/{out.name} 失败：{e}  耗时 {_fmt_dur(elapsed)}")
                failed += 1
                continue
            elapsed = time.perf_counter() - t0
            if not out.exists():
                # _make_video 内部 print 跳过 / 失败 但未抛错
                failed += 1
                continue
            print(f"[VIDEO] {sess.name}/{out.name} 完成  耗时 {_fmt_dur(elapsed)}")
            made += 1

    print(f"\n[DONE] 生成 {made}，跳过 {skipped}，失败 {failed}；总耗时 {_fmt_dur(time.perf_counter() - t_total)}")


def cmd_pack(args):
    if args.spot_check:
        indices = [int(x) for x in args.check_frames.split(",")]
        pack_hdf5.spot_check(Path(args.spot_check), indices, Path(args.check_out))
        return

    if not args.game_dir:
        sys.exit("[错误] pack 需要游戏目录参数：uv run main.py pack --game-dir <DIR>")

    game_dir = Path(args.game_dir)
    if not game_dir.is_dir():
        sys.exit(f"[错误] 游戏目录不存在：{game_dir}")

    sessions = sorted(
        d for d in game_dir.iterdir()
        if d.is_dir() and d.name != "survey" and (d / "frames").is_dir()
    )
    if not sessions:
        sys.exit(f"[错误] 在 {game_dir} 下未找到任何采集会话（缺少 <ts>/frames/）")

    print(f"[PACK] 找到 {len(sessions)} 个会话（{game_dir}）")
    packed = skipped = failed = 0
    t_total = time.perf_counter()
    for sess in sessions:
        h5 = sess / "dataset.h5"
        if h5.exists():
            print(f"[SKIP] {sess.name}（已存在 dataset.h5, {h5.stat().st_size/1024/1024:.1f} MB）")
            skipped += 1
            continue
        frames = sess / "frames"
        inputs = sess / "inputs.jsonl"
        if not inputs.is_file():
            print(f"[SKIP] {sess.name}（缺少 inputs.jsonl）")
            failed += 1
            continue

        print(f"\n[PACK] {sess.name} →")
        t0 = time.perf_counter()
        try:
            pack_hdf5.pack(frames_dir=frames, inputs_path=inputs, output_path=h5,
                           include_depth=args.depth)
        except Exception as e:
            elapsed = time.perf_counter() - t0
            print(f"[ERROR] {sess.name} 失败：{e}  耗时 {_fmt_dur(elapsed)}")
            failed += 1
            continue
        elapsed = time.perf_counter() - t0
        print(f"[PACK] {sess.name} 完成  耗时 {_fmt_dur(elapsed)}")
        packed += 1

    print(f"\n[DONE] 打包 {packed}，跳过 {skipped}，失败 {failed}；总耗时 {_fmt_dur(time.perf_counter() - t_total)}")


# ── CLI ───────────────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(prog="unicap")
    sub = parser.add_subparsers(dest="cmd", required=True)

    p = sub.add_parser("launch", help="部署 + 启动游戏 + 进入交互式 F6/F8/F9 工作流")
    p.add_argument("--game-path", default=str(GAME_PATH))
    p.add_argument("--game-name", default="", help="游戏名（输出路径第一级，默认从 exe 推导）")
    p.add_argument("--dataset-root", default="", metavar="PATH")
    p.add_argument("--ui-mode", choices=["no-ui", "ui", "both"], default="no-ui",
                   help="输出: no-ui=只 pre-UI（默认）, ui=只 post-UI BB（无需 survey）, both=双流")
    p.add_argument("--hints", action=argparse.BooleanOptionalAction, default=True,
                   help="显示控制台 + addon overlay 操作提示（默认开启）")
    p.add_argument("--video", action=argparse.BooleanOptionalAction, default=True,
                   help="F9 停止采集后生成 video.mp4（默认开启；--no-video 跳过）")
    p.add_argument("--pack", action="store_true",
                   help="F9 停止采集后立即打包 HDF5（默认不打包）")

    p = sub.add_parser("video", help="批量生成游戏目录下所有缺失的 video.mp4 / video_ui.mp4")
    p.add_argument("--game-dir", default="", metavar="DIR",
                   help="dataset-root 下的游戏目录（其下含 <YYYYMMDD_HHMMSS>/frames/ 子目录）")
    p.add_argument("--fps", type=float, default=0,
                   help="编码 fps；默认 0 = 从 BMP 文件名时间戳自动估算（推荐）")

    p = sub.add_parser("pack", help="批量打包游戏目录下所有采集会话；已有 dataset.h5 跳过")
    p.add_argument("--game-dir", default="", metavar="DIR",
                   help="dataset-root 下的游戏目录（其下含 <YYYYMMDD_HHMMSS>/frames/ 子目录）")
    p.add_argument("--depth", action=argparse.BooleanOptionalAction, default=True,
                   help="包含 /depth + /normal + UI mask（默认开启；--no-depth 跳过 EXR、只打 color）")
    p.add_argument("--spot-check", metavar="H5_PATH")
    p.add_argument("--check-frames", default="0,99,499")
    p.add_argument("--check-out", default=str(DATASET_ROOT / "spot_checks"))

    args = parser.parse_args()
    {"launch": cmd_launch, "video": cmd_video, "pack": cmd_pack}[args.cmd](args)


if __name__ == "__main__":
    main()
