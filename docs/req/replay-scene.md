# Requirements: 游戏场景自动化复现（录制 + 回放）

**Version:** 1.0 (2026-05-04)
**Confidence:** HIGH
**Sponsor:** raptoravis (`FreddieSparksmie@computer4u.com`)
**Source:** `/zero-review:req --research` 直接请求 — sponsor 选定 Proposal B (时序 + 视觉校验点)，C (VLM 兜底) 列为后续 v2.0

## 中文摘要

测试游戏时反复"启动 → 进入某个场景"操作太繁琐。本需求引入**录制 / 回放机制**：用户手动走一遍流程时按 F6 标视觉同步点 + F7 结束录制，脚本落盘；之后单条命令即可复现。

核心设计：纯时序回放对启动场景的"加载时间方差"（启动器更新、shader compile、登录 retry）天生脆弱，所以采用业界标准的"时序回放 + 视觉同步点"范式 — sync point 处暂停输入注入，截当前帧与录制帧做感知哈希比对，匹配后立即继续，自动吸收抖动。失败（30s 超时）则暂停等用户接管。后续 v2.0 接入现有 VLMDriver 做兜底，超时后 VLM 自主导航而非暂停。

下游消费方（auto-dev）按 G-001 → G-006 顺序实现，全部不动 C++ 层；新增 ~5 个 Python 文件 + Pillow 依赖。

---

## Goals

### G-001：录制场景脚本（含 sync point）

单条命令启动游戏并开始录制；用户按 **F6** 标视觉同步点，按 **F7** 结束录制；脚本完整落盘可重放。

**Acceptance criteria:**
- [ ] 命令 `uv run main.py launch --record-scene <name>` 启动游戏并立即进入录制态
- [ ] 录制内容写入 `DATASET_ROOT/<game>/_scenes/<name>/script.jsonl`（一条 input event = 一行；一条 sync event = 一行 `{type:"sync", id:"S-NN", frame:"sync_NN.bmp", t_rel:<sec>}`）
- [ ] 元数据写入同目录 `meta.json`：`window_size`、`game_exe`、`recorded_at`、`recorder_version`、`api`（dx/vulkan）、`mouse_origin`（录制起点屏幕坐标，仅作记录用）
- [ ] F6 触发：当前帧 BMP 通过 `frame_capture.addon` 现有输出复制为 `sync_NN.bmp`，console 打印 `[REPLAY-REC] sync S-NN at Xs`
- [ ] F7 触发：停止录制，console 打印 `[REPLAY-REC] saved <path> (N inputs / M syncs)`，退回 idle（不退出 launch，可继续 capture）
- [ ] 录制期间 F8/F9 仍走原 capture 语义，互不干扰
- [ ] F6 / F7 加入所有 profile 的 `reserved_keys`，bot 不得占用
- [ ] 录制期间**不**同时落 capture session（脚本与 ML 数据解耦；用户要 ML 数据另起 F8 capture）

### G-002：回放时按时序注入输入

读取脚本，按相对时间戳通过现有 `InputBackend` 注入键鼠/手柄事件。

**Acceptance criteria:**
- [ ] 命令 `uv run main.py launch --replay-scene <name>` 启动游戏并自动进入回放
- [ ] 输入注入复用 `tools/auto_play/input_backend.py` 的 SendInput + ViGEm 通路（与 `--auto-play` 共享 lock）
- [ ] 回放开始前 `SetCursorPos` 把鼠标归到目标显示器屏幕中心（不读 `meta.json` 的 `mouse_origin`，固定中心，跨分辨率最稳）
- [ ] 鼠标坐标按"录制窗口尺寸 → 当前窗口尺寸"等比缩放后注入
- [ ] 录制 / 回放窗口尺寸不一致时 console 一次性 warn，但继续执行
- [ ] **回放期间 F6 / F7 不响应**（既不重新进入录制态，也不影响回放进度）；要中止回放只能 Ctrl+C in console

### G-003：回放在 sync point 处等待视觉匹配

回放遇到 sync event 时暂停输入注入，截当前帧与录制帧做感知哈希比对，匹配后立即继续。

**Acceptance criteria:**
- [ ] 截图复用 `frame_capture.addon` 已落盘的最新 BMP（不另开 hook）
- [ ] 哈希算法在 50 ms 内完成（dev 可选 dHash 或 pHash，纯 numpy/Pillow）
- [ ] 默认匹配阈值 = 汉明距离 ≤ 10（256-bit），可在 `meta.json` per-sync 覆写
- [ ] 默认等待上限 = 30 s，可在 `meta.json` per-sync 覆写
- [ ] 等待期间每 ~200 ms 重抓一次新帧重判
- [ ] 匹配成功立即跳过剩余 sleep 进入下一段输入（自动吸收加载抖动）

