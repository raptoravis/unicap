# Handoff: unicap pipeline — DX11 修复 + 分辨率参数完成

**Generated**: 2026-04-30
**Branch**: master (up to date with origin)
**Status**: Working — 待实机验证（Batman AK / FF7 Remake）

## Goal

FF7 Remake / Batman: Arkham Knight (及其他 DX11/DX12 游戏) 帧采集管线：
- 游戏内按 F9 触发采集，每帧写 `*BackBuffer.bmp` + `*DepthBuffer.exr`
- 零 ReShade UI/splash，游戏目录最小化（仅 dxgi.dll），配置/日志写 `%TEMP%\unicap\`
- 输出分辨率可配置（默认 1600×1200），采集结束自动生成 HDF5 dataset

## Completed

- [x] 6.7.3 DLL 零 splash + UIRemove_ColorTex 路径拿 BMP
- [x] addon 直接写入目标 `frames_dir`（`fc_output_dir.txt` sidecar）
- [x] 异步 save worker + staging texture 预分配 + 单次 wait_idle()
- [x] **DX11 全黑帧修复**：`copy_texture_to_buffer` → `copy_texture_region`，staging buffer → staging texture，`map_buffer_region` → `map_texture_region`
- [x] **分辨率参数**：`FC_CaptureWidth`/`FC_CaptureHeight`（默认1600×1200），save worker 中用 stbir_resize 缩放，`--width`/`--height` CLI 参数
- [x] 游戏目录最小化：deploy 仅创建 dxgi.dll symlink
- [x] ReShade 文件重命名为 unicap（ini_file.cpp, dll_main.cpp, runtime_gui.cpp, runtime_manager.cpp）
- [x] UNICAP_TEMP = `%TEMP%\unicap`，RESHADE_BASE_PATH_OVERRIDE env var
- [x] build.ps1 -Rebuild：删除 build\ 整个目录再重新 configure
- [x] `_make_video` OSError 修复：libx264 偶数尺寸强制 + broken pipe 处理

## Not Yet Done

- [ ] **端到端验证**：实际运行确认 BMP 有内容（非全黑）、save queue 不满
- [ ] save queue full 问题（Batman AK 2423×1363 @ 30fps = ~390 MB/s，超出磁盘带宽）→ 降 fps 或进一步观察 1600×1200 是否改善
- [ ] 决定是否保留 `reshade/` 源码（6.7.3.16 UNOFFICIAL，体积大）
- [ ] 后续 ML 训练定制

## Failed Approaches (Don't Repeat These)

1. **`copy_texture_to_buffer` + staging buffer**：DX11 不支持 texture→buffer 直接 copy，`copy_texture_to_buffer` 静默失败，staging buffer 保持全零，BMP 全黑。改为 staging texture + `copy_texture_region`。

2. **手动计算 `color_row_pitch`**：`(format_row_pitch(...) + 255) & ~255` 硬编码 D3D12 256字节对齐，DX11 对齐不同。改为 `map_texture_region` 直接返回真实 `row_pitch`。

3. **staging buffer 用于 depth**：同上，DX11 下 `copy_texture_to_buffer` 对 depth texture 也静默失败。同样改为 staging texture。

4. **watcher 线程监控 + shutil.move**：跨磁盘时 move = copy+delete，极慢。已改为 addon 直接写目标目录。

5. **每帧 create/destroy staging buffer**：GPU 内存分配开销高。已改为预分配，按分辨率变化时才重建。

6. **EXR PIZ 压缩在 render 线程**：PIZ CPU 密集，100-500ms/帧，阻塞游戏。已改为 async worker + ZIP。

7. **`capture_screenshot()` + 6.7.3 DLL**：R10G10B10A2 swap chain 下返回 ExportTex 数据（psychedelic 色）。改用 UIRemove_ColorTex。

8. **`runtime_manager.cpp` config_name = "ReShade"**：runtime config 与 global config 不一致，PresetPath 读不到，UIRemove 不加载，无 BMP。已改为 `"unicap"`。

9. **build.ps1 -Rebuild 用 cmake -DRESHADE_ALWAYS_REBUILD=ON**：build/ 已存在时跳过 configure，flag 无效。改为删除整个 build/ 目录。

10. **`_make_video` 直接写 `proc.stdin`**：ffmpeg 因奇数尺寸退出（libx264 要求偶数），写入已关闭的 pipe 触发 `OSError: [Errno 22] Invalid argument`。已修复：强制偶数尺寸 + try/except + stderr 显示。

## Key Decisions

| Decision | Rationale |
|----------|-----------|
| staging texture (非 buffer) | DX11/DX12 均支持 copy_texture_region；buffer 方案在 DX11 静默失败 |
| map_texture_region 的 row_pitch | API 直接返回正确对齐值，无需手动计算 |
| 分辨率缩放在 save worker | 不阻塞 render thread；stbir 质量够用于 ML 训练 |
| 默认 1600×1200 | 平衡文件大小与图像质量；BMP 约 7.7MB/帧（原始 13MB） |
| FC_CaptureWidth=0 = 原始分辨率 | 0 值跳过 resize，保持灵活性 |
| `--mode custom` = `dist/dxgi.dll` (6.7.3) | 唯一零 splash 方案 |
| BMP via UIRemove_ColorTex | 6.7.3 capture_screenshot 在 R10G10B10A2 损坏 |
| UNICAP_TEMP = `%TEMP%\unicap` | 配置/日志集中管理，游戏目录保持干净 |
| runtime_manager.cpp config_name = "unicap" | per-runtime config = global config = unicap.ini |
| Technique 顺序：DepthToAddon → UIRemove | DepthToAddon 写自定义 RT；UIRemove 最后 snapshot BackBuffer |

## Current State

**完全实现，未实机运行验证**：
- `dist/dxgi.dll` — 6.7.3，零 splash，unicap 重命名
- `dist/frame_capture.addon` — v20 API，DX11/DX12 兼容，分辨率缩放
- `main.py launch --mode custom` — 部署 + 启动 + 采集 + 自动打包

## Files to Know

| File | Why It Matters |
|------|----------------|
| `reshade-addons/99-frame_capture/frame_capture.cpp` | 整个 addon：staging texture、async worker、resize |
| `reshade/source/runtime_manager.cpp` | `config_name = "unicap"` — 关键，使 runtime config = unicap.ini |
| `reshade/source/ini_file.cpp` | `global_config()` = `unicap.ini` |
| `shaders/UIRemove.fx` | ExportColor pass → UIRemove_ColorTex (RGBA8, BUFFER_WIDTH×BUFFER_HEIGHT) |
| `shaders/DepthToAddon.fx` | 暴露 DepthToAddon_ExportTex (RGBA32F，depth 在 alpha channel) |
| `main.py` | CLI：`_ensure_addon_enabled(addon_dir, cap_width, cap_height)` 写 unicap.ini |
| `tools/capture/capture_all.py` | 采集主循环，写 fc_output_dir.txt sidecar |
| `tools/capture/config.py` | 机器相关路径：GAME_PATH、DATASET_ROOT |
| `scripts/build.ps1` | `-Rebuild` 删除 build\ 整个目录 |

## Code Context

**on_reshade_present 热路径（简化）：**
```cpp
// 触发条件：F10 (VK 0x79) pressed && enableCapturing
// 1. 检查 save queue size < MAX_QUEUE(4)，满则 drop+log
// 2. 读 fc_output_dir.txt → out_dir（回退到游戏目录）
// 3. 确保 color_staging/depth_staging 已分配（staging texture，按分辨率变化重建）
// 4. GPU: barrier(shader_resource → copy_source)
//    GPU: copy_texture_region(color_texture_r → color_staging)
//    GPU: barrier(copy_source → shader_resource)
//    同样处理 depth_staging
// 5. queue->wait_idle()  ← 单次 GPU sync（color + depth 合并）
// 6. map_texture_region → 用 row_pitch 做 de-pitch memcpy → SaveTask
// 7. enqueue → notify worker，render thread 返回
```

**staged texture 创建：**
```cpp
resource_desc sd(width, height, 1, 1,
                 src_format, 1,
                 memory_heap::gpu_to_cpu, resource_usage::copy_dest);
