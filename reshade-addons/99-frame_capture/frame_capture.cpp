/*
 * Frame Capture Add-on for Reshade 6.x (API v20)
 *
 * Performance design:
 *  - Staging buffers are pre-allocated per runtime; reused every frame.
 *  - Both color + depth GPU copies are issued before a single wait_idle().
 *  - CPU work (de-pitch memcpy, BMP write, EXR compression) runs on a
 *    dedicated save-worker thread so the render loop returns immediately.
 *  - EXR uses ZIP compression (vs original PIZ) for ~4x faster encode.
 *
 * Pre-UI capture (FC_PreUICapture=1):
 *  - Hooks bind_render_targets_and_depth_stencil to detect when the game
 *    transitions from 3D rendering (with depth) to UI rendering (no depth,
 *    backbuffer as RTV).  The backbuffer is copied to a staging texture at
 *    that moment, before any HUD draw calls execute.
 *  - FC_PreUISkipCount lets you skip the first N no-DSV backbuffer binds
 *    (e.g. post-process passes that also render to backbuffer w/o DSV).
 */

#define ImTextureID unsigned long long
#define STB_IMAGE_WRITE_IMPLEMENTATION
#define STB_IMAGE_RESIZE_IMPLEMENTATION
#define TINYEXR_IMPLEMENTATION

#include <imgui.h>
#include <reshade.hpp>
#include <vector>
#include <cstring>
#include <algorithm>
#include <unordered_map>
#include <unordered_set>
#include "FormatEnum.h"
#include <filesystem>
#include <stb_image_write.h>
#include <stb_image_resize.h>
#include "stb_image.h"
#include "tinyexr.h"
#include "miniz.c"
#include "miniz.h"
#include <chrono>
#include <ctime>
#include <fstream>
#include <string>
#include <thread>
#include <mutex>
#include <condition_variable>
#include <queue>
#include <atomic>

static bool     enableCapturing   = true;
static bool     enableDepthExp    = true;
static bool     enableNormalExp   = false;
static uint32_t g_cap_width       = 1600;
static uint32_t g_cap_height      = 1200;
static float    g_target_fps      = 30.0f;
static bool     g_pre_ui_mode     = false;   // FC_PreUICapture: capture before HUD is drawn
static uint32_t g_pre_ui_skip     = 0;       // FC_PreUISkipCount: skip first N no-DSV BB binds
static bool     doOnce            = false;
static bool     g_logged_textures = false;
static int      windowSize[2]     = { 320, 560 };

static std::chrono::steady_clock::time_point s_last_capture;

using namespace reshade::api;

// ── Async save queue ──────────────────────────────────────────────────────────

struct SaveTask {
    std::filesystem::path bmp_path;
    std::vector<uint8_t>  color_pixels;   // RGBA8, width*height*4, no pitch padding
    uint32_t              width = 0, height = 0;

    std::filesystem::path depth_path;     // empty → skip depth
    std::vector<float>    depth_pixels;   // RGBA32F, depth_w*depth_h*4, no padding
    uint32_t              depth_w = 0, depth_h = 0;
};

static constexpr size_t         MAX_QUEUE   = 4;
static std::thread              g_save_thread;
static std::mutex               g_queue_mutex;
static std::condition_variable  g_queue_cv;
static std::queue<SaveTask>     g_save_queue;
static std::atomic<bool>        g_worker_stop { false };

static bool SaveEXR(const float* rgb, int width, int height, const char* outfilename)
{
    EXRHeader header; InitEXRHeader(&header);
    EXRImage  image;  InitEXRImage(&image);
    image.num_channels = 3;

    std::vector<float> ch[3];
    for (int c = 0; c < 3; c++) ch[c].resize(width * height);
    for (int i = 0; i < width * height; i++) {
        ch[0][i] = rgb[3 * i + 0];
        ch[1][i] = rgb[3 * i + 1];
        ch[2][i] = rgb[3 * i + 2];
    }
    float* ptrs[3] = { ch[0].data(), ch[1].data(), ch[2].data() };
    image.images = (unsigned char**)ptrs;
    image.width  = width;
    image.height = height;

    header.compression_type = TINYEXR_COMPRESSIONTYPE_ZIP;  // ZIP ~4x faster than PIZ
    header.num_channels = 3;
    header.channels = (EXRChannelInfo*)malloc(sizeof(EXRChannelInfo) * 3);
    strncpy(header.channels[0].name, "B", 255);
    strncpy(header.channels[1].name, "G", 255);
    strncpy(header.channels[2].name, "R", 255);
    header.pixel_types           = (int*)malloc(sizeof(int) * 3);
    header.requested_pixel_types = (int*)malloc(sizeof(int) * 3);
    for (int i = 0; i < 3; i++)
        header.pixel_types[i] = header.requested_pixel_types[i] = TINYEXR_PIXELTYPE_FLOAT;

    const char* err = nullptr;
    int ret = SaveEXRImageToFile(&image, &header, outfilename, &err);
    free(header.channels);
    free(header.pixel_types);
    free(header.requested_pixel_types);
    return ret == TINYEXR_SUCCESS;
}

static void save_worker_fn()
{
    while (true) {
        SaveTask task;
        {
            std::unique_lock<std::mutex> lk(g_queue_mutex);
            g_queue_cv.wait(lk, [] { return !g_save_queue.empty() || g_worker_stop.load(); });
            if (g_save_queue.empty()) break;
            task = std::move(g_save_queue.front());
            g_save_queue.pop();
        }

        // Resize color if target resolution differs from captured resolution
        const uint8_t* color_src  = task.color_pixels.data();
        uint32_t       color_w    = task.width;
        uint32_t       color_h    = task.height;
        std::vector<uint8_t> color_resized;
        if (g_cap_width > 0 && g_cap_height > 0 &&
            (color_w != g_cap_width || color_h != g_cap_height)) {
            color_resized.resize(g_cap_width * g_cap_height * 4);
            stbir_resize_uint8(color_src, (int)color_w, (int)color_h, 0,
                               color_resized.data(), (int)g_cap_width, (int)g_cap_height, 0, 4);
            color_src = color_resized.data();
            color_w   = g_cap_width;
            color_h   = g_cap_height;
        }

        // Write BMP (RGBA8, 4 channels)
        stbi_write_bmp(task.bmp_path.u8string().c_str(),
                       (int)color_w, (int)color_h, 4, color_src);

        // Write depth EXR
        if (!task.depth_path.empty() && !task.depth_pixels.empty()) {
            // depth_pixels: RGBA32F packed; depth is in alpha (component 3)
            const float* depth_src = task.depth_pixels.data();
            uint32_t     depth_w   = task.depth_w;
            uint32_t     depth_h   = task.depth_h;
            std::vector<float> depth_resized;
            if (g_cap_width > 0 && g_cap_height > 0 &&
                (depth_w != g_cap_width || depth_h != g_cap_height)) {
                depth_resized.resize(g_cap_width * g_cap_height * 4);
                stbir_resize_float(depth_src, (int)depth_w, (int)depth_h, 0,
                                   depth_resized.data(), (int)g_cap_width, (int)g_cap_height, 0, 4);
                depth_src = depth_resized.data();
                depth_w   = g_cap_width;
                depth_h   = g_cap_height;
            }

            uint32_t n = depth_w * depth_h;
            std::vector<float> rgb(n * 3);
            for (uint32_t i = 0; i < n; i++) {
                float d = depth_src[i * 4 + 3];
                rgb[i * 3] = rgb[i * 3 + 1] = rgb[i * 3 + 2] = d;
            }
            SaveEXR(rgb.data(), (int)depth_w, (int)depth_h,
                    task.depth_path.u8string().c_str());
        }
    }
}

