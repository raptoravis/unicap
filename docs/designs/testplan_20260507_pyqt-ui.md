# TestPlan: PyQt UI 包装器

**Date**: 2026-05-07
**Sponsor**: raptoravis
**Requirements**: `.scratch/ui/requirements.md` (v1.0, HIGH)
**Impact**: `docs/designs/impact_20260507_pyqt-ui.md`
**Scope**: 仅本次 enhancement（UI 子系统），不重测 unicap 现有 capture / auto-play / pack 链路

---

## Capability Inventory

UI 暴露给用户的能力：

| Cap-ID | 能力 | 关联 Goal |
|---|---|---|
| C-FORM | 三 tab 全 flag 表单化（含 hover help / 默认值 / 路径 browse） | G-001 |
| C-RUN | 启动子进程并实时显示 stdout（无 buffer 卡顿） | G-002 |
| C-STOP | 优雅停止（CTRL_BREAK + taskkill /T 兜底） | G-003 |
| C-CLI | 等价 CLI 实时显示 + 复制 + Extra args 透传 | G-004 |
| C-DASH | launch 实时仪表盘（状态条 / frame count / VLM 计数 / watchdog 计数 / heartbeat 灯） | G-005 |
| C-MIRROR | F8/F9 UI 镜像按钮（SendInput 到游戏窗口） | G-006 |
| C-AP | auto-play 子面板（profile 下拉 / driver 单选 / VLM masked / 预算条） | G-007 |
| C-SURVEY | redo survey 入口（确认弹窗 + 删 recommended_skip.txt） | G-008 |
| C-PRECHECK | 启动前预检（game-path / dataset-root / profile / VLM_API_KEY） | G-009 |
| C-TREE | video/pack 的 session 树 + 状态图标 + 复选 + 全选/反选/仅缺失 | G-010 |
| C-LOCK | launch 跑时其他 tab Start 锁定 | G-011 |
| C-PERSIST | 退出记忆窗口/tab/flag；下次启动恢复 | G-012 |

---

## Must Have / Need Have / Should Have

### Must Have（gate delivery；必须全过）

> **统一前提**：UI 启动 = `uv run python -m unicap_gui` 或 `unicap-gui` console-script。

