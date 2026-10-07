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

#include <array>
#include <cstddef>
#include <cstdint>
#include <vector>

#include "tinypedal_vr_shared.h"

namespace tpvr {

// Pixel rectangle
struct Rect {
    uint32_t x = 0;
    uint32_t y = 0;
    uint32_t width = 0;
    uint32_t height = 0;
};

bool operator==(const Rect& left, const Rect& right);

// Validated tile: atlas rectangle shown 1:1 at (canvas_x, canvas_y) of the canvas
struct Tile {
    Rect atlas;
    uint32_t canvas_x = 0;
    uint32_t canvas_y = 0;
};

struct FrameInfo {
    uint32_t width = 0;  // atlas
    uint32_t height = 0;
    uint32_t pixel_format = 0;
    uint32_t image_serial = 0;
    bool visible = false;
    bool attach_to_headset = false;
    float width_meters = 0.0f;
    float distance_meters = 0.0f;
    float vertical_offset_meters = 0.0f;
    float horizontal_offset_meters = 0.0f;
    uint32_t canvas_width = 0;
    uint32_t canvas_height = 0;
    uint32_t tile_count = 0;  // tiles used (1 .. TPVR_MAX_TILES when drawable)
    std::array<Tile, TPVR_MAX_TILES> tiles{};
};

enum class ReadResult {
    Updated,    // new frame (placement and/or pixels) copied
    Unchanged,  // same frame as before
    Busy,       // app writing (or wrote during copy): last frame kept, read again next time
    Invalid,    // header not valid (other version, bad sizes): nothing to draw
    AppGone,    // app heartbeat too old (app closed or frozen): nothing to draw
    VersionMismatch,  // app alive, writing another protocol version: nothing to draw (report it)
};

class FrameReader {
public:
    // Read mapped view (base, size bytes) at now_ms (GetTickCount64 clock, same as app).
    // Pixels are copied only when their serial changed. Never throws except std::bad_alloc.
    ReadResult read(const uint8_t* base, size_t size, uint64_t now_ms);

    // Frame drawable: valid, visible frame with pixels & tiles, app alive at last read
    bool drawable() const {
        return has_frame_ && alive_ && info_.visible && !pixels_.empty() && info_.tile_count != 0;
    }
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

// App heartbeat recent enough (same rule as FrameReader::read), app of any protocol version
bool app_alive(const uint8_t* base, size_t size, uint64_t now_ms);

struct LayerStatus {
    uint32_t pid = 0;
    uint32_t state = TPVR_LAYER_IDLE;
    uint32_t graphics_api = TPVR_GRAPHICS_NONE;
    int32_t last_result = 0;
    uint64_t frames_shown = 0;
};

// Write layer fields (heartbeat last) if the view holds a header of any protocol version (layer fields
// keep their offsets), layer_version set to TPVR_VERSION
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
// out is reused: resized, image area overwritten, only the rest (border) cleared.
void convert_pixels(const uint8_t* pixels, uint32_t width, uint32_t height, uint32_t out_width, uint32_t out_height,
                    bool bgra, bool linear, std::vector<uint8_t>& out);

// Quads of a frame: rectangles of the uploaded image, each shown 1:1 at a canvas position.
// Not merged: uploaded image is the atlas, one quad per tile. Merged (fewer layer slots than tiles): tiles
// grouped, each group (bounding box of its tiles on the canvas, transparent between them) copied into a new
// image, one quad per group.
struct LayoutQuad {
    Rect image;
    uint32_t canvas_x = 0;
    uint32_t canvas_y = 0;
};

struct LayoutCopy {
    Rect atlas;  // copied from atlas
    uint32_t x = 0;  // to (x, y) of merged image
    uint32_t y = 0;
};

struct TileLayout {
    bool merged = false;
    uint32_t width = 0;  // uploaded image (0: nothing to show)
    uint32_t height = 0;
    uint32_t canvas_width = 0;
    uint32_t canvas_height = 0;
    std::vector<LayoutQuad> quads;
    std::vector<LayoutCopy> copies;  // merged only
    bool empty() const { return quads.empty(); }
};

bool operator==(const TileLayout& left, const TileLayout& right);
inline bool operator!=(const TileLayout& left, const TileLayout& right) { return !(left == right); }

// Layout of a drawable frame for at most max_quads quads, uploaded image at most max_width x max_height.
// Tiles merged (closest first: smallest added area) when more than max_quads. Empty when nothing fits.
TileLayout plan_layout(const FrameInfo& info, uint32_t max_quads, uint32_t max_width, uint32_t max_height);

// Merged image of layout (width x height RGBA, transparent around tiles) from atlas pixels (tightly packed).
// out reused. Copies outside atlas or image are skipped (never read or write out of bounds).
void compose_layout(const TileLayout& layout, const uint8_t* atlas, uint32_t atlas_width, uint32_t atlas_height,
                    std::vector<uint8_t>& out);

// Quad pose & size (meters) of a canvas rectangle: same place & scale as in the whole canvas image placed
// by info (width_meters, offsets of canvas center). x right, y up, z = -distance.
struct QuadPlacement {
    float x = 0.0f;
    float y = 0.0f;
    float z = 0.0f;
    float width = 0.0f;
    float height = 0.0f;
};

QuadPlacement quad_placement(const FrameInfo& info, uint32_t canvas_width, uint32_t canvas_height, const LayoutQuad& quad);

}  // namespace tpvr

#endif  // TINYPEDAL_SHARED_FRAME_H
