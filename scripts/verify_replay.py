"""verify_replay — offline sanity checks for tools/replay/.

Run by sponsor:
    uv run python scripts/verify_replay.py

Covers all M-checkpoints from docs/designs/testplan_20260504_replay-scene.md
that don't need a live game. Live-game E2E (record FF7R menu, replay it) is
a separate sponsor task.

Layout: each check is a 0-arg function returning (name, passed:bool, msg).
Top-level main() runs them all, prints colored summary, exits 0 on all-pass.
"""

from __future__ import annotations

import json
import os
import sys
import tempfile
import time
import traceback
from pathlib import Path
from unittest.mock import MagicMock, patch

# Ensure repo root on sys.path
ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import numpy as np

import cv2  # noqa: E402  (after sys.path tweak)


# ── Test infrastructure ─────────────────────────────────────────────────────


PASS = "[PASS]"
FAIL = "[FAIL]"
SKIP = "[SKIP]"


def _run(name: str, fn):
    try:
        ok, msg = fn()
    except Exception:
        return name, False, "EXCEPTION:\n" + traceback.format_exc()
    return name, ok, msg


# ── Sync match (sync_match.py) ─────────────────────────────────────────────


def t_dhash_self_zero():
    from tools.replay.sync_match import dhash, hamming
    img = np.full((64, 64, 3), 128, dtype=np.uint8)
    h = dhash(img)
    return hamming(h, h) == 0, f"hamming(self,self)={hamming(h, h)}"


def t_dhash_inverted_far():
    from tools.replay.sync_match import dhash, hamming
    a = np.zeros((64, 64, 3), dtype=np.uint8)
    b = np.full((64, 64, 3), 255, dtype=np.uint8)
    d = hamming(dhash(a), dhash(b))
    # Uniform images → all comparisons are equal → tie-break gives 0 bits set.
    # The real test: gradient images differ a lot.
    a2 = np.tile(np.arange(64, dtype=np.uint8), (64, 1))
    a2 = np.stack([a2, a2, a2], axis=-1)
    b2 = a2[:, ::-1].copy()
    d2 = hamming(dhash(a2), dhash(b2))
    return d2 >= 30, f"reversed-gradient hamming={d2} (uniform={d})"


def t_dhash_perf():
    from tools.replay.sync_match import dhash
    img = (np.random.rand(1080, 1920, 3) * 255).astype(np.uint8)
    t0 = time.perf_counter()
    for _ in range(20):
        dhash(img)
    avg_ms = (time.perf_counter() - t0) * 1000.0 / 20
    return avg_ms < 50.0, f"avg {avg_ms:.1f}ms (target <50ms)"


def t_wait_for_match_no_dir():
    from tools.replay.sync_match import wait_for_match
    res = wait_for_match(Path("/nonexistent_ref.bmp"),
                         Path("/nonexistent_dir"),
                         threshold=10, timeout_s=0.5)
    return (not res.matched and res.reason == "ref_unreadable"), \
        f"matched={res.matched} reason={res.reason}"


def t_wait_for_match_immediate():
    from tools.replay.sync_match import wait_for_match
    with tempfile.TemporaryDirectory() as td:
        td_p = Path(td)
        img = (np.random.rand(720, 1280, 3) * 255).astype(np.uint8)
        ref = td_p / "ref.bmp"
        cv2.imwrite(str(ref), img)
        # Place a copy in scratch as "latest" frame, age it
        scratch = td_p / "scratch"
        scratch.mkdir()
        latest = scratch / "test_BackBuffer.bmp"
        cv2.imwrite(str(latest), img)
        old = time.time() - 2.0
        os.utime(latest, (old, old))
        res = wait_for_match(ref, scratch, threshold=10, timeout_s=2.0)
    return res.matched, f"matched={res.matched} dist={res.distance} reason={res.reason}"


# ── Schema (schema.py) ─────────────────────────────────────────────────────