### G-004：回放结果有明确的成功 / 失败信号

回放结束 console 状态可被肉眼或脚本识别。

**Acceptance criteria:**
- [ ] 全部 sync 通过：console 打印 `[REPLAY] reached scene <name> in Xs (recorded Ys, drift Δs)`，进入正常 launch idle 等 F8
- [ ] 任一 sync 超时：console 红字 `[REPLAY] sync S-NN miss after 30s, paused. Press R to resume, Q to abort.`，输入注入暂停；用户按 R 续 / Q 退
- [ ] R / Q 仅在 paused 态响应；其他时间不监听这两个键（避免与游戏内输入冲突）
- [ ] 回放退出码：成功 0；用户中止（Ctrl+C 或 paused 态 Q）130；sync 超时未续 + 用户 Q 退 2

### G-005：回放时缺 survey 缓存自动跑 survey

首次在新机器回放时不需要用户手动 F8 触发 survey。

**Acceptance criteria:**
- [ ] 回放启动前检查 `DATASET_ROOT/<game>/survey/recommended_skip.txt`
- [ ] 缺失则在游戏窗口出现后、注入第一个事件前自动触发 survey（复用 F8 首次自动 survey 流程）
- [ ] survey 期间 console 打印 `[REPLAY] no survey cache, running survey first...`
- [ ] survey 完成后无缝进入回放（不需要再按键）
- [ ] survey 失败则回放中止，退出码 3

### G-006：`_scenes/` 在 ML pipeline 中被过滤

确保录制脚本目录不污染数据集扫描。

**Acceptance criteria:**
- [ ] `pack` / `video` 子命令扫描 `DATASET_ROOT/<game>/` 时跳过以 `_` 开头的子目录
- [ ] 已有约定则验证；没有则在本任务一并补丁
- [ ] 单元测试覆盖：`_scenes/foo/` 与正常 session `20260504_120000/` 共存时 `pack` 只扫后者

## Constraints

- **平台**：仅 Windows（继承现有 `InputBackend` / `SendInput` / ViGEm 限制）
- **C++ 复用**：截图必须复用 addon 现有 BMP 输出，不在 C++ 侧新增 hook
- **依赖**：可新增 Pillow（pHash 实现），不引入更重依赖
- **C 路径预留**：`script.jsonl` 的 sync event 结构必须可向后兼容地加 `description` 字段（v2.0 给 VLM 用）；`meta.json` 必须可加 `vlm_fallback_enabled`
- **性能**：回放本身不得引入新的 GPU/CPU hot loop（截图 + 哈希仅在 sync 等待期执行）
- **热键唯一性**：F6 / F7 仅服务于 record；F8/F9 始终归 capture/survey；R / Q 仅在 sync paused 态响应

## Non-Goals

- VLM 视觉比对、自然语言 sync 描述（C 阶段，v2.0）
- sync 失败时的自动恢复（C 阶段；当前版只暂停等人）
- scene → scene 链式跳转（C 阶段）
- OCR / 文字校验
- 鼠标拖拽路径平滑插值（按录制 120 Hz 采样直接重放）
- 录制脚本的 git 提交 / 分发（用户自管 `_scenes/`）
- "回放即视为正确场景到达"以外的语义校验
- 回放期间允许重新录制 / 编辑

**与 `--auto-play` 的关系（v1.0 兼容）**：
- `--record-scene foo --auto-play` 允许 — auto-play 只在 F8 capture 阶段生效，不在 record 期间运行（recorder 只录用户键鼠）
- `--replay-scene foo --auto-play` 允许 — replay 完成后用户按 F8 → capture 启动 + auto-play 接管 = 无人值守典型用法
- 仅 `--record-scene` ↔ `--replay-scene` 互斥（语义冲突）

## Scope Boundary

**In scope**：单条 `launch` 命令完成"启动 → 录制 / 回放 → 到达目标场景 → 移交 idle 等 F8 capture"全流程。视觉校验点吸收加载时间方差；启动器更新等小概率非确定事件 → 视觉超时 → 人工接管。新增约 5 个 Python 文件（`replay_recorder.py` / `replay_player.py` / `sync_match.py` / 子命令 wiring / `_scenes/` schema 定义），不改动 C++ 层。`_scenes/` 过滤补丁顺带覆盖到 `pack` / `video`。

**Out of scope**：VLM 兜底、scene 链跳转、自动恢复、跨平台、`_scenes/` 之外的目录命名约定变更。这些是 v2.0 工作。

## Usage Scenarios

### S-001：录制 FF7R 教程关卡入口

