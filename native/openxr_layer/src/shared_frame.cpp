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

bool header_valid(const uint8_t* base, size_t size) {
    if (base == nullptr || size < TPVR_DATA_OFFSET) {
        return false;
    }
    if ((reinterpret_cast<uintptr_t>(base) & 7u) != 0) {
        return false;  // mapped views are page aligned, never expected
    }
    return load_u32(base, offsetof(TpvrHeader, magic)) == TPVR_MAGIC &&
           load_u32(base, offsetof(TpvrHeader, version)) == TPVR_VERSION &&
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

}  // namespace

bool app_alive(const uint8_t* base, size_t size, uint64_t now_ms) {
    return header_valid(base, size) && heartbeat_recent(load_u64(base, offsetof(TpvrHeader, app_heartbeat_ms)), now_ms);
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
    if (!header_valid(base, size)) {
        alive_ = false;
        has_frame_ = false;
        return ReadResult::Invalid;
    }
    if (!heartbeat_recent(load_u64(base, offsetof(TpvrHeader, app_heartbeat_ms)), now_ms)) {
        alive_ = false;
        return ReadResult::AppGone;
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
    }
    info_ = info;
    has_frame_ = true;
    return ReadResult::Updated;
}

void write_layer_status(uint8_t* base, size_t size, const LayerStatus& status, uint64_t now_ms) {
    if (!header_valid(base, size)) {
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

}  // namespace tpvr
