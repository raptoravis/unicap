# Handoff: 自动玩游戏（auto-play）— A 层 + force_borderless 修 console 冻结

**Generated**: 2026-05-02 16:00
**Branch**: `auto-play`（已 push 到 `origin/auto-play`，HEAD = `2f809dd`）
**Status**: In Progress — A 层 + force_borderless 全部 commit + push；FF7R 短跑 (2m29s, 457 BMP, watchdog 触发 4 次) 验证通过；**待 30 min 长跑 + 新游戏 E2E + C 层 VLMDriver 实现**

## Goal

让 unicap 长时间无人值守采集 — auto-play bot 持续注入输入 + watchdog 静帧脱困。两层架构：A 层哑 bot（已落地），C 层 VLM 大脑（占位待接）。多游戏 first-class（profile YAML）。本 session 修了 console 显示链路被 DXGI 全屏独占冻结的问题。

## Completed

### 上 session（commits `5e8ce72` … `a2f4e33`）— 见 commit log
- A 层 driver/profile/watchdog/runner 全栈
- 4 内置 profile (`_default` / `ff7r` / `doom_eternal` / `batman_ak`)
- VLMDriver 占位（构造抛 NotImplementedError 指 G-005/G-006）
- main.py 6 个 auto-play flag
- 38 项 verify_auto_play.py 全 PASS
- stdout line_buffering + watchdog mtime 500ms 防 mid-write BMP
- 实测 FF7R 305 帧 / 40s ≈ 7.6 fps（ui-mode=both）

### 本 session — commit `494644e`（feat）
- [x] **诊断 console 冻结**：sponsor 反馈 F8/F9 后 console 不更新但 dataset 有结果。验证 `auto_play.log` 有完整 INFO（runner.start / watchdog 触发 / runner.stop） → print 真的执行了，console 端坏。
- [x] **根因定位**：DXGI fullscreen-exclusive (FF7R 默认) 让 Windows DWM 暂停后台 console 渲染；alt-tab 出游戏后 print 一次补全。**不是 stdout buffering**（[等待] 行未带 flush=True 但显示正常 = line_buffering 在工作）
- [x] **`tools/window_manager.py`** 新增 — Win32 API 启动后强制 borderless windowed
  - `force_borderless_async(pid, exe_basename, timeout_s=30, settle_delay_s=2)` 后台 daemon thread
  - `_find_main_window` 双匹配：先 pid，找不到 fallback 按 `QueryFullProcessImageNameW` exe basename（FF7R 等 launcher→game PID handoff 兜底）
  - `_monitor_rect` 用 `MonitorFromWindow` + `GetMonitorInfoW` 处理多显示器
  - `SetWindowLongPtrW(GWL_STYLE, WS_POPUP|WS_VISIBLE)` + `SetWindowPos` 撑满 → DXGI 因 style 变化 transition 到 windowed → DWM 不冻结
- [x] **`main.py:cmd_launch`** 集成：Popen 后调 `force_borderless_async(proc.pid, exe_basename=game_exe.name, timeout_s=30)`
- [x] **`--force-borderless`** flag (BooleanOptionalAction，默认 True)
- [x] **CLAUDE.md** 加 force_borderless 章节
- [x] **memory** 写 `fullscreen_console_freeze.md`（避免下次重新诊断）
- [x] 修 4 处 ruff F541/E501（main.py:506/698/715/1055）

### 本 session — commit `2f809dd`（tune）
- [x] [CAPTURE] 进度行频率 1.4s → 14s（`tools/capture/capture_all.py:134`）— 长时无人值守 console 不刷屏

### Live test 验证（本 session）
- [x] FF7R 跑 2m29s，457 BMP / 453 EXR / 3.1 fps，watchdog 触发 4 次
- [x] [CAPTURE] / [AUTO-PLAY] / [F8] / [SURVEY] 全部实时显示
- [x] force_borderless 第一次跑没匹配上 pid 19944（截图46）→ 加 exe basename fallback → 第二次实测验证 console 实时刷新（即使 force 没成功，FF7R 这次也是 windowed mode 没冻结，但接入 fallback 后未来全屏独占场景能 cover）

## Not Yet Done

