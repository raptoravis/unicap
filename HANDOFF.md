# Handoff: 实机回归 OK + CLI 微调 + CLAUDE.md 6 处事实纠错

**Generated**: 2026-05-01 21:30
**Branch**: master（与 origin/master 同步；CLAUDE.md 6 处文档纠错未 commit）
**Status**: Done — 上份 handoff 列的 3 项实机回归全部通过；本会话又收 4 项小改 + 1 份文档纠错

## Goal

用户反馈实机回归通过后，做了 4 个小型 CLI 改动 + 1 个静默 + 1 份 CLAUDE.md 文档纠错：
1. `--ui-mode` 枚举 `ui-only` → `ui`（用户原话："唯一需要修改的就是把 --ui-mode 的 ui-only 修改为 ui"）
2. `pack` 加 `--depth/--no-depth`（缺省包含）
3. `pack` / `video` 位置参数 `game_dir` → `--game-dir DIR` flag
4. dxgi.dll 部署：symlink fail → copy 时静默（不再打印 `[警告]` 和 `[COPY]`）
5. CLAUDE.md 6 处事实纠错（基于 /init 自检发现）

## Completed

### CLI 改动（commit `334303d`）

- [x] `--ui-mode {no-ui,ui,both}`（5 处 `main.py` + 2 处 `CLAUDE.md` 替换）
- [x] `cmd_pack` 加 `--depth` BooleanOptionalAction（默认 True）→ 透传 `pack_hdf5.pack(include_depth=...)`
- [x] `pack_hdf5.pack` 签名加 `include_depth: bool = True`；关闭时 `mode='triplet'` 降级为 `'color'`，跳过 `/depth` `/normal` 数据集 + EXR 加载 + UI mask
- [x] `pack` / `video` 子命令位置参数 `game_dir` → `--game-dir DIR` flag（argparse `--game-dir` 自动转 `args.game_dir`，调用代码无需改）
- [x] docstring + 错误提示同步更新

### Symlink 静默（commit `bddd939`）

- [x] `_symlink_file` 砍掉 `[警告] 无法创建符号链接...` + `[COPY]` 两条 print；OSError 静默 fallback 到 `shutil.copy2`

### CLAUDE.md 文档纠错（**未 commit**）

- [x] Line 20: `dxgi.dll` "**not deployed**" → 实际由 `cmd_deploy` symlink 部署
- [x] Line 60: "packing + video generation run automatically" → 默认只 video；pack 改为 `launch --pack` opt-in 或事后 `pack` 子命令批量
- [x] Line 62: 1600×1200 → 1920×1080（带 commit b7021ed 引用）
- [x] Line 76: 加 `FC_BothCapture` 到 settings 列表
- [x] Runtime logs 节加 `unicap-*.{i,asm,cso}` shader cache 行 + "看到 reshade- 说明 dll 未更新"诊断提示
- [x] Dataset layout 加 `video_ui.mp4`（`--ui-mode both` 才生成）

### 上份 handoff 遗留的实机回归（用户口头确认全过）

