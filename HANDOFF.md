# Handoff: Nuitka 打包 + 版本号 + survey 算法两次修复 + 渲染兼容性边界确认

**Generated**: 2026-05-02 00:50
**Branch**: master（与 origin/master 同步，working tree clean）
**Status**: Done — FF7R + Batman AK 实机回归通过（用户原话"都完美"）；DOOM/Vulkan 系列确认 out-of-scope

## Goal

把 Python 项目打包成 Windows exe，**提高破解成本**，**不包含 C/C++ 源码**。期间发现并修了 survey 算法的两个独立 bug，并标定了 unicap 当前架构的渲染 API 兼容性边界。

## Completed

### 打包 (commits `bc49c6d` / `4b036e4`)
- [x] **Nuitka standalone** 打包：`scripts/build-exe.ps1` 一键脚本，产物 `dist-exe/unicap.exe` 57.6 MB + Python 运行时 + 资产文件夹 = 209.9 MB / 88 个文件
- [x] **zip 分发包**：`unicap-{version}.zip` 78.1 MB，输出到项目根目录；zip 内顶层目录 = `unicap-{version}/`，解压不污染当前目录
- [x] **版本号系统**：单一真相源 `pyproject.toml` 的 `[project].version`；`build-exe.ps1` 用 `tomllib` 读、写到 `--file-version` + 文件名；运行时 `main.py:_read_version()` 从 `ROOT/pyproject.toml` 读（onefile 之外的 standalone 路径生效）
- [x] **banner**：`main()` 在 `parse_args()` 之后 print `unicap v{VERSION}`，保证 [启动] 前可见；`--help` / `--version` 不打 banner（argparse 提前 exit）；用 `flush=True` 解决 stdout buffered → stderr 先到的乱序
- [x] **argparse prog 默认化**：源码模式自动 `usage: main.py`，打包后自动 `usage: unicap.exe`（删 `prog="unicap"` 写死）
- [x] **C/C++ 源码不打入**：`reshade/`, `reshade-addons/`, `murchFX/`, `build/`, `CMakeLists.txt` 全部不在 `--include-data-dir` 内

### 命名一致性 (commit `8cb27be`)
- [x] `dist/reshade-shaders/` → `dist/unicap-shaders/`（CMakeLists 4 处 + CLAUDE.md 2 处 + scripts/build.ps1 1 处 + 物理 rename）
- [x] 运行时无影响：`main.py` 的 `EffectSearchPaths` 用顶层 `ROOT/shaders`，从来不读 `dist/<...>-shaders/`

### 清理 (commit `5bbd312`)
- [x] 删 `scripts/setup.ps1` —— 僵尸代码（`.gitmodules` 不存在 + `git submodule status` 为空，从未把依赖真正注册成 submodule）
- [x] `tools/capture/config.py` 删 `REPO_ROOT`/`DIST_DIR`/`VENDOR_DIR` 死代码
- [x] `build-exe.ps1` PSScriptAnalyzer lint 修复（unused `$nuitkaCheck`）

### survey 算法修复 (commit `15076d2`)
- [x] **FF7R 类管线 boundary bug**：旧代码 `largest = max(pairs)` 全局最大 diff 决定 special case，但首端"早期空场景→主渲染区"跳变可能比末端"UI 合成"跳变还大，导致 special case 判否、回到默认流程返回错的一侧（skip=1 含 UI 而非 skip=0 干净）。修：直接看 adjacent-to-zero 那对的 diff 是否远大于"中段稳定 diff"（`pairs[1:-1]` 排除两端 spike）的 median
- [x] **Batman AK 类管线 total=1 fallback**：旧代码在 `total=1` 时无 boundary 可分析，直接 "帧数不足" 失败。修：自动写 `recommended_skip=0` + 警告用户检查 BMP 是否含 UI、若含则改 `--ui-mode ui`

### 实机回归
- [x] FF7R Remake：survey → skip=0、采集 video.mp4 8.7s/82 帧 ✓
- [x] Batman AK：`total=1` fallback 命中 → skip=0、不含 UI ✓

## Not Yet Done

