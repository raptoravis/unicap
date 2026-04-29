# Handoff: unicap — FF7 Remake 深度采集流水线整合

**Generated**: 2026-04-29
**Branch**: master
**Status**: In Progress — 工具链整合完成，待测试验证

---

## Goal

将 FF7 Remake 视频深度输入采集流水线所需的全部工具（ReShade 定制构建 + Python 采集脚本）
统一纳入 `D:\dev\unicap.git\`（项目名 unicap），以 `main.py` 为唯一入口，支持官方/自定义
两种 ReShade 模式切换，最终实现一键拉起录制。

---

## Completed

- [x] Python 采集脚本从 `D:\ff7_tools\` 迁移到 `tools/capture/`，路径集中到 `config.py`
- [x] `vendor/` 目录存放官方 ReShade 二进制（592/673 + 官方 addon + 安装包）
- [x] `main.py` 统一入口，子命令：`deploy` / `launch` / `capture` / `pack`
- [x] 删除冗余独立脚本（auto_capture, file_watcher, record_inputs 已内联进 capture_all.py）
- [x] 删除 `scripts/deploy.ps1` 和 `scripts/launch.ps1`（功能移入 main.py）
- [x] `capture_all.py` 新增 `run(fps, duration)` 函数供 main.py 调用
- [x] Python 项目初始化（uv + pyproject.toml，name=unicap，Python 3.13）
- [x] C++ 自定义构建（前序 session 完成）：`dist/dxgi.dll` + `dist/frame_capture.addon` 已生成

---

## Not Yet Done

- [ ] **测试 official592 模式**：`python main.py launch --mode official592`，验证 Python 管线与官方 5.9.2 正常配合
- [ ] **测试 custom 模式**：`python main.py launch`，验证自定义构建产物功能与官方版一致
- [ ] **pack 验证**：采集完后跑 `python main.py pack --spot-check`，确认深度/法线对齐
- [ ] **后续定制**（可选）：修改 `reshade-addons/99-frame_capture/frame_capture.cpp`，内置 HTTP 控制替代 F10 键盘模拟
- [ ] 提交当前未 commit 的改动（见下方 Uncommitted Changes）

---

## Failed Approaches (Don't Repeat These)

### Write tool 写中文注释产生乱码

尝试在 `main.py` 的 section 分隔注释行（`# ── ... ──`）中写中文，Write tool 将部分字符替换为 `�`。
**修复**：section 注释改为纯 ASCII，中文仅出现在字符串字面量（argparse help 文本等）中。

### deploy.ps1 / launch.ps1 单独维护成本高

两个 PowerShell 脚本与 Python 脚本分开维护，路径配置重复出现在多处。
**修复**：全部合并到 `main.py`，PowerShell 脚本删除。

_C++ 构建阶段的 Failed Approaches 见上一份 HANDOFF.md（2026-04-29 首版，git log 中 `186c47c`）。_

---

## Key Decisions

| 决策                           | 理由                                                            |
| ------------------------------ | --------------------------------------------------------------- |
| `main.py` 统一入口替代多个 ps1 | 跨工具链统一路径配置，Python 在 Windows 比 ps1 更可移植         |
| vendor 二进制 gitignore        | DLL/exe 不入库；本地 `vendor/` 作为 staging area                |
| capture_all 内联三线程         | 三个独立脚本功能完全重叠，运行时始终一起启动                    |
| uv + pyproject.toml            | Python 3.13 环境隔离，依赖可重现（cv2/h5py/numpy 供 pack_hdf5） |
| 项目名 unicap                  | 更简洁的名称，已同步更新 CMakeLists.txt 和 pyproject.toml       |

---

## Current State

**Working**：

- `python main.py --help` 正常
- `dist/dxgi.dll` + `dist/frame_capture.addon` 已构建（上一 session）
- `vendor/reshade592/`、`vendor/reshade673/`、`vendor/addon_official/` 二进制就位

**Broken**：无已知问题

**Uncommitted Changes**：

- `CMakeLists.txt`：project 名改为 `unicap`
- `tools/capture/config.py`：注释文字改为 unicap
- `main.py`：docstring 改为 "unicap main controller"
- `HANDOFF.md`：本文件
- 新增未跟踪：`.python-version`（3.13）、`pyproject.toml`、`uv.lock`

---

## Files to Know