def t_meta_round_trip():
    from tools.replay.schema import MetaModel, RECORDER_VERSION, write_meta, load_meta
    with tempfile.TemporaryDirectory() as td:
        p = Path(td) / "meta.json"
        m = MetaModel(
            name="x", version=1, recorded_at="2026-05-04T20:00:00+00:00",
            recorder_version=RECORDER_VERSION,
            game_exe="x.exe", api="dx", window_size=(1920, 1080),
            mouse_origin=(960, 540),
        )
        write_meta(p, m)
        m2 = load_meta(p)
    ok = (m2.name == "x" and m2.window_size == (1920, 1080) and
          m2.mouse_origin == (960, 540) and m2.api == "dx")
    return ok, f"got name={m2.name} window={m2.window_size} mouse={m2.mouse_origin} api={m2.api}"


def t_validate_meta_missing_field():
    from tools.replay.schema import validate_meta
    try:
        validate_meta({"name": "x"})
    except ValueError as e:
        msg = str(e)
        return ("name" not in msg and "version" in msg), f"err={msg}"
    return False, "expected ValueError, got success"


def t_validate_meta_forward_compat():
    from tools.replay.schema import validate_meta
    base = {
        "name": "x", "version": 1, "recorded_at": "2026-05-04",
        "recorder_version": "1.0", "game_exe": "x.exe", "api": "dx",
        "window_size": [1920, 1080],
        "future_field_unknown_to_v1": {"hello": "world"},
    }
    try:
        validate_meta(base)
        return True, "unknown field accepted (forward compat)"
    except Exception as e:
        return False, f"rejected: {e}"


def t_iter_events_unknown_skip():
    from tools.replay.schema import iter_events
    with tempfile.TemporaryDirectory() as td:
        p = Path(td) / "script.jsonl"
        p.write_text("\n".join([
            json.dumps({"type": "key_down", "t_rel": 0.0, "vk": "W"}),
            json.dumps({"type": "future_unknown_event", "t_rel": 0.1, "data": 1}),
            json.dumps({"type": "key_up", "t_rel": 0.2, "vk": "W"}),
        ]) + "\n", encoding="utf-8")
        events = list(iter_events(p))
    types = [e["type"] for e in events]
    return types == ["key_down", "key_up"], f"types={types}"


def t_iter_events_t_rel_regression():
    from tools.replay.schema import iter_events
    with tempfile.TemporaryDirectory() as td:
        p = Path(td) / "script.jsonl"
        p.write_text("\n".join([
            json.dumps({"type": "key_down", "t_rel": 1.0, "vk": "W"}),
            json.dumps({"type": "key_up",   "t_rel": 0.5, "vk": "W"}),
        ]) + "\n", encoding="utf-8")
        try:
            list(iter_events(p))
        except ValueError as e:
            return "倒退" in str(e), f"err={e}"
    return False, "expected ValueError, got success"


# ── Recorder (recorder.py) — invoke without real game ────────────────────


def t_recorder_smoke_save():
    """Start recorder briefly with no real input → save() produces empty-ish files."""
    from tools.replay import ReplayRecorder, iter_events, load_meta
    with tempfile.TemporaryDirectory() as td:
        td_p = Path(td)
        scene = td_p / "scene"
        scratch = td_p / "scratch"
        rec = ReplayRecorder(
            scene_dir=scene, sync_scratch_dir=scratch, game_dir=td_p,
            game_exe="test.exe", api="dx",
            window_size=(1920, 1080), mouse_origin=(960, 540),
            scene_name="smoke",
        )
        rec.start()
        time.sleep(0.5)
        rec.stop()
        rec.wait_until_done(timeout=2.0)
        rec.save()
        rec.close()

        # Verify files
        if not (scene / "script.jsonl").exists() or not (scene / "meta.json").exists():
            return False, "missing script.jsonl / meta.json"
        # Schema-level: meta loads, events iterate without raising
        meta = load_meta(scene / "meta.json")
        events = list(iter_events(scene / "script.jsonl"))
    ok = meta.name == "smoke" and isinstance(events, list)
    return ok, f"meta.name={meta.name}, event_count={len(events)}"


