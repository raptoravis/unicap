# Auto-Test Session: replay-scene v1.0

**Session:** AUTO-TEST-2026-05-04-001
**Persona:** power-user
**Project type:** CLI (`uv run main.py`)
**Capability tier:** stable
**Tested by:** auto-test agent (Claude Opus 4.7)
**Tester model meets persona-simulation tier:** yes (experimental, Claude Opus+)

## Scope & Limitations

Live-game record/replay testing requires a running game window (FF7R / DOOM Eternal). Per project memory `feedback_no_auto_verify` and the requirements doc, **live-game E2E is sponsor's job**. This session covers only the CLI surface, error paths, docs, and the offline `verify_replay.py` script.

Live-game findings (record success, sync match resilience, paused R/Q UX in actual game window, FPS-look limitation impact) are **untestable from here** and explicitly out of scope.

## Session Steps

| # | Action | Observation | Friction? |
|---|---|---|---|
| 1 | `uv run main.py --help` | Top-level shows three subcommands; launch description says "F6/F8/F9 工作流" | **Yes** — F7 omitted |
| 2 | `uv run main.py launch --help` | `--record-scene` / `--replay-scene` documented, mutex info present | No |
| 3 | `uv run main.py launch --replay-scene definitely_does_not_exist --game-path bad/path.exe` | Error at game-path resolution (good), but if path were valid, scene-not-found check happens AFTER game launch | **Yes** — wrong order for fast-fail |
| 4 | `uv run python scripts/verify_replay.py` | 23/23 passed, ~3s | No |
| 5 | `uv run main.py launch --replay-scene` (no value) | argparse rejects ✓; but `--record-scene ""` (empty string) silently treated as no-record (Python falsiness) | **Yes** — silent acceptance |
| 6 | `uv run main.py launch --record-scene "../escape"` | Accepted; would write recording outside `_scenes/` | **Yes** — hygiene |
| 7 | Read CLAUDE.md / hints box code | Hints box only shows F8/F9 in idle; F6/F7 hints box appears only when `--record-scene` invoked | No |

## Findings

---

### BUG-001 — Launch help text omits F7

**Type:** bug
**Severity:** minor
**Priority hint:** quick fix; should land before sponsor sees it
**Persona:** power-user
**Session:** AUTO-TEST-2026-05-04-001

**Description:** When I ran `uv run main.py --help` I saw the launch subcommand described as "部署 + 启动游戏 + 进入交互式 F6/F8/F9 工作流". F6 is there, but F7 (which I learned from `--help` is the stop-record key) is missing. As a power user reading docs to understand the surface, I assumed there was no F7 → confused when the recorder hint box later told me to press F7 to stop.

**Reproduction:**
- **Preconditions:** none
- **Steps:**
  1. Run `uv run main.py --help`
  2. Look at the description for `launch`
- **Expected:** "F6/F7/F8/F9 工作流" (mentions all hotkeys the launch flow uses)
- **Actual:** "F6/F8/F9 工作流" — F7 is silently missing
- **Frequency:** always

**Environment:** CLI / shell / stable tier

**Fix hint** (not authoritative): `main.py:1079` — change `"部署 + 启动游戏 + 进入交互式 F6/F8/F9 工作流"` → `"...F6/F7/F8/F9 工作流"`.

---

### BUG-002 — Scene validation happens after game launch (wastes 30s on typos)

**Type:** bug
**Severity:** major
**Priority hint:** before sponsor 30min E2E
**Persona:** power-user
**Session:** AUTO-TEST-2026-05-04-001

**Description:** I want to replay a scene called `tutoral` but I typo it as `tutorialz`. When I run `uv run main.py launch --replay-scene tutorialz`, the game launcher fires up, the actual game loads (~30s for FF7R), and only THEN does `_run_replay` check `script_path.is_file()` and fail with "[REPLAY] script not found". I just wasted 30s of game startup because the script existence check happens after `subprocess.Popen([game_exe])`.

Same for `--record-scene foo` when `_scenes/foo/` already has content — the existence check happens inside `_run_record`, after game launch.

This is real friction during iterative testing where you're running the same launch command 5+ times with small variations.

**Reproduction:**
- **Preconditions:** valid `--game-path` to a real game; `_scenes/typoed_name/` does NOT exist
- **Steps:**
  1. Run `uv run main.py launch --replay-scene typoed_name`
  2. Wait for game launcher → game window → game intro
  3. Eventually console prints "[REPLAY] script not found"
- **Expected:** the "script not found" check should run BEFORE `subprocess.Popen` so the user is told within 1 second and doesn't waste a game launch
- **Actual:** game launches first, ~30s wasted, then the error
- **Frequency:** always

**Environment:** CLI / stable tier