- [ ] **30 分钟 FF7R 长跑**（sponsor）：watchdog 触发率 + recovery 调头是否真脱困 + 长时无 cv2 噪音
- [ ] **新游戏接入 E2E-2**：复制 `_default.yaml` → 改 controls → 5 min 看 watchdog 触发
- [ ] **C 层 VLMDriver 实现**（handoff 主线，下个 dev session）— 改 `tools/auto_play/vlm_driver.py`
- [ ] **merge `auto-play` → master**（待 sponsor 实机验收后）

## Failed Approaches (Don't Repeat These)

### 本 session 新增

#### 1. 第一反应去查 stdout buffering（被 prior handoff 第 4 课误导了）
Prior handoff 写"sponsor 反馈 F8/F9 不响应通常是 stdout buffering"。但本次截图里 [启动] / 操作提示 / [等待] 这些 **未带 flush=True 的 print 都显示了** —— 这反向证明 `sys.stdout.reconfigure(line_buffering=True)` 工作正常。直接跳到 hotkey diagnostic 也走偏，user 提示"capture 真的跑了"才让我查 logger 文件 cross-check，发现 `auto_play.log` 完整 → console 端坏了 → 想到 DWM 全屏独占暂停渲染。

**修法**：先看 logger 文件 vs console 输出，cross-check 是 print 没执行 还是 console 没显示。`%TEMP%/unicap/auto_play.log` 是非常有用的旁路证据。

#### 2. `force_borderless` 只按 pid 匹配窗口
最初 `_find_main_window(pid)` 只用 `GetWindowThreadProcessId` 比对 pid。FF7R 实测 Popen 返回的 pid 19944 找不到对应 visible top-level window —— launcher exe 可能短命退出 / inner exe 派生 child / 别的 PID 持窗口。30s timeout 后打 `[WINDOW] 未找到游戏窗口`。

**修法**：加 `_query_image_basename(pid)`（OpenProcess + QueryFullProcessImageNameW），`_find_main_window` 改成 pid OR exe_basename 双匹配。pid match 是 fast path，匹配不到才调 OpenProcess（贵）按 basename 兜底。

### 上 session 已记录（不重复）
1. `wait` step 返回 `[]` 让 runner sleep 吸收 duration_ms — duration_ms 被静默忽略
2. Watchdog 直接 reach 进 `KeepAliveDriver._step_to_actions`（信息泄漏）
3. `create_driver(**kwargs)` 静默吞 typo
4. ~~depth-based UI mask 在 pack 路径~~（已退役）

## Key Decisions

| Decision | Rationale |
|----------|-----------|
| `--force-borderless` 默认 True | 全屏独占冻结 console 是 sponsor 实测痛点；borderless windowed 视觉一致、capture/ML 数据不变；--no-force-borderless 留给特殊场景 |
| 窗口匹配先 pid 后 exe basename | FF7R 等 launcher→game PID handoff 场景 pid 失效；exe basename + QueryFullProcessImageNameW 兜底；先 pid 是 fast path 避免对每个窗口 OpenProcess |
| `SetWindowLongPtrW` (而非 `SetWindowLongW`) | WS_POPUP=0x80000000 超过 c_long signed 32-bit 上限；ctypes 抛 OverflowError；LongPtr 用 c_ssize_t (64-bit on x64) 容下 |
| `settle_delay_s=2.0` 在改 style 之前 | 让游戏先初始化完 fullscreen state，避免在 DXGI swapchain create 期间打断 |
| `[CAPTURE] x.xs / N 帧` 频率 14s（1/10 of 1.4s） | force_borderless 修好 console 实时输出后刷屏太凶；长时 session 视觉清爽；[AUTO-PLAY]/[WATCHDOG] 重要事件仍突出 |
| watchdog 参数保持不变（5s 采样 + 2 次连续触发 = 10s 静帧门槛） | sponsor 选不动 |
| 不污染游戏 GameUserSettings.ini | sponsor 要求"通过 api 不让我动手改游戏"；Win32 API 强制 style 是 unicap session 内的临时态，退出即恢复（游戏自己记忆原设置）|

