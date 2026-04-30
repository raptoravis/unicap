/*
 * Frame Capture Add-on for Reshade 6.x (API v20)
 *
 * Performance design:
 *  - Staging buffers are pre-allocated per runtime; reused every frame.
 *  - Both color + depth GPU copies are issued before a single wait_idle().
 *  - CPU work (de-pitch memcpy, BMP write, EXR compression) runs on a
 *    dedicated save-worker thread so the render loop returns immediately.
 *  - EXR uses ZIP compression (vs original PIZ) for ~4x faster encode.
 */

#define ImTextureID unsigned long long
#define STB_IMAGE_WRITE_IMPLEMENTATION
#define TINYEXR_IMPLEMENTATION

#include <imgui.h>
#include <reshade.hpp>
#include <vector>
#include <cstring>
#include <algorithm>
#include <unordered_map>
#include "FormatEnum.h"
#include <filesystem>
#include <stb_image_write.h>
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

static bool enableCapturing  = true;
static bool enableDepthExp   = true;
static bool enableNormalExp  = false;
static bool doOnce           = false;
static bool g_logged_textures = false;
static int  windowSize[2]    = { 320, 560 };

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

        // Write BMP (RGBA8, 4 channels)
        stbi_write_bmp(task.bmp_path.u8string().c_str(),
                       task.width, task.height, 4, task.color_pixels.data());

        // Write depth EXR
        if (!task.depth_path.empty() && !task.depth_pixels.empty()) {
            // depth_pixels: RGBA32F packed; depth is in alpha (component 3)
            uint32_t n = task.depth_w * task.depth_h;
            std::vector<float> rgb(n * 3);
            for (uint32_t i = 0; i < n; i++) {
                float d = task.depth_pixels[i * 4 + 3];
                rgb[i * 3] = rgb[i * 3 + 1] = rgb[i * 3 + 2] = d;
            }
            SaveEXR(rgb.data(), task.depth_w, task.depth_h,
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

    // Pre-allocated staging buffers (created once, reused every capture)
    resource color_staging      = { 0 };
    uint32_t color_staging_size = 0;
    resource depth_staging      = { 0 };
    uint32_t depth_staging_size = 0;

    void update(resource sr, resource_desc srd, resource_view srv) {
        export_texture_r = sr; export_texture_rd = srd; export_texture_rv = srv;
    }
    void reset() { export_texture_r = { 0 }; export_texture_rv = { 0 }; }
};

// ── Addon event callbacks ─────────────────────────────────────────────────────

static void on_init_device(device*)
{
    reshade::get_config_value(nullptr, "ADDON", "FC_EnableCapture", enableCapturing);
    reshade::get_config_value(nullptr, "ADDON", "FC_ExportDepth",   enableDepthExp);
    reshade::get_config_value(nullptr, "ADDON", "FC_ExportNormal",  enableNormalExp);
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
}

// ── Capture hot path ──────────────────────────────────────────────────────────

static void on_reshade_present(effect_runtime* runtime)
{
    if (!runtime->is_key_pressed(0x79) || !enableCapturing)
        return;

    stored_buffers_inst& sbi = *runtime->get_private_data<stored_buffers_inst>();
    if (sbi.color_texture_r.handle == 0)
        fc_find_export_tex(runtime, sbi);
    if (sbi.color_texture_r.handle == 0) {
        reshade::log::message(reshade::log::level::warning, "FC: UIRemove_ColorTex not ready, skipped");
        return;
    }

    // Drop frame if worker is behind
    {
        std::lock_guard<std::mutex> lk(g_queue_mutex);
        if (g_save_queue.size() >= MAX_QUEUE) {
            reshade::log::message(reshade::log::level::warning, "FC: save queue full, dropping frame");
            return;
        }
    }

    // ── Resolve output directory ───────────────────────────────────────────────
    WCHAR exe_buf[MAX_PATH] = L"";
    GetModuleFileNameW(nullptr, exe_buf, ARRAYSIZE(exe_buf));
    std::filesystem::path exe_fs(exe_buf);
    std::filesystem::path out_dir = exe_fs.parent_path();
    {
        std::ifstream cfg(out_dir / L"fc_output_dir.txt");
        std::string line;
        if (std::getline(cfg, line)) {
            while (!line.empty() && (line.back() == '\r' || line.back() == '\n'))
                line.pop_back();
            if (!line.empty())
                out_dir = std::filesystem::u8path(line);
        }
    }

    // ── Build filename prefix ─────────────────────────────────────────────────
    const auto now         = std::chrono::system_clock::now();
    const auto now_seconds = std::chrono::time_point_cast<std::chrono::seconds>(now);
    const std::time_t t    = std::chrono::system_clock::to_time_t(now_seconds);
    tm tm_val; localtime_s(&tm_val, &t);
    char ts[32];
    sprintf_s(ts, "%.4d-%.2d-%.2d %.2d-%.2d-%.2d %.3lld ",
              tm_val.tm_year + 1900, tm_val.tm_mon + 1, tm_val.tm_mday,
              tm_val.tm_hour, tm_val.tm_min, tm_val.tm_sec,
              std::chrono::duration_cast<std::chrono::milliseconds>(now - now_seconds).count());

    std::filesystem::path save_prefix = out_dir / exe_fs.filename();
    save_prefix += L' ';
    save_prefix += ts;

    // ── GPU: ensure pre-allocated staging buffers ─────────────────────────────
    device*        dev   = runtime->get_device();
    command_queue* queue = runtime->get_command_queue();
    command_list*  cmd   = queue->get_immediate_command_list();

    const resource_desc& crd = sbi.color_texture_rd;
    uint32_t color_row_pitch = (format_row_pitch(crd.texture.format, crd.texture.width) + 255) & ~255;
    uint32_t color_slice     = format_slice_pitch(crd.texture.format, color_row_pitch, crd.texture.height);

    if (sbi.color_staging.handle == 0 || sbi.color_staging_size < color_slice) {
        if (sbi.color_staging.handle != 0) dev->destroy_resource(sbi.color_staging);
        if (!dev->create_resource(resource_desc(color_slice, memory_heap::gpu_to_cpu, resource_usage::copy_dest),
                                  nullptr, resource_usage::copy_dest, &sbi.color_staging)) {
            reshade::log::message(reshade::log::level::error, "FC: failed to create color staging buffer");
            return;
        }
        sbi.color_staging_size = color_slice;
    }

    // ── GPU: color copy ───────────────────────────────────────────────────────
    cmd->barrier(sbi.color_texture_r, resource_usage::shader_resource, resource_usage::copy_source);
    cmd->copy_texture_to_buffer(sbi.color_texture_r, 0, nullptr,
                                sbi.color_staging, 0, crd.texture.width, crd.texture.height);
    cmd->barrier(sbi.color_texture_r, resource_usage::copy_source, resource_usage::shader_resource);

    // ── GPU: depth copy (if enabled) ──────────────────────────────────────────
    bool do_depth = enableDepthExp && sbi.export_texture_r.handle != 0;
    uint32_t depth_row_pitch = 0;
    if (do_depth) {
        const resource_desc& drd = sbi.export_texture_rd;
        depth_row_pitch = (format_row_pitch(drd.texture.format, drd.texture.width) + 255) & ~255;
        uint32_t depth_slice = format_slice_pitch(drd.texture.format, depth_row_pitch, drd.texture.height);

        if (sbi.depth_staging.handle == 0 || sbi.depth_staging_size < depth_slice) {
            if (sbi.depth_staging.handle != 0) dev->destroy_resource(sbi.depth_staging);
            if (!dev->create_resource(resource_desc(depth_slice, memory_heap::gpu_to_cpu, resource_usage::copy_dest),
                                      nullptr, resource_usage::copy_dest, &sbi.depth_staging)) {
                reshade::log::message(reshade::log::level::error, "FC: failed to create depth staging buffer");
                do_depth = false;
            } else sbi.depth_staging_size = depth_slice;
        }

        if (do_depth) {
            cmd->barrier(sbi.export_texture_r, resource_usage::shader_resource, resource_usage::copy_source);
            cmd->copy_texture_to_buffer(sbi.export_texture_r, 0, nullptr,
                                        sbi.depth_staging, 0, drd.texture.width, drd.texture.height);
            cmd->barrier(sbi.export_texture_r, resource_usage::copy_source, resource_usage::shader_resource);
        }
    }

    // ── Single GPU sync for both copies ──────────────────────────────────────
    queue->wait_idle();

    // ── CPU: de-pitch memcpy → task buffers, then return render thread ────────
    SaveTask task;
    task.bmp_path = save_prefix; task.bmp_path += L"BackBuffer.bmp";
    task.width    = crd.texture.width;
    task.height   = crd.texture.height;
    task.color_pixels.resize(task.width * task.height * 4);

    void* color_ptr = nullptr;
    dev->map_buffer_region(sbi.color_staging, 0, UINT64_MAX, map_access::read_only, &color_ptr);
    if (color_ptr) {
        const uint8_t* src = static_cast<const uint8_t*>(color_ptr);
        for (uint32_t y = 0; y < task.height; y++)
            std::memcpy(task.color_pixels.data() + y * task.width * 4,
                        src + y * color_row_pitch,
                        task.width * 4);
        dev->unmap_buffer_region(sbi.color_staging);
    }

    if (do_depth) {
        const resource_desc& drd = sbi.export_texture_rd;
        task.depth_path = save_prefix; task.depth_path += L"DepthBuffer.exr";
        task.depth_w = drd.texture.width;
        task.depth_h = drd.texture.height;
        task.depth_pixels.resize(task.depth_w * task.depth_h * 4);

        void* depth_ptr = nullptr;
        dev->map_buffer_region(sbi.depth_staging, 0, UINT64_MAX, map_access::read_only, &depth_ptr);
        if (depth_ptr) {
            const float* src      = static_cast<const float*>(depth_ptr);
            uint32_t floats_per_row = depth_row_pitch / sizeof(float);
            for (uint32_t y = 0; y < task.depth_h; y++)
                std::memcpy(task.depth_pixels.data() + y * task.depth_w * 4,
                            src + y * floats_per_row,
                            task.depth_w * 4 * sizeof(float));
            dev->unmap_buffer_region(sbi.depth_staging);
        }
    }

    // Enqueue — render thread is now free
    {
        std::lock_guard<std::mutex> lk(g_queue_mutex);
        g_save_queue.push(std::move(task));
    }
    g_queue_cv.notify_one();
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
    if (ImGui::CollapsingHeader("Settings")) {
        ImGui::Spacing();
        modified |= ImGui::Checkbox("Enable capturing with F10 key", &enableCapturing);
        modified |= ImGui::Checkbox("Export Depth",   &enableDepthExp);
        modified |= ImGui::Checkbox("Export Normals", &enableNormalExp);
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
    reshade::register_event<reshade::addon_event::init_effect_runtime>(on_init_effect_runtime);
    reshade::register_event<reshade::addon_event::destroy_effect_runtime>(on_destroy_effect_runtime);
    reshade::register_event<reshade::addon_event::reshade_present>(on_reshade_present);
    reshade::register_event<reshade::addon_event::reshade_begin_effects>(on_begin_render_effects);
}

void unregister_addon_FC()
{
    reshade::unregister_overlay("Frame Capture", draw_settings_overlay);
    reshade::unregister_event<reshade::addon_event::init_device>(on_init_device);
    reshade::unregister_event<reshade::addon_event::init_effect_runtime>(on_init_effect_runtime);
    reshade::unregister_event<reshade::addon_event::destroy_effect_runtime>(on_destroy_effect_runtime);
    reshade::unregister_event<reshade::addon_event::reshade_present>(on_reshade_present);
    reshade::unregister_event<reshade::addon_event::reshade_begin_effects>(on_begin_render_effects);
}

// ── DLL entry ─────────────────────────────────────────────────────────────────

extern "C" __declspec(dllexport) const char* NAME        = "Frame Capture";
extern "C" __declspec(dllexport) const char* DESCRIPTION = "Captures depth and color textures via ReShade. Press F10 to capture.";

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
