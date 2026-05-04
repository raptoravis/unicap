# Handoff: capture pipeline BMP → PNG migration done — sponsor live-verify open

**Generated**: 2026-05-04 22:20 CST
**Branch**: `master` (HEAD = `3fab8a4`, pushed to `origin/master`)
**Status**: In Progress — code-side closed and EXE shipped; only sponsor live-fps measurement remains.

## Goal

Cut the FF7R capture-write bottleneck (~5fps actual vs 30fps target in `--ui-mode both`) by switching color output from uncompressed BMP to PNG, and downscale the post-UI watchdog/VLM stream to 960×540. Plus close the cleanup-grace TODO from the prior handoff.

## Completed in this session

### commit `80ca317` (cleanup-grace, replay path)

- [x] **`main.py:_run_replay` finally** replaced fixed 0.3s + 3× × 0.1s retry with adaptive polling: wait until `scratch.iterdir()` count is unchanged across a 0.6s window (hard cap 5s) before `rmtree`. Sponsor live-verified on FF7R: no more `[REPLAY] WARN: 清理 ... 失败`.

### commit `e59b5f0` (BMP → PNG migration, addon + 11 .py files)

- [x] **C++ addon (`frame_capture.cpp`)**:
  - 3 new ini knobs: `FC_UsePNG` (default 1), `FC_PostUIDownscaleW` (960), `FC_PostUIDownscaleH` (540).
  - `save_worker_fn` branches on `g_use_png` to call `stbi_write_png` (with stride). Pre-UI and post-UI paths both go through the toggle.
  - Post-UI extra downscale to 960×540 — only fires when source is larger AND `g_post_ui_dscale_w/h > 0`. In `--ui-mode ui` (single stream feeding HDF5) the same field is repurposed but `g_both_capture` is false, so post-UI block isn't reached → no degradation of ML data.
  - Filenames: `BackBuffer.bmp` / `BackBufferUI.bmp` / `survey_skip_NNN_BackBuffer.bmp` → `.png` when `g_use_png=1`.
  - Worker pool: `NUM_WORKERS 2→4`, `MAX_QUEUE 16→32` to absorb PNG encode cost (~10× slower than BMP memcpy).
- [x] **Python pipeline** (11 files): all glob patterns (`*BackBuffer.bmp` → `*BackBuffer.png`), filename constants, `endswith()` filters, ffmpeg input patterns, regex parsers in `pack_hdf5.py`, and `verify_replay.py` / `verify_auto_play.py` test fixtures. `cv2.imdecode` calls didn't need changes (format-agnostic).
- [x] **`main.py:945`**: PACK-style `"[VIDEO] 开始生成 video.mp4（如不需要可加 --no-video 跳过）…"` announcement before fps-estimation log (per sponsor request).
- [x] **`scripts/build.ps1`** produces `frame_capture.addon` (210 KB) without errors. `scripts/verify_replay.py` reports `33/33 passed`.

### commit `3fab8a4` (EXE bundling fix)

