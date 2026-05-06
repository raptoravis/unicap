"""AutoPlayRunner — orchestrates BotDriver + StaticFrameWatchdog + InputBackend
across the lifetime of one capture session.
"""

from __future__ import annotations

import logging
import logging.handlers
import threading
import time
from pathlib import Path
from typing import TYPE_CHECKING

from tools.auto_play.driver import BotDriver, Observation
from tools.auto_play.input_backend import InputBackend
from tools.auto_play.keep_alive import KeepAliveDriver
from tools.auto_play.profile import GameProfile
from tools.auto_play.vlm_driver import BudgetExhausted, VLMDriver
from tools.auto_play.watchdog import StaticFrameWatchdog

if TYPE_CHECKING:
    pass


log = logging.getLogger("unicap.auto_play")


def create_driver(
    name: str,
    profile: GameProfile,
    *,
    seed: int | None = None,
    api_key: str | None = None,
    base_url: str | None = None,
    model: str | None = None,
    budget_per_hour: int = 60,
    frames_dir: Path | None = None,
) -> BotDriver:
    """Factory: 'keep-alive' uses seed only; 'vlm' reads VLM_API_KEY /
    VLM_BASE_URL / VLM_MODEL from env, with `api_key=` / `base_url=` /
    `model=` kwargs as optional one-shot overrides.

    Other kwargs raise TypeError at the call site rather than being silently
    swallowed — caller must adapt to driver-specific args.
    """
    if name == "keep-alive":
        return KeepAliveDriver(profile, seed=seed)
    if name == "vlm":
        return VLMDriver(
            profile,
            api_key=api_key,
            base_url=base_url,
            model=model,
            budget_per_hour=budget_per_hour,
            frames_dir=frames_dir,
        )
    raise ValueError(f"未知 driver: {name!r} (支持: keep-alive, vlm)")


def _setup_log_handler(log_path: Path) -> None:
    """Idempotent: install a rolling file handler on the unicap.auto_play logger."""
    logger = logging.getLogger("unicap.auto_play")
    logger.setLevel(logging.INFO)
    log_path.parent.mkdir(parents=True, exist_ok=True)
    for h in logger.handlers:
        if isinstance(h, logging.handlers.RotatingFileHandler) and \
           getattr(h, "baseFilename", None) == str(log_path):
            return  # already installed
    handler = logging.handlers.RotatingFileHandler(
        log_path, maxBytes=5 * 1024 * 1024, backupCount=3, encoding="utf-8",
    )
    handler.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(message)s"))
    logger.addHandler(handler)


