"""
FF7 Remake 自动连续帧捕获脚本
原理：以固定间隔向游戏窗口发送 F10 键，触发 Frame Capture Addon

用法：
  python auto_capture.py            # 默认 30fps（约 33ms 间隔）
  python auto_capture.py 60         # 60fps
  python auto_capture.py 30 10      # 30fps，录 10 秒后自动停止

注意：
  - 运行前先在游戏内 Frame Capture Settings 勾选三个开关
  - 先按 ~ 输入 showflag.hud 0 隐藏 HUD
  - 本脚本在后台发送按键，不需要游戏窗口在前台
  - 按 Ctrl+C 停止
"""

import ctypes
import time
import sys

KEYEVENTF_KEYDOWN = 0x0000
KEYEVENTF_KEYUP   = 0x0002
VK_F10 = 0x79

user32 = ctypes.WinDLL("user32")

def press_f10():
    user32.keybd_event(VK_F10, 0, KEYEVENTF_KEYDOWN, 0)
    time.sleep(0.02)
    user32.keybd_event(VK_F10, 0, KEYEVENTF_KEYUP, 0)

def main():
    fps      = int(sys.argv[1]) if len(sys.argv) > 1 else 30
    duration = float(sys.argv[2]) if len(sys.argv) > 2 else None
    interval = 1.0 / fps

    print(f"[AUTO-CAPTURE] {fps} fps，间隔 {interval*1000:.1f}ms")
    if duration:
        print(f"[AUTO-CAPTURE] 将在 {duration}s 后自动停止")
    print("[AUTO-CAPTURE] 按 Ctrl+C 停止")
    print()

    count = 0
    t_start = time.perf_counter()

    try:
        while True:
            t0 = time.perf_counter()

            press_f10()
            count += 1

            elapsed = time.perf_counter() - t_start
            if count % fps == 0:
                print(f"\r[{elapsed:7.1f}s] 已捕获 {count} 帧", end="", flush=True)

            if duration and elapsed >= duration:
                break

            # 精确等待到下一帧
            sleep_time = interval - (time.perf_counter() - t0)
            if sleep_time > 0:
                time.sleep(sleep_time)

    except KeyboardInterrupt:
        pass

    elapsed = time.perf_counter() - t_start
    print(f"\n[DONE] 共捕获 {count} 帧，用时 {elapsed:.1f}s，实际 {count/elapsed:.1f} fps")

if __name__ == "__main__":
    main()