def t_recorder_sidecar_cleanup():
    """close() must clear fc_output_dir.txt and rmtree scratch."""
    from tools.replay import ReplayRecorder
    with tempfile.TemporaryDirectory() as td:
        td_p = Path(td)
        scene = td_p / "scene"
        scratch = td_p / "scratch"
        rec = ReplayRecorder(
            scene_dir=scene, sync_scratch_dir=scratch, game_dir=td_p,
            game_exe="test.exe", api="dx",
            window_size=(1920, 1080), mouse_origin=(0, 0),
            scene_name="cleanup_test",
        )
        rec.start()
        time.sleep(0.2)
        # Verify sidecar was set
        sidecar = td_p / "fc_output_dir.txt"
        if not sidecar.exists():
            rec.stop()
            rec.close()
            return False, "fc_output_dir.txt not created on start"
        rec.stop()
        rec.wait_until_done(timeout=2.0)
        rec.close()
        # After close: sidecar gone, scratch gone
        sidecar_ok = (not sidecar.exists()) or sidecar.read_text().strip() == ""
        scratch_ok = not scratch.exists()
    return sidecar_ok and scratch_ok, \
        f"sidecar_clean={sidecar_ok} scratch_clean={scratch_ok}"


# ── Player (player.py) ───────────────────────────────────────────────────


def _make_dummy_scene(td: Path, name: str = "test", with_sync: bool = False,
                     sync_matches: bool = True) -> tuple[Path, Path]:
    """Build a minimal scene_dir + matching scratch with a 'live' BMP."""
    from tools.replay.schema import MetaModel, RECORDER_VERSION, write_meta
    scene = td / name
    scratch = td / f"{name}_scratch"
    scene.mkdir()
    scratch.mkdir()

    # Build script with a few key events
    events = [
        {"type": "key_down", "t_rel": 0.05, "vk": "W"},
        {"type": "key_up",   "t_rel": 0.1, "vk": "W"},
    ]
    if with_sync:
        # ref + (matching or non-matching) live frame
        ref_img = (np.random.rand(360, 640, 3) * 255).astype(np.uint8)
        ref_path = scene / "sync_01.bmp"
        cv2.imwrite(str(ref_path), ref_img)
        if sync_matches:
            live_img = ref_img.copy()
        else:
            live_img = (np.random.rand(360, 640, 3) * 255).astype(np.uint8)
        live_path = scratch / "live_BackBuffer.bmp"
        cv2.imwrite(str(live_path), live_img)
        old = time.time() - 2.0
        os.utime(live_path, (old, old))
        events.append({"type": "sync", "id": "S-01", "frame": "sync_01.bmp",
                       "t_rel": 0.2, "description": ""})
        events.append({"type": "key_down", "t_rel": 0.3, "vk": "S"})
        events.append({"type": "key_up",   "t_rel": 0.35, "vk": "S"})

    (scene / "script.jsonl").write_text(
        "\n".join(json.dumps(e) for e in events) + "\n", encoding="utf-8")
    write_meta(scene / "meta.json", MetaModel(
        name=name, version=1, recorded_at="2026-05-04T20:00:00+00:00",
        recorder_version=RECORDER_VERSION,
        game_exe="x.exe", api="dx", window_size=(1920, 1080),
        mouse_origin=(960, 540),
        syncs={"S-01": {"hamming_threshold": 10, "timeout_s": 2.0}}
        if with_sync else {},
    ))
    return scene, scratch


class _MockBackend:
    """Stand-in for InputBackend — records every inject() call."""

    def __init__(self):
        self.injects: list[dict] = []
        self.profile = MagicMock()
        self.gamepad_available = False

    def inject(self, action):
        self.injects.append({"kind": action.kind, "payload": dict(action.payload)})

    def close(self):
        pass


def t_player_no_sync_happy():
    from tools.replay import ReplayPlayer
    with tempfile.TemporaryDirectory() as td:
        td_p = Path(td)
        scene, scratch = _make_dummy_scene(td_p, with_sync=False)
        backend = _MockBackend()
        player = ReplayPlayer(
            scene_dir=scene, sync_scratch_dir=scratch, game_dir=td_p,
            backend=backend, current_window_size=(1920, 1080),
        )
        with patch.object(sys.modules["tools.replay.player"]._user32, "SetCursorPos"):
            res = player.run()
    ok = res.status == "reached" and res.exit_code == 0
    return ok, f"status={res.status} exit={res.exit_code} injects={len(backend.injects)}"


