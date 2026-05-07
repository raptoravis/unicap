# Impact: PyQt UI 包装器（操作员控制台）

**Date**: 2026-05-07
**Sponsor**: raptoravis
**Requirements**: `.scratch/ui/requirements.md` (v1.0, confidence HIGH)
**Paradigm**: enhancement/delta-design
**Complexity**: **L**（12 goals × 中等粒度；~1500 LoC 新代码）

> **关于 L 复杂度**：phase 文档说 L+ 应升 architecture-first。此处保持 delta-design 的理由：
> - "L" 全在**新增子系统内部**，对现有代码改动 ≈ 0（仅 subprocess + 文件 polling 集成）
> - 现有代码的 contract 已稳定（sidecar protocol 在 CLAUDE.md 写死，stdout/log 格式已用半年）
> - architecture-first 适合 unknown unknowns 高的场景；这里的 unknown 都已在 requirements + community research 阶段解掉
> - 真要细分，UI 是个 **brownfield-housed greenfield subsystem**——repo brownfield 但 UI 子树 greenfield，delta-design 的 impact-analysis 模板对前者足够

---

## Change Summary

在 unicap repo 顶层新增 `unicap_gui/` 包，用 PySide6 把 `main.py` 的 `launch / video / pack` 三个 subcommand 包成 GUI。UI **不修改 `main.py` 一行代码**，只通过 `subprocess.Popen([..., 'main.py', '<sub>', ...])` 调用 + 读 sidecar 文件 + tail 日志文件实现状态可见性。`pyproject.toml` 新增 `gui` optional-dependency（`PySide6`）。

---

## Affected Modules / Files

### 新增（greenfield 子树）

```
unicap_gui/
├── __init__.py
├── __main__.py                  # `uv run python -m unicap_gui` 入口
├── app.py                       # QApplication + QMainWindow + QTabWidget
├── shared/
│   ├── __init__.py
│   ├── cli_schema.py            # CLI flag schema（声明式描述 launch/video/pack flag）
│   ├── process.py               # QProcess wrapper：start/stop/优雅停止 + game taskkill 兜底
│   ├── settings.py              # QSettings(IniFormat) 读写
│   ├── paths.py                 # UNICAP_TEMP / fc_state.txt / auto_play.log 路径
│   └── log_tailer.py            # tail %TEMP%/unicap/auto_play.log 并 emit Qt signal
├── tabs/
│   ├── __init__.py
│   ├── launch_tab.py
│   ├── video_tab.py
│   └── pack_tab.py
└── widgets/
    ├── __init__.py
    ├── flag_form.py             # CLI flag schema → QFormLayout 控件
    ├── log_pane.py              # 5000 行环形 buffer QPlainTextEdit
    ├── cli_preview.py           # 等价 CLI 文本框 + 复制按钮 + Extra args
    ├── dashboard.py             # launch tab 顶部仪表盘（状态条 / 计数器 / 心跳灯）
    ├── auto_play_panel.py       # auto-play 子面板（profile/driver/VLM）
    └── session_tree.py          # video/pack 的 session 树
```

### 已存在（被读，不被改）

| File | UI 怎么用 |
|---|---|
| `main.py` | subprocess 调用入口；CLI flag 默认值的事实来源 |
| `profiles/*.yaml` | `auto_play_panel` 的 profile 下拉扫描源 |
| `<game_dir>/fc_state.txt` | `dashboard` 状态条数据源（1Hz polling） |
| `%TEMP%/unicap/auto_play.log` | `dashboard` VLM/watchdog/heartbeat 计数源（log_tailer 增量读） |
| `<dataset_root>/<game>/survey/recommended_skip.txt` | `redo survey` 按钮删它 |
| `<dataset_root>/<game>/<ts>/frames/*.bmp` | frame counter 数它 |
| `<dataset_root>/<game>/<ts>/{video.mp4,dataset.h5}` | session_tree 状态图标查它 |
| `.env` | auto_play_panel 显示当前值 + "改 .env" 调外部编辑器 |

### 修改（最小）

