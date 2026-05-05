# Handoff: 5-arm watchdog + hybrid VLM patrol for FF7R popup recovery

**Generated**: 2026-05-05 22:15 CST
**Branch**: `auto-play` (HEAD = `e9f6a3b`, in sync with `origin/auto-play`)
**Status**: Ready for Review — sponsor live-test on FF7R is the open verification gate

## Goal

Make `--driver hybrid` reliably dismiss FF7R tutorial popups (especially split-screen ones like "Locking Onto Targets") without human intervention. Previous 3-arm watchdog never triggered on those because frame-diff statistics can't classify "left half live game + right half popup with GIF" as static.

## Completed (this session)

- [x] **中等档 watchdog 灵敏度调整**
  - `watchdog.py` `_LONG_WINDOW_SAMPLES`: 4 → 3 (long-window 累积 12s → 4-6s)
  - `profiles/ff7r.yaml` `sample_period_s`: 3.0 → 2.0 (short-window 触发 12s → 8s)
- [x] **A. Hybrid 主动 patrol (12s 周期, watchdog-independent)**
  - `vlm_driver.py`: 新 `_PATROL_PROMPT_TEMPLATE` (保守 prompt: 仅 dismiss popup/menu, 否则 `[]`)
  - `vlm_driver.py`: 新 `patrol_check()` + 共享 `_run_once(prompt, tag)` helper
  - `runner.py`: hybrid 模式起 `_patrol_thread`，12s 周期独立轮询
  - `main.py`: `--vlm-budget-per-hour` 默认 60 → 360 (300 给 patrol + 60 余量)
- [x] **B. UI-mask 触发臂 (watchdog 第 4 臂)**
  - `|BackBufferUI - BackBuffer|` mask, ratio ≥ 20% 持续 4s → 触发 VLM
  - 仅 `--ui-mode both` 生效；`no-ui`/`ui` 静默禁用
  - pair 配对要求 mtime 差 ≤ 0.4s
- [x] **C. OCR dismiss-prompt 触发臂 (watchdog 第 5 臂)**
  - 新 `tools/auto_play/ocr_detector.py`: Windows.Media.Ocr (winrt) 封装
  - 4 类 regex: `M Back` / `[ESC] Close` / `Press X to ...` / `按 X 返回`
  - 匹配直接注入 key (绕过 VLM, OCR = ground truth)
  - 每 8s 运行一次 (CPU 100-500ms/call)
  - `pyproject.toml` 新 extra `auto-play-ocr`
- [x] Sanity check 全过 (`import main`, 5 profiles 加载, VLMDriver.patrol_check, ocr_detector.is_available()=False (winrt 未装))
- [x] Commit `e9f6a3b` 已 push 到 `origin/auto-play`

## Not Yet Done

- [ ] **Sponsor live FF7R test** — 启动 `uv run main.py launch --profile ff7r --auto-play --driver hybrid`，走到教程弹窗 (Chapter 1 多)，看下面三类 log 行是否出现：
  - `[PATROL] 检测到 overlay → 注入 N action(s)` — A 触发
  - `[WATCHDOG] UI-mask static (4.0s): ui_ratio=XX%` — B 触发
  - `[WATCHDOG] OCR dismiss-prompt key=M — 直接注入` — C 触发
- [ ] **OCR 实测**: sponsor 跑 `uv sync --extra auto-play-ocr` 后启用 C 臂；首次运行可能因 winrt API 版本差异需小修 (代码有 try/except 兜底，最差静默禁用)
- [ ] **可选阈值调整** — 若 false positive 多：watchdog.py 调 `_UI_MASK_RATIO_TRIGGER` (0.20 → 0.30 更严)；若 false negative：OCR 周期 `_OCR_SAMPLE_INTERVAL` 4 → 2 (4s 一次)

## Failed Approaches (Don't Repeat These)

