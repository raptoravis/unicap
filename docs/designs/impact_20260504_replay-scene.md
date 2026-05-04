# Impact Analysis: 游戏场景自动化复现（录制 + 回放）

**Date:** 2026-05-04
**Requirements:** [docs/req/replay-scene.md](../req/replay-scene.md)
**Scope:** v1.0 — Proposal B（时序回放 + 视觉同步点；缺 survey 自动 trigger；`_scenes/` 过滤）

## 1. Change Summary

新增 `tools/replay/` 子模块（4 个 Python 文件）：录制玩家在 launch 中的输入流（仿 `capture_all._thread_input` 但出 event diff，不出 raw state）；F6 标视觉同步点；F7 停止；落 `script.jsonl` + `meta.json`。回放时按时序通过现有 `InputBackend` 注入；sync point 处用 dHash 比对当前帧 vs 录制帧，匹配后立即续注入；超时 30s 暂停等 R/Q。集成到 `main.py launch` 现有 `_interactive_loop`，作为进入 idle 之前的"前置阶段"。修改 `pack` / `video` 的 session 扫描过滤，跳过 `_*` 目录。所有 4 个 profile 的 `reserved_keys` 加 F6 / F7。

**关键复用**：
- `tools/auto_play/input_backend.py` 的 `InputBackend` — 整套输入注入通路 + reserved_keys 守卫
- `tools/auto_play/profile.py` 的 `load_profile` — F6/F7 加入 reserved 后顺势用同一 profile
- `tools/capture/survey.py` 的 `survey_mod.run` — G-005 缺 survey 自动跑（与现有 F8 自动 survey 调用同一函数）
- `frame_capture.addon` 的 `fc_output_dir.txt` 协议 — 录制 / 回放期间设置临时目录，捞最新 BMP 做 sync point 截图

**关键不复用**（且 deliberately 不动）：
- `capture_all.py` 的 `_thread_input` raw-state 录制 — 不能直接重放（256-byte kb state diff 复杂、数据量大）；recorder 用更紧凑的 event diff 格式
- `inputs.jsonl` 不作为 replay 源 — replay 用专门的 `script.jsonl`

## 2. Affected Modules / Files

### 新增

| 路径 | 角色 | 估计 LoC |
|------|------|--------|
| `tools/replay/__init__.py` | 包入口 + 公开符号 | ~20 |
| `tools/replay/recorder.py` | `ReplayRecorder` — 后台轮询 + diff 出 event；F6/F7 监听；落 script.jsonl + meta.json | ~250 |
| `tools/replay/player.py` | `ReplayPlayer` — 读 script.jsonl，按时序通过 InputBackend 注入；sync 暂停 + R/Q 处理 | ~280 |
| `tools/replay/sync_match.py` | `dhash(img)` + `hamming(a,b)` + `wait_for_match(ref_path, frames_dir, threshold, timeout)` | ~80 |
| `tools/replay/schema.py` | `script.jsonl` event types + `meta.json` 结构常量 + 简单校验 | ~60 |
| `scripts/verify_replay.py` | sponsor 手工跑的 capability + offline E2E 测试（仿 verify_auto_play.py 风格） | ~250 |

### 修改

| 文件 | 改动 | 估计行数 |
|------|------|--------|
| `main.py` | (a) `cmd_launch` argparse 加 `--record-scene NAME` / `--replay-scene NAME`；(b) `_interactive_loop` 在进入 F8/F9 idle loop 之前 dispatch 录制/回放阶段；(c) F6/F7 VK 常量；(d) `cmd_video` / `cmd_pack` 的 session 扫描加 `not d.name.startswith("_")` filter | ~80 行新增 / 8 行修改 |
| `tools/capture/main.py`(if exists) / `pack_hdf5.py` (if scans game-dir) | 同上 — 任何按 game-dir 子目录扫的代码都要加 `_*` filter | ~5 行 |
| `profiles/_default.yaml` | `reserved_keys: [F8, F9]` → `[F6, F7, F8, F9]` | 1 行 |
| `profiles/ff7r.yaml` | 同上 | 1 行 |
| `profiles/doom_eternal.yaml` | 同上 | 1 行 |
| `profiles/batman_ak.yaml` | 同上 | 1 行 |
| `tools/auto_play/profile.py` | `MANDATORY_RESERVED_KEYS = {"F8", "F9"}` → `{"F6", "F7", "F8", "F9"}`（强制所有 profile 都保留这 4 个） | 1 行 |
| `pyproject.toml` | 不改（dHash 用 numpy + cv2 自实现，无新 dep） | 0 |
| `CLAUDE.md` | 新章节"录制/回放（replay-scene）" | ~40 行 |

