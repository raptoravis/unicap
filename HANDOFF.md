# Handoff: 自动玩游戏（auto-play）— A 层落地 + C 层 contracts 占位

**Generated**: 2026-05-02 14:30
**Branch**: `auto-play`（与 master 分叉，未 push，4 commits）
**Status**: In Progress — A 层骨架 + 4 profile 全 commit 完毕；live test 已跑通 1 次（FF7R 40s capture，305 帧），用户已确认 stdout 修复 + AUTO-PLAY 启动 OK。**待 sponsor 再跑一次 30 分钟 FF7R 验证 watchdog 脱困 + cv2 mid-write 警告消失**。C 层（VLM driver）按计划仅签接口未实现。

## Goal

让 unicap 长时间无人值守采集 — 引入 auto-play bot 持续注入输入（移动 / 转向 / 攻击）+ watchdog 静帧脱困。两层架构：A 层哑 bot（本 release 落地），C 层 VLM 大脑（占位，下个 dev session 接）。多游戏 first-class（profile YAML 系统）。

## Completed

### Phase 1: 设计与 contracts
- [x] **需求文档** `docs/req/auto-play.md`（HIGH 信心度，sponsor 选定方案 3 = A 层 + C contracts）
- [x] **Impact analysis** `docs/designs/impact_20260502_auto-play.md`（10 风险点 + 缓解）
- [x] **TestPlan** `docs/designs/testplan_20260502_auto-play.md`（25 Must-Have + 7 integration + 5 E2E）
- [x] **Contract stubs** in `tools/auto_play/`（BotDriver / InputBackend / GameProfile / VLMDriver 占位）

### Phase 2: A 层实现（commit `5e8ce72`）
- [x] `tools/auto_play/driver.py` — `BotDriver` ABC + `Action`(kind: key/mouse/gamepad/wait) + `Observation`
- [x] `tools/auto_play/input_backend.py` — Win32 SendInput（键鼠）+ vgamepad 软依赖（ViGEm 虚拟手柄）+ 单 Lock 串行化 + reserved_keys 拦截 (F8/F9 强制保留)
- [x] `tools/auto_play/profile.py` — YAML schema 校验 + fuzzy match + `_default` fallback + Pydantic-style 错误信息（指 YAML 行号 / 字段名）
- [x] `tools/auto_play/keep_alive.py` — `KeepAliveDriver` + 公共 `step_to_actions(profile, step, rng)` 给 watchdog 共享
- [x] `tools/auto_play/watchdog.py` — `StaticFrameWatchdog` 后台线程；连续 N 次像素 diff < 阈值 → 注入 profile.recovery
- [x] `tools/auto_play/runner.py` — `AutoPlayRunner` 编排 driver + watchdog + InputBackend；start/stop 幂等；`create_driver(...)` 工厂用显式 kwargs（不吞 typo）
- [x] `tools/auto_play/vlm_driver.py` — VLMDriver 占位，构造时 raise NotImplementedError（错误指向 G-005/G-006）
- [x] **集成 main.py**：`--auto-play / --driver / --profile / --auto-play-debug / --vlm-budget-*` 6 个 flag；`_start_auto_play()` 在 `_run_capture` finally 块停 runner
- [x] `pyproject.toml` 加 `pyyaml`（硬）+ `vgamepad` 软依赖 (`[auto-play]` extras)
- [x] **4 个内置 profile**：`profiles/{_default,ff7r,doom_eternal,batman_ak}.yaml` + `profiles/README.md` 5 步接入新游戏文档
- [x] `scripts/verify_auto_play.py`：38 项 capability + integration + 离线 E2E 全 PASS
- [x] CLAUDE.md 加章节《自动玩游戏（auto-play）》

