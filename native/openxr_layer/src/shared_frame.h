/*
 * Modern Tiny Pedals - OpenXR overlay layer
 * Copyright (C) 2022-2026 TinyPedal developers, see contributors.md file
 * SPDX-License-Identifier: GPL-3.0-or-later
 *
 * Shared memory frame reader (platform neutral, unit tested on Linux: tests/shared_frame_test.cpp).
 * Every field read from shared memory is validated: the app may write anything, be closed or restarted
 * at any time, the reader never reads outside the mapped view and never keeps a torn image.
 */

#ifndef TINYPEDAL_SHARED_FRAME_H
#define TINYPEDAL_SHARED_FRAME_H

#include <cstddef>
#include <cstdint>
#include <vector>

#include "tinypedal_vr_shared.h"

namespace tpvr {

struct FrameInfo {
    uint32_t width = 0;
    uint32_t height = 0;
    uint32_t pixel_format = 0;
    uint32_t image_serial = 0;
    bool visible = false;
    bool attach_to_headset = false;
    float width_meters = 0.0f;
    float distance_meters = 0.0f;
    float vertical_offset_meters = 0.0f;
    float horizontal_offset_meters = 0.0f;
};

enum class ReadResult {
    Updated,    // new frame (placement and/or pixels) copied
    Unchanged,  // same frame as before
    Busy,       // app writing (or wrote during copy): last frame kept, read again next time
    Invalid,    // header not valid (other version, bad sizes): nothing to draw
    AppGone,    // app heartbeat too old (app closed or frozen): nothing to draw
};

class FrameReader {
public:
    // Read mapped view (base, size bytes) at now_ms (GetTickCount64 clock, same as app).
    // Pixels are copied only when their serial changed. Never throws except std::bad_alloc.
    ReadResult read(const uint8_t* base, size_t size, uint64_t now_ms);

    // Frame drawable: valid, visible frame with pixels, app alive at last read
    bool drawable() const { return has_frame_ && alive_ && info_.visible && !pixels_.empty(); }
    const FrameInfo& info() const { return info_; }
    // Tightly packed rows (width * 4 bytes), RGBA order
    const std::vector<uint8_t>& pixels() const { return pixels_; }
    // True once after pixels changed (consumer uploads them)
    bool take_pixels_changed() {
        const bool changed = pixels_changed_;
        pixels_changed_ = false;
        return changed;
    }
    void reset();

private:
    bool has_frame_ = false;
    bool alive_ = false;
    bool pixels_changed_ = false;
    uint64_t last_sequence_ = 0;
    FrameInfo info_;
    std::vector<uint8_t> pixels_;
    std::vector<uint8_t> scratch_;
};

// App heartbeat recent enough (same rule as FrameReader::read)
bool app_alive(const uint8_t* base, size_t size, uint64_t now_ms);

struct LayerStatus {
    uint32_t pid = 0;
    uint32_t state = TPVR_LAYER_IDLE;
    uint32_t graphics_api = TPVR_GRAPHICS_NONE;
    int32_t last_result = 0;
    uint64_t frames_shown = 0;
};

// Write layer fields (heartbeat last) if the view holds a valid header
void write_layer_status(uint8_t* base, size_t size, const LayerStatus& status, uint64_t now_ms);

// Swapchain format candidate, in order of preference
struct FormatCandidate {
    int64_t format;
    bool bgra;  // B, G, R, A byte order
    bool srgb;  // runtime decodes sRGB (else values are linear: app colors converted)
};

// First candidate the runtime supports, nullptr if none
const FormatCandidate* choose_format(const int64_t* runtime_formats, size_t runtime_count,
                                     const FormatCandidate* candidates, size_t candidate_count);

// Swapchain size able to hold image plus a 1 pixel transparent border (right & bottom, bilinear filtering),
// rounded up to 64 pixels, at least current size, at most max size. 0 when image does not fit.
uint32_t swapchain_extent(uint32_t image, uint32_t current, uint32_t max);

// Upload buffer (out_width * out_height RGBA or BGRA, tightly packed) from packed RGBA frame pixels:
// image at top left, rest transparent, channels swapped for BGRA, colors converted from sRGB to linear
// for a linear (non sRGB) swapchain format. out_width >= width & out_height >= height.
void convert_pixels(const uint8_t* pixels, uint32_t width, uint32_t height, uint32_t out_width, uint32_t out_height,
                    bool bgra, bool linear, std::vector<uint8_t>& out);

}  // namespace tpvr

#endif  // TINYPEDAL_SHARED_FRAME_H
