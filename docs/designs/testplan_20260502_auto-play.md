# TestPlan: 自动玩游戏机制 — A 层 + C contracts

**Date:** 2026-05-02
**Scope:** docs/req/auto-play.md G-001 / G-002 / G-003 / G-004 / G-007 + G-008 短测 + VLMDriver 占位
**Out of scope:** G-005 / G-006（VLMDriver 实际实现 + 成本控制）

## 1. 测试金字塔

| 层级 | 范围 | 通过标准 |
|------|------|--------|
| Capability | 单个 submodule 行为 | 100% Must Have |
| Integration | submodule 之间数据流 | InputBackend ↔ Driver、Profile ↔ Runner、Watchdog ↔ Frames 各 ≥ 1 |
| E2E | 完整用户旅程 | S-001 / S-002 / S-004 各 happy + error |

---

## 2. Capability — 各 submodule

### 2.1 `BotDriver` ABC + dataclass (`tools/auto_play/driver.py`)

**功能**：定义 `BotDriver` 抽象类、`Action`、`Observation` 数据契约。

**Boundary**：纯接口定义；不含具体注入逻辑。

**Forbidden Zone**：
- ❌ 不得在 `Action` 内嵌入 `InputBackend` 实例（保持解耦）
- ❌ 不得让 `BotDriver.next_actions()` 直接调系统 API（必须经 `InputBackend`）
- ❌ 不得让接口签名引入 provider-specific 字段（如 `claude_api_key` — 这属 VLM driver 内部）

**Must Have**:
- M1: 子类实现 `next_actions(observation)` 即可被工厂注册
- M2: `Action` dataclass 字段 = `kind`(Literal["key","mouse","gamepad"]) / `payload`(dict) / `duration_ms`(int)
- M3: `Observation` dataclass 字段 = `frame_bgr`(np.ndarray | None) / `timestamp`(float) / `profile`(GameProfile)

### 2.2 `InputBackend` (`tools/auto_play/input_backend.py`)

**功能**：把 `Action` 翻译成 OS 级输入注入（SendInput 键鼠 + ViGEm 手柄）。

**Boundary**：
- 处理：键盘按键 down/up/click、鼠标移动/点击、虚拟手柄按键 + 摇杆双轴扰动
- 不处理：游戏特定逻辑、状态机、决策

**Forbidden Zone**：
- ❌ 不得在 ViGEm 不可用时 raise（必须 fallback 到键鼠 + warn）
- ❌ 不得在没拿锁的情况下并发调 SendInput（输入乱序风险）
- ❌ 不得注入 reserved_keys（profile 声明的，含 F8 / F9）

**Must Have**:
- M1: `inject(action)` SendInput 一次按键 → `GetAsyncKeyState` 在调用后能读到 down 状态
- M2: ViGEm import 失败时构造 `InputBackend` 不 raise；`gamepad_available` 属性 = False；profile 要求 gamepad 时降级用键盘等价键 + warn 一次
- M3: 并发 10 个线程各注入 100 次 → 所有 down/up 配对，无 stuck key（lock 串行化）
- M4: 注入 reserved_keys（如 F8）→ `inject` raise `ValueError` 并 log

### 2.3 `GameProfile` (`tools/auto_play/profile.py`)

**功能**：从 YAML 加载游戏控制 + 操作约定 + watchdog 参数。

**Boundary**：YAML schema 校验、字段查询、按 exe 名 fuzzy match 找 profile 文件。

**Forbidden Zone**：
- ❌ 不得让 missing 必填字段静默走默认（必须报错，指向具体 YAML 行号或 key 名）
- ❌ 不得允许 reserved_keys 与 controls 冲突（schema validate 阶段拦）
- ❌ 不得在加载时跑任何 game-specific 脚本（profile 是声明式，不含逻辑）

**Must Have**:
- M1: 加载 `profiles/_default.yaml` 返回 `GameProfile` 实例，所有字段非 None
- M2: 加载缺字段的 YAML → raise 含字段名 + 文件路径的 error
- M3: `load_profile("ff7r")` 直接命中 `profiles/ff7r.yaml`
- M4: `load_profile("ff7remake_", fallback=True)` 走 fuzzy match → 命中 `ff7r.yaml`
- M5: `load_profile("totally_unknown_game", fallback=True)` 回落 `_default.yaml` + warn
- M6: 4 个内置 profile 全通过 schema 校验

