# Handoff: unicap pipeline — 定时采集 + 按键禁用

**Generated**: 2026-04-30
**Branch**: master (up to date with origin)
**Status**: Working — 待实机二次验证（Batman AK / FF7 Remake）

## Goal

FF7 Remake / Batman: Arkham Knight (及其他 DX11/DX12 游戏) 帧采集管线：
- 游戏内按 F9 触发 Python 会话开始，之后 addon 自动定时采集帧
- 零 ReShade UI/splash，零按键模拟（不发 F10/Home），游戏目录仅 dxgi.dll symlink
- 输出分辨率可配置（默认 1600×1200），采集结束自动生成 HDF5 dataset

## Completed

- [x] DX11 全黑帧修复：`copy_texture_region` + staging texture + `map_texture_region`
- [x] 分辨率参数：`FC_CaptureWidth`/`FC_CaptureHeight`（默认1600×1200），stbir_resize 缩放
- [x] **定时采集**：`on_reshade_present` 用 `steady_clock` 按 `FC_TargetFPS` 自动触发，不再需要 F10 按键
- [x] **F10 模拟移除**：`capture_all.py` 删除 `_thread_capture` 和所有 `keybd_event` 调用
- [x] **Home/F10 overlay 禁用**：`_ensure_addon_enabled` 写入所有 INPUT 快捷键 = `0,0,0,0`（含 `KeyOverlay`）
- [x] `_make_video` ffmpeg pipe deadlock 修复：`proc.stderr.read()` 移至 `proc.wait()` 之前
- [x] `FC_TargetFPS` 写入 `unicap.ini`，`--fps` CLI 参数控制 addon 采集帧率
- [x] 游戏目录最小化：deploy 仅 dxgi.dll symlink
- [x] ReShade 重命名为 unicap（ini_file.cpp, dll_main.cpp, runtime_manager.cpp）
- [x] UNICAP_TEMP = `%TEMP%\unicap`，RESHADE_BASE_PATH_OVERRIDE env var

## Not Yet Done

- [ ] **端到端二次验证**：含新 timer 机制的实际运行，确认 BMP 有内容、帧率正确
- [ ] save queue full 问题（Batman AK 2423×1363 @ 30fps = ~390 MB/s）→ 观察 1600×1200 是否改善
- [ ] CLAUDE.md 内容已过时（仍描述 F10 机制）— 若需准确可更新
- [ ] 决定是否保留 `reshade/` 源码（6.7.3.16 UNOFFICIAL，体积大）
- [ ] 后续 ML 训练定制

## Failed Approaches (Don't Repeat These)

1. **`copy_texture_to_buffer` + staging buffer**：DX11 不支持 texture→buffer 直接 copy，静默失败，BMP 全黑。改为 staging texture + `copy_texture_region`。

2. **手动计算 `color_row_pitch`**：`(format_row_pitch(...) + 255) & ~255` 硬编码 D3D12 256字节对齐，DX11 对齐不同。改为 `map_texture_region` 直接返回真实 `row_pitch`。

3. **staging buffer 用于 depth**：同上，DX11 下 `copy_texture_to_buffer` 静默失败。同样改为 staging texture。

4. **watcher 线程监控 + shutil.move**：跨磁盘时 move = copy+delete，极慢。已改为 addon 直接写目标目录。

5. **每帧 create/destroy staging buffer**：GPU 内存分配开销高。已改为预分配，按分辨率变化时才重建。

6. **EXR PIZ 压缩在 render 线程**：PIZ CPU 密集，100-500ms/帧，阻塞游戏。已改为 async worker + ZIP。

7. **`capture_screenshot()` + 6.7.3 DLL**：R10G10B10A2 swap chain 下返回 ExportTex 数据（psychedelic 色）。改用 UIRemove_ColorTex。

8. **`runtime_manager.cpp` config_name = "ReShade"**：runtime config 与 global config 不一致，PresetPath 读不到，UIRemove 不加载，无 BMP。已改为 `"unicap"`。

9. **build.ps1 -Rebuild 用 cmake -DRESHADE_ALWAYS_REBUILD=ON**：build/ 已存在时跳过 configure，flag 无效。改为删除整个 build/ 目录。

10. **`_make_video` `proc.wait()` 在 `stderr.read()` 之前**：ffmpeg stderr pipe buffer 满时死锁（ffmpeg 等 Python 读，Python 等 ffmpeg 退出）。已修复：先 `proc.stderr.read()` 再 `proc.wait()`。

11. **`_thread_capture` 发 F10**：按键会干扰游戏操作，且 F10 在游戏中可能有其他绑定。改为 addon 内部 `steady_clock` 定时触发。

