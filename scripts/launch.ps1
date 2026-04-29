#!/usr/bin/env pwsh
# launch.ps1 — FF7 Remake 深度采集一键拉起
#
# 模式：
#   --mode custom      (默认) 使用 dist/ 中的自定义 ReShade + addon
#   --mode official592  使用 vendor/reshade592/dxgi.dll + 官方 addon
#   --mode official673  使用 vendor/reshade673/dxgi.dll + 官方 addon
#
# 用法：
#   scripts\launch.ps1                        # 自定义模式，30fps
#   scripts\launch.ps1 --mode official592     # 官方 5.9.2 测试
#   scripts\launch.ps1 --mode custom --fps 60 # 60fps
#   scripts\launch.ps1 --deploy-only          # 只部署，不启动采集
#
# 前置条件：
#   - FF7 Remake 已安装到 GAME_WIN64 路径
#   - Python 已安装（capture_all.py 依赖）
#   - custom 模式需先执行 scripts\build.ps1

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

param(
    [ValidateSet("custom", "official592", "official673")]
    [string]$Mode = "custom",

    [int]$Fps = 30,

    [float]$Duration = 0,   # 0 = 无限，Ctrl+C 停止

    [switch]$DeployOnly      # 只部署 DLL/addon，不启动 Python 管线
)

$root       = Split-Path $PSScriptRoot -Parent
$gameWin64  = "E:\games\ff7remake\End\Binaries\Win64"
$captureDir = Join-Path $root "tools\capture"

# ── 选择源文件 ─────────────────────────────────────────────────────────────────
switch ($Mode) {
    "custom" {
        $srcDll    = Join-Path $root "dist\dxgi.dll"
        $srcAddon  = Join-Path $root "dist\frame_capture.addon"
        $shaderSrc = Join-Path $root "dist\reshade-shaders\Shaders"
        $deployShaders = $true
    }
    "official592" {
        $srcDll    = Join-Path $root "vendor\reshade592\dxgi.dll"
        $srcAddon  = Join-Path $root "vendor\addon_official\frame_capture.addon"
        $deployShaders = $false
    }
    "official673" {
        $srcDll    = Join-Path $root "vendor\reshade673\dxgi.dll"
        $srcAddon  = Join-Path $root "vendor\addon_official\frame_capture.addon"
        $deployShaders = $false
    }
}

# ── 验证源文件存在 ─────────────────────────────────────────────────────────────
foreach ($f in @($srcDll, $srcAddon)) {
    if (-not (Test-Path $f)) {
        Write-Error "找不到文件：$f`n请先运行 scripts\build.ps1（custom 模式）或检查 vendor/ 目录"
        exit 1
    }
}

if (-not (Test-Path $gameWin64)) {
    Write-Error "游戏目录不存在：$gameWin64`n请修改 launch.ps1 中的 `$gameWin64 变量"
    exit 1
}

# ── 部署 ───────────────────────────────────────────────────────────────────────
Write-Host "[ DEPLOY ] 模式: $Mode → $gameWin64" -ForegroundColor Cyan

$dstDll   = Join-Path $gameWin64 "dxgi.dll"
$dstAddon = Join-Path $gameWin64 "frame_capture.addon"

# 备份现有 dxgi.dll（仅当不是我们上次部署的）
if (Test-Path $dstDll) {
    $bak = "$dstDll.bak"
    if (-not (Test-Path $bak)) {
        Copy-Item $dstDll $bak -Force
        Write-Host "         已备份 dxgi.dll → dxgi.dll.bak" -ForegroundColor Yellow
    }
}

Copy-Item $srcDll   $dstDll   -Force
Copy-Item $srcAddon $dstAddon -Force
Write-Host "         dxgi.dll + frame_capture.addon 已部署" -ForegroundColor Green

if ($deployShaders) {
    $shaderDst = Join-Path $gameWin64 "reshade-shaders\Shaders"
    New-Item -ItemType Directory -Force -Path $shaderDst | Out-Null
    Copy-Item (Join-Path $shaderSrc "DepthToAddon.fx") $shaderDst -Force
    Copy-Item (Join-Path $shaderSrc "UIRemove.fx")     $shaderDst -Force
    Write-Host "         Shaders 已部署 → $shaderDst" -ForegroundColor Green
}

if ($DeployOnly) {
    Write-Host "`n[ DONE ] 仅部署，未启动采集管线" -ForegroundColor Green
    exit 0
}

# ── 启动 Python 采集管线 ──────────────────────────────────────────────────────
Write-Host ""
Write-Host "[ CAPTURE ] 启动采集管线 fps=$Fps$(if ($Duration -gt 0) { " 时长=${Duration}s" } else { ' (Ctrl+C 停止)' })" -ForegroundColor Cyan
Write-Host "            脚本目录: $captureDir" -ForegroundColor Gray
Write-Host ""

$pyArgs = @("capture_all.py", "$Fps")
if ($Duration -gt 0) { $pyArgs += "$Duration" }

Set-Location $captureDir
try {
    python @pyArgs
} finally {
    Set-Location $root
}
