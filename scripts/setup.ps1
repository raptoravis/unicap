#!/usr/bin/env pwsh
# setup.ps1 — 初始化所有 git submodule 依赖
# 首次运行：克隆 reshade / reshade-addons / murchFX 并切换到指定版本
# 后续运行：幂等，已存在则跳过
Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

$root = Split-Path $PSScriptRoot -Parent

function Add-Sub($url, $path, $tag = $null) {
    $full = Join-Path $root $path
    if (Test-Path (Join-Path $full ".git")) {
        Write-Host "[$path] already present, skipping" -ForegroundColor Cyan
    } else {
        Write-Host "Adding submodule: $path" -ForegroundColor Green
        git -C $root submodule add $url $path
    }
    if ($tag) {
        Write-Host "[$path] checking out $tag" -ForegroundColor Yellow
        git -C $full checkout $tag
    }
}

# ── 1. ReShade core (locked to v5.9.2 — DO NOT upgrade to 6.x) ──────────────
Add-Sub "https://github.com/crosire/reshade.git" "reshade" "v5.9.2"
Write-Host "[reshade] initializing nested deps submodules..." -ForegroundColor Green
git -C $root submodule update --init --recursive -- reshade

# ── 2. frame_capture addon source ────────────────────────────────────────────
Add-Sub "https://github.com/murchalloo/reshade-addons.git" "reshade-addons"
Write-Host "[reshade-addons] initializing nested submodules (stb, etc.)..." -ForegroundColor Green
git -C $root submodule update --init --recursive -- reshade-addons

# ── 3. murchFX shaders (DepthToAddon.fx) ─────────────────────────────────────
Add-Sub "https://github.com/murchalloo/murchFX.git" "murchFX"

Write-Host "`nSetup complete." -ForegroundColor Green
Write-Host "Next step: run scripts\build.ps1" -ForegroundColor White