### 2.4 `KeepAliveDriver` (`tools/auto_play/keep_alive.py`)

**功能**：按 profile 的 `keep_alive.sequence` 出循环 Action。

**Boundary**：按时间游标推进；无 vision；无状态机。

**Forbidden Zone**：
- ❌ 不得 hard-code 任何按键名（必须从 profile 读）
- ❌ 不得让序列退出（capture 期内 `next_actions` 必须每次返回非空）
- ❌ 不得读屏幕（属 watchdog 的事）

**Must Have**:
- M1: `next_actions(obs)` 调 100 次 → 至少返回 100 次非空 list（不退出）
- M2: 一段 sequence 跑完后从头循环
- M3: 输出 Action 的按键名只在 `profile.controls.*` 中存在
- M4: 输入频率 ≥ 1 Hz（按 sequence step duration 估算）

### 2.5 `StaticFrameWatchdog` (`tools/auto_play/watchdog.py`)

**功能**：后台采样 BackBuffer.bmp，连续静帧触发恢复 Action 序列。

**Boundary**：仅看 frames_dir 下最新 BMP；只在像素 diff 判断；不做语义识别。

**Forbidden Zone**：
- ❌ 不得阻塞调用线程（必须独立 daemon thread）
- ❌ 不得 raise 出 frames_dir 暂时为空 / BMP 读失败时（log + 跳过该轮）
- ❌ 不得在停止后继续采样（清理 thread）

**Must Have**:
- M1: 模拟 frames_dir 写入两张相同 BMP（连续 N 次）→ 连续 ≥ 2 次触发后调度 recovery action（profile 声明的）
- M2: 写入交替不同 BMP → 不触发
- M3: frames_dir 完全空 / 无新 BMP → log 一行 + 不触发 recovery
- M4: `stop()` 后 thread 在 ≤ 2s 内退出
- M5: 触发记录写入 `auto_play.log`（时间戳 + diff 值）

### 2.6 `VLMDriver` 占位 (`tools/auto_play/vlm_driver.py`)

**功能**：本 release 仅签接口；构造或调用 `next_actions` 抛 NotImplementedError。

**Boundary**：占位类必须能被 import + 被 factory 识别。

**Forbidden Zone**：
- ❌ 不得引入 `anthropic` / `google-genai` 等 SDK 依赖
- ❌ 不得让占位"看起来可用"（必须明确报错，不能默默返回空 list）
- ❌ 不得改 BotDriver 接口签名（C 层接入时不许动 A 层）

**Must Have**:
- M1: `from tools.auto_play import VLMDriver` 不 raise
- M2: `VLMDriver(profile, ...)` 构造时 raise NotImplementedError，错误信息含 G-005 跳转引用
- M3: factory `create_driver("vlm", ...)` raise NotImplementedError 同上

### 2.7 `AutoPlayRunner` (`tools/auto_play/runner.py`)

**功能**：编排 driver + watchdog + lifecycle；start / stop 幂等。

**Boundary**：
- 启动 driver 决策 thread + watchdog thread
- 注入 driver 输出的 Action（经 InputBackend）
- stop 时 join 全部 thread + 释放 ViGEm

**Forbidden Zone**：
- ❌ 不得在 stop 后 leak thread / ViGEm 虚拟手柄
- ❌ 不得让 driver 的 exception 杀 capture 主流程（catch + log + continue）
- ❌ 不得让 driver / watchdog 各自直调 SendInput（必须经共享 InputBackend）

**Must Have**:
- M1: `start()` 后 ≥ 5s 内 InputBackend 被 driver 注入 ≥ 5 次
- M2: `stop()` 在 ≤ 3s 内全 thread join 完毕
- M3: `stop()` 调用 2 次不 raise（幂等）
- M4: driver `next_actions` raise 异常 → runner log + 续跑（不挂）
- M5: ViGEm 已分配时 stop 后释放（`pad.disconnect()` 被调用）

---

## 3. Validation Plan（feature-level）

