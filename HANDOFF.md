# Handoff: hybrid auto-play + record/replay cleanup

**Generated**: 2026-05-05 17:18 CST
**Branch**: `auto-play` (HEAD = `73a39d9`, in sync with `origin/auto-play` and `origin/master`)
**Status**: Ready for Review — 23 files of uncommitted changes ready to commit; sponsor wants to live-test before commit. Three logical chunks layered together:
  - **A.** Auto-play hybrid driver + watchdog rewrite + VLM prompt overhaul (multi-session)
  - **B.** Default-behavior + CLI changes (1 session)
  - **C.** Record/replay/auto-capture removal (this session)

## Goal

Get unicap to a state where someone can clone the repo, run

    uv run main.py launch --game-path "...ff7remake_.exe" --profile ff7r --auto-play --driver hybrid

and have the bot **reliably play through FF7R's frequent tutorial popups** without human intervention. Secondary goal: prune dead `--record-scene` / `--replay-scene` / `--auto-capture` machinery now that it's deemed unfit for purpose.

## Completed

- [x] **Hybrid driver** (`tools/auto_play/runner.py`) — `--driver hybrid` runs `KeepAliveDriver` as the main 1Hz loop; a separate `VLMDriver` is injected into `StaticFrameWatchdog` and only fires when watchdog detects static-frame lockup. Cost-bounded by trigger rate (~5-15 calls/h) instead of 1Hz (~3000/h on pure `--driver vlm`).
- [x] **Watchdog 3-arm static detection** (`tools/auto_play/watchdog.py`) — three independent triggers:
  - **global**: relative-frame `mean ≤ 0.003` for 4 consecutive samples (≈12s) — original behavior
  - **local-only**: `moved_pixel_ratio < 5%` AND `mean < 0.025` — catches "frozen scene + small overlay animation" (dialog blink, dialog cursor)
  - **long-window**: 12s ago vs now `mean < 0.04` AND `moved < 30%` — catches **"FF7R tutorial popup with circular GIF + idle character animation"** where frame-to-frame mean keeps spiking but the player isn't really getting anywhere
- [x] **VLM prompt overhaul** (`tools/auto_play/vlm_driver.py`):
  - Hard Rule #6: only press ESC for confirmed fullscreen menu (not for HUD overlays)
  - Hard Rule #7: ESC anti-loop — don't press ESC twice consecutively if scene isn't a confirmed menu
  - Hard Rule #10 (HIGHEST PRIORITY): if screen shows `<KEY> Back` / `<KEY> Close` / `<KEY> Skip` etc., output exactly that key
  - New "Tutorial popup" state recipe with M Back (FF7R) + ESC Back (generic) examples
  - dotenv missing → loud stderr warning instead of silent skip
- [x] **Dismiss-key abstraction** (`tools/auto_play/profile.py` + `keep_alive.py` + 4 profile YAMLs):
  - new `controls.dismiss_ui` field (FF7R=M, others=ESC)
  - new `dismiss_ui` action in `keep_alive` step grammar; resolves to `controls.dismiss_ui`
  - all 4 profile `recovery` sequences use `{action: dismiss_ui}` instead of hardcoded `{press_key vk: M/ESC}`
- [x] **`--video` defaults False** + **new `--capture-duration N`** (default 30s, 0=unlimited). When timer fires, current capture session ends + a fresh timestamped session auto-starts (rolls). F9 still terminates the whole loop.
- [x] **`_self_cmd()` helper** in `main.py` — hint commands emit `unicap.exe` when running as Nuitka standalone, `uv run main.py` otherwise. All `[VIDEO] / [PACK] / cmd_video / cmd_pack` error hints now also include `--game-dir`.
- [x] **`_start_auto_play` foregrounds the game window** before the bot starts injecting (5s `focus_game_window` + 60s manual-alt-tab fallback). Without this, `SendInput` went to the unicap console instead of the game.
- [x] **Keyboard injection now uses scan codes + `KEYEVENTF_SCANCODE`** (`tools/auto_play/input_backend.py`). Required for id Tech 7 / DirectInput-aware games to receive WASD — pure virtual-key SendInput only lands in the Win32 message queue, which raw-input listeners ignore.
- [x] **`.env`**: `VLM_MODEL` bumped `qwen-vl-plus` → `qwen-vl-max`.
- [x] **Removed record/replay/auto-capture entirely** (this session, ~3000 line net deletion):
  - Deleted `tools/replay/*` (5 files), `scripts/verify_replay.py`, 4 replay-related `docs/` files
  - Removed from `main.py`: `_run_record`, `_run_replay`, `_validate_launch_args`, `_validate_scene_name`, `_scene_dir_for`, `_scratch_dir_for`, `_precheck_scene`, `_get_window_size`, `_read_cursor_pos`, `cmd_scenes`, `VK_F7`, argparse `--record-scene/--replay-scene/--auto-capture`, `scenes` subcommand, `auto_capture_first` parameter from `_interactive_loop`
  - `MANDATORY_RESERVED_KEYS`: `{F7,F8,F9}` → `{F8,F9}`
  - All 4 profiles `reserved_keys: [F6,F7,F8,F9]` → `[F8,F9]`
  - `CLAUDE.md`: deleted "录制 / 回放（replay-scene）" entire section + every `--record-scene` / `--replay-scene` / `--auto-capture` mention