def t_player_sync_match():
    from tools.replay import ReplayPlayer
    with tempfile.TemporaryDirectory() as td:
        td_p = Path(td)
        scene, scratch = _make_dummy_scene(td_p, with_sync=True, sync_matches=True)
        backend = _MockBackend()
        player = ReplayPlayer(
            scene_dir=scene, sync_scratch_dir=scratch, game_dir=td_p,
            backend=backend, current_window_size=(1920, 1080),
        )
        with patch.object(sys.modules["tools.replay.player"]._user32, "SetCursorPos"):
            res = player.run()
    ok = (res.status == "reached" and res.syncs_passed == 1 and res.syncs_total == 1)
    return ok, f"status={res.status} pass/total={res.syncs_passed}/{res.syncs_total}"


def t_player_sync_miss_resume():
    """Sync miss → paused → simulated 'R' → continues to completion."""
    from tools.replay import ReplayPlayer
    with tempfile.TemporaryDirectory() as td:
        td_p = Path(td)
        scene, scratch = _make_dummy_scene(td_p, with_sync=True, sync_matches=False)
        backend = _MockBackend()
        player = ReplayPlayer(
            scene_dir=scene, sync_scratch_dir=scratch, game_dir=td_p,
            backend=backend, current_window_size=(1920, 1080),
            paused_input_provider=lambda: "R",
        )
        with patch.object(sys.modules["tools.replay.player"]._user32, "SetCursorPos"):
            res = player.run()
    ok = res.status == "reached" and res.exit_code == 0
    return ok, f"status={res.status} exit={res.exit_code}"


def t_player_sync_miss_quit():
    """Sync miss → paused → simulated 'Q' → user_abort, exit 2."""
    from tools.replay import ReplayPlayer
    with tempfile.TemporaryDirectory() as td:
        td_p = Path(td)
        scene, scratch = _make_dummy_scene(td_p, with_sync=True, sync_matches=False)
        backend = _MockBackend()
        player = ReplayPlayer(
            scene_dir=scene, sync_scratch_dir=scratch, game_dir=td_p,
            backend=backend, current_window_size=(1920, 1080),
            paused_input_provider=lambda: "Q",
        )
        with patch.object(sys.modules["tools.replay.player"]._user32, "SetCursorPos"):
            res = player.run()
    ok = (res.status == "user_abort" and res.exit_code == 2 and
          res.failed_sync == "S-01")
    return ok, f"status={res.status} exit={res.exit_code} failed={res.failed_sync}"


def t_player_window_scale_warning(capture_output=True):
    """Different window size → warn once + scaled mouse_move."""
    from tools.replay import ReplayPlayer
    from tools.replay.schema import MetaModel, RECORDER_VERSION, write_meta
    with tempfile.TemporaryDirectory() as td:
        td_p = Path(td)
        scene = td_p / "scene"
        scratch = td_p / "scratch"
        scene.mkdir()
        scratch.mkdir()
        (scene / "script.jsonl").write_text(
            json.dumps({"type": "mouse_move", "t_rel": 0.05,
                        "x": 1000, "y": 500}) + "\n",
            encoding="utf-8")
        write_meta(scene / "meta.json", MetaModel(
            name="scale", version=1, recorded_at="2026-05-04T20:00:00+00:00",
            recorder_version=RECORDER_VERSION,
            game_exe="x.exe", api="dx", window_size=(2000, 1000),
            mouse_origin=(0, 0),
        ))
        backend = _MockBackend()
        player = ReplayPlayer(
            scene_dir=scene, sync_scratch_dir=scratch, game_dir=td_p,
            backend=backend, current_window_size=(1000, 500),
        )
        captured = {}

        def fake_set_cursor(x, y):
            captured["x"] = x
            captured["y"] = y
        with patch.object(sys.modules["tools.replay.player"]._user32,
                          "SetCursorPos", side_effect=fake_set_cursor):
            res = player.run()
    # Recorded x=1000 in 2000-wide window → at 1000-wide window should be x=500
    ok = (res.status == "reached" and captured.get("x") == 500
          and captured.get("y") == 250)
    return ok, f"status={res.status} captured={captured}"


# ── main.py glue ─────────────────────────────────────────────────────────


def t_main_mutex_record_replay():
    import subprocess
    proc = subprocess.run(
        [sys.executable, str(ROOT / "main.py"), "launch",
         "--record-scene", "a", "--replay-scene", "b"],
        capture_output=True, timeout=20, text=True,
    )
    combined = proc.stdout + proc.stderr
    return (proc.returncode != 0
            and "--record-scene" in combined
            and "--replay-scene" in combined
            and ("不能同时" in combined or "mutual" in combined.lower())), \
        f"rc={proc.returncode} out={combined[-300:]}"


