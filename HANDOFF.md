# Handoff: 打包 unicap CLI + GUI 双 standalone exe

**Generated**: 2026-05-07 18:45 +0800
**Branch**: master（与 origin/master 同步，clean —— 已 commit `2b62905`，未 push）
**Status**: Ready for Review —— 双产物 build 成功；GUI multidist dispatch 验证通过；GUI exe 内部 spawn CLI 子进程的端到端链路未实跑（需带显示器）

## Goal

把 unicap 打成两个独立 standalone exe 包：
1. **CLI 包**（`dist-exe/`）—— 仅 `unicap.exe`，不含 PySide6，体积小
2. **GUI 包**（`dist-exe-gui/`）—— `unicap-gui.exe` + 包内自带 `unicap.exe`，含 PySide6，self-contained

让用户按需选择下载，CLI 用户不用背 PySide6 体积。

## Completed

- [x] **`unicap_gui/shared/paths.py`** — 新增 `is_frozen()` / `cli_executable()` / `cli_argv_prefix()`；`repo_root()` 在 frozen 模式下返回 `Path(sys.executable).parent`（exe 同目录），dev 模式仍是 `parents[2]`
- [x] **`unicap_gui/shared/process.py`** — `start()` 改用 `cli_argv_prefix()` 替代手拼 `[python, -X utf8, -u, main.py]`；`cwd` 改用 `repo_root()`。frozen 时 cmd = `[unicap.exe, subcommand, *argv_tail]`，dev 时仍走 `[python, -X utf8, -u, main.py, subcommand, ...]`
- [x] **`unicap_gui/widgets/cli_preview.py`** — frozen 时 preview 显示 `unicap.exe ...` 替代 `uv run main.py ...`，让用户复制出来能直接跑
- [x] **`scripts/build-exe.ps1` 重写** — 加 `-Target {cli|gui|all}` 参数；CLI 单 main 走原 standalone 流程；GUI 走 multidist；timestamp 后缀 fallback 应对锁住的旧 buildDir
- [x] **CLI build 验证**：`dist-exe/unicap.exe` 60.3 MB / 总 222.4 MB / zip `unicap-cli-1.0.7.zip` 82.6 MB；`unicap.exe --help` 正确输出 launch/video/pack 子命令
- [x] **GUI build 验证**：`dist-exe-gui/{unicap.exe, unicap-gui.exe}` 各 62.4 MB / 总 773.1 MB / zip `unicap-gui-1.0.7.zip` 293.6 MB
- [x] **multidist dispatch 验证**：`unicap.exe --help` 走 CLI entry；`QT_QPA_PLATFORM=offscreen unicap-gui.exe` 跑满 6s 阻塞在 `app.exec()` 才被 timeout 杀（说明走了 GUI entry）
- [x] **`.gitignore`** 加 `dist-exe-gui/`、`dist-exe-{,gui-}build*/` glob、`/unicap.py` + `/unicap-gui.py`（multidist build-time 临时入口）

## Not Yet Done

- [ ] **GUI exe 内部 spawn CLI 子进程的端到端实跑**（需带显示器）：用户在本机跑 `dist-exe-gui\unicap-gui.exe`，点 Start → SubprocessRunner 应当 spawn `dist-exe-gui\unicap.exe launch ...`，不是 python。验证步骤见 Resume Instructions
- [ ] **可选 push**：`2b62905` 已 commit 但还没 push（用户授权 commit 但未授权 push）
- [ ] **首次启动可能被 Windows Defender 标 SmartScreen**：standalone exe 没签名，初次跑会弹 "Windows protected your PC"。Nuitka 产物比 PyInstaller onefile AV 容忍度好，但仍未签名。如果分发给外部用户需要做 code signing（Authenticode 证书 ~年 200 USD）

## Failed Approaches (Don't Repeat These)

### 1. Nuitka multidist 期望自动产出多个 exe（与文档不符）

**尝试**：基于 Nuitka 文档 "should automatically create extra files for each one of them" 的描述，期望 `--main=unicap.py --main=unicap-gui.py` 在 dist 目录里产出 `unicap.exe` + `unicap-gui.exe` 两个文件，build 完直接校验两个 exe 都存在。

