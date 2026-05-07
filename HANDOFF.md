# Handoff: auto-play 接管检测 + GUI 启停体验改进

**Generated**: 2026-05-07 17:51 +0800
**Branch**: master（与 origin/master 同步，clean）
**Status**: Ready for Review —— 全部代码 commit + push（`74cf102`），headless sanity 全过；端到端实跑用户已验证 FF7R 游戏退出 + GUI toggle 路径"完美"，takeover detector 在真采集流程里的行为还需下一轮实测。

## Goal

为 unicap auto-play / GUI 这一轮做四件事：
1. 加"人类接管检测"——auto-play 模式下 3s 内有主动按键就暂停所有 inject（让人能随时接管）
2. 修 GUI Start 按钮在 main.py 跑着时无出口的问题（Start ↔ Stop toggle）
3. 修一系列 UX 小问题（video/pack 默认 game-dir、fps `0.00` 显示、Extra args 误导 placeholder）
4. 修游戏退出后 main.py 不退导致 Start 卡灰的问题 + QThread 销毁警告

## Completed

- [x] **新文件 `tools/auto_play/takeover.py:TakeoverDetector`**：后台 80ms 轮询 `GetAsyncKeyState`(profile.controls 键 + 鼠标 L/R/Middle，鼠标移动不算，gamepad 跳过，reserved_keys 排除)。bot 自身 inject 用 `backend._lock.acquire(blocking=False)` + `now - last_inject_at_mono < 150ms` grace 双重排除。3s 窗口。
- [x] **runner.py 接入 detector**：构造 + start/stop 跟 lifecycle；`_driver_loop` tick 入口 + `_attack_heartbeat_loop` inject 前都 `is_taken_over()` skip；stop log 加 `takeover=N` 计数
- [x] **watchdog.py 接入 detector**：新 `_taken_over_skip(source)` helper；short-window / long-window recovery + OCR dismiss-prompt inject 前都 gate；runner 把 detector 通过 `takeover_detector` 参数传给 watchdog 构造
- [x] **GUI: Start 按钮 toggle**（`unicap_gui/tabs/base_tab.py`）：`_apply_start_button_style(running)` 切换；不跑 = solid 绿 `▶ Start`；跑 = outline 红 `■ 停止`（透明背景 + 红边 + 红字 + hover 浅红）。点 stop 弹模态二次确认 → `CTRL_BREAK` + 5s 兜底 taskkill
- [x] **GUI: form 字段 running 时锁**：`_on_subprocess_started` → `self._form.setEnabled(False)`；`_on_subprocess_stopped` 恢复。dashboard / F8/F9 镜像按钮 / log / Stop 按钮**不在 form 内**，仍可操作
- [x] **GUI: `set_start_enabled` 与外部锁兼容**：running 时强制 enabled（stop 路径不该被 G-011 锁屏蔽）；idle 时让外部锁生效
- [x] **GUI: video/pack 自动默认 game-dir**：`unicap_gui/shared/settings.py` 加 `derive_game_dir_from_launch()`；`BaseTab._restore_settings` 末尾调新 hook `_apply_smart_defaults()`；VideoTab/PackTab 实现：`game_dir` 为空时从 launch 已保存 settings 派生 `<dataset_root>/<exe stem>`
- [x] **GUI: fps SpinBox 显示 "auto"**：`FlagSpec` 加 `special_value_text: str` 字段；`FlagForm` float editor 检测到时 `setMinimum(default)` + `setSpecialValueText`；video schema 的 `--fps` 设 `special_value_text="auto"`。CLI argv 行为不变（0 = default 不 emit）
- [x] **GUI: Extra args placeholder generic 化**：`cli_preview.py` 从 `--auto-play-debug`（仅 launch 认）改为 `（可选；空格分隔的额外 flag）`
- [x] **main.py: 游戏退出后自动停 main.py**：`cmd_launch` spawn 游戏后启 daemon thread `_watch_game_exit`；改用 exe-name polling（每 5s）+ **30s 启动 grace** 让 launcher → game PID handoff 完成；游戏不在 → `_thread.interrupt_main()` → `KeyboardInterrupt` → cmd_launch finally 清 Vulkan 后退出
- [x] **`tools/window_manager.py:is_process_alive_by_name`**：`tasklist /FI "IMAGENAME eq xxx.exe" /NH` 实现；检查失败保守返回 `True` 避免误杀
- [x] **fix: QThread 销毁警告**（`unicap_gui/shared/process.py`）：`_on_finished` 不再把 `_reader`/`_thread` 提前置 None；改 `reader.finished.connect(reader.deleteLater)` + `thread.finished.connect(thread.deleteLater)` 让 Qt event loop 在 thread 真退出后销毁；加 `thread.setObjectName("unicap-stdout-<subcommand>")`