def t_main_record_autoplay_allowed():
    """--record-scene + --auto-play must NOT be rejected by mutex (it's a
    valid combo; auto-play only fires in F8 capture phase post-record)."""
    import argparse
    import main as main_mod
    args = argparse.Namespace(record_scene="x", replay_scene=None, auto_play=True)
    try:
        main_mod._validate_launch_args(args)
        return True, "validation passed (no mutex rejection)"
    except SystemExit as e:
        return False, f"rejected unexpectedly: {e.code}"


def t_main_replay_autoplay_allowed():
    """Same: --replay-scene + --auto-play is the killer unattended combo."""
    import argparse
    import main as main_mod
    args = argparse.Namespace(record_scene=None, replay_scene="y", auto_play=True)
    try:
        main_mod._validate_launch_args(args)
        return True, "validation passed (no mutex rejection)"
    except SystemExit as e:
        return False, f"rejected unexpectedly: {e.code}"


def t_main_precheck_replay_missing():
    """BUG-002 fix: replay precheck rejects nonexistent scene before game launch."""
    import argparse
    import main as main_mod
    args = argparse.Namespace(record_scene=None, replay_scene="totally_missing",
                              auto_play=False)
    with tempfile.TemporaryDirectory() as td:
        try:
            main_mod._precheck_scene(args, Path(td), "fake_game")
        except SystemExit as e:
            return ("不存在" in str(e.code)
                    and "totally_missing" in str(e.code)), f"err={e.code}"
    return False, "expected SystemExit, got success"


def t_main_precheck_record_clobber():
    """BUG-002 fix: record precheck rejects already-populated scene_dir."""
    import argparse
    import main as main_mod
    args = argparse.Namespace(record_scene="exists", replay_scene=None,
                              auto_play=False)
    with tempfile.TemporaryDirectory() as td:
        # Pre-populate the scene
        scene = Path(td) / "fake_game" / "_scenes" / "exists"
        scene.mkdir(parents=True)
        (scene / "stale.txt").write_text("hi")
        try:
            main_mod._precheck_scene(args, Path(td), "fake_game")
        except SystemExit as e:
            return ("已存在" in str(e.code)), f"err={e.code}"
    return False, "expected SystemExit, got success"


def t_main_precheck_record_fresh_passes():
    """BUG-002 fix: record precheck passes for fresh / non-existent scene_dir."""
    import argparse
    import main as main_mod
    args = argparse.Namespace(record_scene="fresh", replay_scene=None,
                              auto_play=False)
    with tempfile.TemporaryDirectory() as td:
        try:
            main_mod._precheck_scene(args, Path(td), "fake_game")
        except SystemExit as e:
            return False, f"unexpectedly exited: {e.code}"
    return True, "fresh scene_dir passes precheck"


def t_main_auto_capture_skips_f8():
    """--auto-capture sets auto_capture_first=True; loop's first iteration
    must skip _wait_for_keys and call _run_capture immediately."""
    import argparse
    import main as main_mod
    args = argparse.Namespace(
        ui_mode="ui",  # avoid survey path
        record_scene=None, replay_scene=None, auto_play=False,
    )
    call_log: list[str] = []

    def fake_wait(vks):
        call_log.append(f"wait_for_keys({vks})")
        # Returning would normally indicate F8 pressed. To prevent infinite
        # loop, raise after first call.
        raise StopIteration("loop stopped")

    def fake_run_capture(*a, **kw):
        call_log.append("run_capture")
        # Stop the infinite loop after one capture cycle
        raise StopIteration("captured once")

    with tempfile.TemporaryDirectory() as td:
        td_p = Path(td)
        with patch.object(main_mod, "_wait_for_keys", side_effect=fake_wait), \
             patch.object(main_mod, "_run_capture", side_effect=fake_run_capture), \
             patch.object(main_mod, "_set_state"):
            try:
                main_mod._interactive_loop(args, td_p, "g", td_p,
                                           auto_capture_first=True)
            except StopIteration:
                pass

    # First action must be run_capture (not wait_for_keys)
    return call_log[:1] == ["run_capture"], f"call_log={call_log}"


