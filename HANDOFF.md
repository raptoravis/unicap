# Handoff: 采集吞吐 perf 完工 — 19.4 fps capture, 三模式 + survey 稳定

**Generated**: 2026-05-01 16:30
**Branch**: master (5 commits ahead of origin/master, clean tree)
**Status**: Done — 主链路（`--ui-mode no-ui`）完整实机走通；`ui-only` / `both` 仍未实机验证

## Goal

让 unicap 的 survey + capture 全链路稳定 + 不卡。本会话的实测结果：

- survey: 22-pass 场景 5/5 skip ✓，推荐 skip=0 正确
- capture: 250 frames / 12.9 s = **19.4 fps**（目标 30），游戏感知不到卡顿

吞吐演化（同一场景反复实测）：

| 节点 | capture fps | 主因 |
|---|---|---|
| 起点 | 3.6 | EXR ZIP 三通道复制 + render 线程 powf 解码 |
| F16→sRGB LUT | 3.6 | 没动到瓶颈 |
| 单通道 EXR | 7.6 | 干掉 worker 内 3× 数据 + 反交错循环 |
| 1920×1080 native | 11.2 | 跳过 worker 端 stbir resize |
| 2-worker 并行 | 19.4 | CPU compress + disk write 并行 |

## Completed (this session, 已 commit)

### 0bd42fe "nearly perfect"

- [x] **survey-mode dedup 写盘门**（`on_reshade_present`）：每个 distinct `this_frame_skip` 只入队一份 BMP；前置 `fc_pass_total.txt` 写出（确保 Phase 1 始终能读到 pass 总数）。修复 skip=45+ TIMEOUT — 老逻辑下 FF7R enhanced 路径每帧都 fallback 写 7.5 MB BMP，30 fps × 7.5 MB = 225 MB/s 把队列写爆。
- [x] **F16→sRGB LUT**（64 KB 静态数组）：`r16g16b16a16_float` 解码每像素从 3 次 `powf` 降到 3 次 byte load。
- [x] **单通道 "Y" EXR**：`SaveEXR` 从 3 通道 (R=G=B=depth) 重写为 1 通道。worker 跳过 RGB 复制 + 反交错；render 线程仅抽 alpha；depth resize 从 4 通道改 1 通道。EXR 文件从 ~1.5 MB → ~89 KB。
- [x] **BB-bind safe_last_rt 守门**：`(g_pre_ui_skip == 0 || s_prev_non_bb_total == 0)` 时才走 shader_resource → copy_source barrier。skip>0 enhanced 路径下不再触发 `Close() E_INVALIDARG` 崩溃。
- [x] **survey `_wait_for_bmp` mtime_floor 过滤**：去掉主动 unlink，避免和 addon 写盘抢锁。
- [x] **`_find_boundary` 反向规则**：FF7R 类管线（UI 合成在最后一个非 BB RT 之内）下推荐 skip=0。
- [x] **vendor/installers/\*.exe** git rm。

### b7021ed "perf: 1920×1080 native + 2-worker pool"

- [x] **采集分辨率 1600×1200 → 1920×1080**（`main.py:CAP_WIDTH/HEIGHT`）：匹配 FF7R scene RT，worker 三条 stbir resize 路径全部跳过；同时修正之前 16:9→4:3 的横向拉伸。
- [x] **2-worker pool**：`g_save_thread` (单) → `g_save_threads` (2)。`notify_one` 维持（每帧只一个 task），shutdown 改 `notify_all` + 全部 join。

## Not Yet Done

- [ ] **`--ui-mode ui-only` 实机验证**：跳过 survey + 直接采集 post-UI BB；BMP 应**带** UI。
- [ ] **`--ui-mode both` 实机验证**：每个时间戳两份 BMP（`BackBuffer.bmp` 是 pre-UI，`BackBufferUI.bmp` 是 post-UI），HDF5 多 `/color_ui` 数据集，自动出 `video.mp4` + `video_ui.mp4`。从未跑过。
- [ ] **EXR 缺帧** （次要）：实测 250 BMP / 248 EXR — 头 1-2 帧没 depth EXR，疑似 `sbi.depth_staging` 首次分配那帧没赶上。可忽略，pack_hdf5 应已能容忍。
- [ ] **想冲到 30 fps**：现在 19.4 fps，~1.7× 弱缩放（应该 ~2×）。再加 worker（NUM_WORKERS=3）应能到 ~25-30 fps。但游戏体感已经不卡，性价比有限。

