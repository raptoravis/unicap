# Handoff: 简化 CLI + F6/F8/F9 in-game 工作流

**Generated**: 2026-05-01
**Branch**: master（含未提交改动）
**Status**: In Progress — 代码 + addon + shader 已重编并实测加载，剩待实机走完 F6→F8→F9 全流程

## Goal

把 unicap 从"main.py 一堆 CLI 参数"改成"游戏内 F6/F8/F9 热键驱动"。`launch` 自动 deploy + 启动游戏，进入交互循环：F6 触发 survey、F8 触发 capture（无 survey 推荐值时先自动 survey）、F9 停止当前 phase。游戏内有彩色横条作为视觉状态指示，控制台同步打印操作提示。

## Completed

- [x] **`main.py launch` 简化**：12 个参数 → 5 个（`--mode`, `--game-path`, `--game-name`, `--dataset-root`, `--hints/--no-hints`）。`CAP_FPS=30 / CAP_WIDTH=1600 / CAP_HEIGHT=1200` 是模块级常量。
- [x] **CLI 子命令精简**：删 `deploy` / `capture` / `survey` 入口（这些函数仍是 launch 的内部 helper）。顶层只剩 `launch / video / pack`。
- [x] **F6/F8/F9 交互循环**（`_interactive_loop`）：用 `GetAsyncKeyState` 全局轮询，游戏前台时也工作。F8 检测 `recommended_skip.txt` 缺失时自动链式 survey → capture。
- [x] **`capture_all.run` 接 `stop_event`**：F9 触发即停。
- [x] **`survey_mod.run` 接 `abort_event`**：F9 中止；中止跳过分析、不写 recommended_skip.txt。
- [x] **survey 后 skip 立即生效**：`_write_skip_pulse` 把推荐值写入 `fc_skip_count.txt` ≥2 帧再清，让 addon 的 `g_pre_ui_skip` 落到 recommended，无需重启游戏。
- [x] **状态 sidecar 协议**：Python 写 `fc_state.txt`（idle/surveying/capturing）+ `fc_hints.txt`（1/0）；addon 每帧读取。
- [x] **In-game 视觉指示**：新增 `shaders/CaptureStatus.fx` —— 屏幕顶部居中 240×14 像素彩条，蓝=surveying，红=capturing，idle 不绘制。addon 通过 `set_uniform_value_int` 推 `Status_State` 给 shader。
- [x] **Addon overlay 增强**（按 Home 可见）：顶部彩色状态条 + `[F6/F8/F9]` 热键说明 + 当前 skip 值（受 `s_show_hints` 控制）。
- [x] **重新构建**：`scripts/build.ps1` 跑通；`dist/frame_capture.addon` 已更新；`dist/reshade-shaders/Shaders/CaptureStatus.fx` 已 staging。
- [x] **CaptureStatus.fx 加载已验证**：`%TEMP%\unicap\reshade-CaptureStatus-*.cso` 在 13:45 实测出现，证实 ReShade 编译并加载了新 shader。
- [x] **CLAUDE.md 更新**：新 Run 段、热键表、扩展 sidecar 协议、新增 "Runtime logs" 节记录 `%TEMP%\unicap\unicap.log{,1}` 用途。
- [x] **survey 错误信息改进**：未读到 fc_pass_total.txt 时输出"游戏不在 3D 场景"提示。

## Not Yet Done

- [ ] **走通 F6 全流程**：用户在 3D 关卡按 F6 → survey 应能扫到 `s_no_dsv_non_bb > 0`，写出 recommended skip。上一轮上次实测在标题/菜单按 F6，had_depth 全 0 而失败。
- [ ] **目视确认蓝/红横条出现**：CaptureStatus.fx 已加载（cache 文件存在），但实测时 surveying/capturing 期间是否真画出来还没看到。
- [ ] **F8 链式 survey→capture**：未单独验证。
- [ ] **F9 停止 + 自动 pack**：未单独验证。
- [ ] **EXR 深度仍未实机确认**（沿用更早 handoff）。

## Failed Approaches (Don't Repeat These)