**总计**：新增 ~940 LoC，修改 ~100 LoC。

## 3. Interface Changes

### main.py CLI（向后兼容 — 全新 flag，默认关）

```
launch ... [--record-scene NAME]      # 启动后进入录制态；F7 结束后回归 F8/F9 idle
           [--replay-scene NAME]      # 启动后自动回放；完成后回归 F8/F9 idle
```

互斥规则：仅 `--record-scene` 与 `--replay-scene` 互斥。`--auto-play` 与两者均兼容（auto-play 只在 F8 capture 阶段触发，不影响 record/replay 本身的输入注入流）。典型组合 `--replay-scene foo --auto-play` = 自动到达场景 → F8 进入无人值守 capture。

### 新公共 API（`tools.replay`）

```python
from tools.replay import ReplayRecorder, ReplayPlayer, ReplayResult

# 录制
rec = ReplayRecorder(
    scene_dir=Path,        # _scenes/<name>/
    game_dir=Path,         # game exe dir，写 fc_output_dir.txt
    sync_scratch_dir=Path, # addon 临时落 BMP 的目录（_scenes/<name>/_recording_frames/）
    profile_name=str,      # for meta.json
    api=str,               # 'dx'|'vulkan'，for meta.json
)
rec.start()
rec.wait_until_done()  # blocks until F7 pressed (or stop_event set)
rec.save()             # writes script.jsonl + meta.json

# 回放
player = ReplayPlayer(
    scene_dir=Path,
    game_dir=Path,
    sync_scratch_dir=Path,
    profile=GameProfile,   # for InputBackend reserved_keys
    backend=InputBackend,  # injectable for tests
)
result: ReplayResult = player.run()
# ReplayResult: status='reached'|'sync_miss_aborted'|'user_abort'; exit_code
```

### Schema — `script.jsonl`（每行一个 JSON event）

```jsonc
// input event 类型
{"type":"key_down", "t_rel":0.012, "vk":"S"}
{"type":"key_up",   "t_rel":0.245, "vk":"S"}
{"type":"mouse_move", "t_rel":0.030, "x":1230, "y":540}
{"type":"mouse_button_down", "t_rel":0.500, "button":"left"}
{"type":"mouse_button_up",   "t_rel":0.560, "button":"left"}
{"type":"gamepad_button_down","t_rel":0.700,"button":"A"}
{"type":"gamepad_stick","t_rel":0.800,"side":"left","x":0.5,"y":0.0}

// sync event（F6 触发，预留 description 给 v2.0 VLM 用）
{"type":"sync", "id":"S-01", "frame":"sync_01.bmp", "t_rel":12.3, "description":""}
```

### Schema — `meta.json`

```json
{
  "name": "tutorial",
  "version": 1,
  "recorded_at": "2026-05-04T20:30:00Z",
  "recorder_version": "1.0",
  "game_exe": "ff7remake_.exe",
  "api": "dx",
  "window_size": [1920, 1080],
  "mouse_origin": [960, 540],
  "vlm_fallback_enabled": false,
  "syncs": {
    "S-01": {"hamming_threshold": 10, "timeout_s": 30},
    "S-02": {"hamming_threshold": 10, "timeout_s": 30}
  }
}
```

### 修改：`MANDATORY_RESERVED_KEYS`

`{"F8","F9"}` → `{"F6","F7","F8","F9"}`。这是个 schema-breaking 变更：现有 4 个 profile 都已显式列 F8/F9，但没有 F6/F7。若有用户自管的外部 profile 没列 F6/F7 → load_profile 报错。**风险**：profile 校验更严，但外部用户极少（README 才发 1 周），acceptable。

## 4. Integration Points

### 4.1 main.py `_interactive_loop` 改造

伪码：