| 文件                           | 说明                                                          |
| ------------------------------ | ------------------------------------------------------------- |
| `main.py`                      | **唯一入口**：deploy / launch / capture / pack 四个子命令     |
| `tools/capture/config.py`      | 所有路径常量（游戏目录、数据集目录、仓库根）—— 换机器只改这里 |
| `tools/capture/capture_all.py` | 采集管线：三线程（输入录制 120Hz + F10 帧触发 + 文件搬运）    |
| `tools/capture/pack_hdf5.py`   | 离线打包：frames/ + inputs.jsonl → dataset.h5                 |
| `scripts/build.ps1`            | CMake configure + MSBuild（自定义构建用）                     |
| `scripts/setup.ps1`            | 首次初始化 git submodule deps（含精确 commit 兜底）           |
| `dist/`                        | 自定义构建产物（gitignore，本地存在）                         |
| `vendor/`                      | 官方二进制 staging（gitignore，本地存在）                     |

---

## Code Context

### main.py 子命令接口

```python
# deploy: 部署 DLL + addon 到游戏目录
python main.py deploy --mode custom|official592|official673 [--game-dir PATH]

# launch: deploy + 启动 capture（最常用）
python main.py launch [--mode custom] [--fps 30] [--duration 0] [--deploy-only]

# capture: 只启动采集，不部署
python main.py capture --fps 30 --duration 60

# pack: 打包 HDF5
python main.py pack [--frames-dir ...] [--inputs ...] [--output ...]
python main.py pack --spot-check D:/ff7_dataset/dataset.h5
```

### capture_all.run() 签名

```python
# 供 main.py 调用；也可直接 python capture_all.py [fps] [duration]
def run(fps: int = 30, duration=None): ...
```

### config.py 路径常量

```python
GAME_WIN64   = Path(r"E:\games\ff7remake\End\Binaries\Win64")
DATASET_ROOT = Path(r"D:\ff7_dataset")
FRAMES_DIR   = DATASET_ROOT / "frames"
INPUTS_OUT   = DATASET_ROOT / "inputs.jsonl"
HDF5_OUT     = DATASET_ROOT / "dataset.h5"
REPO_ROOT    = Path(__file__).parents[2]   # D:\dev\unicap.git
DIST_DIR     = REPO_ROOT / "dist"
VENDOR_DIR   = REPO_ROOT / "vendor"
```

### vendor 目录布局

```
vendor/
  reshade592/dxgi.dll          <- 官方 5.9.2（用于测试）
  reshade673/dxgi.dll          <- 官方 6.7.3（EXR 导出已断，仅备用）
  reshade673/backup.dll        <- 之前部署的 6.7.3 备份
  addon_official/frame_capture.addon
  installers/ReShade_Setup_5.9.2_Addon.exe
  installers/ReShade_Setup_6.7.3_Addon.exe
```

---

## Resume Instructions

### 1. 提交未 commit 的改动

```bash
cd D:\dev\unicap.git
git add CMakeLists.txt main.py tools/capture/config.py HANDOFF.md pyproject.toml .python-version uv.lock
git commit -m "Rename project to unicap; add uv Python project setup"
```

### 2. 测试官方 5.9.2 模式（先跑这个，验证 Python 管线无误）

```bash
# 部署官方 5.9.2 到游戏目录
python main.py deploy --mode official592

# 启动游戏，进入场景后：
python main.py capture --fps 30 --duration 10

# 预期输出：
# [CAPTURE] 完成：~300 帧
# [INPUT  ] 完成：~1200 条
# [WATCHER] 共移动 ~300 个文件 → D:\ff7_dataset\frames\

# 打包验证
python main.py pack --spot-check D:/ff7_dataset/dataset.h5
# 预期：spot_checks/ 目录下 PNG 图片，深度叠加色彩合理，dt < 10 ms
```

如果采集时帧文件没有被移动：检查 `config.py` 中 `GAME_WIN64` 路径是否与实际游戏安装路径一致。

### 3. 测试自定义构建（官方验证通过后）

```bash
python main.py launch  # 等价于 deploy --mode custom + capture
```

预期行为与官方版相同。如果 addon 未触发，检查游戏内 ReShade overlay 是否启用了 frame_capture.addon。

### 4. 重新构建自定义版本（修改 addon 代码后）

```powershell
# 只重编 addon
cmake --build D:\dev\unicap.git\build --config Release --target frame_capture

# 重新部署
python main.py deploy
```

---

## Warnings

- **ReShade 6.7.3 的 EXR 导出已断**：`vendor/reshade673/dxgi.dll` 只能产生 BMP，不产生深度/法线 EXR。只用 5.9.2 或自定义构建。
- **vendor/ 中的 DLL 是 gitignore 的**：换机器需重新从 `D:\ff7_tools\` 手动复制，或重新安装官方 ReShade。
- **pack_hdf5 依赖 cv2/h5py/numpy**：首次运行前需安装：`uv add opencv-python h5py numpy`（或 pip install）。
- **frame_capture addon 触发键**：默认 F10（`capture_all.py` 的 `VK_F10 = 0x79`）。若游戏内 ReShade 改了按键需同步修改。
- **C++ 构建相关警告**见原始 HANDOFF（commit `186c47c`）。