- [x] `unicap-` 前缀实机验证（清旧 cache → launch → `%TEMP%\unicap\` 全 `unicap-*`）
- [x] video 快进修复实机验证
- [x] `--ui-mode ui-only` / `both` 实机验证 → 用户唯一反馈："`ui-only` 改成 `ui`"，已合入 commit 334303d

## Not Yet Done

- [ ] **CLAUDE.md 6 处纠错 commit + push**（`git diff --stat` 仅 `CLAUDE.md`，10 行净改动）
- [ ] 暂无其他遗留功能项

## Failed Approaches (Don't Repeat These)

1. **`rtk init -g` 想装 PreToolUse hook 实现自动 `rtk` 前缀 → Windows 上不支持**
   `rtk init --show` 显示 `[--] Hook: not found`，跑 `rtk init -g --auto-patch` 输出 `[warn] Hook-based mode requires Unix (macOS/Linux). Windows: use --claude-md mode for full injection.`。
   → 结论：Windows 上 RTK 永远是 CLAUDE.md 注入模式 + AI 手动加 `rtk` 前缀。每次 Bash 输出顶部的 `[rtk] /!\ No hook installed` 警告**在 Windows 上是永久误报**，忽略即可。
   → 备选 `snip`（Go 实现的 RTK clone）几乎肯定有同样的 Unix-only hook 限制。真要 Windows 自动 hook 就得自己写 PowerShell PreToolUse hook，ROI 不高。

2. **CLI 改造时漏改 `args.game_dir` 引用**
   把位置参数改成 `--game-dir` flag 时差点忘了：argparse **自动**把 `--game-dir` 转成 `args.game_dir`（dash → underscore），调用代码（`if not args.game_dir`、`Path(args.game_dir)`）保持不变即可。一开始想成需要改 6 处 `args.game_dir` 引用 → 实际只改 2 行 argparse 声明。
   → 教训：argparse dash-to-underscore 转换对位置参数和 flag 都生效，rename flag 不影响下游 attribute 名。

## Key Decisions

| Decision | Rationale |
|----------|-----------|
| `--depth/--no-depth` 关闭时连 `/normal` 一起跳 | 二者绑定在 EXR triplet 模式同一条加载路径；只跳 `/depth` 留 `/normal` 半边没意义。同时也跳 UI mask（mask 依赖 depth==0）。语义统一为"色彩-only HDF5"。 |
| `--no-depth` 不提供"加载 depth 但不写"的子模式 | YAGNI；若以后要"应用 mask 但不存 depth"再加 |
| `pack`/`video` 位置参数 → `--game-dir` flag | 用户截图明确要求 `--game-dir`；flag 形式更显式，避免后续追加更多 flag 时位置参数语义混乱 |
| symlink fallback 完全静默（不留 stderr/log 痕迹） | 用户原话"把这两个输出 suppress 掉"——直接删，不做 `--verbose` 等开关 |
| 两次 commit 拆分（HANDOFF doc + CLI 改进）| 上份 agent 留的 HANDOFF.md 是历史记录，CLI 改动是本会话产出，分开干净 |
| CLAUDE.md 纠错单独一次 commit | 文档纠错和功能改动语义不同，便于后续 cherry-pick / revert |

## Current State

**Working**:
- `uv run main.py launch --help` / `pack --help` / `video --help` 全 OK
- `uv run main.py pack --help` 显示 `[--game-dir DIR] [--depth | --no-depth]`
- `uv run main.py video --help` 显示 `[--game-dir DIR] [--fps FPS]`
- 所有 CLI / addon / dxgi.dll 改动已实机验证（用户口头确认）

**Uncommitted**:
- 仅 `CLAUDE.md`（6 处文档纠错，10 行净改动）

**Tree**: master 与 origin/master 同步；最近 8 commit：
```
bddd939 chore: suppress symlink fallback warning + COPY 提示
334303d feat: pack/video CLI 改进 — ui-mode 重命名 + --depth toggle + --game-dir flag
f89fe7e docs: handoff — main.py CLI 重构 + cache prefix reshade- → unicap-
09863dd chore: shader cache prefix reshade- → unicap-
b52ac6e update
7e7e7e7 feat: video/pack 批量子命令 + 耗时统计 + 自动 fps 估算
8e0d2c4 handoff: 收尾 — perf 完工 19.4 fps
b7021ed perf: 1920×1080 native + 2-worker pool → 19.4 fps capture
```

## Files to Know

| File | Why It Matters |
|------|----------------|
| `main.py` | 本会话主要改动文件：argparse 改 flag 形式 + `--depth` 透传 + `_symlink_file` 静默 |
| `tools/capture/pack_hdf5.py` | `pack(include_depth: bool = True)` 新参数；`mode='triplet'` 降级逻辑在函数顶部 |
| `CLAUDE.md` | 已纠 6 处事实失准；diff 未 commit |

## Code Context

### `pack_hdf5.pack` 新签名

```python
def pack(frames_dir: Path, inputs_path: Path, output_path: Path, include_depth: bool = True):
    ...
    mode, frames = scan_frames(frames_dir)
    ...
    if not include_depth and mode == 'triplet':
        print("[SCAN] --no-depth: 跳过 /depth /normal 数据集与 UI mask")
        mode = 'color'
        for f in frames:
            f['depth'] = None
            f['normal'] = None
    ...