// ── Per-runtime state ─────────────────────────────────────────────────────────

struct imgui_content {
    float total_width         = ImGui::GetContentRegionAvail().x;
    int   num_columns         = 1;
    float single_image_max_size = total_width;
    void change_values(int col) {
        num_columns = col;
        single_image_max_size = num_columns > 1
            ? (total_width / num_columns) - 4.0f * (num_columns - 1)
            : total_width;
    }
};

struct draw_stats {
    uint32_t vertices = 0, drawcalls = 0, drawcalls_indirect = 0;
    viewport last_viewport = {};
};
struct clear_stats : public draw_stats { bool rect = false; };
struct depth_stencil_info {
    draw_stats total_stats, current_stats;
    std::vector<clear_stats> clears;
    bool copied_during_frame = false;
};
struct depth_stencil_hash {
    inline size_t operator()(resource v) const { return static_cast<size_t>(v.handle >> 4); }
};

struct __declspec(uuid("7c6363c7-f94e-437a-9160-141782c44a98")) state_tracking_inst {
    resource selected_depth_stencil  = { 0 };
    resource override_depth_stencil  = { 0 };
    resource_view selected_shader_resource = { 0 };
    bool using_backup_texture = false;
    std::unordered_map<resource, unsigned int, depth_stencil_hash> display_count_per_depth_stencil;
};

struct __declspec(uuid("eadae23a-4009-4d32-8557-0af07e45f409")) stored_buffers_inst {
    // Shader export textures (found by name each frame)
    resource      export_texture_r  = { 0 };
    resource_desc export_texture_rd;
    resource_view export_texture_rv = { 0 };
    resource      color_texture_r   = { 0 };
    resource_desc color_texture_rd;

    // Pre-allocated staging textures (cpu-readable, created once per resolution)
    // Using textures (not buffers) for DX11/DX12 compatibility:
    // DX11 does not support copy_texture_to_buffer; copy_texture_region works for both.
    resource color_staging   = { 0 };
    uint32_t color_staging_w = 0;
    uint32_t color_staging_h = 0;
    resource depth_staging   = { 0 };
    uint32_t depth_staging_w = 0;
    uint32_t depth_staging_h = 0;

    // CaptureStatus.fx uniform — small always-on indicator driven from s_state.
    effect_uniform_variable status_state_uniform = { 0 };

    void update(resource sr, resource_desc srd, resource_view srv) {
        export_texture_r = sr; export_texture_rd = srd; export_texture_rv = srv;
    }
    void reset() { export_texture_r = { 0 }; export_texture_rv = { 0 }; }
};

// ── Pre-UI (draw-call interception) state ─────────────────────────────────────
//
// Timeline within one frame:
//   game renders 3D  →  bind_rts_dsv(DSV≠0) fires repeatedly  →  had_depth=true
//   game transitions →  bind_rts_dsv(DSV=0, RTV=backbuffer)   →  copy BB to staging
//   game renders HUD →  (we ignore further bind events)
//   game calls Present → present event → ReShade effects → reshade_present (read staging)

static std::unordered_set<uint64_t> s_backbuffer_handles;   // all current backbuffer resources
static bool     s_had_depth_pass    = false;  // saw at least one DSV-bound render this frame
static bool     s_pre_ui_captured   = false;  // did we copy the BB pre-UI this frame?
static uint32_t s_no_dsv_bb_count   = 0;      // count of no-DSV backbuffer binds this frame
static uint32_t s_no_dsv_non_bb     = 0;      // no-DSV passes where BB was NOT found (diag)
static resource g_pre_ui_staging    = { 0 };  // cpu-readable staging for scene capture
static uint32_t g_pre_ui_staging_w  = 0;
static uint32_t g_pre_ui_staging_h  = 0;
static format   g_pre_ui_staging_fmt = format::unknown;

// Last large non-backbuffer RT seen this frame (the 3D scene before UI compositing).
// At reshade_present time its content is current-frame's scene (UI-free if UI renders
// directly to the backbuffer, not to this intermediate RT).
static resource s_last_non_bb_rt   = { 0 };
static uint32_t s_last_non_bb_w    = 0;
static uint32_t s_last_non_bb_h    = 0;
static format   s_last_non_bb_fmt  = format::unknown;

// Previous frame's non-BB RT count — used by reverse-skip to hit the Nth-from-last pass.
static uint32_t s_prev_non_bb_total = 0;

// Survey mode: Python writes fc_skip_count.txt to sweep skip values at runtime.
static bool     s_survey_mode  = false;

// High-level state from Python (fc_state.txt): "idle" / "surveying" / "capturing"
static char     s_state[32]    = "idle";
static bool     s_show_hints   = true;

// Diagnostic: log first N capture frames to diagnose pre-UI detection
static bool     s_cap_armed   = false;  // true in frames where sidecar exists + timer passed
static uint32_t s_cap_diag_n  = 0;     // number of capture frames logged so far

// ── Format-aware RGBA8 decode from a mapped staging texture ──────────────────

// F16 → F32 helper (no external dependencies)
static inline float half_to_float(uint16_t h) noexcept
{
    uint32_t s =  (uint32_t)(h >> 15u) << 31u;
    uint32_t e =  (h >> 10u) & 0x1Fu;
    uint32_t m =   h         & 0x3FFu;
    uint32_t bits;
    if      (e ==  0u) bits = s | (m << 13u);                       // zero / subnormal
    else if (e == 31u) bits = s | 0x7F800000u | (m << 13u);         // inf / NaN
    else               bits = s | ((e + 112u) << 23u) | (m << 13u); // normal
    float f; std::memcpy(&f, &bits, 4); return f;
}

// Reinhard tone map (handles HDR → [0,1]) then approximate sRGB gamma (x^(1/2.2))
static inline uint8_t hdr_to_u8(float v) noexcept
{
    if (v < 0.0f) v = 0.0f;
    v = v / (1.0f + v);                    // Reinhard
    v = v < 0.0031308f ? v * 12.92f        // sRGB gamma
                       : 1.055f * powf(v, 1.0f / 2.2f) - 0.055f;
    if (v > 1.0f) v = 1.0f;
    return (uint8_t)(v * 255.0f + 0.5f);
}

