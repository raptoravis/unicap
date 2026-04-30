# Handoff: unicap pipeline — fully working, ready for customization

**Generated**: 2026-04-30
**Branch**: master (2 commits ahead of origin)
**Status**: Working — pipeline confirmed correct, ready for next development phase

## Goal

Game capture pipeline for FF7 Remake (DX12, R10G10B10A2_UNORM swap chain): each F10 press produces a correct `*BackBuffer.bmp` (game image) + `*DepthBuffer.exr` (linear depth). User wants `--mode custom` as the default so they can customize the addon (`frame_capture.cpp`) and shaders freely.

## Completed

- [x] Identified root cause of wrong BMP: `reshade/` source is **6.7.3.16/17 UNOFFICIAL** (not 5.9.2 as CMakeLists.txt claimed). Its `capture_screenshot` reads the wrong internal buffer on R10G10B10A2 swap chains, producing ExportTex-like (psychedelic/normal-map) colors in the BMP.
- [x] Fixed `--mode custom`: now deploys `vendor/reshade592/dxgi.dll` (official 5.9.2) + `dist/frame_capture.addon` (custom-compiled). BMP and EXR both correct — **confirmed by user**.
- [x] Fixed `ReShade.fxh` redefinition issue: `#ifndef` guards on `BUFFER_RCP_WIDTH/HEIGHT` — without this, both shaders fail to compile silently.
- [x] Fixed technique activation: ReShade ignores `enabled = 1` annotations without a preset file. `_ensure_preset()` in `main.py` always writes `ReShadePreset.ini` with both techniques.
- [x] Restored UIRemove.fx to deploy for all modes — it is the required final-pass passthrough that writes `tex2D(ReShade::BackBuffer, uv)` back to the swap chain so `capture_screenshot` sees the game image.
- [x] Removed `add_dependencies(frame_capture reshade_core)` from CMakeLists.txt — addon now builds independently without triggering the slow 6.7.3 MSBuild.
- [x] Reverted `feb4c39` default-mode change — `--mode custom` stays default.

## Not Yet Done

- [ ] Push 2 local commits to origin (`git push`)
- [ ] Decide what to do with `reshade/` source directory (6.7.3.16 UNOFFICIAL, unused): delete it to save space, or replace with actual 5.9.2 tag if DLL customization is ever needed.
- [ ] Whatever addon/shader customizations the user plans to make (not yet specified).

## Failed Approaches (Don't Repeat These)

1. **Switching default mode to `official592`** — reverted. User wants `--mode custom` as default because addon customization is the whole point.

2. **Using `dist/dxgi.dll` (built from `reshade/` source) for BMP capture** — `reshade/` is 6.7.3.16 UNOFFICIAL. Its `capture_screenshot` on R10G10B10A2 swap chains returns contents of an internal staging buffer that ends up holding DepthToAddon's ExportTex data (not the game image). Official 5.9.2 handles this correctly. **Do not attempt to use `dist/dxgi.dll` for capture** — the reshade/ source version problem would need to be fixed first.

3. **Removing UIRemove.fx** — wrong. UIRemove is the fix, not a bug. Without it, ReShade's effect pipeline can leave DepthToAddon render targets in the backbuffer, and `capture_screenshot` captures those. UIRemove must run last and writes the pre-effect copy back to the swap chain.

4. **Relying on `technique X < enabled = 1; >` annotation alone** — doesn't work. ReShade only activates techniques listed in the preset file's `Techniques=` line. Always write `ReShadePreset.ini` via `_ensure_preset()`.

5. **`shaders/ReShade.fxh` with unconditional `#define BUFFER_RCP_WIDTH (1.0/BUFFER_WIDTH)`** — ReShade runtime predefines this. Both shaders fail to compile with `preprocessor error: redefinition`. Always use `#ifndef` guards.

## Key Decisions

| Decision | Rationale |
|----------|-----------|
| `--mode custom` = vendor 5.9.2 DLL + custom-compiled addon | reshade/ source is 6.7.3 (wrong version); DLL doesn't need rebuilding for addon/shader customization |
| Always deploy shaders for all modes | Addon finds `DepthToAddon_ExportTex` by name; no shader = no EXR regardless of DLL |
| Always write `ReShadePreset.ini` | `enabled = 1` annotations are inert without a preset |
| Technique order locked: DepthToAddon → UIRemove | DepthToAddon writes to custom RTs; UIRemove must run last to restore backbuffer for capture |
| Default `FC_ExportNormal=0` | User-specified; only depth + BMP needed by default |

## Current State

**Working** (confirmed by user):
- `uv run main.py launch --mode custom --game-path E:\games\ff7remake\End\Binaries\Win64\ff7remake_.exe`
- Produces correct `*BackBuffer.bmp` (game image) + `*DepthBuffer.exr` (~20 MB, linear depth)
- `--mode official592` also works identically (same DLL, different addon)

**Unstaged** (binary diffs, not meaningful — dist files were re-deployed to game dir and back):
- `dist/dxgi.dll` — modified (binary diff, same effective content)
- `dist/frame_capture.addon` — modified (binary diff, same effective content)
- `HANDOFF.md` — deleted (previous handoff removed after resolution)

