# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## What This Repo Does

**unicap** is a game capture pipeline for DX12 games. It injects ReShade via a `dxgi.dll` proxy, captures color BMP + depth/normal EXR at a fixed FPS, and records synchronized keyboard/mouse/gamepad input. Output is packed into an HDF5 dataset for ML training. The primary target is FF7 Remake (DX12/UE4).

## Build

Requires Visual Studio 2022 (MSBuild v143) and CMake ≥ 3.20.

```powershell
scripts\build.ps1          # configure (first run) + build
scripts\build.ps1 -Rebuild # force-rebuild ReShade core too
```

Outputs to `dist/`:

- `dxgi.dll` — ReShade core (DX10/11/12 / DXGI proxy)，built from `reshade/` source；`--api dx`(默认) 时由 `cmd_deploy` symlink 到游戏目录（无 Windows 开发者模式时退化为 copy）
- `UniCap64.dll` — same DLL bytes as dxgi.dll，作 Vulkan implicit layer 用；`--api vulkan` 时通过 `VK_IMPLICIT_LAYER_PATH` env var 注入到游戏子进程（不修改游戏目录）
- `UniCap64.json` — Vulkan layer manifest（源在 `reshade-addons/UniCap64.json`），库名 `VK_LAYER_unicap`
- `frame_capture.addon` — capture addon (primary build output)；注册 `on_bind_rts_dsv`(DX 经典) + `on_begin_render_pass`(DX12 enhanced + Vulkan render pass) 两条 capture 路径
- `unicap-shaders/Shaders/*.fx` — DepthToAddon + BackBufferExport (legacy: UIRemove) shaders (copied from `shaders/`)

Delete `build\` to force CMake reconfigure.

## Run

```powershell
uv sync                                         # install Python deps (first time)

