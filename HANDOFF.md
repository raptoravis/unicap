# Handoff: Vulkan 后端 + UE4 嵌套识别 + pack 重设计 + barrier mode 实验性退役

**Generated**: 2026-05-02 12:30
**Branch**: master（与 origin/master 同步，working tree clean）
**Status**: Done — FF7R / Batman AK / DOOM Eternal 三游戏实机回归通过（用户原话"完美"），已 merge 到 master + push

## Goal

把 unicap 从 DX-only 扩展到能跑 Vulkan-only 游戏（DOOM Eternal 等 id Tech 7），途中重新审视 pack 路径的 UI mask 设计，简化交互（删 F6），修一堆边角 bug。

## Completed

### Vulkan 后端支持 (commit `d842307`)
- [x] **dist/UniCap64.{dll,json}** —— Vulkan implicit layer，DLL bytes 同 dxgi.dll（源 reshade_core MSBuild 产物），命名去 ReShade 品牌
- [x] **HKCU\\Software\\Khronos\\Vulkan\\ImplicitLayers** 注册作主路径（Steam env-strip 兜底）
- [x] **三层 cleanup**：atexit + signal handlers (SIGINT/SIGBREAK + Win32 SetConsoleCtrlHandler) + 启动时扫描 stale 残留
- [x] **env vars 兜底**：VK_IMPLICIT_LAYER_PATH + VK_INSTANCE_LAYERS + VK_LAYER_PATH 三件套（loader 1.3.234+ 优先，老 loader fallback）
- [x] **写 game_dir/unicap.ini** 重定向 `[INSTALL] BasePath` → `%TEMP%\unicap\` —— 绕过 ReShade `dll_main.cpp:131` 对非 d3d/dxgi 命名的强制配置存在性检查（被 Steam 剥光 RESHADE_BASE_PATH_OVERRIDE env var 时这是唯一通路）
- [x] **--api {auto,dx,vulkan}** flag，auto 按 exe 名启发（含 `vk`/`vulkan` 子串 → vulkan）
- [x] **DX 路径完全零回归**

### 关键工程改动
- [x] **F8 一键流，删 F6** (commit `b27a062`)：F8 首次自动 survey；重 survey 删 `dataset/<game>/survey/recommended_skip.txt`
- [x] **UIRemove.fx → BackBufferExport.fx** (commit `2818dfd`)：旧名误导（实际只做 BackBuffer 拷贝、不 mask UI）；texture/technique/preset 全同步重命名
- [x] **staging recreation 加 fmt 比较** (commit `0713ba7`)：DOOM Eternal HDR↔LDR 帧间格式切换 driver hang 修复（FF7R/Batman 之前未暴露因为单一格式）
- [x] **UE4 嵌套 exe 自动检测** (commit `717c1c1`)：launcher exe + Binaries\\Win64\\inner.exe 结构自动 walk down
- [x] **pack 三个独立 flag** (commit `4c20bb4`)：`--color {no-ui,ui}` / `--depth` (默认开) / `--normal` (默认关)
- [x] **video --mask-ui** (commit `6e32581` + `c2d8aca`)：用 depth EXR 在 video_masked.mp4 里 mask UI/sky 像素（depth==0|>=0.999），仅视觉验证用，不影响 BMPs/HDF5

### 实机回归通过
- [x] FF7R Remake (UE4 / DX12) — render-pass 模式 survey + capture
- [x] Batman Arkham Knight (DX) — render-pass 模式
- [x] DOOM Eternal (Vulkan) — `--ui-mode ui --color ui` 路径，HKCU layer 注入

## Not Yet Done

- [ ] **暂无主线遗留任务**
- [ ] (可选) `vulkan-support` 分支退役：用户合并后未清理本地 / origin remote 分支
- [ ] (可选) UI mask 改善：DOOM Eternal HUD 是 3D 几何（depth ~0.001-0.01），depth 阈值分不开 HUD 与近景物体；当前 `--mask-ui` 只去 sky。要彻底干掉 HUD 需要 color-based + region-based 双重 mask（半小时工作，但用户决定 ML 模型自学忽略 HUD 即可，不做）

## Failed Approaches (Don't Repeat These)

### 1. 实验性 barrier mode (`on_barrier` hook) — DOOM Eternal compute pipeline 不稳定

DOOM Eternal id Tech 7 用 compute shader 写 scene RT，**不走 render pass 模型** → 现有 `on_begin_render_pass` 只在 HUD 合成时触发，pre-UI scene RT 取不到。我尝试 hook `addon_event::barrier`，捕 `(render_target | unordered_access) → shader_resource` transition 那一刻 GPU copy。

走过的弯路（每个都 commit 然后 revert）：

1. **wrong source state** (commit `bf51a5a`)：以为 event 在 trampoline 之前触发 → 用 old_state 做 barrier source。实际 `vulkan_hooks_command_list.cpp:939` 是先 trampoline 后 fire event → 资源已是 new_state。GPU 崩溃，DOOM 报"stopped working"。
2. **加 UAV→SR transition** (commit `9c88f3b`)：扩 filter 接受 compute writes。但相关问题没解决。
3. **format whitelist** (commit `283d0a0`)：第一次能采到 BMP 后发现是 r8_unorm（5%）= SSAO mask buffer，不是 scene RT。加白名单只接受多通道 color formats。
4. **staging fmt mismatch** (commit `0713ba7`)：DOOM Eternal alternates r11g11b10_float (HDR) ↔ r8g8b8a8_unorm (LDR)，staging 不重建 → vkCmdCopyImage format mismatch → driver hang → 主菜单 freeze。
5. **dry-run 验证 hook 本身没问题** (commit `7b8476f`)：跳过 GPU 操作只 log 候选。诊断显示每帧 2 个候选 (idx=0 HDR, idx=1 LDR)，hook 工作正常。
6. **加上正确的 barrier sequence + 修 fmt 还是 freeze**：即使 SR 作 source、staging 加 fmt 比较，DOOM Eternal 依然 freeze。怀疑深层问题：id Tech 7 多线程 cmd-buffer recording + transient memory aliasing + 我们在 on_barrier 内部插入额外 cmd 干扰命令流。深度 Vulkan debug 半天到一天起，**收益 < 成本**。
7. **revert (commit `6e32581`)**：保留独立改进（staging fmt fix, F6 删除, BackBufferExport 重命名），删除所有 barrier-specific 代码（on_barrier handler, FC_CaptureMode/FC_BarrierDryRun config, --capture-mode/--barrier-dry-run flags）。

**教训**：在 ReShade `addon_event::barrier` 内做 GPU copy 是反模式 —— 该 event 是事后通知（post-trampoline），且对 compute-heavy 引擎风险极大。下次想抓 compute write，应该 hook `addon_event::dispatch` 直接管命令录制阶段。

### 2. depth-based UI mask 在 pack 路径 — 引擎相关、效果不一致

最初方案：pack_hdf5 在打 HDF5 时按 depth==0 mask UI 像素置黑。结果发现：

- 旧代码用 `depth == 0.0`，但 DepthToAddon.fx 导出 LINEARIZED depth + reverse-Z flip → UI 像素其实在 1.0（far）端。**FF7R/Batman 之前的所有 HDF5 数据，理论上 ui_mask_avg_px 都是 0**（mask 没生效，但用户没发现）
- 修成 `depth <= 0 | depth >= 0.999` 后，UE4 引擎能 mask UI（HUD 是 2D overlay，无深度）+ sky
- **但 DOOM Eternal HUD 是真 3D 几何**（小三角面绘制在近平面 depth 0.001-0.01），depth 阈值分不开 HUD 和武器/手部 → mask 啥也抓不到

最终方案 (commit `4c20bb4`)：**pack 路径完全移除 UI mask**。HDF5 `/color` 是原 BMP 内容，`/depth` 完整保留。让消费方（训练管线）自己决定要不要 mask。`video --mask-ui` 仅作为视觉验证工具单独存在。

### 3. ali213 破解版 DOOM 2016 测试 — 本身就跑不起来

用户最初想用 DOOM 2016 (`E:\games\doom2016\DOOMx64vk.exe`) 测 Vulkan，结果发现：
- 该游戏是 ali213 破解版（`ali213.bin` 文件特征 + `开始游戏.exe` 中文 launcher）
- DOOMx64vk.exe 直接启动会秒退（破解 stub 没初始化）
- 通过 `开始游戏.exe` 启动跑的是 DOOMx64.exe (DX11 渲染器) 而非 vk 版本
- 这游戏 install 在用户机器上根本不在 Vulkan 模式下运行

**改用 DOOM Eternal (`E:\games\doom\DOOMEternalx64vk.exe`) 才有可测的 Vulkan target**。教训：先用 Process Explorer / tasklist 确认游戏进程实际在跑、加载了哪些模块，再下结论。

### 4. UE4 嵌套结构 deploy 错位 — FF7R 临时退化

某次 FF7R 测试时用户传了**外层 launcher path** 而不是内层 exe (`Intergrade\End\Binaries\Win64\ff7remake_.exe`)：
- Python deploy dxgi.dll 到 launcher 旁的 `Intergrade\`
- launcher 进程加载 dxgi.dll, 3 秒后退出
- 实际 game 在 `End\Binaries\Win64\` 启动，加载该目录下自己的旧 dxgi.dll（5 月 1 日残留）
- addon 读 sidecar 在 `End\Binaries\Win64\`，Python 写 sidecar 在 `Intergrade\` → 两侧目录不一致 → survey timeout

修复 (commit `717c1c1`)：`_resolve_game_path` 加 `_ue4_nested_exe()` 检测，若 path 不在 Binaries 内但其下有 `**/Binaries/Win64/*.exe`，自动改用内层最大的 exe + 提示用户。

## Key Decisions

| Decision | Rationale |
|----------|-----------|
| Vulkan layer 走 HKCU 而非纯 env var | Steam 重启游戏时剥环境变量 → env-only 方案对 Steam 游戏静默失败。HKCU 不依赖 process tree env propagation |
| DLL/manifest 命名 `UniCap64`（PascalCase） | 用户明确要求"去 ReShade 字样使用 UniCap"。匹配项目其他大写惯例（用户 PR 里的命名风格） |
| Layer 注册带可靠 cleanup（atexit + signal + 启动 scan） | HKCU 是全局副作用，泄漏会让用户机器上**所有** Vulkan 程序都被这层 layer hook → 必须保证清理 |
| 移除 pack 路径 depth-based UI mask | id Tech 7 的 HUD 是 3D 几何，depth 阈值方案失效；UE4 引擎 sky 误伤；引擎特定的 mask 不该在通用 pack 里硬编码 |
| 保留 `video --mask-ui` 作为视觉验证 | 用户明确说想"看一眼 mask 效果"。video 路径是装饰性的、跟训练数据 pipeline 解耦，加进去无副作用 |
| `--bmp` 改名 `--color` | 用户要求。语义更清晰（"哪种 color BMP 进 /color"），且与 `--ui-mode` 用语一致 |
| `--depth` / `--normal` 拆成独立 flag | 之前 `--depth` 同时控制两个数据集是历史遗留；normal 默认关（很少用、占空间大） |
| F8 删除 F6 hotkey | 用户：F8 已自动跑首次 survey，F6 完全冗余 |
| revert 实验性 barrier mode | 见 Failed Approaches #1。深度 Vulkan debug 不值得；DOOM Eternal 通过 `--ui-mode ui` + 模型自学忽略 HUD 已可用 |
| UE4 嵌套自动检测 | UE4 launcher 模式很常见，让用户被坑一次就够了 — auto-fix 比 documenting limitation 强 |

## Current State

**Working**:
- master HEAD = `dbee142` (merge commit, 已 push)
- FF7R / Batman AK 走 DX 路径（`--api auto` 默认 dx）：survey + capture + pack 全 OK
- DOOM Eternal 走 Vulkan 路径（HKCU layer 自动注入），`--ui-mode ui --color ui` 推荐工作流
- `dist/` 全部产物 up-to-date：`dxgi.dll`、`UniCap64.{dll,json}`、`frame_capture.addon`、`unicap-shaders/Shaders/*.fx`
- `--mask-ui` 在 video 路径上正确 mask reverse-Z UI/sky 像素（DOOM Eternal 5% / FF7R 多少看场景）
- 版本号 1.0.0 → 1.0.2

**Broken**:
- 无（unicap 主线全 OK）

**Out-of-scope（设计边界）**:
- 含 ali213 / 类似破解 stub 的游戏：直接启动 inner exe 会秒退，需要走破解 launcher（unicap 无法干预）
- DOOM 2016 这台机器装的破解版只跑 DX11 模式（DOOMx64vk.exe 启动失败），不能用来测 Vulkan
- DOOM Eternal HUD 完全干净化：要 color/region-based mask（未做，用户决策）

**Uncommitted Changes**: 无（working tree clean）

## Files to Know

| File | Why It Matters |
|------|----------------|
| `main.py` | 主控制器；新增 `_resolve_api`/`_vk_register_layer`/`_vk_unregister_layer`/`_vk_clean_stale_entries`/`_ue4_nested_exe`/`_apply_ui_mask_bgr`；命令 launch/video/pack 的 argparse 都改 |
| `tools/capture/pack_hdf5.py` | pack 函数签名 `pack(..., include_depth=True, include_normal=False, color='no-ui')`；移除 UI mask 逻辑 + /color_ui dataset |
| `reshade-addons/UniCap64.json` | Vulkan layer manifest 源（自定义 `name=VK_LAYER_unicap`、`disable_environment=DISABLE_VK_LAYER_unicap_1`）；CMake install 拷到 dist/ |
| `reshade-addons/99-frame_capture/frame_capture.cpp` | addon C++；这次只重命名（UIRemove → BackBufferExport）+ staging fmt fix。**没有** barrier hook（最终 revert 了） |
| `shaders/BackBufferExport.fx` | 重命名自 UIRemove.fx；texture `BackBufferExport_ColorTex`；technique `BackBufferExport`；注释明确说"不做 UI mask 只是 BackBuffer 拷贝" |
| `CMakeLists.txt` | reshade_core install step 同时产 dist/dxgi.dll + dist/UniCap64.dll + dist/UniCap64.json |
| `scripts/build-exe.ps1` | 三处 UniCap64 文件 preflight + Nuitka include + final check |
| `CLAUDE.md` | 文档同步：`--api`、`--mask-ui`、`--color`/`--depth`/`--normal`、F6 删除、UIRemove → BackBufferExport |

## Code Context

### Vulkan layer 注册关键路径 (`main.py:204-280`)

```python
_VK_LAYER_REGKEY = r"Software\Khronos\Vulkan\ImplicitLayers"
_vk_registered_value: str | None = None  # absolute manifest path; None = not registered

def _vk_register_layer(manifest_path: Path) -> None:
    """Register UniCap64.json under HKCU\\...\\ImplicitLayers (DWORD value=0 = enabled)."""
    import winreg
    global _vk_registered_value
    value_name = str(manifest_path.resolve())
    with winreg.CreateKeyEx(winreg.HKEY_CURRENT_USER, _VK_LAYER_REGKEY, 0,
                            winreg.KEY_SET_VALUE | winreg.KEY_QUERY_VALUE) as key:
        winreg.SetValueEx(key, value_name, 0, winreg.REG_DWORD, 0)
    _vk_registered_value = value_name
    atexit.register(_vk_unregister_layer)
    # SIGINT → KeyboardInterrupt (cmd_launch try/finally 接), SIGBREAK + Win32 console-close 单独 hook
    signal.signal(signal.SIGINT, _vk_signal_cleanup)
    signal.signal(signal.SIGBREAK, _vk_signal_cleanup)
    _vk_install_console_handler()
```

### UE4 嵌套检测 (`main.py:166-180`)

```python
def _ue4_nested_exe(start_dir: Path) -> Path | None:
    """UE4 has launcher exe + nested actual game at <Project>\\Binaries\\Win64\\<exe>."""
    inner = [e for e in start_dir.glob("**/Binaries/Win64/*.exe")
             if e.name.lower() not in _SKIP_EXE]
    if not inner:
        return None
    return max(inner, key=lambda f: f.stat().st_size)
```

### pack 新签名 (`tools/capture/pack_hdf5.py:235`)

```python
def pack(frames_dir: Path, inputs_path: Path, output_path: Path,
         include_depth: bool = True, include_normal: bool = False,
         color: str = 'no-ui'):
    """
    color: 'no-ui' (默认) → BackBuffer.bmp 进 /color
           'ui'           → BackBufferUI.bmp 优先 / fallback BackBuffer.bmp
    include_depth (默认 True): 写 /depth
    include_normal (默认 False): 写 /normal
    Pack 不做 UI mask（depth 在 id Tech 7 上分不开 HUD 与近景物体）。
    """
```

### Vulkan loader env vars (`main.py:cmd_launch` 内)

```python
if api == "vulkan":
    cleaned = _vk_clean_stale_entries(VULKAN_LAYER_JSON)  # idempotent on previous crashes
    if cleaned:
        print(f"[VULKAN] 清理上次未释放的 {cleaned} 条注册表残留")
    _vk_register_layer(VULKAN_LAYER_JSON)

    layer_dir = str(VULKAN_LAYER_JSON.parent)
    env["VK_IMPLICIT_LAYER_PATH"] = layer_dir
    env["VK_LAYER_PATH"] = layer_dir
    env["VK_INSTANCE_LAYERS"] = VULKAN_LAYER_NAME
    env.pop("DISABLE_VK_LAYER_unicap_1", None)  # disable_environment 是 presence-checked
```

## Resume Instructions

### 新 agent 第一件事

```bash
git status        # 应该 clean
git log --oneline -5
ls dist/          # 应该有 dxgi.dll + UniCap64.dll + UniCap64.json + frame_capture.addon + unicap-shaders/
```

### 验证三游戏不退化

DX 路径（auto api 检测）:
```powershell
uv run main.py launch --game-path "E:\games\ff7remake\3DMGAME_Final_Fantasy_VII_Remake.CHS.Green.part001\Final Fantasy VII Remake Intergrade\ff7remake.exe"
# 期望: [提示] UE4 嵌套结构: 用内层 End\Binaries\Win64\ff7remake_.exe 而非启动器 ff7remake.exe
# F8 → 自动 survey → 推 skip=0 → capture → video.mp4
```

Vulkan 路径:
```powershell
uv run main.py launch --game-path "E:\games\doom\DOOMEternalx64vk.exe" --ui-mode ui
# 期望: api=auto 检测出 vulkan (exe 名含 vk)
# [VULKAN] HKCU 注册 layer manifest: D:\dev\unicap.git\dist\UniCap64.json
# F8 → 立刻 capture (--ui-mode ui 不需 survey) → video.mp4 含 UI 成片
```

打包训练数据:
```powershell
uv run main.py pack --game-dir "D:\unicap_output\DOOMEternalx64vk" --color ui
# 期望: HDF5 /color = BackBuffer.bmp（含 UI 原图）, /depth 完整, 无 /normal
```

### 如果有人想再做 barrier mode

**别做**。看 §Failed Approaches #1。要继续这条路：
1. 不要在 on_barrier 内做 GPU copy（事后通知 + 多线程 cmd buffer 干扰）
2. 改用 `addon_event::dispatch` hook 直接管 compute write 命令录制
3. 估计 1-2 整天 Vulkan debug + 验证；DOOM Eternal HUD 是 3D 几何**根本问题**仍然在，最终还得色彩或区域 mask 收尾

### 如果要清理 vulkan-support 分支

```bash
git branch -d vulkan-support              # 本地
git push origin --delete vulkan-support   # 远端
```

或者 `/schedule` 1 周后跑 background agent 自动做这事（前面我问过用户但没等到答复）。

## Setup Required

无新增。沿用：
- VS 2022 + MSBuild v143
- `uv sync` 安装 Python deps
- `tools/capture/config.py` 默认 GAME_PATH 是 FF7R inner exe（`E:\games\ff7remake\End\Binaries\Win64\ff7remake_.exe`）—— 用户机器特定
- 日志在 `%TEMP%\unicap\unicap.log{,1}`

## Edge Cases & Error Handling

| 场景 | 当前行为 |
|------|----------|
| 用户传 UE4 launcher path 而非 inner exe | `_resolve_game_path` 自动 walk down 到 `Binaries\Win64\inner.exe` + 打印 [提示] |
| Vulkan 游戏启动后 crash | atexit / signal cleanup 把 HKCU registry 清掉；下次启动 `_vk_clean_stale_entries` 还会再扫一次（冗余兜底） |
| Vulkan 游戏被 Steam 重启 | env vars 被剥光不影响，HKCU 注册全局生效 |
| 游戏目录下有旧 dxgi.dll 残留 | deploy 时 `_symlink_file` 会先 backup .bak 再覆盖 → 旧版会被新版替代 |
| ali213 / 其他破解版 game | unicap 无法干预 launcher 启动逻辑，sticky stub 失败就是失败 |
| pack 时 capture session 没 BackBufferUI.bmp 但用户传 --color ui | fallback 到 BackBuffer.bmp + 打印 "[SCAN] 无 BackBufferUI.bmp → 用 BackBuffer.bmp（假设此 session 是 --ui-mode ui 采集）" |
| `--mask-ui` 在没 depth EXR 的 session 上 | `_apply_ui_mask_bgr` 返回 (img, -1)，原图保留 + 末尾报告 N 帧无 depth |
| HDF5 packed `/normal` 默认关 | 旧代码默认开；旧脚本传 `--no-normal` 兼容（实际很少用，size 节省 ~1 倍） |

## Warnings

- **Vulkan layer HKCU 注册全局副作用** —— 如果 unicap.exe 异常 kill（任务管理器强结），cleanup 跑不完整。`_vk_clean_stale_entries` 启动时扫描兜底（按 manifest 绝对路径匹配，install-unique），但短时间内其他 Vulkan 程序仍会被这层 layer hook → 一般无害但要知道
- **`addon_event::barrier` 是事后通知** (vulkan_hooks_command_list.cpp:939 trampoline 先于 invoke_addon_event) —— 想抓 transition 那一刻的资源状态时**不要**用 old_states[i]，资源已经是 new_states[i]
- **DepthToAddon.fx 导出的是线性化 + reverse-Z flipped depth** —— UE4/UE5/id Tech 7 都是 reverse-Z，UI/sky 像素 depth = **1.0 不是 0.0**。pack_hdf5 之前的 `==0` 阈值在所有这些引擎上都是错的（之前 mask 0 px 但没人发现）
- **DOOM Eternal HUD 是真 3D 几何**（小三角面在近平面 depth 0.001-0.01）—— depth 阈值方法分不开 HUD 和武器手部。要彻底 UI mask 必须用 color HSV 或 region 方案
- **id Tech 7 多线程 cmd-buffer recording** —— 在 on_barrier 内 issue cmd_list->barrier()/copy_texture_region() 是反模式，DOOM Eternal 实测 freeze
- 沿用上份 handoff warnings：reshade/source/ 改了必须 `-Rebuild`；旧 `unicap-*.{i,asm,cso}` cache 不会自动清；R10G10B10A2 swap chain 错色；NUM_WORKERS=2 constexpr
- `dist-exe/` 目录是上次 `build-exe.ps1` 产物，可能含旧 UIRemove.fx / 旧 unicap.exe（v1.0.0），如要重新分发**重跑** `scripts\build-exe.ps1` 拿最新 1.0.2
