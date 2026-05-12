"""LaunchTab —— launch 子命令。

dashboard + F8/F9 镜像按钮 + redo survey + 启动前预检。
"""

from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QHBoxLayout, QMessageBox, QPushButton, QVBoxLayout, QWidget,
)

from unicap_gui.shared import sendinput
from unicap_gui.shared import settings as gui_settings
from unicap_gui.shared.cli_schema import LAUNCH
from unicap_gui.tabs.base_tab import BaseTab
from unicap_gui.widgets.dashboard import LaunchDashboard


# 默认 dataset-root —— main.py 同源（tools/capture/config.py）
_DEFAULT_DATASET_ROOT = Path(r"D:\unicap_output")


class LaunchTab(BaseTab):
    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(LAUNCH, parent)

        # auto_play 首次运行 default=True（INI 没保存过 auto_play key 的场景）。
        # 已保存的值由 BaseTab._restore_settings 还原，这里不覆盖。
        saved = gui_settings.load_flag_values("launch")
        if "auto_play" not in saved:
            self._form.set_values({"auto_play": True})
            self._refresh_preview()

    def _wire_extra(self) -> None:
        # ── dashboard 顶部 ────────────────────────────────────────────────
        self._dashboard = LaunchDashboard(self)
        self._top_box.addWidget(self._dashboard)

        # ── 操作按钮（F8/F9 镜像 + redo survey）─────────────────────────────
        btn_f8 = QPushButton("▶ F8 开始")
        btn_f8.clicked.connect(self._on_press_f8)
        btn_f8.setMinimumWidth(110)
        btn_f9 = QPushButton("■ F9 停止")
        btn_f9.clicked.connect(self._on_press_f9)
        btn_f9.setMinimumWidth(110)
        btn_survey = QPushButton("⟳ 重做 survey")
        btn_survey.clicked.connect(self._on_redo_survey)
        btn_survey.setToolTip("删除该游戏的 recommended_skip.txt；下次 F8 会重跑 survey")

        actions = QHBoxLayout()
        actions.setContentsMargins(8, 0, 8, 0)
        actions.addWidget(btn_f8)
        actions.addWidget(btn_f9)
        actions.addStretch(1)
        actions.addWidget(btn_survey)
        actions_w = QWidget()
        actions_w.setLayout(actions)
        self._top_box.addWidget(actions_w)

        self._btn_f8 = btn_f8
        self._btn_f9 = btn_f9
        self._btn_redo_survey = btn_survey

        # 子进程 lifecycle 钩到 dashboard
        self._runner.started.connect(self._on_run_started)
        self._runner.session_changed.connect(self._dashboard.set_session_dir)
        self._runner.stopped.connect(self._on_run_stopped)
        # 解析 `[DEMO] F6 → GOOD` 类行喂 dashboard 的 DEMO 标签
        self._runner.line_received.connect(self._on_log_line_for_demo)

    # ── slots ─────────────────────────────────────────────────────────────

    def _on_run_started(self, _cmd: list[str]) -> None:
        v = self._form.values()
        game_path_str = (v.get("game_path") or "").strip()
        # 推入历史（仅在非空 + 文件实际存在时）—— 这样 dropdown 下次能选到
        if game_path_str and Path(game_path_str).exists():
            self._form.push_game_path_history(game_path_str)
        game_path = Path(game_path_str) if game_path_str else Path()
        game_dir = game_path.parent if game_path_str else None
        try:
            duration = float(v.get("capture_duration") or 60.0)
        except (TypeError, ValueError):
            duration = 60.0
        self._dashboard.attach_to_launch(game_dir, duration)
        self._btn_redo_survey.setEnabled(False)

    def _on_run_stopped(self, _rc: int) -> None:
        self._dashboard.detach()
        self._btn_redo_survey.setEnabled(True)

    def _on_log_line_for_demo(self, line: str) -> None:
        # main.py prints: `[DEMO] F6 → GOOD` / `[DEMO] F6 → UNMARKED`
        #                 `[DEMO] F7 → BAD`  / `[DEMO] F7 → UNMARKED`
        if "[DEMO]" not in line:
            return
        upper = line.upper()
        if "→ GOOD" in upper or "-> GOOD" in upper:
            self._dashboard.set_demo_quality("good")
        elif "→ BAD" in upper or "-> BAD" in upper:
            self._dashboard.set_demo_quality("bad")
        elif "UNMARKED" in upper:
            self._dashboard.set_demo_quality("unmarked")

    def _on_press_f8(self) -> None:
        ok = sendinput.press_f8()
        msg = "已发送 F8" if ok else "F8 SendInput 失败（仅 Windows 支持）"
        self._log.append_line(f"[unicap-gui] {msg}")

    def _on_press_f9(self) -> None:
        ok = sendinput.press_f9()
        msg = "已发送 F9" if ok else "F9 SendInput 失败（仅 Windows 支持）"
        self._log.append_line(f"[unicap-gui] {msg}")

    def _on_redo_survey(self) -> None:
        v = self._form.values()
        game_name, dataset_root = self._resolve_game_name_and_root(v)
        if not game_name:
            QMessageBox.warning(self, "重做 survey",
                                "无法推断 game_name —— 先填 --game-path")
            return
        survey_path = dataset_root / game_name / "survey" / "recommended_skip.txt"
        if not survey_path.exists():
            QMessageBox.information(
                self, "重做 survey",
                f"该游戏还没有 survey 数据，下次 F8 自动会跑：\n{survey_path}",
            )
            return

        ret = QMessageBox.question(
            self, "确认重做 survey",
            f"将删除：\n{survey_path}\n\n下次按 F8 会重新跑 survey（约 30s-2 分钟）。继续？",
            QMessageBox.Yes | QMessageBox.No, QMessageBox.No,
        )
        if ret != QMessageBox.Yes:
            return
        try:
            survey_path.unlink()
        except OSError as e:
            QMessageBox.critical(self, "删除失败", str(e))
            return
        self._log.append_line(f"[unicap-gui] survey 已重置：{survey_path}")

    # ── 启动前预检 ──────────────────────────────────────────────────────

    def _precheck_before_start(self) -> tuple[bool, str]:
        v = self._form.values()
        problems: list[str] = []

        game_path = (v.get("game_path") or "").strip()
        if not game_path:
            problems.append("--game-path 为空。")
        elif not Path(game_path).exists():
            problems.append(f"--game-path 文件不存在：\n  {game_path}")

        # dataset-root 父目录可写性（空 = 用 CLI 默认）
        ds_root = (v.get("dataset_root") or "").strip()
        if ds_root:
            parent = Path(ds_root).parent
            if not parent.exists():
                problems.append(
                    f"--dataset-root 父目录不存在：\n  {parent}（注意目录会自动建，但父目录必须先在）"
                )

        # profile 名校验：选了非空 profile → 文件得存在
        prof = (v.get("profile") or "").strip()
        if prof:
            from unicap_gui.shared.paths import profiles_dir
            yaml = profiles_dir() / f"{prof}.yaml"
            if not yaml.exists():
                problems.append(
                    f"profile 不存在：profiles/{prof}.yaml\n"
                    f"（改成已存在的 profile 名，或留空让程序按 exe 名 fuzzy match）"
                )

        if problems:
            return False, "\n\n".join(problems)
        return True, ""

    # ── helper ────────────────────────────────────────────────────────────

    def _resolve_game_name_and_root(self, v: dict) -> tuple[str, Path]:
        gp = v.get("game_path") or ""
        gn = Path(gp).stem if gp else ""
        ds = (v.get("dataset_root") or "").strip()
        return gn, Path(ds) if ds else _DEFAULT_DATASET_ROOT