**失败**：Nuitka 4.0.8 实际只产出**单个** binary（dist 里只有 `unicap.exe`，没有 `unicap-gui.exe`）。multidist 模式是单 binary 内嵌多入口，运行时按 `argv[0]` basename 分发。校验脚本里写 `Test-Path unicap-gui.exe` 直接 fail 退出。

**修法**：build 后手工 `Copy-Item unicap.exe unicap-gui.exe`。两个 exe 字节完全相同（62.4 MB 各一份）；Windows 启动时按文件名 dispatch。验证用 `QT_QPA_PLATFORM=offscreen ./unicap-gui.exe` 跑 6s 阻塞确认 dispatch 到 GUI entry。

### 2. GUI build buildDir 删除被 antivirus / explorer 锁住

**尝试**：第一次 GUI build 完产物在 `dist-exe-gui-build/unicap.dist/`，我手工 `cp unicap.exe unicap-gui.exe` 测了 dispatch；之后再跑 `build-exe.ps1 -Target gui`，脚本走到 `Remove-Item -Recurse -Force $guiBuildDir` 失败：`Cannot remove ... because it is in use`。

**失败原因**：刚跑过的 unicap-gui.exe 进程虽然已退出（tasklist 看不到），但目录的 file handle 还被某个后台进程持有（推测 Windows Defender 异步扫描或 explorer 索引），sleep 30s + cmd `rmdir /s /q` + `Rename-Item` 全部失败。

**修法**：build-exe.ps1 GUI build 路径改用 `$localBuildDir`：尝试删旧 `$guiBuildDir`，删失败就用 timestamp 后缀的新路径（`dist-exe-gui-build-yyyyMMddHHmmss`）。旧目录留磁盘上下次 `-Clean` 一并清。`$guiOutDir` 同样加 fallback。

### 3. 单一 standalone 包同时包 CLI + GUI（被用户否决）

**尝试**：方案讨论时倾向 multidist 一次构建产 `unicap.exe + unicap-gui.exe` 共享一个 dist 目录，用户下载一个包。

**失败**：用户明确选择"分两个独立 standalone 目录（CLI 不带 PySide6）"——CLI 包不应背 PySide6 / QtWebEngine 体积，纯命令行用户拿小包。

**修法**：拆 CLI 和 GUI 两次 build：
- CLI 单 main → `dist-exe/`（无 PySide6，82.6 MB zip）
- GUI multidist → `dist-exe-gui/`（含 PySide6 + 内嵌 CLI，293.6 MB zip）

## Key Decisions

| Decision | Rationale |
|----------|-----------|
| 双独立 standalone 目录（不共享 runtime） | 用户明确：CLI 包要小、不带 GUI 依赖；GUI 包 self-contained 不要求用户先装 CLI 包 |
| GUI 包内用 multidist 自带 CLI（不让 GUI 在 PATH 找） | self-contained：用户解压 GUI zip 就能用，不依赖外部 CLI 安装 |
| `is_frozen()` 用 `sys.executable` 文件名启发判断（不依赖 Nuitka 私有标记） | `__compiled__` 是 Nuitka 注入的全局，但只在编译产物的"主模块"里有，子模块未必访问得到；判断 `sys.executable` 不含 `python` 更稳，覆盖 PyInstaller (`sys.frozen`) 也兜底 |
| build-time 临时复制 `main.py → unicap.py` + 写 `unicap-gui.py` wrapper | Nuitka multidist 的 exe 文件名 = main 文件 basename。要让 exe 叫 `unicap.exe` / `unicap-gui.exe`，源文件就得叫这俩名；不重命名 `main.py`（会破坏现有 import + CLAUDE.md 描述）→ build 时临时复制，finally 删 |
| buildDir timestamp 后缀 fallback | Windows 文件锁不可预测（AV / explorer / 索引），不能依赖 `Remove-Item` 一定成功；用唯一目录名绕过比 retry-with-sleep 鲁棒 |
| 手工 `Copy-Item unicap.exe → unicap-gui.exe` 替代依赖 Nuitka 自动多 exe | Nuitka 4.0.8 multidist 实际行为是单 binary + argv[0] dispatch，不是文档描述的"自动多 exe"；脚本注释里写明这点避免下次踩坑 |
| frozen 模式下 cwd 改 `repo_root()` 而不是 `main_py().parent` | frozen 时没有 `main.py` 文件；`repo_root()` 在 frozen 下返回 exe 目录，dev 下返回 repo 根，对 CLI subprocess 来说都是正确的工作目录 |

