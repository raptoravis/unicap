# Handoff: record-scene v1.1 — auto-sync (no F6) + 4 bug fixes

**Generated**: 2026-05-04 17:12 CST
**Branch**: `auto-play`
**Status**: In Progress — code complete, **live-game E2E not yet run successfully**

## Goal

Replace v1.0 manual `F6` sync hotkey with auto-sync (every press + long-gap fallback), fix several bugs that surfaced during sponsor's first live record/replay session.

## Completed (committed earlier in session)

- [x] F6 hotkey removed from `recorder._hotkey_loop` — only F7 (stop) remains
- [x] Auto-sync logic in `recorder._poll_loop`:
  - long-gap fallback at gap start when input idle ≥ `auto_sync_gap_s` (default 1.5s)
  - press-sync just before `key_down` / `mouse_button_down` / `gamepad_button_down`
  - same-tick multi-press → 1 sync (one BMP, no extra dedup)
- [x] `MANDATORY_RESERVED_KEYS` in `tools/auto_play/profile.py`: `{F6,F7,F8,F9}` → `{F7,F8,F9}`
- [x] `scripts/verify_replay.py` test assertion updated to `{F7,F8,F9}` ⊆ reserved_keys
- [x] All 33 offline tests pass on every change

## Completed this session (uncommitted — waiting for commit step)

- [x] **Bug 1 fix** — WinError 32 on auto-sync BMP copy (sharing violation): `recorder._latest_scratch_bmp(min_age_s=0.1)` skips in-flight BMPs; `_emit_auto_sync` retries copy 3× / 50ms backoff
- [x] **Bug 2 fix** — recorder caught zero key events from FF7R: `recorder._read_state()` swapped from `GetKeyboardState` (returns stale per-thread state in a windowless daemon thread) to 256× `GetAsyncKeyState(vk)` loop (physical key state)
- [x] **Bug 3 fix** — replay's SendInput went to console, not game window: new `tools/window_manager.py:focus_game_window()` (SetForegroundWindow + SwitchToThisWindow + 300ms settle) called from `main.py:_run_replay`. 30s timeout (matches `force_borderless_async`). Fallback `wait_for_game_foreground()` polls until exe_basename matches — user can alt-tab without pressing Enter.
- [x] **Bug 4 fix** — `_replay_frames/` left ~520 BMPs (~4 GB) after replay because rmtree silently skipped locked files: `main.py:_run_replay` finally now sleeps 300ms (let addon stop on cleared sidecar) then rmtree retries 3× / 100ms backoff with visible WARN if final attempt fails
- [x] CLAUDE.md updated for press-sync + long-gap docstring

## Not Yet Done

