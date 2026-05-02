# Impact Analysis: 自动玩游戏机制 — A 层 + C contracts

**Date:** 2026-05-02
**Requirements:** [docs/req/auto-play.md](../req/auto-play.md)
**Scope (sponsor 选定):** 方案 3 — A 层 MVP + C 层 contracts 占位（VLMDriver 接口签好不实现）

## 1. Change Summary

新增 `tools/auto_play/` 子系统：定义 `BotDriver` / `InputBackend` / `GameProfile` / `VLMDriver` 接口，落地 `KeepAliveDriver` + `Watchdog` + `InputBackend`(SendInput + ViGEm) + 4 个内置 profile，集成到 `main.py launch` 的 `_run_capture` 生命周期。`VLMDriver` 仅占位（被选择时报"C 层未实现"）。auto-play 注入的 input 走 OS 级 SendInput → 自然进 `inputs.jsonl`，与人类输入无差别。

## 2. Affected Modules / Files

### 新增

| 路径 | 角色 | 估计 LoC |
|------|------|--------|
| `tools/auto_play/__init__.py` | 包入口 + 公开符号 | ~20 |
| `tools/auto_play/driver.py` | `BotDriver` ABC + `Action` / `Observation` dataclass | ~80 |
| `tools/auto_play/input_backend.py` | `InputBackend` — SendInput + ViGEm；按 profile 声明的通道路由 | ~250 |
| `tools/auto_play/profile.py` | `GameProfile` dataclass + `load_profile(name)` + 模糊匹配 exe 名 | ~150 |
| `tools/auto_play/keep_alive.py` | `KeepAliveDriver` — 按 profile sequence 循环出 Action | ~120 |
| `tools/auto_play/watchdog.py` | `StaticFrameWatchdog` — 后台线程采样 BMP，连续静帧触发恢复输入 | ~120 |
| `tools/auto_play/vlm_driver.py` | `VLMDriver` 占位 — 接口签好，`next_actions` 抛 NotImplementedError | ~60 |
| `tools/auto_play/runner.py` | `AutoPlayRunner` — 编排 driver + watchdog + lifecycle | ~150 |
| `profiles/_default.yaml` | 通用 fallback（W/A/S/D + 鼠标） | ~50 |
| `profiles/ff7r.yaml` | FF7R 控制 + 操作约定 | ~60 |
| `profiles/doom_eternal.yaml` | DOOM Eternal 控制 + 操作约定 | ~60 |
| `profiles/batman_ak.yaml` | Batman AK 控制 + 操作约定 | ~60 |
| `profiles/README.md` | profile schema 文档 + 接入新游戏 5 步 | ~80 |

### 修改

| 文件 | 改动 | 估计行数 |
|------|------|--------|
| `main.py` | `cmd_launch` argparse 加 6 个 flag；`_run_capture` 内 wrap auto-play 生命周期；imports | ~50 行新增 |
| `pyproject.toml` | 加 deps：`pyyaml` (硬)、`vgamepad` (软, optional extras `[auto-play]`) | ~5 行 |
| `CLAUDE.md` | 新章节"自动玩游戏（auto-play）" | ~40 行 |

**总计**: 新增 ~1300 LoC（含 YAML + README），修改 ~95 LoC

## 3. Interface Changes

### main.py CLI（向后兼容 — 全新 flag，默认关）

```
launch ... [--auto-play]
           [--driver {keep-alive,vlm}]   # 默认 keep-alive
           [--profile NAME]              # 默认 fuzzy match exe → fallback _default
           [--auto-play-debug]           # 多 log + 不真实注入（dry-run）
           [--vlm-budget-per-hour N]     # 占位 — 仅 vlm driver 用
           [--vlm-budget-total-usd N]    # 占位
```

### 新公共 API（`tools.auto_play`）

```python
from tools.auto_play import AutoPlayRunner, GameProfile, load_profile

runner = AutoPlayRunner(
    driver_name="keep-alive",          # 'keep-alive' | 'vlm'
    profile=load_profile("ff7r"),
    frames_dir=frames_dir,             # 看 BMP 给 watchdog
    debug=False,
)
runner.start()
# ... capture 跑 ...
runner.stop()  # idempotent；blocks until threads joined
```

### 现有接口

