"""BCDriver — runtime BC inference, plugged into AutoPlayRunner via the same
BotDriver ABC as KeepAliveDriver.

Loads:
  - <model_path>           ONNX, exported by tools.train.bc_train
  - <model_dir>/meta.json  action space schema + frame_window/input_resolution

Each tick:
  1. Pop oldest, push latest BackBuffer.png into 8-frame rolling window
  2. Run onnxruntime inference → kb / mouse_dx / mouse_dy / mouse_btn logits
  3. Apply hysteresis (require N consecutive predictions for kb / mouse_btn)
  4. Translate to Action[] for AutoPlayRunner to inject

Resolution: frame_window/input_h/input_w come from meta.json so model and
driver stay in sync without being hardcoded here.
"""

from __future__ import annotations

import json
import logging
import threading
import time
from collections import deque
from pathlib import Path
from typing import Any

import cv2
import numpy as np

from tools.auto_play.driver import Action, BotDriver, Observation
from tools.auto_play.input_backend import VK_MAP


log = logging.getLogger("unicap.auto_play.bc")


def _load_meta(model_path: Path) -> dict:
    meta_path = model_path.parent / "meta.json"
    if not meta_path.is_file():
        raise FileNotFoundError(
            f"BCDriver: 缺 meta.json: {meta_path} —— train-bc 应当在模型旁产出此文件"
        )
    return json.loads(meta_path.read_text(encoding="utf-8"))


_VK_NAME = {v: k for k, v in VK_MAP.items()}  # reverse: 0x57 → "W"
_MOUSE_BTN_OUT = {
    "mouse_left": "left",
    "mouse_right": "right",
    "mouse_middle": "middle",
}


