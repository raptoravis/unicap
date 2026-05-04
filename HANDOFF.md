# Handoff: record-scene v1.1 — E2E partial success, cleanup-grace tuning open

**Generated**: 2026-05-04 17:28 CST
**Branch**: `auto-play` (HEAD = `56a9f1d` pushed)
**Status**: In Progress — replay-side fixes verified live; recorder-side fix not yet exercised live; one new regression to tune

## Goal

Replace v1.0 manual `F6` sync hotkey with auto-sync (every press + long-gap fallback). Fix bugs uncovered during sponsor's first live record/replay sessions in FF7R.

## Completed (commit 56a9f1d, pushed)

- [x] F6 hotkey removed; F7 stops; sync now auto-emit by press-sync + long-gap
- [x] `_emit_auto_sync` BMP race fix: `_latest_scratch_bmp(min_age_s=0.1)` + 3× copy retry / 50ms backoff
- [x] `_read_state` swapped to 256× `GetAsyncKeyState` (daemon-thread safe; physical key state)
- [x] `focus_game_window()` + `wait_for_game_foreground()` in `tools/window_manager.py`; called from `_run_replay`
- [x] `_run_replay` finally: 300ms grace + rmtree retry 3× / 100ms backoff with visible WARN (this is the one to tune — see Not Yet Done)
- [x] `MANDATORY_RESERVED_KEYS` reduced to `{F7,F8,F9}`
- [x] `verify_replay.py` test assertion updated; all 33 tests pass

## Live E2E results (sponsor, this session, post-56a9f1d)

Command run: `launch --game-path "<ff7r>" --profile ff7 --replay-scene test --auto-play`
(Replay only — recording on disk was a pre-fix artifact. NO new recording done with the GetAsyncKeyState fix yet.)

Working ✓:
- `[REPLAY] 等待游戏窗口出现 (ff7remake_.exe, 最多 30s)...`
- `[REPLAY] 已聚焦游戏窗口 (hwnd=0x18103e)` — focus pull working
- `[WINDOW] 已强制 borderless 窗口模式` — borderless transition working
- `[REPLAY] sync S-01 matched (waited 0.9s, dist=0)`
- `[REPLAY] sync S-02 matched (waited 5.0s, dist=6)` — non-zero dist = real picture comparison
- `[REPLAY] sync S-03 matched (waited 0.6s, dist=3)` — non-zero dist = real picture comparison
- `[REPLAY] reached scene test in 39.0s (recorded 38.9s, drift +0.0s)`

Issue ✗:
- `[REPLAY] WARN: 清理 D:\unicap_output\ff7remake_\_scenes\test\_replay_frames 失败: [WinError 145] 目录不是空的。` — cleanup-grace timing too tight for a 39s replay (~1170 BMPs accumulated)

After replay, console correctly stopped at `[等待] 按 F8 = 采集` — sponsor expected auto-capture but only passed `--auto-play`. See Key Decisions for `--auto-capture` flag (existing, not new).

## Not Yet Done

- [ ] **Tune cleanup grace** in `main.py:_run_replay` finally — current 300ms + 3× × 100ms retry = 500ms worst case is insufficient for long replays. Recommended fix: 1.5s grace + 5× × 200ms retry (worst case 2.5s). Or smarter: poll until `len(list(scratch.iterdir()))` is stable for N ticks, then rmtree.
- [ ] **Live record E2E** — sponsor needs to do a full new recording with the GetAsyncKeyState recorder fix; verify console shows `[REPLAY-REC] auto-sync S-NN at X.Xs` lines per press, and that `script.jsonl` `syncs` count matches press count + long-gap firings. The current `_scenes/test/` is a pre-fix artifact — its `script.jsonl` may have only mouse_move events. See Edge Cases below.
- [ ] **Decide on `tools/capture/capture_all.py:_thread_input` GetKeyboardState bug** — same root cause; affects HDF5 `/kb` for ML training; out of scope for v1.1 record-scene.
- [ ] (Cosmetic) Stale F6 references in `docs/req/replay-scene.md`, `docs/designs/*_replay-scene.md` — left intentionally to preserve v1.0 design history. CLAUDE.md is the authoritative current-state doc.

## Failed Approaches (Don't Repeat)

- **200ms dedup on press-sync** — dropped per-key syncs in rapid combos (e.g. ENTER × 3 within 240ms), making replay susceptible to dropped keys when game stutters between presses. Same-tick multi-press merging is the only dedup that survived.
- **5s focus_game_window timeout** — too short. FF7R launcher → game PID handoff takes 10-30s on slow disks. Pulled to 30s.
- **`input()` after focus failure** — Enter steals focus back to console. Replaced with `wait_for_game_foreground()` polling.
- **`GetKeyboardState` in recorder daemon thread** — silently returns zeros (no message queue). Use `GetAsyncKeyState` instead.
- **`shutil.rmtree(scratch, ignore_errors=True)` immediately on player exit** — addon still finishing in-flight BMP writes; locked file silently kept; user saw 4 GB leftover. Replaced with grace + retry + visible WARN. Now needs the grace itself extended (open task).
- **Initial cleanup grace 300ms / retry 3× / 100ms backoff** — partially insufficient: short replays clean fine, 39s+ replays leave the WARN. Bigger grace needed.

