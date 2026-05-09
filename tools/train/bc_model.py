"""Frozen ResNet18 backbone + LSTM head + 4 output heads (kb / mouse_dx /
mouse_dy / mouse_btn).

Design notes:
  - Backbone is frozen at construction time (no_grad on all params); only the
    neck + LSTM + heads have trainable weights. With a 10-minute (~18k frame)
    demo budget this is the only way to avoid massive overfit.
  - Window inference: input is (B, T, 3, H, W). We run the backbone once over
    (B*T, 3, H, W), reshape back to (B, T, 512), feed an LSTM and read the
    last timestep.
  - ONNX export targets a static (1, T, 3, H, W) input — runtime BCDriver
    feeds one batch at a time.
"""

from __future__ import annotations

from dataclasses import dataclass

import torch
import torch.nn as nn
import torchvision.models as tvm

from tools.train.bc_common import MOUSE_DIR_BINS_PER_AXIS


@dataclass(slots=True)
class BCModelConfig:
    num_kb: int
    num_mouse_btn: int
    feat_dim: int = 512        # ResNet18 output
    neck_dim: int = 128
    lstm_hidden: int = 128
    backbone: str = "resnet18"


def _build_backbone(name: str) -> tuple[nn.Module, int]:
    """Returns (feature_extractor, output_dim). Output is global-pooled CHW=1×1."""
    name = name.lower()
    if name == "resnet18":
        net = tvm.resnet18(weights=tvm.ResNet18_Weights.IMAGENET1K_V1)
        # strip final fc; keep avgpool. forward returns (B, 512, 1, 1) → flatten.
        net.fc = nn.Identity()
        return net, 512
    if name == "mobilenetv3_small":
        net = tvm.mobilenet_v3_small(
            weights=tvm.MobileNet_V3_Small_Weights.IMAGENET1K_V1
        )
        net.classifier = nn.Identity()
        return net, 576
    raise ValueError(f"unsupported backbone: {name}")


class BCModel(nn.Module):
    def __init__(self, cfg: BCModelConfig) -> None:
        super().__init__()
        self.cfg = cfg

        backbone, feat_dim = _build_backbone(cfg.backbone)
        for p in backbone.parameters():
            p.requires_grad_(False)
        self.backbone = backbone
        self.feat_dim = feat_dim

        self.neck = nn.Sequential(
            nn.Linear(feat_dim, cfg.neck_dim),
            nn.ReLU(inplace=True),
            nn.LayerNorm(cfg.neck_dim),
        )
        self.lstm = nn.LSTM(
            input_size=cfg.neck_dim, hidden_size=cfg.lstm_hidden,
            num_layers=1, batch_first=True,
        )
        self.head_kb = nn.Linear(cfg.lstm_hidden, cfg.num_kb)
        self.head_mouse_dx = nn.Linear(cfg.lstm_hidden, MOUSE_DIR_BINS_PER_AXIS)
        self.head_mouse_dy = nn.Linear(cfg.lstm_hidden, MOUSE_DIR_BINS_PER_AXIS)
        # head_mouse_btn is empty when profile uses no mouse buttons → guard.
        if cfg.num_mouse_btn > 0:
            self.head_mouse_btn = nn.Linear(cfg.lstm_hidden, cfg.num_mouse_btn)
        else:
            self.head_mouse_btn = None

    def forward(self, frames: torch.Tensor) -> dict[str, torch.Tensor]:
        """frames: (B, T, 3, H, W) float32 [0, 1]. Returns logits dict."""
        B, T, C, H, W = frames.shape
        x = frames.reshape(B * T, C, H, W)
        # Backbone is frozen — no grad through it.
        with torch.no_grad():
            feat = self.backbone(x)         # (B*T, feat_dim)
        feat = feat.reshape(B, T, self.feat_dim)
        z = self.neck(feat)                 # (B, T, neck_dim)
        seq, _ = self.lstm(z)               # (B, T, lstm_hidden)
        last = seq[:, -1, :]                # (B, lstm_hidden)
        out = {
            "kb": self.head_kb(last),
            "mouse_dx": self.head_mouse_dx(last),
            "mouse_dy": self.head_mouse_dy(last),
        }
        if self.head_mouse_btn is not None:
            out["mouse_btn"] = self.head_mouse_btn(last)
        return out

    def export_onnx(self, path, frame_window: int, input_h: int, input_w: int,
                    opset: int = 17) -> None:
        """Export ONNX with static shape (1, T, 3, H, W). Output names match
        forward() dict keys; BCDriver reads them by name."""
        self.eval()
        device = next(self.parameters()).device
        dummy = torch.zeros(1, frame_window, 3, input_h, input_w, device=device)
        out_names = ["kb", "mouse_dx", "mouse_dy"]
        if self.head_mouse_btn is not None:
            out_names.append("mouse_btn")

        # Wrap forward to produce a tuple in fixed order — torch.onnx.export
        # is happiest with positional outputs.
        class _Wrap(nn.Module):
            def __init__(self_inner, m: BCModel, names) -> None:  # noqa: N805
                super().__init__()
                self_inner.m = m
                self_inner.names = names

            def forward(self_inner, x):  # noqa: N805
                d = self_inner.m(x)
                return tuple(d[n] for n in self_inner.names)

        # Dynamic batch dim so eval_bc.py can run with B>1 throughput while the
        # runtime BCDriver still feeds B=1 per tick. Frame-window / resolution
        # remain static — they are part of the model contract surfaced via
        # meta.json.
        dyn_axes = {"frames": {0: "B"}}
        for n in out_names:
            dyn_axes[n] = {0: "B"}
        torch.onnx.export(
            _Wrap(self, out_names),
            (dummy,),
            str(path),
            input_names=["frames"],
            output_names=out_names,
            opset_version=opset,
            dynamic_axes=dyn_axes,
        )