```python
def _interactive_loop(args, game_dir, game_name, dataset_root):
    # NEW: 前置 record / replay 阶段（互斥，最多一个）
    if args.record_scene:
        _run_record(args, game_dir, game_name, dataset_root)
        # 录制完后落到 idle loop（用户可继续 F8 capture）
    elif args.replay_scene:
        ok = _run_replay(args, game_dir, game_name, dataset_root)
        if not ok:
            sys.exit(2)  # sync miss 用户 Q 退；succ 后正常进 idle

    # 原有 F8/F9 idle loop 保持不变
    while True:
        ... 已有逻辑
```

`_run_record` / `_run_replay` 是新函数，组织：
- `_run_record`: 启动 ReplayRecorder + spawn F7 watcher 线程；阻塞到 watcher 释放
- `_run_replay`: G-005 检查 survey 缓存 → 缺则调 `_run_survey`；归位鼠标到屏幕中心；启动 ReplayPlayer

### 4.2 fc_output_dir.txt 协议复用

录制期间：
- 写入 `<game_dir>/fc_output_dir.txt = <_scenes/<name>/_recording_frames/>`
- addon 持续往 `_recording_frames/` 落 BMP（继承现有 FC_TargetFPS 节奏）
- F6 触发：扫 `_recording_frames/` 找最新 mtime 的 `*BackBuffer.bmp`，复制为 `_scenes/<name>/sync_NN.bmp`
- F7 触发：清空 `fc_output_dir.txt`（addon 停止落 BMP）；可选删 `_recording_frames/` 释空间（不删也不影响，下次录制会清）

回放期间：
- 同样设 `fc_output_dir.txt = <_scenes/<name>/_replay_frames/>`
- SyncMatcher 在 sync event 处轮询 `_replay_frames/` 取最新 BMP 比对
- 回放结束清 `fc_output_dir.txt`

**冲突防护**：F8 capture 启动时 `capture_all.run` 自己也写 `fc_output_dir.txt` → 覆盖 record/replay 的设置 → 无问题，因为此时 record/replay 已经结束。

### 4.3 InputBackend 复用

ReplayPlayer 持有 `InputBackend(profile, debug=...)`，event → Action mapping：

| script event | Action |
|--------------|--------|
| `key_down` | `Action(kind="key", payload={"vk":..., "event":"down"})` |
| `key_up` | `Action(kind="key", payload={"vk":..., "event":"up"})` |
| `mouse_move` | `Action(kind="mouse", payload={"op":"move", "dx":<delta>, "dy":<delta>})` ⚠ |
| `mouse_button_down/up` | `Action(kind="mouse", payload={"op":"click", ...})` 拆为 down + 间隔 + up |
| `gamepad_*` | 直接 map |

⚠ **mouse_move 设计**：script 里存的是绝对 `[x, y]`（GetCursorPos 输出），但 SendInput MOUSE 是相对 dx/dy。Player 用 `SetCursorPos(x*sx, y*sy)`（直接置位，不走 InputBackend），其中 `sx, sy = current_window_size / recorded_window_size`。**已知限制**：fullscreen FPS 游戏锁鼠标到中心（GetCursorPos 永远返 [center]），录制不出有效 look 数据 → 回放 mouse_move 等价 no-op。Acceptable for v1.0（请求场景是菜单导航）。

### 4.4 Survey 自动 trigger（G-005）

`_run_replay` 第一步：

```python
if _load_recommended_skip(dataset_root, game_name) is None:
    print("[REPLAY] no survey cache, running survey first...")
    ok = _run_survey(args, game_dir, game_name, dataset_root)
    if not ok:
        sys.exit(3)  # G-005 退出码 3
```

完全复用现有 `_run_survey` —— 不需要修改 survey 模块。

### 4.5 `_*` 过滤补丁（G-006）

`main.py` 现有两处：
- L893 `cmd_video`：`d.is_dir() and d.name != "survey" and (d / "frames").is_dir()`
- L953 `cmd_pack`：同上

改为：
- `d.is_dir() and not d.name.startswith("_") and d.name != "survey" and (d / "frames").is_dir()`

`pack_hdf5.py` 单独跑模式有 `--frames-dir` 直接指定，不扫 game dir，不影响。

### 4.6 鼠标归位（G-002）

`_run_replay` 在注入第一个 event 之前调：

```python
import ctypes
SM_CXSCREEN, SM_CYSCREEN = 0, 1
w = ctypes.windll.user32.GetSystemMetrics(SM_CXSCREEN)
h = ctypes.windll.user32.GetSystemMetrics(SM_CYSCREEN)
ctypes.windll.user32.SetCursorPos(w // 2, h // 2)
```

