#!/usr/bin/env pwsh
# deploy.ps1 — 将 dist/ 中的构建产物部署到游戏目录
# Usage:
#   scripts\deploy.ps1                              # 部署到默认游戏路径
#   scripts\deploy.ps1 -GameDir "D:\other\Win64"   # 指定其他路径
Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

param(
    [string]$GameDir = "E:\games\ff7remake\End\Binaries\Win64"
)

$root     = Split-Path $PSScriptRoot -Parent
$distDir  = Join-Path $root "dist"
$shaderDst = Join-Path $GameDir "reshade-shaders\Shaders"

if (-not (Test-Path $GameDir)) {
    Write-Error "Game directory not found: $GameDir"
    exit 1
}

# ── 备份现有 dxgi.dll（如果存在且不是我们的构建）────────────────────────────
$existing = Join-Path $GameDir "dxgi.dll"
if (Test-Path $existing) {
    $backup = "$existing.bak"
    Write-Host "Backing up existing dxgi.dll → dxgi.dll.bak" -ForegroundColor Yellow
    Copy-Item $existing $backup -Force
}

# ── 复制主 DLL 和 addon ───────────────────────────────────────────────────────
Write-Host "Deploying to: $GameDir" -ForegroundColor Green
Copy-Item (Join-Path $distDir "dxgi.dll")            $GameDir -Force
Copy-Item (Join-Path $distDir "frame_capture.addon") $GameDir -Force

# ── 复制 shaders ──────────────────────────────────────────────────────────────
New-Item -ItemType Directory -Force -Path $shaderDst | Out-Null
Copy-Item (Join-Path $distDir "reshade-shaders\Shaders\DepthToAddon.fx") $shaderDst -Force
Copy-Item (Join-Path $distDir "reshade-shaders\Shaders\UIRemove.fx")     $shaderDst -Force

Write-Host "Deploy complete." -ForegroundColor Green
Write-Host "  dxgi.dll, frame_capture.addon → $GameDir" -ForegroundColor Gray
Write-Host "  DepthToAddon.fx, UIRemove.fx  → $shaderDst" -ForegroundColor Gray
