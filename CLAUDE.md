# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## What This Repo Does

**unicap** is a game capture pipeline for DX12 games. It injects ReShade via a `dxgi.dll` proxy, triggers frame captures (color BMP + depth/normal EXR) at a fixed FPS using F10 keypresses, and records synchronized keyboard/mouse/gamepad input. The output is packed into an HDF5 dataset for ML training.

## Build

Requires Visual Studio 2022 (MSBuild v143) and CMake ≥ 3.20.

```powershell
scripts\build.ps1          # configure (first run) + build
scripts\build.ps1 -Rebuild # force-rebuild ReShade core too
```

Outputs to `dist/`:
- `dxgi.dll` — ReShade core (DX12/DXGI proxy)
- `frame_capture.addon` — capture addon
- `reshade-shaders/Shaders/*.fx` — DepthToAddon + UIRemove shaders

Delete `build\` to force CMake reconfigure.

## Run

```powershell
uv sync                                    # install Python deps (first time)

uv run main.py launch --mode custom        # deploy + launch game + capture
uv run main.py deploy --game-dir PATH      # deploy files only
uv run main.py capture                     # capture only (game already running)
uv run main.py pack                        # pack last session into HDF5
```

`launch` deploys artifacts, starts the game exe, then waits for **F9** (configurable via `--start-key`) pressed in-game before starting capture. Each capture session writes to timestamped paths (`frames_YYYYMMDD_HHMMSS/`, `inputs_YYYYMMDD_HHMMSS.jsonl`). The suggested `pack` command with matching paths is printed at session end.

Machine-specific paths live in `tools/capture/config.py` — edit `GAME_WIN64`, `GAME_EXE`, and `DATASET_ROOT` for each machine.

## Architecture

### C++ layer — `reshade-addons/99-frame_capture/frame_capture.cpp`

ReShade addon compiled to `frame_capture.addon`. On each F10 press (`VK 0x79`), it:
1. Captures the back buffer as BMP via `runtime->capture_screenshot()`
2. Optionally copies the depth/normal EXR textures exposed by `DepthToAddon.fx` (via `DepthToAddon_ExportTex` texture variable)
3. Saves all files to the game's working directory (same folder as the `.exe`)

Settings (`FC_EnableCapture`, `FC_ExportDepth`, `FC_ExportNormal`) default to `true` and are persisted in ReShade's `.ini` config via `config_get_value` / `config_set_value`.

**Important:** `frame_capture.cpp` includes headers from `reshade-addons/deps/reshade/include` (older v5 wrapper API: `reshade::log_message`, `reshade::config_get_value`), not from `reshade/` itself. Do not change this include path — the compiled addon is binary-compatible with `vendor/reshade592/dxgi.dll`.

### ReShade core — `reshade/` and `vendor/reshade592/`

**`vendor/reshade592/dxgi.dll`** — official 5.9.2 binary. This is what `--mode custom` and `--mode official592` both deploy. It correctly handles R10G10B10A2 swap chains in `capture_screenshot`.

**`reshade/`** — contains 6.7.3.16 UNOFFICIAL source. `dist/dxgi.dll` built from it produces wrong BMP on R10G10B10A2 swap chains and is **not deployed by any mode**. The CMake `reshade_core` target exists as infrastructure but its output is unused.

`reshade/deps/glad/target/` contains pre-generated C headers that are excluded by glad's own `.gitignore` but are **force-added** to this repo (`git add -f`). Do not delete them.

### Shader — `murchFX/Shaders/DepthToAddon.fx`

Runs as a ReShade effect. Exposes the game's depth and normal buffers as `DepthToAddon_ExportTex` / `DepthToAddon_DepthTex` / `DepthToAddon_NormalTex` texture variables that `frame_capture.cpp` reads.

### Python pipeline — `tools/capture/`

Three concurrent threads in `capture_all.py`:
- **capture thread** — sends F10 keypresses at the target FPS using `keybd_event`
- **watcher thread** — polls the game directory for new `.bmp`/`.exr` files and moves them to `frames_<tag>/`
- **input thread** — samples keyboard (`GetKeyboardState`), mouse (`GetCursorPos`), and XInput gamepad at 120 Hz; writes to `inputs_<tag>.jsonl` on stop

`pack_hdf5.py` aligns frames and inputs by timestamp and writes `/color`, `/depth`, `/normal`, `/kb`, `/mouse`, `/gamepad` arrays into HDF5.

### CMake structure

`CMakeLists.txt` defines three targets:
1. `reshade_core` (ExternalProject, MSBuild) → `dist/dxgi.dll` (unused; reshade/ is 6.7.3 UNOFFICIAL)
2. `frame_capture` (shared library, MSVC) → `dist/frame_capture.addon` — **this is the primary build output**
3. `shaders` (custom target, always runs) → copies `.fx` files to `dist/reshade-shaders/Shaders/`

## Key Files

| File | Role |
|------|------|
| `tools/capture/config.py` | All machine-specific paths — edit here for new machines |
| `reshade-addons/99-frame_capture/frame_capture.cpp` | Entire capture addon (single file) |
| `CMakeLists.txt` | Full build definition |
| `scripts/build.ps1` | Build entry point |
| `main.py` | Python CLI: deploy / launch / capture / pack |