- **Persona**：power-user (sponsor 自己)
- **Goal**：录一份"启动 → 进入陷落区"脚本，今后可一键复现
- **Steps**：
  1. `uv run main.py launch --record-scene tutorial`
  2. 等启动器主菜单出现 → 按 F6（sync S-01）
  3. 按 X 通过弹窗 → 等主菜单出现 → 按 F6（S-02）
  4. 选"新游戏" → 等加载完 → 按 F6（S-03）
  5. 跳过开场动画 → 进入陷落区可控状态 → 按 F6（S-04）
  6. 按 F7 结束录制
- **Success condition**：console `[REPLAY-REC] saved DATASET_ROOT/ff7r/_scenes/tutorial/script.jsonl (847 inputs / 4 syncs)`

### S-002：第二天回放，加载比录制慢

- **Persona**：power-user
- **Goal**：复用昨天的脚本进入陷落区，开始一次新 capture
- **Steps**：
  1. `uv run main.py launch --replay-scene tutorial`
  2. 不操作，等回放（鼠标自动归位到屏幕中心）
  3. console `[REPLAY] sync S-01 matched (waited 4.5s)`（昨天 1.2s）
  4. console `[REPLAY] sync S-02 matched (waited 0.3s)` ... 一路通过
  5. `[REPLAY] reached scene tutorial in 47s (recorded 41s, drift +6s)`
  6. 用户按 F8 启动 capture
- **Success condition**：到达陷落区与昨天一致，加载慢 6s 被自动吸收

### S-003：回放遇启动器更新弹窗（sync 超时）

- **Persona**：power-user
- **Goal**：脚本失效后能定位并人工修复
- **Steps**：
  1. 启动器弹了"有可用更新" → S-01 等不到主菜单
  2. console 红字 `[REPLAY] sync S-01 miss after 30s, paused. Press R to resume, Q to abort.`
  3. 用户手动点掉更新 → 按 R
  4. 回放从 S-01 之后的下一条输入续上
- **Success condition**：人工接管 → 回放成功收尾，或 Q 退干净退出（退出码 2）

### S-004：换新机器，无 survey 缓存

- **Persona**：power-user
- **Goal**：把脚本拷到新电脑直接能跑，不需要先手动 survey
- **Steps**：
  1. 新机器上 `uv run main.py launch --replay-scene tutorial`
  2. console `[REPLAY] no survey cache, running survey first...`
  3. survey ~30s 完成
  4. 自动进入回放，路径同 S-002
- **Success condition**：用户全程零干预（前提：新机器 GPU/驱动能正常跑游戏）

## Open Questions（deferred — 不阻塞 v1.0）

| Question | Status | Resolution / Note |
|---|---|---|
| 默认 sync 超时 30 s 是否够 FF7R 首次启动 shader compile？ | deferred | 实测后调；先按 30s 上线，per-sync 覆写做兜底 |
| 哈希算法 dHash vs pHash？ | deferred | dev 实现时根据 sync 截图实测决定，对外只暴露阈值参数 |
| C 阶段（VLM 兜底）的 `description` 字段在录制时如何采集？ | deferred | v2.0 设计时定（F6 后 console prompt vs 事后编辑 meta.json） |
| `--replay-scene tutorial --from S-03` 中段续跑能力 | deferred | v1.1 增强；不阻塞 v1.0 |

## Community Research 摘要（--research）

调研了 TAS / AutoHotkey / Squish for Games / Source `demo` / RL replay 五种范式。结论：

| 模式 | 适用性 | 借鉴点 |
|---|---|---|
| TAS frame-perfect | ❌ 不适用（DX12/UE4 商业游戏无 frame-step API） | — |
| AutoHotkey 时序脚本 | ⚠️ 同 Proposal A，已被 sponsor 排除 | — |
| Squish for Games (商业) | ✅ 业界标准 = 时序 + 视觉校验点 | **本设计直接对标** |
| Source `demo` 引擎录制 | ❌ 不适用（DX12/UE4 不开放） | — |
| RL replay (OpenAI Universe) | ⚠️ 接近 Proposal C；v2.0 兜底借鉴 | VLM 接管模式 |

3 个最常见 real-world 失败模式（已合入 acceptance criteria）：
1. 启动器/反作弊弹窗时机不固定 → 由 G-003 sync 超时 + G-004 paused 态处理
2. 鼠标坐标系跨分辨率漂移 → G-002 等比缩放 + 鼠标归位中心
3. 首次启动 shader compile 卡顿 → G-003 per-sync 等待时长可覆写

## 实现路线图

| 阶段 | Goals | 预计工时 |
|---|---|---|
| v1.0 | G-001 ~ G-006（本文档） | 5-7 天 |
| v1.1 | `--from S-NN` 中段续跑 | +2 天 |
| v2.0 | VLM 兜底（C 阶段，依赖现有 VLMDriver 验收完成） | 10-15 天 |