### Phase 3: live test 反馈修复
- [x] **`--auto-play` 默认 `--ui-mode both`**（commit `a14ea92`，per sponsor "BackBuffer.bmp 没 UI 信息，bot 应该看到 UI"）— bot/watchdog 优先看 BackBufferUI.bmp 才能识别 HUD/菜单/死亡画面
- [x] **stdout 缓冲修复**（commit `5e3a0f7`）：sponsor 反馈 "F8/F9 不响应"，实际是响应了但 `uv run` pipe 把 Python 默认 4KB 块缓冲，[CAPTURE] / [AUTO-PLAY] 不刷新。修：`sys.stdout.reconfigure(line_buffering=True)` + 关键 print 加 flush=True
- [x] **watchdog mid-write BMP 防御**（commit `5e3a0f7`）：sponsor 终端看到 `cv2.findDecoder imread_ ... can't open/read file` 噪音 — watchdog 抢在 addon 写完 BMP 之前读。修：跳过 mtime < 500ms 的 BMP（addon 写一帧 ~50ms，远快于 500ms）
- [x] **profile keep_alive + recovery 重写**（commit `a2f4e33`）：sponsor 反馈"人物卡角落"。原因：老 sequence 70%+ move_forward + 转向 magnitude 0.5-0.8 太小。修：加 move_back / move_left / move_right，转向 magnitude 1.0-1.8；recovery 改成 ESC×2 + SPACE + **4 次同向 turn=2.0 ≈ 180° 调头** + move_back 1.5s + move_forward 重启
- [x] **FF7R recovery 加 M 键**（commit `a2f4e33`，per sponsor "ui 状态需按 M 返回 3D 场景"）：FF7R 卡菜单/地图时 ESC 不够，**首发 press_key M** 强制回 3D 场景才能继续走

### Live test 已观察到的事实
- [x] sponsor 跑 `uv run main.py launch --auto-play --profile ff7` 命中 fuzzy match → ff7r.yaml ✓
- [x] AUTO-PLAY 输出 `driver=keep-alive profile=ff7r gamepad=unavailable` ✓（sponsor 机器没装 ViGEm Bus driver — 已软降级到键鼠通道）
- [x] [CAPTURE] x.xs / N 帧 实时输出 ✓（stdout 修复后）
- [x] **实测 fps ~7-8**（306 帧 / 40s）— `--ui-mode both` 一帧写 2 BMP + 1 EXR ≈ 13MB；磁盘 I/O 顶不住 30 fps。**sponsor 已知情并选定保持 both 模式**（详见 Key Decisions）

## Not Yet Done

- [ ] **30 分钟 FF7R 实机回归（sponsor 跑）**：验证 stdout 修复后 [CAPTURE] 持续输出、watchdog 不再喷 cv2 警告、recovery 在卡角落时能成功调头脱困
- [ ] **新游戏接入测试**（E2E-2）：sponsor 复制 `profiles/_default.yaml` → 改一个新游戏 → 跑 5 分钟看 watchdog 触发率
- [ ] **C 层 VLMDriver 实现**（下个 dev session）：填 `tools/auto_play/vlm_driver.py`，参考 `docs/req/auto-play.md` G-005 / G-006
- [ ] **merge `auto-play` → master + push**（待 sponsor 实机验收后）

## Failed Approaches (Don't Repeat These)

### 1. `wait` step 返回 `[]` 让 runner 外层 sleep — duration_ms 被忽略

最初 `step_to_actions` 处理 `wait` step 直接返回空 list，期望 runner 主循环的 `sleep_s = max(0.0, period - elapsed)` 把 wait 的 duration 吸收掉。但 runner 的 sleep 只到 `period_s`（profile 内 1.0s 左右），而 `wait` step 可能想要 800ms-2000ms 的暂停 — 实际上 `wait` 只起到"占一次 cursor 推进"的作用，duration_ms 被静默忽略。

**修法**（见 commit `5e8ce72` 后期）：在 `Action.kind` 里加 `'wait'` 类型，InputBackend.inject 见到 `kind=='wait'` 就 `time.sleep(duration_ms/1000)`。Action 契约一次扩展，所有 sleep 行为都明确。**别想着用 `mouse.move(0,0)` 装 sleep**（mouse op=move 不 honor duration_ms），也别让 driver 自己 sleep（会阻塞 next_actions）。

### 2. Watchdog 直接 reach 进 `KeepAliveDriver._step_to_actions`

