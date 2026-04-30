"""
FF7 Remake 采集管线 — 一键启动
同时运行：输入录制（120Hz）+ 进度监控
addon 通过 FC_TargetFPS 自动定时采集，通过 fc_output_dir.txt 直接将帧写入目标 frames_dir。

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
import sys
import threading
import time
from pathlib import Path
from .config import GAME_WIN64, FRAMES_DIR, INPUTS_OUT

# ── Windows API ───────────────────────────────────────────────────────────────
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
def _thread_input(stop: threading.Event, inputs_out: Path):
    inputs_out.parent.mkdir(parents=True, exist_ok=True)
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
    with open(inputs_out, "w", encoding="utf-8") as f:
        for entry in log:
            f.write(json.dumps(entry) + "\n")
    count = len(log)
    print(f"[INPUT ] 完成：{count} 条，{elapsed:.1f}s，{count/elapsed:.1f} Hz → {inputs_out}")

# ── 主入口 ────────────────────────────────────────────────────────────────────
def run(fps: int = 30, duration=None, frames_dir: Path = None, inputs_out: Path = None, watch_dir: Path = None):
    frames_dir = frames_dir or FRAMES_DIR
    inputs_out = inputs_out or INPUTS_OUT
    watch_dir  = watch_dir  or GAME_WIN64

    frames_dir.mkdir(parents=True, exist_ok=True)

    # 告知 addon 直接写入 frames_dir，省去 monitor+move
    sidecar = watch_dir / "fc_output_dir.txt"
    sidecar.write_text(str(frames_dir), encoding="utf-8")

    print(f"[采集] fps={fps}  时长={'∞' if not duration else f'{duration}s'}")
    print(f"       帧 → {frames_dir}")
    print(f"       输入 → {inputs_out}")
    print("       Ctrl+C 随时停止\n")

    stop = threading.Event()
    t_input = threading.Thread(target=_thread_input, args=(stop, inputs_out), name="input", daemon=True)
    t_input.start()

    t_start = time.perf_counter()
    last_count = 0
    last_print = t_start

    try:
        while not stop.is_set():
            stop.wait(1)
            elapsed = time.perf_counter() - t_start
            if duration and elapsed >= duration:
                stop.set()
                break
            now = time.perf_counter()
            if now - last_print >= 1.4:
                count = sum(1 for _ in frames_dir.glob("*BackBuffer.bmp"))
                if count != last_count:
                    print(f"[CAPTURE] {elapsed:6.1f}s / {count} 帧", flush=True)
                    last_count = count
                    last_print = now
    except KeyboardInterrupt:
        print("\n[STOP] Ctrl+C，正在停止...")
        stop.set()

    elapsed = time.perf_counter() - t_start
    frame_count = sum(1 for _ in frames_dir.glob("*BackBuffer.bmp"))
    fps_actual = frame_count / elapsed if elapsed > 0 else 0
    print(f"[CAPTURE] 完成：{frame_count} 帧，{elapsed:.1f}s，{fps_actual:.1f} fps")

    t_input.join(timeout=10)

    sidecar.unlink(missing_ok=True)
    print("[DONE]")

def main():
    fps      = int(sys.argv[1])   if len(sys.argv) > 1 else 30
    duration = float(sys.argv[2]) if len(sys.argv) > 2 else None
    run(fps, duration)

if __name__ == "__main__":
    main()
