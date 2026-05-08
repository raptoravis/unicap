"""TrainBCTab —— 训 behavior-cloning 模型的 GUI tab。

UI 与其它 tab 同骨架（FlagForm + CLIPreview + Start/Stop + Log）；额外加：
  - ModelList 顶上展示 models/<profile>/ 下已有的训练产物 + metrics 摘要
    （QFileSystemWatcher 自动 rescan，无需手动刷新）
  - QProgressBar 解析训练 log 的 epoch=N/Total → 推动进度
  - precheck：profile 必填（main.py argparse `required=True`，提前拦）
"""

from __future__ import annotations

import re

from PySide6.QtWidgets import QHBoxLayout, QLabel, QProgressBar, QWidget

from unicap_gui.shared import settings as gui_settings
from unicap_gui.shared.cli_schema import TRAIN_BC
from unicap_gui.shared.paths import models_dir
from unicap_gui.tabs.base_tab import BaseTab
from unicap_gui.widgets.model_list import ModelList


_RE_TRAIN_DONE = re.compile(r"\[BC-TRAIN\].*?完成")
# `[BC-TRAIN] epoch= 1/20 train_loss=...` —— 来自 bc_train.run() 的 _flog 行。
_RE_EPOCH = re.compile(r"\[BC-TRAIN\]\s+epoch=\s*(\d+)/(\d+)")
# `val_kb_f1=0.123 val_dx_top1=0.234 val_dy_top1=0.345`
_RE_VAL = re.compile(r"val_kb_f1=([\d.]+)\s+val_dx_top1=([\d.]+)\s+val_dy_top1=([\d.]+)")


class TrainBCTab(BaseTab):
    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(TRAIN_BC, parent)

    def _wire_extra(self) -> None:
        self._models = ModelList(self)
        self._top_box.addWidget(self._models)

        # Progress bar —— 训练时显示 epoch 进度 + 最近一次 val metrics。
        self._progress = QProgressBar(self)
        self._progress.setRange(0, 100)
        self._progress.setValue(0)
        self._progress.setTextVisible(True)
        self._progress.setFormat("空闲")
        self._progress_label = QLabel("", self)
        self._progress_label.setStyleSheet("color: #555; font-size: 12px;")
        prog_row = QHBoxLayout()
        prog_row.setContentsMargins(0, 0, 0, 0)
        prog_row.setSpacing(8)
        prog_row.addWidget(self._progress, stretch=2)
        prog_row.addWidget(self._progress_label, stretch=1)
        self._top_box.addLayout(prog_row)

        self._form.values_changed.connect(self._on_form_changed)
        self._on_form_changed()

        self._runner.line_received.connect(self._on_log_line)
        self._runner.started.connect(self._on_train_started)
        self._runner.stopped.connect(self._on_train_stopped)

    def _apply_smart_defaults(self) -> None:
        # GUI 默认勾选 --raw（schema 默认 False 是为了对齐 CLI argparse；
        # GUI 用户面对的 99% 场景是直读 raw 训练，所以这里覆写）。
        # _restore_settings 已 set saved values；判断 saved 是否含 raw —— 用 ini
        # 里的实际持久化键决定，避免覆盖用户上次手动取消的勾选。
        saved = gui_settings.load_flag_values(self._schema.name)
        if "raw" not in saved:
            self._form.set_values({"raw": True})
        # GUI 默认 --device cuda（schema 默认 cpu 是为了对齐 CLI argparse）。
        if "device" not in saved:
            self._form.set_values({"device": "cuda"})

        # 历史已存过 --dataset 不覆盖；空时从 launch tab 的 dataset-root +
        # game-path 推一个最新 session（h5 优先，否则 raw session 目录）。
        if self._form.values().get("dataset"):
            return
        derived = gui_settings.derive_train_dataset_from_launch()
        if derived:
            self._form.set_values({"dataset": derived})

    def _precheck_before_start(self) -> tuple[bool, str]:
        prof = (self._form.values().get("profile") or "").strip()
        if not prof:
            return False, "必须先选 profile（profiles/<name>.yaml）"
        return True, ""

    def _on_form_changed(self) -> None:
        v = self._form.values()
        prof = (v.get("profile") or "").strip()
        self._models.set_models_root(models_dir(), prof)

        # --raw 时 --dataset 应该指向 session 目录而不是 dataset.h5；动态切
        # 浏览按钮的目标类型，避免 file 选择器在 raw 模式下误导用户。
        raw = bool(v.get("raw", False))
        for f in TRAIN_BC.flags:
            if f.name == "--dataset":
                f.path_kind = "optional_dir" if raw else "optional_path"
                break

    def _on_train_started(self, _cmd) -> None:
        # 训练启动时显示"等待第一个 epoch"，直到 [BC-TRAIN] epoch= 行到来。
        epochs = int(self._form.values().get("epochs", 20) or 20)
        self._progress.setRange(0, max(1, epochs))
        self._progress.setValue(0)
        self._progress.setFormat(f"等待第 1/{epochs} epoch …")
        self._progress_label.setText("")

    def _on_train_stopped(self, rc: int) -> None:
        self._models.rescan()
        if rc == 0 and self._progress.value() < self._progress.maximum():
            # 训练成功但 epoch 没全跑完？把进度填满让用户视觉确认成功。
            self._progress.setValue(self._progress.maximum())
        if rc == 0:
            self._progress.setFormat("完成 ✓")
        else:
            self._progress.setFormat(f"退出 rc={rc}")

    def _on_log_line(self, line: str) -> None:
        m = _RE_EPOCH.search(line)
        if m:
            cur, total = int(m.group(1)), int(m.group(2))
            if self._progress.maximum() != total:
                self._progress.setRange(0, total)
            self._progress.setValue(cur)
            self._progress.setFormat(f"epoch {cur}/{total}")
            mv = _RE_VAL.search(line)
            if mv:
                self._progress_label.setText(
                    f"val: kb_f1={mv.group(1)} dx={mv.group(2)} dy={mv.group(3)}"
                )
            return
        if _RE_TRAIN_DONE.search(line):
            self._models.rescan()