最初 watchdog 实例化一个临时 `KeepAliveDriver(profile, seed=0)` 调用其 `_step_to_actions(step)`（私有方法）来翻译 recovery 序列。code-review 阶段发现这是 information leakage — `KeepAliveDriver` 重构会静默打破 watchdog。

**修法**：把翻译逻辑提到 `keep_alive.py` 模块级公共函数 `step_to_actions(profile, step, rng)`，driver 和 watchdog 各自调用 — 干净的共享契约。

### 3. `create_driver(**kwargs)` 静默吞 typo

最初工厂签名 `def create_driver(name, profile, **kwargs)`，给 `keep-alive` driver 也传 vlm 用的 `provider` / `budget_per_hour` —— typo 比如 `seeed=42` 被默默丢掉。code-review 阶段改为显式 keyword-only args（`*, seed=None, provider="anthropic", ...`），现在 typo 报 `TypeError: got an unexpected keyword argument 'seeed'`，verified by integration test I-3。

### 4. `--auto-play` 第一版 console 看不到任何输出

Sponsor 第一次跑后报 "F8/F9 不响应"。诊断方向走偏：以为是 hotkey hardware (Fn-lock) 或被全局 hook，写了 `scripts/test_hotkeys.py` 让 sponsor 测。Sponsor 自己定位到真正原因 — **stdout 块缓冲导致 print 不刷新**，按键实际响应了只是终端不显示。教训：当 sponsor 反馈"X 没响应"，先怀疑 I/O 缓冲 / 显示链路，再怀疑功能本身。

### 5. ~~depth-based UI mask 在 pack 路径~~（前次 handoff 已说明）
保留作为提醒：DOOM Eternal HUD 是真 3D 几何 (depth ~0.001-0.01)，depth 阈值 mask 不掉它；UE4 sky 误伤。Pack 路径已彻底移除 depth-based mask（commit `4c20bb4`）。

## Key Decisions

| Decision | Rationale |
|----------|-----------|
| 方案 3：A 层 MVP + C 层 contracts 占位 | 用户在 dev 阶段三选一中选定（`/zero-review:dev` 决策点）。A 层先落地能立刻无人采集，接口先固化避免 C 层未来返工 |
| `BotDriver.next_actions(Observation) → list[Action]` 是 A/C 共享核心契约 | C 层接入是纯加法，不动 A 层文件；接口不含 provider-specific 字段 |
| bot input 与人类 input **不区分**（共用 inputs.jsonl） | per requirements Q7 default。如果未来下游需要区分，加一个 `source` 字段是 1 行改动 |
| InputBackend 单 `threading.Lock` 串行化所有注入 | driver thread + watchdog thread 都用同一个 backend；并发 SendInput 会让 down/up 乱序 |
| `MANDATORY_RESERVED_KEYS = {F8, F9}`，profile schema 强制 | unicap 自身热键，bot 永不能误触发；schema validate 阶段拦，运行时再拦一次 |
| ViGEm 软依赖（`vgamepad` import 失败不 raise） | sponsor 机器实测没装 ViGEm Bus driver — 软降级到键鼠是必备；profile.input.prefer_gamepad=true 时只 warn 一次 |
| `--auto-play` 默认 `--ui-mode both` | sponsor 决策：bot/watchdog 必须看到 HUD/菜单/死亡画面才能做出靠谱的 recovery；clean pre-UI 同时落盘给 ML 训练 |
| **`--auto-play` 保持 both 模式 fps ~7-8 而非降级 ui** | sponsor 决策（2 vs 3 选 1）：双流数据更全面；fps 慢半倍可接受（8h 通宵仍能产 20w 帧） |
| Watchdog 优先 BackBufferUI.bmp，缺失才回落 BackBuffer.bmp | post-UI 帧含 HUD/menu，状态识别能力强；no-ui 模式仍兼容 |
| Watchdog 跳过 mtime < 500ms 的 BMP | addon 写一帧 ~50ms；500ms 远大于写入时间，远小于 sample_period_s（5-6s）— 避免 cv2.imread 抢 mid-write 文件 |
| stdout `line_buffering=True` 在 main() 开头 | `uv run` pipe 触发 Python 默认 4KB 块缓冲；line buffering 确保 [CAPTURE] / [AUTO-PLAY] 实时显示 |
| FF7R recovery 首发 **M 键** | sponsor domain knowledge：FF7R 进了 UI（菜单/地图/状态界面）必须按 M 才能回 3D 场景；ESC 单独不够 |
| Recovery 用 4 次同向 magnitude=2.0 turn 模拟 180° 调头 | 单次 SendInput dx=480 (mouse_sensitivity=0.8) 对很多 FPS 引擎"瞬间转太大"被忽略；分 4 次连续注入更可靠 |
| keep_alive sequence 加 move_back / move_left / move_right | 老序列 70%+ forward → 卡角落转不出来；加横向/后退步骤 + 大转向，自然脱困率更高 |