| File | 改动 | 原因 |
|---|---|---|
| `pyproject.toml` | 加 `[project.optional-dependencies] gui = ["PySide6>=6.5"]` + `[project.scripts] unicap-gui = "unicap_gui.__main__:main"` | 安装路径 |
| `.gitignore` | 加 `unicap_gui/__pycache__/`（`*.pyc`/`__pycache__` 已通配则不动） | 卫生 |

**`main.py` 不改一行**——这是关键约束（向后兼容 / 让用户随时退回 CLI）。

---

## Interface Changes

**主程序对外**：none。
- 新增 console-script `unicap-gui`（`pyproject.toml`）
- CLI subcommand 与 flag 表面零变化

**UI 内部 contract（公开给后续维护者）**：
- `shared.cli_schema.CLI_SCHEMA: dict[str, list[FlagSpec]]` —— 三 subcommand 的 flag 描述（dataclass `FlagSpec(name, kind, default, choices, help)`）
- `shared.process.SubprocessRunner.start(cmd: list[str]) / stop()` —— 唯一的子进程控制器；唯一负责 CTRL_BREAK + taskkill 的人
- `widgets.flag_form.FlagForm.values() -> dict[str, Any]` —— 表单到 dict 的纯函数

`flag_form` 通过 `cli_schema` 数据驱动；新加 CLI flag 时只改 schema，不改 widget。

---

## Integration Points

| 集成点 | 方向 | 协议 |
|---|---|---|
| 子进程启动 | UI → main.py | `subprocess.Popen([..., '-u', 'main.py', sub, *flags], creationflags=CREATE_NEW_PROCESS_GROUP, stdout=PIPE, stderr=STDOUT, bufsize=1, text=True)` |
| 子进程优雅停止 | UI → main.py | `proc.send_signal(signal.CTRL_BREAK_EVENT)` → 等 5s → `taskkill /T /F /PID <pid>` 兜底（含游戏子进程） |
| 子进程 stdout 流 | main.py → UI | QSocketNotifier 或 `readyReadStandardOutput`（用 QProcess 替代 Popen 走 Qt 原生通道）；buffer 由 `main.py:1095 sys.stdout.reconfigure(line_buffering=True)` 保证 |
| 状态读 | addon → UI（间接） | UI 1Hz `Path(<game_dir>)/fc_state.txt` 读；变化时 emit signal |
| auto-play 计数读 | runner → UI | 1Hz `tail -F %TEMP%/unicap/auto_play.log`；正则 `[VLM-COST] call#(\d+)` / `static-frame 触发 #(\d+)` / `[HEARTBEAT]`；累计计数 |
| Frame counter | filesystem → UI | 1Hz `len(list(frames_dir.glob("*BackBuffer*.bmp")))` |
| Survey 重置 | UI → filesystem | `recommended_skip.txt.unlink(missing_ok=True)` |
| F8/F9 镜像 | UI → game window | `FindWindowW(None, <title>)` 失败时 fallback `EnumWindows + GetWindowThreadProcessId` 按 game pid；找到后 `SendInput` 发 VK_F8/VK_F9 keydown+keyup（**不是** PostMessage —— SendInput 走全局 input queue，与 game 的 GetAsyncKeyState 兼容）。`tools/window_manager.py` 已有按 pid 找窗口的逻辑可复用思路 |
| Profile 列表 | filesystem → UI | 启动时 + 刷新按钮 `Path("profiles").glob("*.yaml")` |
| .env 显示 | filesystem → UI | `python-dotenv` 读 `.env`；写靠用户用外部编辑器 |
| 进度条 / VLM 预算 | log + 时间 → UI | 维护过去 1 小时 VLM call timestamps 滑动窗口；与 `--vlm-budget-per-hour` 比 |

---

## Existing Behavior to Preserve

- `main.py` 任何 CLI 调用形式（`uv run main.py launch ...`）行为不变
- `main.py` stdout 已 line-buffered（main.py:1095-1099）—— UI 不能依赖未 line-buffered 的假设但能信任
- `[CAPTURE]` 是 `print` 出 stdout 可 grep；`[AUTO-PLAY]` 是 `print` 也 stdout（部分）；`[VLM-COST]/[WATCHDOG]/[HEARTBEAT]` 走 `logging.getLogger("unicap.auto_play")` **只到文件不到 stdout**
- F8/F9 在游戏窗口聚焦时由 `GetAsyncKeyState` 读；UI 不能注册 `QShortcut(QKeySequence("F8"))` 否则双触发
- launch 退出时 main.py finally 块清 `fc_state.txt` 回 `idle` + Vulkan HKCU 注册表清理 —— UI 必须**给 main.py 至少 5s 优雅退出窗口**才上 taskkill
- profile YAML schema 不动（UI 只列出 profile 名，不解析内容）