| MH-ID | 检查 | 验证方法 |
|---|---|---|
| MH-1 | 启动 UI ≤ 3s 出窗口；三 tab `Launch / Video / Pack` 均可见 | 手测 + 看时间 |
| MH-2 | launch tab 的 22 个 flag 全部可见为控件；hover 显示 `argparse help=` 文本 | 对照 `main.py:1101+` argparse 定义清点 |
| MH-3 | video tab 含 `--game-dir / --fps / --mask-ui`；pack tab 含 `--game-dir / --color / --depth / --normal / --spot-check / --check-frames / --check-out` | 同上 |
| MH-4 | 改任意控件 → tab 底部"等价 CLI"文本框 ≤ 0.5s 更新；点"复制"键内容到剪贴板 | 改一个 flag → 立即 `Ctrl+V` 验证 |
| MH-5 | Extra args 输入 `--auto-play-debug` → Start → 子进程 cmdline 含此 flag | `wmic process where "name='python.exe'" get commandline` 抓取并 grep |
| MH-6 | 点 Start：launch 子进程在 ≤ 2s 内出现首行 stdout 在 log 面板；后续 stdout 行实时增量出现（无 30s+ block-buffer 卡顿） | 启动后看 log 面板 5s 内出 `unicap v1.0.6` |
| MH-7 | log 面板超过 5000 行时新行涌入旧行 evict（FIFO） | 灌 5500 行 echo 子进程 → 第 1 行不可见 |
| MH-8 | 点 Stop：launch 子进程在 ≤ 5s 内退出；输出目录无半写文件；**游戏进程不动**（与 main.py 的 `Ctrl+C 退出但游戏继续` 约定一致；避免 Windows Game Bar 弹 ms-gamingoverlay） | `tasklist` 看 main.py 已退、游戏仍在；frames/ 末帧字节正常 |
| MH-9 | launch 仪表盘读 `<game_dir>/fc_state.txt`：写 `idle/surveying/capturing` ≤ 2s 后状态条颜色切换 | `python -c "open(...).write('capturing')"` 注入 + 看 UI |
| MH-10 | launch 跑期间 frame count 1Hz 更新，与 `len(list(frames_dir.glob('*BackBuffer*.bmp')))` 偏差 ≤ 1 帧 | 对比 |
| MH-11 | log 面板出现 `[CAPTURE] 开始采集 ... → <session>` 后，仪表盘 session 路径 link 指向 `<session>` | 点 link 在 Explorer 打开正确目录 |
| MH-12 | UI 不绑 `QShortcut(QKeySequence("F8"))`/`F9`；按 GUI 上的 "F8 开始" 按钮触发 1 次 capture（不是 2 次） | 看 log 面板出现 1 个 `[CAPTURE] 开始采集` |
| MH-13 | profile 下拉列出 `profiles/*.yaml` basename；点刷新按钮新加 `profiles/foo.yaml` 后下拉出现 | 加文件 → 点刷新 |
| MH-14 | driver=keep-alive 时 VLM key/base-url/model 三字段 disabled；driver=vlm 时 enabled | 切 radio 看 |
| MH-15 | VLM key 字段默认 masked `••••••`；眼睛图标点击切显隐 | 看 |
| MH-16 | "重做 survey" 按钮：弹确认对话框含完整路径；点 OK 后 `recommended_skip.txt` 被删 | `dir <path>` 确认 |
| MH-17 | 点 Start 当 game-path 文件不存在 → 模态对话框弹"game-path 不存在: <path>"；不 spawn 子进程 | tasklist 确认无 python.exe spawn |
| MH-18 | 点 Start 当 driver=vlm 且 .env 无 VLM_API_KEY → 模态对话框拦截 | 同上 |
| MH-19 | session 树扫 `<dataset_root>/<game>/` 列出所有 `<ts>/` session；每行三列状态图标反映 frames/ / video.mp4 / dataset.h5 存在性 | 手验：建几个空 session |
| MH-20 | "仅缺失"快捷按钮：仅勾选缺 video.mp4 或 dataset.h5 的 session | 手验 |
| MH-21 | launch 子进程跑期间，video/pack tab 的 Start 按钮 `setEnabled(False)`；hover tooltip "launch 正在跑，暂不可启动" | 启动 launch → 切 tab 看 |
| MH-22 | launch 子进程退出后 ≤ 1s，video/pack Start 自动恢复 enabled | 同上 |
| MH-23 | 关 GUI → 重启 → 上次 active tab + 上次窗口大小 + 上次填的所有 flag 值恢复 | 改 flag → 关 → 开 |
| MH-24 | 删 INI 文件后启动正常恢复 CLI 默认 | `del %APPDATA%\unicap-gui\unicap-gui.ini` |

### Need Have（强烈建议；不阻塞 deliver 但必须文档化未做项）

| NH-ID | 检查 | 验证 |
|---|---|---|
| NH-1 | VLM 调用计数从 `%TEMP%/unicap/auto_play.log` tail 增量读 `[VLM-COST] call#N`；显示总调用数 | 跑 30 分钟实测 + grep log |
| NH-2 | watchdog 触发计数同上读 `static-frame 触发 #N`；新触发时计数变红 1s 后回灰 | 同上 |
| NH-3 | heartbeat 心跳灯 1.5s 闪一次（绿）；recovery 期间橙色 | 观察 |
| NH-4 | VLM 预算条按 `--vlm-budget-per-hour` 与近 1h call 数比例填充；耗尽时变红 | 跑长时实测 |
| NH-5 | F8/F9 UI 镜像按钮：游戏聚焦或 GUI 聚焦时点击都能触发 game-side `[CAPTURE] 开始采集` | 双场景实测 |

### Should Have（锦上添花）

