# Requirements: unicap PyQt UI 包装器（操作员控制台）

**Version:** 1.0
**Confidence:** HIGH
**Sponsor:** raptoravis
**Source:** 直接请求 + 社区调研 + sponsor 三选一选定提案 B
**Date:** 2026-05-07

## Goals

### G-001: 三 tab 表单化映射所有 CLI flag

切到 `launch / video / pack` tab 看到对应 subcommand 的所有 argparse 参数以正确控件类型呈现。

**Acceptance criteria:**
- [ ] `launch` tab 包含全部 22 个 flag（`--game-path / --game-name / --dataset-root / --ui-mode / --api / --vk-debug / --hints / --force-borderless / --video / --capture-duration / --mask-ui / --pack / --color / --normal / --auto-play / --driver / --vlm-api-key / --vlm-base-url / --vlm-model / --profile / --auto-play-debug / --vlm-budget-per-hour`）
- [ ] `video` tab 包含 `--game-dir / --fps / --mask-ui`
- [ ] `pack` tab 包含 `--game-dir / --color / --depth / --normal / --spot-check / --check-frames / --check-out`
- [ ] 默认值与 `parser.add_argument(default=...)` 完全一致；hover 显示 `help=` 文本
- [ ] `choices` → 下拉、`BooleanOptionalAction` → 复选框、`type=float/int` → 数值、路径类 → 带"浏览"按钮的 LineEdit

### G-002: 子进程启动与日志流不丢行

点 Start 启动 `uv run python -u main.py <subcommand> <flags>`；stdout 实时按行流到底部日志面板，无 block-buffer 卡顿。

**Acceptance criteria:**
- [ ] 子进程命令行包含 `python -u`
- [ ] launch 跑 5 分钟，UI 收到的 `[CAPTURE]/[HEARTBEAT]/[VLM-COST]` 行数与 `%TEMP%\unicap\auto_play.log` 一致
- [ ] 日志面板有 5000 行环形缓冲
- [ ] "导出日志"按钮把当前缓冲存成 `.txt`

### G-003: Windows 优雅停止

点 Stop：launch 子进程通过 `CTRL_BREAK_EVENT` 退出；游戏窗口子进程残留时 `taskkill /T /F` 兜底。

**Acceptance criteria:**
- [ ] 子进程以 `CREATE_NEW_PROCESS_GROUP` flag 启动，停止时发 `CTRL_BREAK_EVENT`
- [ ] launch 进程 + 游戏进程在点 Stop 后 ≤5s 退出
- [ ] 输出目录无半写文件（addon 已写完最后一帧 + `inputs.jsonl` 已 flush）
- [ ] 日志面板出现优雅退出 print（如 `[CAPTURE] 收到中断 — 当前 session 已落盘`）

### G-004: 等价 CLI 命令实时显示 + Extra args 逃生口

每 tab 底部一个只读文本框显示当前 GUI 设置等价的 `uv run main.py ...` 命令；下面一个 LineEdit 让用户追加任意原始 flag。

**Acceptance criteria:**
- [ ] 任意控件改动 → 等价 CLI 文本框 ≤0.5s 内更新
- [ ] 文本框右侧"复制"按钮一键到剪贴板
- [ ] Extra args 框内容直接 split-and-append 到子进程 argv
- [ ] 用户在 Extra args 写 `--auto-play-debug` 后启动，子进程实际收到该 flag

### G-005: launch 实时仪表盘

launch tab 顶部仪表盘：状态条 + frame count + elapsed timer + capture-duration 进度条 + 当前 session 路径 + VLM 调用计数 + watchdog 触发计数 + heartbeat 心跳灯。

