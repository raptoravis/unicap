# Handoff: unicap pipeline — Pre-UI 场景 RT 采集

**Generated**: 2026-04-30
**Branch**: master (up to date with origin/master, commit f94e114)
**Status**: In Progress — 颜色已正确，UI 仍可见，需要调参找正确 skip 值

## Goal

FF7 Remake (DX12 / UE4) 帧采集：**只保存 3D 游戏画面，不含 HUD/UI**，同时输出深度 EXR。
核心问题是 UE4 的 UI 通过中间 RT 合成（不是直接画到 backbuffer），需找到合成前的那个 RT。

## Completed

- [x] 定时采集（steady_clock），fc_output_dir.txt sidecar 控制开关（F9 之前不采集）
- [x] GPU TDR 崩溃修复：场景 RT 拷贝移至 `on_bind_rts_dsv` backbuffer bind 事件（mid-frame，游戏自己的 cmd list），而非 `reshade_present`
- [x] Reverse-skip 机制：`FC_PreUISkipCount=N` 捕捉倒数第 N+1 个非 BB RT
- [x] HDR 格式解码：`decode_to_rgba8` 新增 `r16g16b16a16_float`（half_to_float + Reinhard + sRGB gamma）和 `r11g11b10_float`
- [x] EXR（深度）拷贝加入 use_scene_rt 路径（原来只在 UIRemove fallback 路径才拷贝深度）
- [x] `--pre-ui` / `--pre-ui-skip` CLI 参数加入 `deploy` 和 `launch`
- [x] `official592` 模式改用 `dist/frame_capture.addon`（不再用 vendor/addon_official）
- [x] sidecar unlink PermissionError 修复（try/except，fallback 写空字符串）
- [x] 会话结束分别打印 BMP 和 EXR 数量

## Not Yet Done

- [ ] **找到正确的 skip 值**：`skip=5`（pass 67/73）还有 UI，需 binary search（试 skip=15、30、50）
- [ ] **验证 EXR 深度**：use_scene_rt 路径的深度拷贝是本次新加的，尚未实机确认 EXR 正常输出
- [ ] **颜色质量**：当前使用 Reinhard tone map，可能与游戏实际画面有偏差；对 ML 训练是否够用待评估
- [ ] Batman AK 适配（本次工作集中在 FF7 Remake）

## Failed Approaches (Don't Repeat These)

1. **在 `reshade_present` 时拷贝 `s_last_non_bb_rt`（GPU TDR 崩溃）**
   UE4 在 Present 之后对 transient resource 发出 aliasing barrier（deactivate），
   此时再对该 resource 发 `barrier(shader_resource → copy_source)` 导致 GPU hang / TDR。
   **修复**：在 `on_bind_rts_dsv` backbuffer bind 事件（帧渲染中途，Present 之前）发拷贝命令。

2. **Forward-skip of backbuffer binds（g_pre_ui_skip 跳过前 N 次 BB bind）**
   `on_bind_rts_dsv` 在 BB bind 时 backbuffer 内容是上一帧残留（FLIP_DISCARD 语义），
   拷贝出来是上一帧带 UI 的内容。整个思路作废。

3. **捕捉最后一个非 BB RT（skip=0, 即 pass 72/73）显示有 UI**
   说明 FF7 Remake 的 UI 是渲染到中间 RT 再合成到 backbuffer 的（Slate 通过 UE4 RDG 渲染），
   而非直接画 backbuffer。所以最后几个非 BB RT 已含 UI。需要往前跳。

4. **UIRemove_ColorTex fallback（捕获时序太晚）**
   `reshade_begin_effects` 在 Present 之后触发，此时所有 UI 已经画完。该路径只能获得含 UI 的帧，
   只用作 pre_ui_mode=false 的降级路径。

5. **`decode_to_rgba8` default 分支 memcpy HDR RT**
   中间 RT 格式是 `r16g16b16a16_float`（DXGI=10），逐像素 8 字节；
   memcpy 只拷 w×4 字节，等于拷了 R/G 两个 F16 通道，
   结果是极暗的噪点图案（暗红/蓝色）。已添加 half_to_float 解码 + tone map。

6. **Forward 逐帧 binary search skip（之前旧方案）**
   之前的 skip 是正向的（跳过前 N 次 BB bind）；换成 reverse-skip 后，
   skip=N 捕捉第 `(total-1-N)` 个 pass（0-indexed）。两者方向相反，不要混淆。

## Key Decisions

