# Handoff: auto-play 卡墙 / 傻站 / 卡菜单 / 缺挥刀 系列修复

**Generated**: 2026-05-07
**Branch**: `master` (HEAD = `c458ff0`, in sync with `origin/master`)
**Status**: ✅ 三组修复已 ship 到 master，等下一轮 FF7R 实跑反馈

## Goal

一整轮基于 sponsor 实跑 FF7R 截屏 + `auto_play.log` 诊断的连续修复：
让 vlm 驱动下的 bot **不再卡墙、不再傻站、不会被自己推进菜单、并产生攻击动作样本**。

## Completed（已 ship 到 master，3 个 commit）

`c458ff0 feat(auto-play): 加 attack-diversity heartbeat + VLM prompt 探索时挥刀规则`
- [x] VLM prompt "Open exploration" 拆 recipe 1 (70% 纯走) + recipe 2 (30% 走+左键) + Attack-diversity rule
- [x] runner 加 background **attack heartbeat thread** 每 12s 注入 `profile.controls.attack`（FF7R = mouse_left），不依赖 VLM 输出
- [x] `_build_attack_action()` 跨游戏 portable（mouse_*/gamepad_*/任意 vk → 对应 Action）

`a3fffca fix(auto-play): 杜绝 recovery 自开菜单 + VLM menu-key 硬规则 + escalation`
- [x] `profiles/ff7r.yaml` recovery 100% 纯 movement —— 末尾 `dismiss_ui (M)` 整段删除（M 在 gameplay 中=打开 Map 副屏 → VLM 误识别为 Main Menu → 死循环按 M 4 分钟）
- [x] system prompt **rule 7b MENU-KEY GATE**：`{M, ESC, ENTER, TAB, BACKSPACE, F1, F2}` 必须满足 dark-panel ≥60% + 无 HUD + 显式 on-screen 提示三条件，否则改 W
- [x] system prompt **rule 7c DISMISS-KEY ESCALATION**：进菜单连续按同一键不退就 cycle `M → TAB → BACKSPACE → ESC → ENTER → fallback W`
- [x] watchdog `consecutive_static_required: 4 → 5`（8s → 10s 触发，减少 normal gameplay 误触发率）

`f962bc3 fix(auto-play): 解决 bot 卡墙/傻站/卡菜单的链式根因 + capture 默认 60s`
- [x] watchdog UI-mask 阈值 `30/0.20 → 80/0.70`（FF7R pre-UI/post-UI tone-mapping 差异在 normal gameplay 制造 50%+ 整图色差，老阈值 11/17 次假阳性）
- [x] `runner` + `watchdog` 加 `_recovery_active_evt` threading.Event：watchdog 跑 recovery 时 main driver loop + heartbeat 暂停 inject（避免并发 W+S 互抵把 recovery 物理脱困序列冲掉）
- [x] **Background heartbeat thread**（`runner._heartbeat_loop`）：1.5s 没 inject 自动补 W —— 解决 VLM API 3-5s round-trip 期间 main thread 阻塞导致 bot 傻站 50% 时间
- [x] `InputBackend.last_inject_at_mono` 字段（每次 inject 后更新，heartbeat 凭它判断）
- [x] tick-level INFO log `[AUTO-PLAY] tick: vlm → N action(s) [...]` —— 不开 `--auto-play-debug` 也能 grep 看到 bot 实际收到的 actions
- [x] tick-level fallback：VLM 输出无 movement key 时强制追加 W 1500ms
- [x] VLM mouse turn example 反 right-bias：default 改 `dx:-250 (look left)`，加 "Direction balance" 规则
- [x] VLM rule 11 Movement coverage：每 tick 至少一个 movement input `duration_ms ≥ 2500`（覆盖 VLM round-trip）；rule 5 软 cap 提到 3000ms
- [x] `profiles/ff7r.yaml` NEAR-WALL OVERRIDE（vending machine / 海报等遮挡）+ TURN DIRECTION ALTERNATION（90° 墙角同向 turn 累积只是从一面墙转到另一面墙）+ Fullscreen menu 默认 M 不 ESC
- [x] `tools/auto_play/ocr_detector.py` `_DISMISS_PATTERNS` 动词表加 `Confirm|OK|Accept|Proceed|Advance|Yes`（中文加 `确认|是`）—— 修 FF7R 弹窗 "Enter Confirm" 不识别
- [x] `--capture-duration` 默认 `30 → 60s`（main.py + CLAUDE.md）
- [x] `verify_auto_play.py` `_neutralize_os_inputs()` monkey-patch `_user32.SendInput` + `vgamepad = None` —— 跑测试不再喷键鼠到 active window
- [x] `verify_auto_play.py` 修 stale `_trigger_recovery(diff=)` keyword + 加 `wd.stop()` 消除 daemon-thread race