**Acceptance criteria:**
- [ ] 状态条读 `%TEMP%\unicap\fc_state.txt`，从 idle → surveying 切换在 ≤2s 内变色；色块 ≥18pt 清晰可读
- [ ] frame count 每 1s 更新（数 `frames/*.bmp` 或抓 capture stdout `[CAPTURE] frames=N`）
- [ ] capture-duration 进度条与 60s 自动 roll 周期同步，session roll 时进度条重置
- [ ] session 路径点击调 `os.startfile()` / `explorer /select,` 在文件管理器打开
- [ ] VLM 计数从 `[VLM-COST]` 行 grep；预算耗尽时计数变红
- [ ] watchdog 触发计数从 `[WATCHDOG] static-frame 触发 #N` grep；新触发时 1s 红色脉冲后回灰
- [ ] heartbeat 心跳灯每 1.5s 闪一次（绿）；recovery 期间变橙

### G-006: launch tab 内嵌 F8/F9 镜像按钮

游戏不在前台时（如远程串流），用户从 UI 也能触发 capture 开始/停止。

**Acceptance criteria:**
- [ ] "F8 开始 / F9 停止"按钮通过 `SendInput` 把虚拟键事件发到游戏窗口
- [ ] 点 F8 后 ≤2s 状态条变 `CAPTURING`
- [ ] GUI **不**把 F8/F9 注册成 `QShortcut`（避免与游戏内 `GetAsyncKeyState` 双触发）

### G-007: auto-play 子面板

launch tab 中 auto-play 相关 7 个 flag 合成可折叠子组：profile 下拉、driver 单选、VLM 三连（key/base-url/model masked + 改 .env 按钮）、VLM 预算条。

**Acceptance criteria:**
- [ ] profile 下拉自动扫 `profiles/*.yaml`；右侧"刷新"按钮重新扫描
- [ ] driver=keep-alive 时 VLM 字段全部 disabled（与 CLI 行为一致）
- [ ] VLM key 字段默认 masked（`••••••`）；眼睛图标切换显隐
- [ ] VLM 三连显示 `.env` 当前值；"改 .env"按钮调外部默认编辑器（`os.startfile('.env')`）
- [ ] VLM 预算条按 `--vlm-budget-per-hour` 与历史调用计数实时算

### G-008: redo survey 入口

launch tab 右上角"重做 survey"按钮 → 弹确认 → 删除 `DATASET_ROOT/<game>/survey/recommended_skip.txt`。

**Acceptance criteria:**
- [ ] 按钮在 launch 子进程跑期间 disabled
- [ ] 确认弹窗显示要删除的具体路径（防误删）
- [ ] 删除后日志面板出现 `[INFO] survey 已重置，下次 F8 将重跑 survey`

### G-009: 启动前预检

点 Start 前校验：game-path 文件存在；dataset-root 父目录可写；profile 文件解析成功；driver=vlm 时 `.env` 含 `VLM_API_KEY`。

**Acceptance criteria:**
- [ ] 任一预检失败弹模态对话框，明示"哪一项 + 怎么修"
- [ ] 校验通过后 Start 按钮才真正 spawn 子进程
- [ ] "跳过校验"复选项可关掉，让 power-user 故意触发 CLI 自身错误

### G-010: video / pack tab 的 session 树

两 tab 的 game-dir 选择器升级成树：左侧选 `<dataset-root>/<game>/`，右侧列出该游戏下所有 `<ts>` session，每行三列状态图标 [frames✓] [video.mp4 ✓/✗] [dataset.h5 ✓/✗]，复选框多选。

**Acceptance criteria:**
- [ ] 状态图标实时反映文件存在性；扫描期间显示 spinner
- [ ] 复选框默认勾选"缺产物"的 session（与 CLI"已存在跳过"行为一致）
- [ ] 处理过程中每完成一个 session 该行图标更新
- [ ] 全选 / 反选 / 仅缺失 三个快捷按钮
- [ ] 单 game-dir 含 ≤500 session 时初次扫描 ≤2s（≥500 走异步增量加载）

### G-011: launch 跑时其他 tab Start 锁定

单一长任务策略——避免 video encode 与 launch GPU 抢资源。

