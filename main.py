#!/usr/bin/env python3
"""
unicap main controller — interactive in-game workflow.

Hotkeys (GetAsyncKeyState polls globally — game window doesn't need focus):
  F8  开始采集（首次自动 survey；重 survey: 删 dataset/<game>/survey/recommended_skip.txt）
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
  no-ui    只输出 pre-UI 帧（默认；F8 首次会自动 survey）
  ui       只输出 post-UI BackBuffer 帧（不需 survey）
  both     两路并行输出（pre-UI + post-UI；F8 首次会自动 survey）
"""

import argparse
import atexit
import configparser
import ctypes
import os
import re
import shutil
import signal
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


def _read_version() -> str:
    """Read [project].version from pyproject.toml. Source mode reads repo
    pyproject.toml; packaged mode reads the copy embedded into unicap.dist/."""
    try:
        import tomllib
        return tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))["project"]["version"]
    except (ImportError, OSError, KeyError):
        return "unknown"


VERSION = _read_version()

# Capture defaults — change here if a different rate/resolution is needed.
# 1920×1080 matches FF7R's native scene RT — skipping the worker resize cuts
# ~40 ms/frame off the save path, and avoids the 16:9 → 4:3 horizontal stretch
# the old 1600×1200 default introduced.
CAP_WIDTH  = 1920
CAP_HEIGHT = 1080
CAP_FPS    = 30
SURVEY_FPS = 1.0   # Python wait cadence during survey sweep

VK_F8, VK_F9 = 0x77, 0x78
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
VULKAN_LAYER_DLL  = ROOT / "dist" / "UniCap64.dll"
VULKAN_LAYER_JSON = ROOT / "dist" / "UniCap64.json"
VULKAN_LAYER_NAME = "VK_LAYER_unicap"  # must match UniCap64.json `layer.name`
ADDON_BIN = ROOT / "dist" / "frame_capture.addon"
SHADER_SRC = ROOT / "shaders"


# ── Vulkan layer registration (HKCU) ──────────────────────────────────────────
# Steam relaunches games in its own subprocess tree, stripping env vars set by
# main.py. Env-var-only injection (VK_IMPLICIT_LAYER_PATH etc.) silently fails
# for any Steam-required game (DOOM 2016/Eternal etc.). HKCU registration is
# Steam-immune since the loader reads it during vkCreateInstance regardless of
# parent process. Cleanup is critical because a leaked entry affects ALL Vulkan
# apps system-wide. Three-layer cleanup: atexit + signal handlers + startup
# stale-entry scan (idempotent — manifest path is install-unique).

_VK_LAYER_REGKEY = r"Software\Khronos\Vulkan\ImplicitLayers"
_vk_registered_value: str | None = None  # absolute manifest path; None = not registered


def _vk_register_layer(manifest_path: Path) -> None:
    """Register UniCap64.json under HKCU\\...\\ImplicitLayers (DWORD value=0 = enabled)."""
    import winreg
    global _vk_registered_value
    value_name = str(manifest_path.resolve())
    with winreg.CreateKeyEx(winreg.HKEY_CURRENT_USER, _VK_LAYER_REGKEY, 0,
                            winreg.KEY_SET_VALUE | winreg.KEY_QUERY_VALUE) as key:
        winreg.SetValueEx(key, value_name, 0, winreg.REG_DWORD, 0)
    _vk_registered_value = value_name
    atexit.register(_vk_unregister_layer)
    # Best-effort signal hookup: SIGINT becomes KeyboardInterrupt → caught by
    # cmd_launch's try/finally; SIGBREAK + console-close need explicit handlers.
    try:
        signal.signal(signal.SIGINT, _vk_signal_cleanup)
        signal.signal(signal.SIGBREAK, _vk_signal_cleanup)  # type: ignore[attr-defined]
    except (AttributeError, ValueError):
        pass
    _vk_install_console_handler()


def _vk_unregister_layer() -> None:
    """Idempotent — safe to call multiple times. Removes only OUR manifest entry."""
    import winreg
    global _vk_registered_value
    if _vk_registered_value is None:
        return
    try:
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, _VK_LAYER_REGKEY, 0,
                            winreg.KEY_SET_VALUE) as key:
            winreg.DeleteValue(key, _vk_registered_value)
    except (FileNotFoundError, OSError):
        pass
    _vk_registered_value = None


def _vk_signal_cleanup(signum, _frame):
    _vk_unregister_layer()
    # Re-raise as KeyboardInterrupt so the existing cmd_launch handler runs cleanup
    raise KeyboardInterrupt()


