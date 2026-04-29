"""
文件监视脚本：将 Win64 目录新产生的 bmp/exr 实时移动到输出目录
与 auto_capture.py 和 record_inputs.py 同时运行

用法：python file_watcher.py
按 Ctrl+C 停止
"""

import time
import shutil
import sys
from pathlib import Path
from config import GAME_WIN64, FRAMES_DIR

WATCH_DIR  = GAME_WIN64
OUTPUT_DIR = FRAMES_DIR
EXTS       = {".bmp", ".exr"}
POLL_MS    = 0.1  # 100ms 轮询

OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

seen = set(WATCH_DIR.glob("*"))  # 启动时已有的文件，跳过

print(f"[WATCHER] 监视: {WATCH_DIR}")
print(f"[WATCHER] 输出: {OUTPUT_DIR}")
print(f"[WATCHER] 按 Ctrl+C 停止\n")

moved = 0
try:
    while True:
        for f in WATCH_DIR.iterdir():
            if f in seen or f.suffix.lower() not in EXTS:
                continue
            seen.add(f)
            # 等文件写完（大小稳定）
            try:
                s1 = f.stat().st_size
                time.sleep(0.05)
                s2 = f.stat().st_size
                if s1 != s2:
                    continue  # 还在写，下次再处理
                dest = OUTPUT_DIR / f.name
                shutil.move(str(f), str(dest))
                moved += 1
                print(f"[{moved:4d}] -> {f.name}")
            except Exception as e:
                pass  # 文件被占用，下次重试
        time.sleep(POLL_MS)

except KeyboardInterrupt:
    print(f"\n[WATCHER] 已停止，共移动 {moved} 个文件")