uv run main.py launch                           # primary flow: deploy + launch + F8/F9 loop
uv run main.py launch --ui-mode ui              # capture post-UI BackBuffer only (no survey)
uv run main.py launch --ui-mode both            # both pre-UI and post-UI streams (needs survey)
uv run main.py launch --api vulkan              # Vulkan-only games (DOOM 2016/Eternal etc.)
uv run main.py video  --game-dir DIR            # encode frames → MP4 (post-hoc, batch)
uv run main.py pack   --game-dir DIR [--no-depth]  # pack frames + inputs → HDF5 (post-hoc, batch)
```

`--api` 默认 `auto`（按 exe 名启发：含 `vk`/`vulkan` 子串 → vulkan，否则 dx）。DOOM 2016 之类 exe 名不带 vk 标记的 Vulkan-only 游戏必须显式 `--api vulkan`，否则走 DX 路径会在 F8 自动 survey 时静默 timeout。

**id Tech 7 / DOOM Eternal 类 compute-based 引擎**：`begin_render_pass` 只在 HUD 合成时触发，render-pass 路径取不到干净 pre-UI scene。我们尝试过 `on_barrier` hook 路线但 DOOM Eternal 实测 freeze（多线程 cmd-buffer recording + transient memory aliasing 风险大）。**实用方案**：`--ui-mode ui` 抓 post-UI BackBuffer，配合深度图后处理（depth==0 = UI 像素 → 置黑），见下方 `--mask-ui`。

**Vulkan 部署机制**：不修改游戏目录，通过游戏子进程的 env vars 注入：`VK_IMPLICIT_LAYER_PATH=<dist>` (loader ≥1.3.234 优先) + `VK_INSTANCE_LAYERS=VK_LAYER_unicap` + `VK_LAYER_PATH=<dist>` (老 loader fallback)。Layer DLL = `dist/UniCap64.dll`，manifest = `dist/UniCap64.json`（源 `reshade-addons/UniCap64.json`，重命名 + 自定义 layer name 以去 ReShade 品牌）。**全部副作用都在子进程范围内**，unicap 主进程退出后无残留（不写注册表）。

`--ui-mode` controls what gets captured:

| mode | survey 需求 | output BMPs                            | HDF5                  |
| ---- | --------- | -------------------------------------- | --------------------- |
| `no-ui` (default) | F8 首次自动跑 | `<ts> BackBuffer.bmp` (pre-UI)         | `/color` (--bmp no-ui) |
| `ui`              | 不需要       | `<ts> BackBuffer.bmp` (post-UI BB)     | `/color` (--bmp ui)   |
| `both`            | F8 首次自动跑 | both `BackBuffer.bmp` + `BackBufferUI.bmp` | `/color` 由 --bmp 选 |

The addon is driven by two ini keys: `FC_PreUICapture` (1 = scene RT, 0 = post-UI BB) and `FC_BothCapture` (1 = also dump post-UI BMP alongside scene RT). `_ensure_addon_enabled` writes both based on `--ui-mode`.

Deploy + survey + capture are no longer separate subcommands — they all happen inside `launch` (deploy on startup; survey/capture driven by F8/F9 in-game).

`launch` is the canonical flow. It deploys, starts the game, then enters an interactive
loop driven entirely by in-game hotkeys:

| Key                     | Action                                                                                             |
| ----------------------- | -------------------------------------------------------------------------------------------------- |
| **F8**                  | Start a capture session — if no `recommended_skip.txt` exists yet, runs survey first then captures |
| **F9**                  | Stop the current survey or capture                                                                 |
| **Ctrl+C** (in console) | Exit `main.py` (game keeps running)                                                                |

要重做 survey：删 `DATASET_ROOT/<game>/survey/recommended_skip.txt`，下次 F8 会重跑 survey。

Each capture session writes to `DATASET_ROOT/<game_name>/<YYYYMMDD_HHMMSS>/frames/` with a matching `inputs.jsonl`. F9 停止后默认只生成 `video.mp4`；HDF5 打包需 `launch --pack` 显式开启，或事后用 `pack --game-dir DIR` 子命令批量补齐。`video` / `pack` 子命令都是"扫游戏目录、缺啥补啥、已存在跳过"。

Capture defaults (FPS=30, 1920×1080) 是 `main.py` 顶部常量；1920×1080 匹配 FF7R 的 scene RT 原生分辨率，省掉一次 worker resize（参考 perf commit b7021ed → 19.4 fps）。

Machine-specific paths live in `tools/capture/config.py` — edit `GAME_PATH` and `DATASET_ROOT` there. Both can also be overridden via `--game-path` and `--dataset-root`.

## Architecture

### C++ layer — `reshade-addons/99-frame_capture/frame_capture.cpp`

ReShade addon compiled to `frame_capture.addon`. It captures at `FC_TargetFPS` using an internal timer (not keyboard input). Two capture paths:

**Standard path**: `runtime->capture_screenshot()` saves BackBuffer as BMP directly.

**Pre-UI path** (`FC_PreUICapture=1`): Hooks `on_bind_rts_dsv` (DX classic) + `on_begin_render_pass` (DX12 enhanced + Vulkan render pass). Reverse-skip math: `target = (prev_total - 1 - FC_PreUISkipCount)` selects the Nth-from-last non-BB no-DSV pass within the frame. That RT's color is GPU-copied to `g_pre_ui_staging`. `on_reshade_present` decodes `g_pre_ui_staging` to RGBA8 (handling `r16g16b16a16_float` HDR via half-float → Reinhard → sRGB) and saves as BMP.

Settings (`FC_EnableCapture`, `FC_ExportDepth`, `FC_PreUICapture`, `FC_PreUISkipCount`, `FC_TargetFPS`, `FC_BothCapture`) are read from `%TEMP%\unicap\unicap.ini` via `config_get_value`. `FC_BothCapture=1` 让 addon 同时落 pre-UI BMP + post-UI `BackBufferUI.bmp`（驱动 `--ui-mode both`）。

### `--mask-ui` (post-process UI mask)

`--mask-ui`（同时存在于 `launch` 和 `video` 子命令）从 sibling DepthBuffer.exr 读深度，把 `depth <= 0 OR depth >= 0.999` 的像素（reverse-Z 下的 UI/sky）在颜色帧上置黑后再编码 → 生成 `video_masked.mp4`（与 `video.mp4` 并存，不替换）。**注意**：DepthToAddon.fx 导出已 reverse-Z flip + 线性化，所以 UE4/UE5/id Tech 7 都是 sky/UI 像素 = 1.0 不是 0.0。**id Tech 7 (DOOM Eternal) HUD 是真 3D 几何**（小三角面绘制在近平面），depth mask 抓不到 → 现实使用上 mask 主要干掉 sky，HUD 靠模型自学忽略。

`pack` 子命令的 `--bmp {no-ui,ui}`（默认 no-ui）选哪种 BMP 进 `/color`：no-ui=BackBuffer.bmp，ui=BackBufferUI.bmp 优先（不存在 fallback BackBuffer.bmp）。Pack **不再**做 depth-based UI mask（引擎相关、效果差），HDF5 里 `/color` 是原图，`/depth` 完整保留。

**Important:** `frame_capture.cpp` includes headers from `reshade-addons/deps/reshade/include` (v5 wrapper API). Do not change this include path — the addon's exported symbols target the v5 ABI and remain compatible with `dist/dxgi.dll` built from the 6.7.3.16 source.

### Sidecar file protocol (Python ↔ C++ runtime)

The addon reads/writes sidecar files from the game exe's directory on every `on_reshade_present`:

| File                | Direction    | Purpose                                                                                                                                                                                             |
| ------------------- | ------------ | --------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| `fc_output_dir.txt` | Python → C++ | Redirect frame output to this directory                                                                                                                                                             |
| `fc_skip_count.txt` | Python → C++ | Survey mode: Python writes target skip; C++ reads it next frame (1-frame lag). Also used as a one-shot pulse after survey to update `g_pre_ui_skip` to the recommended value before capture starts. |
| `fc_pass_total.txt` | C++ → Python | Survey mode: C++ writes `s_no_dsv_non_bb` (non-BB pass count for current frame)                                                                                                                     |
| `fc_state.txt`      | Python → C++ | High-level state: `idle` / `surveying` / `capturing`. Drives addon overlay color + label.                                                                                                           |
| `fc_hints.txt`      | Python → C++ | `1`/`0` — whether the addon overlay shows hotkey hints (default 1)                                                                                                                                  |

When `fc_skip_count.txt` exists and is non-empty, the addon enters survey mode: filenames become `survey_skip_NNN_BackBuffer.bmp` where NNN is the skip value **that was used this frame** (before reading the new sidecar value).

After a survey completes, Python writes the recommended skip to `fc_skip_count.txt` for ~2 frames so the addon picks it up, then deletes the file. This makes the new skip take effect mid-game without requiring a restart, while restoring normal capture filenames for the upcoming session.

### ReShade core — `reshade/` → `dist/dxgi.dll`

`reshade/` contains 6.7.3.16 UNOFFICIAL source. The CMake `reshade_core` ExternalProject target builds it via MSBuild and stages `dist/dxgi.dll`, which `main.py` deploys to the game directory. Tested on FF7R. Note: this build mishandles R10G10B10A2 swap chains; if a future game produces wrong-color BMPs, switch the source to a different ReShade build (no automatic fallback exists).

`reshade/deps/glad/target/` contains pre-generated C headers excluded by glad's own `.gitignore` but **force-added** to this repo (`git add -f`). Do not delete them.

### Shaders

`shaders/` is the canonical runtime directory (pointed to by `EffectSearchPaths` in `unicap.ini`):

- `DepthToAddon.fx` — exposes `DepthToAddon_ExportTex` / `DepthToAddon_DepthTex` / `DepthToAddon_NormalTex` texture variables that `frame_capture.cpp` reads
- `BackBufferExport.fx` — passthrough copy of BackBuffer into `BackBufferExport_ColorTex` for the addon to read (post-UI capture path / both-mode). Does NOT mask UI despite the legacy "UIRemove" name it inherited.
- `ReShade.fxh` — ReShade standard include

`murchFX/Shaders/` is a sibling FX library (ChannelMixer, DoubleExposure, its own DepthToAddon copy). It is **not** what gets loaded at runtime.

### Python pipeline — `tools/capture/`

**`capture_all.py`** — two threads:

- **input thread** — samples keyboard (`GetKeyboardState`), mouse (`GetCursorPos`), XInput gamepad at 120 Hz; writes `inputs.jsonl` on stop
- **main thread** — writes `fc_output_dir.txt` so the addon writes frames directly to `frames/`; monitors frame count; stops when external `stop_event` is set (F9 watcher in `main.py`) or optional `duration` elapses

The addon handles all timing and frame output; `capture_all.py` only records inputs and monitors progress.

**`main.py`** — owns the interactive loop. Uses `GetAsyncKeyState` (foreground-agnostic — polls globally) to poll **F8** / **F9**. State machine: idle ↔ surveying ↔ capturing. Each transition writes `fc_state.txt` so the addon overlay reflects the current phase. F9 sets the `stop_event` shared with `capture_all.run` / the abort flag passed into `survey_mod.run`.

**`survey.py`** — auto-detects the correct `FC_PreUISkipCount` value for a game:

1. Probe frame (skip=0): writes sidecar, waits for `survey_skip_000_BackBuffer.bmp`, reads `fc_pass_total.txt` to learn pass count
2. Sweep from `total-1` to `0` by step, waiting for each named BMP
3. `_find_boundary()`: groups adjacent-frame diffs into stable/unstable segments (threshold = 3× median diff); discards upper-half segments (early empty scene); returns min `s_lo` of the lowest stable segment (= last clean frame before UI compositing)

**`pack_hdf5.py`** — aligns frames and inputs by timestamp; writes `/color`, `/depth`, `/normal`, `/frame_ts`, `/kb`, `/mouse`, `/gamepad` arrays to HDF5.

### CMake structure

`CMakeLists.txt` defines three targets:

1. `reshade_core` (ExternalProject, MSBuild) → `dist/dxgi.dll` (unused)
2. `frame_capture` (shared library, MSVC, CXX17) → `dist/frame_capture.addon`
3. `shaders` (custom target, always runs) → copies `.fx` files to `dist/unicap-shaders/Shaders/`

## Dataset output layout

```
DATASET_ROOT/
  <game_name>/
    <YYYYMMDD_HHMMSS>/   ← one per launch/capture session
      frames/            ← BMP + optional EXR pairs
      inputs.jsonl
      dataset.h5
      video.mp4
      video_ui.mp4       ← 仅 --ui-mode both 时生成（post-UI 流）
    survey/              ← survey scan frames (fixed subdir)
      survey_skip_000_BackBuffer.bmp
      survey_skip_007_BackBuffer.bmp
      ...
