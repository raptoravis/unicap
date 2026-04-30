# Handoff: unicap pipeline — survey 模式完成，待实机验证

**Generated**: 2026-04-30
**Branch**: master (clean, up to date with origin/master, commit df915e1)
**Status**: In Progress — 全部代码已提交，待实机验证 skip=7 无 UI + EXR 深度输出

## Goal

FF7 Remake (DX12/UE4) 帧采集：只保留 3D 游戏画面（无 HUD/UI），同时输出深度 EXR。`survey` 子命令自动找到正确的 `FC_PreUISkipCount` 值，无需手动试值。

## Completed

- [x] survey 自动扫描：一次游戏会话扫遍全部 skip 值，无需反复重启
- [x] addon 自动写 `fc_pass_total.txt`（当帧非 BB pass 总数），Python 据此计算扫描范围
- [x] `fc_skip_count.txt` sidecar：Python 运行时动态改变 `g_pre_ui_skip`（无需重部署 addon）
- [x] survey 文件名含 skip 值（`survey_skip_NNN_BackBuffer.bmp`），Python 按名匹配
- [x] 边界算法修复：改为"稳定区低 skip 边界"（commit ccb2775），返回 skip=7
- [x] `--dataset-root` CLI 参数（capture / launch / survey 都支持）
- [x] 目录结构：`DATASET_ROOT/<game_name>/<tag>/`（原为平铺 `<game>_<tag>/`）
- [x] survey 目录：`DATASET_ROOT/<game_name>/survey/`
- [x] 所有 `--mode` 默认值统一为 `custom`
- [x] CLAUDE.md 更新：修正架构描述，补充 pre-UI / sidecar / survey 文档

## Not Yet Done

- [ ] **实机验证推荐 skip=7**：算法推荐值正确，需目视确认 skip=7 帧无 UI
- [ ] **精细扫描**（可选）：`--survey-step 1` 在 skip 2~12 范围精确定位边界
- [ ] **验证 EXR 深度**：`use_scene_rt` 路径的深度拷贝未实机确认；检查每帧是否有对应 `.exr`
- [ ] Batman AK 适配（本次工作集中在 FF7 Remake）

## Failed Approaches (Don't Repeat These)

1. **survey 边界算法：全局最大差分**（commit 018775a → 修复于 ccb2775）
   返回了 skip=52（帧图像是粉色/紫色破帧）。原因：全局最大差分命中"主渲染区"中间（光照/几何突然出现），而非 UI 合成点。
   **修复**：改为找"稳定区低 skip 边界"：threshold=3×中位差，分稳定/不稳定段，排除上半段（极早期空场景），取剩余稳定段最小 s_lo。

2. **`--survey-max` 参数**（已删除于 018775a）
   需要用户手动估计最大 skip。addon 在每次 survey 帧时写出 `fc_pass_total.txt`，Python 自动读取，无需该参数。

3. **旧版 pre-UI 的失败方案**（从更早 handoff 继承）
   - 在 `reshade_present` 时拷贝游戏 RT → GPU TDR 崩溃（UE4 transient resource aliasing）
   - Forward-skip of BB binds → 拷到的是上一帧残留
   - UIRemove_ColorTex fallback（begin_effects 触发太晚）
   - `decode_to_rgba8` default 分支 memcpy HDR RT（暗噪点）

## Key Decisions

| Decision | Rationale |
|----------|-----------|
| 稳定区低边界算法 | FF7 Remake 渲染三段：早期空→主渲染→后处理+UI；只有第三段末尾才合成 UI，差分远小于主渲染段 |
| sidecar 读取在 on_reshade_present（1-frame lag） | Present 后读取，skip 更新从下一帧 on_bind_rts_dsv 生效；Python 等待 ≥2.5× 采集间隔规避 |
| fc_pass_total.txt 仅 survey 模式写出 | `s_no_dsv_non_bb` 在 Present 时已确定；普通采集不写该文件 |
| 文件名含 skip 值 | `survey_skip_NNN_BackBuffer.bmp` 让 Python 按名轮询，不依赖文件时间戳或顺序 |
| DATASET_ROOT/<game>/<tag>/ | 按游戏分类，每次会话独立目录，便于多游戏并行 |