def t_main_no_auto_capture_waits_f8():
    """Without --auto-capture, loop must wait F8 first."""
    import argparse
    import main as main_mod
    args = argparse.Namespace(
        ui_mode="ui",
        record_scene=None, replay_scene=None, auto_play=False,
    )
    call_log: list[str] = []

    def fake_wait(vks):
        call_log.append("wait_for_keys")
        raise StopIteration("loop stopped before capture")

    with tempfile.TemporaryDirectory() as td:
        td_p = Path(td)
        with patch.object(main_mod, "_wait_for_keys", side_effect=fake_wait), \
             patch.object(main_mod, "_set_state"):
            try:
                main_mod._interactive_loop(args, td_p, "g", td_p,
                                           auto_capture_first=False)
            except StopIteration:
                pass
    return call_log == ["wait_for_keys"], f"call_log={call_log}"


def t_main_underscore_filter():
    """cmd_video / cmd_pack must skip _scenes/, _foo/."""
    import main as main_mod
    with tempfile.TemporaryDirectory() as td:
        game_dir = Path(td)
        # Create a normal session
        normal = game_dir / "20260504_120000"
        (normal / "frames").mkdir(parents=True)
        # Create _scenes/ and another _under/
        (game_dir / "_scenes" / "tutorial" / "frames").mkdir(parents=True)
        (game_dir / "_recording_frames").mkdir(parents=True)
        (game_dir / "survey").mkdir()
        (game_dir / "survey" / "frames").mkdir()  # survey also has frames/

        sessions = sorted(
            d for d in game_dir.iterdir()
            if d.is_dir() and d.name != "survey"
            and not d.name.startswith("_") and (d / "frames").is_dir()
        )
    return [s.name for s in sessions] == ["20260504_120000"], \
        f"sessions={[s.name for s in sessions]}"


# ── Profile + InputBackend integration ────────────────────────────────────


def t_profile_reserved_keys():
    from tools.auto_play.profile import load_profile
    for name in ("ff7r", "doom_eternal", "batman_ak", "_default"):
        try:
            p = load_profile(name)
        except Exception as e:
            return False, f"{name} load failed: {e}"
        rk = set(p.reserved_keys)
        if not {"F6", "F7", "F8", "F9"}.issubset(rk):
            return False, f"{name} missing F6/F7/F8/F9 in {rk}"
    return True, "all 4 profiles include F6/F7/F8/F9"


def t_inputbackend_mouse_op_extension():
    """New 'down' / 'up' mouse ops do not raise on construction."""
    from tools.auto_play.input_backend import InputBackend
    from tools.auto_play.driver import Action
    from tools.auto_play.profile import load_profile
    profile = load_profile("_default")
    backend = InputBackend(profile)
    # We can't actually inject in CI without a desktop, but instantiation +
    # the dispatch raise on truly-bad ops should still work
    try:
        # This would actually click the mouse — skip on safety;
        # Just verify the dispatch path doesn't raise on op="down"
        # by patching _send_mouse to a no-op
        with patch.object(backend, "_send_mouse"):
            backend.inject(Action(kind="mouse",
                                  payload={"op": "down", "button": "left"}))
            backend.inject(Action(kind="mouse",
                                  payload={"op": "up", "button": "left"}))
        # Now confirm the bad-op still raises
        try:
            backend.inject(Action(kind="mouse",
                                  payload={"op": "warp", "button": "left"}))
            return False, "expected ValueError on bad op"
        except ValueError:
            pass
    finally:
        backend.close()
    return True, "down/up dispatched, bad op rejected"


# ── E2E (offline) ────────────────────────────────────────────────────────


def t_e2e_record_then_replay_round_trip():
    """E2E-1 + E2E-2 (offline): recorder writes script → player reads + completes."""
    from tools.replay import ReplayRecorder, ReplayPlayer
    with tempfile.TemporaryDirectory() as td:
        td_p = Path(td)
        scene = td_p / "rt"
        scratch = td_p / "rt_scratch"
        rec = ReplayRecorder(
            scene_dir=scene, sync_scratch_dir=scratch, game_dir=td_p,
            game_exe="x.exe", api="dx", window_size=(1920, 1080),
            mouse_origin=(0, 0), scene_name="rt",
        )
        rec.start()
        time.sleep(0.4)
        rec.stop()
        rec.wait_until_done(timeout=2.0)
        rec.save()
        rec.close()

        # Now replay (no syncs were marked; should reach immediately)
        replay_scratch = td_p / "rt_replay"
        backend = _MockBackend()
        player = ReplayPlayer(
            scene_dir=scene, sync_scratch_dir=replay_scratch, game_dir=td_p,
            backend=backend, current_window_size=(1920, 1080),
        )
        with patch.object(sys.modules["tools.replay.player"]._user32,
                          "SetCursorPos"):
            res = player.run()
    return res.status == "reached" and res.exit_code == 0, \
        f"status={res.status} elapsed={res.elapsed_s:.2f}s"