dev->create_resource(sd, nullptr, resource_usage::copy_dest, &sbi.color_staging);
```

**map_texture_region 使用：**
```cpp
subresource_data color_data = {};
dev->map_texture_region(sbi.color_staging, 0, nullptr, map_access::read_only, &color_data);
// color_data.data：指向 CPU 可读内存
// color_data.row_pitch：实际行字节数（含对齐 padding）
for (uint32_t y = 0; y < height; y++)
    memcpy(dst + y * width * 4, src + y * color_data.row_pitch, width * 4);
dev->unmap_texture_region(sbi.color_staging, 0);
```

**分辨率缩放（save worker 中）：**
```cpp
// g_cap_width/g_cap_height 从 unicap.ini FC_CaptureWidth/FC_CaptureHeight 读取
// 0 = 跳过缩放，保持原始分辨率
if (g_cap_width > 0 && g_cap_height > 0 && (color_w != g_cap_width || color_h != g_cap_height)) {
    stbir_resize_uint8(src, w, h, 0, dst, g_cap_width, g_cap_height, 0, 4);
}
// depth 用 stbir_resize_float（RGBA32F，4 channels）
```

**CLI：**
```
uv run main.py launch --mode custom --width 1600 --height 1200
uv run main.py launch --mode custom --width 0 --height 0  # 原始分辨率
uv run main.py deploy --width 1280 --height 720           # 只部署+写 ini
```

**_ensure_addon_enabled 写入 unicap.ini 的关键 keys：**
```ini
[ADDON]
AddonPath      = D:\dev\unicap.git\dist
FC_EnableCapture = 1
FC_ExportDepth   = 1
FC_CaptureWidth  = 1600
FC_CaptureHeight = 1200

