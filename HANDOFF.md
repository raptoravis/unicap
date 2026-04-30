# Handoff: unicap pipeline — 性能优化完成，待端到端验证

**Generated**: 2026-04-30
**Branch**: master (up to date with origin)
**Status**: Working — pending end-to-end test with game running

## Goal

FF7 Remake (DX12, R10G10B10A2_UNORM) 帧采集管线：F10 → `*BackBuffer.bmp` + `*DepthBuffer.exr`，零 ReShade UI/splash，游戏帧率影响最小，采集结束自动生成 HDF5 dataset。

## Completed

- [x] 6.7.3 DLL (`dist/dxgi.dll`) — 零 splash，UIRemove_ColorTex 路径拿 BMP（绕过 capture_screenshot 的 R10G10B10A2 bug）
- [x] addon 直接写入目标 `frames_dir`（通过 `fc_output_dir.txt` sidecar），无 watcher/move
- [x] **异步 save worker**：render 线程只做 GPU copy + wait_idle + memcpy，立即返回；worker 线程负责 BMP/EXR 写盘
- [x] **staging buffer 预分配**：首帧分配，后续每帧复用，消除 per-frame GPU 内存分配
- [x] **单次 wait_idle()**：color + depth GPU copy 合并后一次性 sync
- [x] **EXR 压缩 PIZ → ZIP**：约 4x 速度提升
- [x] `cmd_capture` 采集后自动打包 HDF5（`--no-pack` 跳过）
- [x] `deploy` / `launch` 新增 `--clean` 开关，部署前删除旧文件
- [x] 所有改动已编译、commit、push（最新: `ee532e0`）

## Not Yet Done

- [ ] **端到端测试**：启动游戏，按 F10，确认 BMP 显示游戏画面（非 psychedelic 色），EXR ~15–25 MB，游戏帧率明显改善
- [ ] 观察 ReShade log 中 `FC: save queue full, dropping frame` 是否出现（若出现说明 worker 跟不上 30fps，需考虑降 fps 或进一步优化）
- [ ] 决定是否保留 `reshade/` 源码目录（6.7.3.16 UNOFFICIAL，体积大，现在确实在用）
- [ ] 后续 ML 训练所需的 addon/shader 定制

## Failed Approaches (Don't Repeat These)

1. **watcher 线程监控游戏目录 + shutil.move**：当游戏目录与 dataset 目录跨磁盘时 move = copy+delete，极慢；即使同盘也有 100ms poll + 50ms 稳定性等待。已改为 addon 直接写目标目录。

2. **每帧 create_resource/destroy_resource staging buffer**：GPU 内存分配代价高，每帧两次。已改为 stored_buffers_inst 内预分配，按需重建。

3. **两次 wait_idle()**：saveColorBMP 和 saveImage 各自调用一次，每次清空整条 GPU 流水线。已合并为单次。

4. **EXR PIZ 压缩在 render 线程同步执行**：PIZ 是 CPU 密集型波形压缩，100-500ms/帧，直接阻塞游戏。已移到异步 worker + 改用 ZIP。

5. **`TutorialProgress=4` 写在 `[GENERAL]`**：ReShade 只从 `[OVERLAY]` 读，写到 `[GENERAL]` 静默忽略，横幅持续显示。现在写到 `[OVERLAY]`。

6. **`capture_screenshot()` + 6.7.3 DLL**：R10G10B10A2 swap chain 下返回 ExportTex 数据（psychedelic 色），非游戏画面。改用 UIRemove_ColorTex。

7. **5.9.2 DLL + ini 抑制 splash**：5.9.2 没有任何 ini key 能关 splash，hardcoded。必须用 6.7.3。

8. **旧 v1 addon API headers（reshade-addons/deps/reshade/include/）与 6.7.3 DLL 组合**：RESHADE_API_VERSION 不匹配（1 vs 20），`register_addon()` 返回 FALSE，addon 静默不加载。必须用 `reshade/include/`（v20）。

## Key Decisions