## Key Decisions

| Decision | Rationale |
|---|---|
| Auto-capture is `--auto-capture`, NOT `--auto-play` | `--auto-play` only injects bot input *during* capture; it does not skip the F8 wait. Skipping F8 is the role of `--auto-capture`. Three-flag combo `--replay-scene X --auto-play --auto-capture` is the unattended pipeline (CLAUDE.md:36-38). |
| GetAsyncKeyState 256× / tick (~1ms / tick) | acceptable overhead at 120Hz; F7 stop already proved this API works in the recorder daemon thread. |
| `min_age_s=0.1` for recorder BMP picker (vs 0.5 for sync_match) | recorder needs gap-end picture, can't be 500ms stale. 100ms = addon write time (50ms) + frame interval safety. |
| F6 NOT removed from profile YAMLs | extra entries in `reserved_keys` are harmless; prevents breaking sponsor's external profiles. |
| Cleanup grace > silently-failing rmtree | visible WARN tells sponsor when cleanup fails (better than silent 4GB residue). Currently the grace is just too short for long replays. |

## Current State

**Working** (verified live this session):
- `launch --replay-scene X --auto-play` — replay reaches scene; focus pull, borderless transition, sync matching all functional
- `--auto-play` correctly does NOT skip F8 (by design)
- Cleanup WARN is visible (the fix from this session is firing — just timing too tight)

**Working** (verified offline only):
- All 33 `verify_replay.py` tests pass
- Recorder smoke: `t_recorder_smoke_save`, `t_recorder_sidecar_cleanup`, `t_e2e_record_then_replay_round_trip` all pass

**Not yet exercised live**:
- Recording with the GetAsyncKeyState fix (sponsor only ran replay this session; their `_scenes/test/` recording predates the fix)
- `--auto-capture` three-flag pipeline

**Broken / Open**:
- Cleanup of `_replay_frames/` after long (>20s) replays — leaves ~1000+ BMPs on disk; subsequent replay's rmtree at start handles it but interim disk usage is ~4-9 GB

**Uncommitted**: only `.env` (sponsor-local — DO NOT commit).

## Files to Know

| File | Why It Matters |
|---|---|
| `main.py:_run_replay` (~line 692-712) | Where the cleanup grace lives. **The file to edit for the cleanup-grace tuning.** |
| `tools/replay/recorder.py` | Auto-sync logic; GetAsyncKeyState in `_read_state`; `_emit_auto_sync` BMP race fix |
| `tools/window_manager.py` | `focus_game_window` + `wait_for_game_foreground` (this session); `force_borderless_async` (existing) |
| `tools/replay/sync_match.py` | dHash + `_read_latest_bmp(min_age_s=0.5)` — reference implementation for grace-based race avoidance |
| `tools/auto_play/profile.py` | `MANDATORY_RESERVED_KEYS = {"F7","F8","F9"}` |
| `CLAUDE.md` | Authoritative current-state doc; --auto-capture / --auto-play / --replay-scene combos at lines 36-38 |
| `D:\unicap_output\ff7remake_\_scenes\test\` | Pre-fix recording from earlier this session; sponsor should DELETE before fresh recording. Currently has ~9 GB `_replay_frames/` leftover from this run. |

## Code Context

**Cleanup-grace location to tune** (`main.py:_run_replay`):
```python
finally:
    backend.close()
    _set_state(game_dir, "idle")
    # Let addon see the cleared sidecar and finish its in-flight BMP write
    # before we rmtree (otherwise the locked file gets skipped silently).
    time.sleep(0.3)                            # ← extend this (recommend 1.5)
    if scratch.exists():
        for attempt in range(3):               # ← extend retries (recommend 5)
            try:
                shutil.rmtree(scratch)
                break
            except OSError as e:
                if attempt == 2:               # ← update terminal index
                    print(f"[REPLAY] WARN: 清理 {scratch} 失败: {e}",
                          flush=True)
                else:
                    time.sleep(0.1)            # ← extend backoff (recommend 0.2)
return result.exit_code
```

**Alternative (smarter) cleanup**: poll for empty/stable dir before rmtree:
```python
# Wait for addon to fully drain (no new BMPs for N consecutive ticks)
import time as _t
prev_count, stable_ticks = -1, 0
deadline = _t.monotonic() + 3.0
while _t.monotonic() < deadline:
    cur_count = sum(1 for _ in scratch.iterdir()) if scratch.exists() else 0
    if cur_count == prev_count:
        stable_ticks += 1
        if stable_ticks >= 3:  # 600ms stable → safe to rmtree
            break
    else:
        stable_ticks = 0
    prev_count = cur_count
    _t.sleep(0.2)