## Not Yet Done

- [ ] **Action-feedback loop**（potential）：VLM 单帧无 history，看不到自己上次按的键是否生效。当前用 prompt rule 7c 软提示 escalation 依赖 VLM 自觉。如果实测 VLM 不严格遵守 cycle 顺序，可考虑 runner-level 强制 escalation —— 维护 `last_menu_key_attempts: deque[(key, time)]`，连续 2 个 tick 同 key 自动替换为下一个 escalation key（M→TAB→...）。
- [ ] **Frame-hash 完全静帧检测**（potential）：watchdog 现在只看 frame diff 阈值，菜单内有动画（光标闪烁、tutorial GIF）让 frame diff 不全为 0，触发延迟。若实测 menu 卡死仍超 10s，可加 perfect-duplicate hash bucket 检测。

## Failed Approaches (Don't Repeat These)

按时间顺序记录这一轮里**试过又回退**的修法 —— 都是真踩坑后才学到的。

### 1. vlm 模式下 watchdog 咨询 main VLM driver 拿 recovery actions（已回退）

**尝试**：`runner.py` 在 vlm 模式下把 `self._driver` 喂给 watchdog 当 `vlm_for_watchdog`，watchdog 触发时调 `_consult_vlm()` 拿定制 recovery actions（D 修法）。

**实测失败**：vending machine 卡死场景下 log 显示 watchdog 触发后调 VLM call#4，**返回的 reasoning 跟 main loop 一样是 "walk forward"**。VLM 视觉判断**无法察觉物理碰撞**（看到机柜旁有路 → reason 走前方 → 物理被卡）。所以 watchdog 触发 = 真物理卡死时，VLM 拿同样画面输出同样 walk-forward = 等于没触发。

**当前方案**：vlm 模式 `vlm_for_watchdog = None`，watchdog 直接走 deterministic `profile.recovery`（move_back + 4 连 turn + W）—— 不依赖 VLM 视觉判断的物理脱困序列。hybrid 模式保留 VLM consultant（keep_alive 主跑时它仍然有意义）。

### 2. recovery 末尾按 ESC 兜底（已删）

**尝试 v1**：recovery 头部 `ESC × 3` 退菜单（旧版 ff7r.yaml）。
**尝试 v2**：移到末尾"单次 ESC + M"兜底。
**尝试 v3**：缩成末尾仅 ESC。

**实测失败**：watchdog 误触发是常态（local-only 静帧、UI-mask 假阳性、long-window 阈值掠过 0.04 等）。**ESC 在 FF7R gameplay 中 = 打开 Main Menu**。recovery 跑完末尾的 ESC 把 bot 从 gameplay 推进了菜单 → VLM 看到菜单按 M/ENTER 试退又退不掉 → 死循环。这一连锁灾难直接吞掉用户 4 分钟一次 session。

**当前方案**：recovery 完全无 ESC。如果真进了菜单，由 main loop 的 VLM 看图决策处理。

### 3. recovery 末尾按 M (`dismiss_ui`) 兜底（已删）

**尝试**：删掉 ESC 之后保留末尾 `dismiss_ui (M) + wait` 当"轻量"兜底（M 比 ESC 副作用小）。

**实测失败**（log 19:09:27 → 19:11:52，4 分钟死循环）：
- watchdog long-window static `mean=0.0324` 在 normal gameplay 误触发
- recovery 末尾 M 按下 → **打开 FF7R Map 副屏**
- VLM 看到 Map（dark panel + options 视觉跟 Main Menu 类似）误识别为 fullscreen menu → reasoning "close with M"
- 但 **FF7R Map 关闭键是 Tab 不是 M** → bot 反复按 M 4 分钟

**当前方案**：recovery 100% 纯 movement，**绝不按任何 menu/UI/photo 相关键**（无 ESC、M、ENTER、Tab、Backspace、F1、F2）。教训：watchdog 误触发是常态，recovery 必须假定 "bot 还在 gameplay 中" 跑。

