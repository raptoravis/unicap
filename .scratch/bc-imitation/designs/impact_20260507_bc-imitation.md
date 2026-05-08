# Impact Analysis — BC Imitation Auto-Play

**Date:** 2026-05-07
**Paradigm:** enhancement/delta-design
**Source spec:** `/zero-review:req` requirements doc v1.0 (HIGH)

## Change Summary

把 unicap 现有的录帧+录输入采集管线复用为"人类 demo 数据集"，新增训练子系统（PyTorch 在 `[train]` extra 下，仅训练时安装）产出 per-game ONNX 模型，并在 `auto_play` 子系统加新 `BCDriver` 与现有 `KeepAliveDriver` 并存（profile 切换）。共 5 个独立可交付的 goals (G-001..G-005)，每个单独是 S/M 复杂度，组合 XL。**分期上线**。

## Existing Structure（已 mapped）

| Module | Owns |
|--------|------|
| `main.py` | argparse subcommands `launch / video / pack`，F8/F9 watcher，`_run_capture()` 编排 capture + auto-play |
| `tools/capture/capture_all.py` | 输入线程 (120Hz `GetAsyncKeyState` + `GetCursorPos` + XInput) → `inputs.jsonl`；帧由 ReShade addon 写 frames_dir |
| `tools/capture/pack_hdf5.py` | inputs.jsonl + frames → HDF5（`/color, /depth, /normal, /kb, /mouse, /gamepad, /frame_ts, /input_ts, /input_dt_ms`） |
| `tools/auto_play/profile.py` | YAML schema + 校验；`MANDATORY_RESERVED_KEYS = {F8, F9}` |
| `tools/auto_play/runner.py` | `AutoPlayRunner` + `create_driver()` factory（**当前硬编码 KeepAliveDriver**） |
| `tools/auto_play/driver.py` | `BotDriver` ABC + `Action` / `Observation` 数据契约 |
| `tools/auto_play/takeover.py` | 人类按键 3s 检测；`is_taken_over()` 已是 public |
| `tools/auto_play/watchdog.py` | 后台读 `BackBuffer.png` 做静帧检测 |

## Affected Modules / Files（按 goal 拆分）

### G-001：record-demo
- `main.py`：`launch` 加 `--record-demo` flag；`_run_capture` 分支：record-demo 时跳过 `_start_auto_play`，启动 F6/F7 watcher 维护 `quality_state` 共享变量
- `tools/capture/capture_all.py`：`_thread_input` 接收可选 `quality_provider: Callable[[], int]`，每条 entry 写 `demo_quality` 字段
- `tools/capture/pack_hdf5.py`：解析 `demo_quality`，HDF5 加 `/demo_quality (N,) uint8`；缺省时不写该 dataset（向后兼容）
- `tools/auto_play/profile.py`：`MANDATORY_RESERVED_KEYS` 加 `F6/F7`（统一 unicap 自管理热键）

### G-002：train-bc
- `pyproject.toml`：新增 `[project.optional-dependencies].train = ["torch", "torchvision", "onnx", "h5py", ...]`
- `tools/train/__init__.py`（新）
- `tools/train/bc_dataset.py`（新）：HDF5 → torch.utils.data.Dataset；从 `/color`（resize 256×144）+ `/kb` + `/mouse` 推导 (frame_window, label_dict)；按 `/demo_quality` 加权
- `tools/train/bc_model.py`（新）：冻结 ResNet18 (torchvision pretrained) → 1×1 neck → LSTM(8 帧) → 多 head (kb_logits / mouse_dir_logits / mouse_btn_logits)
- `tools/train/bc_train.py`（新）：trainer + ONNX export + metrics.json
- `main.py`：`train-bc` subcommand 接 args → `tools.train.bc_train.run()`；training extra 缺失时友好报错

### G-003：BCDriver
- `pyproject.toml`：runtime deps 加 `onnxruntime`（CPU；GPU/DirectML 走 extras）
- `tools/auto_play/profile.py`：schema 扩展 `driver: keep_alive | bc`（缺省 `keep_alive`）+ `bc:` 段（`model_path`, `min_confidence`）；schema 校验 ui-mode meta 一致性
- `tools/auto_play/bc_driver.py`（新）：`BCDriver(BotDriver)` 加载 ONNX；维护 8 帧 rolling buffer（每 `decision_period_s` 读一次最新 BackBuffer.png）；hysteresis；翻译多 head 输出 → `Action[]`
- `tools/auto_play/runner.py`：`create_driver()` 改为按 `profile.driver` dispatch
- `profiles/_default.yaml` 等：声明 `driver: keep_alive`（显式 = 文档化；缺省也兼容）

### G-004：--record-recovery
- `main.py`：`--record-recovery` flag；启动时把 `runner._takeover` 实例引用挂到 `quality_provider` 上
- `tools/capture/capture_all.py`：`quality_provider` 现在感知 takeover → 接管期间发 `good_recovery=3`
- `tools/train/bc_train.py`：`--recovery-weight` flag，sample weight 应用 `good_recovery`

### G-005：eval_bc
- `scripts/eval_bc.py`（新）：CLI 加载 ONNX + held-out HDF5 → metrics.json schema
- 复用 `tools/train/bc_dataset.py` 的 reader

## Interface Changes