class AutoPlayRunner:
    def __init__(
        self,
        driver_name: str,
        profile: GameProfile,
        frames_dir: Path,
        debug: bool = False,
        vlm_api_key: str | None = None,
        vlm_base_url: str | None = None,
        vlm_model: str | None = None,
        vlm_budget_per_hour: int = 10,
        log_path: Path | None = None,
    ) -> None:
        self._profile = profile
        self._frames_dir = frames_dir
        self._debug = debug
        self._driver_name = driver_name

        if log_path is None:
            import tempfile
            log_path = Path(tempfile.gettempdir()) / "unicap" / "auto_play.log"
        _setup_log_handler(log_path)
        if debug:
            logging.getLogger("unicap.auto_play").setLevel(logging.DEBUG)

        self._backend = InputBackend(profile, debug=debug)
        # `hybrid` = keep_alive runs the main loop; the watchdog gets a VLM
        # consultant that fires only when frames go static (so VLM cost is
        # bounded by watchdog trigger rate, not 1 Hz). The patrol thread
        # additionally polls VLM every 12s (independent of watchdog) to catch
        # popups that frame-diff detection misses (e.g. FF7R split-screen
        # tutorial: left half live game + right half popup with GIF preview —
        # neither global, local-only, nor long-window static checks fire).
        #
        # `vlm` mode does NOT feed the VLM to the watchdog. Reasoning: when
        # the main loop is VLM-driven, the watchdog firing means the VLM has
        # already seen the static frame multiple times and kept outputting
        # "walk forward" anyway (typical failure mode: VLM sees no wall
        # texture, only a vending machine / signpost / small prop, doesn't
        # recognize physical collision, recommends walk forward). Re-asking
        # the same VLM from the watchdog gets the same walk-forward — useless.
        # In `vlm` mode the watchdog falls through to profile.recovery which
        # is a deterministic physical-stuck unstick sequence (long back-step
        # + 4-turn 180°+ + forward) that doesn't depend on visual judgment.
        # No patrol in vlm mode: main loop already polls every 0.5-3s.
        vlm_for_watchdog: VLMDriver | None = None
        patrol_vlm: VLMDriver | None = None
        if driver_name == "keep-alive":
            self._driver = create_driver(driver_name, profile)
        elif driver_name == "vlm":
            self._driver = create_driver(
                driver_name, profile,
                api_key=vlm_api_key,
                base_url=vlm_base_url,
                model=vlm_model,
                budget_per_hour=vlm_budget_per_hour,
                frames_dir=frames_dir,
            )
            # vlm_for_watchdog stays None — watchdog uses profile.recovery
        elif driver_name == "hybrid":
            self._driver = create_driver("keep-alive", profile)
            vlm_for_watchdog = create_driver(
                "vlm", profile,
                api_key=vlm_api_key,
                base_url=vlm_base_url,
                model=vlm_model,
                budget_per_hour=vlm_budget_per_hour,
                frames_dir=frames_dir,
            )
            patrol_vlm = vlm_for_watchdog
        else:
            raise ValueError(
                f"未知 driver: {driver_name!r} (支持: keep-alive, vlm, hybrid)"
            )
        # Shared "recovery in progress" event — watchdog sets while running
        # profile.recovery; main driver loop + heartbeat thread skip their own
        # injects while set. Without this, watchdog's S+turn back-step gets
        # immediately overwritten by main loop's W+turn from a concurrent VLM
        # tick (same ~7s window), so the recovery sequence physically cancels
        # itself. See log around 17:51:31 for a concrete failure case.
        self._recovery_active_evt = threading.Event()
        self._watchdog = StaticFrameWatchdog(
            frames_dir=frames_dir, profile=profile, input_backend=self._backend,
            log_path=log_path, vlm_driver=vlm_for_watchdog,
            recovery_active_evt=self._recovery_active_evt,
        )
        # Hybrid-mode patrol: same VLM client as watchdog, separate prompt
        # (dismiss-only). 12s period × 60min ≈ 300 calls/h — leave ~60 calls/h
        # headroom for watchdog/UI-mask/OCR triggers, hence default budget 360.
        self._patrol_vlm: VLMDriver | None = patrol_vlm
        self._patrol_period_s = 12.0
        self._patrol_disabled = False
        self._patrol_thread: threading.Thread | None = None

        self._stop_evt = threading.Event()
        self._driver_thread: threading.Thread | None = None
        self._heartbeat_thread: threading.Thread | None = None
        self._stopped = False

        # Background-heartbeat config: bridges the 3-5s VLM-API gap so the bot
        # doesn't stand still while the main loop is blocked on chat.completions.
        # Only meaningful for `vlm` and `hybrid` (keep-alive's main loop tick is
        # already <1s; nothing to bridge). Reads InputBackend.last_inject_at_mono
        # — when no inject has happened in the last _heartbeat_silence_s,
        # injects a single forward-key press.
        forward_key = (
            self._profile.controls.get("move_forward")
            or "W"
        )
        from tools.auto_play.driver import Action as _Action
        self._heartbeat_action = _Action(
            kind="key",
            payload={"vk": forward_key, "event": "press"},
            duration_ms=1500,
        )
        self._heartbeat_silence_s = 1.5    # tolerable inject gap before bridging
        self._heartbeat_check_s = 0.5      # how often the heartbeat thread polls

    def start(self) -> None:
        if self._driver_thread is not None and self._driver_thread.is_alive():
            return
        log.info(
            "[AUTO-PLAY] 启动 driver=%s profile=%s gamepad=%s",
            self._driver_name, self._profile.name,
            "vigem_ok" if self._backend.gamepad_available else "unavailable",
        )
        print(f"[AUTO-PLAY] driver={self._driver_name} profile={self._profile.name}"
              f" gamepad={'vigem_ok' if self._backend.gamepad_available else 'unavailable'}",
              flush=True)
        # Surface VLM config so sponsors can sanity-check which endpoint /
        # model is actually in effect (base_url + model resolve from CLI flags
        # → env vars → .env at construction; printing the resolved value here
        # avoids guesswork). In hybrid mode the VLM lives inside the watchdog,
        # not as the main driver, so reach into it explicitly.
        vlm_for_print = None
        if self._driver_name == "vlm":
            vlm_for_print = self._driver
        elif self._driver_name == "hybrid":
            vlm_for_print = getattr(self._watchdog, "_vlm_driver", None)
        if vlm_for_print is not None:
            base = getattr(vlm_for_print, "base_url", None) or "(SDK default)"
            model = getattr(vlm_for_print, "model_name", "") or "(unset)"
            budget = getattr(getattr(vlm_for_print, "_budget", None),
                             "max_calls_per_hour", "?")
            tag = "VLM endpoint" if self._driver_name == "vlm" \
                  else "hybrid VLM (watchdog 触发时介入)"
            print(f"[AUTO-PLAY] {tag} base_url={base} model={model}"
                  f" budget={budget}/h", flush=True)

        self._stop_evt.clear()
        self._driver.on_start()
        self._watchdog.start()
        self._driver_thread = threading.Thread(
            target=self._driver_loop, name="auto-play-driver", daemon=True,
        )
        self._driver_thread.start()
        if self._patrol_vlm is not None:
            self._patrol_thread = threading.Thread(
                target=self._patrol_loop, name="auto-play-patrol", daemon=True,
            )
            self._patrol_thread.start()
            log.info(
                "[PATROL] 启动 period=%.1fs (hybrid mode dismiss-only consultant)",
                self._patrol_period_s,
            )
        # Heartbeat thread — only when the main driver may stall on network
        # (vlm / hybrid). For pure keep-alive driver the main loop never
        # blocks long enough to need bridging.
        if self._driver_name in ("vlm", "hybrid"):
            self._heartbeat_thread = threading.Thread(
                target=self._heartbeat_loop, name="auto-play-heartbeat",
                daemon=True,
            )
            self._heartbeat_thread.start()
            log.info(
                "[HEARTBEAT] 启动 silence=%.1fs check=%.1fs key=%s",
                self._heartbeat_silence_s, self._heartbeat_check_s,
                self._heartbeat_action.payload.get("vk"),
            )

    def stop(self, timeout_s: float = 3.0) -> None:
        if self._stopped:
            return
        self._stopped = True
        self._stop_evt.set()
        try:
            self._watchdog.stop(timeout_s=timeout_s)
        except Exception as e:
            log.warning("[AUTO-PLAY] watchdog stop 异常: %s", e)
        if self._patrol_thread is not None:
            self._patrol_thread.join(timeout=timeout_s)
            if self._patrol_thread.is_alive():
                log.warning("[PATROL] thread join 超时 (%.1fs)", timeout_s)
            self._patrol_thread = None
        if self._heartbeat_thread is not None:
            self._heartbeat_thread.join(timeout=timeout_s)
            if self._heartbeat_thread.is_alive():
                log.warning("[HEARTBEAT] thread join 超时 (%.1fs)", timeout_s)
            self._heartbeat_thread = None
        if self._driver_thread is not None:
            self._driver_thread.join(timeout=timeout_s)
            if self._driver_thread.is_alive():
                log.warning("[AUTO-PLAY] driver thread 超时未退出 (%.1fs)", timeout_s)
            self._driver_thread = None
        try:
            self._driver.on_stop()
        except Exception as e:
            log.warning("[AUTO-PLAY] driver.on_stop 异常: %s", e)
        try:
            self._backend.close()
        except Exception as e:
            log.warning("[AUTO-PLAY] backend close 异常: %s", e)
        log.info("[AUTO-PLAY] stop 完成 watchdog 触发=%d", self._watchdog.trigger_count)
        print(f"[AUTO-PLAY] 停止；watchdog 触发 {self._watchdog.trigger_count} 次", flush=True)

    @property
    def is_running(self) -> bool:
        return (
            self._driver_thread is not None
            and self._driver_thread.is_alive()
            and not self._stop_evt.is_set()
        )

    def _heartbeat_loop(self) -> None:
        """Background heartbeat — bridges the 3-5s VLM-API gap. The main
        driver loop is blocked on `client.chat.completions.create()` for the
        whole call latency, during which it cannot inject anything itself.
        Without this thread the bot stands still ~50% of every tick.

        Strategy: poll InputBackend.last_inject_at_mono every check_s. When
        no inject has happened in the last silence_s (typical: 1.5s), push a
        single forward-key press (default W 1500ms). The press's own duration
        updates last_inject_at_mono, so subsequent ticks coalesce — only one
        heartbeat fires per stall window.

        Heartbeat shares InputBackend.lock with the driver loop and watchdog;
        all three serialize their inject() calls, so no input collisions."""
        heartbeat_count = 0
        while not self._stop_evt.is_set():
            self._stop_evt.wait(self._heartbeat_check_s)
            if self._stop_evt.is_set():
                return
            # Yield to watchdog while it's running profile.recovery — heartbeat
            # W during recovery would cancel the back-step / 4-turn debug.
            if self._recovery_active_evt.is_set():
                continue
            silent = time.monotonic() - self._backend.last_inject_at_mono
            if silent < self._heartbeat_silence_s:
                continue
            try:
                self._backend.inject(self._heartbeat_action)
            except Exception as e:
                log.warning("[HEARTBEAT] inject 异常: %s", e)
                continue
            heartbeat_count += 1
            if heartbeat_count <= 3 or heartbeat_count % 10 == 0:
                # Don't flood the log — first few heartbeats then every 10th.
                log.info(
                    "[HEARTBEAT] silent=%.1fs → 注入 W %dms (heartbeat#%d)",
                    silent, self._heartbeat_action.duration_ms, heartbeat_count,
                )

    def _patrol_loop(self) -> None:
        """Hybrid-mode supplementary VLM consultant. Every patrol_period_s,
        ask the VLM 'is there an overlay/popup that needs dismissing?' (using
        the conservative patrol prompt that returns [] when uncertain).
        Independent of watchdog static-frame detection — covers cases where
        frame-diff statistics can't classify the screen as stuck (split-screen
        tutorial popups, animated overlays, etc.).

        On BudgetExhausted: permanently disable patrol for the rest of the
        session (capture continues; watchdog may still trigger via fallback
        recovery)."""
        if self._patrol_vlm is None:
            return
        # Stagger first tick so patrol doesn't fire at the same instant as
        # watchdog's first sample — reduces concurrent VLM calls.
        first_delay = max(2.0, self._patrol_period_s / 2)
        self._stop_evt.wait(first_delay)
        while not self._stop_evt.is_set():
            if self._patrol_disabled:
                return
            t0 = time.monotonic()
            try:
                obs = Observation(timestamp=time.time(), profile=self._profile)
                actions = self._patrol_vlm.patrol_check(obs) or []
            except BudgetExhausted as e:
                log.warning(
                    "[PATROL] VLM 不可用 (%s) — 本 session 后续不再 patrol", e,
                )
                self._patrol_disabled = True
                return
            except Exception as e:
                log.warning("[PATROL] 决策异常: %s — 本次跳过", e)
                actions = []

            if actions:
                log.info(
                    "[PATROL] 检测到 overlay → 注入 %d action(s)", len(actions),
                )
                for a in actions:
                    if self._stop_evt.is_set():
                        return
                    try:
                        self._backend.inject(a)
                    except Exception as e:
                        log.warning("[PATROL] inject 异常: %s", e)

            elapsed = time.monotonic() - t0
            sleep_s = max(0.5, self._patrol_period_s - elapsed)
            self._stop_evt.wait(sleep_s)

    @staticmethod
    def _action_summary(action: "Action") -> str:
        """Tight one-token summary of an Action for tick logs.
        e.g. key/W/1500ms, mouse/move/+300/0, mouse/click/left, gamepad/stick/L/0.0,1.0
        """
        kind = action.kind
        p = action.payload or {}
        d = action.duration_ms
        if kind == "key":
            return f"key/{p.get('vk', '?')}/{d}ms"
        if kind == "mouse":
            op = p.get("op", "?")
            if op == "move":
                return f"mouse/move/{p.get('dx', 0)},{p.get('dy', 0)}"
            if op == "click":
                return f"mouse/click/{p.get('button', '?')}/{d}ms"
            return f"mouse/{op}/{d}ms"
        if kind == "gamepad":
            op = p.get("op", "?")
            if op == "stick":
                return (f"gamepad/stick/{p.get('side', '?')[0].upper()}/"
                        f"{p.get('x', 0):.1f},{p.get('y', 0):.1f}/{d}ms")
            if op == "button":
                return f"gamepad/btn/{p.get('button', '?')}/{d}ms"
            return f"gamepad/{op}/{d}ms"
        if kind == "wait":
            return f"wait/{d}ms"
        return f"{kind}/{d}ms"

    @staticmethod
    def _has_movement(actions: list["Action"]) -> bool:
        """Returns True if `actions` contains at least one input that visually
        moves the character or camera. wait / pure menu-navigation keys (ESC,
        ENTER, M) do NOT count — they are why the bot ends up standing still
        despite VLM "decisions"."""
        movement_keys = {"W", "A", "S", "D"}
        for a in actions:
            if a.kind == "key":
                vk = (a.payload or {}).get("vk", "").upper()
                if vk in movement_keys:
                    return True
            elif a.kind == "mouse":
                op = (a.payload or {}).get("op")
                if op in ("move", "click"):  # click = attack, also game-side input
                    return True
            elif a.kind == "gamepad":
                op = (a.payload or {}).get("op")
                if op in ("stick", "button"):
                    return True
        return False

    def _driver_loop(self) -> None:
        period = max(0.05, self._driver.decision_period_s)
        consecutive_errors = 0
        # Keep-alive heartbeat used when VLM tick returns no movement —
        # prevents the "VLM thinking for 4s, bot standing for 4s" gap from
        # turning into long idle stretches in the dataset.
        from tools.auto_play.driver import Action as _Action
        forward_key = (
            self._profile.controls.get("move_forward")
            or self._profile.controls.get("move_forward_key")
            or "W"
        )
        heartbeat_action = _Action(
            kind="key",
            payload={"vk": forward_key, "event": "press"},
            duration_ms=1500,
        )
        while not self._stop_evt.is_set():
            # While watchdog is running profile.recovery, yield: another tick
            # of VLM-driven W/turn would step on the recovery's back-step +
            # 4-turn sequence and the bot stays stuck. Cheap ~50ms poll.
            if self._recovery_active_evt.is_set():
                self._stop_evt.wait(0.1)
                continue
            t0 = time.monotonic()
            try:
                obs = Observation(timestamp=t0, profile=self._profile, frame_bgr=None)
                actions = self._driver.next_actions(obs) or []
                consecutive_errors = 0
            except BudgetExhausted as e:
                # G-006: budget exhausted (or VLM client init failed) — swap
                # to KeepAliveDriver and continue. Capture must keep running.
                log.warning(
                    "[AUTO-PLAY] VLM 预算耗尽 (%s) — 降级到 KeepAliveDriver", e,
                )
                print(
                    f"[AUTO-PLAY] VLM 预算耗尽: {e} — 降级到 KeepAliveDriver",
                    flush=True,
                )
                try:
                    self._driver.on_stop()
                except Exception:
                    log.exception("[AUTO-PLAY] vlm driver.on_stop 异常")
                self._driver = KeepAliveDriver(self._profile)
                self._driver_name = "keep-alive"
                self._driver.on_start()
                period = max(0.05, self._driver.decision_period_s)
                continue
            except Exception:
                log.exception("[AUTO-PLAY] driver.next_actions 异常 — 续 5s 重试")
                consecutive_errors += 1
                # Back off if errors keep happening
                self._stop_evt.wait(min(5.0 * consecutive_errors, 30.0))
                continue

            # Heartbeat: if VLM returned no movement-bearing action this tick
            # (empty list, all wait, or only menu keys like ESC/M), inject a
            # default forward key so the bot doesn't stand still during the
            # 3-4s VLM-response window. The real VLM actions, when present,
            # already cover movement — heartbeat is appended only as fallback.
            if self._driver_name == "vlm" and not self._has_movement(actions):
                actions = list(actions) + [heartbeat_action]
                log.info(
                    "[AUTO-PLAY] tick: VLM 未输出 movement → 注入 keep-alive heartbeat (W 1500ms)"
                )

            if actions:
                summary = " ".join(self._action_summary(a) for a in actions)
                log.info(
                    "[AUTO-PLAY] tick: %s → %d action(s) [%s]",
                    self._driver_name, len(actions), summary,
                )

            for action in actions:
                if self._stop_evt.is_set():
                    return
                try:
                    self._backend.inject(action)
                except ValueError as e:
                    log.warning("[AUTO-PLAY] inject 拒绝: %s", e)
                except Exception:
                    log.exception("[AUTO-PLAY] inject 异常")

            elapsed = time.monotonic() - t0
            sleep_s = max(0.0, period - elapsed)
            if sleep_s > 0:
                self._stop_evt.wait(sleep_s)
