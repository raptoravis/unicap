# Handoff: GetKeyboardState daemon-thread fix landed on auto-play; master not yet updated

**Generated**: 2026-05-04 22:40 CST
**Branch**: `auto-play` (HEAD = `f6e1d0c`, in sync with `origin/auto-play`)
**Status**: Ready for Review — code-side fix committed; only docs cleanup + branch alignment remain.

## Goal

Pre-emptively close the `GetKeyboardState` daemon-thread bug listed as a known limit in the prior handoff (`tools/capture/capture_all.py:_thread_input` line 76). The bug caused HDF5 `/kb` columns in every capture session to be all-zeros, silently breaking the keyboard channel of ML training data.

## Completed

- [x] **`tools/capture/capture_all.py:_thread_input`** — replaced `user32.GetKeyboardState(kb)` with a 256-entry `GetAsyncKeyState` loop that writes `0x80` into pressed-key slots. Mirrors the established in-repo pattern at `tools/replay/recorder.py:128-136` (which already documents this exact daemon-thread failure mode and chose the same trade-off). 6-line comment added explaining the *why*. Committed as `f6e1d0c update` on the `auto-play` branch.
- [x] **VLM auto-play status review** (no code change) — confirmed VLMDriver code-side complete since `f854ccc`; only blocking item is sponsor's 30min FF7R live-game test of `--driver vlm`. Not actionable from agent side.

## Not Yet Done