### 4. NEAR-WALL turn 永远固定 right (mouse_dx=+700)

**尝试**：第一版 NEAR-WALL OVERRIDE prompt 推荐 `dx 600+ 大幅 turn`，没指定方向。

**实测失败**：log 显示 VLM 永远输出正值 (`+600`/`+700`)。FF7R 90° 墙角，连续右转 90° 后正好对着另一面墙 → 又触发 near-wall → 又右转 → 死循环。

**当前方案**：`profiles/ff7r.yaml` 加 `TURN DIRECTION ALTERNATION` 规则强调左右交替；`vlm_driver.py` 通用 mouse turn example 把 default 从 `dx:+250 (look right)` 改 `dx:-250 (look left)` + 加 "Direction balance" 规则。

### 5. watchdog 4 连 turn 之间没 wait

**尝试**：早期 recovery 用连续 4 个 turn `payload: {direction: left, magnitude: 2.0}` 期望累积 180° 调头。

**实测失败**：`keep_alive.py` mouse turn 是 `duration_ms=0` 的瞬时 SendInput pulse，4 次 SendInput 在 < 1ms 内全发完，**游戏一帧合并 mouse delta → 实际只转 1 次 (~60°)**。墙角转 60° 还是面墙。

**当前方案**：每个 turn 后插 `wait 80ms`，让游戏每帧 sample 一次 mouse delta，4 次累积约 200°+ 真调头。

### 6. UI-mask 臂阈值 `pixel=30 / ratio=0.20`（已大幅放宽）

**尝试**：原始阈值假定 BackBuffer.bmp ⊖ BackBufferUI.bmp 的差异主要来自 UI 元素 → 20% 像素 max-channel diff > 30 就触发。

**实测失败**：FF7R BackBuffer (Reinhard HDR→sRGB) vs BackBufferUI (游戏自家 tone-mapping) 整图色差 50%+ 是 normal gameplay 常态。30 分钟 session 17 次 watchdog 触发，**11 次是 UI-mask 假阳性**，每次串到 recovery 末尾 ESC（当时还没删）→ 推 bot 进菜单。

**当前方案**：阈值改 `pixel=80 / ratio=0.70` —— 只触发清晰可见的 fullscreen menu (>70% 像素显著色差)。

### 7. 首次 keep_alive sequence forward 占比 52%（已重写）

**尝试**：原版 sequence `move_forward × 4 = 7300ms` 占 14000ms 周期 52%。

**实测失败**：bot 频繁连冲 W 撞墙，截屏一帧定格死直对窗户/砖墙。

**当前方案**：sequence 重写，forward 拆短（每段 0.8-1.2s）+ 每个移动段后强制 turn + strafe 拉到 1s + back 拆 2 段。forward 占比 32%，非 forward 移动占比 19% → 38%。

## Key Decisions

| 决策 | 理由 |
|------|------|
| watchdog 触发走 deterministic profile.recovery，不咨询 VLM | VLM 视觉判断不识别物理碰撞；watchdog 已是真卡死信号，要 deterministic 物理序列，不要再问会犹豫的 VLM |
| recovery 100% 纯 movement，不按任何 menu 键 | watchdog 误触发是常态，按任何 menu 键都自挖坑（ESC 开 Main Menu / M 开 Map / F1 开 Save / F2 开 Photo Mode） |
| Multi-thread 协调用 `threading.Event` (`_recovery_active_evt`) | watchdog inject 序列期间 main loop + heartbeat 必须暂停，避免并发 W+S 互抵 |
| `InputBackend.last_inject_at_mono` 字段 + runner heartbeat thread 凭它判断 | 替代方案是 InputBackend 内部加 callback，太侵入；fields 接口最小 |
| Prompt-level prevention（rule 7b GATE）+ reactive escalation（rule 7c CYCLE）双管齐下 | 单层 prompt 容易被 VLM 抽风击穿，两层互补 |
| 加 attack heartbeat thread 不依赖 VLM | 实测 35 ticks 0 次 click，VLM 不主动产 attack；dataset 训练需要 attack 样本，必须保底 |
| `--capture-duration` 默认 30→60s | 60s/段更便于 ML batch 化，长跑无人值守需求 |
| `verify_auto_play` `_neutralize_os_inputs()` monkey-patch | 测试不污染用户 active window 输入，但保留 lock + reserved-key check 等业务逻辑生效 |

