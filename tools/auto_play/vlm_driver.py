"""VLMDriver — C-layer (vision-language model brain).

Subscribes to BackBuffer.png at ~1 Hz, calls a configured OpenAI-compatible
VLM endpoint with the current frame + profile.vlm.game_instructions, parses
a JSON action plan, and returns Actions for the InputBackend to inject.

# Configuration

Three environment variables (all required) point at any OpenAI-compatible
chat-completions endpoint that accepts `image_url` content blocks:

    VLM_API_KEY=sk-...
    VLM_BASE_URL=https://dashscope.aliyuncs.com/compatible-mode/v1
    VLM_MODEL=qwen-vl-plus

These can live in a `.env` file (loaded automatically on module import via
python-dotenv) or be set in the shell. CLI flags `--vlm-base-url` and
`--vlm-model` override the env values for a single run.

Worked examples (paste into `.env`):

    # 阿里云百炼 Qwen-VL（默认推荐，最便宜的国内 vision API）
    VLM_API_KEY=sk-...
    VLM_BASE_URL=https://dashscope.aliyuncs.com/compatible-mode/v1
    VLM_MODEL=qwen-vl-plus

    # Moonshot Kimi
    VLM_API_KEY=sk-...
    VLM_BASE_URL=https://api.moonshot.ai/v1
    VLM_MODEL=kimi-k2.6

    # OpenAI gpt-4o-mini
    VLM_API_KEY=sk-...
    VLM_BASE_URL=https://api.openai.com/v1
    VLM_MODEL=gpt-4o-mini

    # 本地 Ollama
    VLM_API_KEY=ollama
    VLM_BASE_URL=http://localhost:11434/v1
    VLM_MODEL=qwen2-vl

Cache hit count is read from `usage.prompt_tokens_details.cached_tokens` (the
OpenAI 2024 schema, supported by all the listed providers) and logged on
each call.

When the per-hour call budget is exhausted, or when VLM_API_KEY / openai SDK
is missing on first use, next_actions() raises BudgetExhausted; the runner
catches and swaps in KeepAliveDriver mid-flight (G-006: auto-fallback, do
not exit capture).
"""

from __future__ import annotations

import base64
import json
import logging
import os
import threading
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import cv2
import numpy as np

from tools.auto_play.driver import Action, BotDriver, Observation
from tools.auto_play.profile import GameProfile


log = logging.getLogger("unicap.auto_play")


# Load .env from CWD or ancestor directories on module import. python-dotenv
# is part of the auto-play-vlm extra; if it's missing we silently fall back to
# whatever the shell has already exported.
try:
    from dotenv import load_dotenv as _load_dotenv
    _load_dotenv()
except ImportError:
    pass


VLM_API_KEY_ENV = "VLM_API_KEY"
VLM_BASE_URL_ENV = "VLM_BASE_URL"
VLM_MODEL_ENV = "VLM_MODEL"


class BudgetExhausted(RuntimeError):
    """Raised by next_actions() when the per-hour cap is hit, or when
    VLM_API_KEY / the openai SDK is missing on first use.

    The runner uses this as the single signal to fall back to KeepAliveDriver.
    """


@dataclass(slots=True)
class _CallStats:
    timestamp: float = 0.0
    latency_s: float = 0.0
    input_tokens: int = 0  # uncached input tokens
    output_tokens: int = 0
    cache_read_tokens: int = 0  # tokens served from prefix cache
    schema_ok: bool = True


