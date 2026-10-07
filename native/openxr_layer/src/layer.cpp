/*
 * Modern Tiny Pedals - OpenXR overlay layer
 * Copyright (C) 2022-2026 TinyPedal developers, see contributors.md file
 * SPDX-License-Identifier: GPL-3.0-or-later
 *
 * Implicit OpenXR API layer: draws the app's overlay image (shared memory, see tinypedal_vr_shared.h)
 * as a quad layer after the game's layers, in every OpenXR game and on every runtime (SteamVR, Meta,
 * Virtual Desktop, WMR, Pimax, Varjo...).
 *
 * Safety rules (a layer error would crash the game or break its VR):
 * - every OpenXR call of the game is forwarded unchanged, except xrEndFrame which may get one more layer;
 * - nothing is done unless the app is running and writing frames (heartbeat), or the API is unsupported;
 * - any failure stops the overlay for the session (pure pass-through), no exception leaves a hook;
 * - xrEndFrame retried without the overlay when the runtime refuses the added layer.
 */

#include "xr_includes.h"

#include <algorithm>
#include <atomic>
#include <cstdio>
#include <cstring>
#include <memory>
#include <mutex>
#include <unordered_map>
#include <vector>

#include "graphics.h"
#include "shared_frame.h"

#define TPVR_LAYER_NAME "XR_APILAYER_TINYPEDAL_overlay"

namespace tpvr {

void log_message(const char* message) {
    char line[512];
    std::snprintf(line, sizeof(line), "[TinyPedalXrLayer] %s\n", message);
    OutputDebugStringA(line);
}

namespace {

void log_result(const char* what, XrResult result) {
    char line[256];
    std::snprintf(line, sizeof(line), "%s failed: XrResult %d", what, static_cast<int>(result));
    log_message(line);
}

uint64_t now_ms() { return GetTickCount64(); }

// ---------------------------------------------------------------------------------------------------------
// Shared memory (created by the app). Opened when found, closed after the app is gone for a while, so an
// app started again (possibly another version) gets a new mapping.

constexpr uint64_t kOpenRetryMs = 1000;
constexpr uint64_t kCloseAfterGoneMs = 10000;

class SharedMapping {
public:
    ~SharedMapping() { close(); }

    // Run function(view, size, generation) with the mapping open, under lock. Returns false when not open.
    // generation changes each time the mapping is opened again (readers start over: other app run).
    template <class Function>
    bool with_view(uint64_t now, Function&& function) {
        std::lock_guard<std::mutex> lock(mutex_);
        if (view_ == nullptr) {
            if (now - last_open_attempt_ < kOpenRetryMs && last_open_attempt_ != 0) {
                return false;
            }
            last_open_attempt_ = now;
            if (!open()) {
                return false;
            }
            ++generation_;
            gone_since_ = 0;
        }
        if (app_alive(view_, size_, now)) {
            gone_since_ = 0;
        } else if (gone_since_ == 0) {
            gone_since_ = now;
        } else if (now - gone_since_ > kCloseAfterGoneMs) {
            close();
            last_open_attempt_ = now;
            return false;
        }
        function(view_, size_, generation_);
        return true;
    }

private:
    bool open() {
        handle_ = OpenFileMappingA(FILE_MAP_READ | FILE_MAP_WRITE, FALSE, TPVR_MAPPING_NAME);
        if (handle_ == nullptr) {
            return false;
        }
        void* view = MapViewOfFile(handle_, FILE_MAP_READ | FILE_MAP_WRITE, 0, 0, 0);
        if (view == nullptr) {
            close();
            return false;
        }
        MEMORY_BASIC_INFORMATION info = {};
        if (VirtualQuery(view, &info, sizeof(info)) == 0 || info.RegionSize < TPVR_DATA_OFFSET) {
            UnmapViewOfFile(view);
            close();
            return false;
        }
        view_ = static_cast<uint8_t*>(view);
        size_ = info.RegionSize;
        return true;
    }

    void close() {
        if (view_ != nullptr) {
            UnmapViewOfFile(view_);
            view_ = nullptr;
            size_ = 0;
        }
        if (handle_ != nullptr) {
            CloseHandle(handle_);
            handle_ = nullptr;
        }
    }

