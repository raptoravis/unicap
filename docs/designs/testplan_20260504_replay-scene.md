# TestPlan: 游戏场景自动化复现（录制 + 回放）

**Date:** 2026-05-04
**Scope:** docs/req/replay-scene.md G-001 ~ G-006
**Out of scope:** v2.0 VLM 兜底（C 阶段）；中段续跑（v1.1）；live-game 30min E2E（sponsor 验收）

## 1. 测试金字塔

| 层级 | 范围 | 通过标准 |
|------|------|--------|
| Capability | 单 submodule 行为 | 100% Must Have（offline 可跑） |
| Integration | submodule 间数据流 | recorder→schema, player→schema, player→backend, player→sync, main→survey 各 ≥ 1 |
| E2E | 完整用户旅程 | E2E-1 ~ E2E-4 各 happy + error；live-game 留 sponsor |

`scripts/verify_replay.py` = 所有可 offline 跑的 capability + integration + E2E checks 单文件入口（仿 `verify_auto_play.py`）。Sponsor 一条命令跑全部。

## 2. Capability — 各 submodule

### 2.1 `tools/replay/sync_match.py`

**功能**：dHash + hamming + 主循环 `wait_for_match`。

**Boundary**：纯函数 + 一个轮询 helper；不直接读 sync 配置（threshold/timeout 由调用方传）。

**Forbidden Zone**：
- ❌ 不得在 `dhash` 内做磁盘 IO（接 ndarray，I/O 由调用方做）
- ❌ 不得依赖 cv2 之外的图像库（项目已有 cv2，避免新 dep）
- ❌ 不得在 `wait_for_match` 内 raise——超时返回 `MatchResult(matched=False, ...)`

**Must Have**:
- M1: `dhash(64x64 uniform_gray_image)` 返回 64-bit int
- M2: `hamming(h1, h1) == 0`；`hamming(h1, ~h1 & 0xFFFFFFFFFFFFFFFF) == 64`
- M3: 同图像 dhash 自比 ≤ 2（允许 JPEG-style 噪声）
- M4: 完全不同的图像（uniform black vs uniform white）→ hamming ≥ 30
- M5: `wait_for_match(ref, frames_dir, threshold=10, timeout=2.0)` 当 frames_dir 不存在 → 返回 `matched=False, reason='no_frames'`
- M6: ref 帧 == 实时帧时 `wait_for_match` 在 ≤ 0.5s 内返回 matched=True
- M7: 单次 dhash 计算 ≤ 50ms on 1920×1080 输入（满足 G-003）

### 2.2 `tools/replay/schema.py`

**功能**：`script.jsonl` event 类型枚举、`meta.json` schema、读写 helper、轻量校验。

**Boundary**：纯数据 + I/O；不含录制 / 回放逻辑。

**Forbidden Zone**：
- ❌ 不得允许未知 `type` 事件 silently 通过（必须报错或 ignore + log）
- ❌ 不得在 schema 校验失败时返回 `None`（必须 raise，调用方决定是否 catch）
- ❌ 不得 hardcode `recorder_version`（从 `__init__.py` 常量读）

**Must Have**:
- M1: `write_meta(path, MetaModel(...))` + `read_meta(path)` round-trip 等价
- M2: `iter_events(jsonl_path)` 流式产出 dict；遇未知 `type` log warn 但继续
- M3: `validate_meta(dict)` 缺 `name`/`window_size`/`recorded_at` 抛 ValueError 含字段名
- M4: 未来兼容：含未识别字段（如 `vlm_fallback_enabled`）不报错（forward compat）
- M5: 校验拒绝 `t_rel < 0` 或 `t_rel` 倒退（events 必须按时序）

### 2.3 `tools/replay/recorder.py`

**功能**：录制 = 后台轮询 GetKeyboardState/GetCursorPos/XInput 的 diff → 出 event；F6 sync；F7 stop；落 script.jsonl + meta.json + sync_NN.bmp。