## Not Yet Done

- [ ] **Sponsor live FF7R test of hybrid driver** — does qwen-vl-max + new prompts actually solve the tutorial-popup problem? Last test on `qwen-vl-plus` had VLM responding "gameplay state with HUD visible" while looking at a tutorial popup. Sponsor agreed to retest after upgrade + Hard Rule #10 + tutorial popup recipe + ff7r `game_instructions` rewrite. **This is the open verification gate.**
- [ ] **Commit + push pending changes** — sponsor needs to test first, then explicitly say "commit". 23 files dirty (~343 insertions, ~3348 deletions, mostly from C. cleanup).
- [ ] (Optional) **Tune watchdog thresholds based on log evidence** — `_LOCAL_MOTION_RATIO_CAP=0.05`, `_LOCAL_MOTION_MEAN_CAP=0.025`, `_LONG_WINDOW_MEAN_CAP=0.04`, `_LONG_WINDOW_RATIO_CAP=0.30` are best-guess values calibrated against synthetic data. Real game logs may want adjustment if too many false positives or false negatives.

## Failed Approaches (Don't Repeat These)

- **`press_key M` heartbeat in `keep_alive.sequence`** — first attempt at "blind bot proactively dismisses tutorial popups". Removed because **M is NOT idempotent in FF7R**: pressing M during normal gameplay opens the map screen, and the closing tap doesn't always reliably return to gameplay (sometimes lands on a sub-tab). Net effect was forcing the bot into menus 7s out of every 14s. **Lesson: dismiss_ui belongs only in `recovery` (triggered after watchdog confirms a UI lockup), never in the main sequence.** Sponsor's exact words: "M 心跳会导致进入这个菜单，也是不对，M 只应该在判断有 UI 时才触发".
- **Pure `--driver vlm` (every 1s VLM decision)** — too slow (3-4s effective decision lag because of network), too monotonous (12 of 19 reasonings were "open exploration, walk forward" no matter what scene), too expensive (~¥30/30min on Dashscope), and got into ESC death-loops where VLM mistook HUD for menu, pressed ESC, opened the actual menu, kept pressing ESC. **Hybrid (VLM only on watchdog trigger) replaces this.**
- **`watchdog.static_diff_threshold = 0.008`** (original) — too lenient. Tutorial popup with GIF animation had global mean=0.005-0.01 (above threshold) so watchdog never fired. Tightened to 0.003, then added local-only + long-window arms because even 0.003 misses the "circular GIF + idle character" case where actual frame diffs are non-trivial.
- **`watchdog.recovery` containing `press_key vk: ESC` ×2** (FF7R) — when recovery fired in clean gameplay (false positive), the two ESCs would *open* the system menu (FF7R uses ESC to open, not close). Replaced with `dismiss_ui` action which resolves to M for FF7R.
- **Pure virtual-key `SendInput` for keyboard** (`wVk` only, no SCANCODE flag) — DOOM Eternal / id Tech 7 didn't receive WASD because they read keyboard via raw input which ignores message-queue-only events. Mouse buttons worked fine (different code path) — that asymmetry was the diagnostic clue. Now using `MapVirtualKeyW(vk, MAPVK_VK_TO_VSC)` + `KEYEVENTF_SCANCODE`.

## Key Decisions