| Decision | Rationale |
|----------|-----------|
| `--mode custom` = `dist/dxgi.dll` (6.7.3) | 唯一零 splash 方案 |
| BMP via `UIRemove_ColorTex` | 6.7.3 的 capture_screenshot 在 R10G10B10A2 上损坏 |
| `fc_output_dir.txt` sidecar | addon 运行时（游戏进程）无法接收 Python 参数，用文件传路径 |
| 异步 save worker，MAX_QUEUE=4 | render 线程返回时间从 200ms+ → memcpy 时间；队列满时 drop+log 而非阻塞 |
| EXR ZIP vs PIZ | 速度 ~4x，文件略大，对 ML 训练无影响 |
| staging buffer 预分配在 stored_buffers_inst | 按 runtime 生命周期管理，on_destroy_effect_runtime 时销毁 |
| `TutorialProgress=4` 在 `[OVERLAY]` | ReShade 源码只在此 section 读这个 key |
| Technique 顺序锁定：DepthToAddon → UIRemove | DepthToAddon 写自定义 RT；UIRemove 最后运行，snapshot 原始 BackBuffer |

## Current State

**Working**（编译干净，未实机验证）：
- `dist/dxgi.dll` — 6.7.3，5.44 MB，零 splash
- `dist/frame_capture.addon` — v20 API，async save worker，单次 wait_idle，预分配 staging
- `shaders/UIRemove.fx` — ExportColor pass → UIRemove_ColorTex，RestoreBackBuffer pass → swap chain
- `main.py launch --mode custom` 部署 + 启动游戏 + 采集 + 自动打包 HDF5
- `main.py deploy --clean` 先清理旧部署再重新部署

**`--mode official592`** 仍可用（5.9.2 DLL，有 splash，`capture_screenshot` 正确）。

## Files to Know

| File | Why It Matters |
|------|----------------|
| `reshade-addons/99-frame_capture/frame_capture.cpp` | 整个 addon。async save worker、staged buffer 预分配、on_reshade_present 热路径 |
| `shaders/UIRemove.fx` | 两 pass：ExportColor → UIRemove_ColorTex，RestoreBackBuffer → swap chain |
| `shaders/DepthToAddon.fx` | 暴露 DepthToAddon_ExportTex（RGBA32F：depth in alpha channel）|
| `main.py` | CLI。`_sources()` 按 mode 选 DLL/addon；`_ensure_addon_enabled()` 写 ReShade.ini；`cmd_capture` 自动 pack |
| `tools/capture/capture_all.py` | 采集主循环。写 fc_output_dir.txt sidecar，两线程：input(120Hz) + capture(F10) |
| `tools/capture/pack_hdf5.py` | HDF5 打包。文件名格式 A：`*.exe YYYY-MM-DD HH-MM-SS mmm BackBuffer.bmp` |
| `tools/capture/config.py` | 机器相关路径：GAME_PATH、DATASET_ROOT |
| `dist/dxgi.dll` | 6.7.3 UNOFFICIAL binary。**不要用 capture_screenshot()** |
| `vendor/reshade592/dxgi.dll` | 官方 5.9.2。capture_screenshot 正确但有 splash |
| `reshade/include/` | v20 addon API headers，frame_capture.cpp 用这里的 |

## Code Context

**on_reshade_present 热路径（简化）：**
```cpp
static void on_reshade_present(effect_runtime* runtime) {
    // 1. 检查队列是否满（MAX_QUEUE=4），满则 drop+log
    // 2. 读 fc_output_dir.txt → out_dir（回退到游戏目录）
    // 3. 确保 color_staging/depth_staging 已分配（按需重建）
    // 4. GPU: copy color texture → color_staging
    //    GPU: copy depth texture → depth_staging（若 enableDepthExp）
    // 5. queue->wait_idle()  ← 单次 GPU sync
    // 6. map + memcpy（去 D3D12 256字节 pitch 对齐）→ SaveTask
    // 7. enqueue → notify worker，render thread 返回
}
```

**SaveTask 结构：**
```cpp
struct SaveTask {
    std::filesystem::path bmp_path;
    std::vector<uint8_t>  color_pixels;   // RGBA8, W*H*4, 无 pitch padding
    uint32_t              width, height;
    std::filesystem::path depth_path;     // 空 = 跳过 depth
    std::vector<float>    depth_pixels;   // RGBA32F, W*H*4, depth 在 alpha(component 3)
    uint32_t              depth_w, depth_h;
};
```