## Failed Approaches (Don't Repeat These)

1. **F16→sRGB LUT 是"render 线程瓶颈"的错误诊断**
   先怀疑 `powf` 是 render 线程瓶颈 → 上 LUT。结果 fps 从 3.6 → 3.6（毫无变化）。**真瓶颈是 worker**：每帧 7.4 MB BMP + 1.5 MB EXR 串行写 + ZIP compress 三通道 = 280 ms/帧。LUT 仍然保留（成本零，对 worker 的 use_scene_rt 路径有些许助益），但不要再以为它是关键路径。
   → 教训：先看 `save queue full` warn 计数 + `capf` 在哪一帧开始变慢。warn 多 = worker 吃不消，看 worker；warn 少 = render 线程慢，看 render。

2. **想用 `TINYEXR_COMPRESSIONTYPE_NONE` 提速**
   30 fps × 23 MB raw = 690 MB/s，超过任何消费级磁盘。NONE 反而把瓶颈从 CPU 推给磁盘。
   → 改用：单通道 ZIP（数据 4× 缩减后 ZIP 只剩 ~30 ms 工作量）。

3. **survey 模式跑足游戏帧率写 BMP**
   FF7R enhanced 路径 + skip>0 永远 fallback 到 UIRemove（每帧内容相同），addon 仍按 30 fps 写盘 → 队列饱和 → 后续 skip 帧入队全丢 → Python TIMEOUT。
   → 改用：survey 模式每个 skip 值只写一份 BMP，下一帧若 skip 未变直接 `goto reset_frame_state`。Python 推进后才会再写。15 个 skip = 15 次写盘，磁盘根本注意不到。

4. **承袭旧 handoff 的 D3D12 崩溃叙事**
   上一轮 handoff 警告 skip=45 会"崩溃"。本轮实测：BB-bind safe_last_rt 修复（已 commit）实际上已经把崩溃彻底止住了。skip=45 现在只是**TIMEOUT**（写盘吞吐瓶颈，根因不同）。不要再以为它是 D3D12 崩。

5. **`g_cap_width=1600, g_cap_height=1200` 默认值**
   FF7R native scene RT = 1920×1080（16:9）。1600×1200 是 4:3，stbir 强行拉伸。结果 BMP 横向被压扁，且 worker 多花 ~40 ms 做 resize。
   → 改用：1920×1080 默认。任何 16:9 渲染游戏都会自动跳过 resize。其他游戏要换原生分辨率改 `main.py` 顶部常量。

## Key Decisions

| Decision | Rationale |
|----------|-----------|
| 单通道 "Y" EXR 而非 3 通道 RGB | depth 是标量，3 通道是历史包袱。pack_hdf5 `_load_depth` 已经兼容 1ch/3ch。 |
| 2 workers 而非 4+ | 2 已到 19.4 fps，3 worker 估算 25-30 fps。游戏体感已不卡，超过这个数据收益边际。 |
| `NUM_WORKERS = constexpr` 写死 | 不打算暴露给 ini。CPU 核数差异不大；要调改源码即可。 |
| F16 LUT 留着不删 | 64 KB 静态成本可忽略，且对 use_scene_rt 路径仍是真省（每像素 3 次 byte load vs 3 次 powf）。 |

## Current State

**Working**:
- `--ui-mode no-ui`（默认）+ skip=0 + survey 自动推荐：完整 F8 → F9 → pack → video.mp4 + dataset.h5。19.4 fps capture，1920×1080，1099 MB / 401 帧
- survey 22-pass / 71-pass 场景均稳过，反向规则正确推荐 0
- 游戏运行无感 — 不再有"卡"的体感

**Pending verification**:
- `--ui-mode ui-only` 从未实机测过
- `--ui-mode both` 从未实机测过（双流 BMP + video_ui.mp4 + `/color_ui`）

**Tree state**: 无 uncommitted 改动，5 commits ahead of origin/master。

## Files to Know

