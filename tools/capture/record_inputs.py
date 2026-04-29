"""
FF7 Remake 输入录制脚本 — 120Hz 采样
输出：D:/ff7_dataset/inputs.jsonl
按 Ctrl+C 停止录制
"""

import ctypes
import time
import json
import signal
import sys
from pathlib import Path

# --- 结构体定义 ---

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
    _fields_ = [
        ("dwPacketNumber", ctypes.c_ulong),
        ("Gamepad",        XINPUT_GAMEPAD),
    ]

# --- Windows API ---

user32  = ctypes.WinDLL("user32")
xinput  = None
try:
    xinput = ctypes.WinDLL("xinput1_4")
except OSError:
    try:
        xinput = ctypes.WinDLL("xinput9_1_0")
    except OSError:
        print("[WARN] XInput not found, gamepad disabled")

# --- 解析手柄 ---

def parse_xinput(state):
    g = state.Gamepad
    return {
        "buttons":  g.wButtons,
        "lt":       g.bLeftTrigger  / 255.0,
        "rt":       g.bRightTrigger / 255.0,
        "lx":       g.sThumbLX  / 32767.0,
        "ly":       g.sThumbLY  / 32767.0,
        "rx":       g.sThumbRX  / 32767.0,
        "ry":       g.sThumbRY  / 32767.0,
    }

# --- 主循环 ---

OUTPUT = Path("D:/ff7_dataset/inputs.jsonl")
OUTPUT.parent.mkdir(parents=True, exist_ok=True)

recording = True
log = []

def stop(sig, frame):
    global recording
    recording = False

signal.signal(signal.SIGINT, stop)

print(f"[START] 录制输入至 {OUTPUT}，按 Ctrl+C 停止")
t_start = time.time_ns()
count = 0

while recording:
    t = time.time_ns()

    # 键盘
    kb = (ctypes.c_ubyte * 256)()
    user32.GetKeyboardState(kb)

    # 鼠标
    pt = POINT()
    user32.GetCursorPos(ctypes.byref(pt))

    # 手柄
    gamepad = None
    if xinput:
        state = XINPUT_STATE()
        ret = xinput.XInputGetState(0, ctypes.byref(state))
        if ret == 0:
            gamepad = parse_xinput(state)

    entry = {
        "ts":      t,
        "kb":      list(kb),
        "mouse":   [pt.x, pt.y],
        "gamepad": gamepad,
    }
    log.append(entry)
    count += 1

    time.sleep(1 / 120)

# --- 写出 ---
elapsed = (time.time_ns() - t_start) / 1e9
with open(OUTPUT, "w", encoding="utf-8") as f:
    for entry in log:
        f.write(json.dumps(entry) + "\n")

print(f"[DONE] {count} 条记录，{elapsed:.1f}s，平均 {count/elapsed:.1f} Hz")
print(f"[DONE] 已写出 {OUTPUT}  ({OUTPUT.stat().st_size // 1024} KB)")