## Not Yet Done

- [ ] **实跑端到端验证 takeover detector 在采集流程里**：本机 + GUI 跑 30 分钟 FF7R + auto-play，验证：
  - 不接管时正常注入（attack heartbeat / keep-alive tick / watchdog recovery 都跑）
  - 人手按 W 时 `[TAKEOVER]` log 出现 + 3s 内 `[AUTO-PLAY] tick:` 不出现 + 3s 后恢复
  - 鼠标挥动**不**触发 takeover（验证 mouse 移动不算）
  - watchdog static-frame 触发但人在玩时 `[WATCHDOG] short-window 触发但人在接管 — 跳过`
- [ ] **launch tab `_btn_redo_survey` 异常崩溃路径仍卡 disabled**（旧 handoff 遗留）：若子进程异常崩溃没走 stopped 信号，按钮卡 disabled。改成关联 `is_running` 而非 lifecycle 信号即可
- [ ] **dashboard `_attack_led` recovery 后卡橙**（旧 handoff 遗留）：`_on_recovery_active(False)` 不主动 reset，靠 attack pulse 自然覆盖；recovery 后长期无 attack 注入会卡橙
- [ ] **`scripts/verify_auto_play.py` 已坏**：还在 `from tools.auto_play import VLMDriver`（上一个 session 砍了 VLMDriver）。要修就把 VLMDriver import + 相关 case 删掉

## Failed Approaches (Don't Repeat These)

### 1. 直接 `proc.wait()` 监控游戏退出（已回退）

**尝试**：`_watch_game_exit` 第一版 `rc = proc.wait(); _thread.interrupt_main()`，proc 是 `subprocess.Popen([game_exe])` 返回的对象。

**失败**：FF7R / Steam 等用 launcher → game PID handoff（CLAUDE.md 早就记过 force_borderless_async 也踩过这个坑）：Popen 拿到的是 launcher 的 pid，launcher 启动真 game 后立刻退出 → `proc.wait()` 立刻返回 rc=0 → main.py 误以为游戏退了 → 自杀 → GUI Start 回绿。用户截图显示游戏还在跑 Start 已经回绿。

**修法**：改成按 exe basename `tasklist` polling 每 5s 一次 + **30s 启动 grace**。Grace 内即便 alive=False 也不退出（让 launcher 退场 + game 起来这段空窗）。

### 2. Stop 按钮 solid red 块 + 文字 `⏹ 停止 main.py`（已克制化）

**尝试**：第一版 toggle 用 `background: #c62828` solid + `⏹ 停止 main.py`。

**失败**：用户反馈"不合适"——大块红色太抢视觉焦点，跟左上 Tab / 表单争夺注意力。

**修法**：改 outline 风格（透明背景 + 红边 `2px solid #c62828` + 红字 + hover 浅红 `#fbe9e7`）+ 文字缩短到 `■ 停止`。视觉重量与绿色 Start 对等，仍明示警示。

### 3. SubprocessRunner `_on_finished` 直接把 Python ref None（已修）