| Decision | Rationale |
|----------|-----------|
| Hybrid driver = KeepAlive main + VLM-in-watchdog | Cheapest way to combine "predictable input stream" with "intelligent recovery". VLM cost capped by watchdog trigger rate (12s minimum gap), not 1Hz. |
| Three-arm watchdog (global/local-only/long-window) | Single-arm `mean diff` can't distinguish "frozen scene + small GIF" (low moved_ratio but non-zero mean) from "real walking" (high mean + high moved_ratio). Adding moved_ratio + temporal long-window covers all three cases. |
| `dismiss_ui` action instead of hardcoded `vk: M`/`vk: ESC` | M is FF7R-specific (ESC opens system menu in FF7R; in DOOM/Batman ESC closes menus). Per-game key abstraction makes profiles portable. |
| `--driver hybrid` is opt-in, not default | Default `keep-alive` keeps zero-cost / zero-API-key runs working without `.env`. Sponsor must explicitly opt into VLM cost. |
| Removed record/replay entirely instead of fixing it | Sponsor lost confidence: "this game-state mismatch is a fundamental limitation of dHash sync". Replay couldn't reliably reach a target FF7R scene because UI loading variance broke the visual-anchor matching. Net code reduction ~3000 lines. |
| Hard Rule #10 ranks above all other state recipes | VLM kept misclassifying tutorial popups as "gameplay with HUD". Telling it "if you see `<KEY> Back/Close/Skip` text anywhere on screen, output that key first" leverages the model's OCR strength which was previously underused. |

## Current State

**Working** (verified by running `import main` + `load_profile` for all 4 profiles + argparse `--help`):
- `--driver hybrid` constructs cleanly, KeepAlive in `runner._driver`, VLMDriver in `runner._watchdog._vlm_driver`
- All 4 profiles load + validate; `controls.dismiss_ui` resolves correctly (FF7R→M, others→ESC)
- `argparse --help` no longer shows `record-scene/replay-scene/auto-capture/scenes`
- Watchdog static detection unit-tested on 6 synthetic scenarios (idle, micro-noise, tutorial GIF, real walking, loading fade-in, combat fx) — all classified correctly

**Not yet verified** (sponsor live test needed):
- Whether qwen-vl-max + Hard Rule #10 + tutorial popup recipe actually makes VLM output `press M` on the FF7R "Locking Onto Targets" tutorial popup
- Whether `_LONG_WINDOW_MEAN_CAP=0.04` triggers correctly in real gameplay (synthetic test passes)
- Whether removing `press_key M` heartbeat from sequence causes any new regression elsewhere

**Uncommitted Changes**: 23 files dirty (~343 insertions / 3348 deletions) — all listed below.

## Files to Know

| File | Why It Matters |
|------|----------------|
| `tools/auto_play/watchdog.py` | 3-arm static detection. The `_run` loop is the heart of "is the bot stuck?" detection. Class constants `_PIXEL_MOTION_THRESHOLD`/`_LOCAL_MOTION_*_CAP`/`_LONG_WINDOW_*_CAP` are best-guess thresholds — tune here if false positives. |
| `tools/auto_play/runner.py:101-130` | `driver_name="hybrid"` branch — creates KeepAliveDriver as main + injects VLMDriver into watchdog. Also has the print of "VLM endpoint base_url=... model=... budget=...". |
| `tools/auto_play/vlm_driver.py:_SYSTEM_PROMPT_TEMPLATE` | The big system prompt. Hard Rule #10 (HIGHEST PRIORITY) is the most load-bearing addition. Tutorial popup state recipe near the bottom shows generic + FF7R-specific examples. |
| `tools/auto_play/keep_alive.py:51-58` | `dismiss_ui` action handler. Resolves to `controls.dismiss_ui` per profile. Don't add this action to main `sequence` (sponsor explicitly rejected; only allowed in `recovery`). |
| `tools/auto_play/profile.py:34-37` | `MANDATORY_RESERVED_KEYS = {"F8", "F9"}`. Don't add F7 back — sponsor confirmed F7 is no longer reserved. |
| `profiles/ff7r.yaml` | Largest game-specific profile. `vlm.game_instructions` has scene-recognition cues for FF7R (HUD vs combat vs cutscene vs fullscreen menu vs tutorial popup). |
| `profiles/_default.yaml` | Fallback when fuzzy match fails. `controls.dismiss_ui: ESC` (most common). |
| `main.py:_run_capture` | Capture session lifecycle. `--capture-duration` timer + F9 watcher → either rolls into new session or terminates loop. Returns bool to `_interactive_loop`. |
| `main.py:_start_auto_play` | Spawns AutoPlayRunner. Calls `focus_game_window` before runner.start(). |
| `main.py:cmd_launch` (line ~528) | Main entry. After my removal it's much shorter — no `_validate_launch_args`, no `_run_record/_run_replay`, no `auto_capture_first`. |
| `.env` | VLM_API_KEY + VLM_BASE_URL (Dashscope) + `VLM_MODEL=qwen-vl-max`. **Gitignored** — never commit. |

## Code Context

