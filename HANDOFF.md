# Handoff: Restore correct BMP capture in unicap pipeline (FF7 Remake)

**Generated**: 2026-04-30 (after session ending ~08:51)
**Branch**: master
**Status**: Likely Resolved — awaiting user confirmation that `--mode official592` produces correct BMP

## Goal

Frame capture (`unicap`) on FF7 Remake should produce, on each F10 press:
- `*BackBuffer.bmp` showing the actual game image (3840×2160)
- `*DepthBuffer.exr` containing linear depth from DepthToAddon.fx

The user's last working commit was `f19a9d4` (vendored official 5.9.2 binaries). After commits converted submodules to vendored files and `--mode custom` (CMake-built ReShade) became default, BMP started showing normal-map / psychedelic patterns and EXR stopped writing.

## Completed

- [x] Identified root cause #1: my custom `shaders/ReShade.fxh` had unconditional `#define BUFFER_RCP_WIDTH/HEIGHT`, but ReShade runtime predefines them. Both shaders failed to compile silently. **Fixed** with `#ifndef` guards (this got EXR working).
- [x] Identified root cause #2: with no `ReShadePreset.ini`, ReShade does NOT auto-enable techniques even when shaders carry `enabled = 1` annotations. **Fixed** by adding `_ensure_preset()` in `main.py` that writes `Techniques=` and `TechniqueSorting=`.
- [x] Identified root cause #3 (the real one for the BMP issue): the `reshade/` directory is NOT actual 5.9.2 source — its `res/version.h` reads `VERSION_FULL 0.0.0.1` and our build reports `'0.0.0.1' (64-bit)` in the log. It's a development snapshot, not the 5.9.2 release. Behavior of `render_effects` / `capture_screenshot` differs from real 5.9.2 on R10G10B10A2 swap chains, producing wrong BMP.
- [x] Made `--mode official592` deploy shaders too (previously `deploy_shaders=False` for non-custom modes, which is why nobody noticed — the official addon needs DepthToAddon.fx to find ExportTex).
- [x] Deployed real 5.9.2 official binaries to FF7R Win64 (`vendor/reshade592/dxgi.dll` 4.16 MB + `vendor/addon_official/frame_capture.addon` 100 KB) along with shaders + ReShadePreset.ini. **User has not yet tested this configuration.**
- [x] Restored UIRemove.fx to deploy (I had wrongly removed it earlier this session).
- [x] Removed the stray 4-output MRT version of DepthToAddon.fx, reverting `shaders/DepthToAddon.fx` to murchFX 3-output original (writes only to custom textures: ExportTex/DepthTex/NormalTex).
- [x] Added diagnostic logging in `frame_capture.cpp` (`FC: listing all effect texture variables`, `FC: ExportTex cached → handle = …`, etc.).
- [x] Removed the silent-fail `copy_source` usage check in `saveImage` (the texture turned out to have it — usage = 7364 = 0x1CC4 includes 0x800/copy_source — so the check was harmless but the early-return was a hazard).
- [x] Added `FC_ExportNormal=0` default; only depth + BMP are captured by default.

## Not Yet Done