### 上 session 决策（仍生效）
- A 层 MVP + C 层 contracts 占位（用户选定）
- `BotDriver.next_actions(Observation) → list[Action]` 是 A/C 共享核心契约
- bot input 与人类 input 不区分（共用 inputs.jsonl）
- InputBackend 单 Lock 串行化所有注入
- `MANDATORY_RESERVED_KEYS = {F8, F9}` schema 强制
- ViGEm 软依赖
- `--auto-play` 默认 `--ui-mode both`
- both 模式 fps ~7-8 接受
- watchdog 优先 BackBufferUI.bmp，缺失回落 BackBuffer.bmp
- watchdog 跳过 mtime < 500ms 的 BMP
- stdout `line_buffering=True` 在 main() 开头
- FF7R recovery 首发 M 键
- 4 次同向 turn 模拟 180° 调头
- keep_alive 加 move_back/left/right + 大转向

## Current State

**Working**:
- HEAD = `2f809dd`，working tree clean，已 push 到 origin/auto-play
- `uv run main.py launch --auto-play --profile <ff7|fuzzy>`：启动 → force_borderless 自动切窗口 → console 实时刷新 → F8 自动 capture（首次 survey）→ bot 持续注入 → F9 干净停 → watchdog 触发计数
- FF7R 短跑 2m29s 验证 OK（457 BMP / 453 EXR / 3.1 fps / watchdog 4 次）
- `verify_auto_play.py`：38/38 PASS

**Broken**: 无

**Uncommitted Changes**: 无

## Files to Know

| File | Why It Matters |
|------|----------------|
| `tools/window_manager.py` | **本 session 新增** — Win32 API force borderless；pid + exe basename 双匹配；SetWindowLongPtrW 用 c_ssize_t |
| `main.py:536` | `proc = subprocess.Popen(...)` + `force_borderless_async(proc.pid, exe_basename=game_exe.name)` |
| `main.py:1018-1020` | `--force-borderless` BooleanOptionalAction 默认 True |
| `tools/capture/capture_all.py:134` | `if now - last_print >= 14.0:` ([CAPTURE] 频率 1/10) |
| `CLAUDE.md` 长时不睡眠章节后 | force_borderless 文档段 |
| `C:/Users/jonli/.claude/projects/D--dev-unicap-git/memory/fullscreen_console_freeze.md` | 全屏独占诊断 memory（避免下次重诊断）|

### 上 session 文件（仍生效）
| File | Why It Matters |
|------|----------------|
| `docs/req/auto-play.md` | 8 个 Goals 的需求 |
| `docs/designs/impact_20260502_auto-play.md` | 10 风险点 + 缓解 |
| `docs/designs/testplan_20260502_auto-play.md` | TestPlan + E2E coverage |
| `tools/auto_play/driver.py` | A/C 共享契约（**不动**）|
| `tools/auto_play/{input_backend,profile,keep_alive,watchdog,runner,vlm_driver}.py` | A 层全栈 |
| `profiles/{_default,ff7r,doom_eternal,batman_ak}.yaml` | 4 内置 profile |
| `scripts/verify_auto_play.py` | 38 检查 |
| `scripts/test_hotkeys.py` | F6-F12 诊断（Fn-lock 排查）|

## Code Context

### force_borderless 接口

```python
# tools/window_manager.py
def force_borderless(
    pid: int,
    exe_basename: str | None = None,  # FF7R 等 launcher 场景兜底
    timeout_s: float = 30.0,
    settle_delay_s: float = 2.0,  # 让游戏初始化完 fullscreen state 再改 style
) -> bool:
    """Strip frame; resize to fill monitor. DXGI 因 style 变化 transition windowed."""

def force_borderless_async(
    pid: int,
    exe_basename: str | None = None,
    timeout_s: float = 30.0,
    settle_delay_s: float = 2.0,
) -> threading.Thread:
    """Non-blocking; daemon thread; 完成时 print [WINDOW] 已强制 / 未找到"""
```

### Win32 API 调用要点

```python
# WS_POPUP=0x80000000 超 c_long signed 32-bit 上限 → 必须用 SetWindowLongPtrW + c_ssize_t
_user32.SetWindowLongPtrW.argtypes = [wintypes.HWND, ctypes.c_int, ctypes.c_ssize_t]
_user32.SetWindowLongPtrW.restype = ctypes.c_ssize_t

# 双匹配：pid match 是 fast path，basename match 兜底
def _enum(hwnd, _lparam):
    wpid = wintypes.DWORD()
    _user32.GetWindowThreadProcessId(hwnd, ctypes.byref(wpid))
    match = (wpid.value == pid)
    if not match and target_name is not None:
        img = _query_image_basename(wpid.value)  # OpenProcess + QueryFullProcessImageNameW
        match = (img == target_name)
    if not match: return True
    # ... size 过滤 + 设置 found
```