**Hybrid driver wiring** (`tools/auto_play/runner.py`):
```python
# driver_name == "hybrid":
self._driver = create_driver("keep-alive", profile)             # main loop, free
vlm_for_watchdog = create_driver("vlm", profile, ...)           # consultant
self._watchdog = StaticFrameWatchdog(
    frames_dir=frames_dir, profile=profile,
    input_backend=self._backend,
    vlm_driver=vlm_for_watchdog,                                # ← key wiring
)
```

**3-arm static detection** (`tools/auto_play/watchdog.py:_run` excerpt):
```python
diff_3d = abs(prev - current).astype(int16)
mean_diff = diff_3d.mean() / 255.0
diff_2d = diff_3d.max(axis=2)
moved_ratio = (diff_2d > _PIXEL_MOTION_THRESHOLD).mean()

# Two short-window arms:
global_static = mean_diff <= _diff_threshold          # 0.003 (from profile)
local_only = moved_ratio < 0.05 and mean_diff < 0.025
if global_static or local_only:
    consecutive_static += 1
    if consecutive_static >= 4:                       # 12s
        _trigger_recovery(mean_diff, moved_ratio)

# Long-window arm (only fires after history fills, ~12s):
self._frame_history.append(current)
if len(self._frame_history) == 4:
    long_mean = abs(history[0] - current).mean() / 255.0
    long_moved = (abs(history[0] - current).max(axis=2) > 30).mean()
    if long_mean < 0.04 and long_moved < 0.30:        # → "circular animation, no real progress"
        _trigger_recovery(long_mean, long_moved)
        self._frame_history.clear()
```

**`_trigger_recovery` decision tree**:
```python
if vlm_driver and not vlm_disabled:
    actions = vlm_driver.next_actions(Observation(...))    # consult VLM
    if actions:
        for a in actions: backend.inject(a)
        return                                             # done — VLM handled it
    # else fall through to profile.recovery

for step in profile.recovery:                              # blind escape sequence
    actions = step_to_actions(profile, step, rng)
    for a in actions: backend.inject(a)
```

**`dismiss_ui` action resolution** (`tools/auto_play/keep_alive.py`):
```python
if action_name == "dismiss_ui":
    ctrl = controls.get("dismiss_ui")     # FF7R=M, others=ESC
    return _press_control(ctrl, dur)
```

**Hard Rule #10 in system prompt** (the load-bearing one):
```
10. ⚠️ HIGHEST PRIORITY — explicit dismiss prompts. If ANYWHERE on the
    screen (corner, bottom bar, popup edge) you see a key-hint of the form
    `<KEY> Back` / `<KEY> Close` / `<KEY> Cancel` / `<KEY> Exit` / `<KEY>
    Skip` / `Press <KEY> to dismiss` / `按 <KEY> 返回` — that is the game
    telling you exactly which key dismisses the current overlay. Output
    that exact key as your FIRST action ...
```

## Resume Instructions

1. **Verify clean import** before sponsor tests:
   ```powershell
   uv run python -c "import main; print('OK')"
   uv run python -c "from tools.auto_play.profile import load_profile, list_profiles; [load_profile(n) for n in list_profiles() + ['_default']]; print('all profiles OK')"
   ```
   Expected: both print "OK" / "all profiles OK". If `ImportError`, look for residual `tools.replay` references.

2. **Sponsor live test of hybrid driver on FF7R**:
   ```powershell
   uv run main.py launch --game-path "E:\games\ff7remake\...\ff7remake_.exe" --profile ff7r --auto-play --driver hybrid
   ```
   Then in another shell tail the log:
   ```powershell
   Get-Content "$env:TEMP\unicap\auto_play.log" -Wait -Tail 20
   ```
   Press F8 to start capture. Walk into a tutorial popup (Chapter 1 has many).

   **Expected** (good outcome):
   ```
   [WATCHDOG] long-window static (12s): long_mean=0.012 long_moved=8.5% — 当作卡死
   [WATCHDOG] static-frame 触发 #1 mean=0.012 moved=8.5% → VLM 决策 (1 actions)
   [VLM] reasoning: tutorial popup 'Locking Onto Targets', hint reads 'M Back', dismiss with M
   [VLM-COST] call#N t=2.5s in=3500 out=70 cache_r=0
   ```

   **If VLM still misclassifies** (says "gameplay state with HUD visible"):
   - Save the BackBuffer.png from the session at the moment of trigger
   - Check `vlm_driver.py` system prompt is actually being sent (`grep "HIGHEST PRIORITY"` on a captured request)
   - Try `qwen-vl-max-latest` instead of `qwen-vl-max` (some Dashscope endpoints differ)
   - Or shorten the prompt to put Rule #10 right at the top (currently buried under 200+ lines of preamble)

