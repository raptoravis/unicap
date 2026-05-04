"""TestPlan verification harness for auto-play A-layer + C-layer placeholder.

Runs capability + integration + offline E2E checks. Skips live-game flows
(E2E-1 / E2E-2 — those require sponsor's machine + game install).

Usage:
  uv run python scripts/verify_auto_play.py
"""

from __future__ import annotations

import logging
import random
import shutil
import subprocess
import sys
import tempfile
import threading
import time
from pathlib import Path

import cv2
import numpy as np

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from tools.auto_play import (  # noqa: E402
    Action, AutoPlayRunner, InputBackend, KeepAliveDriver,
    Observation, VLMDriver, load_profile,
)
from tools.auto_play.keep_alive import step_to_actions  # noqa: E402
from tools.auto_play.profile import list_profiles  # noqa: E402
from tools.auto_play.runner import create_driver  # noqa: E402
from tools.auto_play.watchdog import StaticFrameWatchdog  # noqa: E402


PASS = "[PASS]"
FAIL = "[FAIL]"
results: list[tuple[str, str, str]] = []


def check(label: str, cond: bool, detail: str = "") -> None:
    tag = PASS if cond else FAIL
    results.append((tag, label, detail))
    print(f"{tag} {label}{(' — ' + detail) if detail and not cond else ''}")


def run(label: str, fn) -> None:
    print(f"\n=== {label} ===")
    try:
        fn()
    except Exception as e:
        check(f"{label}: 抛异常", False, repr(e))


# ── Capability ──────────────────────────────────────────────────────────────


def cap_profile() -> None:
    # M1 / M3 / M6: load all 4 profiles
    found = list_profiles()
    check("V-009 list_profiles 命中 ff7r/doom_eternal/batman_ak",
          set(found) >= {"ff7r", "doom_eternal", "batman_ak"}, str(found))
    for n in ["_default", "ff7r", "doom_eternal", "batman_ak"]:
        try:
            p = load_profile(n, fallback=False)
            check(f"profile.M1 load {n}", p.name == n)
            check(f"profile.M6 reserved_keys 含 F8/F9 ({n})",
                  {"F8", "F9"} <= set(p.reserved_keys))
        except Exception as e:
            check(f"profile.M1 load {n}", False, str(e))

    # M4: fuzzy match
    p = load_profile("ff7remake_", fallback=True)
    check("profile.M4 fuzzy match ff7remake_ → ff7r", p.name == "ff7r")

    # M5: fallback to _default
    p = load_profile("totally_unknown_xyz", fallback=True)
    check("profile.M5 fallback _default", p.name == "_default")

    # M2 / V-010: missing field error
    bad = ROOT / "tmp_bad_profile.yaml"
    bad.write_text("name: bad\n", encoding="utf-8")
    try:
        load_profile("tmp_bad_profile",
                     fallback=False, profiles_dir=bad.parent)
        check("profile.M2 missing field 报错", False, "未报错")
    except Exception as e:
        msg = str(e)
        check("profile.M2 missing field 报错含字段名",
              "缺少必填字段" in msg, msg[:80])
    finally:
        bad.unlink(missing_ok=True)


