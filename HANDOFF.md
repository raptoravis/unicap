# Handoff: replay-scene v1.0 落地 + auto-test findings 修完

**Generated**: 2026-05-04 22:00
**Branch**: `auto-play`（push 到 `origin/auto-play`，HEAD = `18b575f`，工作树**干净**唯一例外是 `uv.lock` mirror URL 噪音，未 commit）
**Status**: replay-scene v1.0 + 全自动无人值守 + auto-test findings 全修；offline 33/33 PASS。两条主线（VLMDriver 30min FF7R + replay-scene 实机录回放）都等 sponsor 实机验收。

## Goal（本 session）

回应 sponsor 请求"测试游戏时反复拉起游戏 + 进入某场景太繁琐"。走完 zero-review 全流程：req → impact → testplan → impl → verify → auto-test → 修 findings → commit + push。

## Completed（本 session）

### 主交付（2 个 commit）

- `66af6bd feat: replay-scene v1.0 — 录制/回放游戏场景 + 全自动无人值守组合`
  - 新增 `tools/replay/` 5 个 Python 文件（recorder + player + sync_match + schema + __init__）
  - `--record-scene NAME` / `--replay-scene NAME` / `--auto-capture` 三个 launch flag
  - 杀手组合：`--replay-scene foo --auto-play --auto-capture` = 0 按键无人值守
  - InputBackend 扩展 mouse / gamepad `down` / `up` op（向后兼容）
  - profile `MANDATORY_RESERVED_KEYS` 加 F6 / F7；4 个内置 profile 同步
  - `pack` / `video` session 扫描加 `_*` 前缀过滤
  - C++ 层零改动；不引新 dep（dHash 用 cv2 + numpy 自实现）

