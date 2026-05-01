# Handoff: video/pack 批量子命令 + 耗时统计 + 修复 video 快进 bug

**Generated**: 2026-05-01 18:00
**Branch**: master（与 origin/master 同步，clean）
**Status**: Done（代码已 commit + push）；实机回归（重生成那段被快进的 video）+ 上一份 handoff 遗留的 ui-only / both 实机验证仍未做

## Goal

让 `main.py` 在 launch / video / pack 三条路径上行为更可控：
- 每个阶段（survey、capture、video、pack）都打印耗时
- launch 默认不 pack（pack 太耗时），可选 `--pack` 即时打包
- launch 默认仍生成 video，可选 `--no-video` 跳过
- `video` / `pack` 子命令重构成批量扫描模式：传游戏目录，对其下所有 session 缺啥补啥、已存在跳过
- 修复用户反馈的"video 快进"bug

## Completed

- [x] **耗时统计**：`_fmt_dur(seconds)` helper（≥60s 显示 `m分s秒`），包到 `_run_survey` / `_run_capture` / `_make_video` 内层 + `cmd_pack` / `cmd_video` 整体三层
- [x] **launch `--pack` opt-in flag**（默认不 pack）：F9 停止 → 视频 → 提示 "运行 `uv run main.py pack \"<dataset_root>/<game>\"`"
- [x] **launch `--video / --no-video` toggle**（`BooleanOptionalAction`，默认 True）
- [x] **`pack` 重构**：位置参数 `game_dir`；扫描 `<game_dir>/<ts>/frames/`；缺 `dataset.h5` 则打包，已存在跳过；缺 `inputs.jsonl` 计入 failed；末尾汇总 `打包/跳过/失败` + 总耗时
- [x] **`video` 重构**：同 pack 架构，扫描 `video.mp4`（`*BackBuffer.bmp`）+ `video_ui.mp4`（仅当存在 `*BackBufferUI.bmp` 时）
- [x] **修复 video 快进** —— `_make_video` 默认从 BMP 文件名 `YYYY-MM-DD HH-MM-SS <ms>` 时间戳估算实际 fps；`fps=0` 触发自动；估算失败回退 `CAP_FPS=30`。验证：`20260501_161710` 那段 125 帧 / 10.18 s = 12.19 fps（旧版按 30 fps 编 → 播放快进 ~2.5×，与现象一致）
- [x] commit `7e7e7e7` + pushed to origin/master

## Not Yet Done

- [ ] **重生成那段快进 video 并实机回放确认正常速率**（用户反馈来源 `D:\unicap_output\ff7remake_\20260501_161710\video.mp4`）。代码已修，但 `video` 子命令"已存在则跳过"——需要先 `rm video.mp4` 再跑，或用户已自己处理
- [ ] **`--ui-mode ui-only` 实机验证**（上一份 handoff 遗留）
- [ ] **`--ui-mode both` 实机验证**（上一份 handoff 遗留；双流 BMP + `video_ui.mp4` + `/color_ui`）

## Failed Approaches (Don't Repeat These)

1. **初版 launch 直接砍掉 pack 没留 opt-in flag**
   首轮提交后用户问"如果要直接打包怎么办？" → 加了 `--pack`。video 重构时吸取教训，一开始就给了 `--video / --no-video`。
   → 教训：删默认行为时随手加一个"恢复旧行为"的 flag，避免来回往返。

2. **`fps` 改 float 后 `(i + 1) % fps` 没改**
   旧版 `fps: int`，进度打印 `if (i + 1) % fps == 0`。auto fps 后 fps 是 12.187，`%` 运算行为奇怪（且 `% 0` 会崩）。
   → 改用：`progress_step = max(int(round(fps)), 1)` 在循环外算一次。
   → 教训：把字段类型从 int 放宽到 float 时，要 grep 调用点找模数 / 整除 / 索引等隐式 int-only 的运算。

3. **ffmpeg `-r` 直接传 `str(fps)` for float**
   `str(12.187)` → `"12.187"`，理论上 ffmpeg 接受但精度依赖 locale 字符串解析。
   → 改用：`f"{fps:.6f}"` 强制点号小数 6 位。

4. **打开 cv2 测试 `_estimate_fps` 直接 `python -c ...`**
   报 `ModuleNotFoundError: cv2`（main.py 顶层 import 链路里有 pack_hdf5 → cv2）。
   → 改用：`uv run python -c ...` 走项目环境。

## Key Decisions

| Decision | Rationale |
|----------|-----------|
| `_make_video` 默认 `fps=0` 触发自动估算 | 老调用都需要修 → 统一让"传 0 等于自动"，向后兼容、零侵入 |
| `cmd_video` `--fps` 默认 0（自动），用户显式覆盖才用 int/float 值 | 修复快进的同时保留"我就要锁定 30 fps"的逃生通道 |
| `--pack` opt-in 而非 opt-out；`--video` opt-out（默认开） | pack 耗时 vs video 较快，匹配各自常见用法 |
| video / pack 子命令丢掉旧 `--frames-dir` / `--inputs` / `--output` 三联参数 | 用户原话"像 pack 那样对游戏的输出目录检查"，单一位置参数最少噪音；老用法没人用 |
| 自动 fps 失败时回退 `CAP_FPS=30` 而非报错 | 单帧 / 文件名异常 session 也能出片，不卡批量流程 |

## Current State