---

## Risk Assessment

| 风险 | 概率 | 缓解 |
|---|---|---|
| **CTRL_BREAK_EVENT 不杀游戏子进程** | 高 | 总是跟一次 `taskkill /T /F /PID <main_py_pid>` 兜底；测试以确认 ff7r exe 不残留 |
| **fc_state.txt 读到正在写入的中间态** | 低 | 文件极短（idle/surveying/capturing），原子 write 在 Win 上不保证；读失败时保留上次值即可 |
| **log tailer 与日志 rolling 冲突** | 中 | `RotatingFileHandler maxBytes=5MB backupCount=3` —— rotate 时 inode 切换；tailer 用按文件名 reopen 模式（不用 fd hold），失败时 0.5s 后重试 |
| **PySide6 与 Python 3.13 兼容** | 低 | PySide6 ≥ 6.6 支持 3.13；`pyproject.toml` 钉 `>=6.6` |
| **`[VLM-COST]` 等只在 log 文件不在 stdout** | 已识别 | 不修改 main.py；UI 走 log tailer 路径 |
| **F8 SendInput 走错窗口** | 中 | 启动 launch 后 UI 缓存 main.py 子进程的"游戏 pid"（怎么拿？—— 解析 `[启动] <exe>` 后的 cmdline 推断 / 或扫 game.exe 名）。Fallback：UI 提示用户先 alt-tab 到游戏 |
| **session 树扫描 1000+ session 卡 GUI** | 低 | 异步 QtConcurrent / `QThread` worker；首次 ≤500 同步即可 |
| **Windows 路径含中文 game-path** | 中 | 全程用 `pathlib.Path` + `subprocess.Popen([str(...)])` 列表形式（不走 shell）；`text=True, encoding='utf-8'` 强制 UTF-8 stdout |
| **launch 跑时 UI 崩溃 → 子进程孤儿** | 中 | `app.aboutToQuit` connect 到 `SubprocessRunner.stop`；CREATE_NEW_PROCESS_GROUP 让子进程不随 GUI 退出 —— 这是为了优雅停止设计的，孤儿是该 trade-off 的代价；用户重启 GUI 时检测残留 main.py 进程并提示 |
| **预检失败但用户绕过 → CLI 报错对 novice 无意义** | 低 | "跳过校验"复选框默认关；power-user 主动开 |
| **F8/F9 镜像按钮 双触发** | 高（设计陷阱） | UI 不绑 QShortcut；按钮只走 SendInput；明确测试游戏窗口聚焦时 UI F8 按钮触发结果 = 1 次 capture，不是 2 次 |

---

## Test Strategy（移交 phase 3 详细化）

层次：
1. **Capability** —— 单元级。`cli_schema → flag_form → values()` 往返；`SubprocessRunner.stop` mock subprocess；`log_tailer` 喂构造日志文本验证计数
2. **Integration** —— GUI 起来跑 `main.py --version` 子进程，验证 stdout 显示 + Stop 干净
3. **E2E** —— 实跑 FF7R，覆盖 S-001..S-005

无 CI 自动 GUI 测试（unicap 现有 `verify_auto_play.py` 是脚本式 capability 集合，UI 跟它一个风格：`scripts/verify_gui.py` 起 QApplication + 用 QTest 触发动作）。

---

## Complexity Estimate

**L**（详 frontmatter 解释）。10 个文件、~1500 LoC、5 个 subsystem boundary。Decision：保 delta-design 不升 architecture-first。

---

## Phase Sequence Reminder

1. ✅ requirements (HIGH)
2. ✅ impact-analysis (本文件)
3. → test-plan（轻量；must-have checkpoints from G-001..G-012）
4. ⛔ extract-contracts skip（共享层非独立模块）
5. → implement（按 5a/5b/5c 增量切片）
6. → code-review
7. → verify
8. → deliver