- `18b575f fix: replay-scene auto-test findings (BUG-003/004 + FEAT-001)`
  - BUG-003：空字符串 / 纯空白 scene 名 → 早 fail
  - BUG-004：scene 名禁 `..` / `/` / `\` / Win 文件名禁字符
  - FEAT-001：新增 `scenes` 子命令列出已录场景

### 文档

- `docs/req/replay-scene.md` — requirements v1.0 (HIGH confidence)
- `docs/designs/impact_20260504_replay-scene.md` — impact 分析
- `docs/designs/testplan_20260504_replay-scene.md` — TPDD test plan
- `docs/feedback/replay-scene_session_20260504.md` — auto-test session report (5 findings)
- `CLAUDE.md` — 新章节"录制 / 回放（replay-scene）"

### 验证

- `scripts/verify_replay.py` — 33 个 offline 测试（capability + integration + offline E2E + finding-fix coverage）全绿
- 没跑 `verify_auto_play.py`（per memory `feedback_no_auto_verify`）

## Not Yet Done

- [ ] **sponsor 30 min FF7R 实机验收**（两条主线一起）：
  - **VLMDriver C 层** — 上一 session 落地，至今未实机：schema 错误率 ≤ 5% + watchdog 频率合理 + `[VLM-COST]` 数据写入
  - **replay-scene v1.0** — 本 session 落地：录 FF7R 启动→进入陷落区脚本（按 F6 / F7）→ 第二天 `--replay-scene tutorial` 验证抵达；测 `--replay-scene + --auto-play + --auto-capture` 三连无人值守
- [ ] **merge `auto-play` → `master`**（待两条主线实机过后；按 CLAUDE.md 风险规则，agent 不主动 merge）
- [ ] **`scripts/verify_auto_play.py` 的 watchdog timing flake**（不阻塞 merge，前 session 起就偶发）
- [ ] **`uv.lock` 噪音**（本地清华源切换；下次 `uv run` 又会变；属环境配置，不入 commit）

## Failed Approaches (Don't Repeat These)

### 本 session

#### 1. 把 mouse_button_down/up 直接走 InputBackend op="click"

`click` 是设计为 down+up 一起发 → 录回放时按 down 发会被强制带个 up → 时序错乱。
**学到**：扩展 InputBackend 加 op="down" / "up" 才能支持回放分离时序（gamepad 同理加 button_down / button_up）。

#### 2. ⚠ emoji 在 cmd_scenes 输出

Windows GBK 终端 `print(...)` 在 stdout 重定向场景下 GBK 编码不识别 `⚠` → UnicodeEncodeError 把整个 verify 跑挂。
**学到**：跨平台 console 输出**永远用 ASCII**（[!] / [OK] / [FAIL]），不要 emoji。survey.py 老代码里有 ✓ / ✗ 是历史包袱，新代码不要再用。

#### 3. 试图自动跑 `verify_auto_play.py` 检验回归

虽然出于"跨改动 input_backend.py 应顺手 spot-check"的好意跑了一次，但违反 memory `feedback_no_auto_verify`。
**学到**：sponsor 明示不要主动跑 verify_auto_play.py — 即便是 spot-check 也要先问一句。本 session 在产出报告时已自检并标记，不再犯。

### 上 session（仍生效）

详见 `git log` `7a7b886` / `f854ccc` / `f7b8054` handoff。

## Key Decisions（本 session）

| Decision | Rationale |
|----------|-----------|
| 范式选 B（时序 + 视觉同步点）而非 A（纯时序） | 启动场景的杀手是加载方差（启动器更新 / shader compile），纯时序一周就废；视觉校验点是行业标准 |
| dHash + numpy 自实现，**不**引 Pillow | < 20 行代码够用；少一个 dep 就少一份维护负担 |
| `MANDATORY_RESERVED_KEYS` 由 {F8,F9} 扩到 {F6,F7,F8,F9} | F6/F7 是 unicap 第 2 套全局 hotkey，profile 必须保留；外部 profile 极少（README 才发 1 周）所以可接受 schema break |
| `--auto-play` **不**与 record/replay 互斥（sponsor 改判）| `--replay-scene + --auto-play + --auto-capture` 三连是杀手用法；技术上 auto-play 只在 F8 capture 阶段触发，与 record/replay 完全不冲突 |
| 跳过 mouse-look 录制（FPS 锁鼠到中心 → GetCursorPos 等价 no-op） | 启动 → 进场景 99% 是菜单导航，FPS look 不是核心场景；文档明记限制 |
| `_*` 前缀目录约定（`_scenes/` / `_recording_frames/`）| 与 `survey/` 一起被 `pack` / `video` 扫描排除；统一语义比一个个特判清晰 |
| 录制 / 回放 scratch 目录用完 `rmtree` | BMP 按 timestamp 命名不会覆盖，30s 录制能涨 5GB；不清理是真实 disk hazard |
| 错误消息用 ASCII `[错误]` / `[!]` 不用 emoji | Win GBK console encoding 问题；emoji 会 crash 子进程的 print(stdout) |
| BUG-002 precheck 在 `cmd_deploy` 之后、`subprocess.Popen` 之前 | deploy 是幂等的（只写 ini / symlink），代价低；早 fail 在 game launch 前帮 sponsor 省 30s typo iteration |

### 上 session 决策（仍生效）

详见 `a1f829f` / `7a7b886` 的 handoff Key Decisions。

## Current State

**Working**:
- 远端 `origin/auto-play` HEAD = `18b575f`，本地一致
- 33/33 offline tests 全绿（`uv run python scripts/verify_replay.py`）
- 4 个内置 profile load 通过（含新 F6/F7 reserved 校验）
- 上 session VLMDriver / force_borderless / [CAPTURE] 频率改动**全部未动**

**Broken**: 无

**Uncommitted Changes**:

```
~ Modified: uv.lock   (mirror URL 噪音，pypi.org → tuna 清华，不入 commit)
```

## Files to Know

| File | Why It Matters |
|------|----------------|
| `tools/replay/recorder.py` | 120Hz state diff → event；F6/F7 hotkey 监听；落 `script.jsonl` + `meta.json` |
| `tools/replay/player.py` | 按 absolute t_rel 调度；event → Action；sync 等待 + paused R/Q |
| `tools/replay/sync_match.py` | dHash 自实现 + `wait_for_match`（汉明距离 ≤ 10 视为同图） |
| `tools/replay/schema.py` | `script.jsonl` event 类型 + `meta.json` 模型 + 校验（forward-compat 设计 — 未知字段不报） |
| `main.py` | 新增 `_validate_launch_args` / `_validate_scene_name` / `_precheck_scene` / `_run_record` / `_run_replay` / `cmd_scenes` |
| `tools/auto_play/input_backend.py` | mouse op +`down`/`up`；gamepad op +`button_down`/`button_up`（回放分离时序需要） |
| `tools/auto_play/profile.py` | `MANDATORY_RESERVED_KEYS = {F6,F7,F8,F9}` |
| `scripts/verify_replay.py` | sponsor 一条命令跑 33 个 offline 测试 |
| `docs/req/replay-scene.md` | requirements v1.0（含 G-001~G-006 + scenarios + open questions） |
| `docs/designs/impact_20260504_replay-scene.md` | impact 分析 + 决策表 |
| `docs/designs/testplan_20260504_replay-scene.md` | TPDD + E2E 矩阵 |
| `docs/feedback/replay-scene_session_20260504.md` | auto-test 5 findings（4 已修，1 是 v1.1 增强 list-scenes 已落） |

## Code Context（关键 API）

### 杀手命令组合

```bash
# 全自动无人值守：replay → 自动 capture → bot 接管
uv run main.py launch --replay-scene tutorial --auto-play --auto-capture

