# Handoff: FF7 Remake 逐帧数据采集——待正式大规模采集

**Generated**: 2026-04-28
**Branch**: master
**Status**: In Progress — 工具链完整，UI 遮罩已实现，待正式大规模 triplet 采集

---

## Goal

为研究目的，从 Final Fantasy VII Remake Intergrade（单机）逐帧同步采集游戏画面（RGB BMP）、深度缓冲（float32 EXR）、输入状态（键盘/鼠标/手柄 JSONL），输出为对齐的 HDF5 数据集，供 AI/ML 研究使用。

---

## Completed

- [x] 调研并确认方案：ReShade + FrameCapture Addon（见 `docs/ff7remake-game-capture-research.md`）
- [x] 部署 ReShade **5.9.2** Addon 版（dxgi.dll）到游戏 Win64 目录
- [x] 部署 frame_capture.addon v1.0.0.1 + DepthToAddon.fx shader
- [x] 在游戏内配置三个必须勾选的开关
- [x] 验证 F10 触发后产生 BackBuffer.bmp + DepthBuffer.exr + NormalMap.exr
- [x] 验证 EXR 可用 cv2 读取：shape=(1440,2560,3) float32，值域 0.02–0.07
- [x] 编写并验证输入录制脚本（114.5 Hz，324829 条/2836s）
- [x] 编写自动帧捕获脚本（定时发 F10，支持 fps + 时长参数）
- [x] 编写文件搬运脚本（Win64 目录 → D:\ff7_dataset\frames\）
- [x] 安装 Python 依赖：h5py 3.16 / numpy 2.4.4 / cv2 4.13 / imageio 2.37
- [x] 输出操作手册：`D:\ff7_dataset\CAPTURE_GUIDE.md`
- [x] 实现 `D:\ff7_tools\pack_hdf5.py`（时区对齐、bisect 对齐、triplet/color-only 模式、spot-check）
- [x] 用 3 帧测试数据验证 HDF5 结构正确，生成 `D:\ff7_dataset\dataset.h5`（16.1 MB）
- [x] 目视验证 spot_checks/spot_00000.png（Cloud 车站场景，画面清晰，标签正确）
- [x] **合并三脚本为 `D:\ff7_tools\capture_all.py`**（本次会话新增）
  - 三线程并行：输入录制 + F10 帧捕获 + 文件搬运
  - 共享 `threading.Event` 协调停止；`stop.wait()` 替代 `time.sleep()`，Ctrl+C 干净退出
  - 时长到期时自动停止全部线程
- [x] **实现 UI 遮罩双方案**（本次会话新增）
  - 方案 B：`reshade-shaders/Shaders/UIRemove.fx`，实时遮盖 depth==0 像素（UE4 Reverse-Z）
  - 方案 A：`pack_hdf5.py` 打包时兜底，B 生效时为 no-op，B 未开时自动置黑
  - 日志和 HDF5 属性（`ui_mask_avg_px`）显示哪个方案在起作用

---

## Not Yet Done

- [ ] **在 ReShade 里启用 UIRemove 技术**（首次需要手动勾选）
- [ ] **正式大规模采集**：`python D:\ff7_tools\capture_all.py 30 120`，产生含深度的 triplet 数据
- [ ] 用大规模数据重新打包 HDF5（triplet 模式，含 depth/normal 数据集）
- [ ] 抽取第 1、100、500 帧目视确认三路对齐（depth+color 叠加）
- [ ] 用 RenderDoc 方案捕获同一场景，与 EXR 深度精度对比（可选）
- [ ] 磁盘吞吐优化（float16 EXR，异步写入）（可选）
- [ ] 自动化大规模采集（场景切换 + 自动录制）（可选）

---

## Failed Approaches (Don't Repeat These)

### 1. ReShade 6.7.3 + frame_capture.addon
**现象**：addon 面板正常，按 F10 只产生 BMP，完全没有 EXR。  
**根因**：addon EXR 写入依赖 `reshade::api` 5.x 接口，6.x 接口变更导致 EXR 路径静默失败。  
**结论**：必须用 ReShade 5.9.2；备份在 `D:\ff7_tools\dxgi_reshade6.7.3_backup.dll`。