## Current State

**Working**:
- vlm 模式 watchdog → deterministic recovery（log `→ 注入 recovery (16 步)`）
- vlm 模式 main loop 期间 background W heartbeat（log `[HEARTBEAT] silent=1.5s → 注入 W 1500ms`）
- recovery 跑完不再开任何 menu（无 ESC / M / ENTER 注入）
- VLM 应用 NEAR-WALL OVERRIDE（log reasoning `near wall ... back away and turn`）
- VLM 输出 left-turn (`dx:-250` / `-300`) 而非永远右转
- tick INFO log 详细显示每 tick 注入了哪些 actions
- attack heartbeat thread 每 12s 注入 mouse_left（dataset 有 attack 样本）

**Broken / Not yet validated** (等下次实跑确认):
- Rule 7c DISMISS-KEY ESCALATION 实战效果未知（VLM 是否真按 M→TAB→BACKSPACE→ESC→ENTER cycle）
- watchdog `consecutive_static_required 5`（10s）是否仍偶发误触发

**Uncommitted Changes**: 无。working tree clean。

## Files to Know

| 文件 | 角色 |
|------|------|
| `tools/auto_play/runner.py` | main driver loop + background heartbeat thread + attack heartbeat thread + `_recovery_active_evt` 协调；多 thread 启停同步 |
| `tools/auto_play/watchdog.py` | StaticFrameWatchdog 5 臂检测（short-window / local-only / long-window / UI-mask / OCR）+ `_trigger_recovery` try/finally set/clear 共享 event |
| `tools/auto_play/vlm_driver.py` | OpenAI-compatible VLM client；`_SYSTEM_PROMPT_TEMPLATE` 含 rules 1-11（含本轮新加 7b GATE / 7c ESCALATION / 11 movement coverage）；Open exploration recipe 拆 70/30 |
| `tools/auto_play/input_backend.py` | OS-level SendInput + vgamepad；`last_inject_at_mono` 字段供 heartbeat 检测 |
| `tools/auto_play/ocr_detector.py` | Windows.Media.Ocr 包装 + `_DISMISS_PATTERNS` 正则（含 Confirm/OK/Accept/Proceed/Advance/Yes 中英文动词） |
| `profiles/ff7r.yaml` | FF7R-specific config：keep_alive sequence (forward 占比 32%) + recovery (100% 纯 movement) + watchdog (5×2s=10s 触发) + vlm.game_instructions (NEAR-WALL OVERRIDE / TURN ALTERNATION / Fullscreen menu 默认 M) |
| `scripts/verify_auto_play.py` | 44 项 capability + integration + offline E2E checks；顶部 `_neutralize_os_inputs()` 跑测试不污染 OS 输入 |

## Code Context

### `_recovery_active_evt` 协调（核心同步原语）

`tools/auto_play/runner.py:152-157`：
```python
# Shared "recovery in progress" event — watchdog sets while running
# profile.recovery; main driver loop + heartbeat thread skip their own
# injects while set.
self._recovery_active_evt = threading.Event()
self._watchdog = StaticFrameWatchdog(
    ..., recovery_active_evt=self._recovery_active_evt,
)
```

`tools/auto_play/watchdog.py:_trigger_recovery`：
```python
def _trigger_recovery(self, mean_diff, moved_ratio):
    self._trigger_count += 1
    self._recovery_active_evt.set()
    try:
        # ... inject 18 步 recovery sequence ...
    finally:
        self._recovery_active_evt.clear()
```

`tools/auto_play/runner.py:_driver_loop`：
```python
while not self._stop_evt.is_set():
    if self._recovery_active_evt.is_set():
        self._stop_evt.wait(0.1)
        continue
    # ... call VLM + inject actions ...
```

`tools/auto_play/runner.py:_heartbeat_loop`：
```python
while not self._stop_evt.is_set():
    self._stop_evt.wait(self._heartbeat_check_s)
    if self._recovery_active_evt.is_set():
        continue   # yield to watchdog
    silent = time.monotonic() - self._backend.last_inject_at_mono
    if silent < 1.5: continue
    self._backend.inject(self._heartbeat_action)  # W 1500ms
```

`tools/auto_play/runner.py:_attack_heartbeat_loop`：同样 check `_recovery_active_evt`，每 12s 注入 mouse_left。

