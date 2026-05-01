"""
FF7 Remake 采集管线 — 集中路径配置
修改此文件以适配不同机器/路径。
"""

from pathlib import Path

# ── 游戏路径 ──────────────────────────────────────────────────────────────────
GAME_PATH = Path(r"E:\games\ff7remake\End\Binaries\Win64\ff7remake_.exe")
GAME_WIN64 = GAME_PATH.parent  # 兼容 capture_all.py 使用
GAME_EXE = GAME_PATH  # 兼容旧引用

# ── 数据集输出路径 ─────────────────────────────────────────────────────────────
DATASET_ROOT = Path(r"D:\unicap_output")
FRAMES_DIR = DATASET_ROOT / "frames"
INPUTS_OUT = DATASET_ROOT / "inputs.jsonl"
HDF5_OUT = DATASET_ROOT / "dataset.h5"
