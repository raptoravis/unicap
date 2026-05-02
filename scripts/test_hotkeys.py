"""F6-F12 hotkey diagnostic — does GetAsyncKeyState see your function keys?

跑 30s，按下 F6-F12 任何键都打印检测时间。用法：

    uv run python scripts/test_hotkeys.py

如果按 F8 / F9 后看不到输出 — **不是 unicap 的问题**。可能原因：
  1. 笔记本 Fn-Lock 在 media 模式（Fn+F8 = 音量 / 等），需要按 Fn+F8 或切换 Fn-Lock
  2. 另一个程序（杀软 / 录屏 / 输入法）拦截了 F-key
  3. 键盘 macro 软件占用

如果其他 F 键都响应、唯独 F8 / F9 不响应 — 可能是某个 app 全局 hook 了 F8 / F9。
任务管理器看看哪个进程在跑（Logitech G Hub / SteelSeries Engine 等）。
"""

from __future__ import annotations

import ctypes
import time

VK_NAMES = {
    0x75: "F6", 0x76: "F7", 0x77: "F8", 0x78: "F9", 0x79: "F10",
    0x7A: "F11", 0x7B: "F12",
}

_user32 = ctypes.WinDLL("user32")


def main() -> None:
    print("=" * 60)
    print("F6-F12 hotkey 检测 (30s) — 按你想测的键，看是否打印")
    print("=" * 60)
    pressed_recently: dict[int, float] = {}
    deadline = time.monotonic() + 30.0
    detected: set[int] = set()
    while time.monotonic() < deadline:
        now = time.monotonic()
        for vk, name in VK_NAMES.items():
            is_down = bool(_user32.GetAsyncKeyState(vk) & 0x8000)
            last = pressed_recently.get(vk, 0.0)
            if is_down and now - last > 0.3:  # debounce
                print(f"  [{now - (deadline - 30):5.1f}s] {name} (vk=0x{vk:02X}) DOWN")
                pressed_recently[vk] = now
                detected.add(vk)
        time.sleep(0.05)
    print("=" * 60)
    if not detected:
        print("⚠️  整 30s 一个 F 键都没检测到 — 极大概率是 Fn-Lock 在 media 模式")
        print("   建议：找键盘上的 Fn-Lock 切换键，或试试按 Fn+F8 看 unicap 是否响应")
    else:
        names = sorted(VK_NAMES[v] for v in detected)
        print(f"✓ 检测到: {names}")
        missing = {0x77, 0x78} - detected
        if missing:
            mn = sorted(VK_NAMES[v] for v in missing)
            print(f"⚠️  没检测到: {mn} — 可能被全局 hook 拦截（看任务管理器有无键盘 macro 软件）")
        else:
            print("✓ F8 / F9 工作正常 — 如果 unicap 仍不响应，告诉我，我加 main.py 心跳诊断")


if __name__ == "__main__":
    main()