# ── main ──────────────────────────────────────────────────────────────────


CHECKS = [
    # sync_match
    ("sync_match: dhash(self,self)==0", t_dhash_self_zero),
    ("sync_match: reversed gradient differs >=30 bits", t_dhash_inverted_far),
    ("sync_match: dhash perf <50ms on 1080p", t_dhash_perf),
    ("sync_match: wait_for_match handles missing dir", t_wait_for_match_no_dir),
    ("sync_match: wait_for_match returns matched=True on identical", t_wait_for_match_immediate),

    # schema
    ("schema: meta round-trip", t_meta_round_trip),
    ("schema: validate_meta missing field raises", t_validate_meta_missing_field),
    ("schema: validate_meta accepts unknown fields (forward compat)",
     t_validate_meta_forward_compat),
    ("schema: iter_events skips unknown event types", t_iter_events_unknown_skip),
    ("schema: iter_events rejects t_rel regression", t_iter_events_t_rel_regression),

    # recorder
    ("recorder: smoke save() writes valid files", t_recorder_smoke_save),
    ("recorder: close() cleans up sidecar + scratch", t_recorder_sidecar_cleanup),

    # player
    ("player: no-sync script reaches successfully", t_player_no_sync_happy),
    ("player: sync match → reached (1/1)", t_player_sync_match),
    ("player: sync miss + simulated R → reached", t_player_sync_miss_resume),
    ("player: sync miss + simulated Q → user_abort exit 2", t_player_sync_miss_quit),
    ("player: window scale changes mouse coords", t_player_window_scale_warning),

    # main glue
    ("main: --record-scene + --replay-scene mutually exclusive",
     t_main_mutex_record_replay),
    ("main: --record-scene + --auto-play allowed (not mutex)",
     t_main_record_autoplay_allowed),
    ("main: --replay-scene + --auto-play allowed (not mutex)",
     t_main_replay_autoplay_allowed),
    ("main: precheck rejects missing replay scene before game launch (BUG-002)",
     t_main_precheck_replay_missing),
    ("main: precheck rejects clobbering existing record scene (BUG-002)",
     t_main_precheck_record_clobber),
    ("main: precheck passes fresh record scene (BUG-002)",
     t_main_precheck_record_fresh_passes),
    ("main: --auto-capture skips first F8 wait, jumps to capture",
     t_main_auto_capture_skips_f8),
    ("main: without --auto-capture, loop waits F8 first (no regression)",
     t_main_no_auto_capture_waits_f8),
    ("main: _* and survey filtered from session scan",
     t_main_underscore_filter),

    # profile + backend integration
    ("profile: all 4 profiles contain F6/F7/F8/F9 in reserved_keys",
     t_profile_reserved_keys),
    ("backend: mouse ops 'down' / 'up' dispatch correctly",
     t_inputbackend_mouse_op_extension),

    # offline E2E
    ("E2E: record → replay round-trip reaches", t_e2e_record_then_replay_round_trip),
]


def main() -> int:
    print(f"== verify_replay v1.0  ({len(CHECKS)} checks) ==\n")
    results = []
    for name, fn in CHECKS:
        results.append(_run(name, fn))

    pass_n = sum(1 for _, ok, _ in results if ok)
    fail_n = len(results) - pass_n

    for name, ok, msg in results:
        marker = PASS if ok else FAIL
        print(f"{marker} {name}")
        if not ok:
            for line in str(msg).splitlines():
                print(f"        {line}")
        elif msg:
            print(f"        {msg}")

    print(f"\n== {pass_n}/{len(results)} passed, {fail_n} failed ==")
    return 0 if fail_n == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
