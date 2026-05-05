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
        vlm_budget_per_hour: int = 60,
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
        # bounded by watchdog trigger rate, not 1 Hz).
        vlm_for_watchdog: VLMDriver | None = None
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
        else:
            raise ValueError(
                f"未知 driver: {driver_name!r} (支持: keep-alive, vlm, hybrid)"
            )
        self._watchdog = StaticFrameWatchdog(
            frames_dir=frames_dir, profile=profile, input_backend=self._backend,
            log_path=log_path, vlm_driver=vlm_for_watchdog,
        )

        self._stop_evt = threading.Event()
        self._driver_thread: threading.Thread | None = None
        self._stopped = False

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

    def stop(self, timeout_s: float = 3.0) -> None:
        if self._stopped:
            return
        self._stopped = True
        self._stop_evt.set()
        try:
            self._watchdog.stop(timeout_s=timeout_s)
        except Exception as e:
            log.warning("[AUTO-PLAY] watchdog stop 异常: %s", e)
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

    def _driver_loop(self) -> None:
        period = max(0.05, self._driver.decision_period_s)
        consecutive_errors = 0
        while not self._stop_evt.is_set():
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