    std::mutex mutex_;
    HANDLE handle_ = nullptr;
    uint8_t* view_ = nullptr;
    size_t size_ = 0;
    uint64_t last_open_attempt_ = 0;
    uint64_t gone_since_ = 0;
    uint64_t generation_ = 0;
};

SharedMapping& shared_mapping() {
    static SharedMapping mapping;  // never destroyed before game exit (function local static)
    return mapping;
}

// ---------------------------------------------------------------------------------------------------------
// Dispatch

struct InstanceData {
    XrInstance handle = XR_NULL_HANDLE;
    bool enabled = false;  // all functions below found: hooks active, else pass-through
    PFN_xrGetInstanceProcAddr GetInstanceProcAddr = nullptr;
    PFN_xrDestroyInstance DestroyInstance = nullptr;
    PFN_xrCreateSession CreateSession = nullptr;
    PFN_xrDestroySession DestroySession = nullptr;
    PFN_xrEndFrame EndFrame = nullptr;
    PFN_xrGetSystemProperties GetSystemProperties = nullptr;
    PFN_xrEnumerateSwapchainFormats EnumerateSwapchainFormats = nullptr;
    PFN_xrCreateSwapchain CreateSwapchain = nullptr;
    PFN_xrDestroySwapchain DestroySwapchain = nullptr;
    PFN_xrEnumerateSwapchainImages EnumerateSwapchainImages = nullptr;
    PFN_xrAcquireSwapchainImage AcquireSwapchainImage = nullptr;
    PFN_xrWaitSwapchainImage WaitSwapchainImage = nullptr;
    PFN_xrReleaseSwapchainImage ReleaseSwapchainImage = nullptr;
    PFN_xrCreateReferenceSpace CreateReferenceSpace = nullptr;
    PFN_xrDestroySpace DestroySpace = nullptr;
};

struct SessionData {
    std::mutex mutex;  // xrEndFrame & xrDestroySession
    XrSession handle = XR_NULL_HANDLE;
    std::shared_ptr<InstanceData> instance;
    std::unique_ptr<GraphicsBackend> graphics;
    uint32_t graphics_api = TPVR_GRAPHICS_NONE;
    bool failed = false;  // overlay stopped for this session
    int32_t last_result = 0;
    uint32_t max_layers = 0;
    uint32_t max_width = 0;
    uint32_t max_height = 0;
    // Layer resources (created on first frame to draw)
    XrSpace view_space = XR_NULL_HANDLE;
    XrSpace local_space = XR_NULL_HANDLE;
    XrSwapchain swapchain = XR_NULL_HANDLE;
    uint32_t swapchain_width = 0;
    uint32_t swapchain_height = 0;
    const FormatCandidate* format = nullptr;
    bool pending = false;  // image acquired, not waited yet (wait timed out)
    uint32_t pending_index = 0;
    bool stale = false;  // reader pixels newer than last upload
    uint32_t upload_failures = 0;  // in a row
    uint32_t pending_width = 0;  // image being uploaded
    uint32_t pending_height = 0;
    uint32_t pending_format = 0;
    bool image_valid = false;  // a released image holds the overlay (shown_* size & format)
    uint32_t shown_width = 0;
    uint32_t shown_height = 0;
    uint32_t shown_format = 0;
    std::vector<uint8_t> upload;
    uint32_t upload_width = 0;
    uint32_t upload_height = 0;
    FrameReader reader;
    uint64_t mapping_generation = 0;
    // Submitted layers (kept until next frame)
    XrCompositionLayerQuad quad = {};
    std::vector<const XrCompositionLayerBaseHeader*> layers;
    uint64_t frames_shown = 0;
};

std::mutex g_mutex;
std::unordered_map<XrInstance, std::shared_ptr<InstanceData>> g_instances;
std::unordered_map<XrSession, std::shared_ptr<SessionData>> g_sessions;
// Fallbacks for a handle unknown to the layer (its state could not be stored): call forwarded unchanged
std::atomic<PFN_xrGetInstanceProcAddr> g_next_get_instance_proc_addr{nullptr};
std::atomic<PFN_xrEndFrame> g_next_end_frame{nullptr};
std::atomic<PFN_xrDestroySession> g_next_destroy_session{nullptr};

std::shared_ptr<InstanceData> find_instance(XrInstance instance) {
    std::lock_guard<std::mutex> lock(g_mutex);
    const auto found = g_instances.find(instance);
    return found != g_instances.end() ? found->second : nullptr;
}

std::shared_ptr<SessionData> find_session(XrSession session) {
    std::lock_guard<std::mutex> lock(g_mutex);
    const auto found = g_sessions.find(session);
    return found != g_sessions.end() ? found->second : nullptr;
}

template <class T>
bool resolve(PFN_xrGetInstanceProcAddr get_proc, XrInstance instance, const char* name, T& function) {
    PFN_xrVoidFunction address = nullptr;
    if (XR_FAILED(get_proc(instance, name, &address)) || address == nullptr) {
        function = nullptr;
        return false;
    }
    function = reinterpret_cast<T>(address);
    return true;
}

// ---------------------------------------------------------------------------------------------------------
// Overlay resources (session lock held)

void fail(SessionData& session, const char* what, XrResult result) {
    session.failed = true;
    session.last_result = static_cast<int32_t>(result);
    log_result(what, result);
}

void destroy_swapchain(SessionData& session) {
    if (session.swapchain != XR_NULL_HANDLE) {
        if (session.graphics) {
            session.graphics->clear_swapchain();
        }
        session.instance->DestroySwapchain(session.swapchain);
        session.swapchain = XR_NULL_HANDLE;
    }
    session.swapchain_width = session.swapchain_height = 0;
    session.pending = false;
    session.image_valid = false;
}

void destroy_resources(SessionData& session) {
    destroy_swapchain(session);
    if (session.view_space != XR_NULL_HANDLE) {
        session.instance->DestroySpace(session.view_space);
        session.view_space = XR_NULL_HANDLE;
    }
    if (session.local_space != XR_NULL_HANDLE) {
        session.instance->DestroySpace(session.local_space);
        session.local_space = XR_NULL_HANDLE;
    }
}

bool ensure_spaces(SessionData& session) {
    if (session.view_space != XR_NULL_HANDLE && session.local_space != XR_NULL_HANDLE) {
        return true;
    }
    XrReferenceSpaceCreateInfo info{};
    info.type = XR_TYPE_REFERENCE_SPACE_CREATE_INFO;
    info.poseInReferenceSpace.orientation.w = 1.0f;
    if (session.view_space == XR_NULL_HANDLE) {
        info.referenceSpaceType = XR_REFERENCE_SPACE_TYPE_VIEW;
        const XrResult result = session.instance->CreateReferenceSpace(session.handle, &info, &session.view_space);
        if (XR_FAILED(result)) {
            session.view_space = XR_NULL_HANDLE;
            fail(session, "xrCreateReferenceSpace(VIEW)", result);
            return false;
        }
    }
    if (session.local_space == XR_NULL_HANDLE) {
        info.referenceSpaceType = XR_REFERENCE_SPACE_TYPE_LOCAL;
        const XrResult result = session.instance->CreateReferenceSpace(session.handle, &info, &session.local_space);
        if (XR_FAILED(result)) {
            session.local_space = XR_NULL_HANDLE;
            fail(session, "xrCreateReferenceSpace(LOCAL)", result);
            return false;
        }
    }
    return true;
}

bool choose_swapchain_format(SessionData& session) {
    if (session.format != nullptr) {
        return true;
    }
    uint32_t count = 0;
    XrResult result = session.instance->EnumerateSwapchainFormats(session.handle, 0, &count, nullptr);
    if (XR_FAILED(result) || count == 0 || count > 1024) {
        fail(session, "xrEnumerateSwapchainFormats", XR_FAILED(result) ? result : XR_ERROR_RUNTIME_FAILURE);
        return false;
    }
    std::vector<int64_t> formats(count);
    result = session.instance->EnumerateSwapchainFormats(session.handle, count, &count, formats.data());
    if (XR_FAILED(result)) {
        fail(session, "xrEnumerateSwapchainFormats", result);
        return false;
    }
    size_t candidate_count = 0;
    const FormatCandidate* candidates = session.graphics->format_candidates(candidate_count);
    session.format = choose_format(formats.data(), count, candidates, candidate_count);
    if (session.format == nullptr) {
        fail(session, "no RGBA8 swapchain format", XR_ERROR_SWAPCHAIN_FORMAT_UNSUPPORTED);
        return false;
    }
    return true;
}

// Swapchain big enough for image (plus border), created again only when image grows
bool ensure_swapchain(SessionData& session, uint32_t width, uint32_t height) {
    if (!choose_swapchain_format(session)) {
        return false;
    }
    const uint32_t new_width = swapchain_extent(width, session.swapchain_width, session.max_width);
    const uint32_t new_height = swapchain_extent(height, session.swapchain_height, session.max_height);
    if (new_width == 0 || new_height == 0) {
        return false;  // image bigger than runtime allows: not shown (app keeps images to 1 M pixels)
    }
    if (session.swapchain != XR_NULL_HANDLE && new_width == session.swapchain_width &&
        new_height == session.swapchain_height) {
        return true;
    }
    destroy_swapchain(session);
    XrSwapchainCreateInfo info{};
    info.type = XR_TYPE_SWAPCHAIN_CREATE_INFO;
    info.usageFlags = XR_SWAPCHAIN_USAGE_COLOR_ATTACHMENT_BIT | XR_SWAPCHAIN_USAGE_SAMPLED_BIT |
                      XR_SWAPCHAIN_USAGE_TRANSFER_DST_BIT;
    info.format = session.format->format;
    info.sampleCount = 1;
    info.width = new_width;
    info.height = new_height;
    info.faceCount = 1;
    info.arraySize = 1;
    info.mipCount = 1;
    XrResult result = session.instance->CreateSwapchain(session.handle, &info, &session.swapchain);
    if (XR_FAILED(result) && session.graphics_api == TPVR_GRAPHICS_D3D11) {
        // D3D11 UpdateSubresource needs no transfer usage, some runtimes refuse it
        info.usageFlags = XR_SWAPCHAIN_USAGE_COLOR_ATTACHMENT_BIT | XR_SWAPCHAIN_USAGE_SAMPLED_BIT;
        result = session.instance->CreateSwapchain(session.handle, &info, &session.swapchain);
    }
    if (XR_FAILED(result)) {
        session.swapchain = XR_NULL_HANDLE;
        fail(session, "xrCreateSwapchain", result);
        return false;
    }
    if (!session.graphics->set_swapchain(session.swapchain, session.instance->EnumerateSwapchainImages,
                                         session.format->format)) {
        session.instance->DestroySwapchain(session.swapchain);
        session.swapchain = XR_NULL_HANDLE;
        fail(session, "xrEnumerateSwapchainImages", XR_ERROR_RUNTIME_FAILURE);
        return false;
    }
    session.swapchain_width = new_width;
    session.swapchain_height = new_height;
    return true;
}

// Newer pixels: converted, then copied into the next swapchain image (acquire, wait, upload, release).
// A wait that times out is finished on a later frame (last released image shown meanwhile); pixels changed
// meanwhile are uploaded on the frame after.
void update_image(SessionData& session) {
    if (!session.pending && session.stale) {
        const FrameInfo& info = session.reader.info();
        if (!ensure_swapchain(session, info.width, info.height)) {
            session.image_valid = false;
            return;
        }
        session.stale = false;
        session.upload_width = std::min(info.width + 1u, session.swapchain_width);
        session.upload_height = std::min(info.height + 1u, session.swapchain_height);
        convert_pixels(session.reader.pixels().data(), info.width, info.height, session.upload_width,
                       session.upload_height, session.format->bgra, !session.format->srgb, session.upload);
        session.pending_width = info.width;
        session.pending_height = info.height;
        session.pending_format = info.pixel_format;
        XrSwapchainImageAcquireInfo acquire{};
        acquire.type = XR_TYPE_SWAPCHAIN_IMAGE_ACQUIRE_INFO;
        const XrResult result =
            session.instance->AcquireSwapchainImage(session.swapchain, &acquire, &session.pending_index);
        if (XR_FAILED(result)) {
            fail(session, "xrAcquireSwapchainImage", result);
            return;
        }
        session.pending = true;
    }
    if (!session.pending) {
        return;
    }
    XrSwapchainImageWaitInfo wait{};
    wait.type = XR_TYPE_SWAPCHAIN_IMAGE_WAIT_INFO;
    wait.timeout = 2000000;  // 2 ms
    XrResult result = session.instance->WaitSwapchainImage(session.swapchain, &wait);
    if (result == XR_TIMEOUT_EXPIRED) {
        return;
    }
    if (XR_FAILED(result)) {
        fail(session, "xrWaitSwapchainImage", result);
        return;
    }
    const bool uploaded = session.graphics->upload(session.pending_index, session.upload.data(), session.upload_width,
                                                   session.upload_height);
    XrSwapchainImageReleaseInfo release{};
    release.type = XR_TYPE_SWAPCHAIN_IMAGE_RELEASE_INFO;
    result = session.instance->ReleaseSwapchainImage(session.swapchain, &release);
    session.pending = false;
    if (XR_FAILED(result)) {
        fail(session, "xrReleaseSwapchainImage", result);
        return;
    }
    session.image_valid = uploaded;
    session.upload_failures = uploaded ? 0 : session.upload_failures + 1;
    if (session.upload_failures >= 10) {
        fail(session, "image upload", XR_ERROR_RUNTIME_FAILURE);
        return;
    }
    if (uploaded) {
        session.shown_width = session.pending_width;
        session.shown_height = session.pending_height;
        session.shown_format = session.pending_format;
    } else {
        // GPU busy: tried again on next frame
        session.stale = true;
    }
}

// Prepare frame end info with overlay quad appended. False: submit game's frame unchanged.
bool prepare_overlay(SessionData& session, const XrFrameEndInfo& frame, XrFrameEndInfo& patched) {
    const uint64_t now = now_ms();
    bool drawable = false;
    bool pixels_changed = false;
    shared_mapping().with_view(now, [&](uint8_t* view, size_t size, uint64_t generation) {
        if (generation != session.mapping_generation) {
            session.mapping_generation = generation;  // new mapping: sequence & serial start over
            session.reader.reset();
        }
        if (session.graphics && !session.failed) {
            session.reader.read(view, size, now);
            drawable = session.reader.drawable();
            pixels_changed = session.reader.take_pixels_changed();
        }
        LayerStatus status;
        status.pid = GetCurrentProcessId();
        status.graphics_api = session.graphics_api;
        status.state = session.failed ? TPVR_LAYER_FAILED : session.graphics ? TPVR_LAYER_ACTIVE : TPVR_LAYER_UNSUPPORTED;
        status.last_result = session.last_result;
        status.frames_shown = session.frames_shown;
        write_layer_status(view, size, status, now);
    });
    if (!drawable || session.failed) {
        return false;
    }
    if (frame.layerCount == 0 || frame.layers == nullptr || frame.layerCount + 1u > session.max_layers) {
        return false;  // game shows nothing (loading), or no room for one more layer
    }
    if (!ensure_spaces(session)) {
        return false;
    }
    if (pixels_changed) {
        session.stale = true;
    }
    if (session.stale || session.pending) {
        update_image(session);
    }
    if (session.failed || !session.image_valid || session.swapchain == XR_NULL_HANDLE || session.shown_width == 0) {
        return false;
    }
    const FrameInfo& info = session.reader.info();
    XrCompositionLayerQuad& quad = session.quad;
    quad = XrCompositionLayerQuad{};
    quad.type = XR_TYPE_COMPOSITION_LAYER_QUAD;
    quad.layerFlags = XR_COMPOSITION_LAYER_BLEND_TEXTURE_SOURCE_ALPHA_BIT;
    if (session.shown_format == TPVR_FORMAT_RGBA8_STRAIGHT) {
        quad.layerFlags |= XR_COMPOSITION_LAYER_UNPREMULTIPLIED_ALPHA_BIT;
    }
    quad.space = info.attach_to_headset ? session.view_space : session.local_space;
    quad.eyeVisibility = XR_EYE_VISIBILITY_BOTH;
    quad.subImage.swapchain = session.swapchain;
    quad.subImage.imageRect.offset = {0, 0};
    quad.subImage.imageRect.extent = {static_cast<int32_t>(session.shown_width), static_cast<int32_t>(session.shown_height)};
    quad.subImage.imageArrayIndex = 0;
    quad.pose.orientation = {0.0f, 0.0f, 0.0f, 1.0f};
    quad.pose.position = {info.horizontal_offset_meters, info.vertical_offset_meters, -info.distance_meters};
    quad.size.width = info.width_meters;
    quad.size.height = info.width_meters * static_cast<float>(session.shown_height) / static_cast<float>(session.shown_width);

    session.layers.assign(frame.layers, frame.layers + frame.layerCount);
    session.layers.push_back(reinterpret_cast<const XrCompositionLayerBaseHeader*>(&quad));
    patched = frame;
    patched.layerCount = static_cast<uint32_t>(session.layers.size());
    patched.layers = session.layers.data();
    return true;
}

// ---------------------------------------------------------------------------------------------------------
// Hooks

XRAPI_ATTR XrResult XRAPI_CALL hook_xrEndFrame(XrSession session, const XrFrameEndInfo* frameEndInfo) {
    std::shared_ptr<SessionData> data;
    try {
        data = find_session(session);
    } catch (...) {
        data = nullptr;
    }
    if (!data || !data->instance || data->instance->EndFrame == nullptr) {
        const PFN_xrEndFrame fallback = g_next_end_frame.load();  // session state not stored (out of memory)
        return fallback != nullptr ? fallback(session, frameEndInfo) : XR_ERROR_HANDLE_INVALID;
    }
    const PFN_xrEndFrame next = data->instance->EndFrame;
    std::unique_lock<std::mutex> lock(data->mutex, std::defer_lock);
    XrFrameEndInfo patched = {};
    bool overlay = false;
    try {
        lock.lock();
        if (frameEndInfo != nullptr && frameEndInfo->type == XR_TYPE_FRAME_END_INFO) {
            overlay = prepare_overlay(*data, *frameEndInfo, patched);
        }
    } catch (...) {
        overlay = false;
        data->failed = true;
        log_message("exception in xrEndFrame: overlay stopped");
    }
    if (!overlay) {
        return next(session, frameEndInfo);
    }
    XrResult result = next(session, &patched);
    if (XR_SUCCEEDED(result)) {
        ++data->frames_shown;
        return result;
    }
    if (result == XR_ERROR_LAYER_INVALID || result == XR_ERROR_LAYER_LIMIT_EXCEEDED ||
        result == XR_ERROR_SWAPCHAIN_RECT_INVALID || result == XR_ERROR_VALIDATION_FAILURE ||
        result == XR_ERROR_HANDLE_INVALID || result == XR_ERROR_POSE_INVALID) {
        // Overlay refused (layer, space or swapchain): frame submitted again as the game made it
        data->failed = true;
        data->last_result = static_cast<int32_t>(result);
        log_result("xrEndFrame with overlay", result);
        return next(session, frameEndInfo);
    }
    return result;
}

XRAPI_ATTR XrResult XRAPI_CALL hook_xrCreateSession(XrInstance instance, const XrSessionCreateInfo* createInfo,
                                                    XrSession* session) {
    std::shared_ptr<InstanceData> data;
    try {
        data = find_instance(instance);
    } catch (...) {
        data = nullptr;
    }
    if (!data || data->CreateSession == nullptr) {
        return XR_ERROR_HANDLE_INVALID;  // unreachable: hook given only for known instances
    }
    const XrResult result = data->CreateSession(instance, createInfo, session);
    if (XR_FAILED(result) || createInfo == nullptr || session == nullptr) {
        return result;
    }
    try {
        auto state = std::make_shared<SessionData>();
        state->handle = *session;
        state->instance = data;
        for (auto* entry = static_cast<const XrBaseInStructure*>(createInfo->next); entry != nullptr; entry = entry->next) {
            if (entry->type == XR_TYPE_GRAPHICS_BINDING_D3D11_KHR) {
                state->graphics_api = TPVR_GRAPHICS_D3D11;
                state->graphics = create_d3d11_backend(*reinterpret_cast<const XrGraphicsBindingD3D11KHR*>(entry));
                break;
            }
            if (entry->type == XR_TYPE_GRAPHICS_BINDING_D3D12_KHR) {
                state->graphics_api = TPVR_GRAPHICS_D3D12;
                state->graphics = create_d3d12_backend(*reinterpret_cast<const XrGraphicsBindingD3D12KHR*>(entry));
                break;
            }
            if (entry->type == XR_TYPE_GRAPHICS_BINDING_VULKAN_KHR) {  // also XrGraphicsBindingVulkan2KHR
                state->graphics_api = TPVR_GRAPHICS_VULKAN;
                state->graphics = create_vulkan_backend(*reinterpret_cast<const XrGraphicsBindingVulkanKHR*>(entry));
                break;
            }
            if (entry->type == XR_TYPE_GRAPHICS_BINDING_OPENGL_WIN32_KHR) {
                state->graphics_api = TPVR_GRAPHICS_OPENGL;  // not supported: pass-through
                break;
            }
        }
        if (state->graphics) {
            XrSystemProperties properties{};
            properties.type = XR_TYPE_SYSTEM_PROPERTIES;
            const XrResult system = data->GetSystemProperties(instance, createInfo->systemId, &properties);
            if (XR_SUCCEEDED(system)) {
                state->max_layers = properties.graphicsProperties.maxLayerCount;
                state->max_width = std::min<uint32_t>(properties.graphicsProperties.maxSwapchainImageWidth, TPVR_MAX_DIMENSION + 64u);
                state->max_height = std::min<uint32_t>(properties.graphicsProperties.maxSwapchainImageHeight, TPVR_MAX_DIMENSION + 64u);
            } else {
                state->graphics.reset();  // nothing known about limits: pass-through
                state->last_result = static_cast<int32_t>(system);
            }
        } else if (state->graphics_api == TPVR_GRAPHICS_NONE) {
            state->graphics_api = TPVR_GRAPHICS_OTHER;
        }
        std::lock_guard<std::mutex> lock(g_mutex);
        g_sessions[*session] = state;
    } catch (...) {
        log_message("xrCreateSession: overlay not available for session");
    }
    return result;
}

XRAPI_ATTR XrResult XRAPI_CALL hook_xrDestroySession(XrSession session) {
    std::shared_ptr<SessionData> data;
    try {
        std::lock_guard<std::mutex> lock(g_mutex);
        const auto found = g_sessions.find(session);
        if (found != g_sessions.end()) {
            data = found->second;
            g_sessions.erase(found);
        }
    } catch (...) {
        data = nullptr;
    }
    if (!data || !data->instance || data->instance->DestroySession == nullptr) {
        const PFN_xrDestroySession fallback = g_next_destroy_session.load();
        return fallback != nullptr ? fallback(session) : XR_ERROR_HANDLE_INVALID;
    }
    try {
        std::lock_guard<std::mutex> lock(data->mutex);
        destroy_resources(*data);
        data->graphics.reset();
        shared_mapping().with_view(now_ms(), [](uint8_t* view, size_t size, uint64_t) {
            LayerStatus status;
            status.pid = GetCurrentProcessId();
            write_layer_status(view, size, status, 0);  // heartbeat 0: no session
        });
    } catch (...) {
        log_message("xrDestroySession: cleanup failed");
    }
    return data->instance->DestroySession(session);
}

XRAPI_ATTR XrResult XRAPI_CALL hook_xrDestroyInstance(XrInstance instance) {
    std::shared_ptr<InstanceData> data;
    std::vector<std::shared_ptr<SessionData>> sessions;
    try {
        std::lock_guard<std::mutex> lock(g_mutex);
        const auto found = g_instances.find(instance);
        if (found != g_instances.end()) {
            data = found->second;
            g_instances.erase(found);
        }
        for (auto it = g_sessions.begin(); it != g_sessions.end();) {
            if (it->second->instance == data) {
                sessions.push_back(it->second);
                it = g_sessions.erase(it);
            } else {
                ++it;
            }
        }
    } catch (...) {
        sessions.clear();
    }
    if (!data || data->DestroyInstance == nullptr) {
        return XR_ERROR_HANDLE_INVALID;
    }
    for (auto& session : sessions) {
        try {
            // Handles destroyed by the runtime with the instance, graphics resources released here
            std::lock_guard<std::mutex> lock(session->mutex);
            if (session->graphics) {
                session->graphics->clear_swapchain();
            }
            session->graphics.reset();
        } catch (...) {
        }
    }
    return data->DestroyInstance(instance);
}

XRAPI_ATTR XrResult XRAPI_CALL hook_xrGetInstanceProcAddr(XrInstance instance, const char* name,
                                                          PFN_xrVoidFunction* function) {
    std::shared_ptr<InstanceData> data;
    try {
        data = instance != XR_NULL_HANDLE ? find_instance(instance) : nullptr;
    } catch (...) {
        data = nullptr;
    }
    const PFN_xrGetInstanceProcAddr next = data ? data->GetInstanceProcAddr : g_next_get_instance_proc_addr.load();
    if (next == nullptr) {
        if (function != nullptr) {
            *function = nullptr;
        }
        return XR_ERROR_FUNCTION_UNSUPPORTED;
    }
    const XrResult result = next(instance, name, function);
    if (XR_FAILED(result) || !data || !data->enabled || name == nullptr || function == nullptr || *function == nullptr) {
        return result;
    }
    if (std::strcmp(name, "xrGetInstanceProcAddr") == 0) {
        *function = reinterpret_cast<PFN_xrVoidFunction>(hook_xrGetInstanceProcAddr);
    } else if (std::strcmp(name, "xrDestroyInstance") == 0) {
        *function = reinterpret_cast<PFN_xrVoidFunction>(hook_xrDestroyInstance);
    } else if (std::strcmp(name, "xrCreateSession") == 0) {
        *function = reinterpret_cast<PFN_xrVoidFunction>(hook_xrCreateSession);
    } else if (std::strcmp(name, "xrDestroySession") == 0) {
        *function = reinterpret_cast<PFN_xrVoidFunction>(hook_xrDestroySession);
    } else if (std::strcmp(name, "xrEndFrame") == 0) {
        *function = reinterpret_cast<PFN_xrVoidFunction>(hook_xrEndFrame);
    }
    return result;
}

XRAPI_ATTR XrResult XRAPI_CALL layer_xrCreateApiLayerInstance(const XrInstanceCreateInfo* info,
                                                              const XrApiLayerCreateInfo* layerInfo,
                                                              XrInstance* instance) {
    if (layerInfo == nullptr || layerInfo->nextInfo == nullptr ||
        layerInfo->nextInfo->nextCreateApiLayerInstance == nullptr ||
        layerInfo->nextInfo->nextGetInstanceProcAddr == nullptr) {
        return XR_ERROR_INITIALIZATION_FAILED;
    }
    const PFN_xrGetInstanceProcAddr next_get_proc = layerInfo->nextInfo->nextGetInstanceProcAddr;
    XrApiLayerCreateInfo next_info = *layerInfo;
    next_info.nextInfo = layerInfo->nextInfo->next;
    const XrResult result = layerInfo->nextInfo->nextCreateApiLayerInstance(info, &next_info, instance);
    if (XR_FAILED(result) || instance == nullptr) {
        return result;
    }
    g_next_get_instance_proc_addr.store(next_get_proc);
    try {
        auto data = std::make_shared<InstanceData>();
        data->handle = *instance;
        data->GetInstanceProcAddr = next_get_proc;
        const XrInstance handle = *instance;
        // Functions forwarded by hooks: pass-through for the whole instance when any is missing
        bool forward = resolve(next_get_proc, handle, "xrDestroyInstance", data->DestroyInstance);
        forward = resolve(next_get_proc, handle, "xrCreateSession", data->CreateSession) && forward;
        forward = resolve(next_get_proc, handle, "xrDestroySession", data->DestroySession) && forward;
        forward = resolve(next_get_proc, handle, "xrEndFrame", data->EndFrame) && forward;
        bool used = resolve(next_get_proc, handle, "xrGetSystemProperties", data->GetSystemProperties);
        used = resolve(next_get_proc, handle, "xrEnumerateSwapchainFormats", data->EnumerateSwapchainFormats) && used;
        used = resolve(next_get_proc, handle, "xrCreateSwapchain", data->CreateSwapchain) && used;
        used = resolve(next_get_proc, handle, "xrDestroySwapchain", data->DestroySwapchain) && used;
        used = resolve(next_get_proc, handle, "xrEnumerateSwapchainImages", data->EnumerateSwapchainImages) && used;
        used = resolve(next_get_proc, handle, "xrAcquireSwapchainImage", data->AcquireSwapchainImage) && used;
        used = resolve(next_get_proc, handle, "xrWaitSwapchainImage", data->WaitSwapchainImage) && used;
        used = resolve(next_get_proc, handle, "xrReleaseSwapchainImage", data->ReleaseSwapchainImage) && used;
        used = resolve(next_get_proc, handle, "xrCreateReferenceSpace", data->CreateReferenceSpace) && used;
        used = resolve(next_get_proc, handle, "xrDestroySpace", data->DestroySpace) && used;
        data->enabled = forward && used;
        if (data->enabled) {
            g_next_end_frame.store(data->EndFrame);
            g_next_destroy_session.store(data->DestroySession);
        }
        if (!data->enabled) {
            log_message("OpenXR functions missing: layer inactive for this instance");
        }
        std::lock_guard<std::mutex> lock(g_mutex);
        g_instances[handle] = data;
    } catch (...) {
        log_message("xrCreateInstance: layer inactive for this instance");
    }
    return result;
}

}  // namespace
}  // namespace tpvr

