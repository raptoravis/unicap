#!/usr/bin/env pwsh
# build-exe.ps1 — Nuitka standalone build of main.py.
# 输出: dist-exe\unicap.exe (+ Python 运行时 + 资产文件夹).
#
# Usage:
#   scripts\build-exe.ps1            # incremental build (use Nuitka cache)
#   scripts\build-exe.ps1 -Clean     # delete dist-exe + Nuitka cache 全量重建
#
# 依赖: uv + Nuitka (脚本会自动 uv add 一次)。
# 构建期会调用 MSVC (cl.exe) — 需 VS 2022 已安装 (与 build.ps1 一致)。
#
# 为什么 standalone 而不是 onefile:
#   onefile 的 bootloader 解压主 dll 到 %TEMP%，被 Windows Defender 标记为
#   "potentially unwanted" 概率极高 (Nuitka 加壳特征 = 常见恶意软件签名)。
#   standalone 把 dll 留在文件夹里, AV 容忍度好得多, 同时反破解强度不变 —
#   unicap.exe 仍是 Python→C→机器码的 Nuitka 产物。
#   分发: zip dist-exe\ 整个文件夹给最终用户。

param(
    [switch]$Clean
)

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

$root      = Split-Path $PSScriptRoot -Parent
$outDir    = Join-Path $root "dist-exe"
$buildDir  = Join-Path $root "dist-exe-build"   # Nuitka 中间产物
$distDir   = Join-Path $root "dist"
$mainPy    = Join-Path $root "main.py"
$pyproject = Join-Path $root "pyproject.toml"

# ── 前置检查 ──────────────────────────────────────────────────────────────────
if (-not (Test-Path (Join-Path $distDir "dxgi.dll"))) {
    Write-Host "[错误] dist\dxgi.dll 不存在 — 先跑 scripts\build.ps1 构建 C++ 部分。" -ForegroundColor Red
    exit 1
}
if (-not (Test-Path (Join-Path $distDir "frame_capture.addon"))) {
    Write-Host "[错误] dist\frame_capture.addon 不存在 — 先跑 scripts\build.ps1。" -ForegroundColor Red
    exit 1
}

# ── pyproject.toml version 提取 ───────────────────────────────────────────────
$version = & uv run python -c "import tomllib; print(tomllib.load(open(r'$pyproject','rb'))['project']['version'])" 2>&1
if ($LASTEXITCODE -ne 0 -or [string]::IsNullOrWhiteSpace($version)) {
    Write-Host "[错误] 无法从 pyproject.toml 读取 [project].version: $version" -ForegroundColor Red
    exit 1
}
$version = $version.Trim()
Write-Host "Version: $version (来自 pyproject.toml)" -ForegroundColor Cyan

# ── Nuitka 安装检查 ───────────────────────────────────────────────────────────
& uv run python -c "import nuitka" *>$null
if ($LASTEXITCODE -ne 0) {
    Write-Host "Nuitka 未安装，正在 uv add nuitka…" -ForegroundColor Yellow
    & uv add --dev nuitka
    if ($LASTEXITCODE -ne 0) { Write-Host "[错误] uv add nuitka 失败" -ForegroundColor Red; exit 1 }
}

