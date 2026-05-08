#!/usr/bin/env pwsh
# build-exe.ps1 — Nuitka standalone build of unicap CLI + GUI.
#
# 输出（按 -Target 选择）:
#   dist-exe/         CLI standalone (main.py → unicap.exe，不含 PySide6)
#   dist-exe-gui/     GUI standalone (multidist → unicap-gui.exe + 包内 unicap.exe，含 PySide6)
#
# Usage:
#   scripts\build-exe.ps1                       # 默认只 GUI（GUI 包已自带 CLI）
#   scripts\build-exe.ps1 -Target cli           # 只 CLI
#   scripts\build-exe.ps1 -Target gui           # 只 GUI（默认）
#   scripts\build-exe.ps1 -Target both          # CLI + GUI 两个包
#   scripts\build-exe.ps1 -Clean                # 清 dist-exe* + Nuitka cache 全量重建
#
# 依赖: uv + Nuitka (脚本会自动 uv add 一次)。
# 构建期会调用 MSVC (cl.exe) — 需 VS 2022 已安装 (与 build.ps1 一致)。
#
# 双产物设计：
#   - CLI 包仅含 unicap.exe + 必要 runtime（cv2/numpy/h5py），体积小，纯命令行用户
#   - GUI 包通过 Nuitka multidist 一次构建产出 unicap-gui.exe + unicap.exe，
#     共享同一份 Python runtime + PySide6，GUI 进程启动时 spawn 包内 unicap.exe
#   - 两个包独立，分发时按用户需求选一个；GUI 包自带 CLI 不必额外解压 CLI 包

param(
    [switch]$Clean,
    [ValidateSet('cli', 'gui', 'both')]
    [string]$Target = 'gui'
)

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

$root         = Split-Path $PSScriptRoot -Parent
$cliOutDir    = Join-Path $root "dist-exe"
$guiOutDir    = Join-Path $root "dist-exe-gui"
$cliBuildDir  = Join-Path $root "dist-exe-build"
$guiBuildDir  = Join-Path $root "dist-exe-gui-build"
$mainPy       = Join-Path $root "main.py"
$pyproject    = Join-Path $root "pyproject.toml"
$faviconPng   = Join-Path $root "favicon.png"
$faviconIco   = Join-Path $root "favicon.ico"

# ── 前置检查 ──────────────────────────────────────────────────────────────────
$preflight = @(
    @{ Name = "dist\dxgi.dll";            Hint = "scripts\build.ps1 构建 C++ 部分" }
    @{ Name = "dist\UniCap64.dll";        Hint = "scripts\build.ps1（Vulkan layer DLL）" }
    @{ Name = "dist\UniCap64.json";       Hint = "scripts\build.ps1（Vulkan layer manifest）" }
    @{ Name = "dist\frame_capture.addon"; Hint = "scripts\build.ps1" }
    @{ Name = "favicon.png";              Hint = "把项目 logo 放到 repo 根（图标用）" }
)
foreach ($p in $preflight) {
    if (-not (Test-Path (Join-Path $root $p.Name))) {
        Write-Host "[错误] $($p.Name) 不存在 — 先跑 $($p.Hint)。" -ForegroundColor Red
        exit 1
    }
}