class _BudgetTracker:
    """Per-hour call cap. Thread-safe."""

    def __init__(self, max_calls_per_hour: int) -> None:
        self.max_calls_per_hour = max(1, int(max_calls_per_hour))
        self._lock = threading.Lock()
        self._calls: list[_CallStats] = []
        self._call_count = 0
        self._cache_read_total = 0
        self._billable_input_total = 0
        self._latency_sum = 0.0

    def check(self) -> None:
        with self._lock:
            now = time.time()
            window_calls = sum(
                1 for c in self._calls if now - c.timestamp <= 3600.0
            )
            if window_calls >= self.max_calls_per_hour:
                raise BudgetExhausted(
                    f"per-hour 上限耗尽 ({window_calls}/{self.max_calls_per_hour})"
                )

    def record(self, stats: _CallStats) -> None:
        with self._lock:
            self._calls.append(stats)
            cutoff = time.time() - 7200.0
            self._calls = [c for c in self._calls if c.timestamp > cutoff]
            self._call_count += 1
            self._cache_read_total += stats.cache_read_tokens
            self._billable_input_total += (
                stats.input_tokens + stats.cache_read_tokens
            )
            self._latency_sum += stats.latency_s
        log.info(
            "[VLM-COST] call#%d t=%.2fs in=%d out=%d cache_r=%d",
            self._call_count, stats.latency_s, stats.input_tokens,
            stats.output_tokens, stats.cache_read_tokens,
        )

    def snapshot(self) -> dict[str, Any]:
        with self._lock:
            cache_hit_ratio = (
                self._cache_read_total / self._billable_input_total
                if self._billable_input_total > 0 else 0.0
            )
            avg_latency = (
                self._latency_sum / self._call_count
                if self._call_count > 0 else 0.0
            )
            return {
                "call_count": self._call_count,
                "cache_hit_ratio": round(cache_hit_ratio, 4),
                "avg_latency_s": round(avg_latency, 4),
                "max_calls_per_hour": self.max_calls_per_hour,
            }