# 单独使用
uv run main.py launch --record-scene tutorial    # F6 标 sync, F7 停
uv run main.py launch --replay-scene tutorial    # 缺 survey 自动跑
uv run main.py scenes --game-dir DIR             # 列已录场景
```

### `tools/replay` 公共 API

```python
from tools.replay import (
    ReplayRecorder, ReplayPlayer, ReplayResult,
    iter_events, load_meta, write_meta, validate_meta, RECORDER_VERSION,
)

# 录制
rec = ReplayRecorder(scene_dir=..., sync_scratch_dir=..., game_dir=...,
                     game_exe=..., api=..., window_size=..., mouse_origin=...,
                     scene_name=...)
rec.start(); rec.wait_until_done(); rec.save(); rec.close()

# 回放
player = ReplayPlayer(scene_dir=..., sync_scratch_dir=..., game_dir=...,
                      backend=InputBackend(profile),
                      current_window_size=...,
                      paused_input_provider=None)  # None = real GetAsyncKeyState
result: ReplayResult = player.run()
# result.status: 'reached' | 'sync_miss_aborted' | 'user_abort' | 'script_error'
# result.exit_code: 0 / 2 / 3 / 130
```

### Schema

`script.jsonl` 每行 1 个 JSON event（type ∈ {key_down/up, mouse_move, mouse_button_down/up, gamepad_*, sync}）；`meta.json` 含 `name`/`version`/`recorded_at`/`recorder_version`/`game_exe`/`api`/`window_size`/`mouse_origin`/`vlm_fallback_enabled`/`syncs`（per-sync threshold + timeout 覆写）。详见 `docs/designs/impact_20260504_replay-scene.md` § 3 或直接读 `schema.py`。

## Resume Instructions

### 接班 agent 第一件事

```bash
git status                 # 应见 modified uv.lock（mirror 噪音，不要 commit）
git log --oneline -5       # 应见 18b575f → 66af6bd → a1f829f → 7a7b886 → f854ccc
uv run python scripts/verify_replay.py  # 应 33/33 PASS
```

### sponsor 实机验收（核心 — 卡了一周）

**两条主线一起跑**（推荐顺序：先 replay-scene 再 VLM，因为 replay-scene 简单）：

```powershell
# (1) replay-scene v1.0 实机验收
uv run main.py launch --record-scene tutorial
# F6 在每个加载界面 / 菜单切换前后按一下 → F7 停止
# 检查 _scenes/tutorial/ 落了 script.jsonl + meta.json + sync_NN.bmp

# 第二天（或重启电脑后）
uv run main.py launch --replay-scene tutorial
# 期望：自动到达陷落区，console 打印 [REPLAY] reached scene tutorial in Xs

# 三连无人值守（杀手组合）
uv run main.py launch --replay-scene tutorial --auto-play --auto-capture
# 期望：replay 完成 → 自动 capture → bot 接管 → 一直跑到 F9