# favicon.ico 比 favicon.png 旧 → 用 Pillow 重生成（Nuitka 原生吃 ICO，不需
# imageio；多尺寸 ICO 让 Windows 在不同 DPI 下挑合适分辨率）
$needIco = -not (Test-Path $faviconIco) -or `
           (Get-Item $faviconPng).LastWriteTime -gt (Get-Item $faviconIco).LastWriteTime
if ($needIco) {
    Write-Host "favicon.ico 缺失或过期 → 用 Pillow 从 favicon.png 重生成…" -ForegroundColor Yellow
    & uv run python -c @"
from PIL import Image
src = Image.open(r'$faviconPng').convert('RGBA')
src.save(r'$faviconIco', format='ICO', sizes=[(256,256),(128,128),(64,64),(48,48),(32,32),(16,16)])
"@
    if ($LASTEXITCODE -ne 0) {
        Write-Host "[错误] favicon.ico 生成失败（Pillow 是否在 venv？）" -ForegroundColor Red
        exit 1
    }
}

# ── pyproject.toml version 提取 ───────────────────────────────────────────────
$version = & uv run python -c "import tomllib; print(tomllib.load(open(r'$pyproject','rb'))['project']['version'])" 2>&1
if ($LASTEXITCODE -ne 0 -or [string]::IsNullOrWhiteSpace($version)) {
    Write-Host "[错误] 无法从 pyproject.toml 读取 [project].version: $version" -ForegroundColor Red
    exit 1
}
$version = $version.Trim()
Write-Host "Version: $version (来自 pyproject.toml) | Target: $Target" -ForegroundColor Cyan

# ── Nuitka 安装检查 ───────────────────────────────────────────────────────────
& uv run python -c "import nuitka" *>$null
if ($LASTEXITCODE -ne 0) {
    Write-Host "Nuitka 未安装，正在 uv add nuitka…" -ForegroundColor Yellow
    & uv add --dev nuitka
    if ($LASTEXITCODE -ne 0) { Write-Host "[错误] uv add nuitka 失败" -ForegroundColor Red; exit 1 }
}

# GUI build 还需要 PySide6 在 venv 里（即便不带 --extra gui sync 的人也得跑得起 build）
if ($Target -eq 'gui' -or $Target -eq 'both') {
    & uv run python -c "import PySide6" *>$null
    if ($LASTEXITCODE -ne 0) {
        Write-Host "PySide6 未安装（GUI build 需要），uv sync --extra gui…" -ForegroundColor Yellow
        & uv sync --extra gui
        if ($LASTEXITCODE -ne 0) { Write-Host "[错误] uv sync --extra gui 失败" -ForegroundColor Red; exit 1 }
    }
}

# ── Clean 模式 ────────────────────────────────────────────────────────────────
if ($Clean) {
    foreach ($d in @($cliOutDir, $guiOutDir, $cliBuildDir, $guiBuildDir)) {
        if (Test-Path $d) {
            Write-Host "Removing $d" -ForegroundColor Yellow
            Remove-Item -Recurse -Force $d
        }
    }
    $nuitkaCache = Join-Path $env:LOCALAPPDATA "Nuitka\Nuitka\Cache"
    if (Test-Path $nuitkaCache) {
        Write-Host "Clearing Nuitka cache: $nuitkaCache" -ForegroundColor Yellow
        Remove-Item -Recurse -Force $nuitkaCache -ErrorAction SilentlyContinue
    }
}

# ── 公共：编译产物 → 分发 zip ─────────────────────────────────────────────────
function Pack-Distribution {
    param(
        [Parameter(Mandatory)] [string] $OutDir,     # dist-exe / dist-exe-gui
        [Parameter(Mandatory)] [string] $StagingName # unicap-cli-1.0.7 / unicap-gui-1.0.7
    )
    $staging = Join-Path $root $StagingName
    $zip     = Join-Path $root "$StagingName.zip"
    if (Test-Path $staging) { Remove-Item -Recurse -Force $staging }
    if (Test-Path $zip)     { Remove-Item -Force $zip }

    Add-Type -AssemblyName System.IO.Compression.FileSystem
    Move-Item -Path $OutDir -Destination $staging
    try {
        [System.IO.Compression.ZipFile]::CreateFromDirectory(
            $staging, $zip, [System.IO.Compression.CompressionLevel]::Optimal, $true
        )
    } finally {
        # 还原产物目录，方便就地运行
        Move-Item -Path $staging -Destination $OutDir
    }
    return $zip
}

# ── CLI build ─────────────────────────────────────────────────────────────────
function Build-Cli {
    Write-Host "`n========== CLI build ==========" -ForegroundColor Magenta

    # 中间目录每次重建（避免 Nuitka 看到旧 dist 直接 reuse）
    if (Test-Path $cliBuildDir) { Remove-Item -Recurse -Force $cliBuildDir }
    New-Item -ItemType Directory -Force -Path $cliBuildDir | Out-Null

    Write-Host "构建 Nuitka standalone (CLI)…" -ForegroundColor Green
    Write-Host "  中间: $cliBuildDir\main.dist\" -ForegroundColor Gray
    Write-Host "  最终: $cliOutDir\unicap.exe" -ForegroundColor Gray

    Push-Location $root
    try {
        & uv run python -m nuitka `
            --standalone `
            --assume-yes-for-downloads `
            --lto=yes `
            --remove-output `
            --output-dir=$cliBuildDir `
            --output-filename=unicap.exe `
            --include-package=tools `
            --include-data-dir=dist=dist `
            --include-data-files=dist/dxgi.dll=dist/dxgi.dll `
            --include-data-files=dist/UniCap64.dll=dist/UniCap64.dll `
            --include-data-dir=shaders=shaders `
            --include-data-dir=config=config `
            --include-data-dir=profiles=profiles `
            --include-data-files=pyproject.toml=pyproject.toml `
            --include-data-files=favicon.png=favicon.png `
            --windows-icon-from-ico=$faviconIco `
            --product-name=unicap `
            --file-version=$version `
            --product-version=$version `
            --file-description="unicap game capture pipeline" `
            --company-name=unicap `
            $mainPy
        $code = $LASTEXITCODE
    } finally {
        Pop-Location
    }
    if ($code -ne 0) {
        Write-Host "`n[错误] Nuitka CLI 构建失败 (exit $code)" -ForegroundColor Red
        exit $code
    }

    # 整理产物
    $nuitkaDist = Join-Path $cliBuildDir "main.dist"
    if (-not (Test-Path (Join-Path $nuitkaDist "unicap.exe"))) {
        Write-Host "[错误] $nuitkaDist\unicap.exe 未生成" -ForegroundColor Red
        exit 1
    }
    if (Test-Path $cliOutDir) { Remove-Item -Recurse -Force $cliOutDir }
    Move-Item -Path $nuitkaDist -Destination $cliOutDir
    Remove-Item -Recurse -Force $cliBuildDir -ErrorAction SilentlyContinue

    # 校验关键资产
    $required = @(
        "unicap.exe",
        "dist\dxgi.dll", "dist\UniCap64.dll", "dist\UniCap64.json", "dist\frame_capture.addon",
        "shaders\DepthToAddon.fx",
        "profiles\_default.yaml", "profiles\ff7r.yaml",
        "favicon.png"
    )
    $missing = @()
    foreach ($rel in $required) {
        if (-not (Test-Path (Join-Path $cliOutDir $rel))) { $missing += $rel }
    }
    if ($missing.Count -gt 0) {
        Write-Host "[错误] CLI 关键资产缺失：" -ForegroundColor Red
        $missing | ForEach-Object { Write-Host "  - $_" -ForegroundColor Red }
        exit 1
    }

    $zipPath = Pack-Distribution -OutDir $cliOutDir -StagingName "unicap-cli-$version"

    $exeMB    = [math]::Round((Get-Item (Join-Path $cliOutDir "unicap.exe")).Length / 1MB, 1)
    $totalMB  = [math]::Round(((Get-ChildItem $cliOutDir -Recurse | Measure-Object -Property Length -Sum).Sum) / 1MB, 1)
    $fileCnt  = (Get-ChildItem $cliOutDir -Recurse -File).Count
    $zipMB    = [math]::Round((Get-Item $zipPath).Length / 1MB, 1)
    Write-Host "`nCLI 构建成功 ✓" -ForegroundColor Green
    Write-Host "  unicap.exe: $exeMB MB" -ForegroundColor White
    Write-Host "  总大小:     $totalMB MB ($fileCnt 个文件)" -ForegroundColor White
    Write-Host "  位置:       $cliOutDir\" -ForegroundColor White
    Write-Host "  分发包:     $zipPath ($zipMB MB)" -ForegroundColor White
}