[GENERAL]
EffectSearchPaths = D:\dev\unicap.git\shaders
IntermediateCachePath = C:\Users\...\AppData\Local\Temp\unicap
PresetPath = D:\dev\unicap.git\config\unicapPreset.ini

[OVERLAY]
TutorialProgress = 4   ← 必须在 [OVERLAY]，不是 [GENERAL]
```

## Resume Instructions

1. **确认 addon 已编译**（含 DX11 修复和 resize）：
   ```powershell
   # 若 dist/frame_capture.addon 时间戳早于 2026-04-30 15:00，重新编译：
   scripts\build.ps1
   ```

2. **清理游戏目录残留**（旧版本可能遗留 ReShade.ini、reshade-shaders/）：
   ```powershell
   # Batman AK：
   Remove-Item "E:\SteamLibrary\steamapps\common\Batman Arkham Knight\Binaries\Win64\ReShade.ini" -ea SilentlyContinue
   Remove-Item "E:\SteamLibrary\steamapps\common\Batman Arkham Knight\Binaries\Win64\reshade-addons" -Recurse -ea SilentlyContinue
   ```

3. **Deploy + 启动**：
   ```powershell
   uv run main.py launch --mode custom --game-path "E:\SteamLibrary\steamapps\common\Batman Arkham Knight\Binaries\Win64\BatmanAK.exe"
   # 游戏内按 F9 开始采集
   ```

4. **验证**：
   - `%TEMP%\unicap\unicap.log` 中有 `FC: listing all effect texture variables` → `UIRemove_ColorTex` 出现
   - `frames/` 目录中出现 `*BackBuffer.bmp`，用 Python 验证非全黑：
     ```python
     import cv2; img = cv2.imread(r"path\to\frame.bmp", cv2.IMREAD_UNCHANGED)
     print(img.shape, img.max())  # 期望 shape=(1200, 1600, 4), max > 0
     ```
   - 无 `FC: save queue full` 连续 warning（偶发 ok，连续说明写盘跟不上）
   - 采集结束自动生成 `dataset.h5`

5. **若 BMP 仍全黑**：
   - 检查 log 中 `FC: failed to create color staging texture`（资源创建失败）
   - 检查 log 中 `UIRemove_ColorTex` 是否在 texture 列表（`FC: listing all effect texture variables`）
   - 若 texture 不在列表：检查 `config/unicapPreset.ini` 是否包含 `UIRemove@UIRemove.fx`

6. **若 save queue 仍持续满**：降低 fps 或降低分辨率：
   ```powershell
   uv run main.py launch --fps 15 --width 1280 --height 720 ...
   ```

## Setup Required

- VS 2022 Build Tools（重编译时需要）
- `uv sync`（Python 依赖）
- Batman AK 路径：`E:\SteamLibrary\steamapps\common\Batman Arkham Knight\Binaries\Win64\BatmanAK.exe`
- FF7 Remake 路径：`E:\games\ff7remake\End\Binaries\Win64\ff7remake_.exe`

## Warnings

- **DX11 游戏不能用 copy_texture_to_buffer**：静默失败，BMP 全黑。当前代码已用 copy_texture_region + staging texture 修复。不要回退。
- **不要用 `capture_screenshot()` + `dist/dxgi.dll`（6.7.3）**：R10G10B10A2 返回 psychedelic 色。
- **TutorialProgress 必须在 `[OVERLAY]`**：写到 `[GENERAL]` 静默忽略。
- **UIRemove 必须排在 DepthToAddon 之后**（Techniques= 顺序）。
- **ff7remake_.exe 是两进程启动器**：第一个进程 ~2s 退出，第二个做真正的 DX12 渲染，两者共享 unicap.log。
- **`reshade/deps/glad/target/`** 内有 force-add 的预生成 C headers，不要删除。
- **Batman AK 原始分辨率 2423×1363**（奇数），`_make_video` 已处理（偶数强制）。
- **save worker MAX_QUEUE=4**：队列满时 drop+log，不阻塞 render loop。
- **BMP 格式是 32-bit BITMAPV4HEADER**（stbi_write_bmp comp=4），部分老旧查看器不支持；OpenCV `IMREAD_UNCHANGED` 可正确读取。