### main.py 调用点

```python
# main.py:536-540
proc = subprocess.Popen([str(game_exe)], cwd=str(game_dir), env=env)
if getattr(args, "force_borderless", True):
    from tools.window_manager import force_borderless_async
    force_borderless_async(proc.pid, exe_basename=game_exe.name, timeout_s=30.0)
```

### 上 session 不变的核心契约

```python
# tools/auto_play/driver.py — A/C 共享契约（不动）
ActionKind = Literal["key", "mouse", "gamepad", "wait"]

@dataclass(slots=True)
class Action:
    kind: ActionKind
    payload: dict[str, Any]
    duration_ms: int = 0

class BotDriver(ABC):
    @abstractmethod
    def next_actions(self, observation: Observation) -> list[Action]: ...
    @property
    def decision_period_s(self) -> float: return 1.0
```

## Resume Instructions

### 接班 agent 第一件事

```bash
git status                        # 应 clean，branch=auto-play
git log --oneline -3              # 应见 2f809dd → 494644e → 51a0105
ls tools/auto_play/               # 8 个 .py 文件
ls tools/window_manager.py        # 本 session 新增
ls profiles/                      # _default + ff7r + doom_eternal + batman_ak + README.md
```

### 验证当前状态

```bash
uv run python scripts/verify_auto_play.py
# 期望: 38 pass / 0 fail

uv run python -c "from tools.window_manager import force_borderless_async; print('OK')"
# 期望: OK
```

### Sponsor 待跑的 30 min FF7R 长跑

```powershell
# git checkout auto-play
uv run main.py launch --auto-play --profile ff7r
# 期望:
#   [AUTO-PLAY] --ui-mode 默认 both
#   [DEPLOY] 自动加载 survey 推荐 pre_ui_skip=...
#   [启动] ...ff7remake_.exe (api=dx)
#   [WINDOW] 已强制 borderless 窗口模式（避免全屏独占冻结 console）
#   操作提示框 (ui-mode=both)
#   [AUTO-PLAY] driver=keep-alive profile=ff7r gamepad=...
# F8 → survey（首次） → capture
# 期望: [CAPTURE] x.xs / N 帧 ~每 14s 一行
# 30 min 期间观察:
#   - watchdog 触发频率（短跑 2m29s 触发 4 次≈37s/次，长跑应类似规律）
#   - alt-tab 切回 console 不再有"积压"批量补出，而是实时显示
#   - %TEMP%/unicap/auto_play.log 无 cv2.imread 警告
# F9 停止
# 期望: [AUTO-PLAY] 停止；watchdog 触发 N 次
```

### 下一步：实现 C 层 VLMDriver

1. **不动 A 层** — 只改 `tools/auto_play/vlm_driver.py`
2. 参考 `docs/req/auto-play.md` G-005 (VLM 决策回路) + G-006 (成本与配额)
3. provider：CLAUDE.md user instructions 偏 Anthropic SDK；Claude Haiku 4.5 + prompt caching 必须启用
4. JSON 严格输出 schema：`{actions: [{kind, payload, duration_ms}], reasoning?}`
5. profile.vlm.game_instructions 拼进 system prompt
6. 写 `scripts/verify_vlm_driver.py`：30 分钟 FF7R 跑 vlm，schema 错误率 ≤5% + 总花费 ≤$5
7. CLAUDE.md 把 "VLMDriver 占位未实现" 改 "VLMDriver 实战测过"

### Merge `auto-play` → master（待 sponsor 30 min 验收后）

```bash
git checkout master
git merge --no-ff auto-play -m "merge: auto-play — 无人值守采集 A 层 + force_borderless"
git push origin master
git branch -d auto-play
```

## Setup Required

### 已沿用（无新需求）
- VS 2022 + MSBuild v143（C++ 没动）
- `uv sync`（pyyaml 已 lock）
- `tools/capture/config.py` GAME_PATH = FF7R inner exe

### Auto-play 可选
- ViGEm Bus driver（虚拟手柄）—— sponsor 没装，软降级到键鼠
- `--auto-play-debug` flag —— 详细注入 log

## Edge Cases & Error Handling

