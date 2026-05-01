# Handoff: --ui-mode 三模式 + survey 多轮崩溃修复

**Generated**: 2026-05-01 15:18
**Branch**: master (3 commits ahead of origin/master, plus uncommitted addon fix)
**Status**: In Progress — 最新一轮 addon 崩溃修复已编译，**未实机验证**

## Goal

让 unicap 支持三种采集输出模式，通过 `--ui-mode {no-ui, ui-only, both}` 控制：

| Mode | F6 survey | 输出 |
|---|---|---|
| `no-ui`（默认） | 必需（自动）| 仅 pre-UI 帧 |
| `ui-only` | 跳过 | 仅 post-UI BackBuffer |
| `both` | 必需 | 双流（pre-UI + post-UI） |

同时本会话踩了一连串 D3D12 崩溃的坑，需要把整套 addon 调到能完整跑通 survey + capture。

## Completed

- [x] **`--ui-mode` CLI 接入**（`main.py`）：argparser + `_ensure_addon_enabled` 写出 `FC_PreUICapture` / `FC_BothCapture` 两个 ini key + `_interactive_loop` 在 ui-only 下不要 survey
- [x] **Addon `FC_BothCapture` 双流支持**：`SaveTask` 加 `ui_*` 字段；`use_scene_rt` 分支额外 copy `UIRemove_ColorTex` 到 `sbi.color_staging`，map 出 `task.ui_color_pixels`；worker 多写一张 `BackBufferUI.bmp`；survey 模式下强制 `do_ui=false`
- [x] **`pack_hdf5.py` 识别 `BackBufferUI` 后缀**：regex 扩展 + `scan_frames` 加 `bmp_ui` 字段 + 存在时新增 `/color_ui` 数据集
- [x] **`_make_video` 接 glob 模式 + `_run_capture` 双流自动生成 `video_ui.mp4`**
- [x] **删除 `--mode` CLI 参数**：`_sources()` 函数移除，改用 `DXGI_DLL` / `ADDON_BIN` / `SHADER_SRC` 常量直接指 `dist/`
- [x] **删除 vendor/reshade592/, vendor/reshade673/, vendor/addon_official/**（git rm，已 commit）
- [x] **修第一轮崩溃**：`survey.py` `_wait_for_bmp` 用 `mtime_floor` 过滤上轮残留，去掉主动 unlink（避免和 addon 写盘抢锁的 `WinError 32`）
- [x] **修 `_find_boundary` 对 FF7R 类管线推荐反向**：最大跳变发生在最小 skip 对（s_lo == 最小捕获值）且差分远超中位时，直接返回最小 skip（即 0）
- [x] **修 D3D12 `E_INVALIDARG` 崩溃（已编译，待验证）**：BB-bind 分支加 `safe_last_rt = (g_pre_ui_skip == 0 || s_prev_non_bb_total == 0)` 守门；`on_begin_render_pass` 移除 `fc_copy_rt_at_bind` 调用；`MAX_QUEUE` 4 → 16
- [x] **CLAUDE.md / CMakeLists.txt** 同步说明（移除 official 路径）

## Not Yet Done

- [ ] **实机验证最新 addon 修复**（未提交）：用户上一轮在 71-pass 场景按 F8 自动 survey，仍在 skip=45 崩。修复已编译进 `dist/frame_capture.addon`（mtime 比上次新），但还没有用户实机测过。
- [ ] **commit 最新一轮 addon 修复**：当前未提交的改动 = `frame_capture.cpp` (BB-bind 守门 + 移除 enhanced 路径 bind-time copy + MAX_QUEUE 16) + `dist/frame_capture.addon` (rebuilt) + `vendor/installers/*.exe` (用户已删盘上)
- [ ] **`vendor/installers/*.exe` 决策**：用户已 rm 掉两个 ReShade 安装包（未 git rm），需要 `git rm` 完成删除或 `git checkout -- ` 恢复
- [ ] **三模式实机走通**：`--ui-mode no-ui`(已工作), `--ui-mode ui-only`(未测), `--ui-mode both`(未测)。`both` 模式下 `BackBufferUI.bmp` + `video_ui.mp4` + `/color_ui` 这条新链路从未跑过

## Failed Approaches (Don't Repeat These)

1. **survey 中 `_wait_for_bmp` 主动 unlink 旧文件**
   `target.unlink()` 和 addon 在 `wait_per_skip` 期间反复覆写同名 BMP 抢锁 → `WinError 32 [另一个程序正在使用此文件]` → Python 抛 PermissionError。
   → 改用：mtime_floor（survey 开始时刻）过滤上轮残留，不再主动 unlink。`stat()` 失败就忽略下一轮再试。

2. **survey 模式 bind-time copy 加在 `on_begin_render_pass`（DX12 enhanced render pass 路径）**
   ReShade 的 `addon_event::begin_render_pass` 在 `BeginRenderPass` API 调用**之前**触发，那时 RT 还没被 UE4/驱动隐式切到 `render_target` 状态。`barrier(rt, render_target, copy_source)` 源状态判定失败 → cmd_list 里悄悄塞了一条非法 barrier → 帧末 `CommandList::Close()` 返回 `E_INVALIDARG` → UE4 LowLevelFatalError → 弹窗崩溃。
   → 改用：`on_begin_render_pass` **不做** bind-time copy。`on_bind_rts_dsv`（legacy `OMSetRenderTargets` 路径，RT 进函数前必须已经在 render_target）保留 bind-time copy。FF7R 走 enhanced 路径就只有 fallback 到 UIRemove，但不崩。

3. **BB-bind 分支无条件用 `barrier(s_last_non_bb_rt, shader_resource, copy_source)`**
   仅当 `s_last_non_bb_rt` 是当帧的**最后一个**非 BB RT（= BB compositor 的输入）时它才一定在 shader_resource。中段 RT（specific skip>0 target）可能在任何状态 → 同样 `Close() E_INVALIDARG` → 崩。
   → 改用：BB-bind 分支加 `safe_last_rt = (g_pre_ui_skip == 0 || s_prev_non_bb_total == 0)` 守门，只在 always-overwrite（最后一个 RT）情况下才动 shader_resource barrier。skip>0 时 BB-bind 分支跳过，让 use_scene_rt 自然落到 false → fallback 到 UIRemove。

4. **`_find_boundary` 默认假设"稳定区=pre-UI"**
   FF7R 把 UI 合成在最后一个非 BB RT 之内，所以 skip=0（最后那个 RT，BB-bind shader_resource path）才是干净 pre-UI 帧；skip=1..21 反而是 with-UI 区。算法当时给出 recommended=1（用户人工覆盖为 0 才正确）。
   → 改用：先检查最大跳变是否发生在最小 skip 对 `largest[1] == ordered[-1]`，且差分 > 5× 中位差分，则直接返回最小 skip。其他情况走原算法。

5. **survey 模式 skip=0 试图统一用 specific target = total-1 + bind-time copy**
   原本想"survey 所有 skip 都用 bind-time copy"保证语义一致，结果 skip=0 在 enhanced 路径下崩，效果还不如分两条路径。
   → 改用：skip=0 仍走 always-overwrite + BB-bind shader_resource path（safe_last_rt=true）。skip>0 走 fc_copy_rt_at_bind（仅 legacy 安全；enhanced 直接 fallback）。

6. **想让 ReShade overlay always-on 显示 hint**（沿用更早 handoff）
   `register_overlay()` callback 仅在 ReShade 主面板打开时绘制。
   → 改用：自定义 shader `CaptureStatus.fx` 画屏幕角条 + 控制台同步打印。

## Key Decisions

| Decision | Rationale |
|----------|-----------|
| skip>0 在 enhanced render pass 路径下放弃精确捕获，回落 UIRemove | DX12 强 barrier 校验下，未知 RT 状态 = 必崩。FF7R 类游戏 skip=0 已能拿到 pre-UI，没必要冒险支持 skip>0 |
| `--ui-mode` 同时控制 `FC_PreUICapture` + `FC_BothCapture` 两个 flag | 单一参数对外，addon 内部解耦：FC_PreUICapture 管 pre-UI 路径开关，FC_BothCapture 管 both 模式额外的 post-UI dump |
| `BackBufferUI.bmp` 而非 `_UI.bmp` 后缀 | pack_hdf5 的 regex 字面量匹配；`*BackBuffer.bmp` glob 不会误匹配 `*BackBufferUI.bmp` |
| `MAX_QUEUE` 4 → 16 | survey 阶段游戏侧 30 fps × 7.5MB BMP 让 worker 跟不上，4-deep 队列瞬间填满；老是 "save queue full, dropping frame" 警告 |
| 删除 `--mode` CLI 而不是保留作 future-proof | 用户明确："不再需要 official592/official673" |
| 移除 `dist/dxgi.dll 不部署`的旧描述 | CLAUDE.md 之前说过它"is unused"但代码 `_sources("custom")` 实际就部署它。统一为：`dist/dxgi.dll` 是唯一部署源 |

## Current State

**Working** (已 commit 部分):
- `--ui-mode no-ui`（默认）+ skip=0：实测可以完整 F8 → F9 → pack → video.mp4 + dataset.h5
- `_find_boundary` 反向规则在 22-pass 场景下推荐 0
- `dist/frame_capture.addon` (205312 B before; 205312 B 重建后) 编译干净（仅遗留 C4819 BOM 警告）

**Pending verification** (未提交):
- 71-pass 场景 + 自动 survey：用户上一轮在 skip=45 崩溃。最新 addon 加了 BB-bind safe_last_rt 守门 + on_begin_render_pass 移除 bind-time copy。**没再实机跑过**。
- `--ui-mode ui-only` / `--ui-mode both` 从未实机测过。
- HDF5 `/color_ui` 字段、`video_ui.mp4` 从未真生成过。

**Uncommitted Changes**:

```
modified:   dist/frame_capture.addon                  ← 重新编译
modified:   reshade-addons/99-frame_capture/frame_capture.cpp
deleted:    vendor/installers/ReShade_Setup_5.9.2_Addon.exe   (用户 rm 掉)
deleted:    vendor/installers/ReShade_Setup_6.7.3_Addon.exe   (用户 rm 掉)
```

## Files to Know

| File | Why It Matters |
|------|----------------|
| `reshade-addons/99-frame_capture/frame_capture.cpp` | 唯一 ~1300 行 C++。本轮关键改动：`fc_copy_rt_at_bind` (~line 498)、`on_bind_rts_dsv` 的 should_record block (~line 568)、`on_begin_render_pass` 的 should_record block (~line 656，**已移除** bind-time copy 调用)、两处 BB-bind safe_last_rt 守门 (~line 595 / ~line 685) |
| `tools/capture/survey.py` | mtime_floor 过滤 (`_wait_for_bmp`) + FF7R 反向规则 (`_find_boundary` 头几行) |
| `main.py` | `_ensure_addon_enabled(addon_dir, pre_ui_skip, ui_mode)` 写两个 flag 到 unicap.ini；`_interactive_loop` 按 ui_mode 决定是否要 survey；`_run_capture` 检测 `*BackBufferUI.bmp` 自动出 video_ui.mp4；`DXGI_DLL`/`ADDON_BIN`/`SHADER_SRC` 常量取代 `_sources()` |
| `tools/capture/pack_hdf5.py` | `_RE_A` 多匹配 `BackBufferUI`，scan_frames 把它存到 `bmp_ui` 字段，pack 检测到就开 `/color_ui` 数据集 |
| `dist/frame_capture.addon` | 已重建含本轮所有改动。**没 commit**。 |

## Code Context

**当前 addon 的关键 flag 与 sidecar 协议**（unicap.ini）：

```ini
[ADDON]
FC_PreUICapture = 0|1     # 0 = ui-only mode (post-UI BB), 1 = no-ui/both
FC_BothCapture  = 0|1     # 1 = both mode 多写一张 BackBufferUI.bmp
FC_PreUISkipCount = N     # 来自 survey 推荐
```

`--ui-mode` 映射：
```python
pre_ui_flag = "0" if ui_mode == "ui-only" else "1"
both_flag   = "1" if ui_mode == "both"    else "0"
```

**关键 BB-bind 守门逻辑**（`frame_capture.cpp` ~line 595, ~685）：

```cpp
// 仅当 g_pre_ui_skip == 0 (always-overwrite, 最后那个 RT) 时才用 shader_resource barrier
bool safe_last_rt = (g_pre_ui_skip == 0 || s_prev_non_bb_total == 0);
if (s_last_non_bb_rt.handle != 0 && s_had_depth_pass && safe_last_rt) {
    cmd_list->barrier(s_last_non_bb_rt, resource_usage::shader_resource, resource_usage::copy_source);
    cmd_list->copy_texture_region(...);
    cmd_list->barrier(s_last_non_bb_rt, resource_usage::copy_source, resource_usage::shader_resource);
    s_pre_ui_captured = true;
}
```

**enhanced render pass 路径不做 bind-time copy**（`on_begin_render_pass` ~line 656）：

```cpp
if (should_record) {
    s_last_non_bb_rt  = r;  // 仅记录，不 copy
    s_last_non_bb_w   = rd.texture.width;
    s_last_non_bb_h   = rd.texture.height;
    s_last_non_bb_fmt = rd.texture.format;
    // NOTE: do NOT call fc_copy_rt_at_bind here. on_begin_render_pass
    // fires BEFORE BeginRenderPass's implicit state transition...
}
```

**survey 反向规则**（`survey.py:_find_boundary`）：

```python
median_diff = all_diffs[len(all_diffs) // 2]
largest = max(pairs, key=lambda p: p[2])
if largest[1] == ordered[-1] and largest[2] > 5.0 * max(median_diff, 1.0):
    return largest[1]   # FF7R 类管线: 最小 skip 才是 pre-UI
```

**HDF5 schema 扩展**：

```python
# pack_hdf5.py:pack()
has_ui = any(f.get('bmp_ui') for f in frames)
...
if has_ui:
    ds_color_ui = hf.create_dataset('color_ui', (n, H, W, 3), dtype='uint8',
                                    chunks=(1, H, W, 3), **_C)
```

## Resume Instructions

> **关键前提**：FF7R 实际安装路径是 `E:\games\ff7remake\3DMGAME_Final_Fantasy_VII_Remake.CHS.Green.part001\Final Fantasy VII Remake Intergrade\End\Binaries\Win64`。每次 launch 都要传 `--game-path`。
> `DATASET_ROOT` 现在是 `D:\unicap_output`（本会话用户改了 `tools/capture/config.py`，已 commit）。

### 1. 实机验证 BB-bind safe_last_rt 修复（最优先）

清旧日志：
```powershell
Remove-Item "$env:TEMP\unicap\unicap.log*"
Remove-Item -Recurse "D:\unicap_output\ff7remake_\survey\*" -ErrorAction SilentlyContinue
```

启动：
```powershell
uv run main.py launch --game-path "E:\games\ff7remake\3DMGAME_Final_Fantasy_VII_Remake.CHS.Green.part001\Final Fantasy VII Remake Intergrade\End\Binaries\Win64"
```

进 3D 关卡按 F8（会自动 survey）：
- **Expected**: survey 完整跑完 skip=70 → skip=0 不崩。skip>0 大多数 ✓ 7500 KB（UIRemove fallback），skip=0 内容明显不同。`_find_boundary` 命中 outlier 规则推荐 0。然后自动进 capture 阶段，红条出现，按 F9 → pack → video.mp4。
- **If 还崩**: 看 `%TEMP%\unicap\unicap.log1` 末尾。如果还是 D3D12 E_INVALIDARG，找最近的几行 `FC: capf%u ...` 看 captured 字段是否=1。如果 captured=1 但崩，说明 fc_copy_rt_at_bind 在 legacy 路径上的 render_target 假设也错了——这种情况下需要把 `on_bind_rts_dsv` 里的 fc_copy_rt_at_bind 调用也移除。

### 2. 实机验证 `--ui-mode ui-only`

```powershell
uv run main.py launch --game-path "..." --ui-mode ui-only
```

期望：
- 终端：`[等待] 按 F8 = 采集（mode=ui-only，无需 survey）`
- 按 F8 直接进 capture（红条），不会先 survey
- 按 F9 → 出 video.mp4 + dataset.h5
- BMP 内容**有 UI**（这是 post-UI BB）

### 3. 实机验证 `--ui-mode both`

```powershell
uv run main.py launch --game-path "..." --ui-mode both
```

期望：
- F8 → 自动 survey（如缺 recommended_skip）
- 帧目录里同一个时间戳有**两份 BMP**：`<ts> BackBuffer.bmp` (pre-UI) + `<ts> BackBufferUI.bmp` (post-UI)
- 按 F9 后输出 `video.mp4` + `video_ui.mp4` + `dataset.h5`（含 `/color` 和 `/color_ui` 两个数据集）
- 验证 HDF5：`uv run main.py pack --spot-check D:\unicap_output\ff7remake_\<时间戳>\dataset.h5` 应该能展示两路 color

### 4. Commit

如果 1-3 全过，commit 当前未提交内容：
```powershell
rtk git rm vendor/installers/ReShade_Setup_5.9.2_Addon.exe vendor/installers/ReShade_Setup_6.7.3_Addon.exe
rtk git add reshade-addons/99-frame_capture/frame_capture.cpp dist/frame_capture.addon
rtk git commit -m "fix: BB-bind shader_resource barrier 仅对 last-RT 安全 + 移除 enhanced 路径 bind-time copy"
```

如果用户保留 installers，则 `git checkout -- vendor/installers/` 恢复。

## Setup Required

- VS 2022 Build Tools；`scripts\build.ps1` 编译 addon
- `uv sync`（Python deps：opencv-python, h5py, numpy）
- FF7 Remake 已装在长 3DMGAME 路径
- Dataset 输出根目录 `D:\unicap_output` 必须可写（`config.py` 默认）
- 日志路径 `%TEMP%\unicap\unicap.log{,1}`（注意：log = 第一个 dxgi 加载进程，**log1 = 真正长跑的游戏进程**，常用 log1）

## Edge Cases & Error Handling

- **F6 在标题/loading/cutscene 按** → 没有 DSV pass → s_no_dsv_non_bb=0 → 不写 fc_pass_total.txt → Python 4 秒后失败提示"请进入 3D 场景"
- **F8 时已有 recommended_skip.txt** → 跳过 survey 直接 capture
- **F8 + ui-only** → 永远不 survey，直接 capture（连 recommended_skip.txt 都不读）
- **F6 + ui-only** → main.py 打印"本模式不需要 survey，已忽略"，不调 survey
- **survey 帧数不足/被 F9 中止** → `[SURVEY] 帧数不足，无法分析` 或 `[SURVEY] 已中止，跳过分析`，不写 recommended_skip.txt
- **save queue full**（addon 日志）→ worker 跟不上，丢一帧。MAX_QUEUE=16 现在应该够，30fps 下 16 帧 ≈ 533ms 缓冲
- **`_load_recommended_skip` 文件不存在** → 返回 None → F8 触发自动 survey
- **fc_copy_rt_at_bind create_resource 失败**（理论上 OOM 才会）→ 返回 false → s_pre_ui_captured 保持 false → use_scene_rt=false → fallback UIRemove → 写 BMP 但**注意**：s_last_non_bb_rt 已被设值，因 safe_last_rt 守门只在 skip=0 时让 BB-bind 跑

## Warnings

- **`on_begin_render_pass` 现在不做 bind-time copy**（已注释说明原因）。如果以后想在 enhanced render pass 路径上支持 skip>0 精确捕获，需要找一个能保证 RT 在 render_target 状态的事件点（可能是 `on_finish_render_pass`，但 ReShade addon API 是否提供需查证）
- **survey skip>0 在 FF7R 上等价于 UIRemove fallback**（用户上次实测 7500 KB BMP 全是这个）。所以 survey 找到的"边界"实际上只是"skip=0 (last RT) vs 其他 (UIRemove BB)"的差分。outlier 规则触发 → 推荐 0。这是设计上接受的妥协
- **F6/F8/F9 是 Python `GetAsyncKeyState` 全局轮询**，不依赖 addon。游戏前台时也能读
- **`fc_skip_count.txt` 双重职责**（survey + post-survey skip pulse），pulse 期间会写一帧 `survey_skip_NNN_BackBuffer.bmp` 然后被 `_clear_skip` 删掉
- **`reshade-addons/deps/reshade/include` 是 v5 wrapper API**，与自建 6.7.3.16 `dist/dxgi.dll` 二进制兼容；不要换路径
- **不要在 `on_reshade_present` 里拷贝游戏 RT**（沿用旧约束 — 此时 RT 可能已被 alias）。所有 game RT copy 必须发生在 `on_bind_rts_dsv` 或 `on_begin_render_pass` 期间，且只在状态可证情况下
- **6.7.3.16 自建 dxgi.dll 在 R10G10B10A2 swap chain 下输出错色 BMP**（FF7R 不是 R10G10B10A2 所以没问题）。如果以后某游戏 BMP 颜色不对，先排查这个
- **`vendor/installers/` 已被用户 rm 但未 git rm**：要么 `git rm` 完成删除，要么 `git checkout -- vendor/installers/` 恢复，否则会一直显示 "deleted in working tree"