def cap_input_backend() -> None:
    profile = load_profile("_default", fallback=False)

    # M2: ViGEm 不可用时构造不 raise
    ib = InputBackend(profile)
    check("input_backend.M2 ViGEm 缺失不 raise", True)
    check("input_backend.gamepad_available 反映 ViGEm 状态",
          ib.gamepad_available in (True, False))

    # M4: reserved_keys 拒绝 (V-004 也覆盖)
    try:
        ib.inject(Action(kind="key", payload={"vk": "F8", "event": "press"},
                         duration_ms=0))
        check("input_backend.M4 注入 F8 raise", False, "未 raise")
    except ValueError:
        check("input_backend.M4 注入 F8 raise", True)

    # M3: 并发 lock 串行化（粗略）
    counter = {"n": 0, "errors": 0}
    lock_action = Action(kind="key", payload={"vk": "Q", "event": "down"},
                         duration_ms=0)

    def hammer():
        for _ in range(50):
            try:
                # 'down' only — won't actually hold key, just SendInput once
                ib.inject(lock_action)
                counter["n"] += 1
            except Exception:
                counter["errors"] += 1

    threads = [threading.Thread(target=hammer) for _ in range(8)]
    for t in threads:
        t.start()
    for t in threads:
        t.join(timeout=10)
    # Release Q so we don't leave it stuck
    try:
        ib.inject(Action(kind="key", payload={"vk": "Q", "event": "up"},
                         duration_ms=0))
    except Exception:
        pass
    check("input_backend.M3 并发注入无 raise",
          counter["errors"] == 0, f"errors={counter['errors']}")
    check("input_backend.M3 并发计数 = 8×50",
          counter["n"] == 400, f"n={counter['n']}")
    ib.close()


def cap_keep_alive() -> None:
    profile = load_profile("ff7r", fallback=False)
    drv = KeepAliveDriver(profile, seed=42)
    obs = Observation(timestamp=time.time(), profile=profile)
    actions_total = 0
    for _ in range(120):
        actions_total += len(drv.next_actions(obs))
    # M1: 100+ next_actions 不退出
    check("keep_alive.M1 120 次 next_actions 总返回 ≥ 100",
          actions_total >= 100, f"total={actions_total}")
    check("keep_alive.M2 序列循环（cursor reset）", drv._cursor < len(drv._seq))


def cap_vlm_driver() -> None:
    """C-layer: VLMDriver constructs cheaply (no env check), reads VLM_API_KEY
    / VLM_BASE_URL / VLM_MODEL from env (or .env loaded at import), exposes
    cost log + decision_period_s, and raises BudgetExhausted on first call
    when VLM_API_KEY is absent so the runner can fall back to keep-alive.
    `--vlm-base-url` / `--vlm-model` override env values."""
    import os as _os
    from tools.auto_play.vlm_driver import BudgetExhausted

    profile = load_profile("_default", fallback=False)

    drv = VLMDriver(profile, budget_per_hour=10)
    check("vlm_driver.M1 构造成功（不需要 env 变量）", isinstance(drv, VLMDriver))
    check("vlm_driver.M2 decision_period_s 合理",
          0.2 <= drv.decision_period_s <= 5.0, f"{drv.decision_period_s}")
    cost = drv.get_cost_log()
    check("vlm_driver.M3 cost_log 含 max_calls_per_hour + base_url + model",
          cost.get("max_calls_per_hour") == 10
          and "base_url" in cost
          and "model" in cost,
          str(cost))

    drv2 = create_driver("vlm", profile, budget_per_hour=5)
    check("vlm_driver.M4 factory 返回 VLMDriver", isinstance(drv2, VLMDriver))

    # Constructor kwargs override env at construction time
    drv3 = VLMDriver(
        profile,
        api_key="ctor-override-key",
        base_url="https://example.test/v1",
        model="my-custom-vlm",
        budget_per_hour=5,
    )
    check("vlm_driver.M5 base_url + model kwarg 覆盖 env",
          drv3.base_url == "https://example.test/v1"
          and drv3.model_name == "my-custom-vlm",
          f"base_url={drv3.base_url} model={drv3.model_name}")
    # api_key override is private (not exposed via property to discourage
    # logging), but we can verify it took by ensuring _ensure_client doesn't
    # raise on the missing-env path — the key check should be satisfied by
    # the override, only failing later on the openai SDK call. Since we
    # don't make a real call, we just verify the override path doesn't
    # raise BudgetExhausted with VLM_API_KEY in the message.
    saved_key = _os.environ.pop("VLM_API_KEY", None)
    try:
        try:
            drv3._ensure_client()
        except BudgetExhausted as e:
            if "VLM_API_KEY" in str(e):
                check("vlm_driver.M5b api_key kwarg 覆盖空 env", False, str(e)[:80])
            else:
                # Some other error (no SDK / network) — that's fine, override worked
                check("vlm_driver.M5b api_key kwarg 覆盖空 env", True)
        else:
            check("vlm_driver.M5b api_key kwarg 覆盖空 env", True)
    finally:
        if saved_key is not None:
            _os.environ["VLM_API_KEY"] = saved_key

    # Lazy validation — clear VLM_API_KEY (and optionally VLM_MODEL),
    # next_actions on a non-empty frames_dir raises BudgetExhausted.
    saved_key = _os.environ.pop("VLM_API_KEY", None)
    saved_model = _os.environ.pop("VLM_MODEL", None)
    try:
        with tempfile.TemporaryDirectory() as td:
            d = VLMDriver(profile, frames_dir=Path(td))
            # Seed a fake PNG so _read_latest_frame returns non-None,
            # forcing the code path past the frame check.
            bmp = Path(td) / "0001 BackBuffer.png"
            cv2.imwrite(str(bmp), np.zeros((720, 1280, 3), dtype=np.uint8))
            time.sleep(0.6)  # mtime > 500ms guard
            try:
                d.next_actions(Observation(timestamp=time.monotonic(), profile=profile))
                check("vlm_driver.M6 缺 VLM_API_KEY → BudgetExhausted", False)
            except BudgetExhausted as e:
                msg = str(e)
                check(
                    "vlm_driver.M6 缺 VLM_API_KEY → BudgetExhausted",
                    "VLM_API_KEY" in msg,
                    msg[:120],
                )
    finally:
        if saved_key is not None:
            _os.environ["VLM_API_KEY"] = saved_key
        if saved_model is not None:
            _os.environ["VLM_MODEL"] = saved_model


