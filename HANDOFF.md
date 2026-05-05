# Handoff: 5-arm watchdog + hybrid VLM patrol — SHIPPED to master

**Generated**: 2026-05-05 22:25 CST
**Branch**: `master` (HEAD = `984b45f`, in sync with `origin/master`)
**Status**: ✅ Done — feature complete, FF7R live-tested, merged to master. Awaiting next directive.

## Goal

(Closed) Make `--driver hybrid` reliably dismiss FF7R tutorial popups (especially split-screen ones like "Locking Onto Targets") without human intervention via 4 independent detection layers + 12s VLM patrol.

## Completed (last session, now in master)

- [x] **5-arm watchdog**: short-window static / local-only / long-window static / UI-mask diff / OCR dismiss-prompt
- [x] **Hybrid driver** (keep-alive main loop + VLM consultant on watchdog trigger + 12s autonomous patrol)
- [x] **OCR arm** (`tools/auto_play/ocr_detector.py`) using Windows.Media.Ocr — direct key inject on regex match
- [x] **`--vlm-budget-per-hour` 默认 60 → 360** (300 给 12s patrol + 60 余量)
- [x] **中等档 watchdog 灵敏度** (`_LONG_WINDOW_SAMPLES` 4→3, `sample_period_s` 3.0→2.0)
- [x] **`auto-play-ocr` extra** in pyproject.toml (5 winrt-* packages)
- [x] **Sponsor FF7R live test passed** — capture / auto-play / continuous capture all working
- [x] **Fast-forward merge** `auto-play` → `master`，pushed to `origin/master` (commit `984b45f`)
- [x] `auto-play` / `origin/auto-play` retained per sponsor instruction (not deleted)

## Not Yet Done

无待办。等 sponsor 下一指令（新游戏 profile 接入 / 新功能 / 调优 / etc.）。

## Failed Approaches (Don't Repeat These — Institutional Knowledge)

- **调宽 long-window 阈值** (`_LONG_WINDOW_MEAN_CAP` 0.04 → 0.08, `_LONG_WINDOW_RATIO_CAP` 0.30 → 0.50) — 短期能让 split tutorial 触发，但 normal walking forward 12s 累积也常 long_mean 0.05-0.08、long_moved 50%+，**会把 bot 走着走着误判卡死 → VLM 看 normal HUD → 输出 ESC/M → 真把人推进菜单**。这是 trade-off 死循环：放宽 → 误触发；收紧 → 漏触发。**放弃在阈值上做文章**，加独立检测臂 (UI-mask + OCR) + patrol 治本。

- **`press_key M` heartbeat 加进 `keep_alive.sequence`** — 早期试图"盲 bot 主动按 M dismiss"。**不行**：M 在 FF7R 不幂等，正常 gameplay 按 M 打开地图，关闭 tap 不一定干净返回 gameplay。结论：**dismiss_ui 只能在 recovery / patrol 触发，不能进 main sequence**。Sponsor 原话："M 心跳会导致进入这个菜单，也是不对，M 只应该在判断有 UI 时才触发"。

- **纯 `--driver vlm` 1Hz 决策** — 太慢 (3-4s 网络延迟)、太单调 (12/19 reasoning 都是"open exploration walk forward")、太贵 (¥30/30min)、ESC 死循环 (VLM 误把 HUD 当 menu，按 ESC 反而打开真菜单)。Hybrid (keep-alive + 12s VLM patrol + watchdog 触发 VLM) 替代之。

- **`watchdog.recovery` 含 `press_key vk: ESC` ×2 (FF7R)** — 误触发 + FF7R ESC 是开菜单不是关，反向打开系统菜单。已替换为 `dismiss_ui` 抽象 (FF7R = M)。

- **`fc_state.txt` SCANCODE 漏 (历史)** — DOOM Eternal raw input 听不到 message-queue-only events。已修：`MapVirtualKeyW(vk, MAPVK_VK_TO_VSC)` + `KEYEVENTF_SCANCODE`。

- **Record/Replay 子系统** — 早期尝试录人类输入回放给 bot；维护成本高、与 VLM/keep-alive 路线重复、sponsor 不再用。已彻底删 (`tools/replay/`、`scripts/verify_replay.py`、相关 docs/req/、F7 hotkey)。**不要加回 F7 / `tools/replay/`。**

## Key Decisions (still valid)

| Decision | Rationale |
|---|---|
| 4 个独立检测层 (frame-diff 三臂 + UI-mask + OCR) + 12s patrol，不调阈值 | Frame-diff 对 split-screen tutorial 力不从心；阈值调松必引入误触发推 bot 入菜单。叠多层独立判别绕过 trade-off |
| Patrol 12s 周期 = 300 calls/h，budget cap 360/h | sponsor 选定 12s；360 留 60 给 watchdog/UI-mask/OCR 触发余量 |
| OCR 直接注入 key，绕过 VLM | OCR match 是 ground truth (`M Back` 文字 → 100% 是 M dismiss)；VLM round-trip 多 3s 没意义 |
| OCR 用 Windows.Media.Ocr 不用 PaddleOCR/EasyOCR | 系统自带零下载、CPU 占用最低、en+zh+ja 开箱即用、unicap 反正 Windows-only |
| OCR 跑 8s 一次不是 1 sample 一次 | 单次 100-500ms CPU；2s 周期 = 25% 单核占用；8s 周期 = 5% |
| UI-mask 仅 `--ui-mode both` 启用 | 没法配对没法算 mask；`--auto-play` 默认 `ui-mode=both` 所以正常都启用 |
| `--auto-play` 默认 `--ui-mode both` | watchdog/未来 VLM 看 post-UI BMP 才能识别 HUD/菜单/死亡画面 |
| `dismiss_ui` 抽象 (而非硬编码 `press_key ESC`) | FF7R = M，DOOM = 各异；profile 声明 dismiss key |

