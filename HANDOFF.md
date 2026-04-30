# Handoff: unicap pipeline — 6.7.3 DLL, zero splash, texture-export BMP capture

**Generated**: 2026-04-30
**Branch**: master (up to date with origin)
**Status**: Working — pending end-to-end test with game running

## Goal

Game capture pipeline for FF7 Remake (DX12, R10G10B10A2_UNORM swap chain): each F10 press produces a `*BackBuffer.bmp` (game image) + `*DepthBuffer.exr` (linear depth), with **zero ReShade UI visible at any point** — not during startup loading, not after.

## Completed

- [x] Eliminated ReShade startup splash entirely by switching `--mode custom` from `vendor/reshade592/dxgi.dll` (5.9.2) to `dist/dxgi.dll` (6.7.3). The 6.7.3 source explicitly sets `_show_splash = false` in `reload_effects()` — no ini key needed.
- [x] Worked around 6.7.3's broken `capture_screenshot` on R10G10B10A2: added `UIRemove_ColorTex` (RGBA8) export texture to `UIRemove.fx`; addon reads this texture directly instead of calling `capture_screenshot`.
- [x] Upgraded `frame_capture.cpp` from ReShade addon API v1 (5.9.2 headers) to v20 (6.7.3 headers). Key API changes: `get_config_value` (renamed), `log::message` (moved namespace), `get_texture_binding` (third arg required), `get_private_data` (returns `T*` not `T&`).
- [x] `ReShade.ini` writes `TutorialProgress=4` under `[OVERLAY]` (was wrongly under `[GENERAL]`) to suppress the "installed successfully" persistent banner.
- [x] All changes committed and pushed (`620fafd`).

## Not Yet Done

- [ ] **End-to-end test**: launch game, press F10, verify `*BackBuffer.bmp` shows game image (not psychedelic/normal-map colors) and `*DepthBuffer.exr` is ~15–25 MB.
- [ ] Decide whether to keep `reshade/` source directory (6.7.3.16 UNOFFICIAL, ~large); now actively used for DLL + addon API headers.
- [ ] Whatever further addon/shader customizations are needed for ML training.

## Failed Approaches (Don't Repeat These)

1. **`TutorialProgress=4` under `[GENERAL]`** — ReShade reads this key exclusively from `[OVERLAY]`. Writing it to `[GENERAL]` is silently ignored. Result: "installed successfully" message persisted.

2. **`CheckForUpdates=0` ini key** — Does not exist in any ReShade version (checked source). The update check is unconditional in the binary. Removing this key had no effect.

3. **Suppressing 5.9.2 splash via ini** — 5.9.2 has no config key to disable the startup splash. The 6.7.3 source has `_show_splash = false` hardcoded in `reload_effects()` — this is why we must use 6.7.3, not 5.9.2, to get zero splash.

4. **Using `capture_screenshot()` with 6.7.3 DLL** — On R10G10B10A2 swap chains, 6.7.3 UNOFFICIAL's `capture_screenshot` reads from an internal staging buffer that holds DepthToAddon's ExportTex data (psychedelic/normal-map colors), not the game image. Fixed by reading `UIRemove_ColorTex` directly from the shader instead.

5. **Using `dist/dxgi.dll` (6.7.3) with the old v1 addon API** — RESHADE_API_VERSION mismatch (1 vs 20) causes `reshade::register_addon()` to return FALSE and the addon silently fails to load. Must use `reshade/include/` headers (v20).

6. **Keeping `reshade-addons/deps/imgui` (ImGui 1.86) with v20 headers** — `reshade_overlay.hpp` has a `#error` that fires unless ImGui version is exactly 19250 (1.92.5). Must use `reshade/deps/imgui/` instead.

## Key Decisions

| Decision | Rationale |
|----------|-----------|
| `--mode custom` = `dist/dxgi.dll` (6.7.3) + custom addon | Only version with zero startup splash; `capture_screenshot` bug bypassed by texture export |
| BMP via `UIRemove_ColorTex` not `capture_screenshot` | 6.7.3's `capture_screenshot` broken on R10G10B10A2; texture export gives identical data |
| Addon headers from `reshade/include/` (v20) | Must match the DLL's RESHADE_API_VERSION; v1 headers cause silent load failure |
| `TutorialProgress=4` in `[OVERLAY]` | Suppresses persistent "installed successfully" banner |
| Technique order locked: DepthToAddon → UIRemove | DepthToAddon writes to custom RTs; UIRemove must run last to snapshot clean BackBuffer |

