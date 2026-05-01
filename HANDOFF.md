# Handoff: main.py CLI 重构 + video 快进修复 + cache 文件名 reshade- → unicap-

**Generated**: 2026-05-01 19:35
**Branch**: master（与 origin/master 同步，clean）
**Status**: Done（代码已 commit + push）；下面 3 项实机回归仍待用户跑

## Goal

本会话两块工作：
1. **`main.py` CLI 优化**：survey/capture/pack 加耗时统计；launch 默认不 pack；pack 与 video 子命令重构成"扫整个游戏目录、缺啥补啥、已存在跳过"的批量模式；修复 video 播放快进（按固定 30 fps 编码导致 19/12 fps 采集被压缩 1.5×~2.5×）。
2. **shader cache 文件名前缀 `reshade-` → `unicap-`**（`%TEMP%\unicap\` 下的 `.i` / `.asm` / `.cso` 文件），与项目命名一致。

## Completed

### main.py CLI（commit `7e7e7e7`）

- [x] `_fmt_dur(seconds)` helper（≥60s 输出 `m分s秒`）
- [x] `_run_survey` / `_run_capture` 三段耗时（CAPTURE / VIDEO / PACK 分开）
- [x] launch 加 `--video / --no-video`（默认 True）+ `--pack`（默认 False）两个 toggle
- [x] `cmd_pack` 重构：位置参数 `game_dir`，扫描 `<game_dir>/<ts>/frames/` 缺 `dataset.h5` 则补、已存在跳过、缺 inputs 计 failed、末尾汇总 `打包/跳过/失败` + 总耗时
- [x] `cmd_video` 同架构重构（含 `*BackBufferUI.bmp` 二级流）
- [x] **`_make_video` 默认从文件名时间戳估算 fps**（`fps=0` 触发自动）：regex `_RE_BMP_TS = r' (\d{4}-\d{2}-\d{2}) (\d{2}-\d{2}-\d{2}) (\d+) '`；`(n-1) * 1000 / (last_ms - first_ms)`；估算失败回退 `CAP_FPS=30`。`cmd_video --fps` 默认 0 = auto

### reshade core（commit `09863dd`）

- [x] `reshade/source/runtime.cpp` 三处替换 `"reshade-"` → `"unicap-"`（line 3540, 3561, 3583）；`compare(0, 8, ...)` 长度 8→7
- [x] `scripts\build.ps1 -Rebuild` 全量重建 → `dist\dxgi.dll` (5.5 MB) + `dist\frame_capture.addon` (206 KB)，timestamp 19:31

## Not Yet Done

- [ ] **重生成那段被快进的 video 实机回放确认正常速率**（`D:\unicap_output\ff7remake_\20260501_161710\` 在测试中已被删，原始 BMP 不可用 → 录新一段做回归）
- [ ] **`unicap-` 前缀实机验证**：当前游戏没重启，`%TEMP%\unicap\` 仍是 `reshade-*.{i,asm,cso}` 旧文件
- [ ] **`--ui-mode ui-only` / `both` 实机验证**（自上份 handoff 起就遗留，本会话未动）

## Failed Approaches (Don't Repeat These)

1. **改源码后忘了重建 dxgi.dll**
   首轮直接编辑 `runtime.cpp` 后告诉用户"清缓存重启游戏" → 用户截图回复"还是老样子"。原因：`reshade_core` 是 ExternalProject + stamp file，`build.ps1` 不带 `-Rebuild` 会跳过 reshade，dxgi.dll 没更新。
   → 教训：动 `reshade/source/` 后必须 `-Rebuild`。CMakeLists.txt 有 `-DRESHADE_ALWAYS_REBUILD=ON` 选项可以让它每次都跑（但默认关，因为完整 MSBuild ~30s）。

2. **初版 launch 直接砍掉 pack，没留 opt-in flag**
   `8e0d2c4 → 7e7e7e7` 的早期 commit 草稿里，launch 默认不 pack 且没有 `--pack` flag。用户问"如果要直接打包怎么办" → 加了 `--pack`。video 同款重构时吸取教训，一开始就给了 `--video / --no-video`。
   → 教训：删默认行为时随手加一个"恢复旧行为"的 flag。

3. **`fps` 改 float 后 `(i + 1) % fps` 没改**
   原版 `fps: int`，进度打印 `if (i + 1) % fps == 0`。auto fps 后 fps 是 12.187，`% 12.187 == 0` 永远不真 + 边界会除零。
   → 改用：`progress_step = max(int(round(fps)), 1)` 在循环外算一次。
   → 教训：放宽字段类型时（int → float）grep 调用点找 `%` / `//` / `range()` / 索引等隐式 int-only 运算。