_SYSTEM_PROMPT_TEMPLATE = """You are an autonomous game-playing agent for unicap, a vision-driven dataset capture pipeline. Your job is to keep the game character moving and exploring so that the capture pipeline records varied gameplay frames for ML training. You are NOT trying to finish the game, beat bosses, or progress story arcs — you are generating (state, action) pairs for downstream learning.

# Your decision loop

You receive on each tick:
1. A subsampled screenshot of the current game frame (long edge ≤ 512 px).
2. The game-specific operation guide below ("GAME OPERATION GUIDE").

You output a JSON object matching the response schema. The shape is:

```
{
  "reasoning": "<one sentence>",   // optional, useful for log review
  "actions": [ <Action>, <Action>, ... ]
}
```

The runner injects each Action sequentially via OS-level input APIs (SendInput / virtual gamepad). Then it waits roughly 1 second and calls you again. You produce 1-6 Actions per tick.

# Action object schema

Each Action has three fields: `kind`, `payload`, `duration_ms`. Choose `kind` based on what input device the game uses (the operation guide tells you).

## kind = "key" — keyboard key

```
{"kind": "key", "payload": {"vk": "<KEY>", "event": "press"}, "duration_ms": 250}
```

`vk` is a virtual-key name. Common values: "W", "A", "S", "D", "SPACE", "ENTER", "ESC", "E", "F", "M", "TAB", "1".."9", "Q", "R". `event` is always `"press"` — the runner holds the key for `duration_ms` and releases.

## kind = "mouse" — mouse movement or button click

Move (turn camera in most 3D games):
```
{"kind": "mouse", "payload": {"op": "move", "dx": 200, "dy": 0}, "duration_ms": 0}
```
`dx`/`dy` are pixel offsets. Positive `dx` turns right; negative turns left. Typical magnitude 100-500 px. Vertical (`dy`) usually unnecessary — keep it 0 unless looking up/down meaningfully.

Click a button (basic attack in many games):
```
{"kind": "mouse", "payload": {"op": "click", "button": "left"}, "duration_ms": 250}
```
`button` is `"left"` or `"right"`.

## kind = "gamepad" — virtual gamepad (only when the profile uses gamepad)

Press a button:
```
{"kind": "gamepad", "payload": {"op": "button", "button": "A"}, "duration_ms": 200}
```
Move a stick (left = movement, right = look):
```
{"kind": "gamepad", "payload": {"op": "stick", "side": "left", "x": 0.0, "y": 1.0}, "duration_ms": 1500}
```
`x`/`y` are -1.0 to 1.0; `y=1.0` is forward.

## kind = "wait" — pure pause, no input

```
{"kind": "wait", "payload": {}, "duration_ms": 500}
```

Use when you want to observe before acting (cutscene playing, animation finishing). Use sparingly — too many waits and the dataset stops growing.

# Hard rules (the runner WILL reject violations)

1. NEVER press F8 or F9. They are unicap's own hotkeys; the InputBackend rejects Actions targeting them and the bot is logged as misbehaving.
2. NEVER press game-quit / log-out / save-and-quit keys. The session must keep running for hours unattended.
3. NEVER pick a "no" / "quit" / "permanent" story option. If a binary "yes/no" prompt blocks progress, prefer Enter / continue / skip — produce frames, do not finish the game.
4. Output 1-6 actions per tick. More than that and the runner cannot keep up at 1 Hz.
5. Cap each `duration_ms` at 2000ms (hard limit 5000ms). Smaller is better — you re-decide every ~1s anyway.
6. If the screen looks like a menu or pause screen, your first action should usually be ESC or Enter to dismiss it and return to gameplay.
7. If the screen is a cutscene (no HUD, cinematic letterbox bars), output `wait` for ~500ms — let the camera resolve before acting. After 2-3 waits, hit Enter to skip if still cinematic.
8. If you cannot tell what is on screen (loading screen, mostly black, transition), default to "move forward 1500ms then small random turn" — keeps frames flowing without committing to a direction.

# Output discipline

Return ONLY a JSON object matching the response schema. No prose before or after the JSON. No code fence. No "Here is the response:". The platform validates and rejects anything else.

# Payload reference

For `kind: "key"` — required `payload.vk` (string), required `payload.event` (must be `"press"`). Examples:

- {"kind":"key","payload":{"vk":"W","event":"press"},"duration_ms":1500}                  // walk forward 1.5s
- {"kind":"key","payload":{"vk":"SPACE","event":"press"},"duration_ms":100}               // jump (instant tap)
- {"kind":"key","payload":{"vk":"E","event":"press"},"duration_ms":150}                   // interact / open door
- {"kind":"key","payload":{"vk":"ENTER","event":"press"},"duration_ms":80}                // skip dialog
- {"kind":"key","payload":{"vk":"ESC","event":"press"},"duration_ms":80}                  // back out of menu
- {"kind":"key","payload":{"vk":"M","event":"press"},"duration_ms":80}                    // (FF7R) close map/menu
- {"kind":"key","payload":{"vk":"TAB","event":"press"},"duration_ms":80}                  // toggle inventory in many games
- {"kind":"key","payload":{"vk":"1","event":"press"},"duration_ms":100}                   // hotbar slot 1

For `kind: "mouse"` with `payload.op == "move"` — required `payload.dx`, `payload.dy` (integers; pixels). Set `duration_ms` to 0.

- |dx| < 100   = small adjustment, drift the camera a little
- |dx| ≈ 200-400 = normal turn (most useful magnitude — 1-2 of these is "look around")
- |dx| ≈ 600+  = large turn, ~90°

Examples:
- {"kind":"mouse","payload":{"op":"move","dx":300,"dy":0},"duration_ms":0}                 // look right
- {"kind":"mouse","payload":{"op":"move","dx":-300,"dy":0},"duration_ms":0}                // look left
- {"kind":"mouse","payload":{"op":"move","dx":150,"dy":0},"duration_ms":0}                 // small right adjust

For `kind: "mouse"` with `payload.op == "click"` — required `payload.button` (`"left"` or `"right"`):

- {"kind":"mouse","payload":{"op":"click","button":"left"},"duration_ms":150}              // basic attack
- {"kind":"mouse","payload":{"op":"click","button":"right"},"duration_ms":80}              // aim / block

For `kind: "gamepad"` (only when the profile uses gamepad — the operation guide will say so):

- {"kind":"gamepad","payload":{"op":"button","button":"A"},"duration_ms":200}              // jump on Xbox layout
- {"kind":"gamepad","payload":{"op":"button","button":"X"},"duration_ms":200}              // attack on Xbox layout
- {"kind":"gamepad","payload":{"op":"button","button":"START"},"duration_ms":80}           // pause / menu
- {"kind":"gamepad","payload":{"op":"stick","side":"left","x":0,"y":1.0},"duration_ms":1500}    // walk forward
- {"kind":"gamepad","payload":{"op":"stick","side":"left","x":-0.7,"y":0.7},"duration_ms":1000} // strafe forward-left
- {"kind":"gamepad","payload":{"op":"stick","side":"right","x":0.7,"y":0},"duration_ms":300}    // turn camera right
- {"kind":"gamepad","payload":{"op":"trigger","side":"right","value":1.0},"duration_ms":200}    // fire / accelerate

For `kind: "wait"` — payload is always `{}`; `duration_ms` is how long to pause.

# Screen-state recipes — what to do when you see X

## State: "Open exploration" (HUD visible, character standing in environment)

```
{"reasoning":"open exploration, walk forward and look around",
 "actions":[
   {"kind":"key","payload":{"vk":"W","event":"press"},"duration_ms":1800},
   {"kind":"mouse","payload":{"op":"move","dx":250,"dy":0},"duration_ms":0}
 ]}
```

## State: "Combat" (enemy on screen, low health bar, attack prompts)

```
{"reasoning":"enemy nearby, attack and back away",
 "actions":[
   {"kind":"mouse","payload":{"op":"click","button":"left"},"duration_ms":150},
   {"kind":"mouse","payload":{"op":"click","button":"left"},"duration_ms":150},
   {"kind":"key","payload":{"vk":"S","event":"press"},"duration_ms":600}
 ]}
```

## State: "Cutscene" (no HUD, letterbox bars, dialogue text)

```
{"reasoning":"cutscene playing, wait then skip",
 "actions":[
   {"kind":"wait","payload":{},"duration_ms":600},
   {"kind":"key","payload":{"vk":"ENTER","event":"press"},"duration_ms":80}
 ]}
```

## State: "Menu / pause / inventory / map"

```
{"reasoning":"map open, dismiss with M then resume",
 "actions":[
   {"kind":"key","payload":{"vk":"M","event":"press"},"duration_ms":80},
   {"kind":"key","payload":{"vk":"ESC","event":"press"},"duration_ms":80}
 ]}
```

## State: "Dialog choice" (text box with prompts)

```
{"reasoning":"dialog showing, advance with Enter",
 "actions":[
   {"kind":"key","payload":{"vk":"ENTER","event":"press"},"duration_ms":80}
 ]}
```

## State: "Death / Game Over / respawn screen"

```
{"reasoning":"death screen, press Enter to respawn",
 "actions":[
   {"kind":"key","payload":{"vk":"ENTER","event":"press"},"duration_ms":80},
   {"kind":"wait","payload":{},"duration_ms":800}
 ]}
```

## State: "Loading screen / black screen / transition"

```
{"reasoning":"loading, wait it out",
 "actions":[
   {"kind":"wait","payload":{},"duration_ms":1000}
 ]}
```

## State: "Stuck / wall / repeating same view"

```
{"reasoning":"appears stuck on wall, back away and turn",
 "actions":[
   {"kind":"key","payload":{"vk":"S","event":"press"},"duration_ms":1000},
   {"kind":"mouse","payload":{"op":"move","dx":700,"dy":0},"duration_ms":0},
   {"kind":"key","payload":{"vk":"W","event":"press"},"duration_ms":1500}
 ]}
```

## State: "Unknown / can't tell"

```
{"reasoning":"unclear scene, default exploration",
 "actions":[
   {"kind":"key","payload":{"vk":"W","event":"press"},"duration_ms":1500},
   {"kind":"mouse","payload":{"op":"move","dx":200,"dy":0},"duration_ms":0}
 ]}
```

# Reminder before you respond

- Output JSON ONLY. No prose. No code fence. No commentary.
- Every action has `kind` + `payload` + `duration_ms`. All three required.
- `duration_ms` is integer 0-5000.
- F8 / F9 are forbidden.
- Don't quit the game. Don't pick "give up". Frames are the goal.
- 1 to 6 actions per response.

# GAME OPERATION GUIDE

The following text comes from the per-game profile and describes this game's specific controls and conventions.

---
__GAME_INSTRUCTIONS__
---
"""