# ── Clean 模式 ────────────────────────────────────────────────────────────────
if ($Clean) {
    foreach ($d in @($outDir, $buildDir)) {
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

# 中间目录每次重建 (避免 Nuitka 看到旧 main.dist 直接 reuse)
if (Test-Path $buildDir) {
    Remove-Item -Recurse -Force $buildDir
}
New-Item -ItemType Directory -Force -Path $buildDir | Out-Null

# ── Nuitka 构建 ───────────────────────────────────────────────────────────────
# 反破解关键 flag:
#   --standalone             生成自包含文件夹 (不嵌入到单 exe，避免 AV 误报)
#   --lto=yes                LTO 优化, 函数边界模糊化
#   --remove-output          删除中间 .build/ 目录, 不留 .c 源
#   --no-pyi-file            不生成 .pyi 接口文件
#   --assume-yes-for-downloads  自动下载 depends.exe (首次)

Write-Host "`n构建 Nuitka standalone…" -ForegroundColor Green
Write-Host "  中间: $buildDir\main.dist\" -ForegroundColor Gray
Write-Host "  最终: $outDir\unicap.exe" -ForegroundColor Gray
Write-Host "  首次构建可能耗时 5-10 分钟 (编译 cv2/numpy/h5py 适配层)" -ForegroundColor Gray

Push-Location $root
try {
    & uv run python -m nuitka `
        --standalone `
        --assume-yes-for-downloads `
        --lto=yes `
        --remove-output `
        --output-dir=$buildDir `
        --output-filename=unicap.exe `
        --include-package=tools `
        --include-package=cv2 `
        --include-package=h5py `
        --include-package=numpy `
        --include-data-dir=dist=dist `
        --include-data-files=dist/dxgi.dll=dist/dxgi.dll `
        --include-data-dir=shaders=shaders `
        --include-data-dir=config=config `
        --include-data-files=pyproject.toml=pyproject.toml `
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
    Write-Host "`n[错误] Nuitka 构建失败 (exit $code)" -ForegroundColor Red
    exit $code
}

# ── 整理产物：buildDir\main.dist\* → outDir\ ─────────────────────────────────
$nuitkaDist = Join-Path $buildDir "main.dist"
if (-not (Test-Path (Join-Path $nuitkaDist "unicap.exe"))) {
    Write-Host "`n[错误] $nuitkaDist\unicap.exe 未生成 — 检查 Nuitka 输出" -ForegroundColor Red
    exit 1
}

if (Test-Path $outDir) {
    Remove-Item -Recurse -Force $outDir
}
Move-Item -Path $nuitkaDist -Destination $outDir
Remove-Item -Recurse -Force $buildDir -ErrorAction SilentlyContinue

# ── 校验关键资产 ──────────────────────────────────────────────────────────────
$exe = Join-Path $outDir "unicap.exe"
$required = @(
    "dist\dxgi.dll",
    "dist\frame_capture.addon",
    "shaders\DepthToAddon.fx",
    "config\unicapPreset.ini"
)
$missing = @()
foreach ($rel in $required) {
    if (-not (Test-Path (Join-Path $outDir $rel))) { $missing += $rel }
}
if ($missing.Count -gt 0) {
    Write-Host "`n[错误] 关键资产缺失（构建配置需修正）：" -ForegroundColor Red
    $missing | ForEach-Object { Write-Host "  - $_" -ForegroundColor Red }
    exit 1
}

# ── 打包 zip 分发包 ───────────────────────────────────────────────────────────
# zip 内顶级目录 = unicap-<version>/，解压不污染当前目录
$staging = Join-Path $root "unicap-$version"
$zip     = Join-Path $root "unicap-$version.zip"
if (Test-Path $staging) { Remove-Item -Recurse -Force $staging }
if (Test-Path $zip)     { Remove-Item -Force $zip }

Write-Host "`n打包分发 zip…" -ForegroundColor Cyan
Add-Type -AssemblyName System.IO.Compression.FileSystem
Move-Item -Path $outDir -Destination $staging
try {
    [System.IO.Compression.ZipFile]::CreateFromDirectory(
        $staging, $zip, [System.IO.Compression.CompressionLevel]::Optimal, $true
    )
} finally {
    # 还原 dist-exe/ 目录，方便就地运行
    Move-Item -Path $staging -Destination $outDir
}

# ── 报告 ──────────────────────────────────────────────────────────────────────
$exeMB    = [math]::Round((Get-Item $exe).Length / 1MB, 1)
$totalMB  = [math]::Round(((Get-ChildItem $outDir -Recurse | Measure-Object -Property Length -Sum).Sum) / 1MB, 1)
$fileCnt  = (Get-ChildItem $outDir -Recurse -File).Count
$zipMB    = [math]::Round((Get-Item $zip).Length / 1MB, 1)

Write-Host "`n构建成功 ✓" -ForegroundColor Green
Write-Host "  unicap.exe: $exeMB MB" -ForegroundColor White
Write-Host "  总大小:     $totalMB MB ($fileCnt 个文件)" -ForegroundColor White
Write-Host "  位置:       $outDir\" -ForegroundColor White
Write-Host "  分发包:     $zip ($zipMB MB)" -ForegroundColor White
Write-Host "  关键资产:   ✓ dxgi.dll / frame_capture.addon / shaders / config" -ForegroundColor Green
Write-Host "`n分发: 直接发 unicap-$version.zip。" -ForegroundColor Cyan
Write-Host "运行: $exe launch --help" -ForegroundColor Cyan