4. **ffmpeg `-r` 直接 `str(fps)` for float**
   `str(12.187)` 理论可用但精度依赖 locale。换成 `f"{fps:.6f}"` 强制点号小数 6 位。

5. **测 `_estimate_fps` 直接 `python -c ...`**
   报 `ModuleNotFoundError: cv2`（main.py 顶层 import → pack_hdf5 → cv2）。
   → 改用：`uv run python -c ...` 走项目环境。

## Key Decisions

| Decision | Rationale |
|----------|-----------|
| `_make_video(fps=0)` 触发自动估算 | 老调用都需要修；统一让"传 0 等于自动"，零侵入 |
| `cmd_video --fps` 默认 0（auto），用户显式覆盖才用具体值 | 修复快进 + 保留"我就要锁定 30 fps"逃生通道 |
| `--pack` opt-in，`--video` opt-out | pack 耗时显著 > video；匹配各自常见用法 |
| video / pack 子命令丢掉旧 `--frames-dir` / `--inputs` / `--output` | 用户原话"像 pack 那样对游戏的输出目录检查"，单一位置参数最少噪音 |
| 自动 fps 失败回退 `CAP_FPS=30` 而非报错 | 单帧 / 文件名异常 session 也能出片，不卡批量流程 |
| Cache prefix 改 7 字符 `unicap-` 而非保留 8 字符比如 `unicap--` | 自然命名 > 字节对齐；`compare(0, 7, ...)` 一并改了 |
| 旧 `reshade-` cache 文件**不**做向下兼容自动清理 | 一次性手工清理代价低，不值得改源码维护双 prefix 规则 |

## Current State

**Working**:
- `main.py` 所有子命令 `--help` 正常；`python -c "import ast; ast.parse(...)"` 通过
- `_estimate_fps` 实测 125 帧 session = 12.187 fps（手算 124 / 10.175 = 12.187 ✓）
- `dist\dxgi.dll` 已包含 `unicap-` prefix 改动（19:31 timestamp）

**Pending verification**:
- 实跑 `uv run main.py video <game_dir>` 重生成被快进的 video（原 session 已删，需录新片回归）
- 实跑 launch 看 `%TEMP%\unicap\` 是 `unicap-*.{i,asm,cso}`
- ui-only / both 模式（上份 handoff 起遗留）

**Tree state**: clean，与 origin/master 同步。最近 5 commit：
```
09863dd chore: shader cache prefix reshade- → unicap-
b52ac6e update                                            ← 用户自己提的（非本 AI 会话）
7e7e7e7 feat: video/pack 批量子命令 + 耗时统计 + 自动 fps 估算
8e0d2c4 handoff: 收尾 — perf 完工 19.4 fps，...
b7021ed perf: 1920×1080 native + 2-worker pool → 19.4 fps capture
```

## Files to Know

| File | Why It Matters |
|------|----------------|
| `main.py` | 本会话主要改动；新增 `_fmt_dur` (~L60)、`_RE_BMP_TS / _bmp_ts_ms / _estimate_fps` (~L451-475)；`_make_video` 签名改 `fps: float = 0`；`cmd_pack` / `cmd_video` 全部重写；CLI 子命令改位置参数 |
| `reshade/source/runtime.cpp` | 三处 `"reshade-" → "unicap-"`（L3540, L3561, L3583）+ `compare(0, 8, ...)` → `compare(0, 7, ...)` |
| `tools/capture/pack_hdf5.py` | `scan_frames` 文件名 regex 是 main.py `_RE_BMP_TS` 的参考来源（pack_hdf5 用 ns 精度，main.py 简化为 ms） |
| `CMakeLists.txt` | `reshade_core` 是 ExternalProject + stamp，必须 `build.ps1 -Rebuild` 才会重跑 MSBuild |

## Code Context

### main.py 新增 fps 估算

```python
_RE_BMP_TS = re.compile(r' (\d{4}-\d{2}-\d{2}) (\d{2}-\d{2}-\d{2}) (\d+) ')

def _bmp_ts_ms(p: Path) -> int | None:
    # 文件名：<prefix> 2026-05-01 16-17-10 325 BackBuffer.bmp
    # 端到端只用差值，本地 / UTC 都行

def _estimate_fps(bmps: list[Path]) -> float | None:
    # (n-1) * 1000 / (last_ms - first_ms)；<2 帧或解析失败返 None