**Acceptance criteria:**
- [ ] launch 子进程存活期间，video/pack tab 的 Start 按钮 `setEnabled(False)`，hover tooltip "launch 正在跑，暂不可启动"
- [ ] 用户仍可在 video/pack tab 浏览设置（不锁整 tab）
- [ ] launch 退出后 ≤1s 自动恢复

### G-012: 状态持久化

退出时记住窗口大小、上次活跃 tab、每个 tab 上次填的所有 flag 值；下次启动恢复。

**Acceptance criteria:**
- [ ] 通过 `QSettings(IniFormat)` 持久化（不写 Windows 注册表）
- [ ] 路径类 flag 也恢复（带 LRU "最近 5 个 game-path" 下拉历史）
- [ ] 删 INI 文件后启动正常恢复 CLI 默认

## Constraints

- 平台：**Windows 11+**（与 unicap 主程序一致；不做 macOS/Linux 支持）
- Python：与项目当前一致（≥3.10，受 `pyproject.toml` 约束）
- 框架：**PySide6**（LGPL，与 OSS repo 兼容性更好；非 PyQt6 GPL）
- 不修改 `main.py` 公开 CLI 表面（向后兼容；UI 仅以 subprocess 形式调用）
- UI 文案：中文（与 CLI help 一致）

## Non-Goals

- profile YAML 富编辑器（用户改 `profiles/*.yaml` 走外部编辑器；提供"刷新"按钮即可）
- .env 富编辑器（提供"改 .env"按钮调外部 notepad 即可）
- frame 缩略图预览 / dataset 浏览 tab
- macOS / Linux 支持
- 双语切换（仅中文）
- 可命名 preset 库（QSettings 仅记上次值，不做命名预设）
- 训练 pipeline 集成
- 完全自定义 GUI 快捷键（F8/F9 镜像按钮足够）

## Scope Boundary

**In**：三 tab（launch/video/pack）+ 全部 CLI flag 表单化 + 子进程启动 + 优雅停止 + 等价 CLI 显示 + Extra args 逃生口 + launch 实时仪表盘 + F8/F9 UI 镜像按钮 + auto-play 子面板（profile/driver/VLM 子组）+ redo survey + 启动前预检 + video/pack session 树状管理 + launch 跑时锁其他 tab Start + 窗口/flag 持久化（QSettings）。

**Out**：profile/.env 富编辑、frame 预览、dataset 浏览、跨平台、双语、preset 库、训练流程集成、云同步。

## Usage Scenarios

### S-001: 通宵无人值守 + 早上回看

- **Persona:** power-user
- **Goal:** 跑 8 小时 `--auto-play --driver hybrid`，早上检查产出
- **Steps:**
  1. launch tab：勾 `--auto-play`、`--driver hybrid`、`--capture-duration 60`，profile 选 `ff7r`，点 Start
  2. 仪表盘显示 `CAPTURING` 绿块；按游戏内 F8
  3. 第二天看仪表盘：watchdog 触发 N 次、VLM 调用 M 次、当前是第 480 段 session
  4. 点 UI 上"F9 停"按钮 → 状态回 `IDLE`，点 Stop 关 launch
  5. 切到 video tab：选游戏 → 480 个 session 状态图标显示全部缺 `video.mp4` → 点"仅缺失"快捷选 → Start
- **Success condition:** 480 段全部生成 mp4；仪表盘统计与 `auto_play.log` grep 计数一致

### S-002: 新同事第一次跑（零 PowerShell 知识）

- **Persona:** novice
- **Goal:** 30 分钟 FF7R 采集
- **Steps:**
  1. 启动 GUI；launch tab：浏览 `--game-path` 选 ff7remake_.exe，其余 flag 保留默认
  2. 点 Start；预检通过；见仪表盘绿色 `CAPTURING (idle)`
  3. 在游戏里按 F8 → 状态变 `CAPTURING (session: 20260507_193012)`，frame counter 开始涨
  4. 30 分钟后点 UI 上的"F9 停"按钮 → 状态回 `IDLE`
  5. 点 Stop 关 launch