**尝试**：reader.finished 触发后立刻 `self._reader = None; self._thread = None`，依赖 `thread.finished.connect(thread.deleteLater)` 自然清。

**失败**：用户启动后 console 报 `QThread: Destroyed while thread '' is still running`。Root cause：`_on_finished` 在 main thread queued event 里跑，但此时 worker thread 的 `quit()` slot **也是 queued 在 main thread**，还没执行；Python 提前 ref None → sip GC Python wrapper → C++ thread object 销毁但 thread 还在跑 event loop。

**修法**：不在 `_on_finished` 清 Python ref；改让 reader/thread 都 `connect(deleteLater)`，由 Qt event loop 在 thread 真退出后销毁底层 C++ 对象。下次 `start()` 用新 `QThread()` 覆盖旧 ref，旧 wrapper 那时已 safe。

### 4. Takeover 用"鼠标移动"作为接管信号（被用户否决）

**尝试**：方案讨论时倾向把 GetCursorPos diff 也算接管信号（玩家挥鼠标看视角）。

**失败**：用户明确否决——bot 自己的 mouse turn 也会引起 GetCursorPos diff，即便用 backend lock 排除也有 race；判定标准要严：只看键 + 鼠标按键。

**修法**：sample 集合限定为 `profile.controls.values()` 中的键 + 鼠标 L/R/Middle 按键；`mouse`（turn_axis）跳过；`gamepad_*` 跳过（GetAsyncKeyState 读不到手柄）。

## Key Decisions

| Decision | Rationale |
|----------|-----------|
| Takeover sample VK 从 `profile.controls` 派生 | 不同游戏键位差很多（ff7r 用 M dismiss_ui，doom 用 SHIFT 跑步等）；硬编码 W/A/S/D 不通用 |
| Takeover bot-self 排除用 `lock.acquire(blocking=False)` + grace | lock 处理 inject 期间，grace 处理 inject 完成后 OS 残留 KeyUp。两者结合避免 race |
| Watchdog 也尊重接管 | 人在玩 = 没卡 = 不需要 recovery；OCR dismiss-prompt 也别替人按 |
| Start ↔ Stop 用同一按钮 toggle | 比独立 Stop 按钮更省 UI 空间；颜色 + 文字明示模式；同位置避免误触（HANDOFF 此前删 big red Stop 的初衷） |
| Stop 弹模态二次确认 | `CTRL_BREAK` 是不可逆动作；防止用户误点把跑了一段的采集 session 中断 |
| 游戏退出检测改 polling（不用 proc.wait） | FF7R launcher → game PID handoff 让 Popen pid 失效；exe basename 是稳定标识 |
| 30s grace 写死 | 经验值（force_borderless_async 也用 30s）。grace 内即便 tasklist 看不到 exe 也不退出，让 launcher 退场 + game 启动这段空窗 |
| `_thread.interrupt_main()` 注入 KeyboardInterrupt | 让 cmd_launch 的 `except KeyboardInterrupt + finally` 走原本的 Vulkan 注册表清理路径，不绕过 cleanup |
| FlagSpec 加 `special_value_text` 字段 | 可复用：将来 `--capture-duration` 也想 0=`unlimited` 也能直接用 |

## Current State

**Working**:
- `git log` HEAD = `74cf102 feat: auto-play 接管检测 + GUI 启停体验改进`
- 工作树 clean（push 完 + 本 handoff 写完后才有这一个 modified）
- TakeoverDetector：sample VK 提取实测对（ff7r 9 个含 W/A/S/D/E/M/SPACE/mouse_L/R；doom_eternal 多 SHIFT；_default/batman_ak 含 ESC）；空跑 0.5s 不误报
- GUI 全 headless 验证：Start toggle 文字/样式切换 OK；form 跑时锁 / 停时解锁 OK；smart default `game_dir` 自动填 `D:\unicap_output\ff7remake_` OK；fps `setSpecialValueText("auto")` 显示 "auto"，setValue(30) 显示 "30.00"
- 用户实跑反馈："验证过完美"——FF7R 启动 launcher→game handoff 期间不假阳性，关游戏后 main.py 自动退、GUI Start 自动回 ▶