static void decode_to_rgba8(const void* src, uint32_t row_pitch,
                             uint8_t* dst, uint32_t w, uint32_t h, format fmt)
{
    for (uint32_t y = 0; y < h; y++) {
        const uint8_t* row = static_cast<const uint8_t*>(src) + (size_t)y * row_pitch;
        uint8_t*       out = dst + (size_t)y * w * 4;

        switch (fmt) {
        case format::r8g8b8a8_unorm:
        case format::r8g8b8a8_unorm_srgb:
            std::memcpy(out, row, (size_t)w * 4);
            break;

        case format::b8g8r8a8_unorm:
        case format::b8g8r8a8_unorm_srgb:
        case format::b8g8r8x8_unorm:
        case format::b8g8r8x8_unorm_srgb:
            for (uint32_t x = 0; x < w; x++) {
                out[x*4+0] = row[x*4+2];  // R ← B
                out[x*4+1] = row[x*4+1];  // G
                out[x*4+2] = row[x*4+0];  // B ← R
                out[x*4+3] = 255;
            }
            break;

        case format::r10g10b10a2_unorm: {
            // 32-bit packed: R[9:0] G[19:10] B[29:20] A[31:30]
            const uint32_t* p32 = reinterpret_cast<const uint32_t*>(row);
            for (uint32_t x = 0; x < w; x++) {
                uint32_t p = p32[x];
                out[x*4+0] = (uint8_t)(((p >>  0) & 0x3FF) >> 2);
                out[x*4+1] = (uint8_t)(((p >> 10) & 0x3FF) >> 2);
                out[x*4+2] = (uint8_t)(((p >> 20) & 0x3FF) >> 2);
                out[x*4+3] = 255;
            }
            break;
        }

        case format::r16g16b16a16_float: {
            // 4 × F16 per pixel — HDR, needs tone mapping
            const uint16_t* p16 = reinterpret_cast<const uint16_t*>(row);
            for (uint32_t x = 0; x < w; x++) {
                out[x*4+0] = hdr_to_u8(half_to_float(p16[x*4+0]));
                out[x*4+1] = hdr_to_u8(half_to_float(p16[x*4+1]));
                out[x*4+2] = hdr_to_u8(half_to_float(p16[x*4+2]));
                out[x*4+3] = 255;
            }
            break;
        }

        case format::r11g11b10_float: {
            // 32-bit packed: R[10:0] G[21:11] B[31:22] (unsigned floats, no sign bit)
            const uint32_t* p32 = reinterpret_cast<const uint32_t*>(row);
            for (uint32_t x = 0; x < w; x++) {
                uint32_t v = p32[x];
                auto f11 = [](uint32_t b) noexcept -> float {
                    uint32_t e = (b >> 6u) & 0x1Fu, m = b & 0x3Fu, r;
                    if      (e ==  0u) r = m << 17u;
                    else if (e == 31u) r = 0x7F800000u;
                    else               r = ((e + 112u) << 23u) | (m << 17u);
                    float f; std::memcpy(&f, &r, 4); return f;
                };
                auto f10 = [](uint32_t b) noexcept -> float {
                    uint32_t e = (b >> 5u) & 0x1Fu, m = b & 0x1Fu, r;
                    if      (e ==  0u) r = m << 18u;
                    else if (e == 31u) r = 0x7F800000u;
                    else               r = ((e + 112u) << 23u) | (m << 18u);
                    float f; std::memcpy(&f, &r, 4); return f;
                };
                out[x*4+0] = hdr_to_u8(f11( v         & 0x7FFu));
                out[x*4+1] = hdr_to_u8(f11((v >> 11u) & 0x7FFu));
                out[x*4+2] = hdr_to_u8(f10((v >> 22u) & 0x3FFu));
                out[x*4+3] = 255;
            }
            break;
        }

        default:
            // Log unknown format once — look for "FC: decode fmt=" in the log
            {
                static uint32_t s_unk_fmt_logged = 0;
                uint32_t fv = (uint32_t)fmt;
                if (s_unk_fmt_logged != fv) {
                    s_unk_fmt_logged = fv;
                    char msg[80]; sprintf_s(msg, "FC: decode fmt=%u not handled, raw copy", fv);
                    reshade::log::message(reshade::log::level::warning, msg);
                }
            }
            std::memcpy(out, row, std::min((size_t)w * 4, (size_t)row_pitch));
            break;
        }
    }
}

// ── Addon event callbacks ─────────────────────────────────────────────────────

static void on_init_device(device*)
{
    reshade::get_config_value(nullptr, "ADDON", "FC_EnableCapture",  enableCapturing);
    reshade::get_config_value(nullptr, "ADDON", "FC_ExportDepth",    enableDepthExp);
    reshade::get_config_value(nullptr, "ADDON", "FC_ExportNormal",   enableNormalExp);
    reshade::get_config_value(nullptr, "ADDON", "FC_CaptureWidth",   g_cap_width);
    reshade::get_config_value(nullptr, "ADDON", "FC_CaptureHeight",  g_cap_height);
    reshade::get_config_value(nullptr, "ADDON", "FC_TargetFPS",      g_target_fps);
    reshade::get_config_value(nullptr, "ADDON", "FC_PreUICapture",   g_pre_ui_mode);
    reshade::get_config_value(nullptr, "ADDON", "FC_PreUISkipCount", g_pre_ui_skip);
}

static void on_init_swapchain(swapchain* sw, bool /*resize*/)
{
    uint32_t n = sw->get_back_buffer_count();
    for (uint32_t i = 0; i < n; i++)
        s_backbuffer_handles.insert(sw->get_back_buffer(i).handle);
}

static void on_destroy_swapchain(swapchain* sw, bool /*resize*/)
{
    uint32_t n = sw->get_back_buffer_count();
    for (uint32_t i = 0; i < n; i++)
        s_backbuffer_handles.erase(sw->get_back_buffer(i).handle);
    // Pre-UI staging resource belongs to the device (still alive), cleaned up in destroy_device.
}

static void on_init_effect_runtime(effect_runtime* runtime)
{
    runtime->create_private_data<stored_buffers_inst>();
}

static void on_destroy_effect_runtime(effect_runtime* runtime)
{
    device* dev = runtime->get_device();
    stored_buffers_inst& sbi = *runtime->get_private_data<stored_buffers_inst>();
    if (sbi.export_texture_rv.handle != 0)
        dev->destroy_resource_view(sbi.export_texture_rv);
    if (sbi.color_staging.handle != 0)
        dev->destroy_resource(sbi.color_staging);
    if (sbi.depth_staging.handle != 0)
        dev->destroy_resource(sbi.depth_staging);
    runtime->destroy_private_data<stored_buffers_inst>();
}

static void on_destroy_device(device* dev)
{
    if (g_pre_ui_staging.handle != 0) {
        dev->destroy_resource(g_pre_ui_staging);
        g_pre_ui_staging     = { 0 };
        g_pre_ui_staging_w   = 0;
        g_pre_ui_staging_h   = 0;
        g_pre_ui_staging_fmt = format::unknown;
    }
}