## Current State

**Working**:
- `git log` HEAD = `2b62905 update build exe gui`，工作树 clean
- `dist-exe/unicap.exe` + `dist-exe-gui/{unicap.exe, unicap-gui.exe}` 落盘
- `unicap-cli-1.0.7.zip`（82.6 MB）+ `unicap-gui-1.0.7.zip`（293.6 MB）落盘
- CLI dispatch 验证：`./dist-exe/unicap.exe --help` 输出 argparse 帮助 + launch/video/pack
- GUI multidist dispatch 验证：`./dist-exe-gui/unicap.exe --help` 同上；`QT_QPA_PLATFORM=offscreen ./dist-exe-gui/unicap-gui.exe` 跑 6s 阻塞在 app.exec()
- dev 模式 GUI 仍工作（headless smoke：toggle、form lock、fps auto display 都过）

**Broken**: 无已知 broken。

**Uncommitted Changes**: 无（commit `2b62905` 已包全部改动，未 push）。

## Files to Know

| File | Why It Matters |
|------|----------------|
| `scripts/build-exe.ps1` | build 入口；`-Target {cli|gui|all}` + `-Clean`；GUI build 函数处理 multidist + buildDir timestamp fallback + 手工复制 unicap-gui.exe |
| `unicap_gui/shared/paths.py` | `is_frozen()` 启发判断；`cli_argv_prefix()` 是 frozen-aware spawn 入口；改 paths 时同步 dev/frozen 两条路径 |
| `unicap_gui/shared/process.py` | `SubprocessRunner.start()` 用 `cli_argv_prefix()` —— frozen 下 spawn 同目录 `unicap.exe`，dev 下走 python+main.py |
| `unicap_gui/widgets/cli_preview.py` | preview 显示也根据 frozen 切换前缀（用户体验细节） |
| `dist-exe/` | CLI standalone 产物目录（gitignored） |
| `dist-exe-gui/` | GUI standalone 产物目录（gitignored），含 `unicap.exe` + `unicap-gui.exe` 双 entry |
| `unicap-cli-1.0.7.zip` / `unicap-gui-1.0.7.zip` | 分发包（gitignored） |
| `.gitignore` | 加了 `dist-exe-gui/`、build dir timestamp glob、临时入口文件 |

## Code Context

### frozen 检测启发（`unicap_gui/shared/paths.py`）

```python
def is_frozen() -> bool:
    """是否运行在 Nuitka standalone 产物里（vs 源码 dev 运行）。

    判据：sys.executable 不是 python.exe / pythonw.exe / py.exe。
    Nuitka standalone 把 sys.executable 设为产物 exe（如 unicap-gui.exe）。
    """
    if getattr(sys, "frozen", False):  # PyInstaller marker (兜底)
        return True
    name = Path(sys.executable).name.lower()
    return "python" not in name and name not in ("py.exe", "py")


def cli_argv_prefix() -> list[str]:
    """spawn CLI 子进程的 argv 前缀（不含 subcommand 本体）。

    frozen: [unicap.exe]                    —— 直接调同目录的 multidist 产物
    dev:    [python, -X utf8, -u, main.py]  —— 走 venv python
    """
    if is_frozen():
        return [str(cli_executable())]
    return [sys.executable, "-X", "utf8", "-u", str(main_py())]
```

### GUI build 关键步骤（`scripts/build-exe.ps1` Build-Gui）

```powershell
# 1) buildDir 锁定 fallback
$localBuildDir = $guiBuildDir
if (Test-Path $localBuildDir) {
    try { Remove-Item -Recurse -Force $localBuildDir -ErrorAction Stop }
    catch {
        $stamp = Get-Date -Format 'yyyyMMddHHmmss'
        $localBuildDir = "$guiBuildDir-$stamp"
    }
}

# 2) build-time 临时入口（Nuitka multidist 按文件 basename 命名 exe）
Copy-Item -Path $mainPy -Destination "$root\unicap.py" -Force
Set-Content -Path "$root\unicap-gui.py" -Encoding utf8 -Value @"
from unicap_gui.__main__ import main
import sys
sys.exit(main())
"@

# 3) Nuitka multidist
& uv run python -m nuitka `
    --standalone --enable-plugin=pyside6 `
    --include-package=tools --include-package=unicap_gui --include-package=PySide6 ... `
    --main=$cliEntry --main=$guiEntry