- [ ] **User must verify `--mode official592` actually produces correct BMP + EXR.** Expected log line on next run: `Initializing crosire's ReShade version '5.9.2'` (NOT `0.0.0.1`).
- [ ] Decide what to do with `--mode custom`:
  - Option A: delete it entirely; rely on vendored `vendor/reshade592/dxgi.dll`.
  - Option B: replace `reshade/` source with the actual 5.9.2 release tag (https://github.com/crosire/reshade tag `v5.9.2`) so `--mode custom` produces a correct binary.
  - Option C: leave it broken but mark it experimental.
- [ ] Commit the changes once user confirms working.

## Failed Approaches (Don't Repeat These)

1. **Removed UIRemove.fx from deploy thinking it caused "psychedelic" colors** (mid-session). Wrong. UIRemove is the *fix*, not the bug — it's a pure passthrough that writes the original `ReShade::BackBuffer` content to the swap chain backbuffer at the end of the technique chain, restoring the game image for `capture_screenshot`. Without it, ReShade's effect pipeline can leave garbage in the backbuffer. *Re-added it.*

2. **Wrote `shaders/ReShade.fxh` with unconditional `#define BUFFER_RCP_WIDTH (1.0/BUFFER_WIDTH)`**. ReShade runtime predefines this macro. Both DepthToAddon.fx and UIRemove.fx failed to compile with `preprocessor error: redefinition of 'BUFFER_RCP_WIDTH'`. *Fixed* with `#ifndef` guards. This was the smoking gun for "no EXR" — shaders silently weren't compiling.

3. **Tried 4-output MRT in DepthToAddon.fx (commit `424589e`)** with explicit backbuffer passthrough (SV_Target0 → backbuffer, SV_Target1/2/3 → custom). Worked structurally but was abandoned in favor of having UIRemove handle the passthrough as a separate technique (cleaner separation; commit `a69d083`). The 4-output version was leftover at one point in this session and got re-staged — **do not bring it back**, it conflicts with murchFX original.

4. **Assumed `technique X < enabled = 1; >` annotation alone enables a technique.** It does not. ReShade only activates techniques listed in the preset file's `Techniques=` line. Without a preset, *no* techniques run, even if every annotation says `enabled = 1`. This was source of the "BMP still wrong after EXR was working" symptom — UIRemove compiled but never ran. *Fixed* by writing `ReShadePreset.ini` in deploy.

5. **Added fallback ExportTex enumeration in `on_reshade_present`** when `sbi.export_texture_r == 0`. Useful diagnostic but not a real fix — once ReShade.fxh was fixed, the texture is always found in `on_begin_render_effects` and the fallback never fires productively. Kept anyway as a safety net.

## Key Decisions

| Decision | Rationale |
|----------|-----------|
| Deploy shaders for ALL modes (not just custom) | The addon enumerates `DepthToAddon_ExportTex` by name; no shader = no EXR regardless of which DLL is used. |
| Always write `ReShadePreset.ini` in deploy | `enabled = 1` annotations are inert without a preset; we have to enumerate techniques explicitly. |
| Lock technique order: DepthToAddon → UIRemove | DepthToAddon writes to custom RTs only; UIRemove must run last to write `tex2D(ReShade::BackBuffer, uv)` back into the swap-chain backbuffer so `capture_screenshot` sees the game image. Reversed order also works (UIRemove is no-op-equivalent if backbuffer wasn't dirty), but locked-order avoids surprises. |
| Default `FC_ExportNormal=0` | User asked for it explicitly. EXR depth is enough for current pipeline; normal export is opt-in via `Frame Capture` overlay panel. |
| Use real 5.9.2 vendor binaries instead of fixing `reshade/` source | Faster path to a known-good baseline. The user's `f19a9d4` already proved this works. Re-syncing `reshade/` to actual 5.9.2 tag is a lot more invasive. |

## Current State

**Working** (after my fixes, with `--mode custom` aka our wrong-version build):
- DepthToAddon.fx + UIRemove.fx compile successfully (no more `BUFFER_RCP_WIDTH redefinition`).
- ExportTex is found and EXR depth files are written correctly (`*DepthBuffer.exr`, ~296 KB each, format = RGBA32F).
- BMP file size is correct (32,401 KB for 3840×2160 RGBA), but **content is wrong** — shows colorful normal-map-like patterns, not the game.

**Broken until user tests `--mode official592`**:
- BMP content under `--mode custom` (our `0.0.0.1 UNOFFICIAL` build of ReShade). The wrong `reshade/` source produces a binary that handles R10G10B10A2_UNORM swap chains differently than 5.9.2 does, and the swap chain backbuffer ends up with ExportTex-like content even though no shader explicitly writes there.

**Currently deployed to `E:\games\ff7remake\3DMGAME_Final_Fantasy_VII_Remake.CHS.Green.part001\Final Fantasy VII Remake Intergrade\End\Binaries\Win64\`**:
- `dxgi.dll` ← `vendor/reshade592/dxgi.dll` (4.16 MB, real 5.9.2)
- `frame_capture.addon` ← `vendor/addon_official/frame_capture.addon` (100 KB)
- `reshade-shaders/Shaders/{DepthToAddon.fx, UIRemove.fx, ReShade.fxh}`
- `ReShade.ini` with `EffectSearchPaths=.\reshade-shaders\Shaders\` etc.
- `ReShadePreset.ini` with `Techniques=DepthToAddon@DepthToAddon.fx,UIRemove@UIRemove.fx` (and same `TechniqueSorting=`)

**Uncommitted Changes**:
- `main.py`: added `_ensure_preset()`, made all modes deploy shaders, made shader source `ROOT/shaders` for all modes, default `FC_ExportNormal=0`, ensured `EffectSearchPaths` set.
- `reshade-addons/99-frame_capture/frame_capture.cpp`: added `FC:` log lines, extracted `fc_find_export_tex()` helper, increased name buffer 32→256, removed silent-fail on missing `copy_source` flag, default `enableNormalExp=false`.
- `shaders/DepthToAddon.fx`: reverted from local 4-output MRT version back to murchFX 3-output original.
- `shaders/ReShade.fxh`: NEW file (untracked). Minimal version with `#ifndef` guards, namespace `ReShade { texture BackBufferTex : COLOR; … }`, `PostProcessVS`, `RESHADE_DEPTH_*` defaults.
- `CMakeLists.txt`: shader staging now copies `shaders/ReShade.fxh`, `shaders/DepthToAddon.fx`, `shaders/UIRemove.fx` to `dist/reshade-shaders/Shaders/` (previously copied DepthToAddon from `murchFX/Shaders/` submodule).
- `dist/dxgi.dll`, `dist/frame_capture.addon`: rebuilt during session (still `0.0.0.1`).
- `dist/reshade-shaders/Shaders/ReShade.fxh`: new staged shader (untracked).

## Files to Know

| File | Why It Matters |
|------|----------------|
| `main.py` | Single CLI entry: `deploy`, `launch`, `capture`, `pack`. `_sources()` decides which DLL/addon to use; `_ensure_addon_enabled()` writes ReShade.ini; `_ensure_preset()` writes ReShadePreset.ini. |
| `reshade-addons/99-frame_capture/frame_capture.cpp` | The whole addon. `on_begin_render_effects` caches the `DepthToAddon_ExportTex` SRV. `on_reshade_present` checks F10 (VK 0x79), calls `capture_screenshot()`, writes BMP, calls `saveImage()` for EXR. |
| `shaders/DepthToAddon.fx` | murchFX 3-output, all RTs custom. Generates ExportTex (RGBA32F: normal.xyz, depth.w), DepthTex, NormalTex. |
| `shaders/UIRemove.fx` | Pure passthrough: `return tex2D(ReShade::BackBuffer, uv);`. MUST be enabled and MUST run last. |
| `shaders/ReShade.fxh` | Minimal local version; deployed as fallback because ReShade doesn't auto-bundle this on raw installs. Use `#ifndef` guards on all defines. |
| `CMakeLists.txt` | Builds reshade core (MSBuild) + frame_capture (CMake) + stages shaders to `dist/`. **The reshade core build target uses `reshade/` source which is the wrong version (0.0.0.1, not 5.9.2)** — see warning below. |
| `vendor/reshade592/dxgi.dll` | Real 5.9.2 official binary. Used by `--mode official592`. |
| `vendor/addon_official/frame_capture.addon` | Real 5.9.2-era official addon binary. |
| `tools/capture/config.py` | Machine-specific paths. Edit `GAME_PATH`, `DATASET_ROOT` for new machines. |

## Code Context

**Working flow (techniques in order):**

```hlsl
// shaders/DepthToAddon.fx — writes ExportTex (RGBA32F: normals + depth)
namespace DepthToAddon {
    texture DepthToAddon_ExportTex { Width = BUFFER_WIDTH; Height = BUFFER_HEIGHT; Format = RGBA32F; };
    texture DepthToAddon_DepthTex  { Width = BUFFER_WIDTH; Height = BUFFER_HEIGHT; Format = RGBA8; };
    texture DepthToAddon_NormalTex { Width = BUFFER_WIDTH; Height = BUFFER_HEIGHT; Format = RGBA8; };
    void PS_DepthToAddon(..., out float4 exportTex : SV_Target0,
                              out float4 depthTex : SV_Target1,
                              out float4 normalTex : SV_Target2) { ... }
    technique DepthToAddon < enabled = 1; > {
        pass {
            VertexShader = PostProcessVS;
            PixelShader  = PS_DepthToAddon;
            RenderTarget0 = DepthToAddon_ExportTex;  // custom — backbuffer NOT touched
            RenderTarget1 = DepthToAddon_DepthTex;
            RenderTarget2 = DepthToAddon_NormalTex;
        }
    }
}
```

```hlsl
// shaders/UIRemove.fx — restores backbuffer
float4 PS_RemoveUI(float4 vpos : SV_Position, float2 uv : TEXCOORD) : SV_Target {
    return tex2D(ReShade::BackBuffer, uv);  // start-of-frame copy
}
technique UIRemove < enabled = 1; > {
    pass { VertexShader = PostProcessVS; PixelShader = PS_RemoveUI; }
    // no explicit RenderTargetN → defaults to swap chain backbuffer
}
```

**Addon hot path:**

```cpp
// frame_capture.cpp — fires every frame after effects render
static void on_reshade_present(effect_runtime* runtime) {
    if (!runtime->is_key_pressed(0x79) || !enableCapturing) return;  // 0x79 = F10
    // ... build save_path with timestamp ...
    runtime->capture_screenshot(pixels.data());          // reads swap chain backbuffer
    // BGRA→RGBA swap only for b8g8r8a8 formats; r10g10b10a2 returns RGBA already
    stbi_write_bmp(bmp_path, width, height, 4, pixels);
    if (enableDepthExp) saveImage(runtime, depth_path, sbi.export_texture_r, ...);
}
```

**Generated `ReShadePreset.ini`** (must be in game dir alongside ReShade.ini):
```ini
Techniques=DepthToAddon@DepthToAddon.fx,UIRemove@UIRemove.fx
TechniqueSorting=DepthToAddon@DepthToAddon.fx,UIRemove@UIRemove.fx
```

**Generated `ReShade.ini`** (relevant lines):
```ini
[ADDON]
FC_EnableCapture=1
FC_ExportDepth=1
FC_ExportNormal=0

[GENERAL]
EffectSearchPaths=.\reshade-shaders\Shaders\
PresetPath=.\ReShadePreset.ini
```

## Resume Instructions

1. **Ask the user to test the current deployment** (already done by previous agent — vendor 5.9.2 binaries are deployed). Have them launch FF7R, press F10 a few times in-game, then share `Win64/ReShade.log` and one of the `*BackBuffer.bmp` files.
2. **Verify in the log** that the line reads `Initializing crosire's ReShade version '5.9.2' (64-bit)` — NOT `0.0.0.1`.
   - Expected BMP: actual game image at 3840×2160.
   - Expected EXR: `*DepthBuffer.exr` ~300 KB per frame.
   - If BMP wrong: check `Win64/ReShadePreset.ini` exists and contains both technique names. Check log for `Successfully compiled` lines for both .fx files. Look for `FC: ExportTex cached` log line confirming addon is happy.
3. **Once confirmed working**, commit the changes. Suggested message:
   ```
   capture: fix BMP/EXR pipeline — deploy real 5.9.2 binaries with shaders + preset
   ```
4. **Decide on `--mode custom`** with the user (see "Not Yet Done"). My recommendation: replace `reshade/` source with actual 5.9.2 tag from upstream, since the project's intent (per CMakeLists comment) was always to build 5.9.2.

## Setup Required

- Game path is hard-coded for FF7R: `E:/games/ff7remake/3DMGAME_Final_Fantasy_VII_Remake.CHS.Green.part001/Final Fantasy VII Remake Intergrade/End/Binaries/Win64`. Override via `--game-path` if testing on a different install.
- Python deps via `uv sync`.
- For `--mode custom` (NOT recommended right now): VS 2022 Build Tools + CMake ≥ 3.20.

## Edge Cases & Error Handling

- **Game already running when deploy runs**: `dxgi.dll` will be locked, `shutil.copy2` fails. Current behavior: Python exception with EACCES. Not handled — user must close the game first.
- **Game uses HDR10 swap chain**: untested. R10G10B10A2_UNORM SDR works. If a future game presents HDR-encoded values, BMP would look washed out / wrong but in a *different* way than the current bug (mostly black with bright highlights, not "normal-map look").
- **Multiple `.exe` in game dir**: `_resolve_game_path()` picks the largest non-blacklisted exe. Blacklist in `_SKIP_EXE` covers UE4 prereq installers, vcredist, crashreporter.
- **F10 already bound by game**: ReShade.ini sets `KeyScreenshot=0,0,0,0` to prevent ReShade's own screenshot grabbing the same key, but the GAME might still bind F10. User can pass `--start-key F9` to `launch` for a different start trigger (the game-internal F10 capture trigger inside the addon is hard-coded to VK 0x79).

## Warnings

- **`reshade/` source directory is NOT v5.9.2.** Its `res/version.h` says `VERSION_FULL 0.0.0.1` and our build reports the same in the log. CMakeLists.txt comment claiming it's 5.9.2 is currently a lie. Either fix the source or delete `--mode custom`.
- **Don't trust shader `enabled = 1` annotations alone.** They only set the *default* state in a *new* preset. With no preset file, no technique runs at all. Always write `ReShadePreset.ini` explicitly.
- **Don't reinstate the removal of `shutil.copy2(shader_src / "UIRemove.fx", ...)`**. UIRemove is required, not optional.
- **Don't add `texture BackBufferTex : COLOR` declarations outside the `ReShade` namespace.** Multiple textures with `: COLOR` semantic in different namespaces are fine; outside-namespace globals collide with ReShade's bundled bindings.
- **`reshade-addons/deps/reshade/include/`** holds an OLDER reshade header set (uses `reshade::log_message`, `reshade::config_get_value` wrapper names). The addon source in `99-frame_capture/frame_capture.cpp` calls those wrappers, so we must keep that include path. Don't switch to `reshade/include/` — the wrapper names changed in newer reshade.
- **Removing the `copy_source` usage check in `saveImage` is intentional.** With our texture (usage = 7364 = 0x1CC4 includes 0x800/copy_source) the check passes anyway; on textures where it would fail, modern ReShade abstracts the resource state correctly and `barrier(... shader_resource → copy_source ...)` works for any DEFAULT-heap texture in DX12.
- **`get_texture_variable_name` returns the unqualified name** even when the texture is declared inside a namespace (we logged `'DepthToAddon_ExportTex'` not `'DepthToAddon::DepthToAddon_ExportTex'`). Don't change the strcmp target.
- The session's earlier "fix for psychedelic colors" by removing UIRemove was wrong. Earlier psychedelic colors were likely just the same root cause (no UIRemove + wrong reshade build) misdiagnosed as a UIRemove side-effect.