// Survey mode bind-time copy: the chosen RT is currently in render_target
// state (the game just transitioned it for this bind), so we can safely copy
// from it now using render_target↔copy_source barriers.  The deferred
// shader_resource→copy_source barrier at BB-bind time crashes the game
// (E_INVALIDARG on Close) for mid-pipeline RTs that were never read as SRV.
// Captured contents are the RT's pre-this-frame state (= last frame's draws
// into it); for survey's adjacent-skip-diff algorithm that's still meaningful.
static bool fc_copy_rt_at_bind(command_list* cmd_list, device* dev,
                                resource rt, uint32_t w, uint32_t h, format fmt)
{
    if (!g_pre_ui_staging.handle ||
        g_pre_ui_staging_w != w || g_pre_ui_staging_h != h) {
        if (g_pre_ui_staging.handle) dev->destroy_resource(g_pre_ui_staging);
        g_pre_ui_staging = { 0 };
        resource_desc sd(w, h, 1, 1, fmt, 1,
                         memory_heap::gpu_to_cpu, resource_usage::copy_dest);
        if (!dev->create_resource(sd, nullptr, resource_usage::copy_dest, &g_pre_ui_staging)) {
            reshade::log::message(reshade::log::level::error,
                "FC: failed to create scene RT staging (survey bind-time)");
            return false;
        }
        g_pre_ui_staging_w   = w;
        g_pre_ui_staging_h   = h;
        g_pre_ui_staging_fmt = fmt;
    }
    cmd_list->barrier(rt, resource_usage::render_target, resource_usage::copy_source);
    cmd_list->copy_texture_region(rt, 0, nullptr, g_pre_ui_staging, 0, nullptr);
    cmd_list->barrier(rt, resource_usage::copy_source, resource_usage::render_target);
    return true;
}

// Called on every OMSetRenderTargets (DX11) or equivalent.
// When the game switches from depth-enabled 3D passes to a no-DSV pass that
// writes to the swap chain back buffer, we copy the back buffer content —
// this is just before the first HUD draw call.
static void on_bind_rts_dsv(command_list* cmd_list, uint32_t count,
                              const resource_view* rtvs, resource_view dsv)
{
    if (!enableCapturing || !g_pre_ui_mode || s_pre_ui_captured) return;

    if (dsv.handle != 0) {
        s_had_depth_pass = true;
        return;
    }
    // No depth stencil bound.  Only interesting after we've seen 3D geometry.
    if (!s_had_depth_pass || count == 0) return;

    // Is the backbuffer one of the render targets?
    device* dev = cmd_list->get_device();
    resource bb = { 0 };
    for (uint32_t i = 0; i < count; i++) {
        if (!rtvs[i].handle) continue;
        resource r = dev->get_resource_from_view(rtvs[i]);
        if (s_backbuffer_handles.count(r.handle)) { bb = r; break; }
    }
    if (!bb.handle) {
        // Reverse-skip: capture the (total-1-skip)-th non-BB RT from the previous frame.
        // When skip=0 or total unknown, always overwrite so the last RT wins (same as before).
        for (uint32_t i = 0; i < count; i++) {
            if (!rtvs[i].handle) continue;
            resource r = dev->get_resource_from_view(rtvs[i]);
            if (!r.handle) continue;
            resource_desc rd = dev->get_resource_desc(r);
            if (rd.texture.width < 1280) continue;
            bool should_record;
            if (g_pre_ui_skip == 0 || s_prev_non_bb_total == 0) {
                should_record = true;  // always overwrite → last RT wins
            } else {
                uint32_t target = (s_prev_non_bb_total > g_pre_ui_skip)
                                  ? (s_prev_non_bb_total - 1 - g_pre_ui_skip)
                                  : 0;
                should_record = (s_no_dsv_non_bb == target);
            }
            if (should_record) {
                s_last_non_bb_rt  = r;
                s_last_non_bb_w   = rd.texture.width;
                s_last_non_bb_h   = rd.texture.height;
                s_last_non_bb_fmt = rd.texture.format;
                // Survey mode: do the GPU copy NOW with render_target barriers.
                // Avoids the BB-bind shader_resource assumption that crashes
                // for mid-pipeline RTs not actually read as SRV downstream.
                if (s_survey_mode &&
                    fc_copy_rt_at_bind(cmd_list, dev, r,
                                       rd.texture.width, rd.texture.height, rd.texture.format)) {
                    s_pre_ui_captured = true;
                }
            }
            break;
        }
        s_no_dsv_non_bb++;
        return;
    }

    // Backbuffer about to be bound: all non-BB passes are done.
    // Copy the tracked scene RT now while it's still active and in shader_resource state
    // (the final composite pass just read from it before transitioning to the backbuffer).
    // Doing this here (mid-frame, on the game's cmd list) avoids accessing a resource
    // that UE4 may alias/deactivate after Present.
    if (s_last_non_bb_rt.handle != 0 && s_had_depth_pass) {
        if (!g_pre_ui_staging.handle ||
            g_pre_ui_staging_w != s_last_non_bb_w || g_pre_ui_staging_h != s_last_non_bb_h) {
            if (g_pre_ui_staging.handle) dev->destroy_resource(g_pre_ui_staging);
            g_pre_ui_staging = { 0 };
            resource_desc sd(s_last_non_bb_w, s_last_non_bb_h, 1, 1,
                             s_last_non_bb_fmt, 1,
                             memory_heap::gpu_to_cpu, resource_usage::copy_dest);
            if (dev->create_resource(sd, nullptr, resource_usage::copy_dest, &g_pre_ui_staging)) {
                g_pre_ui_staging_w   = s_last_non_bb_w;
                g_pre_ui_staging_h   = s_last_non_bb_h;
                g_pre_ui_staging_fmt = s_last_non_bb_fmt;
                char msg[128];
                sprintf_s(msg, "FC: scene RT staging allocated %ux%u fmt=%d",
                          s_last_non_bb_w, s_last_non_bb_h, (int)s_last_non_bb_fmt);
                reshade::log::message(reshade::log::level::info, msg);
            } else {
                reshade::log::message(reshade::log::level::error, "FC: failed to create scene RT staging");
                return;
            }
        }
        cmd_list->barrier(s_last_non_bb_rt, resource_usage::shader_resource, resource_usage::copy_source);
        cmd_list->copy_texture_region(s_last_non_bb_rt, 0, nullptr, g_pre_ui_staging, 0, nullptr);
        cmd_list->barrier(s_last_non_bb_rt, resource_usage::copy_source, resource_usage::shader_resource);
        s_pre_ui_captured = true;
    }
}

