"""FlagForm —— 把 cli_schema.SubcommandSchema 渲染成 QFormLayout 控件树。

- choice → QComboBox
- bool / store_true / bool_optional → QCheckBox
- int / float → QSpinBox / QDoubleSpinBox
- str → QLineEdit
- path → QLineEdit + 浏览按钮（按 path_kind 选 file/dir picker）

values() / set_values() 是与 schema 对齐的纯函数接口；CLIPreview 凭它拼命令。
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QCheckBox, QComboBox, QDoubleSpinBox, QFileDialog, QFrame, QGridLayout,
    QHBoxLayout, QLabel, QLineEdit, QPushButton, QScrollArea, QSizePolicy,
    QSpinBox, QVBoxLayout, QWidget,
)

from unicap_gui.shared import settings as gui_settings
from unicap_gui.shared.cli_schema import FlagSpec, SubcommandSchema

# 路径历史 QSettings key：FlagForm 加载时填充 combo，外部（LaunchTab）写入
GAME_PATH_HISTORY_KEY = "flags/launch/__game_path_history__"
GAME_PATH_HISTORY_MAX = 10


class FlagForm(QScrollArea):
    """schema 驱动的 flag 表单。子控件 changed → emit values_changed。"""

    values_changed = Signal()

    def __init__(self, schema: SubcommandSchema,
                 parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._schema = schema
        self._editors: dict[str, QWidget] = {}
        self._browse_buttons: dict[str, QPushButton] = {}

        inner = QWidget()
        outer = QVBoxLayout(inner)
        outer.setContentsMargins(8, 8, 8, 8)
        outer.setSpacing(0)

        # 按 group 分块；保留 schema 里的相对顺序作为组内顺序。
        groups: dict[str, list[FlagSpec]] = {}
        group_order: list[str] = []
        for spec in schema.flags:
            g = (spec.group or "通用").strip() or "通用"
            if g not in groups:
                groups[g] = []
                group_order.append(g)
            groups[g].append(spec)

        # 单一大 grid，5 列：[group_name, label1, editor1, label2, editor2]
        # group_name 在最左列纵向 spanning 该组所有 row；竖直分隔线靠 stylesheet 模拟。
        grid = QGridLayout()
        grid.setHorizontalSpacing(12)
        grid.setVerticalSpacing(6)
        grid.setContentsMargins(0, 0, 0, 0)

        current_row = 0
        for g_idx, gname in enumerate(group_order):
            specs = groups[gname]
            row_span = (len(specs) + 1) // 2  # 2 列 → 向上取整

            # 组间横线（首组前不画）
            if g_idx > 0:
                sep = QFrame()
                sep.setFrameShape(QFrame.HLine)
                sep.setFrameShadow(QFrame.Plain)
                sep.setStyleSheet("color: #c0c0c0; background: #c0c0c0; max-height: 1px;")
                sep.setFixedHeight(1)
                grid.addWidget(sep, current_row, 0, 1, 5)
                current_row += 1

            gl = QLabel(gname)
            gl.setAlignment(Qt.AlignCenter | Qt.AlignVCenter)
            gl.setStyleSheet(
                "color: #444; font-weight: bold; font-size: 13px;"
                " background: #f0f0f0; border-right: 2px solid #c0c0c0;"
                " padding: 4px 8px;"
            )
            gl.setMinimumWidth(72)
            gl.setMaximumWidth(96)
            grid.addWidget(gl, current_row, 0, row_span, 1)

            for i, spec in enumerate(specs):
                r = current_row + i // 2
                col_base = 1 + (i % 2) * 2  # 1 或 3
                label, editor_cell = self._build_grid_entry(spec)
                grid.addWidget(label, r, col_base, Qt.AlignVCenter)
                grid.addWidget(editor_cell, r, col_base + 1)

            current_row += row_span

        # 列宽策略：group / label 紧凑，editor 吃剩余空间
        grid.setColumnStretch(0, 0)
        grid.setColumnStretch(1, 0)
        grid.setColumnStretch(2, 1)
        grid.setColumnStretch(3, 0)
        grid.setColumnStretch(4, 1)

        outer.addLayout(grid)
        outer.addStretch(1)
        self.setWidget(inner)
        self.setWidgetResizable(True)
        self.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)

    # ── 公开 API ──────────────────────────────────────────────────────────

    def values(self) -> dict[str, Any]:
        out: dict[str, Any] = {}
        for spec in self._schema.flags:
            out[spec.cli_key()] = self._read_editor(spec)
        return out

    def set_values(self, values: dict[str, Any]) -> None:
        for spec in self._schema.flags:
            if spec.cli_key() in values:
                self._write_editor(spec, values[spec.cli_key()])

    def schema(self) -> SubcommandSchema:
        return self._schema

    def set_controls_enabled(self, enabled: bool) -> None:
        for editor in self._editors.values():
            editor.setEnabled(enabled)
        for button in self._browse_buttons.values():
            button.setEnabled(enabled)

    # ── grid entry builder ────────────────────────────────────────────────

    def _build_grid_entry(self, spec: FlagSpec) -> tuple[QLabel, QWidget]:
        """Return (label, editor_cell). editor_cell 是 QWidget；path 类型自带浏览按钮。"""
        tip = _rich_tooltip(spec)

        label = QLabel(spec.name)
        label.setMinimumWidth(140)
        label.setMaximumWidth(180)
        label.setToolTip(tip)

        editor = self._make_editor(spec)
        editor.setToolTip(tip)
        editor.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Preferred)
        self._editors[spec.cli_key()] = editor

        if spec.kind == "path":
            cell = QWidget()
            cell_layout = QHBoxLayout(cell)
            cell_layout.setContentsMargins(0, 0, 0, 0)
            cell_layout.setSpacing(4)
            cell_layout.addWidget(editor, stretch=1)
            btn = QPushButton("…")
            btn.setMaximumWidth(28)
            btn.setToolTip("浏览…")
            btn.clicked.connect(lambda _=False, s=spec: self._browse_path(s))
            self._browse_buttons[spec.cli_key()] = btn
            cell_layout.addWidget(btn)
            return label, cell

        return label, editor

    def _make_editor(self, spec: FlagSpec) -> QWidget:
        kind = spec.kind

        if kind == "choice":
            cb = QComboBox()
            for c in (spec.choices or []):
                cb.addItem(c)
            cb.setCurrentText(str(spec.default) if spec.default is not None else "")
            cb.currentTextChanged.connect(self._emit_changed)
            return cb

        if kind in ("store_true", "bool_optional"):
            chk = QCheckBox()
            chk.setChecked(bool(spec.default))
            chk.toggled.connect(self._emit_changed)
            return chk

        if kind == "int":
            sp = QSpinBox()
            sp.setRange(-2_147_483_648, 2_147_483_647)
            sp.setValue(int(spec.default or 0))
            sp.valueChanged.connect(self._emit_changed)
            return sp

        if kind == "float":
            ds = QDoubleSpinBox()
            ds.setDecimals(int(getattr(spec, "decimals", 2)))
            if spec.special_value_text:
                # special value 显示在 value == minimum 时；让 default == minimum
                # 使"默认值"在 UI 上显示为 token 而非数字（如 fps=0 → "auto"）。
                ds.setRange(float(spec.default or 0.0), 1e9)
                ds.setSpecialValueText(spec.special_value_text)
            else:
                ds.setRange(-1e9, 1e9)
            ds.setValue(float(spec.default or 0.0))
            ds.valueChanged.connect(self._emit_changed)
            return ds

        # game_path 用可编辑 combo + 历史下拉（用户希望从历史选）
        if spec.cli_key() == "game_path":
            cb = QComboBox()
            cb.setEditable(True)
            cb.setInsertPolicy(QComboBox.NoInsert)
            cb.setSizeAdjustPolicy(QComboBox.AdjustToMinimumContentsLengthWithIcon)
            history = _load_path_history()
            default_path = str(spec.default or "")
            # default_path 不在 history 里就追加进去 + 持久化，保证它永远在下拉里
            if default_path and default_path not in history:
                history.append(default_path)
                _save_path_history(history)
            for p in history:
                if p:
                    cb.addItem(p)
            cb.setCurrentText(default_path)
            cb.editTextChanged.connect(self._emit_changed)
            return cb

        # profile 用可编辑 combo —— 扫 profiles/*.yaml 列出可选项 + 空项
        # （留空让 main.py 按 exe 名 fuzzy match）
        if spec.cli_key() == "profile":
            cb = QComboBox()
            cb.setEditable(True)
            cb.setInsertPolicy(QComboBox.NoInsert)
            cb.addItem("")  # 空 = 不传 --profile，按 exe 名 fuzzy match
            try:
                from unicap_gui.shared.paths import profiles_dir
                names = sorted(p.stem for p in profiles_dir().glob("*.yaml"))
            except OSError:
                names = []
            for n in names:
                cb.addItem(n)
            cb.setCurrentText(str(spec.default or ""))
            cb.editTextChanged.connect(self._emit_changed)
            return cb

        # str / path
        le = QLineEdit()
        le.setText(str(spec.default or ""))
        le.textChanged.connect(self._emit_changed)
        return le

    # ── 读 / 写 editor ────────────────────────────────────────────────────

    def _read_editor(self, spec: FlagSpec) -> Any:
        ed = self._editors[spec.cli_key()]
        if isinstance(ed, QComboBox):
            return ed.currentText()
        if isinstance(ed, QCheckBox):
            return ed.isChecked()
        if isinstance(ed, QSpinBox):
            return ed.value()
        if isinstance(ed, QDoubleSpinBox):
            return ed.value()
        if isinstance(ed, QLineEdit):
            return ed.text()
        return None

    def _write_editor(self, spec: FlagSpec, v: Any) -> None:
        ed = self._editors[spec.cli_key()]
        try:
            if isinstance(ed, QComboBox):
                ed.setCurrentText(str(v))
            elif isinstance(ed, QCheckBox):
                # QSettings IniFormat 把 bool 存成 "true"/"false" str —— 兼容读
                if isinstance(v, str):
                    v = v.lower() == "true"
                ed.setChecked(bool(v))
            elif isinstance(ed, QSpinBox):
                ed.setValue(int(v) if v not in ("", None) else 0)
            elif isinstance(ed, QDoubleSpinBox):
                ed.setValue(float(v) if v not in ("", None) else 0.0)
            elif isinstance(ed, QLineEdit):
                ed.setText(str(v) if v is not None else "")
        except (TypeError, ValueError):
            pass  # QSettings 残留无效值，忽略

    # ── 浏览按钮 ──────────────────────────────────────────────────────────

    def _browse_path(self, spec: FlagSpec) -> None:
        ed = self._editors[spec.cli_key()]

        def _get_text() -> str:
            if isinstance(ed, QComboBox):
                return ed.currentText()
            return ed.text()

        def _set_text(s: str) -> None:
            if isinstance(ed, QComboBox):
                ed.setCurrentText(s)
            else:
                ed.setText(s)
            # game_path：浏览选中后立即推历史，不必等 Start
            if spec.cli_key() == "game_path" and s:
                self.push_game_path_history(s)

        current = _get_text() or str(Path.home())
        kind = spec.path_kind or "file"

        if kind == "dir" or kind == "optional_dir":
            picked = QFileDialog.getExistingDirectory(self, f"选择 {spec.name} 目录", current)
            if picked:
                _set_text(picked)
            return

        if kind == "optional_path":
            picked, _ = QFileDialog.getOpenFileName(self, f"选择 {spec.name}", current)
            if picked:
                _set_text(picked)
            return

        # default: file
        picked, _ = QFileDialog.getOpenFileName(
            self, f"选择 {spec.name}", current, "可执行 (*.exe);;所有文件 (*)",
        )
        if picked:
            _set_text(picked)

    # ── helper ────────────────────────────────────────────────────────────

    def _emit_changed(self, *_args) -> None:
        self.values_changed.emit()

    def push_game_path_history(self, path: str) -> None:
        """LaunchTab 在 Start 时调；把 path 推到历史顶部，刷新 combo 下拉项。"""
        if not path:
            return
        hist = _load_path_history()
        hist = [p for p in hist if p and p != path]
        hist.insert(0, path)
        hist = hist[:GAME_PATH_HISTORY_MAX]
        _save_path_history(hist)

        ed = self._editors.get("game_path")
        if isinstance(ed, QComboBox):
            current = ed.currentText()
            ed.blockSignals(True)
            ed.clear()
            seen: set[str] = set()
            for p in hist:
                if p and p not in seen:
                    ed.addItem(p)
                    seen.add(p)
            ed.setCurrentText(current)
            ed.blockSignals(False)


def _rich_tooltip(spec: FlagSpec) -> str:
    """Build hover tooltip: <b>flag</b> + 默认值 + 详细描述（spec.tooltip 优先）。"""
    body = spec.tooltip or spec.help or ""
    body_html = body.replace("&", "&amp;").replace("<", "&lt;").replace("\n", "<br>")
    default_txt = ""
    if spec.kind == "store_true":
        default_txt = "False（不勾即不传）"
    elif spec.kind == "bool_optional":
        default_txt = "True" if spec.default else "False"
    elif spec.default not in (None, ""):
        default_txt = str(spec.default)
    parts = [f"<b>{spec.name}</b>"]
    if default_txt:
        parts.append(f"<i>默认</i> <code>{default_txt}</code>")
    if body_html:
        parts.append(body_html)
    # max-width 让 Qt 自动换行（避免过长 tooltip 横向越界）
    return f'<div style="max-width:480px">{"<br>".join(parts)}</div>'


def _load_path_history() -> list[str]:
    """从 QSettings 读 game-path 历史（每条独立编号 key，绕开 list 序列化坑）。"""
    return gui_settings.load_string_list(GAME_PATH_HISTORY_KEY)


def _save_path_history(hist: list[str]) -> None:
    gui_settings.save_string_list(GAME_PATH_HISTORY_KEY, hist)