### 2. 不勾选 Frame Capture Settings 三个开关就按 F10
**现象**：F10 触发 ReShade 内置截图（PNG/BMP），不是 addon 逻辑。  
**根因**：addon 源码 `enableCapturing` 默认 false，Settings 折叠不可见。  
**结论**：必须展开 Settings 手动勾选三项。

### 3. frame_capture.addon 放在 `Win64/addons/` 子目录
**现象**：插件标签页无 Frame Capture 条目。  
**根因**：ReShade 插件搜索路径默认 `.\`，不递归子目录。  
**结论**：.addon 必须与 dxgi.dll 同级在 Win64 根目录。

### 4. 未部署 DepthToAddon.fx shader
**现象**：addon 加载但只产生 BMP，无 EXR。  
**根因**：addon 通过 `DepthToAddon_ExportTex` 纹理变量获取深度；没有这个 shader 则 `export_texture_r == 0`，EXR 跳过。  
**结论**：必须同时部署 DepthToAddon.fx 并在主页启用。

### 5. cv2.imread 读 EXR 未设环境变量
**现象**：`cv2.error: OpenEXR codec is disabled`  
**结论**：读/写 EXR 前必须 `os.environ['OPENCV_IO_ENABLE_OPENEXR'] = '1'`（pack_hdf5.py 已在 import cv2 之前设置）。

### 6. 用 UE4 Console 命令 `showflag.hud 0` 隐藏 UI
**局限**：不持久化（每次新会话需重新输入），依赖引擎 Console 功能。  
**替换方案**：  
- 方案 B（优先）：`UIRemove.fx` 在 ReShade 层实时遮盖，不依赖引擎  
- 方案 A（兜底）：`pack_hdf5.py` 打包时用 depth==0 遮罩

---

## Key Decisions

| 决策 | 理由 |
|------|------|
| ReShade **5.9.2**（非 6.x） | 6.x EXR 写入 API 已断，5.9.2 是经验证可用版本 |
| frame_capture.addon 放 Win64 根目录 | ReShade 插件搜索路径为 `.\`，子目录不扫描 |
| EXR 输出到 Win64 目录再搬运 | addon 硬编码写到 exe 所在目录，用 file_watcher 转移 |
| 时区用 `datetime.timezone(timedelta(hours=8))` 显式处理 | 不依赖系统 tz 设置，换机器不出错 |
| HDF5 chunk=(1, H, W, C) for images | 支持帧级随机访问，gzip-4 压缩 |
| 支持两种文件名格式 A/B | 实测发现文件名格式与早期记录不同（无 BackBuffer 后缀），自动检测 |
| UI 遮罩：depth==0 阈值 0.001 | FF7R 真实几何体最小深度约 0.02，UI clear value 精确为 0.0，0.001 安全 |
| 三脚本合并为 `capture_all.py` | 减少维护负担，统一 Ctrl+C 停止，stop.wait() 替代 sleep 保证响应性 |

---

## Current State

**Working**：
- `D:\ff7_tools\capture_all.py`：一键启动三线程采集管线
- `D:\ff7_tools\pack_hdf5.py`：HDF5 打包 + UI 遮罩双方案 + spot-check
- `E:\games\ff7remake\End\Binaries\Win64\reshade-shaders\Shaders\UIRemove.fx`：已部署，**待在 ReShade 界面手动启用**
- `D:\ff7_dataset\dataset.h5`：3 帧 color-only HDF5，结构验证通过
- 三个原始脚本仍保留（`record_inputs.py` / `auto_capture.py` / `file_watcher.py`）

**Broken**：无

**Uncommitted Changes**：
- `D:\ff7_tools\capture_all.py` — 本次新增，未提交（此 repo 仅为文档库，工具在 D:/E: 盘）
- `D:\ff7_tools\pack_hdf5.py` — 本次修改，增加 UI 遮罩逻辑
- `E:\...\UIRemove.fx` — 本次新增 ReShade 着色器
- `docs/ff7remake-game-capture-research.md` — 调研报告（新增，未提交到 git）
- `docs/req/req.md` — 原始需求（新增，未提交）

---

## Files to Know

| 文件 | 说明 |
|------|------|
| `D:\ff7_dataset\CAPTURE_GUIDE.md` | **主操作手册**：完整录制流程、配置说明 |
| `D:\ff7_tools\capture_all.py` | **一键启动脚本**（本次新增）：三线程并行采集 |
| `D:\ff7_tools\pack_hdf5.py` | HDF5 打包 + UI 遮罩 A/B 双方案 |
| `D:\ff7_tools\record_inputs.py` | 原始输入录制脚本（仍可单独用） |
| `D:\ff7_tools\auto_capture.py` | 原始帧捕获脚本（仍可单独用） |
| `D:\ff7_tools\file_watcher.py` | 原始文件搬运脚本（仍可单独用） |
| `E:\games\ff7remake\End\Binaries\Win64\reshade-shaders\Shaders\UIRemove.fx` | ReShade UI 遮罩着色器（方案 B） |
| `docs/ff7remake-game-capture-research.md` | 方案调研报告（含 RenderDoc 备用方案） |

---

## Code Context

### 游戏与工具路径

```
游戏 Win64 目录：E:\games\ff7remake\End\Binaries\Win64\
游戏 EXE：       E:\games\ff7remake\End\Binaries\Win64\ff7remake_.exe
帧输出目录：     D:\ff7_dataset\frames\
输入文件：       D:\ff7_dataset\inputs.jsonl
工具目录：       D:\ff7_tools\
操作手册：       D:\ff7_dataset\CAPTURE_GUIDE.md
```

### capture_all.py 用法

```bash
python D:\ff7_tools\capture_all.py              # 30fps，Ctrl+C 停止
python D:\ff7_tools\capture_all.py 30 120       # 30fps，120 秒自动停
python D:\ff7_tools\capture_all.py 60           # 60fps
```

### pack_hdf5.py 用法

```bash
# 正常打包
python D:\ff7_tools\pack_hdf5.py