// DX12 render-pass variant of the same heuristic.
// Fires when the game calls BeginRenderPass (DX12 enhanced render passes).
// The event fires before the actual DX12 call, so copy commands on cmd_list
// execute before this render pass's draw calls.
static void on_begin_render_pass(command_list* cmd_list, uint32_t count,
                                  const render_pass_render_target_desc* rts,
                                  const render_pass_depth_stencil_desc* ds,
                                  render_pass_flags /*flags*/)
{
    if (!enableCapturing || !g_pre_ui_mode || s_pre_ui_captured) return;

    bool has_dsv = (ds != nullptr && ds->view.handle != 0);
    if (has_dsv) { s_had_depth_pass = true; return; }
    if (!s_had_depth_pass || count == 0) return;

    device* dev = cmd_list->get_device();
    resource bb = { 0 };
    for (uint32_t i = 0; i < count; i++) {
        if (!rts[i].view.handle) continue;
        resource r = dev->get_resource_from_view(rts[i].view);
        if (s_backbuffer_handles.count(r.handle)) { bb = r; break; }
    }
    if (!bb.handle) {
        for (uint32_t i = 0; i < count; i++) {
            if (!rts[i].view.handle) continue;
            resource r = dev->get_resource_from_view(rts[i].view);
            if (!r.handle) continue;
            resource_desc rd = dev->get_resource_desc(r);
            if (rd.texture.width < 1280) continue;
            bool should_record;
            if (g_pre_ui_skip == 0 || s_prev_non_bb_total == 0) {
                should_record = true;
            } else {
                uint32_t target = (s_prev_non_bb_total > g_pre_ui_skip)
                                  ? (s_prev_non_bb_total - 1 - g_pre_ui_skip)
                                  : 0;
                should_record = (s_no_dsv_non_bb == target);
            }
            if (should_record) {
                s_last_non_bb_rt  = r;
                s_last_non_bb_w   = rd.texture.width;
                s_last_non_bb_h   = rd.texture.height;
                s_last_non_bb_fmt = rd.texture.format;
                if (s_survey_mode &&
                    fc_copy_rt_at_bind(cmd_list, dev, r,
                                       rd.texture.width, rd.texture.height, rd.texture.format)) {
                    s_pre_ui_captured = true;
                }
            }
            break;
        }
        s_no_dsv_non_bb++;
        return;
    }

    if (s_last_non_bb_rt.handle != 0 && s_had_depth_pass) {
        if (!g_pre_ui_staging.handle ||
            g_pre_ui_staging_w != s_last_non_bb_w || g_pre_ui_staging_h != s_last_non_bb_h) {
            if (g_pre_ui_staging.handle) dev->destroy_resource(g_pre_ui_staging);
            g_pre_ui_staging = { 0 };
            resource_desc sd(s_last_non_bb_w, s_last_non_bb_h, 1, 1,
                             s_last_non_bb_fmt, 1,
                             memory_heap::gpu_to_cpu, resource_usage::copy_dest);
            if (dev->create_resource(sd, nullptr, resource_usage::copy_dest, &g_pre_ui_staging)) {
                g_pre_ui_staging_w   = s_last_non_bb_w;
                g_pre_ui_staging_h   = s_last_non_bb_h;
                g_pre_ui_staging_fmt = s_last_non_bb_fmt;
            } else {
                reshade::log::message(reshade::log::level::error, "FC: failed to create scene RT staging (RP)");
                return;
            }
        }
        cmd_list->barrier(s_last_non_bb_rt, resource_usage::shader_resource, resource_usage::copy_source);
        cmd_list->copy_texture_region(s_last_non_bb_rt, 0, nullptr, g_pre_ui_staging, 0, nullptr);
        cmd_list->barrier(s_last_non_bb_rt, resource_usage::copy_source, resource_usage::shader_resource);
        s_pre_ui_captured = true;
    }
}

static void fc_find_export_tex(effect_runtime* runtime, stored_buffers_inst& sbi)
{
    device* dev = runtime->get_device();
    runtime->enumerate_texture_variables(nullptr, [&sbi, dev](effect_runtime* rt, auto variable) {
        char name[256] = {};
        rt->get_texture_variable_name(variable, name);
        resource_view srv = { 0 }, srv_srgb = { 0 };
        if (std::strcmp(name, "DepthToAddon_ExportTex") == 0) {
            rt->get_texture_binding(variable, &srv, &srv_srgb);
            if (srv.handle != 0) {
                resource r = dev->get_resource_from_view(srv);
                sbi.update(r, dev->get_resource_desc(r), srv);
            } else sbi.reset();
        } else if (std::strcmp(name, "UIRemove_ColorTex") == 0) {
            rt->get_texture_binding(variable, &srv, &srv_srgb);
            if (srv.handle != 0) {
                resource r = dev->get_resource_from_view(srv);
                sbi.color_texture_r  = r;
                sbi.color_texture_rd = dev->get_resource_desc(r);
            } else sbi.color_texture_r = { 0 };
        }
    });
}

static void on_begin_render_effects(effect_runtime* runtime, command_list*, resource_view, resource_view)
{
    stored_buffers_inst& sbi = *runtime->get_private_data<stored_buffers_inst>();
    if (!g_logged_textures) {
        reshade::log::message(reshade::log::level::info, "FC: listing all effect texture variables:");
        runtime->enumerate_texture_variables(nullptr, [](effect_runtime* rt, auto variable) {
            char name[256] = {}; rt->get_texture_variable_name(variable, name);
            char msg[320]; sprintf_s(msg, "FC:   '%s'", name);
            reshade::log::message(reshade::log::level::info, msg);
        });
        g_logged_textures = true;
    }
    fc_find_export_tex(runtime, sbi);

    // Refresh backbuffer handle set every frame — init_swapchain may have
    // fired before the addon was loaded (e.g. FF7 Remake's two-process launch).
    if (g_pre_ui_mode) {
        uint32_t n = runtime->get_back_buffer_count();
        for (uint32_t i = 0; i < n; i++)
            s_backbuffer_handles.insert(runtime->get_back_buffer(i).handle);
    }

    // Drive CaptureStatus.fx uniform from the high-level state so the in-game
    // indicator reflects idle / surveying / capturing.
    if (sbi.status_state_uniform.handle == 0)
        sbi.status_state_uniform = runtime->find_uniform_variable("CaptureStatus.fx", "Status_State");
    if (sbi.status_state_uniform.handle != 0) {
        int32_t v = 0;
        if (std::strcmp(s_state, "surveying") == 0) v = 1;
        else if (std::strcmp(s_state, "capturing") == 0) v = 2;
        if (!s_show_hints) v = 0;  // hide indicator when hints disabled
        runtime->set_uniform_value_int(sbi.status_state_uniform, &v, 1);
    }
}

// ── Capture hot path ──────────────────────────────────────────────────────────