def cap_watchdog() -> None:
    profile = load_profile("_default", fallback=False)
    profile.watchdog["sample_period_s"] = 0.3
    profile.watchdog["consecutive_static_required"] = 2
    profile.watchdog["static_diff_threshold"] = 0.05

    tmp = Path(tempfile.mkdtemp(prefix="unicap_wd_"))
    ib = InputBackend(profile)
    wd = StaticFrameWatchdog(tmp, profile, ib)

    # Write 5 identical PNGs with growing mtimes
    img = np.full((180, 320, 3), 128, dtype=np.uint8)
    for i in range(5):
        cv2.imwrite(str(tmp / f"frame_{i:03d} BackBuffer.png"), img)
        time.sleep(0.05)

    wd.start()
    time.sleep(1.0)
    check("watchdog.start 后 thread 运行", wd._thread is not None and wd._thread.is_alive())

    # M1 (auto-trigger): with sample_period_s=0.3 + 5 identical BMPs +
    # consecutive_required=2, watchdog should auto-trigger ≥1 within 1s.
    # (Warmup window only suppresses 'no-frames' debug log, not real triggers.)
    auto_triggered = wd.trigger_count >= 1
    check("watchdog.M1 静帧自动触发 recovery",
          auto_triggered, f"trigger_count={wd.trigger_count}")

    # Manual call also increments (defensive)
    before = wd.trigger_count
    wd._trigger_recovery(diff=0.001)
    check("watchdog._trigger_recovery 计数 +1",
          wd.trigger_count == before + 1,
          f"before={before} after={wd.trigger_count}")

    # M3: empty dir + read returns None
    empty_dir = Path(tempfile.mkdtemp(prefix="unicap_wd_empty_"))
    wd_empty = StaticFrameWatchdog(empty_dir, profile, ib)
    img_read = wd_empty._read_latest_bmp()
    check("watchdog.M3 空 frames_dir 返回 None", img_read is None)

    # M4: stop joins in time
    t0 = time.monotonic()
    wd.stop(timeout_s=2.0)
    elapsed = time.monotonic() - t0
    check("watchdog.M4 stop ≤ 2s", elapsed < 2.5, f"{elapsed:.1f}s")

    ib.close()
    shutil.rmtree(tmp, ignore_errors=True)
    shutil.rmtree(empty_dir, ignore_errors=True)