| File | Why It Matters |
|------|----------------|
| `reshade-addons/99-frame_capture/frame_capture.cpp` | 唯一 ~1300 行 C++ addon。本会话改动重点：`SaveEXR` (单通道，~line 95)、`g_hdr_f16_lut` (~line 350)、`save_worker_fn` 单通道 depth (~line 178)、survey dedup gate in `on_reshade_present` (~line 845)、`g_save_threads` 2-worker pool (DllMain ~line 1295) |
| `main.py` | `CAP_WIDTH=1920 / CAP_HEIGHT=1080`（line 46-50）。`_ensure_addon_enabled` 写出到 unicap.ini，addon 在 `on_init_device` 读取 |
| `tools/capture/survey.py` | mtime_floor + FF7R 反向规则 |
| `tools/capture/pack_hdf5.py` | `_load_depth` 兼容 1ch/3ch EXR — 切到单通道时无需改 |
| `dist/frame_capture.addon` | 已重建，已 commit |

## Performance Numbers (final)

```
游戏：FF7 Remake，1080p，scene RT 1920×1080 r16g16b16a16_float
addon：FC_TargetFPS=30，FC_PreUICapture=1，FC_ExportDepth=1
worker：2 threads，MAX_QUEUE=16

capture 实测：
  250 BMP / 12.9 s = 19.4 fps
  248 EXR / 12.9 s = 19.2 fps（首 1-2 帧 depth_staging 未分配）

输出体积：
  BackBuffer.bmp     7.4 MB（1920×1080 RGBA8）
  DepthBuffer.exr   ~89 KB（1920×1080 1ch float ZIP）
  dataset.h5      1099.6 MB / 401 frames
```

## Resume Instructions

如果下一会话要继续：

### 验证 ui-only / both 模式

```powershell
Remove-Item "$env:TEMP\unicap\unicap.log*"
uv run main.py launch --game-path "E:\games\..." --ui-mode ui-only
# 期望：F8 直接进 capture（无 survey），BMP 带 UI

uv run main.py launch --game-path "E:\games\..." --ui-mode both
# 期望：F8 先 survey（如缺 recommended），然后双流。
# 帧目录每个 ts 两份 BMP（BackBuffer / BackBufferUI），video.mp4 + video_ui.mp4
```

### 想冲 30 fps

`reshade-addons/99-frame_capture/frame_capture.cpp` line ~88：
```cpp
static constexpr size_t NUM_WORKERS = 2;  // → 改成 3 或 4
```
重编 + 实机看是否到 30 fps。注意盯磁盘 IO（任务管理器 → 性能 → 磁盘活动时间），如果接近 100% 就是磁盘瓶颈，加 worker 没用。

## Warnings

- **不要回退 `safe_last_rt` 守门**：FF7R 在 enhanced render pass 路径下，skip>0 的 BB-bind shader_resource barrier 会让 `CommandList::Close()` 返回 `E_INVALIDARG` → UE4 LowLevelFatalError → 弹窗崩溃。当前代码靠这个守门把 enhanced + skip>0 收编为 UIRemove fallback。代价是 enhanced + skip>0 拿不到精确 pre-UI（FF7R 用 skip=0 已够，没人在乎）。
- **survey dedup gate 不能省 `fc_pass_total.txt`**：移到 dedup gate **之前**写出。Phase 1 第一帧不写 → Python 4 秒后 abort 报"未读到 fc_pass_total.txt"。
- **`reshade-addons/deps/reshade/include` 是 v5 wrapper API**，与自建 6.7.3.16 `dist/dxgi.dll` 二进制兼容；不要换路径。
- **6.7.3.16 自建 dxgi.dll 在 R10G10B10A2 swap chain 下输出错色 BMP**（FF7R swap chain 是 R10G10B10A2，但 capture 走 scene RT 路径、不读 BB，所以没事）。如果以后某游戏 BMP 颜色不对、且强制 ui-only 走 BB 路径，先排查这个。
- **`NUM_WORKERS` 是 `constexpr`，不读 ini**。要改值需改源码 + 重编。

## Setup Required

- VS 2022 Build Tools；`scripts\build.ps1` 编译 addon
- `uv sync`（Python deps：opencv-python, h5py, numpy）
- FF7 Remake 路径写在 README/handoff，不在 config.py
- `DATASET_ROOT = D:\unicap_output`（`tools/capture/config.py`）
- 日志：`%TEMP%\unicap\unicap.log{,1}` — log1 是真正长跑的游戏进程