- [x] **`scripts/build-exe.ps1`** was missing `--include-data-dir=profiles=profiles`. Sponsor unzipped `unicap-1.0.5.zip` and got `[REPLAY] profile load failed: profiles 目录不存在: E:\downloads\unicap-1.0.5\profiles`. Fixed + added `profiles\_default.yaml` and `profiles\ff7r.yaml` to the required-asset preflight so a future regression fails the build instead of shipping. Rebuilt zip = 81.3 MB / 96 files (was 91), `dist-exe\profiles\` now contains all 4 yaml + README.

## Not Yet Done

- [ ] **Sponsor live-fps measurement on FF7R**:
  1. `uv run main.py launch --game-path "<ff7r>" --profile ff7 --ui-mode both` (or run the unicap.exe build); capture 60s of normal play.
  2. Compute fps: count `*BackBuffer.png` in the session `frames/` dir / capture wall-time. Target: 5 → 15-20.
  3. Check `%TEMP%\unicap\unicap.log1` for `FC: save queue full, dropping frame` lines. Zero or sparse = workers keeping up. Frequent = encode CPU bound; either bump `NUM_WORKERS` further or set `FC_UsePNG=0` (escape hatch in `unicap.ini`).
  4. Eyeball FF7R itself for fps drops from the addon's encode CPU cost. If sponsor's game-side fps tanks, the worker pool is starving the render thread.
- [ ] **Sponsor verify post-UI quality at 540p**: open one `*BackBufferUI.png` from a capture session — confirm watchdog/VLM can still see HUD/menus clearly enough. If 540p too fuzzy, bump `FC_PostUIDownscaleH=720` in `unicap.ini`.
- [ ] **`auto-play` branch** still points at `68e89c7` (pre-PNG). All PNG work is on `master` only; if that branch matters going forward, ff-merge it to `3fab8a4`.

## Failed Approaches (Don't Repeat These)

- **Synchronous BMP→PNG (option c-1)** was rejected during planning, NOT tried in code. Rationale: `runtime->capture_screenshot()` runs on a render-adjacent thread, ~30-50ms PNG encode synchronously would risk stuttering FF7R itself. The existing `save_worker_fn` infrastructure (already present for BMP) plus a worker-pool bump is the right route.
- **Custom encode / libpng / zlib add-on**: rejected. `stb_image_write.h` was already linked in the addon (line 153/172 of `frame_capture.cpp` had `stbi_write_bmp`). Switching to `stbi_write_png` is zero new dependency.
- **Backward-compat reading old `.bmp` recordings (Q4)**: the user explicitly chose NOT to support this. Old `_scenes/<name>/sync_NN.bmp` will fail under the new globs. Sponsor must re-record.
- **Keeping `.bmp` extension while writing PNG bytes inside**: rejected. cv2/ffmpeg are content-detected so it would "work", but `file` command and external tools would mis-identify. Honest extension wins.
- **Pre-`/clear` survey check** (closed last session in `68e89c7` but worth keeping in failed-list lore): ran survey before `focus_game_window()` was called → addon hadn't loaded → survey timed out. Survey check now lives in `_interactive_loop`, fires after replay.

## Key Decisions

| Decision | Rationale |
|---|---|
| Switch extension `.bmp` → `.png` (Q1=yes, no compat shim) | Honest filename / content match. ffmpeg detects by extension. Python glob churn was mechanical (~50 sites). |
| Pre-UI also PNG, not just post-UI (Q2=both) | Pre-UI 1080p BMP is the dominant write load (~8 MB/frame). Skipping it would only halve the gain. Worker pool bump (2→4) covers the encode cost. |
| Add 3 ini knobs as escape hatches (Q3=yes) | `FC_UsePNG=0` in `unicap.ini` reverts to BMP without rebuilding `dxgi.dll`. Useful if sponsor sees game-side fps drops. |
| No backward compat (Q4=no) | One-time re-record cost vs permanent dual-glob complexity. Sponsor's recordings are fresh anyway. |
| Post-UI 540p downscale only in `both` mode | In `--ui-mode ui` post-UI is the ML training data — must stay full res. The downscale runs inside the `if (!task.ui_bmp_path.empty() ...)` branch, which only has data when `g_both_capture=true`. |
| `NUM_WORKERS 2→4`, `MAX_QUEUE 16→32` | PNG encode is ~10× slower than BMP memcpy. At 30fps × pre-UI 1080p ~50ms encode = ~1500ms work/sec → needs ≥2 dedicated cores. Doubled both with margin. |
| Trailing sync `frame=None` (from prior session, still load-bearing) | dHash on post-final-input HUD state is brittle (20-40 bit run-to-run variance). Wall-clock wait is the robust guarantee. |

## Current State

**Working** (verified offline + addon build):
- Full BMP → PNG pipeline. Addon emits PNG when `FC_UsePNG=1` (default), worker fn branches cleanly.
- Post-UI 540p downscale gated by `g_both_capture` AND `g_post_ui_dscale_w/h > 0`.
- `scripts/verify_replay.py` 33/33 pass against the new `.png`-fixture tests.
- `scripts/build.ps1` produces `dist/frame_capture.addon` (210 KB).
- `scripts/build-exe.ps1` produces `dist-exe/unicap.exe` (59.7 MB) + `unicap-1.0.5.zip` (81.3 MB) with `profiles/` correctly bundled.

**Not yet exercised live**:
- Actual fps gain on FF7R (the whole point of this work).
- Whether 540p is enough resolution for VLM driver to read HUD text.
- Whether 4 workers + 32 queue is enough headroom under sustained 30fps capture.

**Open / Known limits**:
- Auto-play stuck on non-modal popups (out of scope; needs region-based or VLM detection).
- `tools/capture/capture_all.py:_thread_input` line 76 still has the `GetKeyboardState` daemon-thread bug noted in earlier handoffs — not addressed in this session, affects HDF5 `/kb` for ML training.

**Uncommitted**: nothing. Working tree clean. `.env` is sponsor-local and gitignored.

## Files to Know

| File | Why It Matters |
|---|---|
| `reshade-addons/99-frame_capture/frame_capture.cpp` | All PNG/downscale logic. `save_worker_fn` (~ line 125-200) has the encode branch. Globals + ini reader near top of file. `NUM_WORKERS=4`, `MAX_QUEUE=32` near line 86. |
| `main.py` | Line 947: `[VIDEO]` announcement. Lines 1008-1017: `_depth_path_for` extension swap. Line 1052: `*BackBuffer.png` glob. All argparse `--color` help strings updated. |
| `scripts/build-exe.ps1` | Nuitka standalone build. Lines 110-115: `--include-data-dir` list. Lines 147-156: `$required` preflight. **Don't ship without `profiles/` here again.** |
| `scripts/build.ps1` | C++ build. Wraps MSBuild. `-Rebuild` flag forces ReShade core rebuild too. |
| `scripts/verify_replay.py` | 33 offline tests. Now uses `.png` fixtures. Sponsor's go-to before/after any replay-path change. |
| `tools/capture/pack_hdf5.py` | `_RE_A` / `_RE_B` regex updated to `(png|exr)`. Comment headers reference `BackBuffer.png` triplet. |
| `tools/auto_play/watchdog.py` / `vlm_driver.py` | `endswith(".png")` filters. `_BMP_MIN_AGE_S = 0.5` still tuned for ~50ms write time + safety margin (PNG isn't dramatically slower at 540p). |
| `profiles/ff7r.yaml` | Watchdog timing: `sample_period_s: 3.0`, `consecutive_static_required: 2` (= 6s recovery trigger). Don't touch without reason. |

## Code Context

**Worker function PNG branch** (`frame_capture.cpp:save_worker_fn`, current truth from commit `e59b5f0`):
```cpp
// Write color (RGBA8, 4 channels) — PNG (~3-4× smaller, slower encode) or BMP (uncompressed)
if (g_use_png)
    stbi_write_png(task.bmp_path.u8string().c_str(),
                   (int)color_w, (int)color_h, 4, color_src, (int)color_w * 4);
