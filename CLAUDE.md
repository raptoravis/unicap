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

- `dxgi.dll` — ReShade core (DX12/DXGI proxy); built from `reshade/` source but **not deployed** (see ReShade core section)
- `frame_capture.addon` — capture addon (primary build output)
- `reshade-shaders/Shaders/*.fx` — DepthToAddon + UIRemove shaders (copied from `shaders/`)

Delete `build\` to force CMake reconfigure.

## Run

```powershell
uv sync                                         # install Python deps (first time)

uv run main.py launch                           # primary flow: deploy + launch + F6/F8/F9 loop
uv run main.py video  --frames-dir PATH ...     # encode frames → MP4 (post-hoc)
uv run main.py pack   --frames-dir PATH ...     # pack frames + inputs → HDF5 (post-hoc)
```

Deploy + survey + capture are no longer separate subcommands — they all happen inside `launch` (deploy on startup; survey/capture driven by F6/F8/F9 in-game).

`launch` is the canonical flow. It deploys, starts the game, then enters an interactive
loop driven entirely by in-game hotkeys:

| Key                     | Action                                                                                             |
| ----------------------- | -------------------------------------------------------------------------------------------------- |
| **F6**                  | Run survey (auto-scan pre-UI skip values, write `recommended_skip.txt`)                            |
| **F8**                  | Start a capture session — if no survey recommendation exists yet, runs survey first, then captures |
| **F9**                  | Stop the current survey or capture                                                                 |
| **Ctrl+C** (in console) | Exit `main.py` (game keeps running)                                                                |

Each capture session writes to `DATASET_ROOT/<game_name>/<YYYYMMDD_HHMMSS>/frames/` with a matching `inputs.jsonl`. After F9 stops capture, packing + video generation run automatically; pressing F8 again starts a new session.

Capture defaults (FPS=30, 1600×1200) are constants in `main.py` — edit there to change.

Machine-specific paths live in `tools/capture/config.py` — edit `GAME_PATH` and `DATASET_ROOT` there. Both can also be overridden via `--game-path` and `--dataset-root`.

## Architecture

### C++ layer — `reshade-addons/99-frame_capture/frame_capture.cpp`

ReShade addon compiled to `frame_capture.addon`. It captures at `FC_TargetFPS` using an internal timer (not keyboard input). Two capture paths:

**Standard path**: `runtime->capture_screenshot()` saves BackBuffer as BMP directly.

**Pre-UI path** (`FC_PreUICapture=1`): Hooks `on_bind_rts_dsv` to intercept render target bindings. Uses reverse-skip: `target = (prev_total - 1 - FC_PreUISkipCount)` selects the Nth-from-last non-BB, no-DSV RT bind within the frame. That RT's color is GPU-copied to `g_pre_ui_staging` during `on_bind_rts_dsv`. In `on_reshade_present`, the staging buffer is decoded to RGBA8 (handling `r16g16b16a16_float` HDR via half-float → Reinhard → sRGB) and saved as BMP. This captures the scene before UI compositing without touching the BackBuffer during Present.

Settings (`FC_EnableCapture`, `FC_ExportDepth`, `FC_PreUICapture`, `FC_PreUISkipCount`, `FC_TargetFPS`) are read from `%TEMP%\unicap\unicap.ini` via `config_get_value`.

**Important:** `frame_capture.cpp` includes headers from `reshade-addons/deps/reshade/include` (v5 wrapper API). Do not change this include path — the addon is binary-compatible with `vendor/reshade592/dxgi.dll` (5.9.2).

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

### ReShade core — `reshade/` and `vendor/reshade592/`

**`vendor/reshade592/dxgi.dll`** — official 5.9.2 binary. Both `--mode custom` and `--mode official592` deploy this. It correctly handles R10G10B10A2 swap chains.

**`reshade/`** — contains 6.7.3.16 UNOFFICIAL source. `dist/dxgi.dll` built from it produces incorrect BMP on R10G10B10A2 swap chains and is **not deployed by any mode**. The CMake `reshade_core` target exists as infrastructure but its output is unused.

`reshade/deps/glad/target/` contains pre-generated C headers excluded by glad's own `.gitignore` but **force-added** to this repo (`git add -f`). Do not delete them.

### Shaders

`shaders/` is the canonical runtime directory (pointed to by `EffectSearchPaths` in `unicap.ini`):

- `DepthToAddon.fx` — exposes `DepthToAddon_ExportTex` / `DepthToAddon_DepthTex` / `DepthToAddon_NormalTex` texture variables that `frame_capture.cpp` reads
- `UIRemove.fx` — restores the original BackBuffer to the swap chain after UIRemove_ColorTex capture
- `ReShade.fxh` — ReShade standard include

`murchFX/Shaders/` is a sibling FX library (ChannelMixer, DoubleExposure, its own DepthToAddon copy). It is **not** what gets loaded at runtime.

### Python pipeline — `tools/capture/`

**`capture_all.py`** — two threads:

- **input thread** — samples keyboard (`GetKeyboardState`), mouse (`GetCursorPos`), XInput gamepad at 120 Hz; writes `inputs.jsonl` on stop
- **main thread** — writes `fc_output_dir.txt` so the addon writes frames directly to `frames/`; monitors frame count; stops when external `stop_event` is set (F9 watcher in `main.py`) or optional `duration` elapses

The addon handles all timing and frame output; `capture_all.py` only records inputs and monitors progress.

**`main.py`** — owns the interactive loop. Uses `GetAsyncKeyState` (works while the game is foreground) to poll **F6**/**F8**/**F9**. State machine: idle ↔ surveying ↔ capturing. Each transition writes `fc_state.txt` so the addon overlay reflects the current phase. F9 sets the `stop_event` shared with `capture_all.run` / the abort flag passed into `survey_mod.run`.

**`survey.py`** — auto-detects the correct `FC_PreUISkipCount` value for a game:

1. Probe frame (skip=0): writes sidecar, waits for `survey_skip_000_BackBuffer.bmp`, reads `fc_pass_total.txt` to learn pass count
2. Sweep from `total-1` to `0` by step, waiting for each named BMP
3. `_find_boundary()`: groups adjacent-frame diffs into stable/unstable segments (threshold = 3× median diff); discards upper-half segments (early empty scene); returns min `s_lo` of the lowest stable segment (= last clean frame before UI compositing)

**`pack_hdf5.py`** — aligns frames and inputs by timestamp; writes `/color`, `/depth`, `/normal`, `/frame_ts`, `/kb`, `/mouse`, `/gamepad` arrays to HDF5.

### CMake structure

`CMakeLists.txt` defines three targets:

1. `reshade_core` (ExternalProject, MSBuild) → `dist/dxgi.dll` (unused)
2. `frame_capture` (shared library, MSVC, CXX17) → `dist/frame_capture.addon`
3. `shaders` (custom target, always runs) → copies `.fx` files to `dist/reshade-shaders/Shaders/`

## Dataset output layout

```
DATASET_ROOT/
  <game_name>/
    <YYYYMMDD_HHMMSS>/   ← one per launch/capture session
      frames/            ← BMP + optional EXR pairs
      inputs.jsonl
      dataset.h5
      video.mp4
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