- **调宽 long-window 阈值** (`_LONG_WINDOW_MEAN_CAP` 0.04 → 0.08, `_LONG_WINDOW_RATIO_CAP` 0.30 → 0.50) — 短期能让 split tutorial 触发，但 normal walking forward 12s 累积也常 long_mean 0.05-0.08、long_moved 50%+，**会把 bot 走着走着误判卡死 → VLM 看 normal HUD → 输出 ESC/M → 真把人推进菜单**。这是 trade-off 死循环：放宽 → 误触发把人推进菜单；收紧 → 漏触发卡 popup。所以**放弃在 long-window 阈值上做文章**，加独立检测臂 (B/C) + patrol (A) 治本。

- **`press_key M` heartbeat 加进 `keep_alive.sequence`** — 早期试图"盲 bot 主动按 M dismiss"。**不行**：M 在 FF7R 不幂等，正常 gameplay 按 M 打开地图，关闭 tap 不一定干净返回 gameplay。结论：**dismiss_ui 只能在 recovery 触发，不能进 main sequence**。Sponsor 原话："M 心跳会导致进入这个菜单，也是不对，M 只应该在判断有 UI 时才触发"。

- **纯 `--driver vlm` 1Hz 决策** — 太慢 (3-4s 网络延迟)、太单调 (12/19 reasoning 都是"open exploration walk forward")、太贵 (¥30/30min)、ESC 死循环 (VLM 误把 HUD 当 menu，按 ESC 反而打开真菜单)。Hybrid 替代之。

- **`fc_state.txt` SCANCODE 漏 (历史)** — DOOM Eternal raw input 听不到 message-queue-only events。已修：`MapVirtualKeyW(vk, MAPVK_VK_TO_VSC)` + `KEYEVENTF_SCANCODE`。

- **`watchdog.recovery` 含 `press_key vk: ESC` ×2 (FF7R)** — 误触发 + FF7R ESC 是开菜单不是关，结果反向打开系统菜单。已替换为 `dismiss_ui` 抽象 (FF7R = M)。

## Key Decisions

| Decision | Rationale |
|---|---|
| 4 个独立检测层 (frame-diff 三臂 + UI-mask + OCR) + 12s patrol，不再调阈值 | Frame-diff 检测对 split-screen tutorial 力不从心；阈值调松必引入误触发推 bot 入菜单。叠多层独立判别绕过这个 trade-off |
| Patrol 12s 周期 = 300 calls/h，budget cap 360/h | sponsor 选定 12s (60-90s 太慢)；360 留 60 给 watchdog/UI-mask/OCR 触发余量 |
| OCR 直接注入 key，绕过 VLM | OCR match 是字面 ground truth (`M Back` 文字 → 100% 是 M dismiss)，VLM round-trip 多 3s 没意义 |
| OCR 用 Windows.Media.Ocr 不用 PaddleOCR/EasyOCR | 系统自带 (零下载)、CPU 占用最低、en+zh+ja 开箱即用、纯 Windows 限定 (unicap 反正是 Windows-only) |
| OCR 跑 8s 一次不是 1 sample 一次 | 单次 100-500ms CPU，2s 周期 = 25% 单核占用会影响游戏；8s 周期 = 5% |
| UI-mask 仅 `--ui-mode both` 启用，single-stream 模式静默禁用 | 没法配对没法算 mask；`--auto-play` 默认 ui-mode=both 所以正常情况都启用 |
| `--vlm-budget-per-hour` 默认从 60 大跳到 360 | 配 12s patrol 必需；纯 vlm 1Hz 模式建议手动 `--vlm-budget-per-hour 3600` |
| 4 个 regex 只匹配 dismiss verb (Back/Close/Cancel/Skip/Exit/Continue/Dismiss/Return + 中文 7 词) | 避免误匹配 "Press W to walk" 之类的 gameplay 提示。匹配关键词必须是"撤销"语义 |

## Current State