## Current State

**Working** (compiled clean, not yet tested with live game):
- `dist/dxgi.dll` — 6.7.3 UNOFFICIAL, 5.44 MB — zero splash on load
- `dist/frame_capture.addon` — v20 API, reads `UIRemove_ColorTex` for BMP + `DepthToAddon_ExportTex` for EXR
- `shaders/UIRemove.fx` — two-pass: ExportColor (→ UIRemove_ColorTex) + RestoreBackBuffer (→ swap chain)
- `main.py --mode custom` deploys `dist/dxgi.dll` + `dist/frame_capture.addon` + shaders

**Not yet confirmed**: BMP correctness with the new code path (texture export not previously tested end-to-end).

**`--mode official592`** still works as before (vendor 5.9.2 DLL + official addon, has splash).

## Files to Know

| File | Why It Matters |
|------|----------------|
| `main.py` | CLI. `_sources()` decides DLL/addon per mode. `_ensure_addon_enabled()` writes `ReShade.ini`. |
| `reshade-addons/99-frame_capture/frame_capture.cpp` | Entire addon. `saveColorBMP()` reads `UIRemove_ColorTex`. `fc_find_export_tex()` finds both textures. |
| `shaders/UIRemove.fx` | Two-pass: ExportColor → `UIRemove_ColorTex`, RestoreBackBuffer → swap chain. |
| `shaders/DepthToAddon.fx` | Exposes `DepthToAddon_ExportTex` (RGBA32F: normals+depth) read by addon. |
| `shaders/ReShade.fxh` | Minimal local version. All `#define`s must have `#ifndef` guards (ReShade redefines them). |
| `dist/dxgi.dll` | 6.7.3 UNOFFICIAL binary. Zero startup splash. `capture_screenshot` broken on R10G10B10A2 — do not use. |
| `vendor/reshade592/dxgi.dll` | Official 5.9.2 binary. `capture_screenshot` correct but has startup splash. |
| `reshade/include/` | v20 addon API headers used by `frame_capture.cpp`. |
| `reshade/deps/imgui/` | ImGui 1.92.5 — required by `reshade_overlay.hpp` in v20 headers. |
| `tools/capture/config.py` | Machine-specific paths: `GAME_PATH`, `DATASET_ROOT`. |
| `CMakeLists.txt` | Builds `frame_capture.addon`. Include paths now point to `reshade/include/` and `reshade/deps/imgui/`. |

## Code Context

**`_sources()` — which files get deployed per mode:**
```python
def _sources(mode: str):
    shader_src = ROOT / "shaders"
    dist = ROOT / "dist"
    # custom: 6.7.3 DLL (no splash) + our compiled addon
    if mode == "custom":
        return dist / "dxgi.dll", dist / "frame_capture.addon", shader_src, True
    addon = ROOT / "vendor" / "addon_official" / "frame_capture.addon"
    if mode == "official592":
        return ROOT / "vendor" / "reshade592" / "dxgi.dll", addon, shader_src, True
    return ROOT / "vendor" / "reshade673" / "dxgi.dll", addon, shader_src, True
```

**`stored_buffers_inst` — texture handles cached per runtime:**
```cpp
struct stored_buffers_inst {
    resource export_texture_r = { 0 };   // DepthToAddon_ExportTex (RGBA32F)
    resource_desc export_texture_rd;
    resource_view export_texture_rv = { 0 };
    resource color_texture_r = { 0 };    // UIRemove_ColorTex (RGBA8) — BMP source
    resource_desc color_texture_rd;
};
```

**`saveColorBMP()` — reads RGBA8 texture from GPU, saves as BMP:**
- GPU→CPU copy via staging buffer (D3D12 `copy_texture_to_buffer` path)
- Row-by-row memcpy to handle 256-byte pitch alignment
- Calls `stbi_write_bmp` with 4 channels

**`fc_find_export_tex()` — enumerates both textures:**
```cpp
// looks for both "DepthToAddon_ExportTex" and "UIRemove_ColorTex"
// uses three-arg get_texture_binding(var, &srv, &srv_srgb) — v20 API requires both args
```