1. **想让 ReShade overlay always-on 显示提示**
   `register_overlay()` 注册的 callback 只在 ReShade 主面板打开（按 Home）时被绘制。addon API 不暴露 always-on overlay。
   → 改用：自定义 shader（`CaptureStatus.fx`）画屏幕角条 + Python 控制台同步打印 + 现有 ReShade overlay tab 加 hints（按 Home 可见，作为补充）。

2. **`fc_skip_count.txt` 删除后 g_pre_ui_skip 残留为最后扫描值**
   survey 结束直接 `_clear_skip` 会让 addon 的 `g_pre_ui_skip` 停在最后扫描的 skip（如 step=5 时是 2），不是 recommended（如 7）。
   → 改用：`_write_skip_pulse(recommended)` 写 recommended 到 sidecar，sleep 2 帧让 addon 读到，再删除文件。pulse 期间 addon 会写一帧 `survey_skip_NNN_BackBuffer.bmp`（无害，Python 不读）。

3. **survey 在游戏未进 3D 时按 F6**（用户实测踩中）
   FF7R 标题画面 / loading / cutscene 没有 DSV-bound 渲染 → addon 的 `s_had_depth_pass` 永远不变 true → `s_no_dsv_non_bb=0` → addon 不写 `fc_pass_total.txt` → Python "未读到 fc_pass_total.txt" 失败。
   → 不是代码 bug，是用户操作时机问题。已加错误提示文案。

## Key Decisions

| Decision                                              | Rationale                                                                          |
| ----------------------------------------------------- | ---------------------------------------------------------------------------------- |
| Python 端 `GetAsyncKeyState` 轮询热键，不在 addon 加键盘钩子          | 全局键状态，游戏前台焦点时也能读；保持 addon 单一职责（只做帧采集 + 状态读取）；不用碰 ImGui input flow。            |
| `fc_skip_count.txt` 双重职责（survey 模式 + post-survey 一次性脉冲）       | 不引入新 sidecar；pulse 短暂留一帧 survey 文件名也无碍。                                            |
| `fc_state.txt` / `fc_hints.txt` 独立                    | state 频繁变（Python 主动写），hint 静态（启动时一次）；分开避免每帧覆盖。                                       |
| `CaptureStatus.fx` 用整数 uniform + 简单矩形判定                 | 不引入字体纹理；颜色条够用且性能开销可忽略；技术列表里 sort 在最后，不影响 UIRemove_ColorTex 抓取的图像。              |
| 删除 `deploy` / `capture` / `survey` 子命令               | 用户明确要求"参数太多太复杂"。这些功能都是 launch 的子环节，不需要单独入口。helper 函数保留以备 launch 内部调用。     |
| `cmd_deploy` 函数保留为 helper，仅删 CLI 入口                  | launch 内部仍依赖；删 CLI 不删函数。                                                     |
| 不改 `tools/capture/config.py` 默认路径                | 用户明确说："通过参数指定的"。机器特定路径用 `--game-path` 覆盖。                                            |

## Current State

**Working** (代码层面):
- 编译通过：addon (`dist/frame_capture.addon` 202240 bytes) + 4 个 staged shaders (`DepthToAddon.fx` / `UIRemove.fx` / `CaptureStatus.fx` / `ReShade.fxh`)
- Python `py_compile` OK
- `uv run main.py --help` 显示 `{launch, video, pack}` 三个子命令
- ReShade 实测加载 CaptureStatus.fx（cache 文件出现）

**Pending verification** (实机):
- 进 3D 关卡按 F6 是否能扫出 pass 总数（旧 log 总是 had_depth=0，因为按时机太早）
- 蓝/红横条是否真的画到屏幕上
- F8 链式 survey→capture 与 F9 停止
- 自动 pack（capture_all.run 后调 pack_hdf5.pack）

**Uncommitted Changes**:

```
modified:   CLAUDE.md
modified:   CMakeLists.txt
modified:   HANDOFF.md
modified:   dist/frame_capture.addon
modified:   main.py
modified:   reshade-addons/99-frame_capture/frame_capture.cpp
modified:   scripts/build.ps1
modified:   tools/capture/capture_all.py
modified:   tools/capture/survey.py

Untracked files:
        dist/reshade-shaders/Shaders/CaptureStatus.fx
        shaders/CaptureStatus.fx
```

## Files to Know