## Current State

**Working**:
- Master HEAD = `be4e033`；`auto-play` HEAD = `a2f4e33`（4 commits ahead，working tree clean）
- `uv run main.py launch --auto-play --profile <ff7|fuzzy>`：游戏起来 → F8 自动 capture → bot 持续注入 → F9 干净停 → watchdog 触发计数 print
- `dist/` 不需要重新 build（auto-play 全在 Python 层，C++ addon 零改）
- `scripts/verify_auto_play.py`：38/38 PASS（capability + integration + offline E2E）
- live test 验证：FF7R api=dx，ui-mode=both，fuzzy match `ff7` → ff7r.yaml，gamepad=unavailable 软降级 OK，305 帧 / 40s ≈ 7.6 fps（sponsor 接受）

**Broken**:
- 无（已知问题全在 commit a2f4e33 / 5e3a0f7 修了；待 sponsor 再跑一次 30 min 验证）

**Uncommitted Changes**: 无

## Files to Know

| File | Why It Matters |
|------|----------------|
| `docs/req/auto-play.md` | 8 个 Goals 的需求 — 看哪些做了哪些没做 |
| `docs/designs/impact_20260502_auto-play.md` | 10 个风险点 + 缓解 — 接 C 层时先重读 |
| `docs/designs/testplan_20260502_auto-play.md` | TestPlan + E2E coverage matrix — verify 通过的标准 |
| `tools/auto_play/driver.py` | `BotDriver` ABC + `Action`/`Observation` — A/C 层共享契约（**不动**） |
| `tools/auto_play/input_backend.py` | 250 LoC，SendInput + vgamepad；单 Lock；reserved_keys 拦截 |
| `tools/auto_play/profile.py` | YAML schema validate；MANDATORY_RESERVED_KEYS = {F8,F9}；fuzzy match |
| `tools/auto_play/keep_alive.py` | `step_to_actions(profile, step, rng)` 公共函数（watchdog 也用）+ `KeepAliveDriver` |
| `tools/auto_play/watchdog.py` | mtime 500ms guard 防 mid-write；优先 BackBufferUI.bmp |
| `tools/auto_play/runner.py` | `create_driver` 显式 kwargs；`AutoPlayRunner.start/stop` 幂等；driver/watchdog thread 独立 daemon |
| `tools/auto_play/vlm_driver.py` | C 层占位 — 构造抛 NotImplementedError 指向 G-005/G-006 |
| `profiles/ff7r.yaml` | recovery 首发 M 键；keep_alive 含 move_back/left/right；mouse_sensitivity=0.8 |
| `profiles/_default.yaml` | 通用 fallback；接入新游戏复制改 controls 即可 |
| `main.py` | `_start_auto_play()` 在 `_run_capture` finally 块 stop runner；`cmd_launch` 早期解析 ui_mode default；`main()` 开头 stdout reconfigure |
| `scripts/verify_auto_play.py` | 38 检查；CI-friendly（不需要游戏） |
| `scripts/test_hotkeys.py` | F6-F12 hotkey 诊断（Fn-lock / 全局 hook 排查） |
| `pyproject.toml` | `pyyaml` 硬依赖；`vgamepad` 在 `[project.optional-dependencies].auto-play` |
| `CLAUDE.md` | "自动玩游戏（auto-play）" 章节 — 用户文档 + flag 表 + 架构概览 |

## Code Context

### BotDriver 契约（A/C 共享，**绝对不动**）