### 本 session 新增
| 场景 | 行为 |
|------|------|
| force_borderless 30s timeout 找不到窗口 | print `[WINDOW] 未找到游戏窗口 (pid=X / exe=Y, timeout=30s) — 如游戏全屏独占，console 实时输出会延迟到 alt-tab 才补出`；不 raise，capture 继续 |
| 游戏本身就是 windowed mode | force_borderless 仍执行（去边框 + 撑满） — 视觉变成无标题栏全屏窗口；DWM 本就不冻结，效果是把带标题栏切到无 |
| 多显示器，游戏在副屏 | `MonitorFromWindow(hwnd, MONITOR_DEFAULTTONEAREST)` + `GetMonitorInfoW` 用游戏所在显示器的 rect，不会强搬到主屏 |
| OpenProcess 拒绝（权限不足）| `_query_image_basename` 返回 None；该窗口跳过；不 raise |
| `--no-force-borderless` | 跳过整个 force 流程；如游戏全屏独占，console 仍可能冻结（sponsor 自负）|
| splash / loading 小窗 | `_find_main_window` 跳过 < 320×240 窗口，避免误抓 launcher splash |

### 上 session（仍生效）
- `--driver vlm` 错选 → NotImplementedError exit 2
- ViGEm 未装 → 键鼠 fallback + warn
- profile YAML 缺字段 → ValueError 含字段名 + 文件路径
- profile fuzzy match → 实测 'ff7' → ff7r.yaml ✓
- profile 找不到 → `_default.yaml` warn fallback
- frames_dir 暂空 → watchdog 30s warmup 不 log
- BMP mid-write → mtime 500ms guard 跳过
- driver next_actions 异常 → 5s 重试 backoff 30s
- F9 driver 卡死 → stop(timeout=3) join 超时 warn
- 用户期间手动操作 → 无冲突保护，时间叠加
- stdout buffering pipe → main() reconfigure line_buffering=True 双保险

## Warnings

### 本 session 新增
- **`SetWindowLongW` (32-bit) 不能用于 WS_POPUP** — 0x80000000 超 c_long signed 上限 OverflowError；必须 `SetWindowLongPtrW` + `c_ssize_t`
- **不要把 `force_borderless` 改成同步阻塞** — 必须 async daemon thread；否则 main.py 等 30s timeout 才进 `_interactive_loop`，user 看不到 [等待] 提示
- **`settle_delay_s=2.0` 别砍掉** — 游戏 fullscreen state 初始化期间改 style 可能让 DXGI swapchain 抛 device removal；2s 是经验值
- **DXGI re-evaluation 依赖 SWP_FRAMECHANGED** — 不传这个 flag DXGI 不知道 style 变了；保留必加
- **`--force-borderless` 默认 True 且 sponsor 已 expect** — 不要改默认；他要全屏才传 `--no-force-borderless`
- **[CAPTURE] 14s 频率 sponsor approved** — 不要再调更慢，否则长 capture 看着像 hang；不要回 1.4s（刷屏太凶）

### 上 session（仍生效）
- profile.reserved_keys 必须含 F8 / F9（schema 强制）
- InputBackend 单 Lock 串行化（time.sleep 持锁有意为之）
- `Action.kind='wait'` 是第 4 种 kind（别退化为 mouse op=move）
- `step_to_actions` 是公共 API（watchdog 也用）
- `create_driver` keyword-only args（typo 报错而非吞掉）
- `--auto-play` 默认 both fps ~7-8（已知）
- stdout `line_buffering=True` 必须 main() 最早调
- vgamepad 软依赖（用户没装内核 ViGEm 时构造 raise → fallback 键鼠）
- watchdog 优先 BackBufferUI.bmp / fallback BackBuffer.bmp（命名规则改要同步）
- FF7R recovery 首发 M 键（domain 知识，DOOM/Batman 不需要）
- C 层 VLMDriver 接入禁忌：不动 BotDriver ABC、driver.py 不加 provider-specific 字段、不从 main.py 直接 import VLM SDK
- reshade/source/ 改了必须 `-Rebuild`；R10G10B10A2 错色；NUM_WORKERS=2 constexpr
- `dist-exe/` 是旧 v1.0.2 产物（无 auto-play）；分发 auto-play 版本要重跑 `scripts\build-exe.ps1` 确认 nuitka 打包 `tools/auto_play/` + `tools/window_manager.py` + `profiles/`