# 目视验证
python D:\ff7_tools\pack_hdf5.py --spot-check D:/ff7_dataset/dataset.h5 --check-frames 0,99,499
```

### UI 遮罩逻辑（pack_hdf5.py 核心片段）

```python
# triplet 模式打包循环内：
depth_arr = _load_depth(frame['depth'])
ui_mask = depth_arr == 0.0          # UI 像素：UE4 Reverse-Z clear value
if ui_mask.any():
    color[ui_mask] = 0              # 方案 B 已生效时为 no-op；否则方案 A 兜底
ds_depth[i] = depth_arr
```

日志解读：
- `[MASK] 未发现 UI 像素` → ReShade UIRemove.fx（方案 B）已生效
- `[MASK] 方案A兜底：平均每帧遮罩 XXXX 个 UI 像素` → B 未启用，A 在工作

### UIRemove.fx 关键参数

```hlsl
#ifndef UI_DEPTH_THRESHOLD
  #define UI_DEPTH_THRESHOLD 0.001   // 可在 ReShade Preprocessor Definitions 里调整
#endif
// UE4 Reverse-Z：raw depth < 0.001 → UI 像素 → 置黑
// 真实几何体最近深度约 0.02，阈值安全
```

### HDF5 数据集结构

```python
import h5py
with h5py.File('D:/ff7_dataset/dataset.h5', 'r') as f:
    color    = f['color'][i]        # uint8  (H, W, 3) RGB，UI 区域已置黑
    depth    = f['depth'][i]        # float32 (H, W)   0.02-0.07（triplet 模式）
    normal   = f['normal'][i]       # float32 (H, W, 3) 法线 RGB
    frame_ts = f['frame_ts'][i]     # int64  UTC 纳秒
    input_ts = f['input_ts'][i]     # int64  UTC 纳秒
    dt_ms    = f['input_dt_ms'][i]  # float32 对齐误差（ms）
    kb       = f['kb'][i]           # uint8  (256,) 键盘状态
    mouse    = f['mouse'][i]        # int32  (2,) [x, y]
    gamepad  = f['gamepad'][i]      # float32 (7,) [buttons,lt,rt,lx,ly,rx,ry]
    # attrs: ui_mask_avg_px — 平均每帧被方案 A 遮罩的像素数（B 生效时为 0）