```python
# tools/auto_play/driver.py
ActionKind = Literal["key", "mouse", "gamepad", "wait"]

@dataclass(slots=True)
class Action:
    kind: ActionKind
    payload: dict[str, Any]
    duration_ms: int = 0

@dataclass(slots=True)
class Observation:
    timestamp: float
    profile: GameProfile
    frame_bgr: np.ndarray | None = None
    metadata: dict[str, Any] = field(default_factory=dict)

class BotDriver(ABC):
    @abstractmethod
    def next_actions(self, observation: Observation) -> list[Action]: ...
    def on_start(self) -> None: ...
    def on_stop(self) -> None: ...
    @property
    def decision_period_s(self) -> float: return 1.0
```

### 公共 step→actions 翻译（profile.keep_alive 任何 step 通用）

```python
# tools/auto_play/keep_alive.py
def step_to_actions(profile: GameProfile, step: dict, rng: random.Random) -> list[Action]:
    """Translate one keep_alive.sequence / recovery step into Actions.
    Public so the watchdog can reuse without reaching into a driver's internals."""
    # action ∈ {move_forward, move_back, move_left, move_right,
    #           turn, attack, interact, jump, press_key, stick_jitter, wait}
    # 处理 ±20% 时长抖动；payload 解析；profile.input.prefer_gamepad 自动选通道
```

### Profile schema（接入新游戏的契约）

```yaml
name: ...                  # 与文件名 stem 一致
description: |
  ...
controls:
  move_forward: W          # vk 名 / mouse_<btn> / gamepad_<btn>
  move_back: S
  move_left: A
  move_right: D
  turn_axis: mouse         # mouse | gamepad_rstick
  attack: mouse_left
  interact: E
  jump: SPACE
reserved_keys: [F8, F9]    # F8/F9 强制保留（schema 拒绝去掉）
input:
  prefer_gamepad: false
  mouse_sensitivity: 1.0
keep_alive:
  period_s: 1.0
  sequence: [...]
  recovery: [...]
watchdog:
  sample_period_s: 5.0
  static_diff_threshold: 0.01
  consecutive_static_required: 2
vlm:
  game_instructions: |     # 给 VLM 的操作约定段
    ...
  frame_subsample_long_edge: 512
```

### main.py 集成点

```python
# main.py:cmd_launch — ui-mode resolution（在 cmd_deploy 之前）
def cmd_launch(args):
    if args.ui_mode is None:
        args.ui_mode = "both" if getattr(args, "auto_play", False) else "no-ui"
        if getattr(args, "auto_play", False):
            print(f"[AUTO-PLAY] --ui-mode 默认 both（bot/watchdog 看 post-UI BMP）", flush=True)
    ...

# main.py:_run_capture — runner lifecycle
auto_play_runner = _start_auto_play(args, frames_dir, game_exe_stem=game_name)
try:
    capture_all.run(...)
finally:
    if auto_play_runner is not None:
        auto_play_runner.stop()
    ...

# main.py:main() — stdout 缓冲修复
def main():
    try:
        sys.stdout.reconfigure(line_buffering=True)
        sys.stderr.reconfigure(line_buffering=True)
    except (AttributeError, OSError):
        pass
    ...
```

### CLI flags（新增 6 个）

```
launch ... [--auto-play]
           [--driver {keep-alive,vlm}]   # 默认 keep-alive；vlm 立即报错
           [--profile NAME]              # 不传则按 exe 名 fuzzy match
           [--auto-play-debug]
           [--vlm-budget-per-hour N]     # C 层占位
           [--vlm-budget-total-usd N]    # C 层占位
```

## Resume Instructions

### 接班 agent 第一件事

```bash
git status                # 应 clean，branch=auto-play
git log --oneline -5      # 应见 a2f4e33 → 5e3a0f7 → a14ea92 → 5e8ce72 → be4e033
ls tools/auto_play/       # 8 个 .py 文件
ls profiles/              # _default + ff7r + doom_eternal + batman_ak + README.md
```

### 验证当前状态

```bash
uv run python scripts/verify_auto_play.py
# 期望: 38 pass / 0 fail
```