extern "C" __declspec(dllexport) XRAPI_ATTR XrResult XRAPI_CALL xrNegotiateLoaderApiLayerInterface(
    const XrNegotiateLoaderInfo* loaderInfo, const char* layerName, XrNegotiateApiLayerRequest* apiLayerRequest) {
    if (loaderInfo == nullptr || apiLayerRequest == nullptr ||
        loaderInfo->structType != XR_LOADER_INTERFACE_STRUCT_LOADER_INFO ||
        loaderInfo->structVersion != XR_LOADER_INFO_STRUCT_VERSION ||
        loaderInfo->structSize != sizeof(XrNegotiateLoaderInfo) ||
        apiLayerRequest->structType != XR_LOADER_INTERFACE_STRUCT_API_LAYER_REQUEST ||
        apiLayerRequest->structVersion != XR_API_LAYER_INFO_STRUCT_VERSION ||
        apiLayerRequest->structSize != sizeof(XrNegotiateApiLayerRequest)) {
        return XR_ERROR_INITIALIZATION_FAILED;
    }
    if (layerName != nullptr && std::strcmp(layerName, TPVR_LAYER_NAME) != 0) {
        return XR_ERROR_INITIALIZATION_FAILED;
    }
    if (loaderInfo->minInterfaceVersion > XR_CURRENT_LOADER_API_LAYER_VERSION ||
        loaderInfo->maxInterfaceVersion < XR_CURRENT_LOADER_API_LAYER_VERSION) {
        return XR_ERROR_INITIALIZATION_FAILED;
    }
    // Only OpenXR 1.0 functions & structures are used: any 1.x version accepted
    XrVersion api_version = XR_MAKE_VERSION(1, 0, 0);
    if (api_version < loaderInfo->minApiVersion) {
        api_version = loaderInfo->minApiVersion;
    }
    if (api_version > loaderInfo->maxApiVersion || XR_VERSION_MAJOR(api_version) != 1) {
        return XR_ERROR_INITIALIZATION_FAILED;
    }
    apiLayerRequest->layerInterfaceVersion = XR_CURRENT_LOADER_API_LAYER_VERSION;
    apiLayerRequest->layerApiVersion = api_version;
    apiLayerRequest->getInstanceProcAddr = tpvr::hook_xrGetInstanceProcAddr;
    apiLayerRequest->createApiLayerInstance = tpvr::layer_xrCreateApiLayerInstance;
    return XR_SUCCESS;
}