```

### 文件名格式（两种，均已支持）

```
格式 A（triplet）：
  ff7remake_.exe 2026-04-28 19-17-06 805 BackBuffer.bmp
  ff7remake_.exe 2026-04-28 19-17-06 805 DepthBuffer.exr
  ff7remake_.exe 2026-04-28 19-17-06 805 NormalMap.exr

格式 B（color-only）：
  ff7remake_ 2026-04-28 19-10-10_523.bmp
```

---

## Resume Instructions

1. **游戏内准备**（每次新会话）：
   - 启动游戏，进入可移动场景（避免过场动画）
   - 打开 ReShade 面板，确认以下技术已勾选：
     - `DepthToAddon`（深度导出，采集 EXR 必须）
     - `UIRemove`（方案 B，首次需手动勾选）
   - 在 Frame Capture Settings 确认三个开关已勾选（Enable capturing / Export Depth / Export Normals）
   - 游戏内输入 `showflag.hud 0`（可选，双重保险）

2. **小规模验证**（10 秒，确认 triplet + UI 遮罩正常）：
   ```bash
   python D:\ff7_tools\capture_all.py 30 10
   python D:\ff7_tools\pack_hdf5.py
   ```
   预期：
   - `[SCAN] 模式=triplet, 帧数=~300`
   - `[MASK] 未发现 UI 像素`（B 生效）或 `方案A兜底`（B 未开，A 兜底，均可接受）
   - 最大对齐误差 < 10 ms

3. **正式大规模采集**（120 秒，约 3600 帧）：
   ```bash
   python D:\ff7_tools\capture_all.py 30 120
   ```
   注意：30fps × 1440p triplet ≈ 34 GB/分钟，确认 D: 盘有足够空间

4. **打包 HDF5**：
   ```bash
   python D:\ff7_tools\pack_hdf5.py
   ```

5. **目视验证**：
   ```bash
   python D:\ff7_tools\pack_hdf5.py --spot-check D:/ff7_dataset/dataset.h5 --check-frames 0,99,499
   ```
   预期：`D:\ff7_dataset\spot_checks\` 下 3 张 PNG，深度伪彩色叠加有分层（角色/墙壁可区分），UI 区域为黑色，dt < 10 ms

   如深度叠加颜色均匀无分层 → 检查 DepthToAddon.fx 是否在 ReShade 主页启用

---

## Warnings

- **ReShade 版本锁死 5.9.2**：不要升级到 6.x，EXR 会静默失败只产生 BMP
- **Frame Capture Settings 三开关**：每台新机器首次启动需在游戏内手动勾选
- **addon 必须在 Win64 根目录**：不能放子目录
- **UIRemove.fx 需手动在 ReShade 启用**：文件已部署，但 ReShade 不自动激活新 technique
- **UIRemove 效果排序**：确保 UIRemove 在效果列表中排在 Frame Capture 触发之前
- **EXR 值域 0.02–0.07**：深度经 UE4 Reverse-Z + shader 处理后，不是原始 GPU 深度
- **磁盘吞吐**：30fps × 1440p ≈ 34 GB/分钟，必须 NVMe SSD，建议先 10 秒小规模验证
- **HUD Console 命令不持久化**：每次新游戏会话需重新输入 `showflag.hud 0`
- **此 git repo 仅为文档库**：工具脚本在 D:\ff7_tools\，不在 git 版本控制下