def _make_video(frames_dir, output, fps: float = 0, glob_pat="*BackBuffer.bmp"):
    if fps <= 0:
        est = _estimate_fps(bmps)
        fps = est if est else CAP_FPS
    progress_step = max(int(round(fps)), 1)   # ← 不能用 % fps，fps 是 float
    # ffmpeg ... "-r", f"{fps:.6f}"           ← 不要 str(fps)
```

### CLI 形态

```
uv run main.py launch [--no-video] [--pack]
uv run main.py video <GAME_DIR> [--fps N]   # 0 = auto
uv run main.py pack  <GAME_DIR>
```

### reshade prefix 改动

```cpp
// runtime.cpp L3540 / L3561 (read & write paths)
path /= std::filesystem::u8path("unicap-" + id + '.' + type);

// runtime.cpp L3583 (clear_effect_cache)
if (filename.wstring().compare(0, 7, L"unicap-") != 0 || ...)
```

## Resume Instructions

### 1. 实机验证 unicap- prefix（≤2 分钟）

```powershell
# 退出当前游戏（dxgi.dll 是 symlink；游戏运行时锁着旧 DLL）
# 然后：
Remove-Item "$env:TEMP\unicap\reshade-*","$env:TEMP\unicap\unicap.log*"
uv run main.py launch
# 启动后随便走两步触发 shader 编译
# 退游戏后看：
ls "$env:TEMP\unicap\"
```

期望：`unicap-CaptureStatus-*.{i,asm,cso}`、`unicap-DepthToAddon-*.{i,asm,cso}`、`unicap-UIRemove-*.{i,asm,cso}` —— 没有任何 `reshade-` 前缀。

如果还看到 `reshade-` 前缀：
- 检查 `dist\dxgi.dll` 修改时间是否为 19:31 之后（旧 dll 没替换）
- 检查游戏目录 `dxgi.dll` 是 symlink 指向 `dist\dxgi.dll`（不是 copy）：`(Get-Item "<game>\dxgi.dll").LinkType` 应为 `SymbolicLink`

### 2. 实机验证 video 快进修复（≥10 秒采集 1 段）

```powershell
uv run main.py launch
# 游戏内：F8 → 等 ~15 秒 → F9
# 等待 [VIDEO] 自动 fps=XX.YY（XXX 帧 / 文件名时间戳） 输出
# 然后回放生成的 video.mp4，秒表对一下与采集时长是否一致
```

期望：
- 控制台打印 `[VIDEO] 自动 fps=...` 行
- video.mp4 时长 ≈ 采集时长（不再快进）

如果仍快进：检查 `_estimate_fps` 输出。可能 BMP 文件名 regex 失配（addon 命名格式变了？）。

### 3. ui-only / both 实机（上份 handoff 遗留）

```powershell
uv run main.py launch --ui-mode ui-only   # F8 直接采，BMP 应带 UI
uv run main.py launch --ui-mode both      # F6 → F8 双流（video.mp4 + video_ui.mp4）
```

## Warnings

- **改 `reshade/source/` 必须 `-Rebuild`**。stamp file 让普通 build 跳过。本会话因此返工一次。
- **旧 `reshade-*.{i,asm,cso}` 不会被新 cleanup 自动清**（filter 只匹配 `unicap-`）。手动 `Remove-Item` 一次即可。
- **`_RE_BMP_TS` 和 addon BMP 命名强耦合**：`<prefix> YYYY-MM-DD HH-MM-SS <ms> BackBuffer.bmp`。改 addon 命名格式时 regex 静默失效 → fps 回退 30 → 又快进。命名定义在 `frame_capture.cpp` 的 BMP 写盘路径。
- **video / pack 已存在则跳过**按文件名判断；损坏的 video.mp4 也算"已存在"。重生成需手动 `rm` 旧文件。考虑过加 `--force` 但 YAGNI。
- **fps 估算只看首末两帧**：中间长暂停会让估值偏低。capture 不会主动暂停，但理论存在。
- **承袭上份 handoff 所有 warning**：`safe_last_rt` 守门、`fc_pass_total.txt` 写出顺序、`reshade-addons/deps/reshade/include` v5 wrapper、R10G10B10A2 swap chain 错色、`NUM_WORKERS=2` constexpr。

## Setup Required

无新增。沿用：VS 2022 + MSBuild v143、`uv sync`、`tools/capture/config.py` 的 `DATASET_ROOT`、日志在 `%TEMP%\unicap\unicap.log{,1}`。