- [ ] **暂无 unicap 主线遗留功能项**
- [ ] (可选) Vulkan 支持：DOOM 2016/Eternal、Wolfenstein II/Youngblood、Quake Champions 等 id Software 游戏全是 Vulkan only，dxgi.dll 永远不会被加载（看 §Failed Approaches 第 3 条）

## Failed Approaches (Don't Repeat These)

### 1. Nuitka onefile → Windows Defender 拦截

最初选 `--onefile`（合理：用户明确要"单 exe"）。Build 出来 main.exe 跑 `--help` 报：

```
Error, load DLL. ([Error 225] Operation did not complete successfully because the file contains a virus or potentially unwanted software.)
```

`Get-MpThreatDetection` 显示拦截的是 Nuitka onefile bootloader 解压到 `%TEMP%\onefile_*\main.dll` 的那个 dll —— **不是** `dxgi.dll`（ReShade core）。这是 Nuitka onefile + LTO + 压缩组合的典型 AV 误报：加壳特征恰好和某些恶意软件签名重合。

**改 standalone 后立刻 OK**：main.dll 留在 `unicap.dist/` 文件夹里，Defender 不再 path-scan，反破解强度无损（`unicap.exe` 仍是 Python→C→机器码的 Nuitka 产物）。

> **教训**：反破解越狠（onefile + LTO + 压缩），AV 误报越高 —— 这是固有 trade-off。standalone 是"够用就好"的甜点。

### 2. argparse `prog="unicap"` 写死

为了让打包后 `usage:` 行显示 "unicap"，第一次写 `parser = argparse.ArgumentParser(prog="unicap")`。结果用户期望 "unicap.exe"（带后缀）。

正确做法：**删 `prog` 参数**，让 argparse 默认从 `os.path.basename(sys.argv[0])` 取——源码模式自动 `main.py`、打包后自动 `unicap.exe`。

> **教训**：argparse prog 默认行为已经是对的，写死 `prog="..."` 反而失去自动化。

### 3. Vulkan 游戏（DOOM 等）当前架构无解

用户测了 DOOM Eternal (`DOOMEternalx64vk.exe`) + DOOM 2016 (`DOOMx64.exe`)，survey 全部 timeout "未收到探测帧"。

**根因**：unicap 走 `dxgi.dll` proxy 路径（DXGI hook），但 id Tech 6/7 引擎（DOOM 系列、Wolfenstein II/Youngblood、Quake Champions）全部 **Vulkan only**：
- DOOM 2016 (id Tech 6)：Vulkan / OpenGL
- DOOM Eternal (id Tech 7)：Vulkan only ← **我前一轮回答错说"支持 DX12"，纠正过**

Vulkan 完全不走 dxgi.dll，部署的 dxgi.dll 永远不被加载，ReShade 不初始化、addon 不启动、sidecar 文件不存在。

**修复需要**：
- ReShade Vulkan layer 部署机制（注册表 `HKLM\SOFTWARE\Khronos\Vulkan\ImplicitLayers` 或 `VK_INSTANCE_LAYERS` env），不是 dxgi.dll proxy
- frame_capture.addon 在 Vulkan 后端的 hook 实现（v5 wrapper API 在 Vulkan 下行为不同，需单独验证）
- 工作量评估：1-2 整天，建议另立分支 `vulkan-support`

**当前规避**：用户跳过 id Software 游戏，专注 DX11/DX12 目标（FF7R / Batman AK 已验证）。

### 4. onefile 路径生命周期问题（已绕开）

