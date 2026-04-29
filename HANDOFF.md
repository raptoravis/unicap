# Handoff: ReShade 5.9.2 + frame_capture Addon 本地源码构建

**Generated**: 2026-04-29
**Branch**: master
**Status**: In Progress — 构建成功，待部署验证 + 后续定制开发

---

## Goal

将 FF7 Remake 帧捕获流水线所用的 ReShade 5.9.2 及 frame_capture addon 的源码
纳入本地 git 仓库（`D:\dev\reshade-custom\`），以 CMake + Visual Studio 2022 构建，
为后续自定义采集行为（内置 HTTP 控制、自动触发等）创造条件。

---

## Completed

- [x] 创建 `D:\dev\reshade-custom\` git 仓库，推送到 `github.com:raptoravis/reshade-custom`
- [x] 添加三个 git submodule：`reshade` (v5.9.2)、`reshade-addons`、`murchFX`
- [x] 解决 Windows Schannel TLS 不稳定导致的 deps 克隆失败（HTTP/1.1 + 串行兜底）
- [x] 将 reshade/deps/ 下 11 个子依赖全部校验并切换到 v5.9.2 要求的精确 commit
- [x] 编写 `CMakeLists.txt`（ExternalProject for ReShade core + add_library for addon）
- [x] 修复 5 个构建错误（见 Failed Approaches）
- [x] 首次构建成功，产物在 `dist/`：
  - `dxgi.dll` (5.4 MB)、`frame_capture.addon` (113 KB)
  - `reshade-shaders/Shaders/DepthToAddon.fx`、`UIRemove.fx`
- [x] `scripts/setup.ps1` 内置 deps 精确 commit 兜底，可在新机器一键复现

---

## Not Yet Done

- [ ] 运行 `scripts\deploy.ps1` 将 `dist/` 部署到游戏目录，验证与现有流水线兼容
- [ ] 用部署后的 `dxgi.dll + frame_capture.addon` 跑一次 10 秒小规模采集，确认功能与原预编译版本一致
- [ ] 后续定制方向（可选）：
  - 修改 `reshade-addons/99-frame_capture/frame_capture.cpp`，内置 HTTP 控制接口，消除 F10 键盘模拟
  - 将 frame_capture + UIRemove 合并为单一 `ff7r_capture.addon`

---

## Failed Approaches (Don't Repeat These)

### 1. `$ENV{ProgramFiles(x86)}` 在 CMake 中直接使用
**错误**：`Invalid character '(' in a variable name: 'ProgramFiles'`  
**修复**：改为硬编码路径或省略（VS 2022 Community 在标准 ProgramFiles 路径下）

### 2. MSBuild `/p:Platform=x64`
**错误**：`MSB4126: 指定的解决方案配置"Release|x64"无效`  
**原因**：ReShade.sln 的 Solution-level 平台名是 `64-bit`，不是 `x64`  
**修复**：`"/p:Platform=64-bit"`（需引号，因含连字符）

### 3. 期望输出文件是 `dxgi.dll`
**错误**：`Error copying file ".../reshade/bin/x64/Release/dxgi.dll": No such file or directory`  
**原因**：ReShade 构建出通用代理 `ReShade64.dll`，不直接输出 `dxgi.dll`  
**修复**：INSTALL_COMMAND 从 `ReShade64.dll` 复制并重命名为 `dxgi.dll`

### 4. frame_capture 使用 `reshade/include/`（v5.9.2 新 API）
**错误**：`error C1189: Unexpected ImGui version 19250` + `C2039: 'config_get_value' 不是 'reshade' 的成员`  
**原因**：
- `frame_capture.cpp` 用旧包装函数名 `reshade::log_message`/`reshade::config_get_value`，v5.9.2 已改名
- `reshade/include/reshade_overlay.hpp` 要求 imgui 19250，但 addon 是为 18600 写的  
**修复**：改用 `reshade-addons/deps/reshade/include`（旧包装 API）+ `reshade-addons/deps/imgui`（18600）  
**兼容性**：底层 C 导出名（`ReShadeLogMessage`、`ReShadeGetConfigValue`）在 v5.9.2 中与旧版完全相同，二进制兼容

### 5. `--depth 1` 浅克隆拉到最新 imgui/vma/d3d12 而非 v5.9.2 所需旧 commit
**错误**：`error C2061: 语法错误: ImGuiDockNodeFlags` 等大量 API 不兼容错误  
**原因**：imgui docking branch 在 commit `3912b3d` 之后修改了 API  
**修复**：对每个 dep 单独 `git fetch --depth 1 origin <exact-sha> && git checkout FETCH_HEAD`

### 6. `git submodule update --init --recursive` 并发克隆在 Windows Schannel 下频繁失败
**现象**：`schannel: server closed abruptly`，多个 deps 停留在空目录（只有 .git gitlink）  
**修复**：`git config http.version HTTP/1.1 + http.postBuffer 524288000` + setup.ps1 串行逐个 fix_dep 兜底

---

## Key Decisions

| 决策 | 理由 |
|------|------|
| ReShade 通过 ExternalProject + MSBuild 构建 | ReShade 无原生 CMake 支持；ExternalProject 包装 MSBuild 是最省力的正确路径 |
| frame_capture 用 addon 自带 reshade headers（旧 API 名）| 底层 C 导出不变，二进制兼容；避免改源码 |
| deps/ 不作为 submodule-in-submodule，而是直接 clone | reshade 的 submodule 机制在浅克隆 + 网络不稳时太脆，setup.ps1 串行 fix_dep 更可靠 |
| ReShade 版本锁死 v5.9.2 | 6.x EXR 导出 API 已断，frame_capture.addon 会静默只产生 BMP |

---

## Current State

**Working**：
- `cmake -S . -B build -G "Visual Studio 17 2022" -A x64` + `cmake --build build --config Release` → 成功
- `dist/dxgi.dll`（5.4 MB）、`dist/frame_capture.addon`（113 KB）已生成
- `scripts/setup.ps1`：新机器一键初始化所有 deps（含精确 commit 兜底）
- `scripts/build.ps1` / `deploy.ps1` 可用

**Broken**：无

**Uncommitted Changes**：无（working tree clean）

---

## Files to Know

| 文件 | 说明 |
|------|------|
| `CMakeLists.txt` | 顶层构建，ExternalProject for ReShade core + add_library for addon |
| `scripts/setup.ps1` | 首次初始化，含所有 11 个 deps 的精确 commit SHA 兜底 |
| `scripts/build.ps1` | cmake configure（VS 17 2022 x64）+ build |
| `scripts/deploy.ps1` | `dist/` → 游戏目录，备份旧 dxgi.dll |
| `shaders/UIRemove.fx` | UE4 Reverse-Z UI 遮罩 shader（本 repo 维护的源码） |
| `reshade-addons/99-frame_capture/frame_capture.cpp` | addon 主源文件，后续定制改这里 |

---

## Code Context

### CMake 关键参数（不要改这些，有坑）

```cmake
"/p:Platform=64-bit"    # 必须是 64-bit，不是 x64（sln 层 platform 名）
/t:ReShade              # 只构建主项目，不构建 setup/inject
# 实际输出名：
set(RESHADE_DLL ".../reshade/bin/x64/Release/ReShade64.dll")

