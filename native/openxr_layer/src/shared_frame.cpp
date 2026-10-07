/*
 * Modern Tiny Pedals - OpenXR overlay layer
 * Copyright (C) 2022-2026 TinyPedal developers, see contributors.md file
 * SPDX-License-Identifier: GPL-3.0-or-later
 */

#include "shared_frame.h"

#include <algorithm>
#include <atomic>
#include <cmath>
#include <cstring>

namespace tpvr {
namespace {

// Shared memory written by another process: volatile loads (not cached or merged by the compiler),
// fences around the copy (seqlock reader). x86-64 keeps stores of the writer in order.
uint32_t load_u32(const uint8_t* base, size_t offset) {
    return *reinterpret_cast<const volatile uint32_t*>(base + offset);
}

uint64_t load_u64(const uint8_t* base, size_t offset) {
    return *reinterpret_cast<const volatile uint64_t*>(base + offset);
}

void store_u32(uint8_t* base, size_t offset, uint32_t value) {
    *reinterpret_cast<volatile uint32_t*>(base + offset) = value;
}

void store_u64(uint8_t* base, size_t offset, uint64_t value) {
    *reinterpret_cast<volatile uint64_t*>(base + offset) = value;
}

// Header of any protocol version: magic, header_size, heartbeat & layer fields at known offsets
bool header_compatible(const uint8_t* base, size_t size) {
    if (base == nullptr || size < TPVR_DATA_OFFSET) {
        return false;
    }
    if ((reinterpret_cast<uintptr_t>(base) & 7u) != 0) {
        return false;  // mapped views are page aligned, never expected
    }
    return load_u32(base, offsetof(TpvrHeader, magic)) == TPVR_MAGIC &&
           load_u32(base, offsetof(TpvrHeader, header_size)) == TPVR_HEADER_SIZE;
}

bool heartbeat_recent(uint64_t heartbeat, uint64_t now_ms) {
    if (heartbeat == 0) {
        return false;  // never written, or app closed cleanly
    }
    if (heartbeat > now_ms) {
        return heartbeat - now_ms <= TPVR_APP_TIMEOUT_MS;  // tick read just before app wrote
    }
    return now_ms - heartbeat <= TPVR_APP_TIMEOUT_MS;
}

bool finite_in(float value, float low, float high) {
    return std::isfinite(value) && value >= low && value <= high;
}

// Canvas & tile table of a visible frame copied to info (atlas size from header, checked by caller)
bool tiles_valid(const TpvrHeader& header, const TpvrTile* tiles, FrameInfo& info) {
    if (header.canvas_width < 1 || header.canvas_width > TPVR_MAX_CANVAS || header.canvas_height < 1 ||
        header.canvas_height > TPVR_MAX_CANVAS || header.tile_count < 1 || header.tile_count > TPVR_MAX_TILES) {
        return false;
    }
    info.canvas_width = header.canvas_width;
    info.canvas_height = header.canvas_height;
    info.tile_count = header.tile_count;
    for (uint32_t index = 0; index < header.tile_count; ++index) {
        const TpvrTile& tile = tiles[index];
        // 64-bit sums: no wrap around
        const uint64_t right = static_cast<uint64_t>(tile.atlas_x) + tile.width;
        const uint64_t bottom = static_cast<uint64_t>(tile.atlas_y) + tile.height;
        const uint64_t canvas_right = static_cast<uint64_t>(tile.canvas_x) + tile.width;
        const uint64_t canvas_bottom = static_cast<uint64_t>(tile.canvas_y) + tile.height;
        if (tile.width < 1 || tile.height < 1 || right > header.width || bottom > header.height ||
            canvas_right > header.canvas_width || canvas_bottom > header.canvas_height) {
            return false;
        }
        Tile& out = info.tiles[index];
        out.atlas = Rect{tile.atlas_x, tile.atlas_y, tile.width, tile.height};
        out.canvas_x = tile.canvas_x;
        out.canvas_y = tile.canvas_y;
    }
    return true;
}

}  // namespace

bool app_alive(const uint8_t* base, size_t size, uint64_t now_ms) {
    return header_compatible(base, size) && heartbeat_recent(load_u64(base, offsetof(TpvrHeader, app_heartbeat_ms)), now_ms);
}

void FrameReader::reset() {
    has_frame_ = false;
    alive_ = false;
    pixels_changed_ = false;
    last_sequence_ = 0;
    info_ = FrameInfo{};
    pixels_.clear();
}

ReadResult FrameReader::read(const uint8_t* base, size_t size, uint64_t now_ms) {
    if (!header_compatible(base, size)) {
        alive_ = false;
        has_frame_ = false;
        return ReadResult::Invalid;
    }
    if (!heartbeat_recent(load_u64(base, offsetof(TpvrHeader, app_heartbeat_ms)), now_ms)) {
        alive_ = false;
        return ReadResult::AppGone;
    }
    if (load_u32(base, offsetof(TpvrHeader, version)) != TPVR_VERSION) {
        // Other app version: layout unknown, nothing read (frame of the previous app dropped)
        alive_ = true;
        has_frame_ = false;
        pixels_.clear();
        info_ = FrameInfo{};
        return ReadResult::VersionMismatch;
    }
    alive_ = true;
    const uint64_t sequence = load_u64(base, offsetof(TpvrHeader, sequence));
    if ((sequence & 1u) != 0) {
        return ReadResult::Busy;
    }
    if (has_frame_ && sequence == last_sequence_) {
        return ReadResult::Unchanged;
    }
    std::atomic_thread_fence(std::memory_order_acquire);

    TpvrHeader header;
    std::memcpy(&header, base, sizeof(header));
    TpvrTile tiles[TPVR_MAX_TILES];
    std::memcpy(tiles, base + TPVR_TILE_OFFSET, sizeof(tiles));  // inside view: size >= TPVR_DATA_OFFSET

    // Validate copy (never the shared memory again: app may change it meanwhile)
    const bool visible = (header.flags & TPVR_FLAG_VISIBLE) != 0;
    FrameInfo info;
    info.visible = visible;
    info.attach_to_headset = (header.flags & TPVR_FLAG_ATTACH_TO_HEADSET) != 0;
    info.width = header.width;
    info.height = header.height;
    info.pixel_format = header.pixel_format;
    info.image_serial = header.image_serial;
    info.width_meters = header.width_meters;
    info.distance_meters = header.distance_meters;
    info.vertical_offset_meters = header.vertical_offset_meters;
    info.horizontal_offset_meters = header.horizontal_offset_meters;

    bool valid = finite_in(info.width_meters, 0.01f, 100.0f) && finite_in(info.distance_meters, -100.0f, 100.0f) &&
                 finite_in(info.vertical_offset_meters, -100.0f, 100.0f) &&
                 finite_in(info.horizontal_offset_meters, -100.0f, 100.0f);
    bool copy_pixels = false;
    if (valid && visible) {
        valid = tiles_valid(header, tiles, info);
    }
    if (valid && visible) {
        const uint64_t row_bytes = static_cast<uint64_t>(header.width) * 4u;
        const uint64_t data_offset = header.data_offset;
        const uint64_t data_capacity = header.data_capacity;
        valid = header.width >= 1 && header.width <= TPVR_MAX_DIMENSION && header.height >= 1 &&
                header.height <= TPVR_MAX_DIMENSION &&
                (header.pixel_format == TPVR_FORMAT_RGBA8_STRAIGHT ||
                 header.pixel_format == TPVR_FORMAT_RGBA8_PREMULTIPLIED) &&
                header.stride >= row_bytes && header.stride <= TPVR_MAX_DIMENSION * 4u && data_offset >= TPVR_HEADER_SIZE &&
                data_offset <= size && data_capacity <= size - data_offset &&
                static_cast<uint64_t>(header.stride) * (header.height - 1u) + row_bytes <= data_capacity;
        copy_pixels = valid && (!has_frame_ || pixels_.empty() || header.image_serial != info_.image_serial ||
                                header.width != info_.width || header.height != info_.height);
        if (valid && copy_pixels) {
            const size_t packed_row = static_cast<size_t>(row_bytes);
            scratch_.resize(packed_row * header.height);
            const uint8_t* source = base + data_offset;
            for (uint32_t row = 0; row < header.height; ++row) {
                std::memcpy(scratch_.data() + packed_row * row, source + static_cast<size_t>(header.stride) * row,
                            packed_row);
            }
        }
    }

    std::atomic_thread_fence(std::memory_order_acquire);
    if (load_u64(base, offsetof(TpvrHeader, sequence)) != sequence) {
        return ReadResult::Busy;  // app wrote during copy: copy dropped
    }
    last_sequence_ = sequence;
    if (!valid) {
        has_frame_ = false;
        pixels_.clear();
        info_ = FrameInfo{};
        return ReadResult::Invalid;
    }
    if (copy_pixels) {
        pixels_.swap(scratch_);
        pixels_changed_ = true;
    }
    if (!visible) {
        // Pixels kept: shown again as is when made visible with same serial
        info.width = info_.width;
        info.height = info_.height;
        info.pixel_format = info_.pixel_format;
        info.image_serial = info_.image_serial;
        info.canvas_width = info_.canvas_width;
        info.canvas_height = info_.canvas_height;
        info.tile_count = info_.tile_count;
        info.tiles = info_.tiles;
    }
    info_ = info;
    has_frame_ = true;
    return ReadResult::Updated;
}

void write_layer_status(uint8_t* base, size_t size, const LayerStatus& status, uint64_t now_ms) {
    if (!header_compatible(base, size)) {
        return;
    }
    store_u32(base, offsetof(TpvrHeader, layer_pid), status.pid);
    store_u32(base, offsetof(TpvrHeader, layer_state), status.state);
    store_u32(base, offsetof(TpvrHeader, layer_graphics_api), status.graphics_api);
    store_u32(base, offsetof(TpvrHeader, layer_last_result), static_cast<uint32_t>(status.last_result));
    store_u64(base, offsetof(TpvrHeader, layer_frames_shown), status.frames_shown);
    store_u32(base, offsetof(TpvrHeader, layer_version), TPVR_VERSION);
    std::atomic_thread_fence(std::memory_order_release);
    store_u64(base, offsetof(TpvrHeader, layer_heartbeat_ms), now_ms);
}

const FormatCandidate* choose_format(const int64_t* runtime_formats, size_t runtime_count,
                                     const FormatCandidate* candidates, size_t candidate_count) {
    if (runtime_formats == nullptr || candidates == nullptr) {
        return nullptr;
    }
    for (size_t candidate = 0; candidate < candidate_count; ++candidate) {
        for (size_t index = 0; index < runtime_count; ++index) {
            if (runtime_formats[index] == candidates[candidate].format) {
                return &candidates[candidate];
            }
        }
    }
    return nullptr;
}

uint32_t swapchain_extent(uint32_t image, uint32_t current, uint32_t max) {
    if (image == 0 || image > max) {
        return 0;
    }
    const uint64_t wanted = static_cast<uint64_t>(image) + 1u;
    uint64_t extent = (wanted + 63u) / 64u * 64u;
    if (extent < current) {
        extent = current;
    }
    if (extent > max) {
        extent = max;  // no room for border: image fills swapchain width or height
    }
    return static_cast<uint32_t>(extent);
}

namespace {

struct LinearTable {
    uint8_t values[256];
    LinearTable() {
        for (int index = 0; index < 256; ++index) {
            const double srgb = index / 255.0;
            const double linear = srgb <= 0.04045 ? srgb / 12.92 : std::pow((srgb + 0.055) / 1.055, 2.4);
            values[index] = static_cast<uint8_t>(std::lround(linear * 255.0));
        }
    }
};

}  // namespace

void convert_pixels(const uint8_t* pixels, uint32_t width, uint32_t height, uint32_t out_width, uint32_t out_height,
                    bool bgra, bool linear, std::vector<uint8_t>& out) {
    static const LinearTable table;
    // Buffer reused (no reallocation nor full zero fill on the game's render thread): image pixels
    // overwritten, only the rest (transparent border) cleared
    out.resize(static_cast<size_t>(out_width) * out_height * 4u);
    const size_t out_row = static_cast<size_t>(out_width) * 4u;
    if (pixels == nullptr || width > out_width || height > out_height) {
        std::fill(out.begin(), out.end(), static_cast<uint8_t>(0));
        return;
    }
    const size_t in_row = static_cast<size_t>(width) * 4u;
    for (uint32_t row = 0; row < height; ++row) {
        const uint8_t* source = pixels + in_row * row;
        uint8_t* target = out.data() + out_row * row;
        if (!bgra && !linear) {
            std::memcpy(target, source, in_row);
        } else {
            for (uint32_t column = 0; column < width; ++column, source += 4, target += 4) {
                uint8_t red = source[0];
                uint8_t green = source[1];
                uint8_t blue = source[2];
                if (linear) {
                    red = table.values[red];
                    green = table.values[green];
                    blue = table.values[blue];
                }
                target[0] = bgra ? blue : red;
                target[1] = green;
                target[2] = bgra ? red : blue;
                target[3] = source[3];
            }
        }
        if (out_row > in_row) {
            std::memset(out.data() + out_row * row + in_row, 0, out_row - in_row);  // right border
        }
    }
    if (out_height > height) {
        std::memset(out.data() + out_row * height, 0, out_row * (out_height - height));  // bottom border
    }
}

bool operator==(const Rect& left, const Rect& right) {
    return left.x == right.x && left.y == right.y && left.width == right.width && left.height == right.height;
}

bool operator==(const TileLayout& left, const TileLayout& right) {
    if (left.merged != right.merged || left.width != right.width || left.height != right.height ||
        left.canvas_width != right.canvas_width || left.canvas_height != right.canvas_height ||
        left.quads.size() != right.quads.size() || left.copies.size() != right.copies.size()) {
        return false;
    }
    for (size_t index = 0; index < left.quads.size(); ++index) {
        const LayoutQuad& a = left.quads[index];
        const LayoutQuad& b = right.quads[index];
        if (!(a.image == b.image) || a.canvas_x != b.canvas_x || a.canvas_y != b.canvas_y) {
            return false;
        }
    }
    for (size_t index = 0; index < left.copies.size(); ++index) {
        const LayoutCopy& a = left.copies[index];
        const LayoutCopy& b = right.copies[index];
        if (!(a.atlas == b.atlas) || a.x != b.x || a.y != b.y) {
            return false;
        }
    }
    return true;
}

namespace {

struct Group {
    uint32_t left = 0;  // canvas bounding box (right & bottom exclusive)
    uint32_t top = 0;
    uint32_t right = 0;
    uint32_t bottom = 0;
    std::vector<uint32_t> tiles;
    uint64_t area() const { return static_cast<uint64_t>(right - left) * (bottom - top); }
};

uint64_t union_area(const Group& a, const Group& b) {
    const uint64_t width = std::max(a.right, b.right) - std::min(a.left, b.left);
    const uint64_t height = std::max(a.bottom, b.bottom) - std::min(a.top, b.top);
    return width * height;
}

}  // namespace

TileLayout plan_layout(const FrameInfo& info, uint32_t max_quads, uint32_t max_width, uint32_t max_height) {
    TileLayout layout;
    const uint32_t count = std::min<uint32_t>(info.tile_count, TPVR_MAX_TILES);
    if (count == 0 || max_quads == 0) {
        return layout;
    }
    layout.canvas_width = info.canvas_width;
    layout.canvas_height = info.canvas_height;
    if (count <= max_quads) {
        if (info.width > max_width || info.height > max_height) {
            return TileLayout{};  // atlas bigger than swapchain allows
        }
        layout.width = info.width;
        layout.height = info.height;
        for (uint32_t index = 0; index < count; ++index) {
            const Tile& tile = info.tiles[index];
            layout.quads.push_back(LayoutQuad{tile.atlas, tile.canvas_x, tile.canvas_y});
        }
        return layout;
    }
    // Too many tiles: closest groups merged first (smallest bounding box growth)
    std::vector<Group> groups;
    groups.reserve(count);
    for (uint32_t index = 0; index < count; ++index) {
        const Tile& tile = info.tiles[index];
        Group group;
        group.left = tile.canvas_x;
        group.top = tile.canvas_y;
        group.right = tile.canvas_x + tile.atlas.width;  // validated: within canvas (<= TPVR_MAX_CANVAS)
        group.bottom = tile.canvas_y + tile.atlas.height;
        group.tiles.push_back(index);
        groups.push_back(group);
    }
    while (groups.size() > max_quads) {
        size_t best_first = 0;
        size_t best_second = 1;
        uint64_t best_growth = UINT64_MAX;
        for (size_t first = 0; first < groups.size(); ++first) {
            for (size_t second = first + 1; second < groups.size(); ++second) {
                const uint64_t merged = union_area(groups[first], groups[second]);
                const uint64_t parts = groups[first].area() + groups[second].area();
                const uint64_t growth = merged > parts ? merged - parts : 0;
                if (growth < best_growth) {
                    best_growth = growth;
                    best_first = first;
                    best_second = second;
                }
            }
        }
        Group& target = groups[best_first];
        const Group& source = groups[best_second];
        target.left = std::min(target.left, source.left);
        target.top = std::min(target.top, source.top);
        target.right = std::max(target.right, source.right);
        target.bottom = std::max(target.bottom, source.bottom);
        target.tiles.insert(target.tiles.end(), source.tiles.begin(), source.tiles.end());
        groups.erase(groups.begin() + static_cast<std::ptrdiff_t>(best_second));
    }
    // Groups packed in rows (tallest first), 1 pixel apart (no bilinear bleeding between quads)
    std::vector<size_t> order(groups.size());
    for (size_t index = 0; index < order.size(); ++index) {
        order[index] = index;
    }
    std::stable_sort(order.begin(), order.end(), [&](size_t a, size_t b) {
        return groups[a].bottom - groups[a].top > groups[b].bottom - groups[b].top;
    });
    std::vector<Rect> places(groups.size());
    uint64_t x = 0;
    uint64_t y = 0;
    uint64_t row_height = 0;
    uint64_t width = 0;
    for (size_t index : order) {
        const Group& group = groups[index];
        const uint32_t group_width = group.right - group.left;
        const uint32_t group_height = group.bottom - group.top;
        if (group_width > max_width) {
            return TileLayout{};
        }
        if (x != 0 && x + group_width > max_width) {
            y += row_height + 1u;
            x = 0;
            row_height = 0;
        }
        places[index] = Rect{static_cast<uint32_t>(x), static_cast<uint32_t>(y), group_width, group_height};
        width = std::max<uint64_t>(width, x + group_width);
        row_height = std::max<uint64_t>(row_height, group_height);
        x += group_width + 1u;
    }
    const uint64_t height = y + row_height;
    if (height > max_height) {
        return TileLayout{};
    }
    layout.merged = true;
    layout.width = static_cast<uint32_t>(width);
    layout.height = static_cast<uint32_t>(height);
    for (size_t index = 0; index < groups.size(); ++index) {
        const Group& group = groups[index];
        const Rect& place = places[index];
        layout.quads.push_back(LayoutQuad{place, group.left, group.top});
        for (uint32_t tile_index : group.tiles) {
            const Tile& tile = info.tiles[tile_index];
            layout.copies.push_back(
                LayoutCopy{tile.atlas, place.x + (tile.canvas_x - group.left), place.y + (tile.canvas_y - group.top)});
        }
    }
    return layout;
}

void compose_layout(const TileLayout& layout, const uint8_t* atlas, uint32_t atlas_width, uint32_t atlas_height,
                    std::vector<uint8_t>& out) {
    out.assign(static_cast<size_t>(layout.width) * layout.height * 4u, 0);
    if (atlas == nullptr) {
        return;
    }
    for (const LayoutCopy& copy : layout.copies) {
        const Rect& source = copy.atlas;
        if (static_cast<uint64_t>(source.x) + source.width > atlas_width ||
            static_cast<uint64_t>(source.y) + source.height > atlas_height ||
            static_cast<uint64_t>(copy.x) + source.width > layout.width ||
            static_cast<uint64_t>(copy.y) + source.height > layout.height) {
            continue;
        }
        const size_t row_bytes = static_cast<size_t>(source.width) * 4u;
        for (uint32_t row = 0; row < source.height; ++row) {
            const uint8_t* from = atlas + ((static_cast<size_t>(source.y) + row) * atlas_width + source.x) * 4u;
            uint8_t* to = out.data() + ((static_cast<size_t>(copy.y) + row) * layout.width + copy.x) * 4u;
            std::memcpy(to, from, row_bytes);
        }
    }
}

QuadPlacement quad_placement(const FrameInfo& info, uint32_t canvas_width, uint32_t canvas_height, const LayoutQuad& quad) {
    QuadPlacement placement;
    if (canvas_width == 0 || canvas_height == 0) {
        return placement;
    }
    const double scale = static_cast<double>(info.width_meters) / canvas_width;  // meters per pixel
    const double center_x = quad.canvas_x + quad.image.width / 2.0 - canvas_width / 2.0;
    const double center_y = quad.canvas_y + quad.image.height / 2.0 - canvas_height / 2.0;
    placement.x = static_cast<float>(info.horizontal_offset_meters + center_x * scale);
    placement.y = static_cast<float>(info.vertical_offset_meters - center_y * scale);  // canvas y down, VR y up
    placement.z = -info.distance_meters;
    placement.width = static_cast<float>(quad.image.width * scale);
    placement.height = static_cast<float>(quad.image.height * scale);
    return placement;
}

}  // namespace tpvr