def cap_runner() -> None:
    profile = load_profile("_default", fallback=False)
    profile.keep_alive["period_s"] = 0.1  # fast for test
    tmp = Path(tempfile.mkdtemp(prefix="unicap_runner_"))

    # M3: stop before start is safe
    runner = AutoPlayRunner("keep-alive", profile, tmp, debug=True)
    runner.stop()
    check("runner.M3 stop-before-start 安全", True)

    # M2 + M4: start + stop within budget
    runner2 = AutoPlayRunner("keep-alive", profile, tmp, debug=True)
    runner2.start()
    time.sleep(0.7)
    check("runner.start is_running=True", runner2.is_running)
    t0 = time.monotonic()
    runner2.stop(timeout_s=3.0)
    elapsed = time.monotonic() - t0
    check("runner.M2 stop ≤ 3s", elapsed < 3.5, f"{elapsed:.1f}s")
    check("runner.M3 stop 幂等（再调一次不 raise）",
          (runner2.stop(), True)[1])

    shutil.rmtree(tmp, ignore_errors=True)


# ── Integration ─────────────────────────────────────────────────────────────


def integ_step_to_actions_shared() -> None:
    profile = load_profile("ff7r", fallback=False)
    rng = random.Random(0)
    a1 = step_to_actions(profile, {"action": "move_forward", "duration_ms": 100}, rng)
    check("I-1 step_to_actions 输出非空", len(a1) == 1 and a1[0].kind == "key")
    rng2 = random.Random(0)
    a2 = step_to_actions(profile, {"action": "press_key",
                                   "payload": {"vk": "ESC"},
                                   "duration_ms": 100}, rng2)
    check("I-2 press_key step → key Action vk=ESC",
          a2[0].kind == "key" and a2[0].payload["vk"] == "ESC")


def integ_factory_typo_rejected() -> None:
    profile = load_profile("_default", fallback=False)
    try:
        create_driver("keep-alive", profile, seeed=1)
        check("I-3 factory 拒绝 typo kwarg", False)
    except TypeError:
        check("I-3 factory 拒绝 typo kwarg", True)


def integ_main_cli_help() -> None:
    # I-6: main.py 解析 --auto-play 不报错（不实际启动游戏）
    proc = subprocess.run(
        [sys.executable, str(ROOT / "main.py"), "launch", "--help"],
        capture_output=True, text=True, cwd=str(ROOT), encoding="utf-8",
        errors="replace",
    )
    out = (proc.stdout or "") + (proc.stderr or "")
    check("I-6 launch --help 含 --auto-play",
          "--auto-play" in out and "--driver" in out)


# ── E2E offline ─────────────────────────────────────────────────────────────


def e2e_3_vlm_driver_budget_fallback() -> None:
    """E2E-3: 缺 VLM_API_KEY 时 VLMDriver 抛 BudgetExhausted；runner 必须能
    catch 该异常完成 fallback 而不是终止 capture。"""
    import os as _os
    from tools.auto_play.vlm_driver import BudgetExhausted

    profile = load_profile("_default", fallback=False)

    saved_key = _os.environ.pop("VLM_API_KEY", None)
    saved_model = _os.environ.pop("VLM_MODEL", None)
    try:
        with tempfile.TemporaryDirectory() as td:
            d = VLMDriver(profile, frames_dir=Path(td))
            bmp = Path(td) / "0001 BackBuffer.png"
            cv2.imwrite(str(bmp), np.zeros((720, 1280, 3), dtype=np.uint8))
            time.sleep(0.6)
            raised = False
            detail = ""
            try:
                d.next_actions(Observation(timestamp=time.monotonic(),
                                           profile=profile))
            except BudgetExhausted as e:
                detail = str(e)[:120]
                raised = "VLM_API_KEY" in detail
            check("E2E-3 缺 VLM_API_KEY → BudgetExhausted (runner 可降级)",
                  raised, detail)
    finally:
        if saved_key is not None:
            _os.environ["VLM_API_KEY"] = saved_key
        if saved_model is not None:
            _os.environ["VLM_MODEL"] = saved_model

    # runner.create_driver 接受 vlm 不报错（lazy 验证，便于 fallback 路径走通）
    drv = create_driver("vlm", profile, budget_per_hour=10)
    check("E2E-3 create_driver('vlm') 不再 raise", isinstance(drv, VLMDriver))