12. **`KeyOverlay` 未在 `_ensure_addon_enabled` 中覆盖**：ReShade 默认写入 `KeyOverlay=36,0,0,0`（Home），导致 Home 仍可打开 overlay。已在 `_ensure_addon_enabled` 显式设置所有 INPUT 快捷键为 `0,0,0,0`。

## Key Decisions

| Decision | Rationale |
|----------|-----------|
| staging texture（非 buffer） | DX11/DX12 均支持 copy_texture_region；buffer 方案在 DX11 静默失败 |
| map_texture_region 的 row_pitch | API 直接返回正确对齐值，无需手动计算 |
| steady_clock 定时触发（非 F10） | 不干扰游戏，不依赖 Python 发键，精度更高 |
| FC_TargetFPS 在 unicap.ini | Python --fps 写 ini，addon 读 ini；两侧解耦 |
| 分辨率缩放在 save worker | 不阻塞 render thread；stbir 质量够用于 ML 训练 |
| 默认 1600×1200 | 平衡文件大小与图像质量；BMP 约 7.7MB/帧（原始 13MB） |
| FC_CaptureWidth=0 = 原始分辨率 | 0 值跳过 resize，保持灵活性 |
| `--mode custom` = `dist/dxgi.dll` (6.7.3) | 唯一零 splash 方案 |
| BMP via UIRemove_ColorTex | 6.7.3 capture_screenshot 在 R10G10B10A2 损坏 |
| UNICAP_TEMP = `%TEMP%\unicap` | 配置/日志集中管理，游戏目录保持干净 |
| runtime_manager.cpp config_name = "unicap" | per-runtime config = global config = unicap.ini |
| Technique 顺序：DepthToAddon → UIRemove | DepthToAddon 写自定义 RT；UIRemove 最后 snapshot BackBuffer |
| 所有 INPUT 快捷键 = 0,0,0,0 | 防止 ReShade 响应任何键盘输入，游戏控制不受干扰 |

## Current State

**完全实现，timer 机制未实机验证**：
- `dist/dxgi.dll` — 6.7.3，零 splash，unicap 重命名
- `dist/frame_capture.addon` — 定时触发（steady_clock），DX11/DX12 兼容，分辨率缩放
- `main.py launch --mode custom` — 部署 + 启动 + 采集 + 自动打包
- unicap.ini 所有 INPUT 快捷键清零

## Files to Know

| File | Why It Matters |
|------|----------------|
| `reshade-addons/99-frame_capture/frame_capture.cpp` | 整个 addon：定时触发、staging texture、async worker、resize |
| `reshade/source/runtime_manager.cpp` | `config_name = "unicap"` — 关键，使 runtime config = unicap.ini |
| `reshade/source/ini_file.cpp` | `global_config()` = `unicap.ini` |
| `shaders/UIRemove.fx` | ExportColor pass → UIRemove_ColorTex (RGBA8) |
| `shaders/DepthToAddon.fx` | 暴露 DepthToAddon_ExportTex (RGBA32F，depth 在 alpha channel) |
| `main.py` | CLI：`_ensure_addon_enabled` 写 unicap.ini（含所有 INPUT 键清零） |
| `tools/capture/capture_all.py` | 采集主循环：写 fc_output_dir.txt sidecar，监控帧数进度 |
| `tools/capture/config.py` | 机器相关路径：GAME_PATH、DATASET_ROOT |
| `scripts/build.ps1` | `-Rebuild` 删除 build\ 整个目录 |

## Code Context

**on_reshade_present 定时触发（替换原 F10）：**
```cpp
static std::chrono::steady_clock::time_point s_last_capture;
static float g_target_fps = 30.0f;  // read from FC_TargetFPS in unicap.ini

static void on_reshade_present(effect_runtime* runtime)
{
    if (!enableCapturing) return;

    auto tick = std::chrono::steady_clock::now();
    float fps = (g_target_fps > 0.0f) ? g_target_fps : 30.0f;
    if (std::chrono::duration<float>(tick - s_last_capture).count() < 1.0f / fps)
        return;
    s_last_capture = tick;
    // ... capture code continues
}
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
for (uint32_t y = 0; y < height; y++)
    memcpy(dst + y * width * 4, src + y * color_data.row_pitch, width * 4);
dev->unmap_texture_region(sbi.color_staging, 0);
```

**_ensure_addon_enabled 写入 unicap.ini 的关键 keys：**
```ini
[ADDON]
FC_EnableCapture  = 1
FC_ExportDepth    = 1
FC_TargetFPS      = 30
FC_CaptureWidth   = 1600
FC_CaptureHeight  = 1200

[INPUT]
KeyOverlay        = 0,0,0,0   ← 必须显式设置，否则 ReShade 默认写 36,0,0,0 (Home)
KeyScreenshot     = 0,0,0,0
KeyEffects        = 0,0,0,0
KeyReload         = 0,0,0,0
KeyNextPreset     = 0,0,0,0
KeyPreviousPreset = 0,0,0,0

[OVERLAY]
TutorialProgress  = 4         ← 必须在 [OVERLAY]，不是 [GENERAL]
```