**多显示器注意**：`GetSystemMetrics(SM_CXSCREEN)` 返回主显示器 width，正合需求（游戏窗口正常在主屏）。

## 5. Risk Assessment

| 风险 | 评估 | 缓解 |
|------|------|------|
| **mouse-look 录制不可用**（FPS 锁鼠标） | 中 — 限制了录制范围 | 文档明记；scenarios 限定为菜单/导航；v2.0 VLM 兜底可恢复 |
| **F6/F7 与游戏内键冲突** | 低 — 项目已确立 F6-F12 是 unicap 保留区 | profile 校验扩为强制 4 键 |
| **MANDATORY_RESERVED_KEYS 扩容破坏外部 profile** | 极低 — README 才 1 周，外部用户少 | release notes / handoff 提示 |
| **dHash 阈值 10 不通用** | 中 — 不同游戏 / 不同 sync 帧差异大 | per-sync `hamming_threshold` 覆写 + 默认 30s 超时 + paused 态 R/Q 兜底 |
| **`_recording_frames/` 占空间** | 低 — 30s 录制 ≈ 900 BMP × 6MB ≈ 5GB | F7 后清理；同名 BMP 被 addon 不断覆盖（按 timestamp 命名 → 不会覆盖 → 真会涨）— **解决**：record 完直接 shutil.rmtree _recording_frames/ |
| **addon 写 BMP 与 SyncMatcher 读冲突** | 低 — watchdog 已踩过这坑 | 复用 watchdog 的 `_BMP_MIN_AGE_S = 0.5` 模式：只读 mtime 早于 0.5s 的 BMP |
| **录制时按 F8 误触发 capture** | 低 — F8/F9 watcher 在 idle 阶段才安装 | record/replay 阶段不安装 F8 watcher；显式提示用户"录制中 F8/F9 不响应" |
| **多显示器 SetCursorPos 错位** | 低 — 多显示器时主屏中心一般够用 | 文档说明；用户可手动 `--no-cursor-recenter`（v1.1 加）|
| **script.jsonl 文件体积** | 低 — 录制 1 小时 ≈ 120Hz × 3600 = 432K events × ~80B/event = 35MB | 接受；JSONL 易调试 |
| **回放 events 的时序漂移**（系统调度抖动） | 中 — long-running 回放可能累积漂移 | event 间用 absolute t_rel sleep（不累加 delta），自动校正 |

## 6. Complexity Estimate

**M (Medium)** — 6 新文件 + 7 改动文件，~940 LoC 新增；3 个新概念（recorder/player/sync）；高复用现有 InputBackend / profile / survey；不动 C++。

不需要 `extract-contracts` phase（模块间耦合不强：recorder 独立、player 调 backend / sync_match、main.py 编排）。

不需要 parallel-execution（M 复杂度，单 dev 足够）。

## 7. 决策点（impl 前确认）

以下 2 点改动 sponsor 之前未直接拍板，但属于 impact-driven 必要细节。**默认按推荐方案落，sponsor 反对再调**：

| 点 | 推荐 | 备选 | 影响 |
|---|---|---|---|
| `MANDATORY_RESERVED_KEYS` 加 F6/F7 | 是 | 否（仅在 4 个内置 profile 加，不强制） | 推荐：未来扩展 record-only profile 也安全；备选：外部 profile 不会因升级炸 |
| `--record-scene` / `--replay-scene` 与 `--auto-play` 互斥 | **否**（sponsor 拍板）— 允许 `--replay-scene foo --auto-play` 组合 = 自动到场景 → F8 capture+auto-play 无人值守 | 是（早 fail） | 选不互斥：解锁"replay → 无人值守"杀手用法，auto-play 只在 F8 capture 阶段触发，技术上完全兼容 |

## 8. Out of Impact（明确不改）

- `frame_capture.cpp` / `dxgi.dll` / shader — C++ 层零改动
- `capture_all.py` — 不改（_thread_input 继续录 inputs.jsonl 给 ML 用）
- `survey.py` — 不改（直接复用 `survey_mod.run`）
- `pack_hdf5.py` — 仅在主入口扫描时改（如果它有；否则不动）
- `tools/auto_play/runner.py` / `watchdog.py` / `vlm_driver.py` — 不动
- `pyproject.toml` deps — 不加新 dep（dHash 用 numpy + cv2 自实现）