**Broken**: 无已知 broken。

**Uncommitted Changes**: 仅本 `HANDOFF.md`（即将由 `commit` skill 处理）。

## Files to Know

| File | Why It Matters |
|------|----------------|
| `tools/auto_play/takeover.py` | 全新 detector 模块；后台线程 + 排除 bot 自身 inject 的两道闸门 |
| `tools/auto_play/runner.py` | AutoPlayRunner 构造 detector + lifecycle；`_driver_loop` / `_attack_heartbeat_loop` 入口 gate |
| `tools/auto_play/watchdog.py` | `_taken_over_skip(source)` helper；short/long-window recovery + OCR inject 都 gate |
| `tools/auto_play/input_backend.py` | `last_inject_at_mono` 是 detector 的 grace 判据；`_lock` 是 try-acquire 排除 bot 自身的依据 |
| `tools/window_manager.py` | 新暴露 `is_process_alive_by_name`；main.py `_watch_game_exit` 依赖它 |
| `main.py` | `cmd_launch` 中 `_watch_game_exit` daemon thread + 30s grace polling；`_thread.interrupt_main` 触发 KeyboardInterrupt 走 finally 清 Vulkan |
| `unicap_gui/tabs/base_tab.py` | `_apply_start_button_style(running)` toggle；form `setEnabled` lock；`_apply_smart_defaults()` hook；`_on_start_button_clicked` dispatcher（弹模态 + stop） |
| `unicap_gui/shared/settings.py` | `derive_game_dir_from_launch()` —— video/pack tab 智能默认源头 |
| `unicap_gui/shared/cli_schema.py` | `FlagSpec.special_value_text` 字段；改 main.py argparse 时仍要这边同步 |
| `unicap_gui/widgets/flag_form.py` | float editor 处理 `special_value_text`：`setMinimum(default)` + `setSpecialValueText` |
| `unicap_gui/shared/process.py` | SubprocessRunner deleteLater 模式；`thread.setObjectName` 让 debug 输出可读 |
| `profiles/*.yaml` | 影响 takeover sample VK；改 controls 时 detector 自动跟随 |

## Code Context

### TakeoverDetector 主循环（`tools/auto_play/takeover.py`）

```python
def _loop(self) -> None:
    while not self._stop_evt.is_set():
        self._stop_evt.wait(self._sample_period_s)
        if self._stop_evt.is_set():
            break

        # 1) bot inject 中？lock 拿不到说明正在 inject。
        got = self._backend._lock.acquire(blocking=False)
        if not got:
            continue
        self._backend._lock.release()

        # 2) bot 刚 inject 完？OS 还在 propagate KeyUp，跳过。
        if (time.monotonic() - self._backend.last_inject_at_mono
                < self._bot_inject_grace_s):
            continue

        # 3) sample 关键键 — 任何高电平 → 标记接管
        for vk in self._sample_vks:
            if _user32.GetAsyncKeyState(vk) & 0x8000:
                self._last_human_at = time.monotonic()
                # ... log（限频）
                break

def is_taken_over(self) -> bool:
    return (time.monotonic() - self._last_human_at) < self._grace_s
```

### Sample VK 提取规则（不同 profile 不同，自适应）