**Fix hint:** Move scene-validity precheck (script.jsonl + meta.json existence for replay; scene-dir non-empty check for record) into `cmd_launch` BEFORE `cmd_deploy` / `subprocess.Popen`. Same scope as the existing `_validate_launch_args`.

---

### BUG-003 — Empty `--record-scene ""` / `--replay-scene ""` silently ignored

**Type:** bug
**Severity:** minor
**Priority hint:** low; uncommon path but confusing when it happens
**Persona:** power-user
**Session:** AUTO-TEST-2026-05-04-001

**Description:** I ran `uv run main.py launch --record-scene ""` (empty string — happens if a shell variable is unset). The system silently treated it as "no record-scene specified" and entered normal launch flow. No warning, no error. I sat there waiting for the recording hint box that never appeared, eventually realized my variable was empty.

The mutex check in `_validate_launch_args` does `if record and replay:` — empty string is falsy in Python, so the check is silently skipped, and `_run_record` is also not invoked (same falsiness check at the dispatch site).

**Reproduction:**
- **Preconditions:** valid `--game-path`
- **Steps:**
  1. Run `uv run main.py launch --record-scene ""`
- **Expected:** error like "[错误] --record-scene 不能为空" and exit ≠ 0
- **Actual:** silent — proceeds as if `--record-scene` was not given at all
- **Frequency:** always

**Environment:** CLI / stable tier

**Fix hint:** In `_validate_launch_args`, add `if record == "" or replay == "":` early-exit check before the mutex check.

---

### BUG-004 — Scene name allows `..` traversal (data hygiene)

**Type:** bug
**Severity:** cosmetic
**Priority hint:** lowest — hygiene only, no security exposure (local-only tool, no untrusted input)
**Persona:** power-user
**Session:** AUTO-TEST-2026-05-04-001

**Description:** I noticed that `--record-scene "../escape"` is accepted without normalization. The `_scene_dir_for` helper does `dataset_root / game_name / "_scenes" / scene_name`, and Python's `Path` doesn't normalize `..` until OS access. So a recording would land in `<dataset_root>/<game>/escape/` — outside `_scenes/`, violating the documented layout and the `_*` filter assumption used by `pack` / `video`.

Not a security issue (the user controls their own command line) but reflects sloppy validation that a careful user would notice.

**Reproduction:**
- **Preconditions:** valid `--game-path`
- **Steps:**
  1. Run `uv run main.py launch --record-scene "../foo"` — let the game launch then F7 to stop
  2. Look at where the script.jsonl ended up
- **Expected:** scene name validation rejects names containing `/`, `\`, `..`, leading/trailing whitespace, etc.
- **Actual:** path traversal silently accepted
- **Frequency:** always

**Environment:** CLI / stable tier

**Fix hint:** Validate in `_validate_launch_args`: `if any(c in scene_name for c in r'\/..') or scene_name != scene_name.strip(): sys.exit(...)`.

---

### FEAT-001 — A `list-scenes` helper would close a discoverability gap

**Type:** feature-request
**Priority hint:** nice-to-have
**Persona:** power-user
**Session:** AUTO-TEST-2026-05-04-001

**Description:** As a power user with multiple games in `DATASET_ROOT`, I'd like a quick way to see which scenes I've already recorded for a given game without `ls`-ing through `_scenes/`. Something like `uv run main.py launch --list-scenes` (or a top-level `scenes` subcommand) that prints scene name + recorded date + sync count for each scene under the inferred or specified game.

This isn't a blocker — `ls DATASET_ROOT/<game>/_scenes/` works — but the feature feels half-discovered without it. Same UX gap exists for `survey/` btw, but there's only ever one survey per game so it matters less.

**Environment:** CLI / stable tier

---

## Summary

- **5 findings** total: 0 critical, 1 major, 2 minor, 1 cosmetic, 1 feature request.
- **No blockers** — every finding is "minor friction" or "would-be-nice"; the feature is functionally usable for sponsor's first 30min FF7R live-test.
- **Recommend fixing BUG-001 + BUG-002 before sponsor's E2E** — both are quick (each <10 LoC) and BUG-002 in particular will save sponsor 30s+ per typo during iterative testing.
- BUG-003, BUG-004, FEAT-001 are post-merge cleanup.

## What I Could Not Test

- **Live game record happy path** (S-001 in requirements) — needs FF7R window
- **Live game replay with load drift** (S-002) — same
- **Live game sync timeout + R/Q UX** (S-003) — same
- **G-005 auto-survey on missing cache** with a real game — same
- **Mouse-look limitation** (FPS lock) impact in practice — same
- **`--force-borderless` interaction with replay** — needs game window
- **`fc_output_dir.txt` interaction with addon during replay** — needs running addon
- **Window-size mismatch warning** in the actual game (e.g., user records at 1920x1080, replays at 2560x1440) — same

These all belong to the sponsor's manual 30min E2E pass.