| Interface | Change | Backward-Compat |
|---|---|---|
| `BotDriver` ABC | None | ✅ |
| `Action` / `Observation` dataclass | `Observation.frame_bgr` 现在 BCDriver 真用 | ✅（之前 None） |
| `inputs.jsonl` schema | 加 optional `demo_quality: int`（0=unmarked default） | ✅（旧文件不写该字段，pack 视为 0） |
| HDF5 schema | 加 optional `/demo_quality (N,) uint8` | ✅（旧 dataset 不含此 key） |
| Profile YAML schema | 加 optional top-level `driver` (default `keep_alive`) + `bc:` 段（仅 `driver: bc` 时必填） | ✅（旧 profile 不写 = keep_alive） |
| `MANDATORY_RESERVED_KEYS` | 加 F6/F7 | ⚠️ **breaking** for profiles 已声明 controls 用 F6/F7 — 当前所有 profile 都没用，OK |
| `tools/auto_play/runner.create_driver` | dispatch on profile.driver | ✅（profile 不声明 = keep_alive） |
| `pyproject.toml` deps | 加 `onnxruntime` 到 runtime；新增 `[train]` extra | ⚠️ standalone exe 体积 +60-100MB（onnxruntime） |
| `main.py` argparse | `launch` 加 `--record-demo`/`--record-recovery`；新增 `train-bc` subcommand | ✅ 纯加法 |

## Integration Points

1. **F6/F7 watcher**：与现有 F8/F9 watcher 同结构（`_spawn_f9_watcher` 类似），监听 `GetAsyncKeyState` 全局轮询；写入 `quality_state` 由 input thread 读
2. **`quality_provider` 注入**：`_run_capture` 构造 `quality_provider` 闭包传给 `capture_all.run`；G-001 时仅 F6/F7，G-004 时叠加 takeover_detector
3. **BCDriver ↔ frame source**：BCDriver 直接 `cv2.imread(frames_dir / latest_BackBuffer.png)`；与 watchdog 同源，不冲突（独立 file handle）
4. **Profile dispatch**：`runner.create_driver(profile)` 单点 if-else
5. **Train pipeline ↔ HDF5 dataset**：`bc_dataset.py` 单方向读，不写
6. **ONNX 模型路径**：profile YAML 写绝对/repo-relative；BCDriver 解析时 cwd 用 `repo_root()`

## Risk Assessment

| # | Risk | Severity | Mitigation |
|---|------|---------|-----------|
| R1 | 添加 onnxruntime 到 runtime → standalone exe +60-100MB | M | 接受；GUI 包已 293MB，CLI 包 82MB，加 60MB 仍可用。文档说明 |
| R2 | F6/F7 与某 profile 控制键冲突（未来） | L | `MANDATORY_RESERVED_KEYS` 强制；启动时 raise 友好错 |
| R3 | BCDriver 单帧推理 > 50ms（CPU） → 30Hz 不够 | M | G-003 verify 阶段实测 ResNet18@256×144 + LSTM(8) ≤ 50ms；超了就降分辨率到 224×128 或换 MobileNetV3-Small |
| R4 | PyTorch on Windows install 失败 | M | `[train]` extra 隔离；安装文档明示；不影响主 runtime |
| R5 | 10 分钟数据训出来 F1/accuracy 不达阈值 | H | spec 已下调阈值（F1≥0.55, mouse_dir≥0.45）；若仍不达，文档说明这是数据预算下的现实；用户可加录数据 |
| R6 | inputs.jsonl 写 `demo_quality` 字段 → 旧 pack 路径解析报错 | L | pack 用 `entry.get("demo_quality", 0)`；旧 inputs 兼容 |
| R7 | profile schema 加字段可能让旧 profile 解析失败 | L | 新字段全是 optional with default；现有 5 个 profile（_default/ff7r/doom_eternal/batman_ak）跑通验证 |
| R8 | takeover detector 引入误判 → 错把 bot 自己的 inject 标 good_recovery | M | 已有 `_lock` + `bot_inject_grace_s` 双重过滤（见 `takeover.py` doc）；复用即可 |

## Complexity Estimate (per goal)

| Goal | Complexity | Files Touched | New Files | Est. LoC |
|------|-----------|---------------|-----------|----------|
| G-001 record-demo | **S** | 4 (main, capture_all, pack_hdf5, profile) | 0 | ~150 |
| G-002 train-bc | **M** | 2 (main, pyproject) | 4 (tools/train/*) | ~600 |
| G-003 BCDriver | **M** | 4 (profile, runner, pyproject, _default.yaml) | 1 (bc_driver) | ~300 |
| G-004 record-recovery | **S** | 3 (main, capture_all, bc_train) | 0 | ~80 |
| G-005 eval_bc | **S** | 0 | 1 (eval_bc.py) | ~120 |
| **Total** | XL（拆 5 期 S+M+M+S+S） | — | 6 | ~1250 |

每期独立可 verify、可 commit、可 ship，符合 enhancement/delta-design 的 "S/M per phase" 限制。

## Phase / Quality Gates

每期单独走：
1. implement
2. sanity check（`uv sync` + lint + 现有路径不退化 smoke）
3. **停在 unstaged 等用户 commit/push**（用户 CLAUDE.md 明示）

跨期不依赖未实现的 goal（G-001 不依赖 G-002，etc.）。G-004 需要 G-003（recovery 只有 BC 跑时才有意义），其余无强依赖。

## Out-of-Scope Reminders（spec 锁死，本次不做）

- RL fine-tune；跨游戏共享权重；手柄输出；GUI 训练界面；模型 zoo；多卡训练；在线学习；自动数据增广；自动 reward