**`on_reshade_present` hot path:**
```cpp
static void on_reshade_present(effect_runtime* runtime) {
    if (!runtime->is_key_pressed(0x79) || !enableCapturing) return;  // 0x79 = F10
    stored_buffers_inst& sbi = *runtime->get_private_data<stored_buffers_inst>();
    if (sbi.color_texture_r.handle == 0) fc_find_export_tex(runtime, sbi);
    saveColorBMP(runtime, bmp_path, sbi.color_texture_r, sbi.color_texture_rd);
    if (enableDepthExp) saveImage(runtime, depth_path, sbi.export_texture_r, ...);
}
```

**UIRemove.fx two-pass structure:**
```hlsl
technique UIRemove {
    pass ExportColor {         // writes BackBuffer → UIRemove_ColorTex (RGBA8)
        RenderTarget = UIRemove_ColorTex;
    }
    pass RestoreBackBuffer {   // writes BackBuffer → swap chain (no RenderTarget = default)
    }
}
```

**ReShade.ini keys written by `_ensure_addon_enabled()`:**
```ini
[ADDON]
FC_EnableCapture = 1
FC_ExportDepth   = 1
FC_ExportNormal  = 0

[OVERLAY]
ShowScreenshotMessage = 0
TutorialProgress = 4      ; ← must be [OVERLAY], not [GENERAL]

[INPUT]
KeyScreenshot = 0,0,0,0

[GENERAL]
EffectSearchPaths = .\reshade-shaders\Shaders\
TextureSearchPaths = .\reshade-shaders\Textures\
```

## Resume Instructions

1. **Rebuild addon** (already done, but do after any `.cpp` change):
   ```powershell
   scripts\build.ps1
   ```

2. **Delete old `ReShade.ini`** in game dir to flush stale ini from 5.9.2 era:
   ```powershell
   Remove-Item "E:\games\ff7remake\End\Binaries\Win64\ReShade.ini" -Force
   ```

3. **Deploy + test**:
   ```powershell
   uv run main.py launch --game-path "E:\games\ff7remake\End\Binaries\Win64\ff7remake_.exe"
   ```
   - Press F9 in-game to start capture session
   - Press F10 once to capture a frame
   - Expected: `*BackBuffer.bmp` shows game image (NOT psychedelic colors), `*DepthBuffer.exr` ~15–25 MB
   - If BMP is wrong color: `UIRemove_ColorTex` might not be bound yet — check ReShade log for "FC: listing all effect texture variables" and confirm `UIRemove_ColorTex` appears
   - If BMP is skipped: log says "UIRemove_ColorTex not ready" — verify `UIRemove` technique is active in `ReShadePreset.ini`

4. **Verify zero splash**: game window should open with no ReShade overlay text at any point.

## Setup Required

- VS 2022 Build Tools (for addon rebuild only)
- `uv sync` for Python deps
- Game path: `E:\games\ff7remake\End\Binaries\Win64\ff7remake_.exe`

## Warnings

- **Do NOT use `capture_screenshot()` with `dist/dxgi.dll` (6.7.3)** — on R10G10B10A2 it returns DepthToAddon's ExportTex data (psychedelic colors), not the game image. Use `UIRemove_ColorTex` exclusively.
- **Do NOT use `vendor/reshade592/dxgi.dll` (5.9.2) for zero-splash** — 5.9.2 has no ini key to suppress the startup splash. The splash is hardcoded.
- **`reshade-addons/deps/reshade/include/`** — old v1 API. Do NOT use for compilation with `dist/dxgi.dll`; addon will silently fail to load (API version mismatch).
- **`reshade/include/`** — v20 API. Function names differ from v5: `get_config_value` (not `config_get_value`), `log::message` (not `log_message`), `get_private_data` returns `T*` (not `T&`).
- **Always write `ReShadePreset.ini`** — `enabled = 1` shader annotations are inert without a preset listing techniques explicitly.
- **UIRemove must run last** and be listed after DepthToAddon in `Techniques=`. If order is wrong, `UIRemove_ColorTex` captures DepthToAddon's RT output instead of the game image.
- **`TutorialProgress` must be in `[OVERLAY]`** — writing it to `[GENERAL]` is silently ignored by ReShade.
- **`reshade/deps/glad/target/`** — pre-generated C headers force-added with `git add -f`. Do not delete.