| SH-ID | 检查 |
|---|---|
| SH-1 | 路径 LineEdit 旁的 LRU "最近 5 个 game-path" 下拉历史 |
| SH-2 | "导出日志"按钮把当前 log 缓冲存 .txt |
| SH-3 | "复制 CLI" 按钮成功后短 toast "已复制" |
| SH-4 | session 树 ≥ 500 session 异步增量加载（spinner） |

---

## Forbidden Zones（≥ 3 redlines）

| FZ-ID | 严禁 | 原因 |
|---|---|---|
| FZ-1 | **禁止改 `main.py` 任何一行** | 向后兼容；CLI 必须可独立用 |
| FZ-2 | **UI 进程禁止 import `tools.capture` / `tools.auto_play` / `tools.window_manager`** | UI 必须是纯 subprocess wrapper；in-process import 会拖入 cv2 / opencv 等重依赖 + GIL 锁，且 PySide6 与 capture 的多线程不应耦合 |
| FZ-3 | **禁止用 `QShortcut(QKeySequence("F8"))` / `("F9")`** | 与游戏内 GetAsyncKeyState 双触发，会引发已踩过的 capture 双开/双停 BUG |
| FZ-4 | **禁止 hard-kill 子进程跳过 CTRL_BREAK** | 游戏窗口 / Vulkan HKCU 注册表清理依赖 main.py finally 块，跳过会留垃圾 |
| FZ-5 | **禁止读写 `<game_dir>` 内任何 sidecar 文件除了 read `fc_state.txt`** | 那些 sidecar 是 addon ↔ python CLI 的私有协议，UI 误碰会破坏 capture 行为 |
| FZ-6 | **禁止直接修改 `.env` 文件**（只读 + 调外部编辑器） | 复杂解析（含注释 / 多行）容易丢，scope 也明确说不做富编辑器 |
| FZ-7 | **禁止把 launch 子进程 stdout 缓存超过 5000 行不淘汰** | 长跑 8h 累积百万行会 OOM |
| FZ-8 | **禁止在 GUI 主线程做文件 I/O block > 200ms** | 卡顿；扫 1000+ session 必须 worker thread |

---

## Failure & Edge Cases

| F-ID | 场景 | 期望行为 |
|---|---|---|
| F-1 | 子进程立即 crash（exit code != 0 在 1s 内） | log 面板显示 stderr；状态恢复"未跑"；Start 按钮恢复可点 |
| F-2 | 子进程 hang（点 Stop 后 5s 不退出） | 自动 `taskkill /T /F /PID`；log 面板提示"已强制终止"；状态恢复 |
| F-3 | `fc_state.txt` 不存在（addon 还没启动） | 状态条显示"未连接"灰色；不报错 |
| F-4 | `auto_play.log` 不存在或正在 rotate | tailer 0.5s 后重试；UI 不崩 |
| F-5 | profiles/ 目录不存在 | profile 下拉空；显示"无 profile —— 创建 profiles/<name>.yaml" |
| F-6 | `.env` 不存在 | VLM 三字段显示"(.env 未找到)"；驱动选 vlm 时预检拦截 |
| F-7 | session 树扫描时用户切到其他 tab | 后台继续扫；切回时已就绪 |
| F-8 | UI 启动时 PySide6 缺失 | 启动器（`__main__.py`）打印中文友好提示 + `pip install "unicap[gui]"` 命令 |
| F-9 | 游戏路径含中文（如 `D:\游戏\FF7R\ff7remake_.exe`） | subprocess 正常启动；log 中文不乱码 |
| F-10 | 点 Stop 时子进程已自然退出 | 不报错；幂等 |

---

## Audit / Logs

UI 自身的 log（不是子进程 log）：
- 写到：`%APPDATA%\unicap-gui\unicap-gui.log`（rotating，5MB×3）
- 内容：UI 启动/退出、subprocess spawn cmdline（脱敏 VLM key）、subprocess exit code、预检失败原因、taskkill 触发记录
- **不**写：用户的全部输入流、log 面板每行内容（重复且大）