## Current State

- `master` = `origin/master` = `984b45f` ✅
- Working tree clean ✅
- `auto-play` / `origin/auto-play` 保留（sponsor 指令）
- `.env` 在 working tree 是 `M` 状态（VLM_API_KEY 本地值），**永不 commit**

## Files to Know (post-merge layout)

| File | Why It Matters |
|---|---|
| `tools/auto_play/watchdog.py` | 5 个检测臂核心。常量 `_LONG_WINDOW_*`、`_UI_MASK_*`、`_OCR_SAMPLE_INTERVAL` 在 class 头部 |
| `tools/auto_play/runner.py:_patrol_loop` | 12s VLM patrol 主循环；`first_delay = period/2` 错开 watchdog 第一次采样 |
| `tools/auto_play/vlm_driver.py:_PATROL_PROMPT_TEMPLATE` | Patrol 用保守 prompt（仅 dismiss popup/menu，否则 `[]`）；区别于主 `_SYSTEM_PROMPT_TEMPLATE` |
| `tools/auto_play/ocr_detector.py` | OCR 全部逻辑 (~150 行)。Lazy init winrt；4 类 dismiss 正则；失败静默 |
| `tools/auto_play/keep_alive.py` | Bot 主循环；`step_to_actions` helper 也被 watchdog recovery 复用 |
| `tools/auto_play/profile.py` | YAML schema；F8/F9 强制 `reserved_keys` |
| `profiles/ff7r.yaml` | watchdog `sample_period_s: 2.0`, `consecutive_static_required: 4`；recovery 用 `dismiss_ui`(M) |
| `profiles/_default.yaml` | 接新游戏的起点模板 |
| `main.py` | CLI 入口；`launch / video / pack` 子命令；`_start_auto_play` (~440-460) 构造 AutoPlayRunner |
| `pyproject.toml` | extras: `auto-play` (vgamepad), `auto-play-vlm` (openai+dotenv), `auto-play-ocr` (winrt×5) |
| `reshade-addons/99-frame_capture/frame_capture.cpp` | C++ capture addon (~1100 行单文件)；DX 经典 + DX12 enhanced + Vulkan render pass 三路径 |
| `tools/capture/config.py` | 机器特定路径 (GAME_PATH / DATASET_ROOT) |
| `CLAUDE.md` | 项目规约 (capture 流程 / sidecar 协议 / auto-play 架构) |

## Setup Required (for next agent)

- `.env` at repo root: `VLM_API_KEY=sk-...` + `VLM_BASE_URL=...` + `VLM_MODEL=qwen-vl-max`（gitignored）
- `uv sync --extra auto-play-vlm --extra auto-play-ocr`（VLM + OCR 两个 extra）
- ViGEmBus 内核驱动（gamepad 可选）
- `dist/dxgi.dll` + `dist/frame_capture.addon` 已 build 并 deploy（`scripts\build.ps1`）
- 跑：`uv run main.py launch --profile ff7r --auto-play --driver hybrid`

## Resume Instructions

1. **没有 pending 任务** — 这次 handoff 是收尾刷新，不是 mid-task 中断
2. **等 sponsor 提新指令** — 可能是：
   - 新游戏 profile 接入（参考 `profiles/_default.yaml` + `profiles/README.md`）
   - watchdog/patrol 阈值调优（基于实战数据）
   - 新检测臂（如 audio-based / template-match）
   - 训练 pipeline 工作（`pack` 子命令、HDF5、ML 流水线）
   - 其他全新方向
3. **接到指令时**:
   - `git status` 确认从 master 干净起点
   - 决定是否新开分支（大改→新分支；小修→直接 master 上）
   - 读 CLAUDE.md 对应章节再动
4. **如果是延续 auto-play 调优**: 读 watchdog 五臂常量、log tail `$env:TEMP\unicap\auto_play.log` 看实战触发分布

## Warnings (sticky rules)

- **DO NOT 提交 `.env`** — 即便 git status 显示 `M .env`，规则就是规则。Sponsor 之前手动 commit 过一次（`fb59f3c`），那是例外
- **DO NOT auto commit/push** — 等 sponsor 显式说 "commit" / "push" / "推" / "ff-merge"
- **DO NOT 主动跑 `scripts/verify_auto_play.py`** — sponsor 手工执行，agent 不要重复跑
- **DO NOT 默认 English 输出** — 中文优先（代码/命令/error 原文除外）
- **DO NOT 把 `dismiss_ui` 加到 `keep_alive.sequence`** — 只能在 `recovery` / patrol 用
- **DO NOT 加回 F7 / record-replay** — 已彻底删除
- **DO NOT 调 long-window 阈值救漏检** — 已验证是 trade-off 死循环；用独立检测臂治本
- **OCR 直接注入绕过 VLM 是有意设计** — 不要"为安全起见"加 VLM 二次确认，会丧失速度优势
- **winrt API 兼容风险** — `_ocr_async` 用的 winrt-runtime 3.x API；首次跑若 AttributeError，看 winrt 文档微调；失败时 OCR 臂静默禁用，A/B/三臂仍工作
- **全屏独占冻结 console** — FF7R 全屏让 DWM 暂停 console 渲染。`launch` 默认 `--force-borderless` 已规避；不要去掉