| Decision | Rationale |
|----------|-----------|
| 在 on_bind_rts_dsv BB bind 时拷贝 RT | RT 仍活跃，状态已知（shader_resource，刚被 final blit 读取）；reshade_present 时 UE4 可能已 alias 释放 |
| barrier: shader_resource → copy_source | Final composite pass 将 scene RT 作为 SRV 读取后转到 BB；此时 RT 处于 SR 状态 |
| Reverse-skip 用 s_prev_non_bb_total | 当帧总数稳定（FF7 Remake 每帧固定 73 个非 BB pass）时，用上一帧总数计算目标 pass 序号 |
| Reinhard + sRGB gamma 用于 HDR decode | 简单、无外部依赖；对 ML 训练的视觉质量足够；若需精确 HDR 可替换为 ACES 或游戏自带 tonemapper |
| official592 模式用 dist/frame_capture.addon | vendor/addon_official 是旧二进制，不含本次修复；official592 DLL 与 v5 addon API 兼容 |
| use_scene_rt 条件改为 s_pre_ui_captured | 拷贝已发生在 on_bind_rts_dsv，present 时只需 map；用 s_pre_ui_captured 作标志 |

## Current State

**Working**:
- 场景几何/颜色/光照正确（HDR 解码修复后）
- 无 GPU TDR 崩溃
- F9 之前不采集（sidecar gate 正常工作）
- BMP 文件正常写出，帧率正确

**Broken / Pending**:
- UI 仍可见（skip=5，pass 67/73）—— 需调大 skip 继续搜索
- EXR 深度：代码已加，未实机验证
- Tone map 可能与游戏色调有偏差（Reinhard vs 游戏内部 tonemapper）

## Files to Know

| File | Why It Matters |
|------|----------------|
| `reshade-addons/99-frame_capture/frame_capture.cpp` | 全部采集逻辑：reverse-skip、barrier 拷贝、HDR decode、depth EXR |
| `main.py` | CLI：`_sources()`（mode→addon 路径映射）、`_ensure_addon_enabled`（写 unicap.ini） |
| `tools/capture/capture_all.py` | 写/删 fc_output_dir.txt sidecar；进度打印 |
| `tools/capture/config.py` | 机器相关路径：GAME_PATH、DATASET_ROOT |
| `shaders/UIRemove.fx` | UIRemove_ColorTex fallback（pre_ui=false 时使用） |
| `shaders/DepthToAddon.fx` | 暴露 DepthToAddon_ExportTex（RGBA32F，depth 在 alpha channel）|
| `scripts/build.ps1` | `-Rebuild` 删除 build/ 目录；编译 dist/frame_capture.addon |

## Code Context

**Reverse-skip 逻辑（on_bind_rts_dsv 非 BB 路径）：**
```cpp
// s_prev_non_bb_total = 上一帧的非 BB pass 总数（FF7 Remake 固定 73）
// g_pre_ui_skip       = FC_PreUISkipCount（CLI --pre-ui-skip N）
uint32_t target = (s_prev_non_bb_total > g_pre_ui_skip)
                  ? (s_prev_non_bb_total - 1 - g_pre_ui_skip)
                  : 0;
should_record = (s_no_dsv_non_bb == target);
// skip=0: target=72 (最后一个)；skip=5: target=67；skip=20: target=52
```

**RT 拷贝时机（on_bind_rts_dsv BB bind 路径）：**
```cpp
// BB bind 时：所有非 BB pass 已完，目标 RT 在 shader_resource 状态
cmd_list->barrier(s_last_non_bb_rt, resource_usage::shader_resource, resource_usage::copy_source);
cmd_list->copy_texture_region(s_last_non_bb_rt, 0, nullptr, g_pre_ui_staging, 0, nullptr);
cmd_list->barrier(s_last_non_bb_rt, resource_usage::copy_source, resource_usage::shader_resource);
s_pre_ui_captured = true;
```

**use_scene_rt 判定（on_reshade_present）：**
```cpp
// 颜色已在 on_bind_rts_dsv 拷好，只需 map；深度在这里拷
bool use_scene_rt = g_pre_ui_mode && s_pre_ui_captured && g_pre_ui_staging.handle != 0;
```

**HDR 解码（decode_to_rgba8）：**
```cpp
case format::r16g16b16a16_float: {  // DXGI value = 10
    const uint16_t* p16 = reinterpret_cast<const uint16_t*>(row);
    for (uint32_t x = 0; x < w; x++) {
        out[x*4+0] = hdr_to_u8(half_to_float(p16[x*4+0]));
        // hdr_to_u8: Reinhard(v/(1+v)) + sRGB gamma
    }
}
case format::r11g11b10_float: {  // DXGI value = 26
    // 32-bit packed: R[10:0] G[21:11] B[31:22]
}
// 未知格式：打印 "FC: decode fmt=N not handled" 到日志，然后 raw copy
```

**重置帧状态（每帧末尾）：**
```cpp
s_prev_non_bb_total = s_no_dsv_non_bb;  // 保存本帧总数供下帧 reverse-skip 用
s_had_depth_pass  = false;
s_pre_ui_captured = false;
s_no_dsv_non_bb   = 0;
s_last_non_bb_rt  = { 0 };  // 必须清零，防止旧句柄跨帧污染
```

