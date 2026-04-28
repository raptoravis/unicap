# FF7 Remake 逐帧数据采集方案调研报告

> 生成日期：2026-04-28
> 需求来源：从运行中单机游戏采集逐帧 Color + Depth + Input，用于研究

---

## 一、需求定义

从已运行的二进制游戏中，逐帧同步输出：

| 数据类型 | 内容 | 用途 |
|---------|------|------|
| 游戏画面 | RGB 帧图像 | 视觉输入 |
| 深度信息 | Depth Buffer（GPU 原始值） | 3D 结构感知 |
| 输入状态 | 键盘 / 鼠标 / 手柄 | 行为标注 |

目标游戏：**Final Fantasy VII Remake Intergrade**
使用场景：单机，研究用途（无联机、无反作弊顾虑）

---

## 二、目标游戏技术档案

| 维度 | 确认信息 |
|------|---------|
| 游戏引擎 | Unreal Engine 4（官方确认） |
| 图形 API | **DX11 为主**，部分配置支持 DX12 |
| 反作弊 | **无**（单机，Square Enix 无 EAC/BattleEye） |
| DRM | Denuvo（不影响 DLL 注入，仅防止程序被修改） |
| ReShade 兼容性 | ✅ 社区大量 Mod 证实可用，2025 年仍活跃 |
| 注入目录 | `...\FINAL FANTASY VII REMAKE\End\Binaries\Win64\` |

---

## 三、核心技术挑战

| 维度 | 难度 | 说明 |
|------|------|------|
| RGB 画面采集 | 低 | OBS / DXGI Desktop Dup 均可解决 |
| **深度缓冲采集** | **高** | 必须在 GPU 管线内拦截，是整个问题的瓶颈 |
| 输入同步采集 | 中 | Windows RawInput / XInput API 成熟，但需与帧对齐 |
| 三路数据帧对齐 | 高 | 时序戳对齐是工程难点 |

---

## 四、方案对比

| # | 方案 | 深度来源 | 实时连续 | 配置难度 | 社区验证 |
|---|------|---------|---------|---------|---------|
| 1 | **ReShade + FrameCapture Addon** | UE4 SceneDepth（32-bit EXR） | ✅ | 低（放文件即可） | ✅ 大量 Nexus Mod 证实 |
| 2 | **RenderDoc + UE4 控制台触发** | GPU 原始深度缓冲 | ❌（逐段捕获） | 中（需解锁控制台） | ✅ UE4 官方文档支持 |
| 3 | **自研 DX11 Proxy DLL** | GPU 原始深度缓冲 | ✅ | 高（C++ 开发） | — |

**推荐路线**：先跑方案 1 验证数据，再用方案 2 做精度基准对比。

---

## 五、方案一：ReShade + FrameCapture Addon（推荐首选）

### 5.1 安装步骤

```
游戏目录：
  ...\FINAL FANTASY VII REMAKE\End\Binaries\Win64\

放入文件：
  dxgi.dll          ← ReShade 主体（选 DX11 版）
  ReShade.ini
  reshade-shaders/  ← 着色器目录
  addons/FrameCapture.addon   ← murchalloo 开发

⚠️ 如启动崩溃：将 dxgi.dll 重命名为 d3d11.dll 再试
```

### 5.2 ReShade.ini 配置

```ini
[SCREENSHOT]
SavePath=D:\ff7_dataset\frames\
FileFormat=PNG
DepthFormat=EXR
CaptureDepth=1
```

### 5.3 输入录制（独立 Python 进程）

```python
import ctypes, time, json, threading

xinput = ctypes.WinDLL("xinput1_4")
user32 = ctypes.WinDLL("user32")

def record_inputs(output_path):
    log = []
    while recording:
        t = time.time_ns()
        # 键盘 256 键状态
        kb = (ctypes.c_ubyte * 256)()
        user32.GetKeyboardState(kb)
        # 手柄
        state = XINPUT_STATE()
        xinput.XInputGetState(0, ctypes.byref(state))
        # 鼠标
        pt = POINT()
        user32.GetCursorPos(ctypes.byref(pt))

        log.append({
            "ts": t,
            "kb": list(kb),
            "gamepad": parse_xinput(state),
            "mouse": [pt.x, pt.y]
        })
        time.sleep(1 / 120)  # 120Hz 采样

    with open(output_path, "w") as f:
        for entry in log:
            f.write(json.dumps(entry) + "\n")
```

### 5.4 后处理对齐合并

```python
import h5py, numpy as np, json
from pathlib import Path

dataset_root = Path("D:/ff7_dataset/frames")
color_files  = sorted(dataset_root.glob("*_color.png"))
depth_files  = sorted(dataset_root.glob("*_depth.exr"))
input_log    = [json.loads(l) for l in open("inputs.jsonl")]

with h5py.File("ff7_dataset.hdf5", "w") as f:
    for i, (c, d) in enumerate(zip(color_files, depth_files)):
        grp = f.create_group(f"{i:06d}")
        grp.create_dataset("color", data=load_png(c))        # (H, W, 3) uint8
        grp.create_dataset("depth", data=load_exr(d))        # (H, W)    float32
        grp.create_dataset("input", data=align_input(input_log, i))
