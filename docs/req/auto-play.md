# Requirements: 自动玩游戏机制（unattended capture）

**Version:** 1.0 (2026-05-02)
**Confidence:** HIGH
**Sponsor:** raptoravis (`FreddieSparksmie@computer4u.com`)
**Source:** `/zero-review:req` 直接请求 — sponsor 选定 "C + A 混合 + 多游戏 first-class"

## 中文摘要

unicap 现状：采集需要人坐在电脑前打游戏，长时无人值守不可行。本需求引入**自动玩游戏 (auto-play) 机制**，分两层落地：
- **A 层（基础设施）**：通用输入注入 + 静帧 watchdog + `BotDriver` 抽象接口 — 任意游戏可用。
- **C 层（智能大脑）**：VLM 接入 `BotDriver`，看 BackBuffer 出动作 — 多游戏无需 game-specific 逻辑。
- **多游戏**：不限当前 FF7R / Batman / DOOM Eternal，新游戏通过 `profiles/<game>.yaml` 上手（声明控制绑定、操作约定、视觉锚点）。

下游消费方（auto-dev）按 G-001 → G-007 顺序实现，A 层先于 C 层（C 是 A 的 plug-in）。

---

## Goals

### G-001: BotDriver 抽象接口（A 层基石）

`tools/auto_play/` 新模块定义 `BotDriver` 接口：每帧 / 每决策周期产出一个 `Action`，由通用 `InputBackend` 注入到游戏。Driver 与输入后端解耦，与游戏 profile 解耦。

**Acceptance criteria:**
- [ ] 定义 Python 抽象基类 `BotDriver` with method `next_actions(observation: Observation) -> list[Action]`
- [ ] `Observation` 至少含 `frame_bgr: np.ndarray | None`, `timestamp: float`, `profile: GameProfile`
- [ ] `Action` 至少含 `kind: 'key' | 'mouse' | 'gamepad'`, `payload: dict`, `duration_ms: int`
- [ ] 至少 2 个具体实现注册到工厂：`KeepAliveDriver`（G-003）、`VLMDriver`（G-005）
- [ ] CLI: `--driver {keep-alive,vlm}` 选定（默认 `keep-alive`）

### G-002: 输入注入后端（A 层）

提供统一的输入注入栈：键鼠（SendInput / Win32）+ 虚拟手柄（ViGEm Bus driver via `vgamepad` Python 包）。Driver 输出的 `Action` 不关心后端选择，profile 决定使用哪种通道。

**Acceptance criteria:**
- [ ] `InputBackend` 实现键盘按键、鼠标移动/点击、手柄按键 + 摇杆双轴扰动
- [ ] 注入的输入**完全等同于人类输入** — 与现有 `inputs.jsonl` 记录通路无差别（即 GetKeyboardState / GetCursorPos / XInput 都能读到）
- [ ] ViGEm 不可用（驱动未装）时自动 fallback 到键鼠通道并 warn，不 crash
- [ ] FF7R / Batman / DOOM Eternal 各跑通 ≥ 30 分钟无人输入异常

### G-003: KeepAliveDriver — 通用哑 bot（A 层）

最小可用的 driver：按 profile 中声明的控制绑定，循环执行"前进 / 转向 / 互动 / 攻击"原语；不看屏幕。任意游戏装上即用。

**Acceptance criteria:**
- [ ] 默认行为序列：前进 3-5s → 随机转向 0.5-1s → 偶发攻击 / 互动 → 偶发跳跃 → 重复
- [ ] 序列参数（步长 / 频率 / 抖动）可在 profile 配置
- [ ] 输入 event 频率 ≥ 1 Hz
- [ ] 默认 profile (`profiles/_default.yaml`) 提供 W/A/S/D + 鼠标 + 空格 / E 互动 — 适用大多数 FPS / 第三人称游戏

### G-004: 静帧 / Idle Watchdog（A 层，不依赖 driver）

独立线程每 N 秒采样 BackBuffer 与 N 秒前比像素 diff；连续 ≥ M 次 < 阈值 → 触发恢复序列（profile 声明的"恢复输入" — 默认 ESC、A、左摇杆扰动）。

**Acceptance criteria:**
- [ ] 采样周期、diff 阈值、连续触发次数全部可配置（默认 5s / 1% diff / 2 次）
- [ ] 触发恢复时写一行 `auto_play.log`：时间戳、diff 值、注入了哪些恢复 input
- [ ] 与 Driver 并行运行，不阻塞决策线程
- [ ] 测试：模拟"游戏 minimize"场景能 30s 内识别并触发

