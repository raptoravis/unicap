"""HybridDriver — BC 推理为主，周期性穿插 keep_alive 步骤做 diversification。

为什么需要 hybrid：单纯 BCDriver 在卡场景（按一个 vk 顶墙 / model 没见过的提示
画面）会一直输出相同动作；watchdog 只在帧真静下来才触发 recovery，但小动画 +
HUD pulse 常常让画面不算 static。穿插 keep_alive 步骤强行打破"模型死循环"，给 BC
一个新视角再决策。

策略：
  - 默认走 BCDriver.next_actions
  - 每 hybrid.diversify_period_s（默认 12s）穿插一个 keep_alive.sequence 步骤
  - BCDriver 抛异常时降级到 KeepAliveDriver（鲁棒性兜底）

watchdog static-frame recovery 仍然独立工作，与本 driver 不冲突。
"""

from __future__ import annotations

import logging
import time
from pathlib import Path

from tools.auto_play.driver import Action, BotDriver, Observation


log = logging.getLogger("unicap.auto_play.hybrid")


class HybridDriver(BotDriver):
    def __init__(self, profile, frames_dir: Path, seed: int | None = None) -> None:
        # Imports kept local — BCDriver pulls onnxruntime; we don't want to
        # force that load when nobody asks for hybrid driver.
        from tools.auto_play.bc_driver import BCDriver
        from tools.auto_play.keep_alive import KeepAliveDriver

        self._profile = profile
        self._bc = BCDriver(profile, frames_dir=frames_dir, seed=seed)
        self._fallback = KeepAliveDriver(profile, seed=seed)

        hy_cfg = dict(profile.hybrid or {})
        self._diversify_period_s = float(hy_cfg.get("diversify_period_s", 12.0))
        self._period_s = self._bc.decision_period_s
        self._last_diversify = time.monotonic()
        self._bc_errors = 0

        print(
            f"[AUTO-PLAY] HybridDriver: bc primary + keep_alive diversify "
            f"every {self._diversify_period_s:.1f}s",
            flush=True,
        )

    @property
    def decision_period_s(self) -> float:
        return self._period_s

    def on_start(self) -> None:
        self._bc.on_start()
        self._fallback.on_start()

    def on_stop(self) -> None:
        try:
            self._bc.on_stop()
        except Exception as e:
            log.warning("[HYBRID] bc.on_stop 异常: %s", e)
        try:
            self._fallback.on_stop()
        except Exception as e:
            log.warning("[HYBRID] fallback.on_stop 异常: %s", e)

    def next_actions(self, observation: Observation) -> list[Action]:
        now = time.monotonic()
        if now - self._last_diversify >= self._diversify_period_s:
            self._last_diversify = now
            try:
                actions = self._fallback.next_actions(observation) or []
            except Exception:
                log.exception("[HYBRID] keep_alive diversify 异常")
                return []
            log.info("[HYBRID] diversify tick → %d action(s)", len(actions))
            return actions

        try:
            actions = self._bc.next_actions(observation)
            self._bc_errors = 0
            return actions or []
        except Exception:
            self._bc_errors += 1
            log.exception("[HYBRID] BC tick 异常 #%d — 本 tick 降级 keep_alive",
                          self._bc_errors)
            try:
                return self._fallback.next_actions(observation) or []
            except Exception:
                log.exception("[HYBRID] keep_alive 降级再次异常")
                return []