- `capture_all.run` — **零改动**。auto-play 与之并行，不侵入。
- `_thread_input` (capture_all) — **零改动**。SendInput 注入的 key 状态会被 `GetKeyboardState` 自然采到 → bot input 落进 `inputs.jsonl`，无 source 字段（per requirement Q7 default）。
- `BotDriver` 是新接口；下次 dev session 实现 C 层时填 `VLMDriver.next_actions()`。

## 4. Integration Points

### 主集成点 — `main.py:_run_capture`

```python
def _run_capture(args, game_dir, game_name, dataset_root, just_surveyed):
    _set_state(game_dir, "capturing")
    # ... 现有 session_dir / frames_dir 准备 ...

    # 【新】auto-play 生命周期 — 与 capture 同生共死
    auto_play_runner = None
    if getattr(args, "auto_play", False):
        from tools.auto_play import AutoPlayRunner, load_profile
        profile = load_profile(args.profile or game_exe.stem, fallback=True)
        auto_play_runner = AutoPlayRunner(
            driver_name=args.driver,
            profile=profile,
            frames_dir=frames_dir,
            debug=args.auto_play_debug,
            vlm_budget_per_hour=args.vlm_budget_per_hour,
            vlm_budget_total_usd=args.vlm_budget_total_usd,
        )
        auto_play_runner.start()

    try:
        capture_all.run(...)         # 现有调用，不变
    finally:
        if auto_play_runner is not None:
            auto_play_runner.stop()
        quit_watcher.set()
        _set_state(game_dir, "idle")
```

### 次集成点 — 长时不睡眠

- `cmd_launch` 启动时调一次 `SetThreadExecutionState(ES_CONTINUOUS|ES_DISPLAY|ES_SYSTEM)` 防系统睡眠/锁屏 — 仅在 `--auto-play` 时启用，避免无故改默认行为。

### 不集成点（明确解耦）

- **C++ addon** — 完全不动。auto-play 全在 Python 层。
- **survey 流程** — 不集成。auto-play 仅在 capture 阶段活跃；survey 阶段不需要（survey 自己控制游戏帧序）。
- **inputs.jsonl 写入路径** — 不动。bot input 与人类 input 共用通路（per requirement）。

## 5. Risk Assessment

| # | 风险 | 概率 | 影响 | 缓解 |
|---|------|------|------|------|
| R1 | ViGEm Bus driver 未装 → `vgamepad` import 失败 | 高（首次部署） | 中 | 软 import，捕 ImportError，warn + fallback 到键鼠通道；profile 声明 `prefer_gamepad: true` 时报清晰错误指引装 ViGEmBus |
| R2 | SendInput 在某些反作弊游戏被 hook 屏蔽 | 中 | 中 | 不绕反作弊（per Constraints）；watchdog 检测到长时静帧 → log + 提示 sponsor |
| R3 | bot 把游戏推入 invalid 状态（角色卡墙、菜单循环）→ watchdog 触发 ESC 也没用 | 中 | 低 | watchdog 只 best-effort；卡死时 sponsor 起来手动救 |
| R4 | 多线程 SendInput 竞争（driver + watchdog 同时注入） | 中 | 高（输入乱序） | `InputBackend` 内部 `threading.Lock` 串行化所有注入调用 |
| R5 | Profile YAML schema 错 → 启动崩 | 中 | 低（启动期） | profile.py 加显式 validate；错误信息指明哪个字段哪行 |
| R6 | BackBuffer.bmp 读取 race（addon 正在写）→ watchdog 取到部分图 | 低 | 低 | `cv2.imread` 失败时跳过该轮，不计为静帧 |
| R7 | 长时 8h 内存泄漏（log 累积、profile 重载） | 低 | 高 | log buffer 限定大小（rolling）；profile 启动加载一次 |
| R8 | bot 的 SendInput 影响 unicap 自己（F8/F9 reserved） | 低 | 高（误触发） | profile schema 强制声明 `reserved_keys: [F8, F9]`，default profile 已含 |
| R9 | F9 停止后 ViGEm 虚拟手柄未及时 disconnect → 系统残留 | 中 | 低 | `AutoPlayRunner.stop()` finally 块释放 ViGEm；类析构兜底 |
| R10 | `--driver vlm` 选了但 C 层未实现 → 用户预期落空 | 中（首版） | 中 | `VLMDriver.__init__` 直接 raise 清晰错误："C 层 VLMDriver 未实现，本版只支持 --driver keep-alive。下个 release 启用" |

## 6. Complexity Estimate

**总体: L**（约 1300 LoC + 4 profile + 集成 + 文档；6-8 个独立子模块）