**Boundary**：
- 处理：键鼠手柄 event diff、F6/F7 hotkey、sync 帧捞取（从 `_recording_frames/` 找最新 BMP 复制）
- 不处理：UI 渲染、注入（recording 不注入；Player 才注入）

**Forbidden Zone**：
- ❌ 不得在主线程阻塞 > 100ms（轮询要异步）
- ❌ 不得让 F6/F7 误触发 inject（recorder 是 read-only）
- ❌ 不得在 sync 失败（_recording_frames/ 为空）时 raise — 要写一条 sync event with `frame=null` + warn
- ❌ 不得吞 KeyboardInterrupt（sponsor Ctrl+C 要能干净停）

**Must Have**:
- M1: 启动后 1s 内开始落 event（无 input 也要写 ts marker）
- M2: 假按键序列（mock GetKeyboardState 返回值）→ 输出对应数量的 key_down/key_up event，t_rel 单调递增
- M3: F6 触发 → 在 sync_scratch_dir 放 mock BMP → recorder 复制为 `sync_01.bmp`，jsonl 多一条 sync event
- M4: F7 触发 → recorder 优雅停（≤ 200ms），返回控制
- M5: 输出 meta.json 含 `window_size`(2-tuple int)、`api`、`recorded_at`(ISO8601)、`recorder_version`
- M6: 录完调 cleanup → `_recording_frames/` 被 rmtree
- M7: 已存在 `_scenes/<name>/` → 提示用户后覆盖（不静默删）

### 2.4 `tools/replay/player.py`

**功能**：读 script.jsonl + meta.json，按时序通过 InputBackend 注入；sync 处暂停 + sync_match；超时 paused → R/Q。

**Boundary**：
- 处理：event → Action 翻译、时序调度（absolute t_rel sleep）、sync 等待、paused 态 R/Q polling、退出码
- 不处理：游戏启动、survey trigger（main.py 编排）

**Forbidden Zone**：
- ❌ 不得在 sync paused 时仍响应游戏内输入按键（R/Q 仅 paused 时监听）
- ❌ 不得在 mouse_move event 用 SendInput 相对 dx/dy（FPS 锁鼠不准；统一用 SetCursorPos 绝对）
- ❌ 不得在 windowed-resolution 与 recording 不一致时 silently 拒绝运行（warn 一次后续按比例 scale）
- ❌ 不得吃 Ctrl+C（要 propagate）

**Must Have**:
- M1: 喂一份 mock script.jsonl（10 个 key event）+ mock InputBackend → `inject` 被按时序调 10 次
- M2: 喂含一个 sync event 的 script + sync ref BMP + mock latest frame == ref → player 不暂停，立即续注入
- M3: sync ref 与实时帧不 match → player 等到 timeout，进入 paused 态 → 模拟按 R → 续注入
- M4: 同上，模拟按 Q → 返回 `ReplayResult(status="user_abort", exit_code=2)`
- M5: 全部 sync 通过 → 返回 `status="reached"`, `exit_code=0`
- M6: window 尺寸不一致 → console 一次性 warn；mouse_move event 的 x/y 按 ratio scale
- M7: `t_rel` 时序漂移 ≤ 100ms 跨 1 分钟回放（用 absolute sleep，不 累加 delta）
- M8: 注入 reserved_keys → `inject` 抛 ValueError → player log warn 但**继续**（不阻断回放）

### 2.5 `main.py` 编排（CLI + 过滤器 + 鼠标归位）

**功能**：argparse 加 `--record-scene` / `--replay-scene`；`_interactive_loop` 前置 dispatch；F6/F7 VK 常量；`cmd_video` / `cmd_pack` 加 `_*` filter；`_run_replay` 调 `SetCursorPos` 归位；G-005 缺 survey 自动跑。

**Boundary**：
- 处理：CLI 解析、生命周期编排（subprocess.Popen 游戏 → record/replay → idle loop）、互斥校验
- 不处理：录制 / 回放算法本身