```
关键：把 `mode` 强行降到 `'color'` + 清空 frame['depth'/'normal']，下游 `if mode == 'triplet'` 分支自然全跳过，无需散点 if。

### CLI 形态（最新）

```
uv run main.py launch [--ui-mode {no-ui,ui,both}] [--no-video] [--pack]
uv run main.py video  --game-dir DIR [--fps N]              # 0 = auto
uv run main.py pack   --game-dir DIR [--no-depth]
```

### `_symlink_file` 现状

```python
def _symlink_file(src: Path, dst: Path):
    if dst.is_symlink() or dst.exists():
        dst.unlink()
    try:
        os.symlink(str(src), str(dst))
    except OSError:
        shutil.copy2(src, dst)
```
完全无输出。诊断 dxgi.dll 是否为 symlink 用 PowerShell：
```powershell
(Get-Item "<game>\dxgi.dll").LinkType   # 'SymbolicLink' 或 $null（fallback 到 copy）
```

## Resume Instructions

### 1. 把 CLAUDE.md 纠错 commit + push（30 秒）

```bash
git add CLAUDE.md
git commit -m "docs: CLAUDE.md 6 处事实纠错 — dxgi 部署 / pack 默认 / 分辨率 / FC_BothCapture / unicap- cache / video_ui"
rtk git push
```
预期：成功推到 origin/master，工作树 clean。

### 2. 后续若遇 RTK 警告

每次 Bash 输出顶部的 `[rtk] /!\ No hook installed — run 'rtk init -g'` 在 Windows 上**永远会出现**。
- 不要再 `rtk init -g`，已经是 CLAUDE.md 注入模式的 up-to-date 状态
- 不要相信 `rtk init --show` 里的 `[warn] Global (~/.claude/CLAUDE.md): old RTK block` —— 实际状态是最新（同一次输出还说了 `already contains up-to-date rtk instructions`）

### 3. 若需要再调 ui-mode 行为

`main.py:_ensure_addon_enabled` 是单点开关：
```python
pre_ui_flag  = "0" if ui_mode == "ui" else "1"   # ← 若改 enum 值，先改这里
both_flag    = "1" if ui_mode == "both" else "0"
```
另外 `cmd_launch` 提示框（~L284）+ `_interactive_loop` survey 判断（~L306）也都靠字符串比对。grep `"ui"` 或 `"both"` 找全。

## Warnings

- **CLAUDE.md 还没 commit** —— `git status` 唯一 dirty 项就是这个。下次 agent 第一件事：confirm + commit + push。
- **`--depth/--no-depth` 仅 `pack` 子命令上有**；`launch --pack` 走默认 `True`，即"含 depth"。若用户想 launch 时也能选，得给 `cmd_launch` 的 argparse 也加 `--depth`，并把 `args.depth` 透到 `_run_capture` 内部那次 `pack_hdf5.pack(...)` 调用。**目前未做** —— 用户未要求。
- **承袭上份 handoff 所有 warnings**：`reshade/source/` 改了必须 `-Rebuild`；旧 `reshade-*.{i,asm,cso}` cache 不会自动清；`_RE_BMP_TS` 与 addon BMP 命名强耦合（改 addon 命名格式时 fps 估算会静默回退到 30）；R10G10B10A2 swap chain 错色；`NUM_WORKERS=2` constexpr。
- **RTK Windows 警告**永远在，别浪费时间想"修"它。

## Setup Required

无新增。沿用：VS 2022 + MSBuild v143、`uv sync`、`tools/capture/config.py` 的 `GAME_PATH`/`DATASET_ROOT`、日志在 `%TEMP%\unicap\unicap.log{,1}`。