**Working**:
- `python -c "import ast; ast.parse(open('main.py').read())"` 通过
- `uv run main.py launch --help` / `pack --help` / `video --help` 正常
- `_estimate_fps` 实测于 125 帧 session：12.187 fps（手算 124 / 10.175 = 12.187 ✓）

**Pending verification**:
- 实跑 `uv run main.py video "<game_dir>"` 重生成快进 video（session 目录在测试中被删，没机会跑端到端）
- ui-only / both 模式（自上一份 handoff 起就没实机过）

**Tree state**: clean，与 origin/master 同步在 `7e7e7e7`。

## Files to Know

| File | Why It Matters |
|------|----------------|
| `main.py` | 本会话唯一改动；新增 `_fmt_dur`（~line 60）、`_RE_BMP_TS` + `_bmp_ts_ms` + `_estimate_fps`（~line 451-475）；`_make_video` 签名变 `fps: float = 0`；`cmd_pack` / `cmd_video` 全部重写 |
| `tools/capture/pack_hdf5.py` | `scan_frames` 的文件名 regex 是我抄过来的参考——main.py 里是简化版（只取 ms-精度，pack_hdf5 用 ns） |

## Code Context

**新增 fps 估算（main.py）**：
```python
_RE_BMP_TS = re.compile(r' (\d{4}-\d{2}-\d{2}) (\d{2}-\d{2}-\d{2}) (\d+) ')

def _bmp_ts_ms(p: Path) -> int | None:
    # 文件名格式：<prefix> 2026-05-01 16-17-10 325 BackBuffer.bmp
    # 注意时区：本地（UTC+8），但端到端只算差值，时区无所谓

def _estimate_fps(bmps: list[Path]) -> float | None:
    # (n-1) * 1000 / (last_ms - first_ms)，<2 帧或解析失败返 None
```

**`_make_video` 入口（默认自动）**：
```python
def _make_video(frames_dir, output, fps: float = 0, glob_pat="*BackBuffer.bmp"):
    if fps <= 0:
        est = _estimate_fps(bmps)
        fps = est if est else CAP_FPS
    progress_step = max(int(round(fps)), 1)   # ← 不能用 % fps，fps 是 float
    # ffmpeg ... "-r", f"{fps:.6f}"  ← 不要 str(fps)
```

**新 CLI 形态**：
```
uv run main.py launch [--no-video] [--pack]
uv run main.py video <GAME_DIR> [--fps N]   # 0=auto
uv run main.py pack  <GAME_DIR>
```

## Resume Instructions

### 1. 验证快进修复（5 分钟，需要那段被快进的 session 还在）

```powershell
# 假设 D:\unicap_output\ff7remake_\<ts>\video.mp4 是被快进的
Remove-Item "D:\unicap_output\ff7remake_\<ts>\video.mp4"
uv run main.py video "D:\unicap_output\ff7remake_"
```

期望：
- 控制台打印 `[VIDEO] 自动 fps=12.19（125 帧 / 文件名时间戳）`
- 新 `video.mp4` 时长 ≈ 10.2 秒（旧版是 ~4 秒所以快进感）
- 视频里 1 秒钟里发生的事情和你按 F8 时游戏中 1 秒钟一致

如果没有那段 session 了：F8 录一段 ≥10 秒新的 → F9 → 看 `[VIDEO] 自动 fps=...` 输出和回放速率。

### 2. ui-only / both 模式实机（上一份 handoff 留的）

```powershell
Remove-Item "$env:TEMP\unicap\unicap.log*"
uv run main.py launch --ui-mode ui-only
# 期望：F8 直接进 capture（无 survey），BMP 带 UI

uv run main.py launch --ui-mode both
# 期望：F6 survey OK；F8 后每 ts 两份 BMP（BackBuffer / BackBufferUI）；
# F9 自动出 video.mp4 + video_ui.mp4
```

## Warnings

- **`video` / `pack` 子命令"已存在则跳过"是按文件名判断的**。video.mp4 损坏 / 错误编码 也会被认作"已存在"。需要重生成时手动 `rm` 旧文件。考虑过加 `--force` 但 YAGNI 没加。
- **fps 估算只看首末两个时间戳**。如果 session 中间有"暂停几秒再继续"（capture 不会暂停，但理论上），估算会偏低。代价：偏低的 fps 让回放变慢，仍可看；只在 session ≥2 帧、首末时间戳能解析时生效。
- **`_RE_BMP_TS` 是空格分隔的**：`r' (\d{4}-\d{2}-\d{2}) (\d{2}-\d{2}-\d{2}) (\d+) '`。如果将来改了 BMP 命名格式（去掉空格 / 换分隔符），这个 regex 静默失效 → fps 回退 30 → 又会快进。文件名格式定义在 addon `frame_capture.cpp` 里 `BackBuffer.bmp` 那条。
- **`progress_step = max(int(round(fps)), 1)`**：fps 极低（<0.5）也不会除零。
- **承袭上一份 handoff 的所有 warning**：`safe_last_rt` 守门、`fc_pass_total.txt` 写出顺序、`reshade-addons/deps/reshade/include` v5 wrapper、R10G10B10A2 swap chain 错色、`NUM_WORKERS=2` constexpr。

## Setup Required

无新增。继续沿用上份 handoff 的：VS 2022、`uv sync`、`tools/capture/config.py` 里的 `DATASET_ROOT`、日志在 `%TEMP%\unicap\unicap.log{,1}`。
