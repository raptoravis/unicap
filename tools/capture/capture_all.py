"""
FF7 Remake 采集管线 — 一键启动
同时运行：输入录制（120Hz）+ 自动帧捕获（F10）+ 文件搬运（Win64 → frames/）

用法：
  python capture_all.py              # 30fps，Ctrl+C 停止
  python capture_all.py 30           # 指定 fps
  python capture_all.py 30 60        # 30fps，60 秒后自动停止

输出：
  D:/ff7_dataset/inputs.jsonl
  D:/ff7_dataset/frames/
"""

import ctypes
import json
import shutil
import sys
import threading
import time
from pathlib import Path
from .config import GAME_WIN64, FRAMES_DIR, INPUTS_OUT

# ── 路径配置 ──────────────────────────────────────────────────────────────────
WATCH_DIR  = GAME_WIN64
EXTS       = {".bmp", ".exr"}
POLL_S     = 0.1

# ── Windows API ───────────────────────────────────────────────────────────────
VK_F10            = 0x79
KEYEVENTF_KEYDOWN = 0x0000
KEYEVENTF_KEYUP   = 0x0002

user32 = ctypes.WinDLL("user32")

xinput = None
for lib in ("xinput1_4", "xinput9_1_0"):
    try:
        xinput = ctypes.WinDLL(lib)
        break
    except OSError:
        pass
if xinput is None:
    print("[WARN] XInput 未找到，手柄禁用")

# ── 结构体 ────────────────────────────────────────────────────────────────────
class POINT(ctypes.Structure):
    _fields_ = [("x", ctypes.c_long), ("y", ctypes.c_long)]

class XINPUT_GAMEPAD(ctypes.Structure):
    _fields_ = [
        ("wButtons",      ctypes.c_ushort),
        ("bLeftTrigger",  ctypes.c_ubyte),
        ("bRightTrigger", ctypes.c_ubyte),
        ("sThumbLX",      ctypes.c_short),
        ("sThumbLY",      ctypes.c_short),
        ("sThumbRX",      ctypes.c_short),
        ("sThumbRY",      ctypes.c_short),
    ]

class XINPUT_STATE(ctypes.Structure):
    _fields_ = [("dwPacketNumber", ctypes.c_ulong), ("Gamepad", XINPUT_GAMEPAD)]

def _parse_xinput(state):
    g = state.Gamepad
    return {
        "buttons": g.wButtons,
        "lt": g.bLeftTrigger  / 255.0,
        "rt": g.bRightTrigger / 255.0,
        "lx": g.sThumbLX  / 32767.0,
        "ly": g.sThumbLY  / 32767.0,
        "rx": g.sThumbRX  / 32767.0,
        "ry": g.sThumbRY  / 32767.0,
    }

# ── 线程：输入录制 ─────────────────────────────────────────────────────────────
def _thread_input(stop: threading.Event):
    INPUTS_OUT.parent.mkdir(parents=True, exist_ok=True)
    log = []
    t_start = time.time_ns()

    while not stop.is_set():
        t = time.time_ns()
        kb = (ctypes.c_ubyte * 256)()
        user32.GetKeyboardState(kb)
        pt = POINT()
        user32.GetCursorPos(ctypes.byref(pt))
        gamepad = None
        if xinput:
            state = XINPUT_STATE()
            if xinput.XInputGetState(0, ctypes.byref(state)) == 0:
                gamepad = _parse_xinput(state)
        log.append({"ts": t, "kb": list(kb), "mouse": [pt.x, pt.y], "gamepad": gamepad})
        stop.wait(1 / 120)

    elapsed = (time.time_ns() - t_start) / 1e9
    with open(INPUTS_OUT, "w", encoding="utf-8") as f:
        for entry in log:
            f.write(json.dumps(entry) + "\n")
    count = len(log)
    print(f"[INPUT ] 完成：{count} 条，{elapsed:.1f}s，{count/elapsed:.1f} Hz → {INPUTS_OUT}")

# ── 线程：自动帧捕获 ───────────────────────────────────────────────────────────
def _thread_capture(stop: threading.Event, fps: int, duration):
    interval = 1.0 / fps
    count = 0
    t_start = time.perf_counter()

    while not stop.is_set():
        t0 = time.perf_counter()
        user32.keybd_event(VK_F10, 0, KEYEVENTF_KEYDOWN, 0)
        time.sleep(0.02)
        user32.keybd_event(VK_F10, 0, KEYEVENTF_KEYUP, 0)
        count += 1

        elapsed = time.perf_counter() - t_start
        if count % max(fps, 1) == 0:
            print(f"[CAPTURE] {elapsed:6.1f}s / {count} 帧", flush=True)

        if duration and elapsed >= duration:
            stop.set()
            break

        sleep_time = interval - (time.perf_counter() - t0)
        if sleep_time > 0:
            stop.wait(sleep_time)

    elapsed = time.perf_counter() - t_start
    print(f"[CAPTURE] 完成：{count} 帧，{elapsed:.1f}s，{count/elapsed:.1f} fps")

# ── 线程：文件搬运 ─────────────────────────────────────────────────────────────
def _thread_watcher(stop: threading.Event):
    FRAMES_DIR.mkdir(parents=True, exist_ok=True)
    seen = set(WATCH_DIR.glob("*"))
    moved = 0

    while not stop.is_set():
        try:
            for f in WATCH_DIR.iterdir():
                if f in seen or f.suffix.lower() not in EXTS:
                    continue
                try:
                    s1 = f.stat().st_size
                    time.sleep(0.05)
                    if f.stat().st_size != s1:
                        continue  # 还在写，下次再处理
                    shutil.move(str(f), str(FRAMES_DIR / f.name))
                    seen.add(f)  # 仅在移动成功后加入，保证写中文件下轮重试
                    moved += 1
                    print(f"[WATCHER] {moved:4d} → {f.name}", flush=True)
                except Exception:
                    pass
        except Exception:
            pass
        stop.wait(POLL_S)

    print(f"[WATCHER] 完成：共移动 {moved} 个文件 → {FRAMES_DIR}")

# ── 主入口 ────────────────────────────────────────────────────────────────────
def run(fps: int = 30, duration=None):
    print(f"[START] fps={fps}  时长={'∞' if not duration else f'{duration}s'}")
    print(f"        帧 → {FRAMES_DIR}")
    print(f"        输入 → {INPUTS_OUT}")
    print("        Ctrl+C 随时停止\n")

    stop = threading.Event()
    threads = [
        threading.Thread(target=_thread_input,   args=(stop,),               name="input",   daemon=True),
        threading.Thread(target=_thread_capture, args=(stop, fps, duration),  name="capture", daemon=True),
        threading.Thread(target=_thread_watcher, args=(stop,),               name="watcher", daemon=True),
    ]
    for t in threads:
        t.start()

    try:
        while not stop.is_set():
            stop.wait(1)
    except KeyboardInterrupt:
        print("\n[STOP] Ctrl+C，正在停止...")
        stop.set()

    for t in threads:
        t.join(timeout=10)
    print("[DONE]")

def main():
    fps      = int(sys.argv[1])   if len(sys.argv) > 1 else 30
    duration = float(sys.argv[2]) if len(sys.argv) > 2 else None
    run(fps, duration)

if __name__ == "__main__":
    main()