static void on_reshade_present(effect_runtime* runtime)
{
    if (!enableCapturing) goto reset_frame_state;

    {
        auto tick = std::chrono::steady_clock::now();
        float fps = (g_target_fps > 0.0f) ? g_target_fps : 30.0f;
        if (std::chrono::duration<float>(tick - s_last_capture).count() < 1.0f / fps)
            goto reset_frame_state;
        s_last_capture = tick;

        stored_buffers_inst& sbi = *runtime->get_private_data<stored_buffers_inst>();

        // Drop frame if worker is behind
        {
            std::lock_guard<std::mutex> lk(g_queue_mutex);
            if (g_save_queue.size() >= MAX_QUEUE) {
                reshade::log::message(reshade::log::level::warning, "FC: save queue full, dropping frame");
                goto reset_frame_state;
            }
        }

        // ── Resolve output directory ─────────────────────────────────────────
        // fc_output_dir.txt is written by capture_all.run() after the user
        // presses the start key.  If absent, capture hasn't been armed yet.
        WCHAR exe_buf[MAX_PATH] = L"";
        GetModuleFileNameW(nullptr, exe_buf, ARRAYSIZE(exe_buf));
        std::filesystem::path exe_fs(exe_buf);

        // Survey mode: fc_skip_count.txt lets Python drive g_pre_ui_skip at runtime.
        // g_pre_ui_skip currently holds the value used in THIS frame's on_bind_rts_dsv;
        // record it for the filename, then update for the next frame.
        uint32_t this_frame_skip = g_pre_ui_skip;
        {
            std::ifstream sf(exe_fs.parent_path() / L"fc_skip_count.txt");
            std::string   sl;
            if (std::getline(sf, sl)) {
                while (!sl.empty() && (sl.back() == '\r' || sl.back() == '\n')) sl.pop_back();
                s_survey_mode = !sl.empty();
                if (s_survey_mode) g_pre_ui_skip = (uint32_t)std::stoul(sl);
            } else {
                s_survey_mode = false;
            }
        }

        // High-level state + hint toggle (Python → addon).
        {
            std::ifstream sf(exe_fs.parent_path() / L"fc_state.txt");
            std::string sl;
            if (std::getline(sf, sl)) {
                while (!sl.empty() && (sl.back() == '\r' || sl.back() == '\n')) sl.pop_back();
                if (!sl.empty()) {
                    strncpy(s_state, sl.c_str(), sizeof(s_state) - 1);
                    s_state[sizeof(s_state) - 1] = '\0';
                }
            }
            std::ifstream hf(exe_fs.parent_path() / L"fc_hints.txt");
            std::string hl;
            if (std::getline(hf, hl)) {
                while (!hl.empty() && (hl.back() == '\r' || hl.back() == '\n')) hl.pop_back();
                s_show_hints = (hl != "0" && !hl.empty());
            }
        }

        std::filesystem::path out_dir;
        {
            std::ifstream cfg(exe_fs.parent_path() / L"fc_output_dir.txt");
            std::string line;
            if (!std::getline(cfg, line))
                goto reset_frame_state;   // sidecar absent → not started yet
            while (!line.empty() && (line.back() == '\r' || line.back() == '\n'))
                line.pop_back();
            out_dir = line.empty() ? exe_fs.parent_path() : std::filesystem::u8path(line);
        }
        s_cap_armed = true;   // sidecar confirmed — mark for diagnostic log

        // ── Build filename prefix ────────────────────────────────────────────
        const auto now         = std::chrono::system_clock::now();
        const auto now_seconds = std::chrono::time_point_cast<std::chrono::seconds>(now);
        const std::time_t t    = std::chrono::system_clock::to_time_t(now_seconds);
        tm tm_val; localtime_s(&tm_val, &t);
        char ts[32];
        sprintf_s(ts, "%.4d-%.2d-%.2d %.2d-%.2d-%.2d %.3lld ",
                  tm_val.tm_year + 1900, tm_val.tm_mon + 1, tm_val.tm_mday,
                  tm_val.tm_hour, tm_val.tm_min, tm_val.tm_sec,
                  std::chrono::duration_cast<std::chrono::milliseconds>(now - now_seconds).count());

        std::filesystem::path save_prefix;
        if (s_survey_mode) {
            char sn[32]; sprintf_s(sn, "survey_skip_%03u_", this_frame_skip);
            save_prefix = out_dir / sn;
        } else {
            save_prefix = out_dir / exe_fs.filename();
            save_prefix += L' ';
            save_prefix += ts;
        }

        device*        dev   = runtime->get_device();
        command_queue* queue = runtime->get_command_queue();
        command_list*  cmd   = queue->get_immediate_command_list();

        SaveTask task;
        task.bmp_path = save_prefix; task.bmp_path += L"BackBuffer.bmp";

        // ── Color capture ─────────────────────────────────────────────────────
        // use_scene_rt: color was already copied to g_pre_ui_staging in on_bind_rts_dsv
        // at the backbuffer-bind event (mid-frame, game's cmd list, RT still alive+active).
        bool use_scene_rt = g_pre_ui_mode && s_pre_ui_captured && g_pre_ui_staging.handle != 0;
        if (g_pre_ui_mode && !use_scene_rt)
            reshade::log::message(reshade::log::level::warning,
                "FC: pre-UI mode ON but scene RT not copied this frame — falling back to UIRemove_ColorTex");

        if (use_scene_rt) {
            // Color already in g_pre_ui_staging. Issue depth copy now (ReShade-managed, known state).
            bool do_depth = enableDepthExp && sbi.export_texture_r.handle != 0;
            if (do_depth) {
                const resource_desc& drd = sbi.export_texture_rd;
                if (sbi.depth_staging.handle == 0 ||
                    sbi.depth_staging_w != drd.texture.width || sbi.depth_staging_h != drd.texture.height) {
                    if (sbi.depth_staging.handle != 0) dev->destroy_resource(sbi.depth_staging);
                    resource_desc dsd(drd.texture.width, drd.texture.height, 1, 1,
                                      drd.texture.format, 1, memory_heap::gpu_to_cpu, resource_usage::copy_dest);
                    if (!dev->create_resource(dsd, nullptr, resource_usage::copy_dest, &sbi.depth_staging)) {
                        reshade::log::message(reshade::log::level::error, "FC: failed to create depth staging (scene_rt)");
                        do_depth = false;
                    } else {
                        sbi.depth_staging_w = drd.texture.width;
                        sbi.depth_staging_h = drd.texture.height;
                    }
                }
                if (do_depth) {
                    cmd->barrier(sbi.export_texture_r, resource_usage::shader_resource, resource_usage::copy_source);
                    cmd->copy_texture_region(sbi.export_texture_r, 0, nullptr, sbi.depth_staging, 0, nullptr);
                    cmd->barrier(sbi.export_texture_r, resource_usage::copy_source, resource_usage::shader_resource);
                }
            }

            queue->wait_idle();

            task.width  = g_pre_ui_staging_w;
            task.height = g_pre_ui_staging_h;
            task.color_pixels.resize((size_t)task.width * task.height * 4);

            subresource_data sd_color = {};
            if (dev->map_texture_region(g_pre_ui_staging, 0, nullptr, map_access::read_only, &sd_color) && sd_color.data) {
                decode_to_rgba8(sd_color.data, sd_color.row_pitch,
                                task.color_pixels.data(), task.width, task.height,
                                g_pre_ui_staging_fmt);
                dev->unmap_texture_region(g_pre_ui_staging, 0);
            }

            if (do_depth) {
                const resource_desc& drd = sbi.export_texture_rd;
                task.depth_path = save_prefix; task.depth_path += L"DepthBuffer.exr";
                task.depth_w = drd.texture.width;
                task.depth_h = drd.texture.height;
                task.depth_pixels.resize((size_t)task.depth_w * task.depth_h * 4);
                subresource_data depth_data = {};
                if (dev->map_texture_region(sbi.depth_staging, 0, nullptr, map_access::read_only, &depth_data) && depth_data.data) {
                    const float* dsrc       = static_cast<const float*>(depth_data.data);
                    uint32_t floats_per_row = depth_data.row_pitch / sizeof(float);
                    for (uint32_t y = 0; y < task.depth_h; y++)
                        std::memcpy(task.depth_pixels.data() + y * task.depth_w * 4,
                                    dsrc + y * floats_per_row,
                                    task.depth_w * 4 * sizeof(float));
                    dev->unmap_texture_region(sbi.depth_staging, 0);
                }
            }
        } else {
            // ── Original path: read UIRemove_ColorTex (RGBA8, post-UI) ───────
            if (sbi.color_texture_r.handle == 0)
                fc_find_export_tex(runtime, sbi);
            if (sbi.color_texture_r.handle == 0) {
                reshade::log::message(reshade::log::level::warning, "FC: UIRemove_ColorTex not ready, skipped");
                goto reset_frame_state;
            }

            const resource_desc& crd = sbi.color_texture_rd;

            if (sbi.color_staging.handle == 0 ||
                sbi.color_staging_w != crd.texture.width || sbi.color_staging_h != crd.texture.height) {
                if (sbi.color_staging.handle != 0) dev->destroy_resource(sbi.color_staging);
                resource_desc sd(crd.texture.width, crd.texture.height, 1, 1,
                                 crd.texture.format, 1, memory_heap::gpu_to_cpu, resource_usage::copy_dest);
                if (!dev->create_resource(sd, nullptr, resource_usage::copy_dest, &sbi.color_staging)) {
                    reshade::log::message(reshade::log::level::error, "FC: failed to create color staging texture");
                    goto reset_frame_state;
                }
                sbi.color_staging_w = crd.texture.width;
                sbi.color_staging_h = crd.texture.height;
            }

            cmd->barrier(sbi.color_texture_r, resource_usage::shader_resource, resource_usage::copy_source);
            cmd->copy_texture_region(sbi.color_texture_r, 0, nullptr, sbi.color_staging, 0, nullptr);
            cmd->barrier(sbi.color_texture_r, resource_usage::copy_source, resource_usage::shader_resource);

            task.width  = crd.texture.width;
            task.height = crd.texture.height;
            task.color_pixels.resize((size_t)task.width * task.height * 4);

            // ── GPU: depth copy (if enabled) ─────────────────────────────────
            bool do_depth = enableDepthExp && sbi.export_texture_r.handle != 0;
            if (do_depth) {
                const resource_desc& drd = sbi.export_texture_rd;

                if (sbi.depth_staging.handle == 0 ||
                    sbi.depth_staging_w != drd.texture.width || sbi.depth_staging_h != drd.texture.height) {
                    if (sbi.depth_staging.handle != 0) dev->destroy_resource(sbi.depth_staging);
                    resource_desc dsd(drd.texture.width, drd.texture.height, 1, 1,
                                      drd.texture.format, 1, memory_heap::gpu_to_cpu, resource_usage::copy_dest);
                    if (!dev->create_resource(dsd, nullptr, resource_usage::copy_dest, &sbi.depth_staging)) {
                        reshade::log::message(reshade::log::level::error, "FC: failed to create depth staging texture");
                        do_depth = false;
                    } else {
                        sbi.depth_staging_w = drd.texture.width;
                        sbi.depth_staging_h = drd.texture.height;
                    }
                }

                if (do_depth) {
                    cmd->barrier(sbi.export_texture_r, resource_usage::shader_resource, resource_usage::copy_source);
                    cmd->copy_texture_region(sbi.export_texture_r, 0, nullptr, sbi.depth_staging, 0, nullptr);
                    cmd->barrier(sbi.export_texture_r, resource_usage::copy_source, resource_usage::shader_resource);
                }
            }

            // ── Single GPU sync for both copies ───────────────────────────────
            queue->wait_idle();

            subresource_data color_data = {};
            if (dev->map_texture_region(sbi.color_staging, 0, nullptr, map_access::read_only, &color_data) && color_data.data) {
                const uint8_t* src = static_cast<const uint8_t*>(color_data.data);
                for (uint32_t y = 0; y < task.height; y++)
                    std::memcpy(task.color_pixels.data() + y * task.width * 4,
                                src + y * color_data.row_pitch,
                                task.width * 4);
                dev->unmap_texture_region(sbi.color_staging, 0);
            }

            if (do_depth) {
                const resource_desc& drd = sbi.export_texture_rd;
                task.depth_path = save_prefix; task.depth_path += L"DepthBuffer.exr";
                task.depth_w = drd.texture.width;
                task.depth_h = drd.texture.height;
                task.depth_pixels.resize((size_t)task.depth_w * task.depth_h * 4);

                subresource_data depth_data = {};
                if (dev->map_texture_region(sbi.depth_staging, 0, nullptr, map_access::read_only, &depth_data) && depth_data.data) {
                    const float* src        = static_cast<const float*>(depth_data.data);
                    uint32_t floats_per_row = depth_data.row_pitch / sizeof(float);
                    for (uint32_t y = 0; y < task.depth_h; y++)
                        std::memcpy(task.depth_pixels.data() + y * task.depth_w * 4,
                                    src + y * floats_per_row,
                                    task.depth_w * 4 * sizeof(float));
                    dev->unmap_texture_region(sbi.depth_staging, 0);
                }
            }
        }

        // Survey: write current frame's non-BB pass count so Python knows the range.
        if (s_survey_mode && s_no_dsv_non_bb > 0) {
            std::ofstream tf(exe_fs.parent_path() / L"fc_pass_total.txt", std::ios::trunc);
            tf << s_no_dsv_non_bb << '\n';
        }

        // Enqueue — render thread is now free
        {
            std::lock_guard<std::mutex> lk(g_queue_mutex);
            g_save_queue.push(std::move(task));
        }
        g_queue_cv.notify_one();
    }

reset_frame_state:
    // Diagnostic: log first 30 armed-capture frames so we can understand the pipeline.
    if (s_cap_armed && s_cap_diag_n < 30) {
        s_cap_diag_n++;
        char dmsg[256];
        sprintf_s(dmsg,
            "FC: capf%u bb_handles=%zu had_depth=%d no_dsv_bb=%u no_dsv_non_bb=%u captured=%d",
            s_cap_diag_n,
            s_backbuffer_handles.size(),
            (int)s_had_depth_pass,
            s_no_dsv_bb_count,
            s_no_dsv_non_bb,
            (int)s_pre_ui_captured);
        reshade::log::message(reshade::log::level::info, dmsg);
    }
    // Reset per-frame pre-UI detection state so next frame starts clean.
    s_prev_non_bb_total = s_no_dsv_non_bb;  // save for reverse-skip next frame
    s_cap_armed       = false;
    s_had_depth_pass  = false;
    s_pre_ui_captured = false;
    s_no_dsv_bb_count = 0;
    s_no_dsv_non_bb   = 0;
    s_last_non_bb_rt  = { 0 };  // reset so stale handles don't carry over
}