```python
# tools/auto_play/takeover.py:_build_sample_vks
for ctrl_value in profile.controls.values():
    ctrl_lower = ctrl_value.lower()
    if ctrl_lower in _MOUSE_BTN_VKS:        # mouse_left/right/middle
        vks.add(_MOUSE_BTN_VKS[ctrl_lower])
    elif ctrl_lower == "mouse":             # turn_axis: mouse — 鼠标移动不算
        continue
    elif ctrl_lower.startswith("gamepad_"): # GetAsyncKeyState 读不到手柄
        continue
    else:
        vks.add(_resolve_vk(ctrl_value))    # W/SPACE/M/...

# baseline 兜底（profile 万一没列）
vks.add(VK_LBUTTON); vks.add(VK_RBUTTON)
vks -= reserved_vks                          # F8/F9 永远不算
```

### Runner gate（`tools/auto_play/runner.py`）

```python
# _driver_loop tick 入口
if self._recovery_active_evt.is_set():
    self._stop_evt.wait(0.1); continue
if self._takeover.is_taken_over():
    self._stop_evt.wait(0.2); continue          # ← 加的

# _attack_heartbeat_loop inject 前
if self._recovery_active_evt.is_set(): ...
if self._takeover.is_taken_over():
    self._stop_evt.wait(0.5); continue          # ← 加的
self._backend.inject(self._attack_action)
```

### Watchdog gate（`tools/auto_play/watchdog.py`）

```python
def _taken_over_skip(self, source: str) -> bool:
    if self._takeover is None or not self._takeover.is_taken_over():
        return False
    log.info("[WATCHDOG] %s 触发但人在接管 — 跳过", source)
    return True

# 三处调用：
# - short-window static recovery 前: _taken_over_skip("short-window")
# - long-window static recovery 前:  _taken_over_skip("long-window")
# - OCR dismiss-prompt inject 前:    _taken_over_skip(f"OCR/{key}")
```

### 游戏退出 watcher（`main.py:cmd_launch`）

```python
proc = subprocess.Popen([str(game_exe)], cwd=str(game_dir), env=env)

def _watch_game_exit(exe_basename: str) -> None:
    from tools.window_manager import is_process_alive_by_name
    grace_until = time.monotonic() + 30.0
    while True:
        time.sleep(5.0)
        if is_process_alive_by_name(exe_basename):
            continue
        if time.monotonic() < grace_until:
            continue                         # ← 关键：grace 内不退
        print(f"\n[GAME-EXIT] 找不到 {exe_basename} ...", flush=True)
        _thread.interrupt_main()
        return
threading.Thread(target=_watch_game_exit, args=(game_exe.name,),
                 daemon=True, name="game-exit-watcher").start()
```

### Start 按钮 toggle dispatcher（`unicap_gui/tabs/base_tab.py`）

```python
def _on_start_button_clicked(self) -> None:
    if self._runner.is_running():
        ret = QMessageBox.question(
            self, "停止 main.py",
            f"将向 {self._schema.name} 子进程发 CTRL_BREAK ...",
            QMessageBox.Yes | QMessageBox.No, QMessageBox.No,
        )
        if ret != QMessageBox.Yes: return
        self._runner.stop(timeout_s=5.0)
        return
    self._on_start_clicked()  # 原启动流程

def _on_subprocess_started(self, cmd):
    self._apply_start_button_style(running=True)
    self._btn_start.setEnabled(True)            # stop 路径永远可点
    self._form.setEnabled(False)                # ← lock form
    ...

def _on_subprocess_stopped(self, rc):
    self._apply_start_button_style(running=False)
    self._btn_start.setEnabled(True)
    self._form.setEnabled(True)                 # ← unlock form
    ...
```

### QThread cleanup pattern（`unicap_gui/shared/process.py`）

```python
self._thread = QThread()
self._thread.setObjectName(f"unicap-stdout-{subcommand}")
self._reader = _StdoutReader(self._proc)
self._reader.moveToThread(self._thread)
self._thread.started.connect(self._reader.run)
self._reader.line.connect(self._on_line)
self._reader.finished.connect(self._on_finished)
self._reader.finished.connect(self._thread.quit)
# ↓ 关键：不在 _on_finished 提前 ref None；让 Qt event loop 真 thread 退出后销毁
self._reader.finished.connect(self._reader.deleteLater)
self._thread.finished.connect(self._thread.deleteLater)
self._thread.start()

def _on_finished(self, rc):
    self._proc = None
    # 不动 _reader / _thread 的 Python ref
    self.stopped.emit(rc)
```