**Working** (sanity-checked):
- `import main` ✅, all 5 profiles load ✅
- VLMDriver.patrol_check() exists, `_patrol_prompt` 模板替换 ✅
- ocr_detector imports OK; `is_available()=False` (winrt not installed — expected behavior, C arm silently disabled)
- All auto_play classes import ✅
- Commit `e9f6a3b` push 到 `origin/auto-play` ✅

**Not yet verified** (needs sponsor live game):
- 三个新触发路径在真实 FF7R 教程弹窗里是否生效
- OCR 在 sponsor 装 winrt 后是否能跑通 (winrt async API 我没法本地实测，代码按 winrt-runtime 3.x 写)

**Uncommitted Changes**: 无 (commit `e9f6a3b` 已 push, `.env` 仍 unstaged 按规则不动)

## Files to Know

| File | Why It Matters |
|---|---|
| `tools/auto_play/watchdog.py` | 5 个检测臂的核心。Lines: short-window (~155), long-window (~190), UI-mask (~210), OCR (~245). 阈值常量都在 class 头部 (`_LONG_WINDOW_*`, `_UI_MASK_*`, `_OCR_SAMPLE_INTERVAL`). |
| `tools/auto_play/runner.py:_patrol_loop` | 12s patrol 主循环。`first_delay = period/2` 错开与 watchdog 第一次采样。BudgetExhausted → `self._patrol_disabled = True` 永久禁用 |
| `tools/auto_play/vlm_driver.py:_PATROL_PROMPT_TEMPLATE` | Patrol 用的保守 prompt。区别于主 `_SYSTEM_PROMPT_TEMPLATE`：只输出 key actions (无 mouse/gamepad/wait)，duration_ms 上限 200ms，"uncertain → []" |
| `tools/auto_play/ocr_detector.py` | 全部 OCR 逻辑 (~150 行)。Lazy init winrt。4 类 dismiss 正则。`asyncio.run(_ocr_async())` 包同步接口。失败静默 (logs at debug) |
| `profiles/ff7r.yaml:watchdog` | `sample_period_s: 2.0`, `consecutive_static_required: 4`. 改 sample_period 时记得 watchdog 类常量 `_LONG_WINDOW_SAMPLES` 也要协调 |
| `pyproject.toml:auto-play-ocr extra` | 5 个 winrt-* 包。Sponsor 必须 `uv sync --extra auto-play-ocr` 才启用 C 臂 |
| `main.py:_start_auto_play` (~440-460) | AutoPlayRunner 构造。`vlm_budget_per_hour=getattr(args, "vlm_budget_per_hour", 360)` |
| `.env` | gitignored 之外的本地 VLM_MODEL=qwen-vl-max + API_KEY。**永远不 commit** |

## Code Context

**Watchdog 5-arm wiring** (`tools/auto_play/watchdog.py:_run` excerpt):
```python
# 1. global static (mean ≤ 0.003)
# 2. local-only (moved < 5% AND mean < 0.025)
global_static = mean_diff <= self._diff_threshold
local_only = (moved_ratio < self._LOCAL_MOTION_RATIO_CAP
              and mean_diff < self._LOCAL_MOTION_MEAN_CAP)
if global_static or local_only:
    consecutive_static += 1
    if consecutive_static >= self._consecutive_required:
        self._trigger_recovery(mean_diff, moved_ratio)
        ...

# 3. long-window (current vs N-old: long_mean < 0.04 AND long_moved < 0.30)
self._frame_history.append(current)
if len(self._frame_history) == self._frame_history.maxlen:
    ...
    if long_mean < self._LONG_WINDOW_MEAN_CAP and long_moved < self._LONG_WINDOW_RATIO_CAP:
        self._trigger_recovery(long_mean, long_moved); continue

# 4. UI-mask (only --ui-mode both)
bb_img, ui_img = self._read_latest_pair()
if bb_img is not None and ui_img is not None:
    ui_diff = np.abs(bb_img - ui_img).max(axis=2)
    ui_mask_ratio = (ui_diff > 30).mean()
    if ui_mask_ratio >= 0.20:
        self._ui_mask_consecutive += 1
        if self._ui_mask_consecutive >= 2:  # 4s
            self._trigger_recovery(...)

# 5. OCR (every 8s, direct inject)
self._ocr_tick_counter += 1
if ocr_detector and self._ocr_tick_counter >= self._OCR_SAMPLE_INTERVAL:
    key = ocr_detector.detect_dismiss_prompt(current)
    if key:
        self._backend.inject(Action(kind="key", payload={"vk": key, "event": "press"}, duration_ms=80))
```