# 4) 手工复制（Nuitka 4.0.8 实际只产单 binary）
Copy-Item -Path "$nuitkaDist\unicap.exe" -Destination "$nuitkaDist\unicap-gui.exe" -Force
```

### multidist dispatch 行为

- Nuitka 编译 `--main=unicap.py --main=unicap-gui.py` → 单 binary `unicap.exe` 内嵌两个 main 的所有代码
- 启动时读 `argv[0]` basename：
  - `unicap` → 跑 `unicap.py`（= main.py 副本，CLI argparse）
  - `unicap-gui` → 跑 `unicap-gui.py`（= GUI wrapper，启 QApplication）
- 把 `unicap.exe` 复制为 `unicap-gui.exe` 后 dispatch 自动切换；两文件字节完全相同

### 产物 layout

```
dist-exe/                       # CLI 包（无 PySide6）
  unicap.exe                    60.3 MB
  python313.dll, numpy.libs/, cv2/, h5py/, hdf5.dll, ...
  dist/{dxgi.dll,UniCap64.dll,UniCap64.json,frame_capture.addon}
  shaders/, profiles/, config/

dist-exe-gui/                   # GUI 包（multidist + PySide6）
  unicap.exe                    62.4 MB（multidist 第一入口 = CLI）
  unicap-gui.exe                62.4 MB（multidist 第二入口 = GUI；与 unicap.exe 字节相同）
  PySide6/, QtWebEngineProcess.exe, qt6.conf, icudtl.dat, qtwebengine_resources*.pak, ...
  python313.dll, numpy.libs/, cv2/, h5py/, hdf5.dll, ...
  dist/{dxgi.dll,UniCap64.dll,UniCap64.json,frame_capture.addon}
  shaders/, profiles/, config/
```

## Resume Instructions

### 1) GUI exe 端到端实跑验证（最重要 —— 本 session 没真跑）

```powershell
# 在 Windows GUI 桌面环境
cd D:\dev\unicap.git\dist-exe-gui
.\unicap-gui.exe
```

**预期**：
- GUI 窗口起来（unicap GUI 三 tab：采集/生成视频/打包）
- 选 game-path 指向 FF7R exe → 点 Start
- 子进程 cmd 应当是 `<dist-exe-gui>\unicap.exe launch --game-path ... --auto-play ...`（**不是** python）
- console log 看到 `[CAPTURE]` `[AUTO-PLAY]` 等输出（与源码运行一样）
- 按 F8/F9 / 关游戏 / Stop 按钮路径全部应当工作（与 dev 路径行为一致）

**如果失败**：
- GUI 起不来 → 看 `%APPDATA%\unicap-gui\unicap-gui.log` 找 PySide6 import 错（缺 dll？）
- spawn 失败 `找不到可执行文件` → `is_frozen()` 没命中或 `cli_executable()` 路径不对；检查 `Path(sys.executable).parent / "unicap.exe"` 在 multidist 下是否存在
- spawn 起来但游戏不响应 → CLI subprocess 的 cwd / env 可能不对（已改成 `repo_root() = exe 同目录`，应该 OK）

### 2) Push commit（如果用户决定推）

```powershell
git push origin master
```

`2b62905 update build exe gui` 已 commit，等用户授权 push。

### 3) 如果要重 build

```powershell
# 全量重建（清 Nuitka cache + 旧 dist-exe* 目录）
scripts\build-exe.ps1 -Clean -Target all

# 单独重 CLI（增量，~2 分钟）
scripts\build-exe.ps1 -Target cli