# ── GUI build (multidist: unicap.exe + unicap-gui.exe) ────────────────────────
function Build-Gui {
    Write-Host "`n========== GUI build (multidist) ==========" -ForegroundColor Magenta

    # buildDir 可能被 antivirus / explorer 持锁导致 Remove 失败 → 改用 timestamp 后缀。
    # 旧目录留在磁盘上不影响新 build；下次 -Clean 一并清理。
    $localBuildDir = $guiBuildDir
    if (Test-Path $localBuildDir) {
        try {
            Remove-Item -Recurse -Force $localBuildDir -ErrorAction Stop
        } catch {
            $stamp = Get-Date -Format 'yyyyMMddHHmmss'
            $localBuildDir = "$guiBuildDir-$stamp"
            Write-Host "[警告] 旧 buildDir 被锁，改用 $localBuildDir" -ForegroundColor Yellow
        }
    }
    New-Item -ItemType Directory -Force -Path $localBuildDir | Out-Null

    # multidist 按文件 basename 命名 exe — 必须让源文件叫 unicap.py / unicap-gui.py
    # 这俩是 build-time temp 文件（gitignored），出口在 finally 删
    $cliEntry = Join-Path $root "unicap.py"
    $guiEntry = Join-Path $root "unicap-gui.py"

    Copy-Item -Path $mainPy -Destination $cliEntry -Force

    @"
"""multidist GUI entry — Nuitka 将其编译为 unicap-gui.exe（与 unicap.exe 共享 runtime）。"""
from unicap_gui.__main__ import main
import sys
sys.exit(main())
"@ | Set-Content -Path $guiEntry -Encoding utf8

    Write-Host "构建 Nuitka multidist standalone (CLI + GUI 共享 runtime)…" -ForegroundColor Green
    Write-Host "  中间: $localBuildDir\unicap.dist\" -ForegroundColor Gray
    Write-Host "  最终: $guiOutDir\{unicap.exe,unicap-gui.exe}" -ForegroundColor Gray
    Write-Host "  首次构建 PySide6 + cv2/numpy/h5py 编译可能 10-15 分钟" -ForegroundColor Gray

    Push-Location $root
    try {
        & uv run python -m nuitka `
            --standalone `
            --assume-yes-for-downloads `
            --lto=yes `
            --remove-output `
            --output-dir=$localBuildDir `
            --enable-plugin=pyside6 `
            --include-package=tools `
            --include-package=unicap_gui `
            --noinclude-qt-translations `
            --nofollow-import-to=PySide6.QtWebEngineCore `
            --nofollow-import-to=PySide6.QtWebEngineWidgets `
            --nofollow-import-to=PySide6.QtWebEngineQuick `
            --nofollow-import-to=PySide6.QtMultimedia `
            --nofollow-import-to=PySide6.QtMultimediaWidgets `
            --nofollow-import-to=PySide6.QtPdf `
            --nofollow-import-to=PySide6.QtPdfWidgets `
            --nofollow-import-to=PySide6.QtCharts `
            --nofollow-import-to=PySide6.QtDataVisualization `
            --nofollow-import-to=PySide6.Qt3DCore `
            --nofollow-import-to=PySide6.Qt3DRender `
            --nofollow-import-to=PySide6.QtBluetooth `
            --nofollow-import-to=PySide6.QtNetworkAuth `
            --nofollow-import-to=PySide6.QtPositioning `
            --nofollow-import-to=PySide6.QtSensors `
            --nofollow-import-to=PySide6.QtSerialPort `
            --nofollow-import-to=PySide6.QtTest `
            --nofollow-import-to=PySide6.QtWebChannel `
            --nofollow-import-to=PySide6.QtWebSockets `
            --include-data-dir=dist=dist `
            --include-data-files=dist/dxgi.dll=dist/dxgi.dll `
            --include-data-files=dist/UniCap64.dll=dist/UniCap64.dll `
            --include-data-dir=shaders=shaders `
            --include-data-dir=config=config `
            --include-data-dir=profiles=profiles `
            --include-data-files=pyproject.toml=pyproject.toml `
            --include-data-files=favicon.png=favicon.png `
            --windows-icon-from-ico=$faviconIco `
            --product-name=unicap `
            --file-version=$version `
            --product-version=$version `
            --file-description="unicap game capture pipeline (GUI bundle)" `
            --company-name=unicap `
            --main=$cliEntry `
            --main=$guiEntry
        $code = $LASTEXITCODE
    } finally {
        Pop-Location
        Remove-Item -Path $cliEntry, $guiEntry -ErrorAction SilentlyContinue
    }
    if ($code -ne 0) {
        Write-Host "`n[错误] Nuitka GUI 构建失败 (exit $code)" -ForegroundColor Red
        exit $code
    }

    # multidist：dist 目录用第一个 main 的名字 (unicap.dist)
    # Nuitka 4.0.8 实际只产出单 binary unicap.exe — 它内嵌所有 main，
    # 运行时用 argv[0] basename 分发。复制一份重命名为 unicap-gui.exe，
    # 双 exe 共享 Python runtime，启动时各自走对应 entry。
    $nuitkaDist = Join-Path $localBuildDir "unicap.dist"
    $multidistExe = Join-Path $nuitkaDist "unicap.exe"
    if (-not (Test-Path $multidistExe)) {
        Write-Host "[错误] $multidistExe 未生成" -ForegroundColor Red
        exit 1
    }
    Copy-Item -Path $multidistExe -Destination (Join-Path $nuitkaDist "unicap-gui.exe") -Force
    if (Test-Path $guiOutDir) {
        try {
            Remove-Item -Recurse -Force $guiOutDir -ErrorAction Stop
        } catch {
            $stamp = Get-Date -Format 'yyyyMMddHHmmss'
            Rename-Item -Path $guiOutDir -NewName "$(Split-Path -Leaf $guiOutDir).old-$stamp" -ErrorAction SilentlyContinue
            if (Test-Path $guiOutDir) {
                Write-Host "[错误] 旧 $guiOutDir 被锁，无法清理。请关闭 Explorer 等占用进程后重试。" -ForegroundColor Red
                exit 1
            }
        }
    }
    Move-Item -Path $nuitkaDist -Destination $guiOutDir
    Remove-Item -Recurse -Force $localBuildDir -ErrorAction SilentlyContinue

    # 校验关键资产
    $required = @(
        "unicap.exe", "unicap-gui.exe",
        "dist\dxgi.dll", "dist\UniCap64.dll", "dist\UniCap64.json", "dist\frame_capture.addon",
        "shaders\DepthToAddon.fx",
        "profiles\_default.yaml", "profiles\ff7r.yaml"
    )
    $missing = @()
    foreach ($rel in $required) {
        if (-not (Test-Path (Join-Path $guiOutDir $rel))) { $missing += $rel }
    }
    if ($missing.Count -gt 0) {
        Write-Host "[错误] GUI 关键资产缺失：" -ForegroundColor Red
        $missing | ForEach-Object { Write-Host "  - $_" -ForegroundColor Red }
        exit 1
    }

    $zipPath = Pack-Distribution -OutDir $guiOutDir -StagingName "unicap-gui-$version"

    $cliExeMB = [math]::Round((Get-Item (Join-Path $guiOutDir "unicap.exe")).Length / 1MB, 1)
    $guiExeMB = [math]::Round((Get-Item (Join-Path $guiOutDir "unicap-gui.exe")).Length / 1MB, 1)
    $totalMB  = [math]::Round(((Get-ChildItem $guiOutDir -Recurse | Measure-Object -Property Length -Sum).Sum) / 1MB, 1)
    $fileCnt  = (Get-ChildItem $guiOutDir -Recurse -File).Count
    $zipMB    = [math]::Round((Get-Item $zipPath).Length / 1MB, 1)
    Write-Host "`nGUI 构建成功 ✓" -ForegroundColor Green
    Write-Host "  unicap.exe:     $cliExeMB MB (multidist 第一入口)" -ForegroundColor White
    Write-Host "  unicap-gui.exe: $guiExeMB MB (multidist 第二入口)" -ForegroundColor White
    Write-Host "  总大小:         $totalMB MB ($fileCnt 个文件，含 PySide6)" -ForegroundColor White
    Write-Host "  位置:           $guiOutDir\" -ForegroundColor White
    Write-Host "  分发包:         $zipPath ($zipMB MB)" -ForegroundColor White
}

# ── 主流程 ────────────────────────────────────────────────────────────────────
if ($Target -eq 'cli' -or $Target -eq 'both') { Build-Cli }
if ($Target -eq 'gui' -or $Target -eq 'both') { Build-Gui }

Write-Host "`n全部构建完成 ✓" -ForegroundColor Green
Write-Host "分发：" -ForegroundColor Cyan
if ($Target -eq 'cli' -or $Target -eq 'both') {
    Write-Host "  - unicap-cli-$version.zip   （仅 CLI，体积小）" -ForegroundColor Cyan
}
if ($Target -eq 'gui' -or $Target -eq 'both') {
    Write-Host "  - unicap-gui-$version.zip   （GUI + 内嵌 CLI，self-contained）" -ForegroundColor Cyan
}