### G-005: VLMDriver — 智能大脑（C 层）

实现 `BotDriver` 子类，订阅 BackBuffer 子采样图（≤ 512 长边）以 1-2 Hz 调用 VLM，让模型输出动作计划 JSON，解析为 `Action[]` 序列。

**Acceptance criteria:**
- [ ] 至少支持 2 个 VLM provider（推荐 Anthropic Claude Haiku 4.5 + Google Gemini 2.5 Flash），通过环境变量 `AUTO_PLAY_VLM_PROVIDER` 切换
- [ ] 输出格式：JSON Schema 严格验证，schema 至少含 `{ actions: [{ kind, payload, duration_ms }], reasoning?: string }`
- [ ] System prompt 由 profile 拼装提供"该游戏的操作约定"段（如 FF7R: "X 互动 / 方块攻击 / R3 锁定"）
- [ ] 决策延迟 P95 ≤ 1.5s
- [ ] schema 校验失败 → 当帧丢弃 + log，下一帧重试，不让 driver 挂
- [ ] **prompt caching 必须启用**（system prompt + profile 是稳定段，应被缓存以降本 — 见 USER.md 全局 RTK 与 claude-api skill 期望）

### G-006: VLM 成本与配额控制（C 层安全网）

VLM 调用必须可观测、可降级，避免一夜烧掉一个月预算。

**Acceptance criteria:**
- [ ] CLI: `--vlm-budget-per-hour <N>` 限定每小时最多 N 次 VLM 调用（默认 60）
- [ ] CLI: `--vlm-budget-total-usd <N>` 单次 capture session 累计花费上限（默认 5）
- [ ] 触发任一上限：自动 fallback 到 `KeepAliveDriver` 并 log，不退出 capture
- [ ] 累计花费、调用次数、平均延迟、cache 命中率写入 `auto_play_cost.log`
- [ ] cost 估算用 provider 公开费率表 + 实际 token usage（不要硬编码）

### G-007: 多游戏 Profile 系统（first-class）

新游戏通过 `profiles/<game>.yaml` 上手 — **不改 Python 代码**。Profile 声明：控制绑定、输入通道偏好、KeepAlive 序列参数、watchdog 参数、VLM 操作约定段。

**Acceptance criteria:**
- [ ] Profile schema 定义在 `tools/auto_play/profile.py`，YAML 加载 + Pydantic 校验
- [ ] 仓库内置 profile：`_default.yaml` + `ff7r.yaml` + `doom_eternal.yaml` + `batman_ak.yaml`
- [ ] 每个 profile ≤ 80 行 YAML，新游戏 onboarding ≤ 30 分钟（含手动测一遍）
- [ ] CLI: `--profile <name>`（不指定时按游戏 exe 名 fuzzy match `profiles/*.yaml`，匹配不到回落到 `_default.yaml` + warn）
- [ ] `profiles/README.md` 文档化字段含义 + 新游戏接入步骤

### G-008: 长时无人值守稳定性

可启动后离开 8 小时回来仍在采集，数据未损坏。

**Acceptance criteria:**
- [ ] 主进程持续 `SetThreadExecutionState(ES_CONTINUOUS|ES_DISPLAY_REQUIRED|ES_SYSTEM_REQUIRED)` 阻止系统睡眠
- [ ] 8h 通宵测试在至少 1 个目标游戏跑通：BMP/EXR 无截断 + `inputs.jsonl` 无截断 + HDF5 pack 通过
- [ ] driver / watchdog / VLM 调用任一异常不让 capture 主流程退出（catch + log + 继续）
- [ ] Ctrl+C / F9 / 父进程 kill 都能 graceful 收尾（驱动 stop、释放 ViGEm、写 final log）

---

## Constraints

- **平台**: Windows 11（与现有 unicap 一致）。无 Linux/Mac 适配需求。
- **Python**: 沿用项目现有 `uv` 管理，新依赖加入 `pyproject.toml`。预期新增：`vgamepad`（ViGEm wrapper）、`anthropic`、`google-genai`，可选 `openai`。
- **不改 C++ addon**：addon (`frame_capture.cpp`) 完全不动 — 所有 auto-play 逻辑活在 Python 层。Observation 来自 unicap 已有的 BackBuffer.bmp 写入路径（不引入新 IPC）。
- **不改 capture FPS**：30 FPS 采集是 ML 数据规范，auto-play 决策频率（≤ 2 Hz）不与之耦合。
- **预算上限**: 每次 capture session 默认 ≤ $5（G-006 强制）。Sponsor 接受单晚 8h 上限 $20-40 的量级（与 600/h 调用 × $0.5/100 calls 一致）。
- **反作弊**: 不规避主流反作弊 — 若游戏检测到合成 input 直接踢人/封号，是 profile 作者的取舍，本机制不主动绕过。明确 out-of-scope。