| 编号 | 必须满足 | 验证方式 |
|------|---------|---------|
| V-001 | `--auto-play` 不传，launch 行为零回归 | 跑一次 `launch` 默认路径，console output diff 与不带 flag 的版本一致（除 unicap 版本号） |
| V-002 | `--auto-play --driver keep-alive --profile ff7r` 启动后 InputBackend 在 5s 内被注入 ≥ 5 次 | log grep `[AUTO-PLAY] inject` 计数 |
| V-003 | `--auto-play --driver vlm` 立即报清晰错误 + 退出非零 | `subprocess.run` retcode != 0 + stderr 含"VLMDriver 是 C 层" |
| V-004 | F8 / F9 不被 bot 误触 | 跑 60s keep-alive，监听 F8/F9 事件 → 0 次注入 |
| V-005 | inputs.jsonl 含 bot 注入的 key（如 'W'）的 down 帧 | 跑 30s 后 grep `inputs.jsonl`，bit-position 对应 W 的 byte ≥ 0x80 ≥ 100 次 |
| V-006 | watchdog 在游戏 minimize 模拟下 30s 内触发 ≥ 1 次 recovery | 把 frames_dir 写入相同 BMP 60 次 → log grep `[WATCHDOG] static-frame` |
| V-007 | 长时短测：30 分钟 keep-alive 跑通宵不崩 | 跑 30min，无 Python traceback；BMP 数 ≥ CAP_FPS × 30 × 60 × 0.7 |
| V-008 | ViGEm 缺失时不 crash | 卸载 vgamepad（venv 内）后启动 → 仅 warn + 用键盘通道 |
| V-009 | 4 个内置 profile 加载全 OK | `python -c "from tools.auto_play import load_profile; [load_profile(n) for n in ['_default','ff7r','doom_eternal','batman_ak']]"` 无 raise |
| V-010 | profile schema 错误信息能定位 | 制造一个缺字段的 YAML → error 含字段名 + 文件路径 |

## 4. Failure & Edge Cases

| 失败模式 | 期望行为 |
|----------|---------|
| ViGEm Bus 未装 | InputBackend 软降级；profile 要求 gamepad 时 warn 一次然后用键盘 |
| profiles/ 目录缺失 | `load_profile` raise 清晰错误"profiles/ not found"，指向 ROOT |
| YAML 解析失败 | raise 含文件路径 + YAMLError 原始消息 |
| frames_dir 中无 BMP（capture 还没产帧） | watchdog 等到首帧才开始判断；前 ≤ 30s 不触发 recovery |
| driver 内部 bug 抛 exception | runner catch + log full traceback + 续 5s 后重试 |
| capture stop 时 driver 卡死 | runner.stop 设超时 3s，强制 set thread quit_evt + join(3s)；超时 warn 但不 raise |
| Steam 重启游戏 → 进程换 PID | auto-play 不感知（不绑 PID）；继续注入到当前 foreground 游戏窗口；如未在前台 → SendInput 静默不生效（已知限制，未来通过 SetForegroundWindow 改善 — 不在本 release） |
| 用户在 auto-play 期间手动操作 | 没有冲突保护（Non-Goals）；用户输入与 bot 输入按时间叠加 |

## 5. Audit / Logs

**必须 log**：
- 启动：`[AUTO-PLAY] driver=keep-alive profile=ff7r gamepad=vigem_ok`
- 每次 driver 出 Action（debug 级）：`[AUTO-PLAY] inject kind=key payload={'vk':'W'} duration_ms=300`
- watchdog 触发：`[WATCHDOG] static-frame diff=0.003 → injected recovery sequence`
- runner stop：`[AUTO-PLAY] stop: driver_thread joined, watchdog joined, vigem released`

**不得 log**（隐私 / 安全）：
- 完整 keyboard buffer（与 capture_all 保持一致；只 log Action 类型）
- 用户系统路径（profile name OK，绝对路径 only on debug）
- VLM API key（即使 C 层未接，预留时也明确"never log key"）

**输出位置**：`%TEMP%/unicap/auto_play.log`（与 unicap.log 同目录）；rolling 5MB × 3 文件。

## 6. Integration Tests（cross-submodule）