### `--driver` 模式行为差异

| 模式 | main loop | watchdog 触发后 | patrol thread | heartbeat thread | attack heartbeat |
|------|-----------|-----------------|---------------|------------------|------------------|
| `keep-alive` | 跑 profile.keep_alive.sequence | profile.recovery | 不启动 | 不启动 | **启动** |
| `vlm` | 持续调 VLM 决策 | profile.recovery（**不**咨询 VLM） | 不启动 | 启动 | **启动** |
| `hybrid` | 跑 profile.keep_alive.sequence | 优先咨询 VLM 拿定制 actions，fallback profile.recovery | 启动（每 12s VLM dismiss-only patrol） | 启动 | **启动** |

### VLM JSON action schema（VLM 必须输出）

```json
{
  "reasoning": "<one sentence>",
  "actions": [
    {"kind": "key", "payload": {"vk": "W", "event": "press"}, "duration_ms": 2500},
    {"kind": "mouse", "payload": {"op": "move", "dx": -250, "dy": 0}, "duration_ms": 0},
    {"kind": "mouse", "payload": {"op": "click", "button": "left"}, "duration_ms": 150}
  ]
}
```

`vk` 列表见 `input_backend.py:VK_MAP`（W/A/S/D/SPACE/ENTER/ESC/M/Tab/F1-F12/Backspace 等）。`event` 始终是 `"press"`，runner 持续按 `duration_ms` 后释放。

### tick log 格式（grep 用）

```
[AUTO-PLAY] tick: vlm → 3 action(s) [key/W/2500ms mouse/move/-250,0 mouse/click/left/150ms]
[HEARTBEAT] silent=1.5s → 注入 W 1500ms (heartbeat#3)
[ATTACK-HB] 注入 attack#1 (period=12.0s)
[WATCHDOG] long-window static (4s): long_mean=0.0324 long_moved=6.8% — 当作卡死
[WATCHDOG] static-frame 触发 #1 mean=0.0324 moved=6.8% → 注入 recovery (16 步)
```

## Resume Instructions

1. **Sponsor 实跑下一轮 FF7R 验证**：
   ```powershell
   uv run main.py launch --auto-play --profile ff7r
   ```
   按 F8 开始采集，跑 ≥ 10 分钟覆盖：
   - normal exploration（街道走动）
   - 撞墙场景（Sector 5/7 巷道、机柜旁、墙角凹处）
   - 偶发进 menu / popup（教程、Save dialog 等）

2. **关键观察点**（log `%TEMP%/unicap/auto_play.log`）：

   **A) 进菜单频率应大幅下降**（核心目标）
   - 期望：grep `reasoning.*fullscreen menu\|reasoning.*Map\|reasoning.*Settings` 出现次数 ≤ 1-2 次/10min（之前 5-10 次/10min 正常）
   - 失败信号：仍频繁 reasoning 菜单 → 可能 rule 7b GATE 不够强，需要往 prompt 加更具体反例（如"看到 'F1 Save' 字样不要按 F1"）

   **B) 进了菜单 cycle 退出快**
   - 期望：rule 7c ESCAPATION 触发，连续 5 个 tick 内 reasoning 出现不同 dismiss key（M → TAB → BACKSPACE → ESC → ENTER）
   - 失败信号：连续 ≥ 4 个 tick 都按同一键 → VLM 不遵守 cycle，需要 runner-level 强制 escalation

   **C) recovery 期间 main loop / heartbeat 真的暂停**
   - 期望：watchdog 触发 `→ 注入 recovery (16 步)` 后 7-8s 内**没有** `[AUTO-PLAY] tick:` 或 `[HEARTBEAT] 注入 W` 日志
   - 失败信号：recovery 期间仍有 main loop tick 输出 → `_recovery_active_evt.is_set()` check 没生效

   **D) attack heartbeat 实际产生攻击样本**
   - 期望：`[ATTACK-HB] 注入 attack#N` 每 12s 出现一次
   - 期望：tick log 偶尔含 `mouse/click/left/150ms`（VLM 自觉 + heartbeat 兜底）

   **E) VLM 真用 left-turn 抵消 right-bias**
   - 期望：tick log mouse/move 的 dx 正负**比例接近 50/50**
   - 失败信号：仍以 `+250 / +300` 为主 → prompt direction balance 没生效