onefile 模式下 Nuitka 把资产解压到 `%TEMP%\onefile_xxx\`，`Path(__file__).parent` 指向那里。但 main.py 在 `unicap.ini` 写的 `EffectSearchPaths` / `PresetPath` / `AddonPath` 是给 **game 进程的 dxgi.dll** 读的——main.py 退出后 onefile temp 被清，game 下次加载 shader 就失败。

我加了一段 `_resolve_root()` 把资产从 temp sync 到 `%LOCALAPPDATA%\unicap\runtime\` 解决。**但是**因为后来改 standalone（见 #1），这段逻辑变成无意义复杂——standalone 下 `__file__` 直接指向 `unicap.dist/`，就是持久路径，不需要 sync。

**最终代码**：删除整个 `_resolve_root()`，回到 `ROOT = Path(__file__).parent`（`main.py:48`）。一行注释说明 onefile 不被支持。

## Key Decisions

| Decision | Rationale |
|----------|-----------|
| Nuitka standalone（不是 PyInstaller） | PyInstaller 把 `.py` 编成 `.pyc` 塞进 onefile，`pyinstxtractor` + `uncompyle6` 5 分钟还原 90%。Nuitka 翻译为 C 再 MSVC 编机器码，破解成本数量级提升 |
| standalone 而非 onefile | onefile bootloader 解压 main.dll 到 temp 触发 Defender；standalone 反破解强度同等但 AV 友好 |
| version 单一来源 = pyproject.toml | 单点修改自动反映到 file-version metadata + banner + zip 文件名 |
| pyproject.toml 嵌入 unicap.dist/ | `--include-data-files=pyproject.toml=pyproject.toml`；运行时 `main.py:_read_version()` 用 `tomllib` 读，源码 / 打包模式同一逻辑 |
| zip 内顶层目录 = `unicap-{version}/` | 解压不污染当前目录；用 `.NET ZipFile.CreateFromDirectory` + `includeBaseDirectory=true` 实现，比 `Compress-Archive` 快 |
| build-exe.ps1 中间目录 `dist-exe-build/` 与最终 `dist-exe/` 分离 | Nuitka 默认产物在 `<output-dir>/main.dist/`，需 rename 步骤；分离避免 Nuitka 看到旧 main.dist 直接 reuse |
| survey special case 看 adjacent-to-zero 而非 global max | 数据驱动决策：用户实测 FF7R 同一份代码两次跑结果不同（python=0、exe=1），定位为 "global max 在两端 spike 间易翻转" 的稳定性 bug |
| Batman AK total=1 → 自动 skip=0 + 警告，**不直接报错** | 失败 hard-stop 让用户卡住；自动 fallback + 提示用户验证 BMP 让流程能跑下去 |
| Vulkan 支持留作未来分支 | 工作量大；当前用户主要目标是 FF7R（DX12），DOOM 系列只是 nice-to-have |

## Current State

**Working**:
- `dist-exe/unicap.exe` 57.6 MB，启动打 banner `unicap v1.0.0`
- `unicap-1.0.0.zip` 78.1 MB（项目根，分发就用这个）
- 源码模式 `uv run main.py launch ...` 行为同 exe（banner + version + auto prog）
- FF7R / Batman AK survey + capture 全 OK
- `--help` / `--version` / `launch --help` / `pack --help` / `video --help` 全 OK

**Broken**:
- 无（unicap 主线全 OK）

**Out of scope（设计边界）**:
- Vulkan-only 游戏（DOOM 系列等）：dxgi.dll proxy 不被加载，全部 timeout

**Uncommitted Changes**: 无（working tree clean，所有改动已 push 到 origin/master）

## Files to Know

| File | Why It Matters |
|------|----------------|
| `scripts/build-exe.ps1` | 本会话核心新文件 — Nuitka standalone 打包 + zip。改 build flag / 嵌入资产 / 版本号逻辑都在这 |
| `main.py` | `_read_version()` (L53-61) + `VERSION` 常量 + `main()` 顶部 banner（L674）+ argparse prog 默认 |
| `tools/capture/survey.py` | 算法两次修复都在这；`_find_boundary()` (L122-131) 是 FF7R bug 修复点；`run()` 中 `total == 1` fallback (L274-285) 是 Batman bug |
| `pyproject.toml` | **单一版本真相源**；改 `version` 自动传到所有出口 |
| `.gitignore` | 加了 `dist-exe/` `dist-exe-build/` `unicap-*.zip` |
| `CLAUDE.md` | `dist/reshade-shaders/` → `dist/unicap-shaders/` 改名后保持文档一致；其他基本不动 |
| `dist/unicap-shaders/` | （rename 自 `reshade-shaders/`）shader 副本，CMake build 产物 + cmake install 部署目标。运行时 main.py 不读这里，读顶层 `shaders/` |

## Code Context

### 版本号读取（main.py:53-61）

```python
def _read_version() -> str:
    """Read [project].version from pyproject.toml. Source mode reads repo
    pyproject.toml; packaged mode reads the copy embedded into unicap.dist/."""
    try:
        import tomllib
        return tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))["project"]["version"]
    except (ImportError, OSError, KeyError):
        return "unknown"

