# Handoff: PySide6 GUI + auto-play VLM 砍除

**Generated**: 2026-05-07 16:13 +0800
**Branch**: master（与 origin/master 同步，clean）
**Status**: Ready for Review —— 全部代码 commit + push；GUI 启动可用，端到端 capture 没在本 session 实跑过

## Goal

为 unicap 加一个 PySide6 GUI（`unicap_gui/` 包，pip extra `gui`，入口 `unicap-gui`），代替原来 PowerShell + 控制台手敲 `uv run main.py launch ...` 的工作流。同时根据用户决定，把 auto-play 的 VLM / hybrid driver 整套砍掉，只保留 keep-alive 模式。

## Completed

- [x] 新 `unicap_gui/` 包：app / tabs（launch、video、pack 三 tab）/ widgets / shared
- [x] 三 tab 中文标签（采集 / 生成视频 / 打包）+ 16px 加大字号；缺省选中"采集"
- [x] schema-driven `FlagForm`：`unicap_gui/shared/cli_schema.py` 把 main.py argparse 复刻成数据，FlagForm 渲染对应控件
- [x] `--game-path` 行：可编辑 `QComboBox` + 历史下拉（每条独立编号 key 存 QSettings，绕开 IniFormat list 序列化对 `\\` 路径不友好的问题）；浏览选中即推历史
- [x] `--profile` 行：可编辑 `QComboBox`，扫 `profiles/*.yaml` 列出 + 一个空项（留空让 main.py 按 exe 名 fuzzy match）
- [x] `--dataset-root` 默认值改成 `D:\unicap_output`，与 `tools/capture/config.py:DATASET_ROOT` 同步显示
- [x] 等价 CLI preview 实时刷新 + 一键复制；Extra args 透传段可写额外 flag
- [x] launch tab 顶部 dashboard：状态条 / session link / frames 计数 / elapsed / capture-duration 进度条 / WATCHDOG 计数 / ATK 心跳灯
- [x] dashboard 文字色用 `palette(text)`（浅色主题下不再灰白看不清）+ 加粗 +1pt
- [x] F8 / F9 镜像按钮（`SendInput`）+ 重做 survey 按钮
- [x] Start 按钮放大着色（绿色，44px 高度）
- [x] **Stop 按钮删掉**：launch tab 用 F9 终止 capture 会话；要彻底退 main.py 关 GUI 窗口（`MainWindow.closeEvent` 会向所有 running runner 发 `CTRL_BREAK_EVENT`）
- [x] auto_play 首次运行 default=True（INI 没保存过 `auto_play` key 时）；已保存值由 BaseTab._restore_settings 还原
- [x] `--game-name` flag 整体删除（CLI argparse + GUI schema + launch_tab 的 fallback 逻辑），`game_name` 内部 = `game_exe.stem`
- [x] auto-play 砍掉 VLM / hybrid：删 `tools/auto_play/vlm_driver.py` 整文件；runner.py 砍 vlm/hybrid 分支、`_patrol_loop` / `_heartbeat_loop` / `_has_movement`；watchdog.py 砍 `_consult_vlm` / `vlm_driver` 参数；main.py 删 `--driver` / `--vlm-*` 5 个 flag
- [x] auto-play 视觉判断改为只读 `BackBuffer.png`（no-ui 流）：`watchdog._read_latest_bmp` 全部 skip `BackBufferUI`；删 watchdog UI-mask arm（`_read_latest_pair` + `_UI_MASK_*` dead code）
- [x] launch 默认 `--ui-mode no-ui`（之前 auto-play 时强制 both）
- [x] profiles `_default` / `batman_ak` / `doom_eternal` / `ff7r` 剥掉末尾 `vlm:` block；profile.py YAML schema 不再要求 `vlm:`；`GameProfile` 数据类去 `vlm` 字段
- [x] `pyproject.toml` 删 `auto-play-vlm` extra（openai + python-dotenv）
- [x] `.env` / `.env.example` 从 git 删除 + `.gitignore` 加 `.env`（之前是注释状态）
- [x] dashboard / log_tailer 同步去掉 VLM 计数 + HEARTBEAT 心跳灯，留 WATCHDOG + ATK
- [x] CLAUDE.md auto-play 章节重写，去 `--driver` / VLM 配置 / `.env` 整段
- [x] **Auto-Play 辅助面板** 整体删除（用户决定不要这个旁挂面板，profile 选择直接通过 form 行的 combo）；`unicap_gui/widgets/auto_play_panel.py` 文件已删

## Not Yet Done

