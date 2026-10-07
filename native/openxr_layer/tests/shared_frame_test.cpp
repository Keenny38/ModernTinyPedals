/*
 * Unit tests of the shared memory reader & pixel helpers (platform neutral, no OpenXR needed).
 * Writer below follows tinypedal/vr_shared.py (same layout, same seqlock order).
 */

#include <cstdio>
#include <cstring>
#include <limits>
#include <vector>

#include "shared_frame.h"

namespace {

int failures = 0;

void check(bool condition, const char* what, int line) {
    if (!condition) {
        std::printf("FAILED line %d: %s\n", line, what);
        ++failures;
    }
}

#define CHECK(condition) check((condition), #condition, __LINE__)

// 8-byte aligned shared memory
struct Memory {
    std::vector<uint64_t> words = std::vector<uint64_t>(TPVR_MAPPING_SIZE / 8u, 0);
    uint8_t* data() { return reinterpret_cast<uint8_t*>(words.data()); }
    TpvrHeader& header() { return *reinterpret_cast<TpvrHeader*>(data()); }
    size_t size() const { return words.size() * 8u; }
};

void init_header(Memory& memory) {
    TpvrHeader& header = memory.header();
    header.magic = TPVR_MAGIC;
    header.version = TPVR_VERSION;
    header.header_size = TPVR_HEADER_SIZE;
    header.mapping_size = TPVR_MAPPING_SIZE;
    header.data_offset = TPVR_DATA_OFFSET;
    header.data_capacity = TPVR_MAX_IMAGE_BYTES;
}

void write_frame(Memory& memory, uint32_t width, uint32_t height, uint8_t value, uint32_t serial, uint32_t flags,
                 uint64_t heartbeat) {
    TpvrHeader& header = memory.header();
    header.sequence += 1;  // odd: writing
    header.width = width;
    header.height = height;
    header.stride = width * 4u;
    header.pixel_format = TPVR_FORMAT_RGBA8_STRAIGHT;
    header.flags = flags;
    header.image_serial = serial;
    header.width_meters = 0.8f;
    header.distance_meters = 1.0f;
    header.vertical_offset_meters = -0.2f;
    header.horizontal_offset_meters = 0.0f;
    std::memset(memory.data() + TPVR_DATA_OFFSET, value, static_cast<size_t>(width) * height * 4u);
    header.sequence += 1;  // even: done
    header.app_heartbeat_ms = heartbeat;
}

void test_valid_frame() {
    Memory memory;
    init_header(memory);
    write_frame(memory, 3, 2, 7, 1, TPVR_FLAG_VISIBLE | TPVR_FLAG_ATTACH_TO_HEADSET, 1000);
    tpvr::FrameReader reader;
    CHECK(reader.read(memory.data(), memory.size(), 1500) == tpvr::ReadResult::Updated);
    CHECK(reader.drawable());
    CHECK(reader.info().width == 3 && reader.info().height == 2);
    CHECK(reader.info().attach_to_headset);
    CHECK(reader.pixels().size() == 3u * 2u * 4u && reader.pixels()[5] == 7);
    CHECK(reader.take_pixels_changed());
    CHECK(!reader.take_pixels_changed());
    CHECK(reader.read(memory.data(), memory.size(), 1600) == tpvr::ReadResult::Unchanged);
}

void test_placement_only_change_keeps_pixels() {
    Memory memory;
    init_header(memory);
    write_frame(memory, 2, 2, 9, 5, TPVR_FLAG_VISIBLE, 1000);
    tpvr::FrameReader reader;
    reader.read(memory.data(), memory.size(), 1000);
    reader.take_pixels_changed();
    memory.header().sequence += 2;  // placement changed, same image serial
    memory.header().distance_meters = 2.0f;
    CHECK(reader.read(memory.data(), memory.size(), 1000) == tpvr::ReadResult::Updated);
    CHECK(!reader.take_pixels_changed());
    CHECK(reader.info().distance_meters == 2.0f);
}

void test_writer_busy() {
    Memory memory;
    init_header(memory);
    write_frame(memory, 2, 2, 1, 1, TPVR_FLAG_VISIBLE, 1000);
    tpvr::FrameReader reader;
    reader.read(memory.data(), memory.size(), 1000);
    memory.header().sequence += 1;  // app writing
    CHECK(reader.read(memory.data(), memory.size(), 1000) == tpvr::ReadResult::Busy);
    CHECK(reader.drawable());  // last frame kept
}

void test_heartbeat() {
    Memory memory;
    init_header(memory);
    write_frame(memory, 2, 2, 1, 1, TPVR_FLAG_VISIBLE, 1000);
    tpvr::FrameReader reader;
    CHECK(reader.read(memory.data(), memory.size(), 1000 + TPVR_APP_TIMEOUT_MS + 1) == tpvr::ReadResult::AppGone);
    CHECK(!reader.drawable());
    CHECK(!tpvr::app_alive(memory.data(), memory.size(), 1000 + TPVR_APP_TIMEOUT_MS + 1));
    CHECK(tpvr::app_alive(memory.data(), memory.size(), 999));  // tick read just before app wrote
    memory.header().app_heartbeat_ms = 0;  // app closed
    CHECK(reader.read(memory.data(), memory.size(), 1000) == tpvr::ReadResult::AppGone);
    memory.header().app_heartbeat_ms = 5000;  // app back
    CHECK(reader.read(memory.data(), memory.size(), 5000) == tpvr::ReadResult::Updated);
    CHECK(reader.drawable());
}

void test_hidden() {
    Memory memory;
    init_header(memory);
    write_frame(memory, 2, 2, 1, 1, 0, 1000);
    tpvr::FrameReader reader;
    CHECK(reader.read(memory.data(), memory.size(), 1000) == tpvr::ReadResult::Updated);
    CHECK(!reader.drawable());
}

void test_invalid_headers() {
    tpvr::FrameReader reader;
    {
        Memory memory;  // not initialized
        CHECK(reader.read(memory.data(), memory.size(), 1000) == tpvr::ReadResult::Invalid);
    }
    {
        Memory memory;
        init_header(memory);
        memory.header().version = 99;
        CHECK(reader.read(memory.data(), memory.size(), 1000) == tpvr::ReadResult::Invalid);
    }
    {
        Memory memory;
        init_header(memory);
        write_frame(memory, 2, 2, 1, 1, TPVR_FLAG_VISIBLE, 1000);
        CHECK(reader.read(memory.data(), 100, 1000) == tpvr::ReadResult::Invalid);  // view too small
        CHECK(reader.read(nullptr, memory.size(), 1000) == tpvr::ReadResult::Invalid);
    }
    struct Case {
        const char* name;
        void (*change)(TpvrHeader&);
    };
    const Case cases[] = {
        {"width 0", [](TpvrHeader& header) { header.width = 0; }},
        {"too wide", [](TpvrHeader& header) { header.width = TPVR_MAX_DIMENSION + 1u; }},
        {"stride", [](TpvrHeader& header) { header.stride = 4; }},
        {"format", [](TpvrHeader& header) { header.pixel_format = 7; }},
        {"capacity", [](TpvrHeader& header) { header.data_capacity = TPVR_MAPPING_SIZE; }},
        {"offset", [](TpvrHeader& header) { header.data_offset = 16; }},
        {"offset past end", [](TpvrHeader& header) { header.data_offset = TPVR_MAPPING_SIZE + 4096u; }},
        {"too big for capacity",
         [](TpvrHeader& header) {
             header.width = 2048;
             header.height = 2048;
             header.stride = 2048 * 4;
         }},
        {"nan", [](TpvrHeader& header) { header.width_meters = std::numeric_limits<float>::quiet_NaN(); }},
        {"width meters", [](TpvrHeader& header) { header.width_meters = 0.0f; }},
    };
    for (const Case& item : cases) {
        Memory memory;
        init_header(memory);
        write_frame(memory, 4, 4, 1, 1, TPVR_FLAG_VISIBLE, 1000);
        item.change(memory.header());
        tpvr::FrameReader fresh;
        const bool invalid = fresh.read(memory.data(), memory.size(), 1000) == tpvr::ReadResult::Invalid;
        if (!invalid) {
            std::printf("case not rejected: %s\n", item.name);
        }
        CHECK(invalid && !fresh.drawable());
    }
}

void test_stride_padding() {
    Memory memory;
    init_header(memory);
    write_frame(memory, 2, 2, 0, 1, TPVR_FLAG_VISIBLE, 1000);
    TpvrHeader& header = memory.header();
    header.stride = 16;  // 2 pixels + 8 bytes padding
    uint8_t* data = memory.data() + TPVR_DATA_OFFSET;
    for (int index = 0; index < 32; ++index) {
        data[index] = static_cast<uint8_t>(index);
    }
    header.sequence += 2;
    header.image_serial = 2;
    tpvr::FrameReader reader;
    CHECK(reader.read(memory.data(), memory.size(), 1000) == tpvr::ReadResult::Updated);
    const std::vector<uint8_t>& pixels = reader.pixels();
    CHECK(pixels.size() == 16 && pixels[0] == 0 && pixels[7] == 7 && pixels[8] == 16 && pixels[15] == 23);
}

void test_layer_status() {
    Memory memory;
    init_header(memory);
    tpvr::LayerStatus status;
    status.pid = 1234;
    status.state = TPVR_LAYER_ACTIVE;
    status.graphics_api = TPVR_GRAPHICS_D3D11;
    status.frames_shown = 42;
    tpvr::write_layer_status(memory.data(), memory.size(), status, 777);
    const TpvrHeader& header = memory.header();
    CHECK(header.layer_pid == 1234 && header.layer_state == TPVR_LAYER_ACTIVE);
    CHECK(header.layer_graphics_api == TPVR_GRAPHICS_D3D11 && header.layer_frames_shown == 42);
    CHECK(header.layer_heartbeat_ms == 777 && header.layer_version == TPVR_VERSION);
    Memory empty;  // no header: nothing written
    tpvr::write_layer_status(empty.data(), empty.size(), status, 777);
    CHECK(empty.header().layer_heartbeat_ms == 0);
}

void test_formats_and_extent() {
    const tpvr::FormatCandidate candidates[] = {{29, false, true}, {91, true, true}, {28, false, false}};
    const int64_t runtime[] = {87, 91, 28};
    const tpvr::FormatCandidate* chosen = tpvr::choose_format(runtime, 3, candidates, 3);
    CHECK(chosen != nullptr && chosen->format == 91 && chosen->bgra);
    const int64_t none[] = {10, 11};
    CHECK(tpvr::choose_format(none, 2, candidates, 3) == nullptr);
    CHECK(tpvr::swapchain_extent(100, 0, 4096) == 128);
    CHECK(tpvr::swapchain_extent(128, 0, 4096) == 192);  // border pixel
    CHECK(tpvr::swapchain_extent(100, 256, 4096) == 256);  // never shrinks
    CHECK(tpvr::swapchain_extent(4096, 0, 4096) == 4096);  // no room for border
    CHECK(tpvr::swapchain_extent(5000, 0, 4096) == 0);
    CHECK(tpvr::swapchain_extent(0, 0, 4096) == 0);
}

void test_convert_pixels() {
    const uint8_t pixels[] = {255, 128, 0, 200, 10, 20, 30, 40};  // 2 x 1 RGBA
    std::vector<uint8_t> out;
    tpvr::convert_pixels(pixels, 2, 1, 3, 2, false, false, out);
    CHECK(out.size() == 3u * 2u * 4u);
    CHECK(std::memcmp(out.data(), pixels, 8) == 0);
    CHECK(out[8] == 0 && out[11] == 0 && out[12] == 0 && out[23] == 0);  // transparent border
    tpvr::convert_pixels(pixels, 2, 1, 2, 1, true, false, out);
    CHECK(out[0] == 0 && out[1] == 128 && out[2] == 255 && out[3] == 200);  // BGRA
    tpvr::convert_pixels(pixels, 2, 1, 2, 1, false, true, out);
    CHECK(out[0] == 255 && out[1] == 55 && out[2] == 0 && out[3] == 200);  // sRGB 128 -> linear 55, alpha kept
    // Reused buffer: border cleared even where a bigger image left pixels
    std::vector<uint8_t> reused(5u * 4u * 4u, 0xEE);
    tpvr::convert_pixels(pixels, 2, 1, 5, 4, false, false, reused);
    CHECK(reused.size() == 5u * 4u * 4u);
    CHECK(std::memcmp(reused.data(), pixels, 8) == 0);
    bool border_clear = true;
    for (size_t index = 8; index < reused.size(); ++index) {
        border_clear = border_clear && reused[index] == 0;
    }
    CHECK(border_clear);
    reused.assign(3u * 2u * 4u, 0xEE);
    tpvr::convert_pixels(pixels, 2, 1, 3, 2, true, true, reused);
    CHECK(reused[0] == 0 && reused[1] == 55 && reused[2] == 255 && reused[3] == 200);  // BGRA & linear
    CHECK(reused[8] == 0 && reused[11] == 0 && reused[12] == 0 && reused[23] == 0);  // right & bottom border
    tpvr::convert_pixels(pixels, 4, 1, 3, 2, false, false, reused);  // image larger than buffer
    CHECK(reused.size() == 3u * 2u * 4u && reused[0] == 0 && reused[23] == 0);
}

}  // namespace

int main() {
    test_valid_frame();
    test_placement_only_change_keeps_pixels();
    test_writer_busy();
    test_heartbeat();
    test_hidden();
    test_invalid_headers();
    test_stride_padding();
    test_layer_status();
    test_formats_and_extent();
    test_convert_pixels();
    if (failures != 0) {
        std::printf("%d check(s) failed\n", failures);
        return 1;
    }
    std::printf("shared_frame_test: all checks passed\n");
    return 0;
}