VERSION = _read_version()
```

`ROOT = Path(__file__).parent`：源码模式 = repo 根；Nuitka standalone 模式 = `unicap.dist/`。两边都有 `pyproject.toml`（standalone 通过 `--include-data-files=pyproject.toml=pyproject.toml` 嵌入）。

### main() 入口（main.py:670-678）

```python
def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--version", action="version", version=f"unicap v{VERSION}")
    sub = parser.add_subparsers(dest="cmd", required=True)
    # ... add subparsers
    args = parser.parse_args()
    print(f"unicap v{VERSION}", flush=True)  # banner — 在 [启动] 之前
    {"launch": cmd_launch, "video": cmd_video, "pack": cmd_pack}[args.cmd](args)
```

**注意**：banner 在 `parse_args()` 之后；`flush=True` 必需（stdout block-buffered 时遇 `sys.exit(...)` stderr 会先到，banner 顺序错乱）。

### survey FF7R 修复（survey.py:121-131）

```python
median_diff = all_diffs[len(all_diffs) // 2]
adj_zero = next((p for p in pairs if p[1] == ordered[-1]), None)
mid_diffs = sorted(d for _, _, d in pairs[1:-1]) if len(pairs) >= 3 else []
mid_median = mid_diffs[len(mid_diffs) // 2] if mid_diffs else median_diff
if adj_zero is not None and adj_zero[2] > 5.0 * max(mid_median, 1.0):
    return ordered[-1]
```

判断"紧挨 skip=0 那一对的 diff 是否远大于中段稳定差分的 median"，**不**看全局 max（旧 bug 的根因）。

### survey Batman fallback（survey.py:274-285）

```python
if total == 1 and 0 in captured:
    print("\n[SURVEY] 警告：该游戏仅 1 个非 BB pass，无法做 boundary 分析。")
    print("         skip=0 是唯一可选值；pre-UI 帧能否采到取决于游戏管线。")
    print("         建议：先打开 survey_skip_000_BackBuffer.bmp 检查是否含 UI；")
    print("               若含 UI，请改用 --ui-mode ui（跳过 survey，直抓 BackBuffer）。")
    rec_file = survey_dir / "recommended_skip.txt"
    rec_file.write_text("0", encoding="utf-8")
    return 0
```

### build-exe.ps1 关键 flag

```powershell
& uv run python -m nuitka `
    --standalone `              # 不是 onefile (AV 误报)
    --lto=yes `                 # 函数边界模糊化
    --remove-output `           # 删 .build/ 不留 .c
    --output-dir=$buildDir `    # dist-exe-build/ (中间)
    --output-filename=unicap.exe `
    --include-package=tools `
    --include-package=cv2 `
    --include-package=h5py `
    --include-package=numpy `
    --include-data-dir=dist=dist `
    --include-data-files=dist/dxgi.dll=dist/dxgi.dll `   # ⚠ --include-data-dir 默认排除 .dll，必须显式
    --include-data-dir=shaders=shaders `
    --include-data-dir=config=config `
    --include-data-files=pyproject.toml=pyproject.toml ` # 给运行时 _read_version() 用
    --file-version=$version `   # $version 来自 tomllib 读 pyproject.toml
    ...
```

## Resume Instructions

### 新 agent 第一件事

```bash
git status        # 应该 clean
git log --oneline -5   # 最近 5 个 commit
ls dist-exe/      # 应该存在 unicap.exe + 资产
ls unicap-*.zip   # 应该有 unicap-1.0.0.zip
```

如果都对，本次 handoff 工作已完成，无主动遗留任务。

### 怎么再 build

```powershell
scripts\build-exe.ps1            # 增量 (ccache 几乎全命中，~5-7 min for link)
scripts\build-exe.ps1 -Clean     # 全量重建 (清 Nuitka cache + dist-exe + dist-exe-build)
```

期望输出末尾：
```
构建成功 ✓
  unicap.exe: ~57 MB
  总大小:     ~210 MB (~88 个文件)
  位置:       D:\dev\unicap.git\dist-exe\
  分发包:     D:\dev\unicap.git\unicap-{version}.zip (~78 MB)
  关键资产:   ✓ dxgi.dll / frame_capture.addon / shaders / config
```

### 升级版本

只改 `pyproject.toml` 的 `version = "X.Y.Z"`，所有出口（banner / `--version` / file metadata / zip 文件名）自动跟随。

### 如果要做 Vulkan 支持

新分支：`git checkout -b vulkan-support`。首要研究：
1. ReShade Vulkan layer 怎么部署（注册表 ImplicitLayers 还是 env var）
2. frame_capture.addon 的 v5 API 在 Vulkan 后端的 RT bind hook 行为
3. survey 协议（sidecar 文件）需不需要改

测试游戏：`E:\games\doom2016\DOOMx64.exe`（用户已实测 timeout）。

## Setup Required

无新增。沿用：
- VS 2022 + MSBuild v143（用于 build.ps1 / Nuitka 后端）
- `uv sync` 安装 Python deps（`opencv-python`, `h5py`, `numpy`, `nuitka>=4.0.8`）
- `tools/capture/config.py` 的 `GAME_PATH`/`DATASET_ROOT`（机器特定）
- 日志在 `%TEMP%\unicap\unicap.log{,1}`

## Edge Cases & Error Handling

| 场景 | 当前行为 |
|------|----------|
| 游戏渲染管线 `total=1` (Batman AK) | 自动 skip=0 + 警告，不卡住 |
| 游戏渲染管线 `total=0` 或读不到 fc_pass_total.txt | 报错"未读到 fc_pass_total.txt"，提示进入实际 3D 场景再 F6 |
| FF7R 类两端 spike 在 boundary 算法 | 修后稳定（看 adjacent-to-zero vs 中段 median） |
| Vulkan 游戏 (DOOM 等) | 静默 timeout 12 秒后报"未收到探测帧"——目前没识别 Vulkan exe 自动提示，要靠用户/dev 判断 |
| Defender 拦截 onefile main.dll | **已绕开**：改 standalone |
| `--help` / `--version` | argparse 提前 sys.exit，不打 banner |
| 子命令业务出错 | banner 在错误前打印（`flush=True`） |

## Warnings

- **CLAUDE.md 没更新本次会话改动** — 我只改了 reshade-shaders → unicap-shaders 那两行，但"Build" 段没提到 build-exe.ps1 / unicap.exe / zip。下次有时间该补一段"Distribution"或合并进"Build"
- **dist-exe/ 是 build 产物** — 不入库 (`.gitignore` 已设)，但放心改
- **dxgi.dll 必须显式 `--include-data-files`** —— Nuitka `--include-data-dir` 默认排除 .dll 文件（视为可执行依赖）。第一次 build 漏 dxgi.dll 就是这个坑
- **`reshade/` `reshade-addons/` `murchFX/` 是本地独立 git repo，不是 submodule**（`.gitmodules` 不存在）。setup.ps1 已删，新人想 clone 这些得手动 git clone（或者补 submodule）
- **Vulkan 游戏静默失败** — 没识别提示，看到 timeout 应先怀疑游戏渲染 API。识别方法：exe 名带 `vk` / `vulkan`（如 `DOOMEternalx64vk.exe`）或 id Tech 6/7 引擎
- **id Tech 7 是 Vulkan only**（不是我前一轮误说的"支持 DX12"）——纠正过两次，认真记住
- **unicap.exe 启动时不会加载 `%TEMP%\unicap\unicap.ini` 已有的 ROOT 配置** —— `_ensure_addon_enabled()` 每次 launch 都重写所有路径为当前 ROOT 下的资产，覆盖旧值。所以新 build 的 exe 跑起来会自动指自己的 `unicap.dist/`
- 沿用上份 handoff warnings：reshade/source/ 改了必须 `-Rebuild`；旧 `unicap-*.{i,asm,cso}` cache 不会自动清；R10G10B10A2 swap chain 错色；NUM_WORKERS=2 constexpr