# then rmtree as before
```
Pro: adapts to whatever the addon's flush rate is. Con: more code.

**Sync trigger logic** (already committed, here for reference):
```python
if evts:
    long_gap = (self._last_input_t_rel is not None
                and t_rel - self._last_input_t_rel > self._auto_sync_gap_s)
    has_press = any(e["type"] in _PRESS_EVENT_TYPES for e in evts)
    if long_gap and self._last_input_t_rel is not None:
        self._emit_auto_sync(self._last_input_t_rel + 0.1)
    elif has_press:
        self._emit_auto_sync(t_rel - 0.001)
    self._events.extend(evts)
    self._last_input_t_rel = t_rel
```

## Resume Instructions

1. **Confirm state**: `git log --oneline -1` should show `56a9f1d feat(replay): ...`. `git status -s` should show only `M .env`.
2. **Pick cleanup-grace approach** with sponsor:
   - Option A (simple): Extend constants — `time.sleep(0.3)` → `time.sleep(1.5)`, retries `3` → `5`, backoff `0.1` → `0.2`. Worst case 2.5s.
   - Option B (smarter): Poll for stable BMP count before rmtree (see code above).
3. **Implement chosen option** in `main.py:_run_replay` finally (~line 692-712).
4. **Verify offline**: `uv run python scripts/verify_replay.py`
   - Expected: `== 33/33 passed, 0 failed ==`
5. **Live verify** (sponsor): full record → replay round trip with auto-capture.
   - First, manually clean disk: `rm -r D:\unicap_output\ff7remake_\_scenes\test`
   - Run record: `uv run main.py launch --game-path "<ff7r>" --profile ff7 --record-scene test`
   - Press a few keys (e.g. ENTER × 3) and F7 to stop.
   - Expected console: `[REPLAY-REC] auto-sync S-01 at X.Xs (gap > 1.5s)` per press, then `saved ... (NN inputs / MM syncs)` with MM ≥ press count.
   - If sync count is suspicious (= 0 or only mouse_move events), the recorder fix didn't take effect on this build — `git diff 56a9f1d HEAD -- tools/replay/recorder.py` should show the GetAsyncKeyState swap.
   - Run replay: `uv run main.py launch --game-path "<ff7r>" --profile ff7 --replay-scene test --auto-play --auto-capture`
   - Expected console: focus + 3-step pipeline; replay completes; capture starts immediately (no F8 wait); after replay, **NO `[REPLAY] WARN: 清理 ... 失败`** if cleanup-grace tuning is correct.

## Setup Required

- FF7R install at sponsor's path (E:\games\ff7remake\…\ff7remake_.exe)
- Profile `ff7` (resolves to `profiles/ff7r.yaml`, exists in repo)
- ReShade `dxgi.dll` in `dist/` (auto-deployed by `launch`)
- `uv` installed; project deps via `uv sync`

## Edge Cases & Error Handling

- **Sponsor's existing `_scenes/test/`**: pre-fix recording from earlier this session; `script.jsonl` may be missing key events (only mouse_move). Verify by `cat _scenes/test/script.jsonl | head` — if no `key_down` lines, recording is broken and replay results from this session are coincidence on dHash matching loading screens.
- **Long replay (> 20s)**: cleanup WARN expected until grace is tuned. Disk usage grows ~30 BMPs/s × 8MB = 240MB/s during replay. 39s replay = ~9 GB.
- **`_replay_frames/` not cleaned**: next `--replay-scene <name>` run will rmtree it at start of `_run_replay` (player.run sets fc_output_dir then does mkdir; no explicit pre-rmtree but scratch_dir is already inside scene_dir which the start path reuses).
  - Actually verify this: search `tools/replay/player.py` for whether scratch is wiped on entry. If not, residual files might confuse dHash matching on the next replay.

## Warnings

- **DO NOT commit `.env`** — sponsor-local API keys etc.
- **DO NOT remove F6 from profile YAMLs** — works fine with F6 still listed; touching 4 files just to remove a harmless entry isn't worth the risk.
- **DO NOT amend 56a9f1d** — pushed to origin/auto-play already. Make a new commit on top.
- **DO NOT silently change `auto_sync_gap_s` default** without telling sponsor — it's the one knob that defines what counts as "long gap"; sponsor calibrated to 1.5s for FF7R.
- **`tools/capture/capture_all.py:_thread_input`** has the same `GetKeyboardState` bug (line 76). NOT fixed here. Fixing it would change `/kb` HDF5 column semantics — separate sponsor decision.
- **Live records before fix**: any `_scenes/<name>/script.jsonl` recorded before commit 56a9f1d may have only mouse_move events. Sponsor must re-record after the fix to get real key/mouse-button/gamepad events.