## Non-Goals

- **不做 RL / 自我改进闭环** — driver 是单向决策，无在线学习。
- **不做本地 VLM 推理** — 不部署本地大模型（成本/复杂度不值；C 层就是云 API）。
- **不做 OCR / 文字识别 pipeline** — VLM 自带文字理解，不引入独立 OCR。
- **不做剧情推进 / 任务完成** — bot 只产生"在场景中"的 (s, a) 数据；不打 boss、不刷主线、不解谜。
- **不做声音 / 音频反馈** — 仅看图（BackBuffer.bmp）。
- **不做 30 Hz 反射动作** — VLM 决策天然 1-3 Hz；FPS / 节奏游戏的"瞬时反应"不是目标场景。
- **不重写现有 input recording** — `inputs.jsonl` 写入路径不动，auto-play 注入的 input **走同一通路**（Win32 SendInput → GetKeyboardState 读到），不区分人 vs bot。
- **不做 GUI** — 全 CLI 工具。
- **不规避反作弊** — 详见 Constraints。

## Scope Boundary

**In scope（auto-dev 必须实现）**:
- A 层全套：BotDriver 抽象、InputBackend、KeepAliveDriver、Watchdog、profile system
- C 层 VLMDriver + 至少 2 provider + 成本控制
- 4 个 built-in profile（_default + 3 当前测试游戏）
- `--auto-play / --driver / --profile / --vlm-budget-*` CLI
- 8h 通宵稳定性
- 文档：`profiles/README.md` + `CLAUDE.md` 更新章节

**Out of scope（拒绝接 PR / 单独立项）**:
- 任何 game-specific 状态机（"打到第二章 boss" 这类剧情逻辑）
- 反作弊绕过
- 多机器分布式 capture orchestration
- Web UI / dashboard
- 数据质量评分 / 自动数据筛选（下游 ML pipeline 的事）
- 手机 / 主机游戏（仅 PC Windows）

## Usage Scenarios

### S-001: 通宵采集（A 层路径，无 API 费用）

- **Persona:** 数据工程师（sponsor 自己），睡前要启动 8h 采集
- **Goal:** 醒来时 dataset 多 ~860k 帧（30 FPS × 8h × 0.7 有效率）
- **Steps:**
  1. 手动把游戏读到一个不会卡 / 不会死透的场景（如 FF7R 七番街、DOOM 关卡前期）
  2. `uv run main.py launch --game-path <exe> --auto-play --driver keep-alive --duration 8h`
  3. 游戏起来后按 F8 启动 capture（survey 自动跑首次）
  4. Sponsor 离开
  5. 第二天看 `auto_play.log` + `dataset/.../<ts>/frames/` 数 + watchdog 触发统计
- **Success condition:** 有效采集时间 ≥ 6h（容忍 25% 卡死/死亡丢失）；BMP 计数 ≥ 600k；HDF5 pack 通过

### S-002: 接入新游戏（profile-only workflow）

- **Persona:** 数据工程师，要为一款 DX12 新游戏 *Game X* 加自动采集
- **Goal:** 不改 Python 代码、30 分钟内让新游戏能跑 keep-alive driver
- **Steps:**
  1. 复制 `profiles/_default.yaml` → `profiles/game_x.yaml`
  2. 进游戏一次手动确认操作绑定（W 前进 / 鼠标视角 / E 互动 等），改 YAML 的 `controls.*` 段
  3. 改 `keep_alive.sequence` 段（如这游戏是 RTS 没移动键 → 改成"间歇性鼠标点击"）
  4. 改 `vlm.game_instructions`（一段中文/英文操作说明，给 VLM 看）
  5. `uv run main.py launch --game-path <Game X exe> --auto-play --profile game_x` 跑 30 分钟测试
  6. 看 `auto_play.log` 调参数；满意后 commit 进仓库
- **Success condition:** 新游戏跑 30 分钟 keep-alive 不卡死；watchdog 触发 ≤ 3 次；`inputs.jsonl` 有持续输入

### S-003: VLM driver 通宵 DOOM Eternal