- [ ] **Sponsor E2E live test** in FF7R: delete `D:\unicap_output\ff7remake_\_scenes\test\` then run `--record-scene test` (record arrow keys + Enter sequence to enter game), then `--replay-scene test` and verify game auto-plays through to the recorded endpoint
- [ ] Decide whether to fix `tools/capture/capture_all.py:_thread_input` (same `GetKeyboardState` bug → `/kb` HDF5 column may be all-zero for daemon-thread captures, affects ML training data semantics)
- [ ] Optional: clean up F6 references in `docs/req/replay-scene.md` and `docs/designs/*_replay-scene.md` (left as-is to preserve v1.0 design history)

## Failed Approaches (Don't Repeat)

- **200ms dedup on press-sync** — initial draft skipped sync if previous sync was < 200ms ago. User correctly rejected: rapid combo (e.g. ENTER × 3 within 240ms) loses sync coverage on calls 2 and 3, and at replay time if the game stutters between presses, those keys get eaten because there's no dHash wait. Same-tick multi-press merging is the only dedup that survived.
- **5s focus_game_window timeout** — too short. FF7R launcher → game PID handoff takes 10-30s on slow disks. Pulled to 30s to match `force_borderless_async`.
- **`input()` after focus failure** — original fallback asked user to alt-tab then press Enter. User pointed out the Enter steals focus back to console. Replaced with `wait_for_game_foreground()` polling.
- **`GetKeyboardState` in recorder daemon thread** — silently returns zeros because thread has no message queue. Bug only surfaced when sponsor saw `script.jsonl` had only 1 mouse_move event despite 3 ENTER presses. `GetAsyncKeyState` returns physical state regardless of thread.
- **`shutil.rmtree(scratch, ignore_errors=True)` immediately on player exit** — addon was still finishing in-flight BMP write, file was locked, ignore_errors silently kept the file. 300ms grace + retry with visible failure warning.

## Key Decisions

| Decision | Rationale |
|---|---|
| Press-sync (not long-gap-only) | sponsor scenario: rapid menu navigation in FF7R. Long-gap (1.5s) misses every per-key animation slip. Per-press is rugged. |
| No dedup beyond same-tick | bandwidth cost (~600MB sync pool / 30s recording) is trivial vs unicap's GB-scale dataset; rapid-combo coverage matters more |
| Long-gap fallback retained | catches mouse-look-only segments (no input but loading/cinematic) where press-sync alone wouldn't fire |
| GetAsyncKeyState 256× / tick | ~1ms / tick, ~3% CPU at 120Hz — fine. `_HOTKEY_VKS={VK_F7}` already proves GetAsyncKeyState works in this thread (F7 stop has been working). |
| `min_age_s=0.1` (not 0.5 like sync_match) | recorder needs gap-end picture, can't be 500ms stale; 100ms = addon write time (50ms) + frame interval safety |
| F6 NOT removed from profile YAMLs | extra entries in reserved_keys are harmless; sponsor's external profiles (if any) won't break |

## Current State

**Working** (offline): All 33 verify_replay.py tests pass. Smoke imports clean.

**Working** (live, partially verified): `--record-scene test` UI shows correct hint box. Console focus message shows when launching `--replay-scene`.

**Not yet verified** (live): Full record → replay round trip in FF7R after all 4 bug fixes. Last live attempt prior to fixes 2/3/4 produced `(290 inputs / 2 syncs)` (long-gap-only era) and `(1 mouse_move / 0 syncs)` (GetKeyboardState era).

**Uncommitted Changes** (5 files):
```
M .env                      ← sponsor's env, leave alone
M CLAUDE.md                 ← press-sync docstring
M main.py                   ← focus_game_window integration + scratch cleanup
M tools/replay/recorder.py  ← GetAsyncKeyState + BMP min_age + copy retry
M tools/window_manager.py   ← focus_game_window, wait_for_game_foreground
```

## Files to Know

| File | Why It Matters |
|---|---|
| `tools/replay/recorder.py` | Core auto-sync logic; `_poll_loop`, `_emit_auto_sync`, `_latest_scratch_bmp`, `_read_state` |
| `tools/window_manager.py` | Game window focus management — both `force_borderless_async` (existing) and `focus_game_window` / `wait_for_game_foreground` (new this session) |
| `main.py:_run_replay` (~line 657-700) | Replay flow: focus → recenter → InputBackend → ReplayPlayer → cleanup |
| `tools/replay/player.py` | Time-driven event injection + sync wait. Untouched this session. |
| `tools/replay/sync_match.py` | dHash + `wait_for_match`. `_read_latest_bmp(min_age_s=0.5)` was the inspiration for recorder's race-fix. |
| `tools/auto_play/profile.py` | `MANDATORY_RESERVED_KEYS = {"F7","F8","F9"}` |

## Code Context

**Auto-sync trigger logic** (`recorder._poll_loop`):
```python
if evts:
    long_gap = (self._last_input_t_rel is not None
                and t_rel - self._last_input_t_rel > self._auto_sync_gap_s)
    has_press = any(e["type"] in _PRESS_EVENT_TYPES for e in evts)
    # long-gap takes priority when both apply
    if long_gap and self._last_input_t_rel is not None:
        self._emit_auto_sync(self._last_input_t_rel + 0.1)
    elif has_press:
        self._emit_auto_sync(t_rel - 0.001)
    self._events.extend(evts)
    self._last_input_t_rel = t_rel
```

**Press event types** that trigger sync:
```python
_PRESS_EVENT_TYPES = frozenset({
    "key_down", "mouse_button_down", "gamepad_button_down",
})
```

**Key API swap** in `_read_state`:
```python
# Was (broken in daemon thread):
# kb_arr = (ctypes.c_ubyte * 256)()
# _user32.GetKeyboardState(kb_arr)

# Now:
kb = [0] * 256
for vk in range(256):
    if _user32.GetAsyncKeyState(vk) & 0x8000:
        kb[vk] = 0x80  # mimic GetKeyboardState's "high bit = down"
```

**Replay focus flow** (`main.py:_run_replay`):
```python
hwnd = focus_game_window(exe_basename=game_exe_name, timeout_s=30.0)
if hwnd is None:
    hwnd = wait_for_game_foreground(game_exe_name, timeout_s=60.0)
    if hwnd is None:
        return 2  # user didn't alt-tab in time
recenter_cursor()
# ... player.run() ...
finally:
    backend.close()
    _set_state(game_dir, "idle")
    time.sleep(0.3)              # let addon stop on cleared sidecar
    if scratch.exists():
        for attempt in range(3):
            try: shutil.rmtree(scratch); break
            except OSError as e:
                if attempt == 2: print warning
                else: time.sleep(0.1)
```

## Resume Instructions

1. **Inspect uncommitted state**: `git diff --stat` should show the 5 files above. If anything else is modified, investigate before commit.
2. **Run offline tests** to confirm nothing regressed: `uv run python scripts/verify_replay.py`
   - Expected: `== 33/33 passed, 0 failed ==`
   - If fail: probably encoding or import issue introduced by an edit
3. **Commit + push** (the `/handoff-refresh` flow normally does this; if not, use `commit` skill)
4. **Live E2E** (sponsor task — can't run in CI):
   - Delete `D:\unicap_output\ff7remake_\_scenes\test` if it exists (it's a broken pre-fix artifact)
   - Run: `uv run main.py launch --game-path "<ff7r exe>" --profile ff7 --record-scene test`
   - Press ENTER several times in the game to advance launcher menus
   - Press F7 in console (or game window — F7 is global)
   - Expected console output:
     ```
     [REPLAY-REC] auto-sync S-01 at X.Xs (gap > 1.5s)
     ... one auto-sync per press ...
     [REPLAY-REC] saved ...\script.jsonl (NN inputs / MM syncs)
     ```
     `MM` should equal number of presses you made (+ a few long-gap firings)
   - Then: `uv run main.py launch --game-path "..." --profile ff7 --replay-scene test`
   - Expected:
     ```
     [REPLAY] 等待游戏窗口出现 (ff7remake_.exe, 最多 30s)...
     [WINDOW] 已强制 borderless ...
     [REPLAY] 已聚焦游戏窗口 (hwnd=0x...)
     [REPLAY] sync S-01 matched (waited X.Xs, dist=N)  ← dist should be small but NOT all 0
     ...
     [REPLAY] reached scene test in X.Xs (recorded X.Xs, drift +X.Xs)
     ```
     The game should visibly auto-press through the same menu sequence
   - After replay ends, check `D:\unicap_output\ff7remake_\_scenes\test\_replay_frames\` — should be **gone or empty** (cleanup fix verified)
   - If `_replay_frames/` still has BMPs, the `[REPLAY] WARN: 清理 ... 失败` line in console says why; addon may need more than 300ms grace

## Setup Required

- Existing FF7R install at the path the sponsor has been using (E:\games\ff7remake\...\ff7remake_.exe)
- Profile `ff7` exists (`profiles/ff7r.yaml`, exists in repo)
- ReShade `dxgi.dll` already deployed (auto-deployed by `launch`)

## Edge Cases & Error Handling

- **Same-tick multi-press**: 1 sync emitted, BMP reflects that frame. ✓ tested
- **Long-gap + press in same tick**: long-gap branch wins (sync at gap start, not press time). Subsequent presses still get their own sync if they're > 1 tick apart.
- **All sync BMPs `frame=null`**: addon never wrote BMPs to scratch. Means `fc_output_dir.txt` sidecar wasn't picked up. Check `recorder.start()` writes the sidecar before threads launch.
- **`focus_game_window` finds wrong window**: matches by exe basename via `_query_image_basename`, so launchers (Steam / FF7R) sharing exe name with the game would conflict. Not seen in practice.

## Warnings

- **DO NOT remove F6 from profile YAMLs** — tested working with F6 still in `reserved_keys` lists. Removing requires editing 4 files and might break sponsor's external profiles.
- **`GetAsyncKeyState` reads 256 keys per tick** — looks like overhead but verified ~1ms / tick at 120Hz. If you want to optimize, only loop over `_VK_TO_NAME.keys()` (≈ 80 keys) but make sure mouse-button VKs (0x01/0x02/0x04) and any vk in `_GAMEPAD_BIT_NAMES` consumers stay covered.
- **`_recording_frames/` cleanup** is in `recorder.close()` (existing code, unchanged), uses `shutil.rmtree(..., ignore_errors=True)`. The same race fix applied to `_replay_frames` should arguably apply here too — but record stops on user F7 (not a tight sidecar/rmtree race) so it tends to work. Verify if you re-record and see leftover `_recording_frames/` BMPs.
- **Stale doc files**: `docs/req/replay-scene.md` and `docs/designs/*_replay-scene.md` still describe F6 manual sync as the v1.0 design. Left intentionally — they document v1.0, this session implements v1.1. CLAUDE.md is the authoritative current-state doc.
- **`tools/capture/capture_all.py` has the same GetKeyboardState bug** (`_thread_input`, line 76). NOT fixed here. If sponsor cares about HDF5 `/kb` data integrity for ML training, that's a separate fix. Same one-line API swap will work.