- [ ] **没在本 session 跑过端到端 capture**：commit `d826061` 之前的 auto-play 代码改动量大（runner.py 重排 / watchdog.py 简化），需要实机 F8/F9 走一轮验证 keep-alive driver + watchdog recovery 序列还能跑通
- [ ] launch tab 的 `_btn_redo_survey` 在 `_on_run_started` 时 disabled，但若子进程异常崩溃没走 stopped 路径，按钮会卡 disabled —— 不影响功能，下个 session 可改成关联 `is_running` 而非 lifecycle 信号
- [ ] dashboard 的 `_attack_led.set_steady("#ef6c00")` 在 recovery 进入时设橙色，但 `_on_recovery_active(False)` 没主动 reset，靠 attack pulse 自然覆盖（注释里写明了）—— 视觉上 OK，但若 recovery 后长期无 attack 注入会卡橙；要修就在 `_on_recovery_active(False)` 里 `set_steady("#444")`
- [ ] PR 前需要更新 README（如果有的话）说明 GUI 入口

## Failed Approaches (Don't Repeat These)

- **`auto_play` flag QSettings 持久化坑**：早先尝试每次 GUI 启动都 force-set `auto_play=True` + `color=no-ui`（写死在 LaunchTab.__init__）。用户反对："auto_play,color等参数需要从保存的历史中恢复，而不是总是缺省值"。改回：只在 INI 没 saved key 时才 default True，已保存值优先。
- **game-path 历史用 JSON string 存 QSettings**：第一版用 `json.dumps(hist)` 存单 key，但 IniFormat 对单 string 内含 `,` 或 `[` 等 JSON 元字符会抽风（特别是含 `\` 的 Windows 路径），导致多条历史合并成单串。**改用 `save_string_list`：每条独立编号 key**（`flags/launch/__game_path_history__/0`, `/1`, ...），完全绕开 list 序列化坑。`unicap_gui/shared/settings.py:save_string_list` / `load_string_list`。
- **Auto-Play 辅助面板早期还显示 .env masked 值 + 改 .env / 重读 .env 按钮**：随 VLM driver 砍除一并删了，因为 `.env` 不再被任何代码读取。**不要重新加回这种 panel**——profile 选择已通过 form 里 `--profile` 行的 combo 解决。
- **`--auto-play` 自动设 `--ui-mode=both`**：早先 main.py:cmd_launch 当 `auto_play=True` 时把 ui-mode 默认成 `both`（让 watchdog 看 post-UI BMP）。用户决定不再依赖 post-UI 流，所有视觉判断只用 `BackBuffer.png`（no-ui 流）。**watchdog 的读图路径已改为 skip `BackBufferUI`**，不要恢复 both 默认。
- **dashboard 文字色 `#eaeaea`**：在浅色 Qt 主题下浅灰文字 + 浅色背景几乎看不见。**用 `palette(text)`** 跟随系统主题。
- **QGroupBox checkable + setMaximumHeight 折叠**：原 AutoPlayPanel 用这个手法做折叠。Panel 已删，但模式留作参考——若将来要加 collapsible groupbox，注意 `setChecked(True)` 触发 `toggled` 信号但默认不会自动 hide children，要手动 `_on_toggle` 把 children setVisible + 调整 setMaximumHeight。

## Key Decisions

| Decision | Rationale |
|----------|-----------|
| 砍 VLM / hybrid driver | 用户明确：不再用 VLM 模式；keep-alive 足够长跑无人值守采集，无 API 费用 |
| auto-play 视觉判断只看 no-ui 流 | post-UI BackBufferUI 与 pre-UI BackBuffer tone curve 不同，UI-mask arm 假阳性高（11/17 触发是 false positive 的真实 log）；no-ui 流 + OCR + 帧差已够 |
| `--auto-play` 首次默认 True | 用户决定 GUI 缺省进 auto-play 状态（无人值守是主用例）；后续保存值优先 |
| `--game-name` 删除 | 一直从 `game_exe.stem` 派生，flag 是历史遗留，无人显式用 |
| Stop 按钮删除 | 停止子进程的两条路径（F9 + 关 GUI 窗口）已够用，big red Stop 是冗余 + 误触风险 |
| game-path / profile 都用可编辑 QComboBox | 既允许用户从已知列表选，也允许手填新值（特别是 game-path，新游戏第一次接入需要手输路径） |
| QSettings IniFormat 而非注册表 | 文件型存储好审计、好删（删 `unicap-gui.ini` 一键重置 GUI 状态） |

## Current State