## Resume Instructions

### 实跑端到端验证 takeover（重点 —— 本 session 没在真采集流程里跑过）

```powershell
uv sync --extra gui
uv run --with PySide6 python -m unicap_gui

# 1) 在 GUI 选 ff7r profile + game-path 指向 FF7R exe，--auto-play 勾选，点 Start
# 2) 进游戏，按 F8 开始采集
# 3) 观察 console 5 分钟：应当看到
#    [AUTO-PLAY] tick: keep-alive → ...   每 1s
#    [ATTACK-HB] 注入 attack#N            每 12s
#    （不接管时） 不应有 [TAKEOVER] log
# 4) 中途人手按 W 走两步：应当看到
#    [TAKEOVER] 检测到主动按键 vk=0x57 #1 — 暂停 auto-play 3.0s
#    紧接 3 秒内 NO [AUTO-PLAY] tick / [ATTACK-HB]
#    3 秒后恢复 [AUTO-PLAY] tick
# 5) 中途挥鼠标看视角（不点鼠标按键）：不应触发 takeover（鼠标移动不算）
# 6) 让 watchdog 触发（卡墙 10 秒）但同时人手按 S：应当看到
#    [WATCHDOG] short-window 触发但人在接管 — 跳过
# 7) 关游戏：5s 内 console 应有
#    [GAME-EXIT] 找不到 ff7remake_.exe 进程 — main.py 自动停止
#    [VULKAN] HKCU 注册表已清理      （Vulkan 路径才有）
#    GUI Start 按钮自动回到 ▶ Start，form 解锁
```

### 改 game-path 跑新游戏的完整流程

```
1. 现状：Start 灰 / 红「■ 停止」、form 锁着
2. 点「■ 停止」→ 弹确认 → Yes → main.py CTRL_BREAK 退出 → GUI 看到 stopped
3. Start 自动回绿 ▶ + form 解锁
4. 改 --game-path 选新 exe → CLI preview 实时刷新
5. 点 ▶ Start → 新一轮 main.py
```

### Headless smoke（CI / 远程开发用，无需 X server）

```powershell
PYTHONIOENCODING=utf-8 uv run python -c "
import os; os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
from PySide6.QtWidgets import QApplication
app = QApplication.instance() or QApplication([])
from unicap_gui.app import MainWindow
mw = MainWindow()
launch = mw._launch
launch._on_subprocess_started(['fake'])
assert launch._btn_start.text() == '■ 停止'
assert launch._form.isEnabled() is False
launch._on_subprocess_stopped(0)
assert launch._btn_start.text() == '▶ Start'
assert launch._form.isEnabled() is True
print('toggle + form-lock OK')

# fps SpinBox specialValueText
video = [mw._tabs.widget(i) for i in range(mw._tabs.count())
         if mw._tabs.tabText(i) == '生成视频'][0]
fps_ed = video._form._editors['fps']
assert fps_ed.text() == 'auto', fps_ed.text()
print('fps auto display OK')

# takeover sample VK
from tools.auto_play.takeover import _build_sample_vks
from tools.auto_play.profile import load_profile
ff7r = load_profile('ff7r', fallback=False)
vks = _build_sample_vks(ff7r)
assert 0x57 in vks and 0x01 in vks      # W + LBUTTON
assert 0x77 not in vks and 0x78 not in vks  # F8/F9 排除
print('takeover sample VK OK')
"
```

## Setup Required