**Forbidden Zone**：
- ❌ `--record-scene` + `--replay-scene` 同时给 → 启动前 sys.exit
- ❌ `--record-scene` / `--replay-scene` + `--auto-play` 同时给 → 启动前 sys.exit
- ❌ G-005 自动 survey 失败 → 不得继续 replay（exit code 3）
- ❌ `_*` filter 不得影响 `survey/` 子目录（survey/ 没有下划线，原 filter 已排除）

**Must Have**:
- M1: `uv run main.py launch --record-scene foo --replay-scene bar` → exit code != 0，stderr 含"互斥"
- M2: `uv run main.py launch --record-scene foo --auto-play` → exit code != 0，stderr 含"互斥"
- M3: `cmd_video` / `cmd_pack` 扫描含 `_scenes/`、`_recording_frames/`、`survey/`、`20260101_120000/` 的 game-dir → 只处理 `20260101_120000/`
- M4: `_run_replay` 在归位鼠标 + 注入第一个 event 之间，调 `SetCursorPos(w/2, h/2)` 一次
- M5: G-005 mock 缺 survey 缓存 → `_run_replay` 调 `_run_survey`；mock survey 失败 → exit code 3

## 3. Integration

| Pair | 测试 |
|------|------|
| recorder → schema | recorder 落的 jsonl 能被 `iter_events` 全部成功解析、t_rel 单调 |
| player → schema | player 接受 `iter_events` 输出；未知 type 走 warn-and-skip |
| player → InputBackend | mock 5 种 event → backend.inject 收到 5 个对应 Action |
| player → sync_match | mock sync event → 调 `wait_for_match` 一次；超时 → player 进 paused |
| main → survey_mod | mock 缺 survey → main 调 `survey_mod.run`；返回 None → main exit 3 |
| main → ReplayPlayer | main 编排：deploy → start → SetCursorPos → ReplayPlayer.run → exit code propagate |

## 4. E2E User Flows

> Live-game flow 留 sponsor。下面列的是 offline / mocked E2E（`verify_replay.py` 全跑）。

### E2E-1 (S-001 happy): 录制场景脚本

- **Goal**：sponsor 在 launch 中按 F6 / F7 录制脚本，落盘可重放。
- **Flow**：
  1. mock GetKeyboardState / GetCursorPos 输出固定序列
  2. 起 ReplayRecorder + 写 mock BMP 到 `_recording_frames/`
  3. 模拟 F6 按下两次（中间间隔 5s mock 时间）
  4. 模拟 F7 按下
  5. 检查 `_scenes/test/script.jsonl`、`meta.json`、`sync_01.bmp`、`sync_02.bmp` 存在
- **Verify each step**：步骤 1 后 → 内部状态正常；步骤 3 后 → jsonl 实时增长；步骤 5 后 → `iter_events` 重读全部 event 顺序与录制一致
- **Error path (E2E-1.err)**：F6 触发但 `_recording_frames/` 为空 → sync event `frame=null`，console warn

### E2E-2 (S-002 happy): 回放正常 + 加载抖动吸收

- **Goal**：录制脚本能完整回放到目标场景。
- **Flow**（mock）：
  1. 准备 E2E-1 录的 scene
  2. mock InputBackend 收集 inject 调用
  3. mock SyncMatcher：sync 1 在第 4s 才 match（录制时 1s match → drift +3s），sync 2 立即 match
  4. 跑 ReplayPlayer.run()
  5. 检查 result.status=='reached'，exit_code==0，inject 调用次数 == 录制 input event 数
- **Verify each step**：步骤 3 后 → player 实际等 4s 后才继续；步骤 5 后 → drift 体现在 console "[REPLAY] reached scene ... drift +3s"
- **Error path (E2E-2.err)**：mock window_size 不匹配 → console warn 一次；mouse_move 按 ratio scale；其他 event 不变

### E2E-3 (S-003 error): sync 超时 → paused → R/Q

- **Goal**：脚本失效时人工接管 / 干净退出。
- **Flow**（mock）：
  1. 准备 scene with 1 sync
  2. mock SyncMatcher：永远 match=False
  3. 跑 ReplayPlayer.run() with `paused_input=lambda:'R'`
  4. 30s 后超时 → paused → 'R' → 续注入剩余 input → 完成
  5. 同上 with `paused_input=lambda:'Q'` → result.status=='user_abort', exit_code==2