- [ ] **Decide whether to ff-merge `auto-play` → `master`**, or cherry-pick `f6e1d0c` onto `master`. Right now the fix only exists on `auto-play`. `master` is still at `0dd0143` and produces broken `/kb` columns. Per `CLAUDE.md` `master` is "the main branch" — almost certainly should also get this fix. Action: `git checkout master && git merge --ff-only auto-play && git push` (auto-play is exactly `master` + this one commit, so it'll fast-forward).
- [ ] **Update stale doc lines in `CLAUDE.md`**:
  - Line 142: `samples keyboard (`GetKeyboardState`)` → should now say `GetAsyncKeyState`.
  - Line 207: `capture_all._thread_input 用 `GetKeyboardState`/`XInput` 采集` — same swap. Sentiment ("bot input vs human input no difference") still holds because both paths see the same physical state. Trivial follow-up; could be folded into the merge commit or a separate `docs(claude-md):` commit.
- [ ] **Sponsor live-fps measurement on FF7R** (carried over from prior handoff): 60s capture in `--ui-mode both`, count `*BackBuffer.png` / wall-time, target 5 → 15-20 fps. Check `%TEMP%\unicap\unicap.log1` for `save queue full` lines. Escape hatches: `FC_UsePNG=0` in `unicap.ini` reverts to BMP; bump `NUM_WORKERS 4→6` if encode-bound.
- [ ] **Sponsor verify post-UI 540p readability for VLM** (carried over): if VLM struggles with HUD text at 540p, set `FC_PostUIDownscaleH=720` / `FC_PostUIDownscaleW=1280` in `unicap.ini`. No rebuild needed.
- [ ] **Sponsor 30min FF7R live test of `--driver vlm`** (carried over): only way to verify VLM action JSON parses cleanly under real game frames + that 1Hz decision rate is sufficient. Check `[VLM-COST]` lines in `%TEMP%/unicap/auto_play.log` for actual hourly cost.

## Failed Approaches (Don't Repeat These)

- **Don't use `GetKeyboardState` from a daemon polling thread**. It returns the calling thread's per-thread keyboard input queue state — for a thread with no window and no message pump, that queue is never updated, so the call returns zeros. This is the bug we just fixed, and `tools/replay/recorder.py:128-136` already had a comment explaining it; the in-repo precedent must be respected for any new daemon-thread input poller.
- **Don't preserve toggle bits (caps/num/scroll lock low bits)**. The fix mirrors `recorder.py`'s choice of writing only `0x80` (high bit = down) when the key is physically pressed. Toggle state is not available from `GetAsyncKeyState`. Old recordings had all-zero `/kb`, so toggle data was never preserved historically anyway — no consumer has been depending on it.
- **Don't try to parse the prior session's first git status output literally** — at session start the repo was on `master @ 3fab8a4` clean. Mid-session the user switched to `auto-play` and committed the edit themselves as `f6e1d0c update`. State shift was not driven by the agent; just documenting so the next agent doesn't get confused if they re-read the original handoff and find divergence.

## Key Decisions

| Decision | Rationale |
|---|---|
| Mirror `recorder.py:128-136` rather than invent a new approach | Established in-repo precedent; same daemon-thread problem; same byte-format compatibility (`high bit = down`). Drop-in replacement preserves the `pack_hdf5.py:18` schema doc semantics. |
| `kb = [0] * 256` Python list instead of `(ctypes.c_ubyte * 256)()` | Downstream code does `list(kb)` then JSON-serializes; a Python list is the cleanest path. No semantic change for the JSONL output. |
| Don't fix the `CLAUDE.md` docs in the same commit | Sponsor pushed `f6e1d0c` as a quick "update" — agent didn't get to bundle the doc fix. Rolled into "Not Yet Done" so the next agent picks it up. |
| Land the fix on `auto-play` first, master second | The previous handoff flagged that `auto-play` branch was stale at `68e89c7` (pre-PNG). Sponsor's `f6e1d0c` lands on `auto-play` (which is now `master + 1 commit`), implicitly choosing to bring auto-play current. master can ff-merge later in one step. |

## Current State

**Working** (verified by reading committed file):
- `tools/capture/capture_all.py:_thread_input` now polls `GetAsyncKeyState` per-key. `kb` field in `inputs.jsonl` will contain real data (`0x80` in pressed slots) instead of all-zeros.
- HDF5 `/kb` column going forward will have meaningful per-frame keyboard state for ML training.
- All other auto-play / capture / replay paths unchanged.

**Branch state**:
- `auto-play` at `f6e1d0c`, in sync with `origin/auto-play`.
- `master` at `0dd0143`, has *not* received the fix yet — captures done from `master` still produce broken `/kb`.
- `vulkan-support` and `claude/sharp-tesla-8a79a6` exist but are not in scope.

**Semantic shift to flag to ML consumers**:
- Old recordings: HDF5 `/kb` column was all zeros (junk).
- New recordings: `/kb` column has `0x80` in slots where keys were physically down at sample time.
- If anyone has been training models on the old-data assumption that `/kb` is meaningless and excluding the column, they need to know it's now meaningful.

**Uncommitted Changes**: none. Working tree clean.

## Files to Know

| File | Why It Matters |
|---|---|
| `tools/capture/capture_all.py` | The fix lives in `_thread_input` (lines 73-93). Any future change to per-frame input polling cadence / format must keep the `kb` schema compatible with `pack_hdf5.py:18`. |
| `tools/replay/recorder.py:122-136` | The reference pattern. Comment explains *why* `GetAsyncKeyState` is used in a polling thread; if you ever need to poll input from another daemon thread, copy this pattern. |
| `tools/capture/pack_hdf5.py:18` | Schema doc says `/kb uint8 (N, 256)` with "GetKeyboardState 字节数组" semantics. Comment is now technically inaccurate (we read via `GetAsyncKeyState`) but the *byte format* (`0x80 = down`) is preserved. Either leave or update the comment. Trivial. |
| `tools/auto_play/vlm_driver.py` | VLM driver; code-complete since `f854ccc`. Untouched this session; relevant only because `--driver vlm` live-test is one of the open items. |
| `scripts/verify_auto_play.py` | 38 offline checks for auto-play. Run before any auto-play change. Untouched this session. |
| `CLAUDE.md:142` and `:207` | Stale `GetKeyboardState` references. To update next session along with master ff-merge. |

## Code Context

**The committed fix** (`tools/capture/capture_all.py:_thread_input`, current truth from `f6e1d0c`):
```python
while not stop.is_set():
    t = time.time_ns()
    # GetAsyncKeyState polls the physical key state, independent of the
    # caller thread's message queue. GetKeyboardState would return all
    # zeros here (daemon thread → no window → no message queue → kb state
    # never updated). Mirror the byte format ("high bit = down") so the
    # schema documented in pack_hdf5.py and the recorder.py path stays
    # consistent. Toggle bits (caps/num/scroll lock) are not preserved.
    kb = [0] * 256
    for vk in range(256):
        if user32.GetAsyncKeyState(vk) & 0x8000:
            kb[vk] = 0x80
    pt = POINT()
    user32.GetCursorPos(ctypes.byref(pt))
    gamepad = None
    if xinput:
        state = XINPUT_STATE()
        if xinput.XInputGetState(0, ctypes.byref(state)) == 0:
            gamepad = _parse_xinput(state)
    log.append({"ts": t, "kb": list(kb), "mouse": [pt.x, pt.y], "gamepad": gamepad})
    stop.wait(1 / 120)
```

**Reference pattern** (`tools/replay/recorder.py:_read_state`, lines 126-137 — DO NOT modify, this is the exemplar):
```python
def _read_state() -> _State:
    s = _State()
    # GetAsyncKeyState returns the *physical* key state, independent of the
    # caller thread's message queue. GetKeyboardState would return all zeros
    # in a daemon polling thread (no window → no message queue → no keyboard
    # messages dispatched to update the per-thread state). 256 syscalls/tick
    # × 120Hz ≈ 30k syscalls/s ≈ 3% CPU — fine.
    kb = [0] * 256
    for vk in range(256):
        if _user32.GetAsyncKeyState(vk) & 0x8000:
            kb[vk] = 0x80  # mimic GetKeyboardState's "high bit = currently down"
    s.kb = kb
```

**JSONL schema** (`inputs.jsonl`, one entry per 120Hz tick) — unchanged, only the `kb` content quality changed:
```json
{"ts": 1746368420123456789, "kb": [0, 0, 128, 0, ...256 entries...], "mouse": [960, 540], "gamepad": null}
```

## Resume Instructions

1. **Confirm state**: `git log --oneline -1` → should show `f6e1d0c update` on `auto-play`. `git status` clean. `git log master..auto-play --oneline` should show exactly `f6e1d0c update` (auto-play is master + 1).
2. **Bring `master` in line**:
   - `git checkout master`
   - `git merge --ff-only auto-play` → fast-forwards `master` to `f6e1d0c`.
   - `git push` → publishes the fix to `origin/master` so any sponsor running from `master` (the documented main branch) gets the real `/kb` data.
   - Expected: master ends at `f6e1d0c`. If `merge --ff-only` refuses, somebody pushed to master since this handoff was written; investigate before forcing.
3. **Clean up the doc staleness in the same merge commit OR a follow-up**:
   - Edit `CLAUDE.md:142`: `samples keyboard (\`GetKeyboardState\`)` → `samples keyboard (\`GetAsyncKeyState\`)`
   - Edit `CLAUDE.md:207`: `capture_all._thread_input 用 \`GetKeyboardState\`/\`XInput\` 采集` → `\`GetAsyncKeyState\`/\`XInput\``
   - Optionally also `tools/capture/pack_hdf5.py:18` comment.
   - `git commit -m "docs(claude-md): swap GetKeyboardState → GetAsyncKeyState in _thread_input refs"`.
4. **(Optional, if sponsor reports back on PNG fps)**: see "Edge Cases" below for the queue-full / 540p-too-fuzzy decision tree from the prior handoff.
5. **(Optional, no sponsor signal yet)**: pre-emptive VLM work — `--vlm-dry-run` flag (parse-only mode for first sponsor live test, doesn't inject), or prompt-cache-friendly system prompt restructure to lower Qwen-VL token cost. Both are speculative; do not start without user confirmation.

## Setup Required

Same as prior handoff. Nothing changed.
- FF7R at sponsor's path (`E:\games\ff7remake\…\ff7remake_.exe`).
- `dist/dxgi.dll` + `dist/frame_capture.addon` (auto-deployed by `launch`).
- `uv sync` for Python deps.
- For VLM live test: `.env` with `VLM_API_KEY` / `VLM_BASE_URL` / `VLM_MODEL` (sponsor-local, gitignored).

## Edge Cases & Error Handling

(Carried over from prior handoff — still apply, none new this session.)

- **Capture during stuck modal popup**: 6s watchdog timing fires recovery within ~6-12s. Non-modal popups still defeat watchdog (out of scope).
- **`--ui-mode no-ui` + `--auto-play`**: auto-overridden to `both` in `cmd_launch` so watchdog can see HUD. Explicit `--ui-mode no-ui` stays no-ui.
- **`FC_UsePNG=0` (escape hatch)**: addon falls back to BMP filenames + content. **Python side still globs `*.png` only** — flipping `FC_UsePNG=0` requires also reverting Python globs to `.bmp` for that session. Not a true production rollback path, only addon-side debugging.
- **Old `.bmp` recordings under `_scenes/`**: deliberately broken (Q4=no compat). Sponsor must re-record any scene scripts.
- **PNG queue-full (`save queue full, dropping frame` in `unicap.log1`)**: first try `FC_UsePNG=0` to verify PNG is the cause. If it is, bump `NUM_WORKERS 4→6` in `frame_capture.cpp` and/or set `stbi_write_png_compression_level=1` (faster encode, slightly larger files). Rebuild via `scripts\build.ps1`.
- **540p post-UI too fuzzy for VLM**: sponsor sets `FC_PostUIDownscaleH=720` and `FC_PostUIDownscaleW=1280` in `%TEMP%\unicap\unicap.ini`. No rebuild needed.

## Warnings

- **DO NOT amend `f6e1d0c`** — it's pushed to `origin/auto-play`. New commits on top.
- **DO NOT change `if self._events:` gate** on trailing-sync emission in `tools/replay/recorder.py` — empty-recording E2E test relies on it.
- **DO NOT lower dHash threshold back to 10** without per-sync override — sponsor's recordings will start failing on HUD-bearing scenes.
- **DO NOT change `_BMP_MIN_AGE_S = 0.5`** in watchdog/sync_match without testing — tuned to addon's per-frame write time + safety margin.
- **DO NOT commit `.env`** — sponsor-local API keys.
- **DO NOT amend the `update` commit message** even though it's terse. The diff is small, the commit is on a feature branch, and amending pushed history is a worse outcome than a less-than-ideal commit message.
- **`master` produces broken `/kb` until somebody ff-merges from `auto-play`** — flag this in the merge commit message so the data-pipeline team / future ML training notice the cutover point.