# 单独重 GUI（增量，~3-5 分钟；首次 ~10-15 分钟）
scripts\build-exe.ps1 -Target gui
```

### 4) 修代码后的 sanity check（不重 build）

```powershell
# headless dev-mode smoke（验证 frozen-aware 改动没破 dev 路径）
$env:QT_QPA_PLATFORM = 'offscreen'
$env:PYTHONIOENCODING = 'utf-8'
uv run --with PySide6 python -c "
from unicap_gui.shared.paths import is_frozen, cli_argv_prefix
assert is_frozen() is False                    # dev 模式
prefix = cli_argv_prefix()
assert 'main.py' in prefix[-1]                 # dev: 末尾是 main.py 路径
assert '-X' in prefix and '-u' in prefix       # dev: 带 -X utf8 -u
print('dev-mode argv prefix OK:', prefix)
"
```

## Setup Required

- Windows 11 + Visual Studio 2022（Nuitka 调 `cl.exe` 编译 C 后端）
- `uv` 管理 Python 3.13 venv
- `uv sync --extra gui` 装 PySide6（GUI build 必需）
- `dist/` 已有 ReShade DLL：`dxgi.dll` / `UniCap64.dll` / `UniCap64.json` / `frame_capture.addon`（preflight 会校验，缺失提示跑 `scripts\build.ps1`）
- 首次 build 可能需要 Nuitka 自动下载 `depends.exe`（已加 `--assume-yes-for-downloads`）

## Edge Cases & Error Handling

- **build 时 buildDir 被锁**：脚本 `Remove-Item` 失败 → 自动 fallback 到 timestamp 后缀的新目录。旧目录留磁盘，下次 `-Clean` 一并清。如果连续多次 build 留多个 timestamp 目录，磁盘会涨。
- **build 时 dist-exe-gui 也被锁（旧 GUI 进程没退）**：脚本尝试 Rename 也失败 → 直接报错让用户手工关 explorer 后重试（无法 graceful 处理 OS 级文件锁）。
- **frozen 检测误判（未来某天 Nuitka 改用 `sys.executable=python.exe`）**：`is_frozen()` 会返回 False；GUI 试图 spawn `python -X utf8 -u main.py`，但 frozen 包内没 `main.py` → spawn FileNotFoundError。届时改 `is_frozen()` 用 `__compiled__` 检测或显式 env var marker。
- **multidist binary argv[0] 被改写**（极端：用户 rename 为别的名字）：dispatch 会找不到匹配 main，Nuitka 行为未知（可能 fallback 到第一个 main）。文档约束：用户不要 rename `unicap.exe` / `unicap-gui.exe`。
- **`unicap_gui/__main__.py` 的 PySide6 import 失败 fallback**：源码里有 try/except 提示 `uv sync --extra gui`，但在 frozen 包里 PySide6 必然在；提示文字仍会显示但实际不会触发。
- **跨包共享 frame_capture.addon / dxgi.dll**：CLI 包和 GUI 包各带一份，互不干扰。同机两个包都解压时 `dist/dxgi.dll` 不会冲突（各自的 `<bundle>/dist/`）。

## Warnings

- **`unicap.exe` 和 `unicap-gui.exe` 在 GUI 包里字节完全相同**（62.4 MB × 2 = 124.8 MB 占用）。这是 Nuitka multidist 的实现细节，不是 bug；删一个 dispatch 就坏。
- **未签名 exe 首次跑会被 SmartScreen 拦**：分发给外部用户前最好做 Authenticode 签名，否则用户要点"仍要运行"才行。
- **changes 已 commit 未 push**：`2b62905 update build exe gui` 在本地 master，等用户授权 push。
- **Nuitka 4.0.8 multidist 与文档描述不符**：文档说自动产多 exe，实际单 binary + argv[0] dispatch。脚本里手工复制处理；下次升级 Nuitka 主版本前先小测一次产物布局是否变化。
- **build-time 临时文件 `unicap.py` / `unicap-gui.py` 在 repo 根**：`.gitignore` 已 cover；`finally` 块里 `Remove-Item -ErrorAction SilentlyContinue` 兜底删除，但如果 PowerShell 进程在 finally 前被 hard kill 会残留 → 手工删即可。
- **GUI exe 启动慢**（首次 ~3-5s）：Nuitka standalone 冷启动 + PySide6 + 多 dll 加载，正常现象，非 hang。
- **未实测 GUI exe 实际拉起 CLI**：`is_frozen()` 在 GUI exe 里命中后 spawn `unicap.exe`，但本 session 没验证整链路。GUI exe 起来后第一件事就该测点 Start 看 spawn cmd 是否正确。