**Working**:
- GUI 启动通过 `uv run --with PySide6 python -m unicap_gui` 可起来；三 tab 能切换；表单值持久化到 `%APPDATA%\unicap-gui\unicap-gui.ini`
- main.py CLI 仍可独立用：`uv run main.py launch [--auto-play] [--profile NAME]` 等不依赖 GUI
- `import` sanity 全 pass（Qt 模块 + auto_play 包 + main.py）
- 4 个 profile YAML schema 校验通过；`load_profile('ff7r')` OK
- `auto-play` keep-alive driver + watchdog static-frame recovery + OCR arm + attack heartbeat —— 代码路径都在但本 session 没跑实机

**Broken**: 无已知 broken。但见下方 "Edge Cases" 关于 attack_led recovery 状态。

**Uncommitted Changes**: 无（git clean，已 push）。最近 commit：`1bd49ad update`（Stop 删 + dataset-root default）→ `52e023c update`（Auto-Play 面板删 + profile combo）→ `d826061 feat(gui+auto-play): ...`（主要工作的合并 commit）。

## Files to Know

| File | Why It Matters |
|------|----------------|
| `unicap_gui/app.py` | MainWindow + 三 tab 容器；tab 标签 / 字号 stylesheet 在这；`closeEvent` 处理 running subprocess 的 graceful stop |
| `unicap_gui/tabs/base_tab.py` | 所有 tab 的公共骨架：FlagForm + CLIPreview + Start 按钮 + LogPane + splitter；子类用 `_wire_extra` 钩 dashboard |
| `unicap_gui/tabs/launch_tab.py` | launch 子命令 tab：dashboard / F8/F9/重做 survey 按钮 / 启动前预检 / first-run auto_play=True |
| `unicap_gui/tabs/video_tab.py` / `pack_tab.py` | 简单：用 BaseTab 默认布局即可 |
| `unicap_gui/widgets/flag_form.py` | schema → 控件树；**game_path / profile 两个特判**（line ~131 / ~149）；`push_game_path_history` 公开 API |
| `unicap_gui/widgets/cli_preview.py` | 等价 CLI 文本框 + 复制按钮 + Extra args |
| `unicap_gui/widgets/dashboard.py` | launch tab 顶部状态条；palette-aware 文字色；ATK led 双语义（attack pulse + recovery 常亮橙） |
| `unicap_gui/widgets/log_pane.py` | 子进程 stdout 实时 tail |
| `unicap_gui/shared/cli_schema.py` | 所有 flag 数据驱动定义；改 main.py argparse 时**这里也要改** |
| `unicap_gui/shared/settings.py` | QSettings IniFormat wrapper；含 `save_string_list` / `load_string_list`（path history 用） |
| `unicap_gui/shared/process.py` | `SubprocessRunner`：起 main.py + 解析 stdout 抽 session_dir + CTRL_BREAK_EVENT 优雅停 |
| `unicap_gui/shared/log_tailer.py` | 0.5s tail `auto_play.log` 抽 watchdog 触发 + ATK 信号 |
| `tools/auto_play/runner.py` | `AutoPlayRunner`：keep-alive driver + watchdog + attack heartbeat 编排 |
| `tools/auto_play/watchdog.py` | static-frame 检测：global / local / long-window 三 arm + OCR arm；`_trigger_recovery` 走 profile.recovery |
| `tools/auto_play/profile.py` | YAML schema 校验；`GameProfile` 数据类（已去 vlm 字段） |
| `main.py` | CLI 入口；`cmd_launch` 是核心 flow；`--auto-play` flag + 简化的 `_start_auto_play` |
| `CLAUDE.md` | 项目级指导文档；auto-play 章节已重写 |

## Code Context

### FlagForm 的 game_path / profile 两个特判（`unicap_gui/widgets/flag_form.py`）

```python
# game_path 用可编辑 combo + 历史下拉
if spec.cli_key() == "game_path":
    cb = QComboBox()
    cb.setEditable(True)
    cb.setInsertPolicy(QComboBox.NoInsert)
    history = _load_path_history()
    default_path = str(spec.default or "")
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
```

### values_to_argv 的 path 类型特判（`unicap_gui/shared/cli_schema.py`）

```python
def values_to_argv(schema: SubcommandSchema, values: dict[str, Any]) -> list[str]:
    """path 类型始终 emit（即便等于 spec.default —— 让预览自包含），其它仅含偏离默认值。"""
    argv = []
    for spec in schema.flags:
        v = values.get(spec.cli_key(), spec.default)
        if spec.kind == "path":
            if v:
                argv.extend([spec.name, str(v)])
            continue
        if is_default(spec, v):
            continue
        # ... store_true / bool_optional / choice / str / int / float ...
```