| 编号 | A → B | 验证 |
|------|-------|------|
| I-1 | `KeepAliveDriver` → `InputBackend` | driver 出的每个 Action.kind 都被 backend 接收 + 翻译为 SendInput；100 次无丢 |
| I-2 | `Watchdog` → `InputBackend` | 静帧触发后 backend 收到 profile 声明的 recovery actions（如 ESC） |
| I-3 | `Profile` → `KeepAliveDriver` | profile.keep_alive.sequence 改了 → driver 出的 Action 跟着变 |
| I-4 | `Profile` → `InputBackend` | profile.reserved_keys 拒绝 → backend 注入 reserved key raise |
| I-5 | `Runner` → `Driver` + `Watchdog` + `InputBackend` | 启停链路完整；mock 三者验证调用次数 |
| I-6 | `main.py:_run_capture` → `Runner` | `--auto-play` flag → runner.start 被调用；capture stop → runner.stop 被调用 |
| I-7 | bot SendInput → `capture_all._thread_input` 录入 | bot 注入 W 30 次 → inputs.jsonl 中有 ≥ 30 帧 W 状态为 down |

## 7. E2E User Flows

### E2E-1: keep-alive 通宵采集（happy path）

**Goal:** Sponsor 通宵采集 FF7R 并第二天看数据
**Flow:**
1. 手动读档到一片可走动区域 → 验证：FF7R 在游戏中
2. `uv run main.py launch --auto-play --profile ff7r`
   - 验证：console 出 `[AUTO-PLAY] driver=keep-alive profile=ff7r`
   - 验证：FF7R 起来不闪退
3. 按 F8 启动 capture（survey 自动跑）
   - 验证：survey 完成 + capture 进入
4. 离开 30 分钟（短测代替 8h）
   - 验证：BMP 数 ≥ 30 × 60 × 30 × 0.7 = 37800
   - 验证：`auto_play.log` 含连续 inject 行
5. 按 F9 停止
   - 验证：capture 收尾正常 + auto-play 干净停
6. 检查 `inputs.jsonl` 含 bot 输入

**Success:** capture session 30 分钟 ≥ 600s 有效采集，HDF5 pack 通过

### E2E-2: 接入新游戏（happy path）

**Goal:** 加 1 个新游戏 profile，30 分钟内能跑 keep-alive
**Flow:**
1. 复制 `profiles/_default.yaml` → `profiles/<new_game>.yaml`
   - 验证：YAML 加载成功
2. 改 `controls.move_forward` 等字段
3. `uv run main.py launch --game-path <exe> --auto-play --profile <new_game>`
   - 验证：profile 加载成功 + driver 启动
4. 跑 5 分钟
   - 验证：bot 持续注入；watchdog 不连续触发（说明游戏在动）

**Success:** 5min 跑通 + log 干净

### E2E-3: VLM driver 提前选择报错（error path）

**Goal:** 用户错选 vlm driver，得到清晰指引
**Flow:**
1. `uv run main.py launch --auto-play --driver vlm`
   - 验证：进程退出 retcode != 0
   - 验证：stderr 含"VLMDriver 是 C 层（智能大脑），本 release 仅含 A 层骨架"
   - 验证：错误指向 `docs/req/auto-play.md G-005/G-006`

**Success:** 用户立即知道为什么 + 怎么继续

### E2E-4: ViGEm 缺失降级（error path）

**Goal:** 没装 ViGEm 时 auto-play 仍能用键鼠通道
**Flow:**
1. 临时让 `vgamepad` import 失败（rename 模块）
2. `uv run main.py launch --auto-play --profile ff7r`
   - 验证：console 出 `[AUTO-PLAY] gamepad=unavailable (vgamepad 未装), 降级键鼠`
   - 验证：driver / watchdog 启动正常
3. 跑 1 分钟
   - 验证：inputs.jsonl 含键盘 input

**Success:** 不 crash，fallback 工作

### E2E-5: 静帧 watchdog 触发（happy path of recovery）

**Goal:** 验证 watchdog 在游戏卡顿时自动 recover
**Flow:**
1. 启动 `--auto-play --auto-play-debug`
2. 模拟 frames_dir 写入相同 BMP 30 次（`scripts/test_static_frame.py` helper）
   - 验证：watchdog 在 ≤ 30s 内 log `static-frame → recovery`
   - 验证：recovery action 注入 ESC 1 次