按子模块拆：
| 子模块 | 复杂度 | 备注 |
|--------|--------|------|
| `driver.py` (ABC + dataclass) | S | 纯定义 |
| `input_backend.py` | M | 双通道（键鼠 + ViGEm）+ 锁 + 软 import |
| `profile.py` | S | YAML + dataclass + 校验 |
| `keep_alive.py` | S | profile sequence → action 循环 |
| `watchdog.py` | S | 单线程 + 像素 diff |
| `vlm_driver.py` (占位) | S | 接口 + raise NotImplemented |
| `runner.py` | M | 多线程编排 + lifecycle |
| profiles/*.yaml | S | 4 份 |
| main.py 集成 | S | 50 行 + argparse |
| 文档 | S | profiles/README.md + CLAUDE.md |

**升级为 L 但不到 XL** — 各子模块独立、深度浅。**不需要切到 architecture-first paradigm**。

**parallel-execution 适用性**：
- driver / input_backend / profile / watchdog 之间几乎无相互依赖（driver 依赖 profile + input_backend 接口签名）
- 但本次 sponsor 是单 agent 实现，并行执行收益小、协调成本高 → **顺序实现**。
- 实现顺序：`driver` (接口) → `profile` → `input_backend` → `keep_alive` → `watchdog` → `vlm_driver` 占位 → `runner` → main.py 集成 → profiles → 文档

## 7. Existing Behavior Preserved

| 现有行为 | 验证方式 |
|---------|---------|
| `--auto-play` 不传时 launch 完全等于现状 | 跑一次 launch 走默认路径，diff 输出与上次一致 |
| F8/F9 仍正常 | auto-play 注入时 reserved_keys 排除 F8/F9（profile 强制） |
| inputs.jsonl 格式不变 | 字段集严格对齐，不加 source 字段（默认） |
| capture_all.run 行为不变 | auto-play 与之并行，不传参不调用 |
| Vulkan / DX 路径无差异 | auto-play 不依赖 api 类型 |
| survey 流程不受影响 | auto-play 仅在 capture 阶段活，不在 survey 阶段活 |
| Nuitka 打包 | 软 import vgamepad；硬 import pyyaml（pyproject 加） |

## 8. 向 C 层（VLMDriver）演进的接口稳定性

`BotDriver.next_actions(observation: Observation) -> list[Action]` 这个签名是 A/C 层共享的核心契约。下次 dev session 接 C 层时**只需新加文件**，不动 A 层任何东西：

```python
# tools/auto_play/vlm_driver.py — 占位版本
class VLMDriver(BotDriver):
    def __init__(self, profile: GameProfile, budget_per_hour: int, budget_total_usd: float):
        raise NotImplementedError(
            "VLMDriver 是 C 层（智能大脑），本 release 仅含 A 层骨架。"
            "下个 dev session 启用：参考 docs/req/auto-play.md G-005/G-006"
        )

    def next_actions(self, obs: Observation) -> list[Action]:
        ...
```

C 层启用后，`runner.py` 已经按名字工厂化（`driver_name='vlm'` → `VLMDriver(...)`），main.py 也已经透传 vlm budget 参数 → C 层 PR 是纯加法。

## 9. Quality Gate

- [x] 所有受影响模块已识别（main.py、新 tools/auto_play/、新 profiles/、pyproject.toml、CLAUDE.md）
- [x] 接口变更显式列出（CLI flag + 新 Python API + addon 零改）
- [x] 集成点明确（`_run_capture` 单点 wrap + 防睡眠 SetThreadExecutionState）
- [x] 风险评估到位（10 项含缓解）
- [x] 复杂度 L — 单 agent 顺序实现，不切 architecture-first

## 10. 中文摘要

新增独立子模块 `tools/auto_play/`，~1300 LoC 跨 6 个 Python 文件 + 4 个 profile YAML。改 `main.py` 加 6 个 launch flag + 50 行 wrap 进 `_run_capture`，与 `capture_all` 并行。**C++ addon / capture_all / survey 全部零改动**。bot 注入的 input 走 OS 级 SendInput / ViGEm，自然被 `_thread_input` 录进 `inputs.jsonl`（与人类输入无差别）。VLMDriver 占位仅签接口，下次 session 加实现是纯加法、不动 A 层。10 个风险点已列缓解；并发风险（R4）通过 InputBackend 内部锁解决；ViGEm 缺失（R1）软降级到键鼠。Quality gate 通过。