class VLMDriver(BotDriver):
    """OpenAI-compatible vision-language model driver. Configuration comes
    from VLM_API_KEY / VLM_BASE_URL / VLM_MODEL env vars (loadable via .env);
    constructor kwargs `base_url=` / `model=` override the env values for one
    run.

    Construction is cheap and does NOT validate VLM_API_KEY. The first call
    to next_actions() lazily constructs the SDK client; if VLM_API_KEY or the
    openai package is missing it raises BudgetExhausted, which the runner
    treats as a fallback signal (capture continues with KeepAliveDriver).
    """

    def __init__(
        self,
        profile: GameProfile,
        *,
        api_key: str | None = None,
        base_url: str | None = None,
        model: str | None = None,
        budget_per_hour: int = 60,
        frames_dir: Path | None = None,
        decision_period_s: float | None = None,
    ) -> None:
        # Resolve config: kwargs override env (which may have been loaded
        # from .env at module import). Construction stores values as-is and
        # defers VLM_API_KEY check until first call.
        self._api_key_override = (api_key or "").strip() or None
        self._base_url = (
            base_url or os.environ.get(VLM_BASE_URL_ENV) or ""
        ).strip() or None
        self._model = (
            model or os.environ.get(VLM_MODEL_ENV) or ""
        ).strip()

        self._profile = profile
        self._frames_dir = frames_dir
        self._budget = _BudgetTracker(budget_per_hour)
        self._client: Any = None
        self._client_lock = threading.Lock()

        vlm_cfg = profile.vlm or {}
        self._frame_long_edge = int(vlm_cfg.get("frame_subsample_long_edge", 512))
        cfg_period = vlm_cfg.get("decision_period_s")
        if cfg_period is not None:
            self._period_s = float(cfg_period)
        elif decision_period_s is not None:
            self._period_s = float(decision_period_s)
        else:
            self._period_s = 1.0

        self._game_instructions = str(
            vlm_cfg.get("game_instructions", "") or ""
        ).strip()
        if not self._game_instructions:
            log.warning(
                "[VLM] profile=%s vlm.game_instructions 为空 — 模型缺少游戏特定上下文",
                profile.name,
            )

        # Plain string replacement — the template has literal JSON examples
        # with `{` and `}`, so str.format() chokes.
        self._system_prompt = _SYSTEM_PROMPT_TEMPLATE.replace(
            "__GAME_INSTRUCTIONS__",
            self._game_instructions or "(no game-specific guide provided)",
        )

    @property
    def decision_period_s(self) -> float:
        return self._period_s

    @property
    def base_url(self) -> str | None:
        return self._base_url

    @property
    def model_name(self) -> str:
        return self._model

    def get_cost_log(self) -> dict[str, Any]:
        snap = self._budget.snapshot()
        snap["base_url"] = self._base_url or "(SDK default)"
        snap["model"] = self._model
        return snap

    def on_start(self) -> None:
        log.info(
            "[VLM] driver 启动 base_url=%s model=%s profile=%s period=%.1fs "
            "long_edge=%d budget=%d/h",
            self._base_url or "(SDK default)", self._model or "(unset)",
            self._profile.name, self._period_s, self._frame_long_edge,
            self._budget.max_calls_per_hour,
        )

    def on_stop(self) -> None:
        log.info("[VLM] driver 停止 cost_summary=%s", self.get_cost_log())

    def _ensure_client(self) -> Any:
        if self._client is not None:
            return self._client
        with self._client_lock:
            if self._client is not None:
                return self._client
            api_key = self._api_key_override or os.environ.get(VLM_API_KEY_ENV)
            if not api_key:
                raise BudgetExhausted(
                    f"{VLM_API_KEY_ENV} 环境变量未设置 — VLMDriver 不能调用 "
                    f"(检查 .env 或 shell；或一次性 --vlm-api-key)"
                )
            if not self._model:
                raise BudgetExhausted(
                    f"{VLM_MODEL_ENV} 未设置 — VLMDriver 不知道叫哪个模型 "
                    f"(检查 .env 或 --vlm-model)"
                )
            try:
                import openai
            except ImportError as e:
                raise BudgetExhausted(
                    "openai SDK 未安装 — pip install \"unicap[auto-play-vlm]\" 后重试"
                ) from e
            self._client = openai.OpenAI(
                api_key=api_key,
                base_url=self._base_url,
                timeout=30.0,
            )
            log.info(
                "[VLM] openai SDK client 初始化 base_url=%s model=%s",
                self._base_url or "(SDK default)", self._model,
            )
        return self._client

    def next_actions(self, observation: Observation) -> list[Action]:
        self._budget.check()

        frame = self._read_latest_frame()
        if frame is None:
            log.debug("[VLM] frames_dir 无可读 BMP — skip tick")
            return []

        client = self._ensure_client()  # may raise BudgetExhausted
        subsampled = self._subsample(frame)
        ok, buf = cv2.imencode(
            ".jpg", subsampled, [int(cv2.IMWRITE_JPEG_QUALITY), 85],
        )
        if not ok:
            log.warning("[VLM] cv2.imencode 失败 — skip tick")
            return []
        b64_data = base64.standard_b64encode(buf.tobytes()).decode("ascii")

        stats = _CallStats(timestamp=time.time())
        t0 = time.monotonic()
        try:
            response = client.chat.completions.create(
                model=self._model,
                max_tokens=1024,
                response_format={"type": "json_object"},
                messages=[
                    {"role": "system", "content": self._system_prompt},
                    {
                        "role": "user",
                        "content": [
                            {
                                "type": "image_url",
                                "image_url": {
                                    "url": f"data:image/jpeg;base64,{b64_data}",
                                },
                            },
                            {
                                "type": "text",
                                "text": (
                                    "Current frame. Decide what to do next "
                                    "per the system prompt. Output JSON only."
                                ),
                            },
                        ],
                    },
                ],
            )
        except Exception as e:
            stats.latency_s = time.monotonic() - t0
            stats.schema_ok = False
            self._budget.record(stats)
            log.warning("[VLM] API 调用异常: %s — skip tick", e)
            return []

        stats.latency_s = time.monotonic() - t0

        # OpenAI 2024 usage schema (Qwen DashScope, Moonshot Kimi, OpenAI all
        # follow this shape).
        usage = getattr(response, "usage", None)
        if usage is not None:
            prompt_tokens = getattr(usage, "prompt_tokens", 0) or 0
            completion_tokens = getattr(usage, "completion_tokens", 0) or 0
            details = getattr(usage, "prompt_tokens_details", None)
            cached = 0
            if details is not None:
                cached = getattr(details, "cached_tokens", 0) or 0
            stats.cache_read_tokens = cached
            stats.input_tokens = max(0, prompt_tokens - cached)
            stats.output_tokens = completion_tokens

        try:
            text = response.choices[0].message.content
        except (AttributeError, IndexError):
            text = None
        actions = self._parse_text_to_actions(text, stats)
        self._budget.record(stats)
        return actions

    def _parse_text_to_actions(
        self, text: Any, stats: _CallStats,
    ) -> list[Action]:
        if not text:
            stats.schema_ok = False
            log.warning("[VLM] response 无 text 内容 — drop")
            return []
        if not isinstance(text, str):
            text = str(text)

        try:
            data = json.loads(text)
        except json.JSONDecodeError as e:
            stats.schema_ok = False
            log.warning(
                "[VLM] JSON 解析失败: %s text=%r — drop", e, text[:200],
            )
            return []
        actions_data = data.get("actions") or []
        reasoning = data.get("reasoning") or ""
        if reasoning:
            log.info("[VLM] reasoning: %s", reasoning[:160])

        actions: list[Action] = []
        for i, a in enumerate(actions_data):
            try:
                kind = a["kind"]
                payload = a["payload"]
                dur = int(a["duration_ms"])
            except (KeyError, TypeError, ValueError) as e:
                log.warning(
                    "[VLM] action[%d]=%r 字段缺失/类型错: %s — drop this action",
                    i, a, e,
                )
                continue
            if kind not in ("key", "mouse", "gamepad", "wait"):
                log.warning("[VLM] action[%d] kind=%r 非法 — drop", i, kind)
                continue
            if not isinstance(payload, dict):
                log.warning(
                    "[VLM] action[%d] payload 非 dict (%s) — drop",
                    i, type(payload).__name__,
                )
                continue
            actions.append(Action(kind=kind, payload=payload, duration_ms=dur))
        if not actions and actions_data:
            stats.schema_ok = False
        return actions

    # BMPs younger than this are likely still being written by the addon.
    _BMP_MIN_AGE_S = 0.5

    def _read_latest_frame(self) -> np.ndarray | None:
        """Read latest BackBuffer.png from frames_dir.

        Mirrors watchdog's read pattern: prefer BackBufferUI.png when present
        (--ui-mode={ui,both} writes both, the post-UI variant has HUD/menus
        which gives the model more context), fall back to BackBuffer.png.
        """
        if self._frames_dir is None or not self._frames_dir.is_dir():
            return None
        now = time.time()
        latest_ui_mtime = -1.0
        latest_ui_path: Path | None = None
        latest_bb_mtime = -1.0
        latest_bb_path: Path | None = None
        for p in self._frames_dir.iterdir():
            if not p.name.endswith(".png"):
                continue
            try:
                m = p.stat().st_mtime
            except OSError:
                continue
            if now - m < self._BMP_MIN_AGE_S:
                continue
            if "BackBufferUI" in p.name:
                if m > latest_ui_mtime:
                    latest_ui_mtime, latest_ui_path = m, p
            else:
                if m > latest_bb_mtime:
                    latest_bb_mtime, latest_bb_path = m, p
        latest = latest_ui_path or latest_bb_path
        if latest is None:
            return None
        # np.fromfile + cv2.imdecode (instead of cv2.imread) so partial/locked
        # BMPs return None silently — imread's path-based variant prints
        # "can't open/read file" WARN to stderr that floods the console.
        try:
            data = np.fromfile(str(latest), dtype=np.uint8)
        except OSError:
            return None
        if data.size < 100:
            return None
        return cv2.imdecode(data, cv2.IMREAD_COLOR)

    def _subsample(self, frame: np.ndarray) -> np.ndarray:
        h, w = frame.shape[:2]
        long_edge = max(h, w)
        if long_edge <= self._frame_long_edge:
            return frame
        scale = self._frame_long_edge / long_edge
        new_w = max(1, int(w * scale))
        new_h = max(1, int(h * scale))
        return cv2.resize(frame, (new_w, new_h), interpolation=cv2.INTER_AREA)