// ── Overlay UI ────────────────────────────────────────────────────────────────

static void drawItem(effect_runtime* runtime, resource_view srv, resource_desc srd,
                     const char* source, bool firstElem, imgui_content img_cont)
{
    uint32_t fw = srd.texture.width, fh = srd.texture.height;
    const float ar = static_cast<float>(fw) / static_cast<float>(fh);
    const ImVec2 sz = ar > 1
        ? ImVec2(img_cont.single_image_max_size, img_cont.single_image_max_size / ar)
        : ImVec2(img_cont.single_image_max_size * ar, img_cont.single_image_max_size);
    int dt_id = static_cast<int>(srd.texture.format);
    ImGui::BeginGroup();
    ImGui::Image(srv.handle, sz);
    ImGui::Spacing();
    ImGui::BeginGroup(); ImGui::BeginGroup();
    ImGui::Text(source); ImGui::SameLine(); ImGui::Text("|"); ImGui::SameLine();
    ImGui::Text("%ix%i", (int)fw, (int)fh); ImGui::SameLine(); ImGui::Text("|"); ImGui::SameLine();
    ImGui::Text(texture_format[dt_id]);
    ImGui::EndGroup(); ImGui::EndGroup(); ImGui::EndGroup();
    if (img_cont.num_columns > 1) { if (firstElem) ImGui::SameLine(); }
    else { if (firstElem) { ImGui::Spacing(); ImGui::Separator(); ImGui::Spacing(); } }
}