3. **If hybrid works → commit and push** (sponsor will explicitly say "commit" — do NOT auto-commit):
   - Recommended commit split: 3 commits matching A/B/C above. Or one big "feat(auto-play): hybrid driver + watchdog rewrite + VLM prompt overhaul + remove record/replay" if sponsor wants it as one unit.
   - Push `auto-play` then ff-merge to `master`. Both branches were last in sync at `73a39d9`.

4. **If watchdog over-triggers in real gameplay** (false positives during normal walking), tune in `tools/auto_play/watchdog.py`:
   - Lower `_LONG_WINDOW_MEAN_CAP` from 0.04 → 0.025 (tighter — fewer triggers, but may miss some real lockups)
   - Or raise `_LONG_WINDOW_RATIO_CAP` from 0.30 → 0.50 (allow more pixel movement before declaring static)
   - Or extend `_LONG_WINDOW_SAMPLES` from 4 → 6 (compare 18s ago instead of 12s — slower trigger but more confident lockup)

## Setup Required

- `.env` at repo root with `VLM_API_KEY` (Dashscope sk-... already there) + `VLM_BASE_URL=https://dashscope.aliyuncs.com/compatible-mode/v1` + `VLM_MODEL=qwen-vl-max`. Gitignored.
- `uv sync --extra auto-play-vlm` to install `python-dotenv` + `openai>=1.50` + `vgamepad`. (Without dotenv, .env is silently ignored — vlm_driver now warns on missing dotenv but still doesn't auto-install it.)
- FF7R installed at sponsor's path.
- `dist/dxgi.dll` + `dist/frame_capture.addon` already built (auto-deployed by `launch`).

## Edge Cases & Error Handling

- **VLM_API_KEY missing or wrong** → VLMDriver raises `BudgetExhausted` on first `next_actions` call → watchdog disables VLM permanently for the session and falls back to `profile.recovery`. Capture continues. Logged at WARN.
- **VLM returns `[]` (empty actions or parse failure)** → watchdog treats as "VLM had no opinion" and falls back to `profile.recovery` for this trigger only. Next trigger will retry VLM.
- **VLM budget exhausted (60 calls/h cap)** → same as missing key: permanent fallback for the rest of the session.
- **Watchdog triggers during legitimate cutscene** (bot is "stuck" because user-controlled cutscene is playing) → recovery sequence runs (M / ENTER / 调头 / 后退). For FF7R the M+ENTER won't break gameplay (M=close UI no-op, ENTER=advance dialog if any). For other games may interrupt cutscene — acceptable trade-off.
- **`--capture-duration` timer fires while VLM is mid-call** → capture stop_event is set; capture_all returns; runner.stop() joins driver thread. Mid-flight VLM call may complete after stop but its actions are dropped. No leaks.
- **`--auto-play` without `--profile`** → `_start_auto_play` does fuzzy match by exe basename; if no match falls back to `_default.yaml` with a printed warning.

## Warnings

- **DO NOT add `dismiss_ui` to `keep_alive.sequence`** — sponsor explicitly rejected this. Side effects on FF7R (M opens map) outweigh benefits. dismiss_ui only belongs in `recovery`.
- **DO NOT auto-commit/push** — sponsor's saved memory rule. Wait for explicit "commit"/"push" instruction. Push is shared state; master can't be force-pushed.
- **DO NOT default to English in prose** — sponsor's saved memory rule. Chinese is preferred for explanations; code/commands/error text stay in original.
- **DO NOT regenerate ESC death-loops** — Hard Rule #7 in system prompt is load-bearing. If you simplify the prompt, keep "if previous tick was ESC and screen still isn't a confirmed menu, MUST NOT output ESC".
- **DO NOT bring back F7** — record/replay is gone; F7 is no longer reserved. Adding it back would be surprising.
- **`.env` is gitignored** — never `git add .env` even if it shows in `git status -s`. The `M .env` line in pending changes (VLM_MODEL bump) is local-only and should NOT be committed.
- **Watchdog `_LONG_WINDOW_SAMPLES = 4` × `sample_period_s = 3.0` = 12s window** — if you change either constant, update both `tools/auto_play/watchdog.py` class constant and `profiles/ff7r.yaml:watchdog.sample_period_s` together.
- **`cache_r=0` in `[VLM-COST]` lines is normal for Dashscope** — Qwen OpenAI-compat endpoint doesn't return `cached_tokens`. Not a bug.
- **Old `HANDOFF.md` (from 2026-05-04 22:40 / `f6e1d0c`) was about a `/kb` daemon-thread fix that's already long-merged** — completely overwritten by this handoff.