**Success:** recovery 日志干净；不 crash

## 8. E2E Coverage Matrix

| Capability | E2E Goals | Covered? |
|------------|-----------|----------|
| Driver factory + dispatching | E2E-1, E2E-3 | ✓ |
| Keep-alive 行为循环 | E2E-1, E2E-2 | ✓ |
| Profile 加载 + fuzzy match | E2E-1, E2E-2 | ✓ |
| Profile schema 错误处理 | (capability test V-010 + I-4) | △ — capability-only OK，无独立 E2E |
| InputBackend 键鼠注入 | E2E-1, E2E-4 | ✓ |
| InputBackend ViGEm 注入 | E2E-1（如 ViGEm 装了） | ✓ |
| InputBackend ViGEm 降级 | E2E-4 | ✓ |
| Watchdog 静帧触发 | E2E-5 | ✓ |
| Watchdog 不误触 | (capability M2) | △ — capability OK |
| Runner 启停幂等 | E2E-1（隐含 stop 链路） | ✓ |
| VLMDriver 占位报错 | E2E-3 | ✓ |
| main.py CLI 集成 | E2E-1, E2E-2, E2E-3, E2E-4 | ✓ |
| 长时稳定性（30min 短测） | E2E-1 | ✓ |
| inputs.jsonl bot input 落入 | E2E-1（V-005 验证） | ✓ |

无 ✗ 缺口。两个 △ 标记是"capability-only 验证已足够，无需 E2E"的合理省略。

## 9. Security / Token Constraints

- 不包含 API key（C 层占位，未引入 SDK）
- log 中绝不写完整 keyboard buffer（保持与 capture_all 一致 policy）
- profile YAML 由用户提供，不远程加载
- ViGEm 是 user-mode 注入（非内核 hook），无安全等级提升风险
- SendInput 是合法 OS API，无规避反作弊（per Constraints）

## 10. Environment Spec

| Field | Value |
|-------|-------|
| `type` | local Windows 11 |
| `exec` | sponsor 直接在 D:\dev\unicap.git\ 下执行 `uv run main.py launch ...` |
| `workdir` | `D:\dev\unicap.git` |
| `ports` | n/a |
| `env_vars` | `ANTHROPIC_API_KEY` (仅 C 层用，本 release 不需要)；`AUTO_PLAY_DEBUG=1` 可选 |
| `auto_provisioned` | false — 用户已在 Windows 11 + VS2022 + uv 环境（HANDOFF.md） |

**E2E-1 / E2E-2 / E2E-5** 需要游戏实机（FF7R 已知 sponsor 有）。
**E2E-3 / E2E-4** 不需要游戏，本机跑 CLI 即可（CI-friendly）。

## 11. Quality Gate

- [x] 每个 Must Have 是可观察的（input → output 明确）
- [x] 每个 Forbidden Zone ≥ 3 redlines（达标）
- [x] submodule 边界不重叠（Driver 决策、InputBackend 注入、Watchdog 监控、Runner 编排，职责互斥）
- [x] cross-submodule 数据流均有 integration test（I-1 ~ I-7 覆盖）
- [x] 每个主用户目标有 ≥ 1 E2E + happy + error path
- [x] 每个 E2E step 有验证方法（已用 "验证：" 标注）
- [x] coverage matrix 无 ✗ gap
- [x] 环境为 local Windows，sponsor 自行执行 E2E 实机部分

## 12. 中文摘要

测试金字塔三层：
- **Capability**（per submodule）— 7 个 submodule 共 ~25 个 Must Have（M1-M5 平均 4 个）
- **Integration**（cross-submodule）— 7 条数据流测试覆盖 driver↔backend、profile↔driver、watchdog↔backend、main.py↔runner、bot SendInput↔inputs.jsonl 等关键边界
- **E2E**（用户旅程）— 5 个 flow（happy 3 + error 2），覆盖通宵采集、新游戏接入、VLMDriver 报错、ViGEm 降级、watchdog 触发

10 个 Validation 项中 V-001（零回归）+ V-007（30min 短测）是验收硬条件。E2E-1 / E2E-2 / E2E-5 需 sponsor 实机配合；E2E-3 / E2E-4 在 CI 也能跑。Coverage matrix 无 gap。