**Worker thread（save_worker_fn）：**
```cpp
// stbi_write_bmp(bmp_path, W, H, 4, color_pixels.data())
// depth: for each pixel, d = depth_pixels[i*4+3]; rgb[i*3..i*3+2] = d
// SaveEXR(rgb.data(), W, H, depth_path, false)  // ZIP compression
```

**capture_all.run() sidecar 机制：**
```python
sidecar = watch_dir / "fc_output_dir.txt"
sidecar.write_text(str(frames_dir), encoding="utf-8")
# ... 采集 ...
sidecar.unlink(missing_ok=True)
```

**ReShade.ini 关键 keys（_ensure_addon_enabled 写入）：**
```ini
[ADDON]
FC_EnableCapture = 1
FC_ExportDepth   = 1
FC_ExportNormal  = 0

[OVERLAY]
ShowScreenshotMessage = 0
TutorialProgress = 4      ; ← 必须在 [OVERLAY]，不是 [GENERAL]

[INPUT]
KeyScreenshot = 0,0,0,0
```

**_sources() — 各 mode 部署哪些文件：**
```python
if mode == "custom":
    return dist/"dxgi.dll", dist/"frame_capture.addon", shader_src, True
if mode == "official592":
    return vendor/"reshade592/dxgi.dll", vendor/"addon_official/frame_capture.addon", shader_src, True
```

## Resume Instructions

1. **删除旧 ReShade.ini**（清理 5.9.2 时代的 stale 配置）：
   ```powershell
   Remove-Item "E:\games\ff7remake\End\Binaries\Win64\ReShade.ini" -Force
   ```

2. **Deploy + 启动游戏**：
   ```powershell
   uv run main.py launch --clean --game-path "E:\games\ff7remake\End\Binaries\Win64\ff7remake_.exe"
   ```

3. **游戏内按 F9** 开始采集，**按 F10** 触发一帧捕获。

4. **验证：**
   - `frames/` 目录出现 `*BackBuffer.bmp`（显示游戏画面，非 psychedelic 色）
   - `*DepthBuffer.exr` 约 15–25 MB
   - 游戏帧率明显改善（render 线程不再阻塞在文件 I/O）
   - ReShade log 中无 `save queue full, dropping frame`（若有，考虑降 --fps 或检查磁盘速度）
   - 采集结束后自动生成 `dataset.h5`

5. **若 BMP 颜色错误**：检查 ReShade log 中 `FC: listing all effect texture variables` 后是否出现 `UIRemove_ColorTex`；检查 `ReShadePreset.ini` 中 `UIRemove@UIRemove.fx` 是否在 Techniques= 列表且排在 DepthToAddon 之后。

6. **如果 addon 不加载**（无 FC log 输出）：确认 `dist/frame_capture.addon` 是最新编译版本（`scripts\build.ps1`）；检查 `ReShade.log` 中是否有 API version mismatch。

## Setup Required

- VS 2022 Build Tools（仅 addon 重新编译时需要）
- `uv sync`（Python 依赖）
- 游戏路径：`E:\games\ff7remake\End\Binaries\Win64\ff7remake_.exe`

## Warnings

- **不要用 `capture_screenshot()` + `dist/dxgi.dll`（6.7.3）**：R10G10B10A2 下返回 ExportTex 数据，非游戏画面。
- **不要用 `vendor/reshade592/dxgi.dll`** 期望零 splash：5.9.2 splash hardcoded。
- **不要用 `reshade-addons/deps/reshade/include/`（v1 API）** 配合 6.7.3 DLL：API version mismatch，addon 静默不加载。
- **`TutorialProgress` 必须在 `[OVERLAY]`**，写到 `[GENERAL]` 被静默忽略。
- **UIRemove 必须排在 DepthToAddon 之后**（Techniques= 顺序）。
- **`reshade/deps/glad/target/`** 内有 force-add 的预生成 C headers，不要删除。
- **save worker MAX_QUEUE=4**：若 worker 跟不上，帧会被丢弃并写 log warning，不会阻塞 render loop。