def _vk_install_console_handler() -> None:
    """Hook Win32 SetConsoleCtrlHandler for window-close / logoff (signal module
    doesn't catch CTRL_CLOSE_EVENT). The handler runs in a separate thread that
    Windows kills ~5s after our return — enough for one registry delete."""
    @ctypes.WINFUNCTYPE(ctypes.c_int, ctypes.c_uint)
    def handler(ctrl_type):
        if ctrl_type in (0, 1, 2, 5, 6):  # CTRL_C, CTRL_BREAK, CTRL_CLOSE, CTRL_LOGOFF, CTRL_SHUTDOWN
            _vk_unregister_layer()
        return 0  # let default handler run
    # Keep a strong ref so GC doesn't free the callback before Windows calls it
    if not hasattr(_vk_install_console_handler, "_handler_ref"):
        _vk_install_console_handler._handler_ref = handler  # type: ignore[attr-defined]
        ctypes.windll.kernel32.SetConsoleCtrlHandler(handler, 1)


def _vk_clean_stale_entries(our_manifest: Path) -> int:
    """On startup, scan HKCU ImplicitLayers for any value matching our manifest
    path (could be from a previously crashed unicap session). Returns count cleaned."""
    import winreg
    target = str(our_manifest.resolve()).lower()
    cleaned = 0
    try:
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, _VK_LAYER_REGKEY, 0,
                            winreg.KEY_SET_VALUE | winreg.KEY_QUERY_VALUE) as key:
            stale_values = []
            i = 0
            while True:
                try:
                    name, _, _ = winreg.EnumValue(key, i)
                except OSError:
                    break
                if name.lower() == target:
                    stale_values.append(name)
                i += 1
            for name in stale_values:
                try:
                    winreg.DeleteValue(key, name)
                    cleaned += 1
                except OSError:
                    pass
    except FileNotFoundError:
        pass  # ImplicitLayers key doesn't exist yet
    return cleaned


# ── API backend resolution ────────────────────────────────────────────────────

def _resolve_api(api_arg: str, game_exe: Path) -> str:
    """Returns 'dx' or 'vulkan'. 'auto' inspects exe name (vk-suffixed = Vulkan).
    Heuristic is conservative: only flips to vulkan on strong signals; users with
    Vulkan-only games whose exe names lack a 'vk' marker (e.g. DOOMx64.exe) must
    pass --api vulkan explicitly. The fallback DX path then errors out cleanly
    on F6 timeout, prompting the user to retry with --api vulkan."""
    if api_arg in ("dx", "vulkan"):
        return api_arg
    name = game_exe.stem.lower()
    vk_markers = ("vk", "vulkan")
    if any(m in name for m in vk_markers):
        return "vulkan"
    return "dx"


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
    # without affecting BackBufferExport_ColorTex (taken in BackBufferExport's first pass).
    techniques = "DepthToAddon@DepthToAddon.fx,BackBufferExport@BackBufferExport.fx,CaptureStatus@CaptureStatus.fx"
    content = f"Techniques={techniques}\nTechniqueSorting={techniques}\n"
    existing = preset.read_text(encoding="utf-8") if preset.exists() else ""
    # Rewrite if missing CaptureStatus OR if it still references the legacy
    # UIRemove name (renamed → BackBufferExport).
    if "BackBufferExport@BackBufferExport.fx" not in existing:
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
    api = _resolve_api(getattr(args, "api", "auto"), game_exe)

    required = [ADDON_BIN, DXGI_DLL] if api == "dx" else [ADDON_BIN, VULKAN_LAYER_DLL, VULKAN_LAYER_JSON]
    for f in required:
        if not f.exists():
            sys.exit(f"[错误] 文件不存在：{f}\n       请先执行 scripts\\build.ps1")

    if api == "dx":
        dst_dll = game_dir / "dxgi.dll"
        bak = game_dir / "dxgi.dll.bak"
        if dst_dll.exists() and not dst_dll.is_symlink() and not bak.exists():
            shutil.copy2(dst_dll, bak)
        _symlink_file(DXGI_DLL, dst_dll)
        print(f"[DEPLOY] api=dx  → dxgi.dll proxy 部署到 {game_dir}")
    else:
        # Vulkan: drop a 2-line redirect ini into game_dir. ReShade's dll_main
        # reads <game_dir>/unicap.ini's [INSTALL] BasePath as the HIGHEST-priority
        # base-path source (above RESHADE_BASE_PATH_OVERRIDE env var) — so this
        # survives Steam's env-strip on game relaunch. Without this redirect,
        # ReShade aborts the Vulkan layer load when the DLL name doesn't match
        # d3d*/dxgi/opengl32/dinput* (dll_main.cpp:131-156).
        redirect_ini = game_dir / "unicap.ini"
        redirect_ini.write_text(
            f"[INSTALL]\nBasePath={UNICAP_TEMP}\n", encoding="utf-8"
        )
        print(f"[DEPLOY] api=vulkan  → 写入 {redirect_ini}（base path 重定向到 {UNICAP_TEMP}）")

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
    return game_dir, game_exe, game_name, dataset_root, api