**诊断日志（前 30 个采集帧）：**
```
FC: capfN bb_handles=3 had_depth=1 no_dsv_bb=1 no_dsv_non_bb=73 captured=1
FC: scene RT staging allocated WxHxfmt=10   ← fmt=10 = r16g16b16a16_float
FC: decode fmt=N not handled, raw copy      ← 遇到未知格式时出现
```

**部署命令：**
```powershell
uv run main.py deploy --mode official592 --pre-ui --pre-ui-skip 15
# 或启动游戏
uv run main.py launch --mode official592 --pre-ui --pre-ui-skip 15 --fps 30 --duration 10
```

**unicap.ini 关键配置：**
```ini
[ADDON]
AddonPath          = D:\dev\unicap.git\dist
FC_PreUICapture    = 1
FC_PreUISkipCount  = 15        ← 调整这个值（当前测试用 5，需要更大）
FC_TargetFPS       = 30
FC_ExportDepth     = 1
[INPUT]
KeyOverlay         = 0,0,0,0   ← 必须显式设置
```

## Resume Instructions

**目标：找到 UI 消失的 skip 临界值**

1. 关闭游戏（确保 `dist/frame_capture.addon` 未被锁定）

2. 用更大的 skip 部署：
   ```powershell
   uv run main.py deploy --mode official592 --pre-ui --pre-ui-skip 15
   ```

3. 启动游戏（通过 `main.py launch` 或手动启动，需设置 env var）：
   ```powershell
   $env:RESHADE_BASE_PATH_OVERRIDE = "$env:TEMP\unicap"
   Start-Process "E:\games\ff7remake\End\Binaries\Win64\ff7remake_.exe"
   ```

4. 采集一批帧，检查 BMP：
   - 期望：场景正确，UI 消失（无 waypoint 箭头、无 Commands Menu 等）
   - 如果还有 UI：增大 skip（30、50、60）
   - 如果图像变黑/变成完全不同的内容：skip 太大，往小调

5. Binary search 参考（73 个 pass）：
   | skip | target pass (0-indexed) | 说明 |
   |------|------------------------|------|
   | 5    | 67                     | 已确认有 UI |
   | 15   | 57                     | 试这个 |
   | 30   | 42                     | 若 15 还有 UI |
   | 50   | 22                     | 深度 3D pass 区域 |

6. 找到临界值后，固定在部署命令中；也可写死到 `tools/capture/config.py` 里。

7. **验证 EXR 深度**（本次新加，未验证）：
   ```python
   import glob
   exrs = glob.glob(r"D:\ff7_dataset\*\frames\*.exr")
   print(f"{len(exrs)} EXR files found")
   # 期望：每个 BMP 对应一个 EXR
   ```
   如果 0 EXR：检查日志中是否有 `FC: failed to create depth staging (scene_rt)` 或
   `DepthToAddon_ExportTex` 是否出现在 `FC: listing all effect texture variables`。

## Setup Required

- VS 2022 Build Tools（重编 addon 时需要）
- `uv sync`（Python 依赖）
- FF7 Remake: `E:\games\ff7remake\End\Binaries\Win64\ff7remake_.exe`
- 日志位置: `%TEMP%\unicap\unicap.log`（关键诊断信息都在这里）

## Warnings

- **不要在 reshade_present 时拷贝游戏 RT**：UE4 transient resources 在 Present 后 alias 释放，barrier 会触发 GPU TDR。当前代码的拷贝在 `on_bind_rts_dsv` BB bind 事件，不要改回去。
- **barrier 状态必须用 `shader_resource`**：目标 RT 在最后一个使用它的 pass 之后处于 SR 状态（被 final composite pass 读取）。如果改成 `render_target` 会状态不匹配。
- **on_begin_render_pass 和 on_bind_rts_dsv 都会触发**：DX12 游戏可能同时用两个 API。`s_pre_ui_captured` gate 防止重复拷贝（先到先得，第二个直接 return）。
- **s_last_non_bb_rt 每帧必须清零**：在 `reset_frame_state` 末尾已有 `s_last_non_bb_rt = {0}`。若漏掉会导致旧句柄跨帧使用，造成状态不匹配崩溃。
- **s_prev_non_bb_total 第一帧为 0**：第一帧 skip 逻辑走 always-overwrite（最后一个 RT），第二帧起才生效 reverse-skip。这是正常行为。
- **FF7 Remake 是双进程启动**：第一进程约 2s 退出，第二进程做实际 DX12 渲染。`on_begin_render_effects` 的 backbuffer handle 刷新逻辑依赖这个（每帧重新枚举）。
- **fmt=10 = r16g16b16a16_float** 是当前 FF7 Remake 中间 RT 格式，decode_to_rgba8 已处理。如果遇到其他 fmt 值，看日志 `FC: decode fmt=N not handled`，再加 case。
- **不要改 `reshade-addons/deps/reshade/include` 包含路径**：addon 用 v5 wrapper API，与 official592 dxgi.dll 二进制兼容；改路径会破坏兼容性。