**Hybrid runner wiring** (`tools/auto_play/runner.py`):
```python
# driver_name == "hybrid":
self._driver = create_driver("keep-alive", profile)              # main loop, free
vlm_for_watchdog = create_driver("vlm", profile, ...)            # consultant
self._watchdog = StaticFrameWatchdog(..., vlm_driver=vlm_for_watchdog)
self._patrol_vlm = vlm_for_watchdog                              # share same instance
# In start(): if patrol_vlm is not None: spawn _patrol_thread
```

**Patrol loop** (`tools/auto_play/runner.py:_patrol_loop`):
```python
first_delay = max(2.0, self._patrol_period_s / 2)  # stagger from watchdog
self._stop_evt.wait(first_delay)
while not self._stop_evt.is_set():
    if self._patrol_disabled: return
    actions = self._patrol_vlm.patrol_check(obs) or []
    if actions:
        for a in actions: self._backend.inject(a)
    self._stop_evt.wait(max(0.5, self._patrol_period_s - elapsed))
```

**OCR detector signature** (`tools/auto_play/ocr_detector.py`):
```python
def detect_dismiss_prompt(bgr: np.ndarray) -> str | None:
    """Returns "M" / "ESC" / etc. when match found; None otherwise."""

def is_available() -> bool:
    """True iff winrt is installed AND OcrEngine init succeeded."""
```

## Resume Instructions

1. **Sponsor pre-flight**:
   ```powershell
   uv sync --extra auto-play-ocr   # 装 winrt 包，~50MB
   ```
   - Expected: 5 个 winrt-* 包装好；后续 `is_available()` 应返 True
   - If fail: winrt 包索引或 pip 网络问题；OCR 臂会自动 disable，A/B 仍工作

2. **启动 hybrid run**:
   ```powershell
   uv run main.py launch --profile ff7r --auto-play --driver hybrid
   ```
   - Expected console first lines:
     ```
     [AUTO-PLAY] hybrid VLM (12s patrol + watchdog 触发介入) base_url=https://dashscope.aliyuncs.com/compatible-mode/v1 model=qwen-vl-max budget=360/h api_key=set
     [PATROL] 启动 period=12.0s (hybrid mode dismiss-only consultant)
     ```
   - 按 F8 开始 capture，走到教程弹窗

3. **Tail log 观察**:
   ```powershell
   Get-Content "$env:TEMP\unicap\auto_play.log" -Wait -Tail 30
   ```
   - **理想 log 序列** (任一即视为该臂工作):
     ```
     [PATROL] 检测到 overlay → 注入 1 action(s)
     [PATROL] reasoning: tutorial popup 'Locking Onto Targets' with 'M Back' hint, dismiss with M
     ```
     或:
     ```
     [WATCHDOG] UI-mask static (4.0s): ui_ratio=42.3% — 当作 popup
     [VLM] reasoning: tutorial popup ..., dismiss with M
     ```
     或:
     ```
     [WATCHDOG] OCR dismiss-prompt key=M — 直接注入
     ```

4. **若 patrol 频繁误触发** (在 normal gameplay 也注入按键):
   - 在 `_PATROL_PROMPT_TEMPLATE` 强化 "default to NO when uncertain" 措辞
   - 或拉长 patrol 周期: `runner.py:self._patrol_period_s = 12.0` → 20.0