# (2) VLMDriver C 层实机验收（接 a1f829f handoff，未变）
uv sync --extra auto-play-vlm
# 编辑 .env：填真 VLM_API_KEY；填完立刻 git update-index --skip-worktree .env
uv run main.py launch --auto-play --driver vlm --profile ff7r
# F8 → 30 min → F9
type %TEMP%\unicap\auto_play.log | findstr "VLM-COST" | wc -l
# 期望 ≥ 1500（30min × 60s × 1Hz × 0.85 success rate）
```

### 验收成功后 merge

```powershell
git checkout master
git merge --no-ff auto-play -m "merge: auto-play — A 层 + force_borderless + C 层 VLMDriver + replay-scene v1.0"
git push origin master
```

## Setup Required

无新设置。沿用上 session：
- VS 2022 + MSBuild v143（C++ 编译，本 session 没动 C++）
- `tools/capture/config.py` 的 `GAME_PATH` / `DATASET_ROOT`
- `uv sync --extra auto-play-vlm`（VLM 路径）

## Edge Cases & Error Handling

| 场景 | 行为 |
|------|------|
| `--record-scene foo` 但 `_scenes/foo/` 已有内容 | precheck `[错误] _scenes/foo/ 已存在内容，拒绝覆盖。先删它再录: rm -r ...`，**不**进游戏 launch |
| `--replay-scene foo` 但 scene 不存在 | precheck `[错误] replay scene 不存在: ...\n  缺少 script.jsonl 或 meta.json`，**不**进游戏 launch |
| `--record-scene ""` 或 `"   "` | `[错误] --record-scene 不能为空` |
| `--record-scene "../escape"` | `[错误] --record-scene 名字不能含 '..'（防路径穿越）` |
| `--record-scene "foo/bar"` | `[错误] --record-scene 名字含非法字符 ['/']` |
| sync 超时 30s | console 红字 paused，等用户 R 续 / Q 退（exit 2） |
| Ctrl+C in record/replay | 干净停（exit 130） |
| FPS 游戏锁鼠到中心 | mouse_move event 录到 `[center, center]` → 回放 SetCursorPos 等价 no-op；启动 / 菜单场景不受影响 |
| `--replay-scene` + 缺 survey | G-005 自动调 `survey_mod.run`；survey 失败 exit 3 |
| 录完 `_recording_frames/` | recorder.close() 强制 rmtree（避免 5GB 涨）|
| 回放 paused 态 | 仅响应 R / Q（不响应游戏内任何键） |
| F6/F7 在回放期间按下 | 不响应（设计如此 — 用户回放期不该重新录）|

### 上 session（仍生效）

详见 `a1f829f` 那版 handoff 的 Edge Cases 段。

## Warnings

### 本 session 新增

- **mouse-look 录制无效** — FPS 游戏锁鼠到屏幕中心，GetCursorPos 永远返中心。**仅菜单 / 导航场景适用**。文档已明记，scenarios S-001 ~ S-004 都是菜单 / 加载导向。如果 sponsor 想录战斗内 mouse look 操作 — v1.0 不行，得 v2.0 接 raw input 或 VLM 兜底。
- **`MANDATORY_RESERVED_KEYS` 扩容**（{F8,F9} → {F6,F7,F8,F9}）— 现有 4 profile 都已加，但**外部用户自管的 profile**（README 才发 1 周，应该极少）会因升级炸 load_profile。Sponsor 如果有外部 profile，记得给它的 reserved_keys 加 F6/F7。
- **录制 BMP 涨盘**：录制期间 addon 持续往 `_recording_frames/` 落 BMP（timestamp 命名不覆盖）；**30s 录制 ≈ 5GB**；recorder.close() 必 rmtree 清理。如果 Ctrl+C 异常退出且没走 finally 路径（极少），需手工 `rm -r _scenes/*/_recording_frames/`。
- **dHash 阈值 10 是默认**，per-sync 可在 `meta.json` 的 `syncs.<id>.hamming_threshold` 覆写；FF7R / DOOM 不同游戏可能需要不同阈值。第一次实机如果 sync miss 频繁，第一招就是放宽阈值（10→15→20）或拉长 timeout（30s→60s）。
- **emoji 在 cmd_scenes 输出会 crash GBK 终端**。本 session 已替换 ⚠ → `[!]`。新代码也别用 emoji 在 print() 里 — Win console encoding 问题反复出现。

### 上 session（仍生效）

详见 `7a7b886` / `f7b8054` / `a1f829f` 的 handoff Warnings 段（`SetWindowLongPtrW` c_ssize_t、`force_borderless` 不能同步阻塞、`settle_delay_s=2.0` 别砍、`[CAPTURE]` 14s 频率别动、`--force-borderless` 默认 True 别改、`--vlm-api-key` 留 shell history、`api_key` 不暴露 property、DeepSeek 无 vision、`.env` tracked 后填真 key 前必须 `git update-index --skip-worktree .env` 等）。