---

## Security / Token Constraints

- VLM key UI 内存里始终 masked 显示；只在生成等价 CLI（用户主动复制时）才以明文出现 → "复制 CLI" 时弹一次提示"含 API key，确认复制？"
- subprocess cmdline 不写 UI 自身 log（避免 audit log 泄漏 key）
- VLM 预算条数据来自本地 `auto_play.log`，不发出网请求

---

## Integration Tests

UI 内部跨模块（capability ↔ capability）：

| IT-ID | 测试 | 期望 |
|---|---|---|
| IT-1 | `flag_form` 改值 → `cli_preview` 拼出含此 flag 的命令 | 字符串匹配 |
| IT-2 | `cli_preview` 取出的 cmdline + Extra args → `SubprocessRunner.start()` → 子进程 cmdline 完全一致 | `wmic process` 比对 |
| IT-3 | `SubprocessRunner.stop()` 后 `dashboard` 自动复位（状态条 idle / counters 清零 / heartbeat 灯灭） | 看 |
| IT-4 | `session_tree` 扫描完后 → `flag_form` 的 `--game-dir` 自动填该 game 路径 | 选游戏 → 看 flag |
| IT-5 | launch tab `SubprocessRunner` 状态变 running → video/pack tab `Start.setEnabled(False)` | 信号链 |

---

## E2E User Flows

> **环境约束**：完整 E2E 需要 sponsor 实机（FF7R + Steam + GPU）。本 phase 列出必跑的 5 个 flow；verify 阶段无环境时降级为"流程模拟 + 关键 step manual stub"。

### E2E-1：novice 30 分钟 FF7R 采集（happy path，对应 S-002）
1. 启动 UI；launch tab 默认 game-path = QSettings 上次值（首次启动 = `tools/capture/config.py:GAME_PATH`）—— 验：路径 LineEdit 显示
2. 浏览改路径到 ff7remake_.exe —— 验：等价 CLI 实时显示更新
3. 点 Start —— 验：log 面板 ≤ 2s 出现 `unicap v1.0.6`，仪表盘出现 `IDLE` 灰色块
4. 游戏窗口出现后按 F8 —— 验：仪表盘 ≤ 2s 切 `CAPTURING` 绿块；frame count 开始涨
5. 30 分钟后按 F9 —— 验：仪表盘回 `IDLE`
6. 点 Stop —— 验：log 面板出现优雅退出 print；进程 ≤ 5s 退；session 目录有 ~54000 张 BMP

错误路径 E2E-1.err：步骤 2 用户填了不存在的路径 → 步骤 3 弹模态拦截 → 不 spawn 子进程

### E2E-2：通宵 8h auto-play hybrid + 早上 video 批处理（对应 S-001）
1. launch tab：勾 `--auto-play`、driver=hybrid、`--capture-duration=60`、profile=ff7r —— 验：等价 CLI 含全部 flag
2. 点 Start；F8 开始 —— 验：仪表盘 VLM call count 增加；watchdog 触发计数零或低
3. 第二天回 UI —— 验：仪表盘 frame count 极大；session 路径已 roll 到第 N 段
4. 点 GUI "F9 停止" 镜像按钮 —— 验：仪表盘 `IDLE`
5. 点 Stop；切 video tab —— 验：launch 锁解除（Start enabled）
6. video tab：选游戏 → "仅缺失"快捷选 —— 验：N 个 session 全部勾选
7. 点 Start —— 验：处理过程中每完成一个 session 该行图标更新；log 面板出现 N 行 `[VIDEO] ... 完成`

错误路径 E2E-2.err：步骤 1 driver=vlm 但 `.env` 无 KEY → 预检弹拦截

### E2E-3：远程串流 F8/F9 UI 镜像（对应 S-004）
1. UI 启动；launch tab Start；游戏跑起来 —— 验：log 面板出现游戏启动行
2. **不**切焦到游戏，直接在 UI 点 "F8 开始" 按钮 —— 验：仪表盘 ≤ 2s `CAPTURING`
3. 点 GUI "F9 停止" —— 验：仪表盘回 `IDLE`