5. **若 UI-mask 误触发** (HUD 也 ratio ≥ 20%):
   - `watchdog.py:_UI_MASK_RATIO_TRIGGER`: 0.20 → 0.30
   - 或加 `_UI_MASK_CONSECUTIVE`: 2 → 3 (6s 持续才触发)

6. **若 OCR 漏触发** (popup 在屏但没匹配):
   - 拷一张 BackBufferUI.png
   - `python -c "import cv2; from tools.auto_play.ocr_detector import detect_dismiss_prompt; img = cv2.imread('BackBufferUI.png'); print(detect_dismiss_prompt(img))"`
   - 如返 None，加新 regex 到 `_DISMISS_PATTERNS`

## Setup Required

- `.env` at repo root: `VLM_API_KEY=sk-...` + `VLM_BASE_URL=https://dashscope.aliyuncs.com/compatible-mode/v1` + `VLM_MODEL=qwen-vl-max`. Gitignored.
- `uv sync --extra auto-play-vlm` (基础 + openai + dotenv)
- `uv sync --extra auto-play-ocr` (新增，5 个 winrt 包，启用 C 臂)
- ViGEmBus 内核驱动 (gamepad；可选)
- FF7R 实机 + sponsor 操作 (Chapter 1 多教程弹窗最容易复现)
- `dist/dxgi.dll` + `dist/frame_capture.addon` 已 build 并 deploy

## Edge Cases & Error Handling

- **winrt 未装** → ocr_detector 一次性 WARN，C 臂禁用；A/B/三臂正常
- **OCR async 调用失败** (winrt API 版本不匹配) → 单次 debug log，下次仍重试；`detect_dismiss_prompt` 返 None
- **VLM_API_KEY 缺** → patrol 第一次 call BudgetExhausted → `_patrol_disabled=True` 永久禁用 patrol，watchdog 仍走 profile.recovery 兜底
- **Patrol vs watchdog 同时触发同一帧** → 两个 thread 各自调 `vlm_for_watchdog.patrol_check` / `next_actions` (不同 prompt)；budget tracker 是 thread-safe，会顺序消耗 calls；可能短时间出现两个 inject 但 input_backend 有 lock，不会冲突
- **Capture-duration 30s 自动 roll** → patrol thread 随 runner.stop() 一并退出 (`_stop_evt` + `join`)；新 session 起新 patrol thread，counter 重置
- **OCR 跑 100-500ms 期间 watchdog 卡住** → 是的，OCR 在 watchdog 主线程跑会阻塞其他臂的本周期检测；下个周期恢复。如果 sponsor 反映这是问题，可改成独立 OCR thread

## Warnings

- **DO NOT 提交 `.env`** — 哪怕 git status 显示 `M .env`，sponsor 之前手动 commit 过一次（`fb59f3c`），但规则就是规则
- **DO NOT auto commit/push** — 等 sponsor 显式说 "commit" / "push"
- **DO NOT 默认 English 输出** — 回答用中文（代码/命令/error 原文除外）
- **DO NOT 把 `dismiss_ui` 加到 `keep_alive.sequence`** — sponsor 已明确反对；只能在 `recovery` 用
- **DO NOT 加回 F7** — record/replay 已彻底删，F7 不再 reserved
- **OCR 直接注入绕过 VLM** — 这是有意设计 (OCR = ground truth)，不要"为安全起见"加 VLM 二次确认，会让 OCR 臂的速度优势丧失
- **Patrol budget 占大头** — 360/h cap 里 patrol 12s 周期就吃 300/h，watchdog 触发太频繁会撞 budget；若 sponsor 反映 BudgetExhausted，先调 patrol 周期 12 → 20s
- **winrt API 风险** — `_ocr_async` 用的 `DataWriter.write_bytes`/`store_async`/`flush_async`/`detach_stream` 是 winrt-runtime 3.x 标准 API，但具体方法签名可能因 winrt 版本微调；首次跑若报 AttributeError，看 winrt 文档微调
