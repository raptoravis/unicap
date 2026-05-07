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
from tools.auto_play.takeover import TakeoverDetector
from tools.auto_play.watchdog import StaticFrameWatchdog

if TYPE_CHECKING:
    pass


log = logging.getLogger("unicap.auto_play")


def create_driver(profile: GameProfile, *, seed: int | None = None) -> BotDriver:
    """Factory: only keep-alive driver is supported."""
    return KeepAliveDriver(profile, seed=seed)


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
        profile: GameProfile,
        frames_dir: Path,
        debug: bool = False,
        log_path: Path | None = None,
    ) -> None:
        self._profile = profile
        self._frames_dir = frames_dir
        self._debug = debug

        if log_path is None:
            import tempfile
            log_path = Path(tempfile.gettempdir()) / "unicap" / "auto_play.log"
        _setup_log_handler(log_path)
        if debug:
            logging.getLogger("unicap.auto_play").setLevel(logging.DEBUG)

        self._backend = InputBackend(profile, debug=debug)
        self._driver: BotDriver = create_driver(profile)
        # Human-takeover detector: 3s 内有主动按键则暂停所有 inject 路径。
        # 鼠标移动不算（避免 bot 自己的 mouse turn 误判为接管）。
        self._takeover = TakeoverDetector(self._backend, profile)
        # Shared "recovery in progress" event — watchdog sets while running
        # profile.recovery; main driver loop skips its own injects while set.
        # Without this, watchdog's S+turn back-step gets immediately overwritten
        # by main loop's W+turn (same ~7s window), so the recovery sequence
        # physically cancels itself.
        self._recovery_active_evt = threading.Event()
        self._watchdog = StaticFrameWatchdog(
            frames_dir=frames_dir, profile=profile, input_backend=self._backend,
            log_path=log_path,
            recovery_active_evt=self._recovery_active_evt,
            takeover_detector=self._takeover,
        )

        self._stop_evt = threading.Event()
        self._driver_thread: threading.Thread | None = None
        self._stopped = False

        # Attack-diversity heartbeat: ensures dataset always has attack-action
        # samples even if the keep-alive sequence never picks attack during a
        # given window. Mapped from profile.controls.attack so non-FF7R games
        # (gamepad, keys, different mouse buttons) work too.
        from tools.auto_play.driver import Action as _Action
        attack_ctrl = self._profile.controls.get("attack")
        self._attack_action: _Action | None = self._build_attack_action(
            attack_ctrl
        )
        self._attack_period_s = 12.0       # one attack frame every ~12s
        self._attack_thread: threading.Thread | None = None

    def start(self) -> None:
        if self._driver_thread is not None and self._driver_thread.is_alive():
            return
        log.info(
            "[AUTO-PLAY] 启动 driver=keep-alive profile=%s gamepad=%s",
            self._profile.name,
            "vigem_ok" if self._backend.gamepad_available else "unavailable",
        )
        print(f"[AUTO-PLAY] driver=keep-alive profile={self._profile.name}"
              f" gamepad={'vigem_ok' if self._backend.gamepad_available else 'unavailable'}",
              flush=True)

        self._stop_evt.clear()
        self._driver.on_start()
        self._takeover.start()
        self._watchdog.start()
        self._driver_thread = threading.Thread(
            target=self._driver_loop, name="auto-play-driver", daemon=True,
        )
        self._driver_thread.start()
        # Attack-diversity heartbeat — ensures the dataset always has
        # attack-action samples even when keep-alive sequence skips attacks.
        if self._attack_action is not None:
            self._attack_thread = threading.Thread(
                target=self._attack_heartbeat_loop, name="auto-play-attack-hb",
                daemon=True,
            )
            self._attack_thread.start()
            log.info(
                "[ATTACK-HB] 启动 period=%.1fs action=%s",
                self._attack_period_s,
                f"{self._attack_action.kind}/{self._attack_action.payload}",
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
        try:
            self._takeover.stop(timeout_s=timeout_s)
        except Exception as e:
            log.warning("[AUTO-PLAY] takeover stop 异常: %s", e)
        if self._attack_thread is not None:
            self._attack_thread.join(timeout=timeout_s)
            if self._attack_thread.is_alive():
                log.warning("[ATTACK-HB] thread join 超时 (%.1fs)", timeout_s)
            self._attack_thread = None
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
        log.info(
            "[AUTO-PLAY] stop 完成 watchdog 触发=%d takeover=%d",
            self._watchdog.trigger_count, self._takeover.detection_count,
        )
        print(
            f"[AUTO-PLAY] 停止；watchdog 触发 {self._watchdog.trigger_count} 次"
            f"，takeover {self._takeover.detection_count} 次",
            flush=True,
        )

    @property
    def is_running(self) -> bool:
        return (
            self._driver_thread is not None
            and self._driver_thread.is_alive()
            and not self._stop_evt.is_set()
        )

    @staticmethod
    def _build_attack_action(ctrl) -> "Action | None":
        """Translate profile.controls.attack ('mouse_left' / 'gamepad_X' /
        'SPACE' / etc.) into an attack heartbeat Action, mirroring the
        keep_alive `_press_control` resolver."""
        from tools.auto_play.driver import Action as _Action
        if ctrl is None:
            return None
        ctrl_str = str(ctrl)
        if ctrl_str.startswith("mouse_"):
            button = ctrl_str.split("_", 1)[1]
            return _Action(
                kind="mouse",
                payload={"op": "click", "button": button},
                duration_ms=150,
            )
        if ctrl_str.startswith("gamepad_"):
            button = ctrl_str.split("_", 1)[1]
            return _Action(
                kind="gamepad",
                payload={"op": "button", "button": button},
                duration_ms=150,
            )
        return _Action(
            kind="key",
            payload={"vk": ctrl_str, "event": "press"},
            duration_ms=150,
        )

    def _attack_heartbeat_loop(self) -> None:
        """Background attack-diversity heartbeat — ensures the dataset has
        attack-action samples even in long empty-exploration windows where
        keep-alive sequence happens to skip them. Injects profile.controls.attack
        every _attack_period_s.

        Yields to watchdog while it's running profile.recovery (recovery is
        pure movement and an attack mid-back-step would confuse the unstuck
        sequence)."""
        if self._attack_action is None:
            return
        attack_count = 0
        # Stagger first attack so it doesn't fire at session start (bot may
        # still be in loading screen / opening cinematic).
        self._stop_evt.wait(self._attack_period_s)
        while not self._stop_evt.is_set():
            if self._recovery_active_evt.is_set():
                self._stop_evt.wait(0.5)
                continue
            if self._takeover.is_taken_over():
                # 人在玩 → 不要打扰；3s 后 detector 自动 expire 重新进 inject
                self._stop_evt.wait(0.5)
                continue
            try:
                self._backend.inject(self._attack_action)
            except Exception as e:
                log.warning("[ATTACK-HB] inject 异常: %s", e)
                self._stop_evt.wait(self._attack_period_s)
                continue
            attack_count += 1
            if attack_count <= 3 or attack_count % 10 == 0:
                log.info(
                    "[ATTACK-HB] 注入 attack#%d (period=%.1fs)",
                    attack_count, self._attack_period_s,
                )
            self._stop_evt.wait(self._attack_period_s)

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

    def _driver_loop(self) -> None:
        period = max(0.05, self._driver.decision_period_s)
        consecutive_errors = 0
        while not self._stop_evt.is_set():
            # While watchdog is running profile.recovery, yield: another tick
            # of W/turn would step on the recovery's back-step + 4-turn
            # sequence and the bot stays stuck. Cheap ~50ms poll.
            if self._recovery_active_evt.is_set():
                self._stop_evt.wait(0.1)
                continue
            # Human takeover: 3s 内有主动按键则跳过整 tick；polled 短的 poll
            # 让接管释放后 bot 能快速恢复（detector grace = 3s 自然 expire）。
            if self._takeover.is_taken_over():
                self._stop_evt.wait(0.2)
                continue
            t0 = time.monotonic()
            try:
                obs = Observation(timestamp=t0, profile=self._profile, frame_bgr=None)
                actions = self._driver.next_actions(obs) or []
                consecutive_errors = 0
            except Exception:
                log.exception("[AUTO-PLAY] driver.next_actions 异常 — 续 5s 重试")
                consecutive_errors += 1
                # Back off if errors keep happening
                self._stop_evt.wait(min(5.0 * consecutive_errors, 30.0))
                continue

            if actions:
                summary = " ".join(self._action_summary(a) for a in actions)
                log.info(
                    "[AUTO-PLAY] tick: keep-alive → %d action(s) [%s]",
                    len(actions), summary,
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