```

## Runtime logs

Both ReShade core and the addon write to `%TEMP%\unicap\` (i.e. `C:\Users\<user>\AppData\Local\Temp\unicap\`):

- `unicap.log` — log of the first dxgi.dll-loaded process (often a short-lived launcher/stub).
- `unicap.log1` — log of the actual long-running game process. **This is the one with the useful diagnostics** (capf frames, FC warnings, shader compile messages).
- `unicap.ini` — runtime config the addon reads.
- `unicap-*.{i,asm,cso}` — shader compile cache (commit 09863dd 改前缀 `reshade-` → `unicap-`，与项目命名一致)。看到 `reshade-*.{i,asm,cso}` 说明部署的 `dxgi.dll` 还是旧版，需 `scripts\build.ps1 -Rebuild` 重生成。

When debugging capture issues, default to reading `unicap.log1` first.

## Key Files

| File                                                | Role                                                    |
| --------------------------------------------------- | ------------------------------------------------------- |
| `tools/capture/config.py`                           | All machine-specific paths — edit here for new machines |
| `reshade-addons/99-frame_capture/frame_capture.cpp` | Entire capture addon (single file, ~1100 LoC)           |
| `tools/capture/survey.py`                           | Pre-UI skip auto-detection: sweep + boundary algorithm  |
| `main.py`                                           | Python CLI: survey / deploy / launch / capture / pack   |
| `CMakeLists.txt`                                    | Full build definition                                   |
| `scripts/build.ps1`                                 | Build entry point                                       |
| `shaders/DepthToAddon.fx`                           | Depth/normal buffer export shader (runtime canonical)   |

## 任何输出要么使用英文，要么使用中文，优先使用中文，不要使用其他语言