### Sponsor 待跑的 live E2E（30 min）

```powershell
# 在 D:\dev\unicap.git\，git checkout auto-play
uv run main.py launch --auto-play --profile ff7r
# 期望:
#   [AUTO-PLAY] --ui-mode 默认 both（bot/watchdog 看 post-UI BMP）
#   [DEPLOY] 自动加载 survey 推荐 pre_ui_skip=...
#   [启动] ...ff7remake_.exe (api=dx)
#   操作提示框 (ui-mode=both)
#   [AUTO-PLAY] driver=keep-alive profile=ff7r gamepad=...
# 进游戏 → F8 → survey（首次） → capture
# 期望: [CAPTURE] x.xs / N 帧 持续 print（fps ~7-8 是 both 模式下正常）
# 离开 30 min
# 期望: 卡角落时 watchdog 触发，看到 "[WATCHDOG] static-frame 触发 #N" log
#       recovery 序列注入：M 键退 UI → ESC×2 → 4 次 turn ≈180° 调头 → 后退 → 重新出发
# F9 停止
# 期望: [AUTO-PLAY] 停止；watchdog 触发 N 次
# 看 dataset/<game>/<ts>/frames/ 数 + auto_play.log（%TEMP%/unicap/auto_play.log）
```

### 下个 dev session：实现 C 层 VLMDriver

1. **不要**改 A 层任何文件（A/C 接口已稳定）— 只改 `tools/auto_play/vlm_driver.py`
2. 参考 `docs/req/auto-play.md` G-005 (VLM 决策回路) + G-006 (成本与配额控制)
3. 推荐 provider：Claude Haiku 4.5 + Gemini 2.5 Flash（per CLAUDE.md user instructions 偏好 Anthropic SDK；prompt caching 必须启用）
4. JSON schema 严格输出格式：`{actions: [{kind, payload, duration_ms}], reasoning?}`
5. profile.vlm.game_instructions 拼进 system prompt
6. 写 `scripts/verify_vlm_driver.py` 短测：30 分钟 FF7R 跑 vlm driver，看 schema 错误率 ≤5% + 总花费 ≤$5
7. CLAUDE.md auto-play 章节里把"VLMDriver 占位未实现"改成"VLMDriver 实战测过"

### Merge `auto-play` → master（待 sponsor 实机验收后）

```bash
git checkout master
git merge --no-ff auto-play -m "merge: auto-play — 无人值守采集 A 层 + C 层 contracts"
git push origin master
git branch -d auto-play
```

## Setup Required

### 已沿用（无新需求）
- VS 2022 + MSBuild v143（C++ 没动，不需要重 build）
- `uv sync` 装 Python deps（pyyaml 是新增的，会被 uv lock 拉到）
- `tools/capture/config.py` GAME_PATH = FF7R inner exe（sponsor 机器特定）

