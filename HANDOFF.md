# Handoff: unicap Build System Stabilization

**Generated**: 2026-04-29
**Branch**: master
**Status**: In Progress — build mostly working, submodule restore required before each build

## Goal

Build `dist/dxgi.dll` (ReShade core) and `dist/frame_capture.addon` from source, then deploy + run FF7 Remake capture pipeline via `uv run main.py`.

## Completed

- [x] Fixed all git submodule init issues (minhook, imgui, stb, spirv, utfcpp, vma, fpng, d3d12, glad, openxr, jxl_simple_lossless)
- [x] Fixed `reshade-addons` submodule (frame_capture.cpp, stb_image_write.h)
- [x] Fixed `murchFX` shaders submodule
- [x] Fixed Python imports: `from config import` → `from .config import` in `tools/capture/`
- [x] Added `tools/__init__.py` and `tools/capture/__init__.py`
- [x] Declared missing Python deps in `pyproject.toml` (opencv-python, h5py, numpy)
- [x] Fixed `ROOT` variable in `main.py` (was accidentally commented out)
- [x] Updated `scripts/build.ps1` to show correct `uv run main.py` subcommands
- [x] `dist/dxgi.dll` and `dist/frame_capture.addon` produced successfully at least once

## Not Yet Done

- [ ] Verify full clean build succeeds end-to-end after latest d3d12 submodule restore
- [ ] Confirm `uv run main.py deploy` works against actual game directory
- [ ] Consider adding submodule restore step to `build.ps1` or a setup script

## Failed Approaches (Don't Repeat These)

**Vendoring submodules into git history (commits efd1f2f, 5666fb6)**
- Attempted to convert reshade/reshade-addons/murchFX from submodules to vendored tracked files
- Broke the build because the vendored content was incomplete (glad was missing generated `target/` files, etc.)
- Had to force-push to remove those commits: `git reset --hard f19a9d4 && git push --force-with-lease`
- Do NOT repeat: keep submodules as-is

**`git submodule update --init --recursive` alone is not enough**
- Registers submodules but does NOT populate working trees when dirs already have a `.git` file
- Fix: must `cd <submodule> && git checkout -f HEAD` individually for every empty submodule

**`git pull --rebase` / `--no-rebase` both failed**
- Both fail with "untracked working tree files would be overwritten" when submodule content exists in working tree but remote has those paths as tracked files
- Fix used: `git format-patch HEAD~1` → `git reset --hard origin/master` → `git am patch`

## Key Decisions

| Decision | Rationale |
|----------|-----------|
| Keep submodules (don't vendor) | Vendoring failed; submodule restore pattern is understood |
| `from .config import` (relative imports) | `capture_all.py` and `pack_hdf5.py` are imported as package members from `main.py`; bare imports only work when running files directly |
| `uv run main.py <subcommand>` | Replaced `scripts/deploy.ps1`; single entrypoint for deploy/launch/capture/pack |

## Current State

**Working**: `dist/dxgi.dll`, `dist/frame_capture.addon`, `dist/reshade-shaders/Shaders/*.fx` all present. Python pipeline imports cleanly.

**Uncertain**: After the most recent `git reset --hard`, all submodule working trees were emptied and restored one-by-one as build errors appeared. The d3d12 submodule was the last one fixed. Full build success after that fix is not yet confirmed.

**Uncommitted Changes**: None — working tree clean, up to date with origin/master.

## Files to Know

| File | Why It Matters |
|------|----------------|
| `CMakeLists.txt` | Drives the whole build: ExternalProject for reshade MSBuild, then frame_capture addon, shaders |
| `scripts/build.ps1` | Run this to build; delete `build\` to force reconfigure |
| `main.py` | Python entrypoint: deploy / launch / capture / pack subcommands |
| `tools/capture/config.py` | All path constants (GAME_WIN64, FRAMES_DIR, etc.) — edit for different machines |
| `reshade/deps/ImGui.patch` | Patch for imgui — NOT applied this session but build succeeded anyway |

## Code Context

**main.py subcommands**:
```
uv run main.py deploy   [--mode custom|official592|official673] [--game-dir PATH]
uv run main.py launch   [--mode custom|official592|official673] [--fps N] [--duration SEC] [--deploy-only]
uv run main.py capture  [--fps N] [--duration SEC]
uv run main.py pack     [--frames-dir PATH] [--inputs PATH] [--output PATH]
```

**Submodule restore pattern** (MUST run after any `git reset --hard`):
```bash
# Top-level submodules
for sub in reshade reshade-addons murchFX; do
  cd D:/dev/unicap.git/$sub && git checkout -f HEAD && cd -
done

# reshade nested deps (11 total)
for dep in d3d12 fpng glad imgui jxl_simple_lossless minhook openxr spirv stb utfcpp vma; do
  cd D:/dev/unicap.git/reshade/deps/$dep && git checkout -f HEAD && cd -
done

# reshade-addons nested dep
cd D:/dev/unicap.git/reshade-addons/deps/stb && git checkout -f HEAD && cd -
```

**Paths config** (`tools/capture/config.py`):
```python
GAME_WIN64   = Path(r"E:\games\ff7remake\End\Binaries\Win64")
DATASET_ROOT = Path(r"D:\ff7_dataset")
FRAMES_DIR   = DATASET_ROOT / "frames"
INPUTS_OUT   = DATASET_ROOT / "inputs.jsonl"
```

## Resume Instructions

1. Restore all submodule working trees using the pattern above (always needed after any git reset)

2. Build: `scripts\build.ps1`
   - Expected: completes with "Artifacts in: dist\"
   - If `No such file or directory` for a source file → that submodule's working tree is empty; `cd` into it and `git checkout -f HEAD`
   - If stale intermediate errors → `rm -rf reshade/intermediate/ReShade "reshade/intermediate/ReShade FX" reshade/bin` then rebuild

3. Deploy + capture: `uv run main.py launch --mode custom`
   - Expected: deploys dxgi.dll + frame_capture.addon to GAME_WIN64, then starts capture
   - If `[ERROR] not found: dist/dxgi.dll` → run step 2 first
   - If `ModuleNotFoundError` → run `uv sync`

## Warnings

- **`git reset --hard` destroys all submodule working trees** — always run the full restore pattern afterward. No automated step exists yet.
- **Don't re-vendor the submodules** — already tried and force-removed from history. Do not repeat.
- **`glad/target/` is untracked but required** — `reshade/deps/glad/target/include/` and `target/src/` are pre-generated C headers not tracked by git. Do not delete them.
- **`build\` directory**: delete it to force CMake reconfigure. `build.ps1` skips configure if it exists.
- **`ImGui.patch` not applied** — present at `reshade/deps/ImGui.patch` but was not applied this session; build succeeded without it.