class BCDriver(BotDriver):
    """Inference driver. Reads BackBuffer.png from frames_dir and emits Actions."""

    def __init__(
        self,
        profile,
        frames_dir: Path,
        seed: int | None = None,
    ) -> None:
        bc_cfg = dict(profile.bc or {})
        model_path_str = bc_cfg.get("model_path")
        if not model_path_str:
            raise RuntimeError(
                f"BCDriver: profile {profile.name!r} 缺少 bc.model_path"
            )
        model_path = Path(model_path_str)
        if not model_path.is_absolute():
            # repo-root-relative resolution (matches tools.train output convention)
            model_path = (Path(__file__).resolve().parents[2] / model_path).resolve()
        if not model_path.is_file():
            raise FileNotFoundError(f"BCDriver: 模型文件不存在: {model_path}")

        self._profile = profile
        self._frames_dir = Path(frames_dir)
        self._meta = _load_meta(model_path)
        self._frame_window = int(self._meta["frame_window"])
        h, w = self._meta["input_resolution"]
        self._input_h, self._input_w = int(h), int(w)
        self._action_space = self._meta["action_space"]
        self._kb_keys: list[dict] = self._action_space["kb_keys"]
        self._mouse_btns: list[str] = self._action_space["mouse_btns"]

        self._min_confidence = float(bc_cfg.get("min_confidence", 0.5))
        self._hysteresis_n = int(bc_cfg.get("hysteresis_n", 2))
        self._period_s = float(bc_cfg.get("decision_period_s", 1.0 / 30.0))

        # ONNX session (CPU). Imports onnxruntime lazily so a missing install
        # raises only when BC is actually requested, not at module import time.
        import onnxruntime as ort
        sess_opts = ort.SessionOptions()
        sess_opts.intra_op_num_threads = max(1, (Path(model_path).parent and 2) or 2)
        sess_opts.log_severity_level = 3  # warn+
        providers = ["CPUExecutionProvider"]
        if bc_cfg.get("device") == "cuda":
            providers.insert(0, "CUDAExecutionProvider")
        elif bc_cfg.get("device") == "directml":
            providers.insert(0, "DmlExecutionProvider")
        self._sess = ort.InferenceSession(
            str(model_path), sess_options=sess_opts, providers=providers,
        )
        self._input_name = self._sess.get_inputs()[0].name
        self._output_names = [o.name for o in self._sess.get_outputs()]

        # Rolling frame buffer (deque of float32 (3, H, W) tensors).
        self._buffer: deque[np.ndarray] = deque(maxlen=self._frame_window)
        # Hysteresis state — running tallies of consecutive "above-thresh" predictions
        self._kb_streak = np.zeros(len(self._kb_keys), dtype=np.int32)
        self._kb_currently_down = np.zeros(len(self._kb_keys), dtype=bool)
        self._btn_streak = np.zeros(len(self._mouse_btns), dtype=np.int32)
        self._btn_currently_down = np.zeros(len(self._mouse_btns), dtype=bool)

        self._lock = threading.Lock()
        log.info(
            "[BC] 模型 %s | window=%d input=%dx%d kb=%d mouse_btns=%d",
            model_path.name, self._frame_window,
            self._input_h, self._input_w,
            len(self._kb_keys), len(self._mouse_btns),
        )
        print(
            f"[AUTO-PLAY] driver=bc model={model_path.name} "
            f"backbone={self._meta.get('backbone_id', '?')} "
            f"window={self._frame_window} kb={len(self._kb_keys)} "
            f"mouse_btns={len(self._mouse_btns)}",
            flush=True,
        )

    @property
    def decision_period_s(self) -> float:
        return self._period_s

    # ── frame source ─────────────────────────────────────────────────────────

    _MIN_AGE_S = 0.5

    def _read_latest_frame(self) -> np.ndarray | None:
        """Returns (3, H, W) float32 [0, 1] or None when no frame available."""
        if not self._frames_dir.is_dir():
            return None
        latest_mtime = -1.0
        latest_path: Path | None = None
        now = time.time()
        for p in self._frames_dir.iterdir():
            if not p.name.endswith(".png") or "BackBufferUI" in p.name:
                continue
            try:
                m = p.stat().st_mtime
            except OSError:
                continue
            if now - m < self._MIN_AGE_S:
                continue
            if m > latest_mtime:
                latest_mtime = m
                latest_path = p
        if latest_path is None:
            return None
        try:
            data = np.fromfile(str(latest_path), dtype=np.uint8)
        except OSError:
            return None
        if data.size < 100:
            return None
        img = cv2.imdecode(data, cv2.IMREAD_COLOR)   # BGR
        if img is None:
            return None
        img_rgb = cv2.cvtColor(img, cv2.COLOR_BGR2RGB)
        resized = cv2.resize(
            img_rgb, (self._input_w, self._input_h),
            interpolation=cv2.INTER_AREA,
        )
        # (H, W, 3) uint8 → (3, H, W) float32 [0, 1]
        return (resized.astype(np.float32) / 255.0).transpose(2, 0, 1)

    def _ensure_buffer(self) -> bool:
        """Pad buffer with zeros until full size; return True if at least one
        real frame is in there."""
        new_frame = self._read_latest_frame()
        if new_frame is None and not self._buffer:
            # Nothing to work with yet. Caller will skip this tick.
            return False
        if new_frame is not None:
            self._buffer.append(new_frame)
        # Pad missing slots with the oldest available frame.
        if len(self._buffer) < self._frame_window:
            pad = self._buffer[0]
            while len(self._buffer) < self._frame_window:
                self._buffer.appendleft(pad)
        return True

    # ── inference ────────────────────────────────────────────────────────────

    def _infer(self) -> dict[str, np.ndarray]:
        x = np.stack(list(self._buffer), axis=0)        # (T, 3, H, W)
        x = x[None, ...].astype(np.float32)              # (1, T, 3, H, W)
        outs = self._sess.run(self._output_names, {self._input_name: x})
        return dict(zip(self._output_names, outs))

    # ── action decoding ──────────────────────────────────────────────────────

    @staticmethod
    def _sigmoid(x: np.ndarray) -> np.ndarray:
        return 1.0 / (1.0 + np.exp(-x))

    @staticmethod
    def _bin_to_dx(bin_idx: int) -> int:
        """Inverse of bc_common.mouse_bin: return a representative pixel delta
        for the chosen 16-bin slot. Center bins (7/8) → 0."""
        # bins layout (mirror of bc_common):
        #   0..7  = neg, magnitudes 64+, 64, 32, 16, 8, 4, 2, 1
        #   8..15 = non-neg, magnitudes 0, 1, 2, 4, 8, 16, 32, 64+
        mag_lookup = (1, 2, 4, 8, 16, 32, 64, 128)  # representative pixels
        if bin_idx <= 7:
            mag = mag_lookup[7 - bin_idx]
            return -mag
        idx = bin_idx - 8
        if idx == 0:
            return 0
        return mag_lookup[idx - 1]

    def next_actions(self, observation: Observation) -> list[Action]:
        if not self._ensure_buffer():
            return []  # capture just started; nothing to infer on

        outputs = self._infer()
        kb_logit = outputs["kb"][0]                    # (K,)
        dx_logit = outputs["mouse_dx"][0]              # (16,)
        dy_logit = outputs["mouse_dy"][0]              # (16,)
        btn_logit = outputs.get("mouse_btn")
        btn_logit = btn_logit[0] if btn_logit is not None else None

        kb_p = self._sigmoid(kb_logit)
        dx_bin = int(dx_logit.argmax())
        dy_bin = int(dy_logit.argmax())

        actions: list[Action] = []

        # ── keyboard with hysteresis ─────────────────────────────────────────
        for i, slot in enumerate(self._kb_keys):
            vk = int(slot["vk"])
            vk_name = _VK_NAME.get(vk)
            if vk_name is None:
                continue
            wants_down = bool(kb_p[i] >= self._min_confidence)
            if wants_down:
                self._kb_streak[i] = min(self._kb_streak[i] + 1, 100)
            else:
                self._kb_streak[i] = max(self._kb_streak[i] - 1, -100)
            if wants_down and self._kb_streak[i] >= self._hysteresis_n and not self._kb_currently_down[i]:
                actions.append(Action(kind="key",
                                      payload={"vk": vk_name, "event": "down"},
                                      duration_ms=0))
                self._kb_currently_down[i] = True
            elif (not wants_down) and self._kb_streak[i] <= -self._hysteresis_n and self._kb_currently_down[i]:
                actions.append(Action(kind="key",
                                      payload={"vk": vk_name, "event": "up"},
                                      duration_ms=0))
                self._kb_currently_down[i] = False

        # ── mouse buttons with hysteresis ────────────────────────────────────
        if btn_logit is not None and len(self._mouse_btns) > 0:
            btn_p = self._sigmoid(btn_logit)
            for i, name in enumerate(self._mouse_btns):
                wants = bool(btn_p[i] >= self._min_confidence)
                if wants:
                    self._btn_streak[i] = min(self._btn_streak[i] + 1, 100)
                else:
                    self._btn_streak[i] = max(self._btn_streak[i] - 1, -100)
                button = _MOUSE_BTN_OUT[name]
                if wants and self._btn_streak[i] >= self._hysteresis_n and not self._btn_currently_down[i]:
                    actions.append(Action(kind="mouse",
                                          payload={"op": "click", "button": button},
                                          duration_ms=80))
                    self._btn_currently_down[i] = True
                elif (not wants) and self._btn_streak[i] <= -self._hysteresis_n:
                    self._btn_currently_down[i] = False

        # ── mouse direction (per-tick relative move) ─────────────────────────
        dx = self._bin_to_dx(dx_bin)
        dy = self._bin_to_dx(dy_bin)
        if dx or dy:
            actions.append(Action(kind="mouse",
                                  payload={"op": "move", "dx": int(dx), "dy": int(dy)},
                                  duration_ms=0))

        return actions

    def on_stop(self) -> None:
        # Release any keys we left held — runner won't otherwise.
        for i, slot in enumerate(self._kb_keys):
            if self._kb_currently_down[i]:
                vk_name = _VK_NAME.get(int(slot["vk"]))
                if vk_name:
                    log.debug("[BC] on_stop release %s", vk_name)
                self._kb_currently_down[i] = False