# frame_capture include 顺序（顺序重要）：
"${ADDON_ROOT}/deps/reshade/include"   # 旧包装 API：log_message / config_get_value
"${ADDON_ROOT}/deps/imgui"             # imgui 18600，匹配 addon 的 reshade_overlay.hpp
```

### deps 精确 commit（v5.9.2 所需，不要 pull 到新版）

```
imgui             3912b3d9a9c1b3f17431aebafd86d2f40ee6e59c
vma               1076b348abd17859a116f4b111c43d58a588a086
d3d12             9e393d6d8a3b30dcc6f2806ef604ec16a27b0d7e
glad              27bed1181560211b55e39a9b132fef8c5846aae5
minhook           8fda4f5481fed5797dc2651cd91e238e9b3928c6
stb               28d546d5eb77d4585506a20480f4de2e706dff4c
spirv             7845730cab6ebbdeb621e7349b7dc1a59c3377be
utfcpp            63d64de49fd6b829f7c8694df5ab2ee625cb7134
openxr            288d3a7ebc1ad959f62d51da75baa3d27438c499
fpng              925796543b9d26b8edfcdcecd94c1dac280f29fc
jxl_simple_lossless  8dc970fc771e35239db55dfbce8f46f83f8e9b73
```

### 路径速查

```
游戏 Win64：  E:\games\ff7remake\End\Binaries\Win64\
源码仓库：    D:\dev\reshade-custom\
构建中间物：  D:\dev\reshade-custom\reshade\bin\x64\Release\ReShade64.dll
部署产物：    D:\dev\reshade-custom\dist\
```

### API 兼容性说明

```
v5.9.2 新 C++ 包装：  reshade::log::message()   / reshade::get_config_value()
addon 旧 C++ 包装：   reshade::log_message()    / reshade::config_get_value()
底层 C 导出（相同）：  ReShadeLogMessage()        / ReShadeGetConfigValue()
```

---

## Resume Instructions

### 1. 部署并验证功能（首要任务）

```powershell
cd D:\dev\reshade-custom
.\scripts\deploy.ps1
```

预期：游戏目录下 `dxgi.dll` 被更新，旧版备份为 `dxgi.dll.bak`。

然后启动游戏，配置 ReShade（见原始 HANDOFF.md 的 Resume Instructions），跑 10 秒验证：
```bash
python D:\ff7_tools\capture_all.py 30 10
python D:\ff7_tools\pack_hdf5.py
```
预期：`[SCAN] 模式=triplet, 帧数=~300`，最大对齐误差 < 10 ms。

### 2. 修改 addon 行为后重编部署

```powershell
# 只重编 addon（不触碰 ReShade core）
cmake --build D:\dev\reshade-custom\build --config Release --target frame_capture
.\scripts\deploy.ps1
```

### 3. 强制重建 ReShade core（只在需要时）

```powershell
cmake -S . -B build -G "Visual Studio 17 2022" -A x64 -DRESHADE_ALWAYS_REBUILD=ON
cmake --build build --config Release
```

### 4. 在新机器上从零开始

```powershell
git clone https://github.com/raptoravis/reshade-custom.git D:\dev\reshade-custom
cd D:\dev\reshade-custom
.\scripts\setup.ps1   # 克隆所有 deps，自动串行兜底到正确 commit（约 10–20 分钟）
.\scripts\build.ps1   # CMake configure + build（首次 ReShade core 约 20 分钟）
.\scripts\deploy.ps1
```

---

## Warnings

- **ReShade 版本锁死 v5.9.2**：不要 `git -C reshade checkout main`，6.x EXR 导出静默失败
- **deps/ 不要随意 git pull**：imgui 等必须停在特定旧 commit，拉新版重现 API 不兼容错误
- **frame_capture include 路径**：必须用 `reshade-addons/deps/reshade/include` 而非 `reshade/include`
- **build/stamps 卡住时**：删除 `build/stamps/reshade_core/` 目录，强制 ExternalProject 重跑
- **ReShade64.dll → dxgi.dll 是正常的**：ReShade 构建通用代理二进制，不直接输出 dxgi.dll
- **Windows Schannel TLS**：此机器 GitHub 并发克隆不稳定，setup.ps1 已内置串行兜底，不要替换为 `--recurse-submodules`