- **Persona:** 数据工程师，验证 C 层在 Vulkan 游戏可用性
- **Goal:** 通宵采集 ≥ 6h，bot 在场景内 ≥ 80% 时间，总花费 ≤ $20
- **Steps:**
  1. 设置 `ANTHROPIC_API_KEY` 环境变量
  2. `uv run main.py launch --game-path "...DOOMEternalx64vk.exe" --ui-mode ui --auto-play --driver vlm --profile doom_eternal --vlm-budget-per-hour 90 --vlm-budget-total-usd 20`
  3. F8 启动 capture（DOOM Eternal 走 `--ui-mode ui`，无 survey）
  4. Sponsor 离开
  5. 第二天看：`auto_play_cost.log`（总花费 / cache 命中率）+ video.mp4 抽样看 bot 表现 + frames 数
- **Success condition:** 6h+ 采集；bot 持续在游戏内活动（非死亡/菜单）≥ 80% 时间；总花费 ≤ $20

### S-004: VLM 配额超限自动降级

- **Persona:** Sponsor 误设过低预算（`--vlm-budget-total-usd 1`）
- **Goal:** capture 不退出，自动降级
- **Steps:**
  1. 启动 VLM driver，1 美元额度跑约 30 分钟即耗尽
  2. 系统检测到超限 → 输出 `[AUTO-PLAY] VLM 预算耗尽，降级到 KeepAliveDriver` → 切 driver 继续
- **Success condition:** capture 不中断；剩余时间用 keep-alive 跑完；log 清晰记录切换时刻

---

## Open Questions

| # | Question | Status | Resolution |
|---|----------|--------|-----------|
| Q1 | 数据下游用途（无监督预训练 / IL / RL）会反过来影响 bot 数据质量需求吗？ | deferred | 当前不做差异化；G-008 通过测时长保证体量，质量交给下游筛选 |
| Q2 | VLM provider 优先级 — Anthropic vs Google? | deferred | 默认 Anthropic Claude Haiku 4.5（仓库已有 RTK / claude-api skill 偏好），Google Gemini 2.5 Flash 作 fallback / 对比 |
| Q3 | 8h 通宵 vs 多日连续？ | resolved | 验收只要求 8h（G-008）；多日是 stretch goal，不强制 |
| Q4 | ViGEm 驱动 sponsor 机器是否已装？ | deferred | G-002 fallback 到键鼠，安装由 dev agent 在 setup 文档里写明 |
| Q5 | profile YAML 哪些字段强制 / 可选？ | deferred | dev agent 负责定 schema，参考 `profiles/_default.yaml` 兜底 |
| Q6 | watchdog 触发恢复后若仍静帧（如游戏 freeze）是否要重启游戏进程？ | deferred | 第一版只 log + 继续 watchdog；自动重启游戏作 stretch（涉及读 `--game-path` 重新 launch + Vulkan layer 注册重置） |
| Q7 | auto-play 注入的 input 是否要在 `inputs.jsonl` 打个标记区分 bot vs 人类？ | deferred | 默认**不区分**（Non-Goals 已声明）。如下游需要，加 `inputs.jsonl` 字段 `source: 'bot' \| 'human'` 是 1 行改动，但当前 sponsor 未要求 |

---

## Acceptance Test Plan（auto-test 消费方使用）

按 G-001 → G-008 顺序验收。每个 G 都有可执行/可观测的 criteria。验收测试集至少覆盖：

1. **单元 / 集成**：BotDriver 接口契约、InputBackend 注入正确性、profile YAML 校验
2. **3 游戏短测**：FF7R / Batman / DOOM Eternal 各 30 分钟 keep-alive 跑通
3. **新游戏 onboarding**：随便选一款仓库 profile 之外的 PC DX/Vulkan 游戏，验证 S-002 流程 30 分钟内通
4. **VLM 短测**：Claude Haiku 4.5 + Gemini 2.5 Flash 各跑 1h，schema 错误率 ≤ 5%
5. **8h 通宵**：FF7R + keep-alive 跑通宵，HDF5 pack 通过
6. **降级测试**：S-004（成本超限自动 fallback）

---

## 实现优先级（建议给 auto-dev）

1. G-001 + G-002 + G-007（基础设施 + profile 系统）— 无此则余皆空中楼阁
2. G-003 + G-004（KeepAlive + Watchdog）— 完成 A 层，已有"无人采集 v1"
3. G-008（稳定性测试）— 验证 A 层后才接 C 层
4. G-005 + G-006（VLM driver + 成本控制）— C 层
5. README / CLAUDE.md 文档同步

---

> **下游消费方**：本文是 auto-dev / dev-add 的输入。开发完成后请回到本文勾选 Acceptance criteria。