## Current State

**Working**:
- survey 扫描正常运行（实测 FF7 Remake：73 pass，16 个扫描点，推荐 skip=7）
- addon 动态读取 skip sidecar，写出 pass total
- 颜色/光照正确，无 GPU TDR 崩溃
- 目录结构正确
- dist/frame_capture.addon 已重编（含 survey 模式，HDR decode，depth EXR）
- CLAUDE.md 已更新为当前架构

**Broken / Pending**:
- skip=7 正确性未目视确认（图像内容是否无 UI）
- EXR 深度：代码已加，未实机验证

**Uncommitted Changes**: 仅本文件（HANDOFF.md）未提交

## Files to Know

| File | Why It Matters |
|------|----------------|
| `reshade-addons/99-frame_capture/frame_capture.cpp` | survey sidecar 读写、reverse-skip、HDR decode、depth EXR |
| `tools/capture/survey.py` | survey 扫描逻辑、边界算法 `_find_boundary` |
| `main.py` | CLI 入口：survey / capture / launch / deploy 子命令 |
| `tools/capture/config.py` | 机器相关路径：GAME_PATH、DATASET_ROOT |
| `dist/frame_capture.addon` | 已编译的 addon 二进制（本次已重编） |

## Code Context

**Survey sidecar 协议（C++ 侧，on_reshade_present）：**
```cpp
// fc_skip_count.txt → 每帧读取，更新 g_pre_ui_skip（下一帧起生效）
// fc_pass_total.txt → survey 模式时写出 s_no_dsv_non_bb（当帧非 BB pass 总数）
// fc_output_dir.txt → 采集输出目录（survey 写入 survey_dir）
// 文件名：survey_skip_NNN_BackBuffer.bmp（N = this_frame_skip，本帧实际使用的 skip 值）

uint32_t this_frame_skip = g_pre_ui_skip;  // 本帧已用的 skip
// ... 读 fc_skip_count.txt，更新 g_pre_ui_skip（下帧用）...
if (s_survey_mode) {
    char sn[32]; sprintf_s(sn, "survey_skip_%03u_", this_frame_skip);
    save_prefix = out_dir / sn;
}
if (s_survey_mode && s_no_dsv_non_bb > 0) {
    std::ofstream tf(exe_fs.parent_path() / L"fc_pass_total.txt", std::ios::trunc);
    tf << s_no_dsv_non_bb << '\n';
}
```

**边界算法（survey.py `_find_boundary`）：**
```
FF7 Remake pass 分布（total=73，step=5 扫描的实测数据）：
  skip 72→52: 差分 0.38~0.93 (极早期空场景段，排除)
  skip 52→27: 差分 13~69   (主渲染区，排除)
  skip 27→7:  差分 1.1~2.7  (稳定后处理区，无 UI)  ← 推荐 skip 在此段底部
  skip 7→0:   差分 9.7~12.9 (UI 合成区)

算法：threshold = max(3× 中位差分, 3.0)
      稳定段 = 连续 d<threshold 的相邻对
      排除 max(s_hi) >= mid 的段（上半段）
      取剩余段中 min(s_lo) 最小的，其最小 s_lo = 推荐 skip
      FF7 Remake → skip=7 (pass 65，UI 从 pass 67 起合成)
```

**目录结构：**
```
DATASET_ROOT/
  ff7remake_/
    20260430_174317/   ← launch/capture 会话
      frames/
      inputs.jsonl
      dataset.h5
      video.mp4
    survey/            ← survey 扫描帧（固定子目录）
      survey_skip_000_BackBuffer.bmp
      survey_skip_007_BackBuffer.bmp
      ...
```

