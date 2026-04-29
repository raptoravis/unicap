#!/usr/bin/env pwsh
# build.ps1 — CMake configure + build (Release x64)
# Usage:
#   scripts\build.ps1              # normal build
#   scripts\build.ps1 -Rebuild     # force-rebuild ReShade core too

param(
    [switch]$Rebuild
)

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

$root     = Split-Path $PSScriptRoot -Parent
$buildDir = Join-Path $root "build"

# ── Configure ─────────────────────────────────────────────────────────────────
if (-not (Test-Path $buildDir)) {
    Write-Host "Configuring (first run)..." -ForegroundColor Green
    $extra = if ($Rebuild) { "-DRESHADE_ALWAYS_REBUILD=ON" } else { "" }
    cmake -S $root -B $buildDir `
        -G "Visual Studio 17 2022" -A x64 `
        $extra
} else {
    Write-Host "Build dir exists, skipping configure (delete build\ to reconfigure)" -ForegroundColor Cyan
}

# ── Build ──────────────────────────────────────────────────────────────────────
Write-Host "Building Release x64..." -ForegroundColor Green
cmake --build $buildDir --config Release --parallel

Write-Host "`nArtifacts in: $root\dist\" -ForegroundColor White
Write-Host "  dxgi.dll              (ReShade core)" -ForegroundColor Gray
Write-Host "  frame_capture.addon   (frame capture addon)" -ForegroundColor Gray
Write-Host "  reshade-shaders\Shaders\*.fx" -ForegroundColor Gray
Write-Host "`nNext steps:" -ForegroundColor White
Write-Host "  uv run main.py deploy          # deploy to game directory" -ForegroundColor Gray
Write-Host "  uv run main.py launch          # deploy + start capture" -ForegroundColor Gray
Write-Host "  uv run main.py capture         # capture only (no deploy)" -ForegroundColor Gray