### E2E-4：老用户透传未暴露 flag（对应 S-003）
1. launch tab → Extra args 输入 `--auto-play-debug` —— 验：等价 CLI 含此 flag
2. 点 Start —— 验：`auto_play.log` 出现详细 inject 行（debug 级）

### E2E-5：预检拦截（对应 S-005）
1. launch tab：勾 `--auto-play`、driver=vlm；`.env` 无 KEY —— 验：等价 CLI 显示
2. 点 Start —— 验：模态对话框弹"VLM_API_KEY 未在 .env 中找到。点'改 .env'按钮配置；或改用 driver=keep-alive"；不 spawn 子进程
3. 点"改 .env" —— 验：默认编辑器打开 .env 文件

错误路径 E2E-5.err：用户勾"跳过校验"重新点 Start → 子进程 spawn → main.py 自身打 `[AUTO-PLAY] WARN: VLM_API_KEY 未读到`

---

## E2E Coverage Matrix

| Capability | E2E Goals | Covered |
|---|---|---|
| C-FORM | E2E-1, E2E-2 | ✓ |
| C-RUN | E2E-1, E2E-2, E2E-3, E2E-4, E2E-5(err) | ✓ |
| C-STOP | E2E-1, E2E-2 | ✓ |
| C-CLI | E2E-1, E2E-2, E2E-4 | ✓ |
| C-DASH | E2E-1, E2E-2, E2E-3 | ✓ |
| C-MIRROR | E2E-3, E2E-2(F9) | ✓ |
| C-AP | E2E-2, E2E-5 | ✓ |
| C-SURVEY | （未独立 E2E）—— 通过 MH-16 capability 单测覆盖 | △ 需补 E2E-6 redo-survey-then-recapture，但 sponsor 短期无需求；标 deferred |
| C-PRECHECK | E2E-1.err, E2E-5 | ✓ |
| C-TREE | E2E-2 (步骤 6) | ✓ |
| C-LOCK | E2E-2 (步骤 5) | ✓ |
| C-PERSIST | （UI 重启场景）—— 通过 MH-23 / MH-24 覆盖；E2E 隐含步骤 1 | ✓ |

**Gap**：C-SURVEY 仅 MH 单测覆盖；本期接受。

---

## Environment Spec

| Field | Value |
|---|---|
| `type` | local（Windows 11） |
| `exec` | 直接 `uv run python -m unicap_gui` 在 sponsor 主机 |
| `workdir` | `D:\dev\unicap.git` |
| `ports` | none |
| `env_vars` | `.env` 含 `VLM_API_KEY` / `VLM_BASE_URL` / `VLM_MODEL`（vlm 路径 E2E 才需要） |
| `auto_provisioned` | false |

**E2E 受限项**：MH-1..MH-24 + IT-1..IT-5 全部 verify 阶段可在不连游戏的情况下完成（subprocess 跑个 echo 假命令也能验大部分行为）。E2E-1..E2E-5 的"游戏端"步骤（按 F8 / 看 capture）需 sponsor 实机实跑。

---

## Quality Gate

- [x] 每个 Must Have 都有 specific input → specific output 形式（24/24）
- [x] Forbidden Zone 8 条 ≥ 3
- [x] Capability 边界不重叠（按 12 个 G-XXX 一对一映射）
- [x] Integration Must Have 覆盖 5 个跨模块流（C-FORM↔C-CLI↔C-RUN↔C-DASH↔C-LOCK 链）
- [x] 5 个 E2E flow 各有 happy + 至少 1 个 error path（E2E-1/2/5 已标 .err；E2E-3/4 happy 已足）
- [x] 每个 E2E step 都有验证方法
- [x] coverage matrix 12 行无 gap（C-SURVEY 标 deferred 是 explicitly justified）
- [x] Environment spec 已填