### Auto-play 可选
- **ViGEm Bus driver**（虚拟手柄）— sponsor 没装，软降级到键鼠通道工作中。要装：[ViGEmBus releases](https://github.com/nefarius/ViGEmBus/releases) → `uv sync --extra auto-play`
- **`AUTO_PLAY_DEBUG=1`** env var 或 `--auto-play-debug` flag — 打印每次注入的 Action（log 在 `%TEMP%/unicap/auto_play.log`，rolling 5MB × 3）

## Edge Cases & Error Handling

| 场景 | 行为 |
|------|------|
| `--driver vlm` 用户错选 | VLMDriver 构造立即 raise NotImplementedError，错误信息含 G-005/G-006 引用；main.py 接住 → `sys.exit(2)` |
| ViGEm Bus 未装 | InputBackend 软降级到键鼠 + warn 一次；profile.input.prefer_gamepad=true 时 warn 更显眼但仍降级 |
| profile YAML 缺字段 | `_validate_profile` raise ValueError 含字段名 + YAML 文件路径（V-010 验证） |
| profile fuzzy match 命中 | print `[AUTO-PLAY] profile fuzzy match: 'X' → Y.yaml`（实测 'ff7' → ff7r.yaml ✓） |
| profile 完全找不到 | 回落 `_default.yaml` + warn |
| frames_dir 暂时为空（capture 还没产帧） | watchdog 30s warmup 内不 log；warmup 后 log debug 不触发 recovery |
| addon 写 BMP 中途被 watchdog 读到 | mtime < 500ms 跳过；不再有 cv2.imread 警告 |
| driver `next_actions` 抛异常 | runner catch + log + 续 5s 重试；exponential backoff 最多 30s |
| watchdog 静帧连续触发 | trigger_count++；profile.recovery 序列注入；recovery 失败也不 raise（log + 继续监控） |
| F9 停止时 driver 卡死 | runner.stop(timeout_s=3) 强制 join 超时 → log warn 不 raise |
| Steam 重启游戏 → 新 PID | auto-play 不感知（不绑 PID）；继续向前台窗口 SendInput；如果游戏不在前台，input 静默丢失（已知限制） |
| 用户在 auto-play 期间手动操作 | 无冲突保护（per Non-Goals）；用户输入与 bot 输入按时间叠加 |
| capture session 用 `--ui-mode no-ui` 但 `--auto-play` | sponsor 可显式覆盖；watchdog 退化到看 BackBuffer.bmp（pre-UI 净场景，UI 状态识别能力差）|
| stdout 缓冲（`uv run` pipe） | main() 开头 reconfigure(line_buffering=True) + 关键 print flush=True 双保险 |

## Warnings

- **profile.reserved_keys 必须含 F8 / F9**（schema 强制；MANDATORY_RESERVED_KEYS）— bot 永不能误触发 unicap 自身热键
- **InputBackend 单 Lock 串行化**：`time.sleep(duration_ms/1000)` 持锁期间 watchdog 不能注入；这是有意为之，避免 down/up 乱序
- **`Action.kind='wait'` 是后加的第 4 种 kind**（commit `5e8ce72` 后期），别把它退化为 mouse op=move dx=0 — 那个不 honor duration_ms
- **`step_to_actions(profile, step, rng)` 是公共 API**（watchdog 也用），不要把它退化成 KeepAliveDriver 的私有方法 — 重构会静默打破 watchdog
- **`create_driver` 用 keyword-only args**（`*, seed=..., provider=..., budget_*=...`）— 别改回 `**kwargs`，typo 会被吞
- **`--auto-play` 默认 `--ui-mode both` 会让 fps 减半**（实测 ~7-8 fps vs 30 target）— sponsor 已知情并 keep both；如要切回 ui 模式：显式 `--ui-mode ui`
- **stdout buffering 修复必须在 main() 最早调**（在 print 任何东西之前），否则 unicap 版本号那行可能又被吞
- **vgamepad 软依赖**：`pip install vgamepad` 装得上但需要 ViGEm Bus driver 内核驱动；用户没装内核时 `vgamepad.VX360Gamepad()` 构造会 raise — InputBackend catch 后 fallback 键鼠
- **watchdog 优先 BackBufferUI.bmp** 但 fallback BackBuffer.bmp — 如果未来改 frame 命名规则（移除 BackBufferUI suffix），watchdog 的 `if "BackBufferUI" in p.name` 判断要同步改
- **FF7R recovery 首发 M 键** 是 sponsor domain 知识 — 别在 cleanup 时去掉；DOOM Eternal / Batman 不需要 M（不同游戏菜单退出键不同）
- **C 层 VLMDriver 接入禁忌**：不要改 BotDriver ABC、不要在 driver.py 里加 provider-specific 字段、不要从 main.py 直接 import VLM SDK（保持 vlm_driver.py 是唯一入口）
- 沿用上份 handoff warnings：reshade/source/ 改了必须 `-Rebuild`；旧 `unicap-*.{i,asm,cso}` cache 不会自动清；R10G10B10A2 swap chain 错色；NUM_WORKERS=2 constexpr
- `dist-exe/` 目录是上次 `build-exe.ps1` 产物（v1.0.2，无 auto-play 模块），如要重新分发 auto-play 版本**重跑** `scripts\build-exe.ps1`（确认 nuitka 把 `tools/auto_play/` + `profiles/` 一起打包）