else
    stbi_write_bmp(task.bmp_path.u8string().c_str(),
                   (int)color_w, (int)color_h, 4, color_src);

// "Both" mode: also write the post-UI BB. This stream feeds watchdog / VLM
// (HUD / menu visibility) — full resolution is unnecessary, so downscale to
// FC_PostUIDownscaleW/H (default 960×540) when configured.
if (!task.ui_bmp_path.empty() && !task.ui_color_pixels.empty()) {
    const uint8_t* ui_src = task.ui_color_pixels.data();
    uint32_t ui_w = task.ui_width;
    uint32_t ui_h = task.ui_height;
    // First normalize to capture resolution if needed (matches existing behavior).
    std::vector<uint8_t> ui_resized;
    if (g_cap_width > 0 && g_cap_height > 0 &&
        (ui_w != g_cap_width || ui_h != g_cap_height)) {
        ui_resized.resize(g_cap_width * g_cap_height * 4);
        stbir_resize_uint8(ui_src, (int)ui_w, (int)ui_h, 0,
                           ui_resized.data(), (int)g_cap_width, (int)g_cap_height, 0, 4);
        ui_src = ui_resized.data();
        ui_w   = g_cap_width;
        ui_h   = g_cap_height;
    }
    // Then downscale post-UI stream specifically (only applies in both-mode).
    std::vector<uint8_t> ui_dscale;
    if (g_post_ui_dscale_w > 0 && g_post_ui_dscale_h > 0 &&
        (ui_w > g_post_ui_dscale_w || ui_h > g_post_ui_dscale_h)) {
        ui_dscale.resize((size_t)g_post_ui_dscale_w * g_post_ui_dscale_h * 4);
        stbir_resize_uint8(ui_src, (int)ui_w, (int)ui_h, 0,
                           ui_dscale.data(),
                           (int)g_post_ui_dscale_w, (int)g_post_ui_dscale_h, 0, 4);
        ui_src = ui_dscale.data();
        ui_w   = g_post_ui_dscale_w;
        ui_h   = g_post_ui_dscale_h;
    }
    if (g_use_png)
        stbi_write_png(task.ui_bmp_path.u8string().c_str(),
                       (int)ui_w, (int)ui_h, 4, ui_src, (int)ui_w * 4);
    else
        stbi_write_bmp(task.ui_bmp_path.u8string().c_str(),
                       (int)ui_w, (int)ui_h, 4, ui_src);
}
```

**Ini knobs read at init** (`frame_capture.cpp` config-load block):
```cpp
reshade::get_config_value(nullptr, "ADDON", "FC_UsePNG",            g_use_png);
reshade::get_config_value(nullptr, "ADDON", "FC_PostUIDownscaleW",  g_post_ui_dscale_w);
reshade::get_config_value(nullptr, "ADDON", "FC_PostUIDownscaleH",  g_post_ui_dscale_h);
```

**Cleanup-grace adaptive polling** (`main.py:_run_replay` lines 691-722, current truth from commit `80ca317`):
```python
if scratch.exists():
    stable_window_s = 0.6
    sample_period_s = 0.15
    deadline = time.monotonic() + 5.0
    prev_count = -1
    stable_since: float | None = None
    while time.monotonic() < deadline:
        try:
            count = sum(1 for _ in scratch.iterdir())
        except OSError:
            count = prev_count
        now = time.monotonic()
        if count == prev_count:
            if stable_since is None:
                stable_since = now
            elif now - stable_since >= stable_window_s:
                break
        else:
            prev_count = count
            stable_since = None
        time.sleep(sample_period_s)
    for attempt in range(3):
        try:
            shutil.rmtree(scratch)
            break
        except OSError as e:
            if attempt == 2:
                print(f"[REPLAY] WARN: 清理 {scratch} 失败: {e}", flush=True)
            else:
                time.sleep(0.2)