### LaunchTab 的 first-run auto_play 默认（`unicap_gui/tabs/launch_tab.py`）

```python
def __init__(self, parent: QWidget | None = None) -> None:
    super().__init__(LAUNCH, parent)
    # auto_play 首次运行 default=True（INI 没保存过 auto_play key 的场景）。
    # 已保存的值由 BaseTab._restore_settings 还原，这里不覆盖。
    saved = gui_settings.load_flag_values("launch")
    if "auto_play" not in saved:
        self._form.set_values({"auto_play": True})
        self._refresh_preview()
```

### AutoPlayRunner 简化后的构造器（`tools/auto_play/runner.py`）

```python
class AutoPlayRunner:
    def __init__(
        self,
        profile: GameProfile,
        frames_dir: Path,
        debug: bool = False,
        log_path: Path | None = None,
    ) -> None:
        # ... 4 个 driver-/vlm-相关参数都已去掉
        self._driver: BotDriver = create_driver(profile)  # 永远 KeepAliveDriver
        self._watchdog = StaticFrameWatchdog(
            frames_dir=frames_dir, profile=profile, input_backend=self._backend,
            log_path=log_path,
            recovery_active_evt=self._recovery_active_evt,
        )  # vlm_driver 参数删了
```

### QSettings 落盘位置（`%APPDATA%\unicap-gui\unicap-gui.ini`）

```ini
[window]
size=@Size(1100 800)

[flags/launch]
game_path=E:/games/ff7remake/End/Binaries/Win64/ff7remake_.exe
ui_mode=no-ui
auto_play=true
color=no-ui
__extra_args__=--auto-play-debug
...

[flags/launch/__game_path_history__]
0=E:/games/ff7remake/.../ff7remake_.exe
1=E:/games/Doom/...
```

## Resume Instructions

### 启动 GUI 验证基础功能

1. `uv sync --extra gui` 装 PySide6 依赖（首次）
2. `uv run --with PySide6 python -m unicap_gui` 起来
   - Expected: 1100×800 窗口，三 tab `采集 / 生成视频 / 打包`，缺省选中"采集"
   - Expected: 采集 tab 顶部 "未连接" 灰色状态条，session/frames/elapsed 标签可见
   - Expected: 表单 `--auto-play` checkbox 默认勾上（首次跑）；CLI preview 显示 `uv run main.py launch --game-path E:\... --dataset-root D:\unicap_output --auto-play`
3. 点 game-path 下拉：应该看到 default `E:\games\ff7remake\...` 一项；点 浏览 选别的 exe → 推入历史 → 下拉变两项
4. 点 profile 下拉：应该有 `""` / `_default` / `batman_ak` / `doom_eternal` / `ff7r` 五项
5. 关窗 → 重启 → 表单值应该恢复（除 first-run 后 auto_play 由 saved 决定）

### 验证端到端 capture（重要 —— 本 session 没做）

1. 启 GUI；填 `--game-path` 指向有效游戏 exe
2. 点 Start → 子进程 main.py 应该起来 → 状态变绿"运行中（pid=N）"
3. 在游戏内按 F8 → 状态条变绿 CAPTURING；frames 计数应该开始涨
4. 等 60s（`--capture-duration` 默认）→ 应该自动 roll 到新 session；session link 切到新时间戳
5. 按 F9 → 应该停止当前 capture 但 main.py 进程留着；状态回 IDLE
6. 关 GUI 窗口 → MainWindow.closeEvent 弹模态确认 → Yes → main.py 收 CTRL_BREAK_EVENT 退出
   - Expected: log pane 显示 `[unicap-gui] cmd: ...` + capture 进度行 + watchdog 触发计数（如有）
   - If 子进程不退: 检查 SubprocessRunner.stop() 的 timeout（默认 5s）；可能游戏还卡着没释放 stdin

### 验证 keep-alive driver + watchdog（无人值守 30 分钟测）

```powershell
uv run main.py launch --auto-play --profile ff7r --capture-duration 60
# 在游戏中按 F8，观察 console:
#   [AUTO-PLAY] driver=keep-alive profile=ff7r gamepad=...
#   [CAPTURE] 开始采集 → ...
#   [AUTO-PLAY] tick: keep-alive → N action(s) [...]
# 至少 30 分钟无干预，应该看到:
#   [WATCHDOG] static-frame 触发 #N ... → 注入 recovery (5 步)  （若卡住）
#   [ATTACK-HB] 注入 attack#N (period=12.0s)                  （每 12s 一次）
# 不应该看到任何 [VLM-COST] / [PATROL] / [HEARTBEAT] 行（这些都已删）
```