# ── Subcommand: launch (interactive) ──────────────────────────────────────────

def cmd_launch(args):
    game_dir, game_exe, game_name, dataset_root, api = cmd_deploy(args)

    print(f"\n[启动] {game_exe}  (api={api})")
    env = {**os.environ, "RESHADE_BASE_PATH_OVERRIDE": str(UNICAP_TEMP)}
    if api == "vulkan":
        # Primary path: HKCU registration. Steam-immune (loader reads registry
        # during vkCreateInstance regardless of parent process). Cleaned up via
        # atexit + signal handlers; stale entries scrubbed on next launch.
        cleaned = _vk_clean_stale_entries(VULKAN_LAYER_JSON)
        if cleaned:
            print(f"[VULKAN] 清理上次未释放的 {cleaned} 条注册表残留")
        _vk_register_layer(VULKAN_LAYER_JSON)
        print(f"[VULKAN] HKCU 注册 layer manifest: {VULKAN_LAYER_JSON.resolve()}")

        # Belt-and-suspenders: env vars also work for non-Steam launches and
        # newer loaders. Cheap to set; fail-safe if HKCU read is delayed.
        layer_dir = str(VULKAN_LAYER_JSON.parent)
        env["VK_IMPLICIT_LAYER_PATH"] = layer_dir
        env["VK_LAYER_PATH"] = layer_dir
        env["VK_INSTANCE_LAYERS"] = VULKAN_LAYER_NAME
        # disable_environment is presence-checked (NOT value-checked) by the
        # Vulkan loader — `="0"` still disables. Remove in case parent inherited.
        env.pop("DISABLE_VK_LAYER_unicap_1", None)
        if getattr(args, "vk_debug", False):
            env["VK_LOADER_DEBUG"] = "layer,error,warn"
            log_file = str(UNICAP_TEMP / "vk_loader.log")
            env["VK_LOADER_LOG_FILE"] = log_file
            print(f"[VULKAN] VK_LOADER_DEBUG enabled → {log_file}")
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
            print("│  F8  开始采集（首次自动 survey；pre-UI + post-UI）    │")
        else:
            print("│  F8  开始采集（首次自动 survey）                      │")
        if ui_mode != "ui":
            print("│  (重做 survey: 删 dataset/<game>/survey/recommended_skip.txt) │")
        print("│  F9  停止当前 survey 或采集                           │")
        print("│  Ctrl+C  退出 main.py（不会关闭游戏）                 │")
        print("└──────────────────────────────────────────────────────┘\n")

    try:
        _interactive_loop(args, game_dir, game_name, dataset_root)
    except KeyboardInterrupt:
        print("\n[退出] Ctrl+C，main.py 退出。游戏继续运行。")
    finally:
        _set_state(game_dir, "idle")
        if api == "vulkan":
            _vk_unregister_layer()
            print("[VULKAN] HKCU 注册表已清理")


def _interactive_loop(args, game_dir: Path, game_name: str, dataset_root: Path):
    ui_mode = getattr(args, "ui_mode", "no-ui")
    needs_survey = ui_mode != "ui"  # ui 模式直接抓 BackBuffer，无需 skip

    while True:
        _set_state(game_dir, "idle")
        suffix = "（首次自动 survey）" if needs_survey else f"（mode={ui_mode}，无需 survey）"
        print(f"[等待] 按 F8 = 采集 {suffix}   F9 = 停止   (Ctrl+C 退出)")
        _wait_for_keys([VK_F8])

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
        # --mask-ui: 额外生成 video_masked.mp4
        if getattr(args, "mask_ui", False):
            _make_video(frames_dir, session_dir / "video_masked.mp4", fps=0,
                        glob_pat="*BackBuffer.bmp", mask_ui=True)
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
                           output_path=session_dir / "dataset.h5",
                           bmp=getattr(args, "bmp", "no-ui"))
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