**Deployed to** `E:\games\ff7remake\End\Binaries\Win64\`:
- `dxgi.dll` ← `vendor/reshade592/dxgi.dll` (5.9.2.1760, 4.06 MB)
- `frame_capture.addon` ← `dist/frame_capture.addon` (custom-compiled, ~116 KB)
- `reshade-shaders/Shaders/{DepthToAddon.fx, UIRemove.fx, ReShade.fxh}`
- `ReShade.ini` with `FC_EnableCapture=1`, `FC_ExportDepth=1`, `FC_ExportNormal=0`
- `ReShadePreset.ini` with `Techniques=DepthToAddon@DepthToAddon.fx,UIRemove@UIRemove.fx`

## Files to Know

| File | Why It Matters |
|------|----------------|
| `main.py` | CLI entry. `_sources()` decides which DLL/addon to deploy per mode. `_ensure_preset()` writes ReShadePreset.ini. |
| `reshade-addons/99-frame_capture/frame_capture.cpp` | Entire addon (single file). Edit here for capture customization. |
| `shaders/DepthToAddon.fx` | murchFX 3-output: writes ExportTex (RGBA32F: normals+depth), DepthTex, NormalTex to custom RTs only. |
| `shaders/UIRemove.fx` | Pure passthrough — MUST run last. Writes `tex2D(ReShade::BackBuffer, uv)` to swap chain. |
| `shaders/ReShade.fxh` | Minimal local version. All `#define`s must have `#ifndef` guards. |
| `vendor/reshade592/dxgi.dll` | Official 5.9.2 binary. Used by both `--mode custom` and `--mode official592`. |
| `tools/capture/config.py` | Machine-specific paths — `GAME_PATH`, `DATASET_ROOT`. |
| `CMakeLists.txt` | Builds `frame_capture.addon` only (reshade_core target exists but output unused). |

## Code Context

**`_sources()` — which files get deployed per mode:**
```python
def _sources(mode: str):
    shader_src = ROOT / "shaders"
    dist = ROOT / "dist"
    # custom: official 5.9.2 DLL + our compiled addon
    if mode == "custom":
        return ROOT / "vendor" / "reshade592" / "dxgi.dll", dist / "frame_capture.addon", shader_src, True
    addon = ROOT / "vendor" / "addon_official" / "frame_capture.addon"
    if mode == "official592":
        return ROOT / "vendor" / "reshade592" / "dxgi.dll", addon, shader_src, True
    return ROOT / "vendor" / "reshade673" / "dxgi.dll", addon, shader_src, True
```

**Addon hot path (frame_capture.cpp):**
```cpp
static void on_reshade_present(effect_runtime* runtime) {
    if (!runtime->is_key_pressed(0x79) || !enableCapturing) return;  // 0x79 = F10
    runtime->capture_screenshot(pixels.data());  // reads swap chain backbuffer (correct with 5.9.2 DLL)
    // BGRA→RGBA swap only for b8g8r8a8; r10g10b10a2 returns RGBA already
    stbi_write_bmp(bmp_path, width, height, 4, pixels);
    if (enableDepthExp) saveImage(runtime, depth_path, sbi.export_texture_r, ...);
}
```

**ExportTex lookup (fires once per frame in on_begin_render_effects):**
```cpp
static void on_begin_render_effects(effect_runtime* runtime, ...) {
    if (sbi.export_texture_r != 0) return;
    runtime->enumerate_texture_variables(nullptr, [](effect_runtime* rt, effect_texture_variable var, void*) {
        char name[256]; rt->get_texture_variable_name(var, name);
        if (strcmp(name, "DepthToAddon_ExportTex") == 0)
            rt->get_texture_variable_value(var, &sbi.export_texture_r);
    }, nullptr);
}
```

**Generated ReShadePreset.ini** (must be present alongside ReShade.ini):
```ini
Techniques=DepthToAddon@DepthToAddon.fx,UIRemove@UIRemove.fx
TechniqueSorting=DepthToAddon@DepthToAddon.fx,UIRemove@UIRemove.fx
```

## Resume Instructions

1. **Push** pending commits: `git push`
2. **Rebuild addon** after any `frame_capture.cpp` change: `scripts\build.ps1` (fast — only compiles the addon, not reshade core)
3. **Deploy + test**: `uv run main.py launch --game-path E:\games\ff7remake\End\Binaries\Win64\ff7remake_.exe`
   - Press F9 in-game to start capture, F10 to capture frames
   - Expected: `*BackBuffer.bmp` shows game image, `*DepthBuffer.exr` ~15–25 MB

## Setup Required

- VS 2022 Build Tools (for addon rebuild only)
- `uv sync` for Python deps
- Game path: `E:\games\ff7remake\End\Binaries\Win64\ff7remake_.exe`

## Warnings

- **Do not use `dist/dxgi.dll` for capture** — built from 6.7.3.16 UNOFFICIAL source; `capture_screenshot` returns wrong data on R10G10B10A2 swap chains.
- **`reshade-addons/deps/reshade/include/`** uses old v5 wrapper names (`reshade::log_message`, `reshade::config_get_value`). Do not switch to `reshade/include/` — the wrapper names changed in v6.
- **`get_texture_variable_name` returns unqualified name** even for namespace-scoped textures: compare against `"DepthToAddon_ExportTex"`, not `"DepthToAddon::DepthToAddon_ExportTex"`.
- **UIRemove is mandatory** — removing it causes `capture_screenshot` to capture DepthToAddon render target content.
- **Always write ReShadePreset.ini** — `enabled = 1` annotations in shaders are inert without it.
