# Handoff: replay-scene v1.1 unattended pipeline live-verified — 1 open item

**Generated**: 2026-05-04 22:30 CST
**Branch**: `master` (HEAD = `80ca317`, pushed to `origin/master`)
**Status**: In Progress — replay/auto-play pipeline closed and live-verified on FF7R; only capture-fps design call remains

## Goal

Make `--replay-scene X --auto-play --auto-capture` work as a true unattended pipeline in FF7R: replay reaches scene → capture starts automatically → bot keeps playing → no human keypresses needed.

## Completed in this wave

### commit `68e89c7` (pushed to `origin/master`)

- [x] **Survey deferred** — `main.py:_run_replay` no longer runs survey before the game window is up. Check moved to `_interactive_loop` (~line 826) which fires it after replay completes, before first capture.
- [x] **Trailing time-marker sync** — `recorder.py:_poll_loop` emits `frame=None` sync at F7-press time. Player waits the full recorded duration before declaring "reached" (was finishing at last input event's `t_rel`, which is BEFORE the game settles the post-input transition). dHash on that post-input state was tried and proved brittle (HUD text variance) — see Failed Approaches.
- [x] **dHash threshold 10 → 16** in `sync_match.py` / `player.py` / `recorder.py:save()`. Press-syncs on loading screens still match cleanly; cross-run HUD-text noise no longer blocks matches.
- [x] **cv2.imread WARN flood silenced** — `watchdog.py` / `vlm_driver.py` / `sync_match.py` switched to `np.fromfile + cv2.imdecode`. Partial/locked BMPs now return `None` silently instead of OpenCV printing `can't open/read file: check file path/integrity` to stderr.
- [x] **ff7r watchdog tightened** — `profiles/ff7r.yaml`: `sample_period_s: 6→3`, `consecutive_static_required: 3→2`. Modal popups (e.g. "Locking Onto Targets" tutorial) freeze frames; recovery now fires in 6s instead of 18s, presses M to dismiss.

### commit `80ca317` (pushed to `origin/master`)

- [x] **Cleanup-grace adaptive polling** — `main.py:_run_replay` finally (lines 691-722) replaces fixed 0.3s sleep + 3× × 0.1s retry with: poll `scratch.iterdir()` count, conclude addon is flushed when count stays unchanged across a 0.6s window, hard cap 5s. Live-verified on FF7R: no more `[REPLAY] WARN: 清理 ... 失败` on long replays.

### Sponsor live-verified

- [x] Recording: `[REPLAY-REC] trailing sync S-NN at X.Xs (time-only, no dHash)` printed as last recorder line.
- [x] `--replay-scene test --auto-play --auto-capture`: replay reaches scene with no R/Q prompt, capture starts automatically, bot takes over, no cleanup WARN.

## Not Yet Done

- [ ] **Capture-fps bottleneck — design call**. `--ui-mode both` (the auto-play default) produces ~5fps actual vs 30fps target because addon writes 2× 8MB BMPs + 11KB EXR per frame ≈ 480 MB/s sustained. Sponsor decision needed:
  - **(a)** default `--ui-mode no-ui` for unattended ML capture (halves write load → expect ~10fps; loses post-UI for watchdog/VLM)
  - **(b)** keep `both` and accept low fps
  - **(c)** addon-side BMP→PNG compression (3-4× saving, requires touching `frame_capture.cpp`'s capture path which currently calls ReShade's `runtime->capture_screenshot()`)

## Failed Approaches (Don't Repeat These)

- **Pre-replay survey check** (was lines 641-648 of `main.py:_run_replay`): ran survey before `focus_game_window()` was called → addon hadn't loaded → no probe frame received → survey timed out → replay aborted with exit code 3. Symptom: `[REPLAY] no survey cache, running survey first... [SURVEY] × 未收到探测帧 ... [REPLAY] survey failed; aborting replay` immediately after `[启动]`. **Don't add survey checks before the game window is confirmed up.**
- **dHash on the trailing sync** (first attempt at the trailing-sync feature, before this session's final form): emitted the trailing sync with a real BMP frame so player could dHash-verify the post-final-input scene. Best dist consistently 17-24 across runs (HUD text / random tutorial tip varies > threshold), so the sync ALWAYS missed → R/Q prompt → blocks `--auto-capture`. **Trailing sync must be `frame=None` (time-marker only).** Press-syncs and long-gap syncs in the middle of the script are fine to dHash because they typically land on loading screens / menu transitions where HUD is absent.
- **dHash threshold 10**: too tight for any sync that lands on a HUD-bearing frame. Bumped to 16 as the new default. If a specific scene still fails, override per-sync via `meta.json` `syncs[sid].hamming_threshold`.
- **`cv2.imread(str(path))` for live BMP polling**: OpenCV's path-based imread prints `[ WARN:1@...] global loadsave.cpp:278 cv::findDecoder imread_(...): can't open/read file` to stderr when the file is mid-write or briefly locked. Floods the console. Bytes-based `cv2.imdecode(np.fromfile(...))` returns None silently for the same failure modes.

## Key Decisions

| Decision | Rationale |
|---|---|
| Trailing sync uses `frame=None` (no dHash) | Wall-clock time alignment is the robust guarantee; visual verification on the post-input HUD frame is too brittle (run-to-run variance 20-40 bits). Press-syncs in the middle still do full dHash. |
| dHash default 16, not e.g. 24 | 16 still rejects clearly-different scenes (a totally wrong room is usually 30+ bits); 24 risks false positives. Sponsor can per-sync override in `meta.json` if a specific sync needs more slack. |
| Defer survey to `_interactive_loop`, not gate `_run_replay` on cached survey | `_interactive_loop` already had on-demand survey for the F8 path; reusing it makes the auto-capture path consistent and avoids touching survey code. |
| Watchdog 6s (not 3s or 12s) | Modal popups freeze frames immediately; 6s = 2 samples is the minimum that excludes single-sample noise. Cutscene false-positive risk is low because recovery first-step is `M` (no-op outside UI) followed by `ENTER` (advances cutscenes — desired side effect anyway). |

## Current State

**Working** (verified offline AND live on FF7R):
- All 33 `verify_replay.py` tests pass.
- Full `--replay-scene + --auto-play + --auto-capture` pipeline: deploy → focus window → replay (with trailing time-marker) → reaches via wall-clock + final dHash press-sync → `_interactive_loop` checks survey cache → runs survey if absent (game now in foreground, addon responsive) → starts capture → `--auto-play` bot takes over.
- Cleanup-grace polling: no `[REPLAY] WARN: 清理 ... 失败` on long replays.

**Open / Known limits**:
- Capture fps ~5 in `--ui-mode both` — see Not Yet Done.
- Auto-play stuck on non-modal popups (where bot's W keeps frame moving) — out of scope; needs region-based or VLM detection.

**Uncommitted**: nothing. Working tree clean. `.env` is sponsor-local and gitignored (despite earlier commit `43d7b95 add .env` adding a placeholder).

## Files to Know

| File | Why It Matters |
|---|---|
| `main.py:_run_replay` (~ line 628-724) | Survey-defer comment at top; cleanup-grace adaptive polling at the bottom (lines 691-722) — already closed |
| `tools/replay/recorder.py:_poll_loop` (~ line 389-420) | Trailing-sync emission lives at the end of this function; uses `frame=None` |
| `tools/replay/sync_match.py` | dHash + `wait_for_match`; default `threshold=16`; uses `np.fromfile + cv2.imdecode` |
| `tools/replay/player.py` | `_sync_threshold_default = 16`; null-frame sync handling at line ~154 (`if not frame: skipping match`) |
| `tools/auto_play/watchdog.py` | `_read_latest_bmp` uses `np.fromfile + cv2.imdecode`; FF7R timing in `profiles/ff7r.yaml`, NOT here |
| `tools/auto_play/vlm_driver.py:_read_latest_frame` | Same `np.fromfile + cv2.imdecode` pattern |
| `profiles/ff7r.yaml` | `watchdog.sample_period_s: 3.0`, `consecutive_static_required: 2` (= 6s recovery trigger); `keep_alive.recovery` first step is press M (already correct) |
| `scripts/verify_replay.py` | 33 offline tests; sponsor's go-to before/after any replay code change |

## Code Context

**Trailing sync emission** (`recorder.py:_poll_loop` end — current truth):
```python
# F7 (or manual stop) — emit a trailing time-marker sync at the actual
# stop moment so the player waits for the in-game state to settle
# (menu transition / loading screen still in flight after last input)
# before declaring "reached". frame=None deliberately: dHash on the
# post-final-input state is brittle (HUD text / random tip / animation
# state vary 20-40 bits across runs); the wall-clock wait is the
# robust guarantee. Press/long-gap syncs continue to do full dHash.
if self._events:
    stop_t_rel = time.monotonic() - (self._t_start or time.monotonic())
    if self._last_input_t_rel is None or stop_t_rel > self._last_input_t_rel:
        self._sync_count += 1
        sid = f"S-{self._sync_count:02d}"
        self._events.append({"type": "sync", "id": sid, "frame": None,
                             "t_rel": stop_t_rel,
                             "description": "trailing time-marker"})
        print(f"[REPLAY-REC] trailing sync {sid} at {stop_t_rel:.1f}s "
              "(time-only, no dHash)", flush=True)
```

**Cleanup-grace adaptive polling** (`main.py:_run_replay` lines 691-722 — current truth, commit `80ca317`):
```python
finally:
    backend.close()
    _set_state(game_dir, "idle")
    # Poll for scratch-dir BMP count to stabilize before rmtree. Player
    # already cleared fc_output_dir.txt in its finally; here we wait until
    # the count stays put across a 0.6s window (= addon has finished its
    # in-flight write). Hard cap 5s in case the addon is hung on heavy I/O.
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
                count = prev_count  # transient; treat as no change
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
                    print(f"[REPLAY] WARN: 清理 {scratch} 失败: {e}",
                          flush=True)
                else:
                    time.sleep(0.2)
```

**Pattern to copy when reading polled BMPs** (silences cv2 WARN flood):
```python
try:
    data = np.fromfile(str(latest_path), dtype=np.uint8)
except OSError:
    return None
if data.size < 100:                          # too small for valid BMP header
    return None
img = cv2.imdecode(data, cv2.IMREAD_COLOR)
if img is None:
    return None
```

## Resume Instructions

1. **Confirm state**: `git log --oneline -1` should show `80ca317 fix(replay): poll scratch BMP count ...`. `git status` clean.
2. **Capture-fps design call** with sponsor — pick (a) / (b) / (c) from Not Yet Done. (a) and (b) are CLI/default-flip changes; (c) means editing `frame_capture.cpp`'s capture path (currently calls ReShade's `runtime->capture_screenshot()`, which always emits BMP).
3. **Implement** the chosen option.
4. **Verify offline**: `uv run python scripts/verify_replay.py` → expect `== 33/33 passed, 0 failed ==`. Sponsor's `verify_auto_play.py` is per-CLAUDE.md NOT to be auto-run by agent.
5. **Sponsor live-verify** end-to-end fps measurement on FF7R (count BMPs / capture duration).

## Setup Required

- FF7R install at sponsor's path (`E:\games\ff7remake\…\ff7remake_.exe`)
- Profile `ff7` (resolves to `profiles/ff7r.yaml`, in repo)
- ReShade `dxgi.dll` in `dist/` (auto-deployed by `launch`)
- `uv` installed; `uv sync` for Python deps

## Edge Cases & Error Handling

- **Capture during a stuck popup**: with the new 6s watchdog timing, recovery should fire within ~6-12s of the popup appearing. If popup is non-modal (game keeps animating), watchdog never sees static → still stuck. Out of scope.
- **`--ui-mode no-ui` + `--auto-play`**: currently auto-overridden to `both` in `cmd_launch` so watchdog can see HUD. If sponsor explicitly passes `--ui-mode no-ui`, it stays `no-ui`; watchdog falls back to pre-UI BMP, recovery quality drops. CLAUDE.md documents this.
- **Trailing sync when recording is empty (no input events)**: gated by `if self._events:` — empty recordings don't get a trailing sync (correct: nothing to wait for).
- **Cleanup-grace hard cap (5s)**: protects against a hung addon. Real-world replays observed stable in ~0.6-1.2s.

## Warnings

- **DO NOT commit `.env`** — sponsor-local API keys. `.env.example` is the public template.
- **DO NOT amend `80ca317` or earlier** — pushed to `master`. Make new commits on top.
- **DO NOT remove the `if self._events:` gate** on the trailing-sync emission — empty-recording E2E test relies on no trailing sync being added when there are no events.
- **DO NOT lower dHash threshold back to 10** without per-sync override — sponsor's recordings will start failing on HUD-bearing scenes.
- **DO NOT change `_BMP_MIN_AGE_S = 0.5`** in watchdog/sync_match without testing — it's tuned to addon's ~50ms BMP write time + safety margin.
- **`tools/capture/capture_all.py:_thread_input` line 76** still has the `GetKeyboardState` daemon-thread bug noted in earlier handoff — not fixed here, affects HDF5 `/kb` for ML training. Sponsor decision pending (changes column semantics).