**capture_all.py — 无 F10，进度靠计文件数：**
```python
def run(fps, duration, frames_dir, inputs_out, watch_dir):
    sidecar = watch_dir / "fc_output_dir.txt"
    sidecar.write_text(str(frames_dir))   # addon 读取输出目录
    # 只启动 input 线程，无 capture 线程
    # 主循环计 *BackBuffer.bmp 文件数打印进度
    # 结束时删除 sidecar
```

**CLI：**
```
uv run main.py launch --mode custom --game-path "E:\...\BatmanAK.exe"
uv run main.py launch --mode custom --fps 15 --width 1280 --height 720 ...
uv run main.py launch --mode custom --width 0 --height 0 ...  # 原始分辨率
```

## Resume Instructions

1. **确认 dist/frame_capture.addon 已包含定时触发代码**（commit d22b9d8，2026-04-30）：
   ```powershell
   git log --oneline dist/frame_capture.addon | head -3
   # 应看到 d22b9d8
   ```

2. **清理游戏目录残留**（旧版本可能遗留 ReShade.ini）：
   ```powershell
   Remove-Item "E:\SteamLibrary\steamapps\common\Batman Arkham Knight\Binaries\Win64\ReShade.ini" -ea SilentlyContinue
   ```

3. **Deploy + 启动**：
   ```powershell
   uv run main.py launch --mode custom --game-path "E:\SteamLibrary\steamapps\common\Batman Arkham Knight\Binaries\Win64\BatmanAK.exe"
   # 游戏内按 F9 开始采集，Ctrl+C 停止
   ```

4. **验证**：
   - `%TEMP%\unicap\unicap.log` 中有 `FC: listing all effect texture variables` → `UIRemove_ColorTex` 出现
   - `frames/` 目录中出现 `*BackBuffer.bmp`，每 ~33ms 一个（30fps）
   - 用 Python 验证非全黑：
     ```python
     import cv2; img = cv2.imread(r"path\to\frame.bmp", cv2.IMREAD_UNCHANGED)
     print(img.shape, img.max())  # 期望 shape=(1200,1600,4), max > 0
     ```
   - Home/F10 键在游戏内不触发任何 ReShade 行为
   - 无 `FC: save queue full` 连续 warning

5. **若 BMP 仍全黑**：
   - 检查 log 中 `FC: UIRemove_ColorTex not ready, skipped`（texture 未就绪）
   - 检查 `config/unicapPreset.ini` 是否包含 `UIRemove@UIRemove.fx`
   - 确认 unicap.ini `[INPUT] KeyOverlay = 0,0,0,0`（不是 `36,0,0,0`）

6. **若 save queue 持续满**：
   ```powershell
   uv run main.py launch --fps 15 --width 1280 --height 720 ...
   ```

## Setup Required

- VS 2022 Build Tools（重编译时需要）
- `uv sync`（Python 依赖）
- Batman AK 路径：`E:\SteamLibrary\steamapps\common\Batman Arkham Knight\Binaries\Win64\BatmanAK.exe`
- FF7 Remake 路径：`E:\games\ff7remake\End\Binaries\Win64\ff7remake_.exe`

## Warnings

- **DX11 游戏不能用 `copy_texture_to_buffer`**：静默失败，BMP 全黑。当前代码已用 `copy_texture_region` + staging texture 修复。不要回退。
- **不要用 `capture_screenshot()` + `dist/dxgi.dll`（6.7.3）**：R10G10B10A2 返回 psychedelic 色。
- **`KeyOverlay` 必须显式写 `0,0,0,0`**：不写则 ReShade 运行时自动写入 `36,0,0,0`（Home），导致 Home 键打开 overlay。
- **`TutorialProgress` 必须在 `[OVERLAY]`**：写到 `[GENERAL]` 静默忽略。
- **UIRemove 必须排在 DepthToAddon 之后**（Techniques= 顺序）。
- **`steady_clock` 的 `s_last_capture` 初始为 epoch**：首次进入 `on_reshade_present` 时差巨大，必然触发一帧。这是正常的。
- **ff7remake_.exe 是两进程启动器**：第一个进程 ~2s 退出，第二个做真正的 DX12 渲染。
- **Batman AK 原始分辨率 2423×1363**（奇数），`_make_video` 已处理（偶数强制）。
- **`reshade/deps/glad/target/`** 内有 force-add 的预生成 C headers，不要删除。
- **BMP 格式是 32-bit BITMAPV4HEADER**（stbi_write_bmp comp=4），OpenCV `IMREAD_UNCHANGED` 可正确读取。