| File                                                | Why It Matters                                                                                         |
| --------------------------------------------------- | ------------------------------------------------------------------------------------------------------ |
| `main.py`                                           | 全部交互循环 + sidecar 写入 + F9 watcher。`_interactive_loop` / `_run_survey` / `_run_capture` / `_write_skip_pulse` 都在这。约 360 LoC。 |
| `tools/capture/survey.py`                           | `run(..., abort_event=...)`：F9 中止；写 `recommended_skip.txt`；中止时跳过分析。                                          |
| `tools/capture/capture_all.py`                      | `run(..., stop_event=...)`：F9 触发的 event 即停。                                                            |
| `reshade-addons/99-frame_capture/frame_capture.cpp` | 新增 `s_state` / `s_show_hints` + sidecar 读取 + `Status_State` uniform 推送 + overlay 提示                       |
| `shaders/CaptureStatus.fx`                          | 屏幕顶部彩条；`Status_State` 整数 uniform 控制（0 hide / 1 blue / 2 red）。预设 `_ensure_preset` 自动加入 technique 列表。              |
| `dist/frame_capture.addon`                          | 已重编含本轮所有改动（202240 bytes，比上一版多 1536 字节）                                                                |

## Code Context

**Sidecar 协议（已扩展）**：

```
fc_output_dir.txt   Python → C++  采集帧输出目录
fc_skip_count.txt   Python → C++  survey 模式 skip 值；survey 结束时也用作 post-survey skip 注入脉冲
fc_pass_total.txt   C++ → Python  当帧 s_no_dsv_non_bb（非 BB 非 DSV pass 数）
fc_state.txt        Python → C++  "idle" / "surveying" / "capturing"  ← 新
fc_hints.txt        Python → C++  "1" / "0" 控制 overlay + 颜色条       ← 新
```

**Python 状态机（`main.py:_interactive_loop`）**：

```python
while True:
    _set_state(game_dir, "idle")
    key = _wait_for_keys([VK_F6, VK_F8])
    if key == VK_F6:
        _run_survey(args, game_dir, game_name, dataset_root)
    elif key == VK_F8:
        if _load_recommended_skip(dataset_root, game_name) is None:
            _run_survey(...)            # 自动链式
        _run_capture(game_dir, game_name, dataset_root, just_surveyed=...)
```

**F9 watcher（每个 phase 单独 spawn）**：

```python
def _spawn_f9_watcher(stop_event: threading.Event) -> threading.Event:
    """Returns quit_evt — phase 结束时 set 这个释放 watcher。"""
    quit_evt = threading.Event()
    def watcher():
        _drain_keys([VK_F9])
        while not quit_evt.is_set() and not stop_event.is_set():
            if _key_down(VK_F9):
                stop_event.set(); return
            time.sleep(0.05)
    threading.Thread(target=watcher, daemon=True).start()
    return quit_evt
```

**Addon → shader 状态推送（`on_begin_render_effects`）**：

```cpp
if (sbi.status_state_uniform.handle == 0)
    sbi.status_state_uniform = runtime->find_uniform_variable(
        "CaptureStatus.fx", "Status_State");
if (sbi.status_state_uniform.handle != 0) {
    int32_t v = 0;
    if (std::strcmp(s_state, "surveying") == 0) v = 1;
    else if (std::strcmp(s_state, "capturing") == 0) v = 2;
    if (!s_show_hints) v = 0;
    runtime->set_uniform_value_int(sbi.status_state_uniform, &v, 1);
}
```

**Shader 关键判定（`shaders/CaptureStatus.fx`）**：

```hlsl
if (Status_State == 0) return col;   // idle: passthrough
const float bar_w = 240.0, bar_h = 14.0, pad_top = 16.0;
float2 origin = float2((BUFFER_WIDTH - bar_w) * 0.5, pad_top);
// 在矩形内填色：1=蓝, 2=红；矩形外原样返回
```

## Resume Instructions

> **关键前提**：FF7R 实际安装路径是 `E:\games\ff7remake\3DMGAME_Final_Fantasy_VII_Remake.CHS.Green.part001\Final Fantasy VII Remake Intergrade\End\Binaries\Win64`，**不是** `config.py` 默认的短路径。每次 launch 都要传 `--game-path`。

1. 关掉游戏；清掉旧日志看新 log 更直观（可选）：

   ```powershell
   Remove-Item "$env:TEMP\unicap\unicap.log*"
   ```