- **Success condition:** `DATASET_ROOT/<game>/<ts>/frames/` 有 ~54000 张 BMP；`inputs.jsonl` 行数对得上；novice 全程不用记 flag、不用敲命令

### S-003: 老用户改一个 GUI 没暴露的 flag

- **Persona:** power-user
- **Goal:** 跑 `--auto-play-debug`（假设此 flag GUI 暂未建控件）
- **Steps:** launch tab → Extra args 输入 `--auto-play-debug` → Start
- **Success condition:** `auto_play.log` 出现详细 inject 行；等价 CLI 文本框显示完整命令含此 flag

### S-004: 远程串流场景需要 UI 触发 capture

- **Persona:** power-user
- **Goal:** 笔记本控制台远程串流 PC 跑 FF7R 采集，键盘 F8/F9 不方便切回游戏窗口
- **Steps:**
  1. launch tab → Start，游戏跑起来
  2. 不切焦，直接在 GUI 点"F8 开始"按钮
  3. 仪表盘 ≤2s 后显示 `CAPTURING`
  4. 30 分钟后点 GUI"F9 停止"
- **Success condition:** session 完整落盘；GUI 始终聚焦不影响游戏接收 F8/F9 虚拟键

### S-005: 接 profile 错配触发预检拦截

- **Persona:** novice
- **Goal:** 想用 vlm driver 但忘了配 .env
- **Steps:** launch tab → 勾 `--auto-play`、`--driver vlm`、点 Start
- **Success condition:** 模态对话框弹"VLM_API_KEY 未在 .env 中找到。点'改 .env'按钮配置；或改用 driver=keep-alive"；用户不会进入"启动后 VLMDriver 抛 BudgetExhausted 默默降级"的困惑路径

## Open Questions

| 问题 | 状态 | 解决方案 |
|---|---|---|
| 框架最终选 PySide6 还是 PyQt6？ | resolved | PySide6（LGPL；sponsor 选 B 后未 pushback 推荐） |
| F8/F9 UI 镜像按钮是否必须？ | resolved | 是（B 包含 G-006；远程串流场景 S-004 验证必要性） |
| launch 跑时其他 tab Start 是锁定还是软警告？ | resolved | 锁定（避 GPU 抢；如需绕开走 Extra args 起多进程） |
| VLM key 改完后是否需立即生效？ | resolved | 子进程下次 Start 时从 `.env` 读，无需重启 GUI |
| 1000+ session 的树扫描性能？ | deferred | G-010 acceptance criteria 已规定 ≥500 走异步增量加载 |

## Community Research Attribution

本份 requirements 引用的社区证据：

- HandBrake [#408](https://github.com/HandBrake/HandBrake/issues/408) / [#5430](https://github.com/HandBrake/HandBrake/issues/5430) — "show CLI command" + "Extra args 逃生口"高 +1 长青请求 → G-004
- [Qt forum: stopping QProcess slows GUI on Windows](https://forum.qt.io/topic/142762/) + [Python subprocess CTRL_BREAK_EVENT docs](https://docs.python.org/3/library/subprocess.html) → G-003 优雅停止策略
- [pythonguis.com: streaming subprocess output](https://www.pythonguis.com/faq/constantly-print-subprocess-output-while-process-is-running/) → G-002 `python -u` 强制 line-buffer
- [OBS forum: how to know recording state](https://obsproject.com/forum/threads/so-how-do-i-actually-see-an-indication-whether-im-recording-or-not.111369/) → G-005 大色块状态条 ≥18pt
- [PyQt6 vs PySide6 licensing](https://www.pythonguis.com/faq/licensing-differences-between-pyqt6-and-pyside6/) → 框架选型 constraint