**部署命令（当前推荐 skip=7）：**
```powershell
uv run main.py deploy --mode custom --pre-ui --pre-ui-skip 7

# 或直接 launch
uv run main.py launch --mode custom --pre-ui --pre-ui-skip 7 --fps 30 --duration 30
```

**unicap.ini 关键配置（写入 %TEMP%\unicap\unicap.ini）：**
```ini
[ADDON]
FC_PreUICapture    = 1
FC_PreUISkipCount  = 7       ← survey 推荐值
FC_TargetFPS       = 30
FC_ExportDepth     = 1
[INPUT]
KeyOverlay         = 0,0,0,0
```

## Resume Instructions

**目标：验证 skip=7 无 UI，确认 EXR 深度正常**

1. 确认游戏已关闭（防止 addon 文件被锁定）

2. 验证推荐 skip=7：
   ```powershell
   uv run main.py launch --mode custom --pre-ui --pre-ui-skip 7 --fps 5 --duration 10
   ```
   - 期望：`D:\ff7_dataset\ff7remake_\<tag>\frames\` 内的 BMP 无 HUD/UI
   - 若仍有 UI：做精细扫描 → `uv run main.py survey --no-launch --survey-step 1`
   - 若图像变黑/不完整：skip 太大，试 skip=5 或 skip=3

3. 验证 EXR 深度（use_scene_rt 路径）：
   ```python
   import glob
   exrs = glob.glob(r"D:\ff7_dataset\ff7remake_\*\frames\*.exr")
   print(f"{len(exrs)} EXR files")
   # 期望：每个 BMP 对应一个 EXR
   ```
   - 若 0 EXR：检查日志 `%TEMP%\unicap\unicap.log` 是否有 `FC: failed to create depth staging (scene_rt)` 或 `DepthToAddon_ExportTex` 是否出现在 `FC: listing all effect texture variables`

4. 精细扫描（如需要）：
   ```powershell
   # 游戏需已运行并在采集状态
   uv run main.py survey --no-launch --survey-step 1
   ```
   扫描 skip 0~72（step=1），自动报告精确边界并写入 unicap.ini。

## Setup Required

- VS 2022 Build Tools（重编 addon 时需要：`scripts\build.ps1`）
- `uv sync`（Python 依赖：opencv-python, h5py, numpy）
- FF7 Remake: `E:\games\ff7remake\End\Binaries\Win64\ff7remake_.exe`
- 日志: `%TEMP%\unicap\unicap.log`

## Warnings

- **不要在 reshade_present 时拷贝游戏 RT**：UE4 transient resources 在 Present 后 alias 释放，会触发 GPU TDR。拷贝在 `on_bind_rts_dsv` BB bind 事件中完成（已有）。
- **barrier 状态必须用 `shader_resource`**：final composite pass 把 scene RT 作为 SRV 读取后转 BB，此时 RT 处于 SR 状态。
- **1-frame lag**：`fc_skip_count.txt` 在 on_reshade_present 读取，更新的 skip 从下一帧生效。survey.py 已用 `wait_per_skip = max(2.5 × capture_interval, 2.0)` 补偿。
- **survey 模式检测**：`s_survey_mode` 由 `fc_skip_count.txt` 是否存在且非空决定；删除或清空该文件即退出 survey 模式。
- **`fc_pass_total.txt` 仅 survey 模式写出**：普通采集不写该文件。
- **fmt=10 = r16g16b16a16_float**：FF7 中间 RT 格式，`decode_to_rgba8` 已处理（half_to_float + Reinhard + sRGB gamma）。
- **不要改 `reshade-addons/deps/reshade/include` 包含路径**：addon 用 v5 wrapper API，与 official592 dxgi.dll 二进制兼容。
- **dist/dxgi.dll 不部署**：由 reshade/ (6.7.3 UNOFFICIAL) 构建，R10G10B10A2 swap chain 下 BMP 错误。两种工作模式（custom / official592）都部署 `vendor/reshade592/dxgi.dll`。