3. **如果 cycle escalation 不可靠**（最可能的下一个工作项）：
   - 在 `tools/auto_play/runner.py` 加 `_last_menu_keys: collections.deque[str](maxlen=3)` 字段
   - main loop inject 后记录"这次 inject 中的 menu key"（M/ESC/ENTER/TAB/BACKSPACE）
   - 下次 tick 前判断：deque 最近 2 次相同 → 强制把当前 actions 里的同 menu key 替换为 escalation 序列下一个
   - 这是 runner-level 强制 cycle，不依赖 VLM 自觉

4. **如果 menu 卡死时间仍 > 30s**：
   - 考虑 watchdog 加新臂：`frame-hash bucket` 检测 perfect duplicate（菜单内静止帧的 hash 一致）
   - `tools/auto_play/watchdog.py` 加 `_HASH_HISTORY` deque，连续 N 帧 hash 相同 → 强制触发 recovery（绕过 frame diff 阈值）

## Setup Required

跑 auto-play 前需要的环境：

| 配置 | 用途 |
|------|------|
| `.env` 含 `VLM_API_KEY` / `VLM_BASE_URL` / `VLM_MODEL` | VLM driver 端点（默认 Qwen-VL via DashScope） |
| ViGEmBus driver 装好（可选） | 启用虚拟手柄；不装也能跑（键鼠通道仍可用） |
| `uv sync --extra auto-play-vlm` | 装 openai SDK + python-dotenv |
| `uv sync --extra auto-play-ocr` | 装 winrt-* 5 件套（OCR 臂） |
| `tools/capture/config.py` 改 `GAME_PATH` | 指向 ff7remake_.exe |

## Edge Cases & Error Handling

- **VLM_API_KEY 缺失**：`VLMDriver` 第一次 `next_actions()` 抛 `BudgetExhausted` → runner 自动降级 `KeepAliveDriver` 继续 capture
- **ViGEm 缺失**：`InputBackend` 走"键鼠 fallback"分支 + warn 一次；profile.input.prefer_gamepad=true 也强制键鼠
- **OCR 臂禁用**（winrt 缺失）：watchdog 仍跑其他 4 臂，OCR tick 永远 skip
- **watchdog daemon thread join 超时**：log warn `[WATCHDOG] thread join 超时 (3.0s)`，runner 继续 stop（thread 是 daemon，进程退出会被回收）
- **VLM 输出无 movement key**：tick-level 兜底追加 W 1500ms（`runner._driver_loop`）；额外 thread-level heartbeat 1.5s 静默后再补
- **VLM 输出连续相同 menu key（如反复 M）**：当前依赖 prompt rule 7c 自觉 cycle —— 未做 runner-level 强制（见 Resume Instructions #3）

## Warnings

- **不要回退 recovery 移除 menu 键的设计**。已有 3 代踩坑（ESC×3 → 末尾 ESC → 末尾 M），每代都被实测推 bot 进菜单。recovery 必须 100% 纯 movement。
- **不要在 vlm 模式重新喂 VLM consultant 给 watchdog**。VLM 视觉判断不识别物理碰撞，watchdog 触发咨询 VLM 拿到的是同样 walk-forward = 等于啥都没做。
- **不要把 turn `payload.direction` 默认改回固定值**（如 `right`）。FF7R 90° 墙角同向 turn 累积只是从一面墙转到另一面墙。`random` 或 prompt-driven left-bias 都比固定方向好。
- **`InputBackend.last_inject_at_mono` 是 read-only for outsiders**。只有 `InputBackend.inject()` 内部更新；runner heartbeat thread / watchdog 都是 read-only consumer。
- **`_recovery_active_evt` 必须用 `try/finally` 配对 set/clear**。否则 watchdog 跑 recovery 中途异常会让 event 永远 set，main loop 永远 skip → bot 完全没动。
- **`scripts/verify_auto_play.py` 的 `_neutralize_os_inputs()` 必须在 main() 头部调用**。它 monkey-patch module-level `_user32.SendInput` 和 `vgamepad`，必须在 InputBackend 任何实例化之前生效。
- **`profiles/ff7r.yaml` recovery 别再加 dismiss_ui / press_key**。即使是"轻量兜底"也会推 bot 进菜单。要 dismiss 让 main loop 的 VLM 处理，不要写在 recovery 里。