- Windows 11（GUI 用 SendInput；GetAsyncKeyState 也仅 Windows）
- Python 3.13+ (`uv`)
- PySide6 ≥ 6.6（`uv sync --extra gui`）
- ViGEm Bus 内核驱动（`auto-play` extra；不装会 fallback 键鼠）
- 可选：Windows.Media.Ocr（`pip install "unicap[auto-play-ocr]"` 让 watchdog OCR arm 工作）
- 环境变量：无（`.env` 已在前 session 删除）

## Edge Cases & Error Handling

- **Takeover 在 bot inject hold 期间检测到键？** bot inject `_inject_key` press 模式持有 lock 的整个 `down → sleep(duration_ms) → up` 时长；detector `_lock.acquire(blocking=False)` 拿不到 → skip 本轮。+ inject 完成后 150ms grace 再过滤 OS 残留 KeyUp。两道闸门覆盖。
- **Profile 没有任何键（只 gamepad_*）？** `_build_sample_vks` 仍兜底加 `VK_LBUTTON / VK_RBUTTON`，detector 不会无条件返回 False。
- **launcher → game 实际超过 30s 才接管显示？** `_watch_game_exit` 30s grace 后第 31s polling 看不到 exe 就退。极端慢 launcher（DRM 联网验证）需要把 grace 调大；当前写死 `grace_until = monotonic() + 30.0`，要改在 main.py 加 CLI flag 暴露。
- **用户在 main.py 跑期间关 GUI 窗口？** MainWindow.closeEvent 弹模态确认 → Yes → `runner.stop(timeout_s=5.0)` → 5s 优雅 / 兜底 taskkill。Stop 按钮路径与关窗路径都走同一个 stop()。
- **Start 时弹模态 stop 期间用户多点几下？** Stop 按钮在 stop() 期间会被同步阻塞 5s（GUI 主线程 wait），用户多点会进 event queue 但因为按钮已经 setEnabled 在 stop 完成前不变，多次点击 → 多次 stop → 第二次 stop 调用看到 is_running=False → no-op return。
- **launcher pid 退出但 game 还没起，用户点 GUI Stop？** Stop 走 GUI 路径独立于 game watcher：`runner.stop` 直接对 main.py 子进程 send CTRL_BREAK，不依赖 game 状态。OK。
- **`tasklist` 命令找不到（中文 Windows 偶见）？** `is_process_alive_by_name` catch `subprocess.SubprocessError` / `OSError` → 返回 True 保守不退出。

## Warnings

- **改 main.py argparse 时**：必须同步改 `unicap_gui/shared/cli_schema.py`，否则新 flag 不会显示在 GUI / 不会传给 CLI。
- **TakeoverDetector 触动 `backend._lock` 是私有属性访问**：当前 backend 没暴露 `try_lock()` 公开 API，detector 直接 `_lock.acquire(blocking=False)`。如果将来 InputBackend 重构 lock 实现，detector 也要跟改。
- **`_thread.interrupt_main()` 在 `time.sleep` 中触发 KeyboardInterrupt 是 OS 行为依赖**：Windows console subprocess 上验证可靠；如将来跑非 console（pythonw / GUI 启不带 console），interrupt_main 仍会工作但没法看到 print。
- **30s game launch grace 是经验值**：FF7R / Steam / DOOM Eternal 实测够用；其它 launcher（Epic / GOG） 没全测；如真踩到再调成 CLI flag。
- **Stop 按钮 outline 风格在 dark theme 下文字 `#c62828` 红色对深灰背景仍清晰**；如果将来加暗色主题切换，注意 stylesheet 用 palette() 而不是写死颜色。
- **`scripts/verify_auto_play.py` 已坏但本 session 没修**：`from tools.auto_play import VLMDriver` 上一个 session 砍 VLM 时遗留，HANDOFF 之前没记。下次想跑 verify 之前先修这个 import。
- **HANDOFF.md 已被 `ebc232d` commit 过一次（这是上一个 session 的内容），现在要再被这次 handoff 覆盖**：git history 里能拿回旧 handoff 的全文。