```

---

## 六、方案二：RenderDoc + UE4 控制台（精度验证用）

### 6.1 解锁 UE4 开发者控制台

```ini
# 文件位置：
# %LOCALAPPDATA%\FINAL FANTASY VII REMAKE\Saved\Config\WindowsNoEditor\Engine.ini

[SystemSettings]
con.EnableConsole=1
```

游戏内按 **`~`** 打开控制台，输入：

```
renderdoc.CaptureFrame      ← 捕获当前帧为 .rdc 文件
r.DumpRenderTargets 1       ← 导出所有渲染目标（含 SceneDepth）
```

### 6.2 Python API 批量提取深度

```python
import renderdoc as rd
import numpy as np

rdc = rd.OpenCaptureFile()
rdc.OpenFile("capture.rdc", "", None)
controller = rdc.OpenCapture(0, None)

# 提取 SceneDepth texture
depth_tex = find_scene_depth_texture(controller)
data = controller.GetTextureData(depth_tex.resourceId, rd.Subresource())
depth_array = np.frombuffer(data, dtype=np.float32).reshape(H, W)
```

---

## 七、统一输出数据格式

```
ff7_dataset.hdf5
└── frames/
    ├── 000001/
    │   ├── color     → (1080, 1920, 3)  uint8
    │   ├── depth     → (1080, 1920)     float32  # 线性深度，单位：米
    │   └── input/
    │       ├── keyboard    → (256,)      bool
    │       ├── mouse       → (4,)        float32  # dx, dy, btn_mask, scroll
    │       ├── gamepad     → (10,)       float32  # LX,LY,RX,RY,LT,RT,buttons
    │       └── timestamp_ns → int64
    ├── 000002/
    │   └── ...
```

---

## 八、FF7 Remake 专项注意事项

| 问题 | 说明 | 解决方法 |
|------|------|---------|
| UE4 反向深度（Reverse-Z） | 近处=1.0，远处≈0，与直觉相反 | 线性化公式：`linear = near * far / (far - depth * (far - near))` |
| Denuvo 启动检查 | 首次启动需联网验证，之后可离线 | 正常启动一次后断网采集即可 |
| Epic/Steam 版路径差异 | Epic 版路径含空格 | 路径用双引号包裹 |
| DX12 模式兼容性 | ReShade 在 DX12 模式需重命名 DLL | 默认保持 DX11 模式更稳定 |

---

## 九、实施路线图

```
Week 1 — 验证阶段
  ① 安装 ReShade + FrameCapture Addon，放入游戏 Win64 目录
  ② 运行游戏，录制 10 秒测试片段
  ③ 检查 depth EXR：伪彩色叠加到 color 帧上，确认近/远平面渐变正常
  ④ 运行 Python 输入录制脚本，确认按键/手柄状态正确捕获

Week 2 — 对齐与打包
  ⑤ 实现时间戳对齐逻辑
  ⑥ 打包为 HDF5，抽检 100 帧验证三路数据一致性
  ⑦ 用 RenderDoc 方案捕获同一场景，对比深度精度

Week 3+（按需）— 规模化
  ⑧ 自动化采集脚本（游戏场景切换 + 自动录制）
  ⑨ 磁盘吞吐优化（float16 EXR，异步写入）
  ⑩ 如需高帧率实时流式输出 → 演进至自研 DX11 Proxy DLL
```

---

## 十、磁盘吞吐估算

| 分辨率 | 帧率 | Color (PNG) | Depth (EXR f32) | 合计/分钟 |
|--------|------|------------|----------------|---------|
| 1080p  | 30fps | ~1.5 MB/帧 | ~8 MB/帧 | ~17 GB |
| 1080p  | 60fps | ~1.5 MB/帧 | ~8 MB/帧 | ~34 GB |
| 1080p  | 60fps | ~1.5 MB/帧 | ~4 MB/帧（f16） | ~20 GB |

> 建议使用 NVMe SSD，depth 降为 float16 EXR 可节省约 50% 空间，精度对研究用途仍足够。

---

## 十一、参考资料

- [Final Fantasy VII Remake Intergrade — PCGamingWiki](https://www.pcgamingwiki.com/wiki/Final_Fantasy_VII_Remake_Intergrade)
- [FF7 Remake ReShade Mods — Nexus Mods](https://www.nexusmods.com/finalfantasy7remake/mods/58)
- [How Square Enix optimized FF7R — Unreal Engine 官方](https://www.unrealengine.com/en-US/developer-interviews/how-square-enix-impressively-optimized-final-fantasy-vii-remake-intergrade-for-next-gen)
- [Using RenderDoc with Unreal Engine — Epic Developer Community](https://dev.epicgames.com/documentation/en-us/unreal-engine/using-renderdoc-with-unreal-engine)
- [renderdoc_for_game_data — GitHub (GTA5 学术采集参考)](https://github.com/xiaofeng94/renderdoc_for_game_data)
- [RenderDoc Python API](https://renderdoc.org/docs/python_api/index.html)
- [ReShade Depth Capture Guide — FRAMED Screenshot Community](https://framedsc.com/ReshadeGuides/depthguide.htm)
- [DirectXHook — GitHub](https://github.com/techiew/DirectXHook)
- [OpenAI VPT: Video PreTraining](https://openai.com/index/vpt/)
