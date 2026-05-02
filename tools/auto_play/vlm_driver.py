"""VLMDriver — C-layer placeholder.

This file pins the contract so the next dev session can fill it in without
touching A-layer code. Construction raises NotImplementedError on purpose —
do NOT silently return empty Actions, the user should see a clear message
explaining which release will enable it.
"""

from __future__ import annotations

from tools.auto_play.driver import Action, BotDriver, Observation
from tools.auto_play.profile import GameProfile


_NOT_IMPLEMENTED_MSG = (
    "VLMDriver 是 C 层（智能大脑），本 release 仅含 A 层骨架。"
    "下个 dev session 启用：参考 docs/req/auto-play.md G-005/G-006。"
    "当前可用：--driver keep-alive"
)


class VLMDriver(BotDriver):
    """Placeholder. Raises NotImplementedError on construction.

    Future implementation will:
      - Subsample observation.frame_bgr (long edge ≤ 512)
      - Call configured VLM provider (Anthropic / Google) with a JSON-schema
        constrained prompt built from profile.vlm.game_instructions
      - Parse response.actions and return as list[Action]
      - Track cost via get_cost_log()

    See docs/req/auto-play.md G-005 / G-006 for the full contract.
    """

    def __init__(
        self,
        profile: GameProfile,
        provider: str = "anthropic",
        budget_per_hour: int = 60,
        budget_total_usd: float = 5.0,
    ) -> None:
        raise NotImplementedError(_NOT_IMPLEMENTED_MSG)

    def next_actions(self, observation: Observation) -> list[Action]:
        raise NotImplementedError(_NOT_IMPLEMENTED_MSG)

    def get_cost_log(self) -> dict:
        raise NotImplementedError(_NOT_IMPLEMENTED_MSG)
