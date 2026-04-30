# Handoff: unicap pipeline — 最小化游戏目录 + ReShade 重命名完成

**Generated**: 2026-04-30
**Branch**: master (up to date with origin)
**Status**: 所有代码变更完成，待端到端验证

## Goal

FF7 Remake (DX12, R10G10B10A2_UNORM) 帧采集管线：F9 触发采集 → `*BackBuffer.bmp` + `*DepthBuffer.exr`，零 ReShade UI/splash，游戏目录最小化（仅 dxgi.dll 一个文件），配置/日志全部写 `%TEMP%\unicap\`。

## Completed

- [x] 6.7.3 DLL (`dist/dxgi.dll`) — 零 splash，UIRemove_ColorTex 路径拿 BMP（绕过 capture_screenshot 的 R10G10B10A2 bug）
- [x] addon 直接写入目标 `frames_dir`（通过 `fc_output_dir.txt` sidecar），无 watcher/move
- [x] 异步 save worker + staging buffer 预分配 + 单次 wait_idle()
- [x] EXR 压缩 ZIP（非 PIZ）
- [x] **游戏目录最小化**：deploy 仅创建 `dxgi.dll` symlink（或 copy），不复制 addon/ini/shader
- [x] **ReShade 文件重命名为 unicap**：`ReShade.ini` → `unicap.ini`，`ReShade.log` → `unicap.log`
  - `reshade/source/ini_file.cpp:19` — `L"unicap.ini"`
  - `reshade/source/dll_main.cpp:64` — `L"unicap.ini"`
  - `reshade/source/runtime_gui.cpp:1690` — `L"unicap.ini"`
  - `reshade/source/runtime_manager.cpp:23` — `config_name = "unicap"`（关键：使 runtime config = global config = unicap.ini）
- [x] **UNICAP_TEMP** (`%TEMP%\unicap`)：`unicap.ini`、`unicap.log`、`unicap.log1` 全写这里
  - `RESHADE_BASE_PATH_OVERRIDE` env var 在 `cmd_launch` 中设置，把 ReShade base path 重定向到 UNICAP_TEMP
  - `_ensure_addon_enabled()` 显式写 `IntermediateCachePath=UNICAP_TEMP` 和 `PresetPath=config/unicapPreset.ini`
- [x] **build.ps1 -Rebuild** 修复：`-Rebuild` 时删除整个 `build\` 目录再重新 configure，绕过 ExternalProject stamp 机制问题
- [x] **preset 重命名**：`ReShadePreset.ini` → `config/unicapPreset.ini`（gitignored）
- [x] 所有改动已编译、commit（最新：见 git log）

## Not Yet Done

- [ ] **端到端测试**：启动游戏，按 F9，确认 BMP 显示游戏画面（非 psychedelic 色），EXR ~15–25 MB
- [ ] 观察 `unicap.log` 中 `FC: save queue full, dropping frame` 是否出现
- [ ] 决定是否保留 `reshade/` 源码目录（6.7.3.16 UNOFFICIAL，体积大）
- [ ] 后续 ML 训练所需的 addon/shader 定制

## Failed Approaches (Don't Repeat These)

1. **watcher 线程监控游戏目录 + shutil.move**：跨磁盘时 move = copy+delete，极慢。已改为 addon 直接写目标目录。

2. **每帧 create_resource/destroy_resource staging buffer**：GPU 内存分配代价高。已改为预分配复用。

3. **两次 wait_idle()**：已合并为单次。

4. **EXR PIZ 压缩在 render 线程**：PIZ CPU 密集，100-500ms/帧阻塞游戏。已移到 async worker + ZIP。

5. **`TutorialProgress=4` 写在 `[GENERAL]`**：ReShade 只从 `[OVERLAY]` 读，静默忽略。现在写到 `[OVERLAY]`。

6. **`capture_screenshot()` + 6.7.3 DLL**：R10G10B10A2 下返回 psychedelic 色。改用 UIRemove_ColorTex。

7. **5.9.2 DLL + ini 抑制 splash**：5.9.2 splash hardcoded，无法关。必须用 6.7.3。

8. **旧 v1 addon API headers**：RESHADE_API_VERSION 不匹配，addon 静默不加载。必须用 `reshade/include/`（v20）。

9. **复制 addon/shader/ini 到游戏目录**：游戏目录污染，文件散乱。改为仅 dxgi.dll symlink + UNICAP_TEMP。

10. **`runtime_manager.cpp` config_name = "ReShade"**：runtime config 与 global config 不一致，PresetPath 读不到，UIRemove 不加载，无 BMP。必须改为 `"unicap"`。

11. **build.ps1 -Rebuild 用 cmake -DRESHADE_ALWAYS_REBUILD=ON**：build/ 已存在时跳过 configure，flag 无效。改为删除 build/ 整个目录。

## Key Decisions

| Decision | Rationale |
|----------|-----------|
| `--mode custom` = `dist/dxgi.dll` (6.7.3) | 唯一零 splash 方案 |
| BMP via `UIRemove_ColorTex` | 6.7.3 的 capture_screenshot 在 R10G10B10A2 上损坏 |
| `fc_output_dir.txt` sidecar | addon 运行时无法接收 Python 参数，用文件传路径 |
| 异步 save worker，MAX_QUEUE=4 | render 线程返回时间从 200ms+ → memcpy 时间；队列满时 drop+log |
| EXR ZIP vs PIZ | 速度 ~4x，文件略大，对 ML 训练无影响 |
| 仅 dxgi.dll 在游戏目录 | Windows DLL 搜索顺序：dxgi.dll 必须在 app dir；其他文件无此限制 |
| UNICAP_TEMP = `%TEMP%\unicap` | 配置/日志集中管理，游戏目录保持干净 |
| `runtime_manager.cpp` config_name = "unicap" | 使 per-runtime config = global config，避免分裂 |
| `RESHADE_BASE_PATH_OVERRIDE` env var | ReShade 支持的运行时 base path 重定向机制 |
| Technique 顺序：DepthToAddon → UIRemove | DepthToAddon 写自定义 RT；UIRemove 最后运行，snapshot 原始 BackBuffer |

## Current State

**代码完成，需要实机验证**：
- `dist/dxgi.dll` — 6.7.3，已含 unicap 重命名，零 splash
- `dist/frame_capture.addon` — v20 API，async save worker，单次 wait_idle，预分配 staging
- `shaders/UIRemove.fx` — ExportColor pass → UIRemove_ColorTex，RestoreBackBuffer pass → swap chain
- `main.py launch --mode custom` — 部署（仅 symlink dxgi.dll）+ 启动游戏 + 设置 RESHADE_BASE_PATH_OVERRIDE + 采集

**`--mode official592`** 仍可用（5.9.2 DLL，有 splash，`capture_screenshot` 正确）。

## Files to Know

| File | Why It Matters |
|------|----------------|
| `reshade-addons/99-frame_capture/frame_capture.cpp` | 整个 addon |
| `reshade/source/runtime_manager.cpp` | `config_name = "unicap"` — 关键，使 runtime config = unicap.ini |
| `reshade/source/ini_file.cpp` | `global_config()` = `unicap.ini` |
| `reshade/source/dll_main.cpp` | bootstrap lookup = `unicap.ini` |
| `shaders/UIRemove.fx` | ExportColor + RestoreBackBuffer |
| `shaders/DepthToAddon.fx` | 暴露 DepthToAddon_ExportTex |
| `main.py` | CLI：`_ensure_addon_enabled()` 写 UNICAP_TEMP/unicap.ini；`cmd_launch` 设置 env |
| `tools/capture/capture_all.py` | 采集主循环，写 fc_output_dir.txt sidecar |
| `tools/capture/config.py` | 机器相关路径 |
| `scripts/build.ps1` | `-Rebuild` 删除 build\ 整个目录后重新 configure |

## Resume Instructions

1. **必须先全量重编译**（若尚未做过含 runtime_manager.cpp 修复的编译）：
   ```powershell
   scripts\build.ps1 -Rebuild
   ```
   确认 MSBuild 输出中有 `dll_main.cpp`、`ini_file.cpp`、`runtime_manager.cpp` 编译行。

2. **清理游戏目录残留的旧文件**（避免 stale 配置干扰）：
   ```powershell
   Remove-Item "E:\games\ff7remake\End\Binaries\Win64\ReShade.ini" -ErrorAction SilentlyContinue
   Remove-Item "E:\games\ff7remake\End\Binaries\Win64\ReShade.log" -ErrorAction SilentlyContinue
   Remove-Item "E:\games\ff7remake\End\Binaries\Win64\reshade-addons" -Recurse -ErrorAction SilentlyContinue
   Remove-Item "E:\games\ff7remake\End\Binaries\Win64\reshade-shaders" -Recurse -ErrorAction SilentlyContinue
   ```

3. **Deploy + 启动游戏**：
   ```powershell
   uv run main.py launch --mode custom
   ```

4. **游戏内按 F9** 开始采集（持续 10 秒，`--duration` 默认值）。

5. **验证**：
   - `%TEMP%\unicap\unicap.ini` 存在（含 `AddonPath`、`EffectSearchPaths`、`IntermediateCachePath` 等）
   - `%TEMP%\unicap\unicap.log` 存在，包含 `FC:` 开头的 addon 日志
   - `frames/` 目录出现 `*BackBuffer.bmp`（显示游戏画面，非 psychedelic 色）
   - `*DepthBuffer.exr` 约 15–25 MB
   - 采集结束后自动生成 `dataset.h5`

6. **若 BMP 颜色错误**：检查 `unicap.log` 中 `FC: listing all effect texture variables` 后是否出现 `UIRemove_ColorTex`；确认 `config/unicapPreset.ini` 中 `UIRemove@UIRemove.fx` 在 Techniques= 列表。

7. **若 addon 不加载**（无 FC log）：确认 `unicap.ini` 中 `[ADDON] AddonPath` 指向 `dist/`；检查 `unicap.log` 中 API version mismatch。

## Setup Required

- VS 2022 Build Tools（重编译时需要）
- `uv sync`（Python 依赖）
- 游戏路径：`E:\games\ff7remake\End\Binaries\Win64\ff7remake_.exe`

## Warnings

- **不要用 `capture_screenshot()` + `dist/dxgi.dll`（6.7.3）**：R10G10B10A2 下返回 psychedelic 色。
- **不要用 `vendor/reshade592/dxgi.dll`** 期望零 splash：5.9.2 splash hardcoded。
- **不要用 v1 addon API headers**（`reshade-addons/deps/reshade/include/`）：API mismatch，addon 静默不加载。
- **`TutorialProgress` 必须在 `[OVERLAY]`**，写到 `[GENERAL]` 被静默忽略。
- **UIRemove 必须排在 DepthToAddon 之后**（Techniques= 顺序）。
- **`reshade/deps/glad/target/`** 内有 force-add 的预生成 C headers，不要删除。
- **ff7remake_.exe 是两进程启动器**：第一个进程 ~2s 退出，第二个进程才是真正的 DX12 进程；两个进程都会加载 dxgi.dll 并写同一个 unicap.log（顺序 rotation）。
- **`-Rebuild` 删除 build\**：rebuild 后需要重新 configure（cmake）+ 完整 build，时间较长。