static void previewBuffers(effect_runtime* runtime, imgui_content img_cont)
{
    stored_buffers_inst& sbi = *runtime->get_private_data<stored_buffers_inst>();
    device* dev = runtime->get_device();
    bool firstElem = true;
    runtime->enumerate_texture_variables(nullptr, [&](effect_runtime* rt, auto variable) {
        char source[32] = ""; rt->get_texture_variable_name(variable, source);
        auto show = [&](const char* label) {
            resource_view srv = { 0 }, srv2 = { 0 };
            rt->get_texture_binding(variable, &srv, &srv2);
            if (srv.handle != 0) {
                drawItem(rt, srv, dev->get_resource_desc(dev->get_resource_from_view(srv)),
                         label, firstElem, img_cont);
                firstElem = false;
            } else {
                char msg[64]; sprintf_s(msg, "%s not found!", label);
                ImGui::TextColored(ImVec4(1,0.2f,0.2f,1), msg);
            }
        };
        if (std::strcmp(source, "DepthToAddon_DepthTex")   == 0) show("DepthTex");
        if (std::strcmp(source, "DepthToAddon_NormalTex")  == 0) show("NormalTex");
    });
}

static void draw_settings_overlay(effect_runtime* runtime)
{
    imgui_content img_cont;
    if (ImGui::GetContentRegionAvail().x > 560.0f) img_cont.change_values(2);
    bool modified = false;
    if (!doOnce) {
        auto& IO = ImGui::GetIO();
        ImGui::SetWindowSize(ImVec2(windowSize[0], windowSize[1]));
        ImGui::SetWindowPos(ImVec2((IO.DisplaySize.x - 16.0f) / 2.75f, 8.0f));
        doOnce = true;
    }

    // ── Hotkey hints + current state (driven by Python via fc_state.txt) ─────
    if (s_show_hints) {
        ImVec4 col = ImVec4(0.5f, 1.0f, 0.5f, 1.0f);  // green = idle
        const char* label = "IDLE";
        if (std::strcmp(s_state, "surveying") == 0) {
            col = ImVec4(0.5f, 0.8f, 1.0f, 1.0f);     // blue = surveying
            label = "SURVEYING";
        } else if (std::strcmp(s_state, "capturing") == 0) {
            col = ImVec4(1.0f, 0.4f, 0.4f, 1.0f);     // red = capturing
            label = "CAPTURING";
        }
        ImGui::TextColored(col, "● 状态: %s", label);
        ImGui::Spacing();
        ImGui::TextColored(ImVec4(1, 1, 0.6f, 1), "[F6] 开始 survey   [F8] 开始采集   [F9] 停止");
        ImGui::Text("skip = %u   captured = %s", g_pre_ui_skip,
                    s_pre_ui_captured ? "yes" : "no");
        ImGui::Spacing(); ImGui::Separator(); ImGui::Spacing();
    }

    if (ImGui::CollapsingHeader("Settings")) {
        ImGui::Spacing();
        modified |= ImGui::Checkbox("Enable capturing", &enableCapturing);
        modified |= ImGui::Checkbox("Export Depth",   &enableDepthExp);
        modified |= ImGui::Checkbox("Export Normals", &enableNormalExp);
        ImGui::Spacing();
        ImGui::Text("Pre-UI mode: %s", g_pre_ui_mode ? "ON" : "OFF");
        ImGui::Text("skip=%u  captured=%s  hadDepth=%s",
                    g_pre_ui_skip,
                    s_pre_ui_captured ? "yes" : "no",
                    s_had_depth_pass  ? "yes" : "no");
        ImGui::Spacing(); ImGui::Separator();
    }
    ImGui::Spacing();
    previewBuffers(runtime, img_cont);
    ImGui::Spacing();
    if (modified) {
        reshade::set_config_value(nullptr, "ADDON", "FC_EnableCapture", enableCapturing);
        reshade::set_config_value(nullptr, "ADDON", "FC_ExportDepth",   enableDepthExp);
        reshade::set_config_value(nullptr, "ADDON", "FC_ExportNormal",  enableNormalExp);
    }
}

// ── Register / unregister ─────────────────────────────────────────────────────

void register_addon_FC()
{
    reshade::register_overlay("Frame Capture", draw_settings_overlay);
    reshade::register_event<reshade::addon_event::init_device>(on_init_device);
    reshade::register_event<reshade::addon_event::destroy_device>(on_destroy_device);
    reshade::register_event<reshade::addon_event::init_swapchain>(on_init_swapchain);
    reshade::register_event<reshade::addon_event::destroy_swapchain>(on_destroy_swapchain);
    reshade::register_event<reshade::addon_event::init_effect_runtime>(on_init_effect_runtime);
    reshade::register_event<reshade::addon_event::destroy_effect_runtime>(on_destroy_effect_runtime);
    reshade::register_event<reshade::addon_event::bind_render_targets_and_depth_stencil>(on_bind_rts_dsv);
    reshade::register_event<reshade::addon_event::begin_render_pass>(on_begin_render_pass);
    reshade::register_event<reshade::addon_event::reshade_present>(on_reshade_present);
    reshade::register_event<reshade::addon_event::reshade_begin_effects>(on_begin_render_effects);
}

void unregister_addon_FC()
{
    reshade::unregister_overlay("Frame Capture", draw_settings_overlay);
    reshade::unregister_event<reshade::addon_event::init_device>(on_init_device);
    reshade::unregister_event<reshade::addon_event::destroy_device>(on_destroy_device);
    reshade::unregister_event<reshade::addon_event::init_swapchain>(on_init_swapchain);
    reshade::unregister_event<reshade::addon_event::destroy_swapchain>(on_destroy_swapchain);
    reshade::unregister_event<reshade::addon_event::init_effect_runtime>(on_init_effect_runtime);
    reshade::unregister_event<reshade::addon_event::destroy_effect_runtime>(on_destroy_effect_runtime);
    reshade::unregister_event<reshade::addon_event::bind_render_targets_and_depth_stencil>(on_bind_rts_dsv);
    reshade::unregister_event<reshade::addon_event::begin_render_pass>(on_begin_render_pass);
    reshade::unregister_event<reshade::addon_event::reshade_present>(on_reshade_present);
    reshade::unregister_event<reshade::addon_event::reshade_begin_effects>(on_begin_render_effects);
}

// ── DLL entry ─────────────────────────────────────────────────────────────────

extern "C" __declspec(dllexport) const char* NAME        = "Frame Capture";
extern "C" __declspec(dllexport) const char* DESCRIPTION = "Captures depth and color textures via ReShade. Timer-driven, no key required.";

BOOL APIENTRY DllMain(HMODULE hModule, DWORD fdwReason, LPVOID)
{
    switch (fdwReason) {
    case DLL_PROCESS_ATTACH:
        if (!reshade::register_addon(hModule))
            return FALSE;
        g_worker_stop = false;
        g_save_thread = std::thread(save_worker_fn);
        register_addon_FC();
        break;
    case DLL_PROCESS_DETACH:
        unregister_addon_FC();
        reshade::unregister_addon(hModule);
        {
            std::lock_guard<std::mutex> lk(g_queue_mutex);
            g_worker_stop = true;
        }
        g_queue_cv.notify_one();
        if (g_save_thread.joinable())
            g_save_thread.join();
        break;
    }
    return TRUE;
}