- **Verify each step**：步骤 4 后 → console 红字 paused 提示；'R' 后 inject 调用恢复
- **Error path 已含**

### E2E-4 (S-004): 缺 survey 自动跑

- **Goal**：新机器零干预回放。
- **Flow**（mock）：
  1. 准备 scene；mock dataset_root 不含 `survey/recommended_skip.txt`
  2. 调 `main._run_replay` with mock `_run_survey` 返回 True
  3. 验证 `_run_survey` 被调一次；之后 `ReplayPlayer.run` 才调
  4. 同上 with mock `_run_survey` 返回 False → 不调 player，exit 3
- **Verify each step**：步骤 2 console "[REPLAY] no survey cache..."；步骤 4 exit code 3

### E2E Coverage Matrix

| Capability | E2E Goals | Covered? |
|-----------|-----------|----------|
| 录制（recorder + schema） | E2E-1 | ✓ |
| 回放注入 + 时序（player + InputBackend） | E2E-2, E2E-3 | ✓ |
| sync 等待（sync_match） | E2E-2, E2E-3 | ✓ |
| paused 态 + R/Q（player） | E2E-3 | ✓ |
| 缺 survey 自动跑（main） | E2E-4 | ✓ |
| `_*` 目录过滤（main） | (capability-only M3) | ✗ — capability 已覆盖，无需 E2E |
| 鼠标归位（main） | (capability-only M4) | ✗ — capability 已覆盖 |
| F6/F7 reserved（profile + recorder） | E2E-1 隐式 | ✓ |

`✗` 项：纯系统集成检查，capability 测足够；不另立 E2E goal。

## 5. Failure & Edge Cases

| 失败 | 期望行为 |
|------|--------|
| script.jsonl 损坏（坏 JSON 行） | 报错 + 行号 + 不启动 player |
| meta.json 缺字段 | 报错 + 字段名 + 不启动 player |
| sync_NN.bmp 缺失 | sync 必失败 → 走 paused 流程 |
| F6 触发时 fc_output_dir.txt 没设（addon 未写 BMP） | sync event `frame=null` + warn |
| 录制中游戏崩溃 | recorder 轮询线程感知不到，要靠 F7（人工）/ Ctrl+C 停；不自动 |
| `_scenes/<name>/` 已存在 | console 提示并要求手动删（不静默覆盖） |
| profile load 失败 | record/replay 都不能跑（player 用 InputBackend → InputBackend 用 profile.reserved_keys） |
| `MANDATORY_RESERVED_KEYS` 校验阻挡老外部 profile | 报错 + 提示加 F6/F7 进 reserved_keys |
| Ctrl+C in record/replay | 干净停（recorder.stop() / player 退出，exit code 130） |

## 6. Audit / Logs

**必须 log**:
- 录制开始 / sync N 标记 / 录制结束（含 event count, sync count, duration, output path）
- 回放开始 / 每个 sync match 结果（matched + waited Xs OR timeout）/ 回放结束（status, exit code, drift）
- paused 态进入 / R/Q 决定

**不得 log**:
- 每条 input event 的内容（量太大，仅 debug 模式）
- meta.json 全文（仅引用路径）

## 7. Security / Token Constraints

- 无 API call → 无 token cost
- script.jsonl 含原始按键序列（包括用户密码若录制时输了任何文字字段）→ 文档明示"录制不要在登录界面带密码"
- `_scenes/` 不入 ML pipeline，不上传

## 8. Environment Spec

| Field | Value |
|-------|-------|
| `type` | local |
| `exec` | `uv run python ...` |
| `workdir` | repo root |
| `auto_provisioned` | false |

Live-game E2E（FF7R 30 min）由 sponsor 手动跑（项目 memory feedback_no_auto_verify）。

`verify_replay.py` 所有 capability + integration + E2E offline 在本地 windows shell 跑，无需 docker。
