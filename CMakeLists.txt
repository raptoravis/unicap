cmake_minimum_required(VERSION 3.20)
project(reshade-custom LANGUAGES CXX)

# ── Locate MSBuild (Visual Studio 2022) ──────────────────────────────────────
find_program(MSBUILD_EXE msbuild HINTS
    "$ENV{ProgramFiles}/Microsoft Visual Studio/2022/Enterprise/MSBuild/Current/Bin"
    "$ENV{ProgramFiles}/Microsoft Visual Studio/2022/Professional/MSBuild/Current/Bin"
    "$ENV{ProgramFiles}/Microsoft Visual Studio/2022/Community/MSBuild/Current/Bin"
    "$ENV{ProgramFiles(x86)}/Microsoft Visual Studio/2022/BuildTools/MSBuild/Current/Bin"
    REQUIRED
)
message(STATUS "MSBuild: ${MSBUILD_EXE}")

# ── ReShade core (dxgi.dll) — built via its native .sln ──────────────────────
# ReShade has no CMakeLists.txt; we drive its MSBuild solution from here.
# Source is pinned to v5.9.2 (see .gitmodules); DO NOT upgrade to 6.x —
# frame_capture.addon's EXR export silently breaks on the 6.x API.
include(ExternalProject)

set(RESHADE_SLN "${CMAKE_SOURCE_DIR}/reshade/ReShade.sln")
set(RESHADE_DLL "${CMAKE_SOURCE_DIR}/reshade/bin/x64/Release/dxgi.dll")

ExternalProject_Add(reshade_core
    SOURCE_DIR       "${CMAKE_SOURCE_DIR}/reshade"
    CONFIGURE_COMMAND ""
    BUILD_COMMAND    "${MSBUILD_EXE}" "${RESHADE_SLN}"
                     /p:Configuration=Release
                     /p:Platform=x64
                     /p:PlatformToolset=v143
                     /t:ReShade
                     /m
    BUILD_IN_SOURCE  1
    INSTALL_COMMAND  ${CMAKE_COMMAND} -E copy "${RESHADE_DLL}"
                     "${CMAKE_SOURCE_DIR}/dist/dxgi.dll"
    STAMP_DIR        "${CMAKE_BINARY_DIR}/stamps/reshade_core"
    BUILD_BYPRODUCTS "${RESHADE_DLL}"
)

# Force rebuild when reshade source changes (opt-in via -DRESHADE_ALWAYS_REBUILD=ON)
if(RESHADE_ALWAYS_REBUILD)
    ExternalProject_Add_StepTargets(reshade_core build)
    set_target_properties(reshade_core PROPERTIES BUILD_ALWAYS 1)
endif()

# ── frame_capture addon ───────────────────────────────────────────────────────
# Single source file; deps are header-only (tinyexr, stb) or pure headers (imgui).
# We use reshade/include/ from the main clone to guarantee API version parity.
set(ADDON_ROOT "${CMAKE_SOURCE_DIR}/reshade-addons")

add_library(frame_capture SHARED
    "${ADDON_ROOT}/99-frame_capture/frame_capture.cpp"
)
set_target_properties(frame_capture PROPERTIES
    CXX_STANDARD                     17
    CXX_STANDARD_REQUIRED            ON
    OUTPUT_NAME                      "frame_capture"
    SUFFIX                           ".addon"
    RUNTIME_OUTPUT_DIRECTORY         "${CMAKE_SOURCE_DIR}/dist"
    RUNTIME_OUTPUT_DIRECTORY_RELEASE "${CMAKE_SOURCE_DIR}/dist"
)
target_include_directories(frame_capture PRIVATE
    "${CMAKE_SOURCE_DIR}/reshade/include"
    "${ADDON_ROOT}/deps/imgui"
    "${ADDON_ROOT}/deps/tinyexr"
    "${ADDON_ROOT}/deps/stb"
)
target_compile_definitions(frame_capture PRIVATE
    WIN32_LEAN_AND_MEAN
    NOMINMAX
    NDEBUG
)
# Ensure reshade headers exist before compiling the addon
add_dependencies(frame_capture reshade_core)

# ── Shaders ───────────────────────────────────────────────────────────────────
set(SHADER_DST "${CMAKE_SOURCE_DIR}/dist/reshade-shaders/Shaders")

add_custom_target(shaders ALL
    COMMAND ${CMAKE_COMMAND} -E make_directory "${SHADER_DST}"
    COMMAND ${CMAKE_COMMAND} -E copy
        "${CMAKE_SOURCE_DIR}/murchFX/Shaders/DepthToAddon.fx"
        "${SHADER_DST}/DepthToAddon.fx"
    COMMAND ${CMAKE_COMMAND} -E copy
        "${CMAKE_SOURCE_DIR}/shaders/UIRemove.fx"
        "${SHADER_DST}/UIRemove.fx"
    COMMENT "Staging shaders to dist/reshade-shaders/Shaders/"
)

# ── Deploy target (cmake --install) ──────────────────────────────────────────
set(GAME_WIN64 "E:/games/ff7remake/End/Binaries/Win64"
    CACHE PATH "Absolute path to FF7R Win64 directory")

install(FILES
    "${CMAKE_SOURCE_DIR}/dist/dxgi.dll"
    "${CMAKE_SOURCE_DIR}/dist/frame_capture.addon"
    DESTINATION "${GAME_WIN64}"
)
install(FILES
    "${CMAKE_SOURCE_DIR}/dist/reshade-shaders/Shaders/DepthToAddon.fx"
    "${CMAKE_SOURCE_DIR}/dist/reshade-shaders/Shaders/UIRemove.fx"
    DESTINATION "${GAME_WIN64}/reshade-shaders/Shaders"
)