```

## Resume Instructions

1. **Confirm state**: `git log --oneline -1` → `3fab8a4 fix(build-exe): bundle profiles/ ...`. `git status` clean.
2. **Sponsor live-verify the fps gain**:
   - `cd D:\dev\unicap.git` and either `uv run main.py launch ...` (dev) or unzip `unicap-1.0.5.zip` and run `unicap.exe launch ...` (release path).
   - Capture 60s in FF7R at `--ui-mode both --profile ff7`. Stop with F9.
   - In the session `frames/` dir, count `*BackBuffer.png` and divide by elapsed seconds. Target: 15-20 fps.
   - Open `%TEMP%\unicap\unicap.log1`. `Select-String "save queue full"` should return zero or a handful of lines.
3. **If queue-full warnings are frequent**:
   - First try `FC_UsePNG=0` in `%TEMP%\unicap\unicap.ini` to revert to BMP without rebuilding. Verifies the regression isn't elsewhere.
   - If revert fixes it, look at bumping `NUM_WORKERS` 4→6 and/or setting `stbi_write_png_compression_level=1` in `frame_capture.cpp` (faster encode, slightly larger files).
4. **If 540p post-UI is too fuzzy for VLM**:
   - Sponsor sets `FC_PostUIDownscaleH=720` in `unicap.ini` and `FC_PostUIDownscaleW=1280`. No rebuild needed.
5. **Update `auto-play` branch if relevant**:
   - `git checkout auto-play && git merge --ff-only master` (it's at `68e89c7`, would fast-forward cleanly).

## Setup Required

- FF7R at sponsor's path (`E:\games\ff7remake\…\ff7remake_.exe`)
- Profile `ff7` (resolves to `profiles/ff7r.yaml`, in repo)
- `dist/dxgi.dll` + `dist/frame_capture.addon` (auto-deployed by `launch`)
- For the EXE path: `unicap-1.0.5.zip` extracted to e.g. `E:\downloads\unicap-1.0.5\`
- `uv` for the dev path; `uv sync` for Python deps

## Edge Cases & Error Handling

- **Capture during a stuck popup**: 6s watchdog timing fires recovery within ~6-12s. Non-modal popups (game keeps animating) defeat watchdog → still stuck. Out of scope.
- **`--ui-mode no-ui` + `--auto-play`**: auto-overridden to `both` in `cmd_launch` so watchdog can see HUD. Explicit `--ui-mode no-ui` stays `no-ui`; watchdog falls back to pre-UI BMP, recovery quality drops.
- **Empty recording (no input events)**: trailing sync gated by `if self._events:` — empty recordings get no trailing sync (correct).
- **Cleanup-grace hard cap (5s)**: protects against a hung addon. Real-world stable in ~0.6-1.2s.
- **`FC_UsePNG=0` (escape hatch)**: addon falls back to BMP filenames + content. Python side still globs `*.png` only — so during fallback, capture sessions would have `.bmp` files that Python doesn't see. **If you flip `FC_UsePNG=0`, you must also temporarily revert Python globs to `.bmp`.** The escape hatch is for the addon-only / dev-side fps debugging, not a production rollback.
- **Old `.bmp` recordings under `_scenes/`**: deliberately broken (Q4=no compat). Sponsor must re-record any scene scripts.

## Warnings

- **DO NOT amend `3fab8a4` or earlier** — pushed to `master`. New commits on top.
- **DO NOT remove the `if self._events:` gate** on trailing-sync emission — empty-recording E2E test relies on it.
- **DO NOT lower dHash threshold back to 10** without per-sync override — sponsor's recordings will start failing on HUD-bearing scenes.
- **DO NOT change `_BMP_MIN_AGE_S = 0.5`** in watchdog/sync_match without testing — tuned to addon's per-frame write time + safety margin. PNG at 1080p is slower than BMP, but 0.5s still has headroom; if sponsor sees lots of `None`-frame reads in long captures, this is the first knob to look at.
- **DO NOT commit `.env`** — sponsor-local API keys.
- **`FC_UsePNG=0` is an addon-only switch** — see Edge Cases. Don't expect it to be a true production rollback without also reverting Python globs.
- **`tools/capture/capture_all.py:_thread_input` line 76** still has the `GetKeyboardState` daemon-thread bug — not fixed here, affects HDF5 `/kb` for ML training. Sponsor decision pending (changes column semantics).