def _depth_path_for(bmp: Path) -> Path:
    """Sibling depth EXR for a BMP. Filename pattern:
       '<exe> <date> <time> <ms> BackBuffer.bmp'
       '<exe> <date> <time> <ms> DepthBuffer.exr'  (matched on suffix swap)"""
    name = bmp.name
    if name.endswith(" BackBuffer.bmp"):
        return bmp.with_name(name[:-len(" BackBuffer.bmp")] + " DepthBuffer.exr")
    if name.endswith(" BackBufferUI.bmp"):
        return bmp.with_name(name[:-len(" BackBufferUI.bmp")] + " DepthBuffer.exr")
    return bmp.with_suffix(".exr")  # fallback


def _apply_ui_mask_bgr(img_bgr, depth_exr: Path) -> tuple:
    """Mask UI pixels → black. Returns (img, mask_count). -1 = depth missing.

    DepthToAddon.fx exports LINEARIZED depth (0=near, 1=far). Modern engines
    (UE4/UE5/id Tech 7) use reverse-Z so cleared / no-depth-write pixels (UI
    overlays + skybox) end up at 1.0 after linearization. Some forward-Z
    engines might leave UI at 0.0; keep both branches for safety.

    Empirical (DOOM Eternal 2026-05-02 capture): ~5% pixels at d>=0.999, all
    HUD + sky. ~0 pixels at exactly 0.0."""
    import cv2
    if not depth_exr.is_file():
        return img_bgr, -1
    d = cv2.imread(str(depth_exr), cv2.IMREAD_UNCHANGED)
    if d is None:
        return img_bgr, -1
    if d.ndim == 3:
        d = d[:, :, 0]
    if d.shape != img_bgr.shape[:2]:
        return img_bgr, -1  # resolution mismatch — bail rather than corrupt
    ui_mask = (d <= 0.0) | (d >= 0.999)
    img_bgr[ui_mask] = 0
    return img_bgr, int(ui_mask.sum())