2. 启动：

   ```powershell
   uv run main.py launch --game-path "E:\games\ff7remake\3DMGAME_Final_Fantasy_VII_Remake.CHS.Green.part001\Final Fantasy VII Remake Intergrade\End\Binaries\Win64"
   ```

   - 期望终端输出 5 行操作提示框 + `[等待] 按 F6 = survey  F8 = 采集`
   - 期望 `%TEMP%\unicap\unicap.log1` 出现 `Successfully compiled '...CaptureStatus.fx'`

3. **进入 3D 关卡**（角色可移动、明显是 3D 场景），再按 F6：
   - 期望：屏幕顶部出现蓝色横条
   - 期望：终端 `[SURVEY] Phase 1: 探测帧…` → `Phase 2: 共 N 个非 BB pass…` → `推荐 skip = X`
   - 期望：横条变回隐藏；写出 `D:\ff7_dataset\ff7remake_\survey\recommended_skip.txt`
   - 失败时检查 `unicap.log1` 中 `FC: capf<N> had_depth=?`：若全 0，仍是没进 3D 渲染。

4. 按 F8：
   - 已有 recommended → 直接进 capture（红条出现）
   - 按 F9 → 红条消失，自动 pack HDF5

5. 加 `--no-hints` 重启验证关闭逻辑：横条不显示，但 F6/F8/F9 仍工作。

## Setup Required

- VS 2022 Build Tools（rebuild 用 `scripts\build.ps1`）
- `uv sync`（Python 依赖：opencv-python, h5py, numpy）
- FF7 Remake at 长 3DMGAME 路径
- 日志：`%TEMP%\unicap\unicap.log{,1}`（详见 CLAUDE.md "Runtime logs" 节）

## Edge Cases & Error Handling

- **F6 时游戏不在 3D 场景** → addon `s_no_dsv_non_bb=0`，不写 fc_pass_total.txt，Python 4 秒后失败 + 提示"请进入 3D 场景"。
- **F8 时 survey 已经做过** → 跳过 survey，直接进 capture。
- **F8 触发的自动 survey 失败** → 不进 capture，回到 IDLE 等待。
- **F6/F8 在 SURVEYING/CAPTURING 期间被按** → 当前在 phase 内不会响应（phase 退出前 watcher 只看 F9）；phase 结束回 IDLE 才重新接 F6/F8。
- **`--no-hints` 关闭** → addon 写 `Status_State=0`（隐藏横条），ReShade overlay tab 也不显示状态行；控制台输出仍打印（属"操作记录"不属"提示"）。
- **`fc_skip_count.txt` 文件锁失败** → 只 `print` 警告不抛异常。

## Warnings

- **F6/F8/F9 是 Python 用 `GetAsyncKeyState` 全局轮询的**，addon 不参与。游戏窗口需能接收键盘焦点；如游戏吃掉某个 F 键，改 `main.py` 顶部 `VK_F6/F8/F9` 同时改 overlay 文本与控制台提示。
- **F9 watcher 在每个 phase 单独 spawn，phase 退出 `quit_evt.set()`**，避免 capture 结束后还有 watcher 抢 F9。
- **`fc_skip_count.txt` 现在双重职责**（survey + post-survey skip pulse）。pulse 期间会写一帧 `survey_skip_NNN_BackBuffer.bmp`，紧接着删除文件即恢复正常文件名。
- **不要在 `reshade_present` 时拷贝游戏 RT**（沿用旧约束）。
- **dist/dxgi.dll 不部署**（沿用）；`--mode custom` 实际通过 `dist/dxgi.dll` 路径返回（CLAUDE.md 说 6.7.3 BMP 错误，二者矛盾——但本轮没动这块，沿用既有行为）。
- **不要改 `tools/capture/config.py`**：用户明确要求 CLI 参数覆盖，不动默认值。
- **`murchFX/Shaders/`** 是 sibling FX 库（含自带 DepthToAddon 副本），运行时**不**加载它；运行时 `EffectSearchPaths = D:\dev\unicap.git\shaders`。
- **`reshade-addons/deps/reshade/include` 是 v5 wrapper API**，与 vendor/reshade592 dxgi.dll 二进制兼容；不要换路径。
