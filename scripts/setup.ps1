#!/usr/bin/env pwsh
# setup.ps1 — 初始化所有 git submodule 依赖
# 首次运行：克隆 reshade / reshade-addons / murchFX 并切换到正确版本
# 后续运行：幂等，已存在则跳过
#
# 已知问题 & 解决方案（在此机器上验证）：
#   - Windows Schannel TLS 不稳定 → git config http.version HTTP/1.1 + http.postBuffer 524288000
#   - git submodule update --recursive 并发克隆失败 → 逐个串行 fix_dep 兜底
#   - reshade deps/ 需要精确 commit（非最新），浅克隆需单独 fetch by SHA
Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

$root = Split-Path $PSScriptRoot -Parent

# ── 0. 修复 Schannel TLS 不稳定问题 ──────────────────────────────────────────
git config --global http.version HTTP/1.1
git config --global http.postBuffer 524288000

function Add-Sub($url, $path, $tag = $null) {
    $full = Join-Path $root $path
    if (Test-Path (Join-Path $full ".git")) {
        Write-Host "[$path] already present, skipping" -ForegroundColor Cyan
    } else {
        Write-Host "Adding submodule: $path" -ForegroundColor Green
        git -C $root submodule add --depth 1 $url $path
    }
    if ($tag) {
        Write-Host "[$path] fetching tag $tag..." -ForegroundColor Yellow
        git -C $full fetch --depth 1 origin "refs/tags/${tag}:refs/tags/${tag}" 2>$null
        git -C $full checkout $tag
    }
}

function Fix-Dep($name, $url, $commit) {
    $dir = Join-Path $root "reshade/deps/$name"
    $realFiles = (Get-ChildItem -Path $dir -Recurse -File -ErrorAction SilentlyContinue |
                  Where-Object { $_.FullName -notmatch '\\.git\\' } | Measure-Object).Count
    if ($realFiles -gt 0) {
        Write-Host "  [OK] $name ($realFiles files)" -ForegroundColor Cyan
        return
    }
    Write-Host "  [FIX] $name → $commit" -ForegroundColor Yellow
    Remove-Item -Recurse -Force $dir -ErrorAction SilentlyContinue
    New-Item -ItemType Directory -Path $dir -Force | Out-Null
    git -C $dir init -q
    git -C $dir remote add origin $url
    git -C $dir fetch --depth 1 origin $commit 2>&1
    git -C $dir checkout FETCH_HEAD 2>&1
}

# ── 1. ReShade core (locked to v5.9.2) ───────────────────────────────────────
Add-Sub "https://github.com/crosire/reshade.git" "reshade" "v5.9.2"

Write-Host "[reshade] initializing nested deps submodules..." -ForegroundColor Green
git -C $root submodule update --init --recursive -- reshade 2>&1 | Write-Host

# 兜底：用精确 commit 补全仍为空的 deps（并发克隆失败时的安全网）
Write-Host "[reshade] verifying/fixing deps to exact pinned commits..." -ForegroundColor Green
$reshadeRoot = Join-Path $root "reshade"
Fix-Dep "imgui"             "https://github.com/ocornut/imgui.git"                                  "3912b3d9a9c1b3f17431aebafd86d2f40ee6e59c"
Fix-Dep "vma"               "https://github.com/GPUOpen-LibrariesAndSDKs/VulkanMemoryAllocator"     "1076b348abd17859a116f4b111c43d58a588a086"
Fix-Dep "d3d12"             "https://github.com/microsoft/DirectX-Headers.git"                      "9e393d6d8a3b30dcc6f2806ef604ec16a27b0d7e"
Fix-Dep "glad"              "https://github.com/Dav1dde/glad"                                       "27bed1181560211b55e39a9b132fef8c5846aae5"
Fix-Dep "minhook"           "https://github.com/TsudaKageyu/minhook.git"                            "8fda4f5481fed5797dc2651cd91e238e9b3928c6"
Fix-Dep "stb"               "https://github.com/nothings/stb.git"                                   "28d546d5eb77d4585506a20480f4de2e706dff4c"
Fix-Dep "spirv"             "https://github.com/KhronosGroup/SPIRV-Headers.git"                     "7845730cab6ebbdeb621e7349b7dc1a59c3377be"
Fix-Dep "utfcpp"            "https://github.com/nemtrif/utfcpp.git"                                 "63d64de49fd6b829f7c8694df5ab2ee625cb7134"
Fix-Dep "openxr"            "https://github.com/KhronosGroup/OpenXR-SDK.git"                        "288d3a7ebc1ad959f62d51da75baa3d27438c499"
Fix-Dep "fpng"              "https://github.com/richgel999/fpng"                                    "925796543b9d26b8edfcdcecd94c1dac280f29fc"
Fix-Dep "jxl_simple_lossless" "https://github.com/kampidh/simple-lossless-encoder.git"              "8dc970fc771e35239db55dfbce8f46f83f8e9b73"

# ── 2. frame_capture addon source ────────────────────────────────────────────
Add-Sub "https://github.com/murchalloo/reshade-addons.git" "reshade-addons"
Write-Host "[reshade-addons] initializing nested submodules..." -ForegroundColor Green
git -C $root submodule update --init --recursive -- reshade-addons 2>&1 | Write-Host

# ── 3. murchFX shaders (DepthToAddon.fx) ─────────────────────────────────────
Add-Sub "https://github.com/murchalloo/murchFX.git" "murchFX"

Write-Host "`nSetup complete." -ForegroundColor Green
Write-Host "Next step: run scripts\build.ps1" -ForegroundColor White