def _make_video(frames_dir: Path, output: Path, fps: float = 0,
                glob_pat: str = "*BackBuffer.bmp", mask_ui: bool = False):
    """fps=0 时按文件名时间戳自动估算实际采集 fps，避免快进/慢放。
    mask_ui=True 时读 sibling DepthBuffer.exr，把 depth==0 的 UI 像素置黑后再编码。"""
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
    masked_total = 0
    no_depth = 0

    def _read_frame(bmp_path: Path):
        nonlocal masked_total, no_depth
        img = cv2.imread(str(bmp_path))
        if img is None:
            return None
        if mask_ui:
            img, n = _apply_ui_mask_bgr(img, _depth_path_for(bmp_path))
            if n < 0:
                no_depth += 1
            else:
                masked_total += n
        return img

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
            img = _read_frame(bmp)
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
            img = _read_frame(bmp)
            if img is not None:
                writer.write(img)
            if (i + 1) % progress_step == 0:
                print(f"[VIDEO] {i + 1}/{len(bmps)} 帧", flush=True)
        writer.release()

    if mask_ui:
        avg_px = masked_total / max(len(bmps) - no_depth, 1)
        msg = f"，UI mask 平均 {avg_px:.0f} px/帧"
        if no_depth:
            msg += f"（{no_depth} 帧无 depth EXR，原图保留）"
        print(f"[VIDEO] 完成：{len(bmps)} 帧 @ {fps}fps → {output}{msg}")
    else:
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

    print(f"[VIDEO] 找到 {len(sessions)} 个会话（{game_dir}）"
          + ("  [mask-ui]" if args.mask_ui else ""))
    made = skipped = failed = 0
    t_total = time.perf_counter()
    for sess in sessions:
        frames = sess / "frames"
        # 主流：BackBuffer
        targets = [(sess / "video.mp4", "*BackBuffer.bmp", False)]
        # masked variant: 仅在 --mask-ui 时生成（独立文件，不覆盖 video.mp4）
        if args.mask_ui:
            targets.append((sess / "video_masked.mp4", "*BackBuffer.bmp", True))
        # post-UI 流（both 模式才存在）
        if any(frames.glob("*BackBufferUI.bmp")):
            targets.append((sess / "video_ui.mp4", "*BackBufferUI.bmp", False))

        for out, pat, mask in targets:
            if out.exists():
                print(f"[SKIP] {sess.name}/{out.name}（已存在, {out.stat().st_size/1024/1024:.1f} MB）")
                skipped += 1
                continue
            print(f"\n[VIDEO] {sess.name}/{out.name} ←")
            t0 = time.perf_counter()
            try:
                _make_video(frames, out, args.fps, glob_pat=pat, mask_ui=mask)
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
                           include_depth=args.depth, bmp=args.bmp)
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
    parser = argparse.ArgumentParser()
    parser.add_argument("--version", action="version", version=f"unicap v{VERSION}")
    sub = parser.add_subparsers(dest="cmd", required=True)

    p = sub.add_parser("launch", help="部署 + 启动游戏 + 进入交互式 F6/F8/F9 工作流")
    p.add_argument("--game-path", default=str(GAME_PATH))
    p.add_argument("--game-name", default="", help="游戏名（输出路径第一级，默认从 exe 推导）")
    p.add_argument("--dataset-root", default="", metavar="PATH")
    p.add_argument("--ui-mode", choices=["no-ui", "ui", "both"], default="no-ui",
                   help="输出: no-ui=只 pre-UI（默认）, ui=只 post-UI BB（无需 survey）, both=双流")
    p.add_argument("--api", choices=["auto", "dx", "vulkan"], default="auto",
                   help="渲染后端: auto=按 exe 名启发（默认）, dx=DXGI proxy, vulkan=Vulkan layer")
    p.add_argument("--vk-debug", action="store_true",
                   help="Vulkan: 启用 VK_LOADER_DEBUG=layer，写到 %%TEMP%%\\unicap\\vk_loader.log")
    p.add_argument("--hints", action=argparse.BooleanOptionalAction, default=True,
                   help="显示控制台 + addon overlay 操作提示（默认开启）")
    p.add_argument("--video", action=argparse.BooleanOptionalAction, default=True,
                   help="F9 停止采集后生成 video.mp4（默认开启；--no-video 跳过）")
    p.add_argument("--mask-ui", action="store_true",
                   help="同时生成 video_masked.mp4：depth==0|>=0.999 像素置黑（reverse-Z UI/sky mask）")
    p.add_argument("--pack", action="store_true",
                   help="F9 停止采集后立即打包 HDF5（默认不打包）")
    p.add_argument("--bmp", choices=["no-ui", "ui"], default="no-ui",
                   help="--pack 时哪种 BMP 进 /color: no-ui (默认) = BackBuffer.bmp; "
                        "ui = BackBufferUI.bmp 优先")

    p = sub.add_parser("video", help="批量生成游戏目录下所有缺失的 video.mp4 / video_ui.mp4")
    p.add_argument("--game-dir", default="", metavar="DIR",
                   help="dataset-root 下的游戏目录（其下含 <YYYYMMDD_HHMMSS>/frames/ 子目录）")
    p.add_argument("--fps", type=float, default=0,
                   help="编码 fps；默认 0 = 从 BMP 文件名时间戳自动估算（推荐）")
    p.add_argument("--mask-ui", action="store_true",
                   help="额外生成 video_masked.mp4：用 sibling DepthBuffer.exr 的 depth==0 把 UI 像素置黑（适用于 --ui-mode ui 采集 + UE4/id Tech 引擎）")

    p = sub.add_parser("pack", help="批量打包游戏目录下所有采集会话；已有 dataset.h5 跳过")
    p.add_argument("--game-dir", default="", metavar="DIR",
                   help="dataset-root 下的游戏目录（其下含 <YYYYMMDD_HHMMSS>/frames/ 子目录）")
    p.add_argument("--depth", action=argparse.BooleanOptionalAction, default=True,
                   help="包含 /depth + /normal（默认开启；--no-depth 跳过 EXR、只打 color）")
    p.add_argument("--bmp", choices=["no-ui", "ui"], default="no-ui",
                   help="哪种 BMP 进 /color: no-ui (默认) = BackBuffer.bmp; "
                        "ui = BackBufferUI.bmp（不存在则 fallback BackBuffer.bmp）")
    p.add_argument("--spot-check", metavar="H5_PATH")
    p.add_argument("--check-frames", default="0,99,499")
    p.add_argument("--check-out", default=str(DATASET_ROOT / "spot_checks"))

    args = parser.parse_args()
    print(f"unicap v{VERSION}", flush=True)
    {"launch": cmd_launch, "video": cmd_video, "pack": cmd_pack}[args.cmd](args)


if __name__ == "__main__":
    main()