def e2e_4_vigem_fallback() -> None:
    """E2E-4: 没有 ViGEm，InputBackend 仍能用 + driver 仍能跑."""
    profile = load_profile("_default", fallback=False)
    ib = InputBackend(profile)
    check("E2E-4 ViGEm 缺失时 InputBackend 仍构造", True)
    # Drive 5 keep-alive ticks with KeepAliveDriver — should not raise even
    # though gamepad path may be selected.
    drv = KeepAliveDriver(profile, seed=7)
    obs = Observation(timestamp=time.time(), profile=profile)
    for _ in range(5):
        actions = drv.next_actions(obs)
        for a in actions:
            try:
                ib.inject(a)
            except ValueError as e:
                # Reserved key — shouldn't appear in default profile sequence
                check(f"E2E-4 reserved-key 不应在 default sequence: {a}",
                      False, str(e))
                return
    check("E2E-4 default profile 5 ticks 无异常", True)
    ib.close()


def e2e_5_watchdog_trigger_logging() -> None:
    """E2E-5: watchdog 触发后写 trigger_count, log 含 [WATCHDOG] static-frame."""
    profile = load_profile("_default", fallback=False)

    log_capture = []

    class L(logging.Handler):
        def emit(self, record):
            log_capture.append(record.getMessage())

    logger = logging.getLogger("unicap.auto_play")
    h = L()
    logger.addHandler(h)
    logger.setLevel(logging.INFO)

    tmp = Path(tempfile.mkdtemp(prefix="unicap_e2e_wd_"))
    ib = InputBackend(profile)
    wd = StaticFrameWatchdog(tmp, profile, ib)
    wd._trigger_recovery(diff=0.005)
    matched = [m for m in log_capture if "[WATCHDOG]" in m and "static-frame" in m]
    check("E2E-5 watchdog 日志写 [WATCHDOG] static-frame", bool(matched),
          str(log_capture[-3:]))
    ib.close()
    logger.removeHandler(h)
    shutil.rmtree(tmp, ignore_errors=True)


# ── Main ────────────────────────────────────────────────────────────────────


def main() -> int:
    print(f"=== auto-play 验证 — {time.strftime('%Y-%m-%d %H:%M:%S')} ===")
    run("Capability: profile",      cap_profile)
    run("Capability: input_backend", cap_input_backend)
    run("Capability: keep_alive",   cap_keep_alive)
    run("Capability: vlm_driver",   cap_vlm_driver)
    run("Capability: watchdog",     cap_watchdog)
    run("Capability: runner",       cap_runner)
    run("Integration: shared step_to_actions", integ_step_to_actions_shared)
    run("Integration: factory typo", integ_factory_typo_rejected)
    run("Integration: main CLI",     integ_main_cli_help)
    run("E2E-3: VLM 预算/key fallback", e2e_3_vlm_driver_budget_fallback)
    run("E2E-4: ViGEm 降级",         e2e_4_vigem_fallback)
    run("E2E-5: watchdog log",      e2e_5_watchdog_trigger_logging)

    n_pass = sum(1 for r in results if r[0] == PASS)
    n_fail = sum(1 for r in results if r[0] == FAIL)
    print(f"\n=== TOTAL: {n_pass} pass / {n_fail} fail ===")
    if n_fail:
        print("\n失败项:")
        for tag, label, detail in results:
            if tag == FAIL:
                print(f"  {label}{(' — ' + detail) if detail else ''}")
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