### 单测 / 静态检查

```powershell
# 1. 语法 & import
uv run --with PySide6 python -c "import main; from tools.auto_play.runner import *; from unicap_gui.app import MainWindow"

# 2. profile YAML schema
uv run python -c "from tools.auto_play.profile import load_profile; [load_profile(n, fallback=False) for n in ['_default', 'batman_ak', 'doom_eternal', 'ff7r']]"

# 3. cli_schema flag 数量（删 game-name + 5 个 vlm-* 后应该是 16）
uv run python -c "from unicap_gui.shared.cli_schema import LAUNCH; print(len(LAUNCH.flags))"
# Expected: 16
```

## Setup Required

- Windows 11（GUI 用 SendInput 发 F8/F9，仅 Windows 实现）
- Python 3.13+ (`uv` 管依赖)
- PySide6 ≥ 6.6（`uv sync --extra gui`）
- ViGEm Bus 内核驱动（`auto-play` extra 用，不装会 fallback 键鼠）
- 环境变量：无（`.env` / `VLM_*` 全删了）

## Edge Cases & Error Handling

- **subprocess 启动失败**：`SubprocessRunner.start` 抛异常 → BaseTab 不会更新状态条，Start 按钮卡 disabled
  - 当前行为：log pane 应显示 error；用户需重启 GUI 或手动 `runner._on_subprocess_stopped(rc=-1)`
  - 改进点：catch + 立即 emit stopped(rc=-1)
- **auto-play 子进程崩**：runner.stop 通过 `_on_run_stopped` 回 detach dashboard；btn_redo_survey 重新 enabled
  - If 没收到 stopped 信号（如 Python OOM kill），按钮卡 disabled —— 见 Not Yet Done
- **profile 文件不存在**：FlagForm 行可手填任意 profile 名 → `_precheck_before_start` 弹模态拦截
- **dataset-root 父目录不存在**：precheck 拦截
- **game-path 文件不存在**：precheck 拦截
- **关 GUI 时有 running 子进程**：MainWindow.closeEvent 弹模态确认 → Yes 走 `runner.stop(timeout=5s)` → 5s 内不退就遗留孤儿进程（main.py 自己的 ctrl_break handler 应该 catch；游戏进程不归 main.py 管）
- **recovery 后 attack_led 卡橙**：`_on_recovery_active(False)` 没主动 reset led，靠下一次 attack pulse 自然覆盖；30 分钟无 attack 时视觉上有点怪 —— 见 Not Yet Done

## Warnings

- **`unicap_gui/shared/cli_schema.py` 必须与 main.py argparse 同步**：加新 flag 时两边都要改，否则 GUI 不会显示 / 不会传到 CLI。建议改 main.py 时立刻 grep 一下 `cli_schema.py`。
- **`.env` 已 git rm + .gitignore**：但 git 历史里仍有真实 API key（`sk-a629...` in commit `fb59f3c "update"`）。如果 repo 要公开，需要 `git filter-repo` 或 `bfg` 重写历史。当前是私 repo 暂未处理。
- **`docs/designs/impact_20260507_pyqt-ui.md` / `testplan_20260507_pyqt-ui.md`** 是本 session 的设计 / 测试计划文档，已 commit。如果计划被推翻（如本 session 中 Auto-Play 辅助面板被删），这两文档可能与代码不完全一致 —— 文档作为快照，不是 spec。
- **`.scratch/ui/` 含 smoke test 脚本 + requirements.md**：本 session 的开发草稿，已 commit 进来。下个 session 不需要修改这些；要做新功能开新目录 `.scratch/<feature>/`。
- **`auto-play` 的 keep-alive 注入 vs 人类输入无差别**：`capture_all._thread_input` 用 `GetAsyncKeyState` / XInput 采集时无法区分；这是设计意图（数据集训练用）。不要试图 "过滤掉 bot 输入"。
- **CLI preview 的 `--game-path` 总是显示**：这是 `values_to_argv` 对 `path` 类型的特判（始终 emit）。若想改成"等于 default 时省略"，要改 `cli_schema.py:values_to_argv` 但会让用户不知道实际跑哪个游戏的 exe。
- **`Ctrl+C in console`** 退 main.py 时游戏进程不动 —— 这是 main.py 设计行为；GUI 关窗也是同样语义（CTRL_BREAK 让 main.py 优雅退）。
