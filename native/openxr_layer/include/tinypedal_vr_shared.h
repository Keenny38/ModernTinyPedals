/*
 * Modern Tiny Pedals - OpenXR overlay layer
 * Copyright (C) 2022-2026 TinyPedal developers, see contributors.md file
 * SPDX-License-Identifier: GPL-3.0-or-later
 *
 * Shared memory protocol between the app (writer, tinypedal/vr_shared.py) and the OpenXR API layer
 * loaded in the game (reader). Keep both files in sync: tests check the Python layout against these
 * offsets (tests/test_vr_shared.py) and the C++ reader (native/openxr_layer/tests).
 *
 * Named file mapping "TinyPedalVROverlay" (session namespace, same as "Local\TinyPedalVROverlay"),
 * TPVR_MAPPING_SIZE bytes: header (256 bytes), tile table (TPVR_TILE_OFFSET), atlas pixels (TPVR_DATA_OFFSET).
 * All fields little endian, naturally aligned.
 *
 * Version 2 (tiles): overlay widgets are drawn on a virtual canvas (canvas_width x canvas_height pixels,
 * the desktop layout of all visible widgets), placed in VR by width_meters & offsets (canvas center) as
 * one image would be. Only its visible parts are sent: tile_count tiles (TpvrTile), each a rectangle of the
 * atlas image (width x height pixels) shown 1:1 at (canvas_x, canvas_y) of the canvas. Tiles never overlap
 * on the canvas and are 1 pixel apart in the atlas (bilinear filtering never mixes two tiles). The layer
 * submits one quad layer per tile from one swapchain (imageRect), or merges tiles when the runtime has
 * fewer layer slots left than tiles.
 *
 * Compatibility: magic, version, header_size, mapping_size, sequence & app_heartbeat_ms (0 .. 31) and the
 * layer fields (128 .. 167) keep their offsets in every version. A reader of another version draws nothing
 * (pure pass-through) and reports TPVR_LAYER_VERSION_MISMATCH with its own layer_version, so the app can
 * tell the user to restart the game (a game keeps the layer DLL it started with). Version 1 had no tiles:
 * the image itself was placed by width_meters & offsets.
 *
 * Writer (app), seqlock: sequence made odd, fields, tiles & pixels written, sequence made even (+2 in all).
 * Reader (layer): reads sequence (even), copies header, tiles & pixels, reads sequence again: copy kept only
 * when both reads match, so an image is never torn. app_heartbeat_ms is written every app tick outside
 * the seqlock (the layer only draws while it is recent), layer_* fields are written by the layer only.
 */

#ifndef TINYPEDAL_VR_SHARED_H
#define TINYPEDAL_VR_SHARED_H

#include <stddef.h>
#include <stdint.h>

#define TPVR_MAPPING_NAME "TinyPedalVROverlay"
#define TPVR_MAGIC 0x52565054u /* "TPVR" read as little endian uint32 */
#define TPVR_VERSION 2u
#define TPVR_HEADER_SIZE 256u /* bytes of TpvrHeader */
#define TPVR_DATA_OFFSET 4096u /* atlas pixels offset (page aligned) */
#define TPVR_TILE_OFFSET 256u /* tile table (TpvrTile[TPVR_MAX_TILES]), right after header */
#define TPVR_TILE_SIZE 32u /* bytes of TpvrTile */
#define TPVR_MAX_TILES 16u /* tiles of one frame (quad layers submitted at most) */
#define TPVR_MAX_CANVAS 16384u /* canvas width or height (pixels) */
#define TPVR_MAX_IMAGE_BYTES (4u * 1024u * 1024u) /* 1024 x 1024 RGBA, app scales images down above */
#define TPVR_MAPPING_SIZE (TPVR_DATA_OFFSET + TPVR_MAX_IMAGE_BYTES)
#define TPVR_MAX_DIMENSION 4096u /* width or height */
#define TPVR_APP_TIMEOUT_MS 2000u /* app heartbeat older than this: app closed or frozen, nothing drawn */
#define TPVR_LAYER_TIMEOUT_MS 1000u /* layer heartbeat older than this: no OpenXR game showing the overlay */

/* pixel_format */
#define TPVR_FORMAT_RGBA8_STRAIGHT 1u /* R, G, B, A bytes, sRGB encoded colors, not premultiplied (Qt RGBA8888) */
#define TPVR_FORMAT_RGBA8_PREMULTIPLIED 2u /* same, colors premultiplied by alpha */

/* flags */
#define TPVR_FLAG_VISIBLE 0x1u /* image shown (cleared while every overlay is hidden, or app closing) */
#define TPVR_FLAG_ATTACH_TO_HEADSET 0x2u /* placement relative to headset (VIEW space), else seated (LOCAL) */

/* layer_state */
#define TPVR_LAYER_IDLE 0u /* no session */
#define TPVR_LAYER_ACTIVE 1u /* session with supported graphics API: overlay drawn by layer */
#define TPVR_LAYER_UNSUPPORTED 2u /* session with unsupported graphics API (OpenGL...): nothing drawn */
#define TPVR_LAYER_FAILED 3u /* overlay stopped after an error (see layer_last_result), game unaffected */
#define TPVR_LAYER_VERSION_MISMATCH 4u /* app writes another protocol version than layer_version: nothing drawn */

/* layer_graphics_api */
#define TPVR_GRAPHICS_NONE 0u
#define TPVR_GRAPHICS_D3D11 1u
#define TPVR_GRAPHICS_D3D12 2u
#define TPVR_GRAPHICS_VULKAN 3u
#define TPVR_GRAPHICS_OPENGL 4u
#define TPVR_GRAPHICS_OTHER 5u

typedef struct TpvrHeader {
    /* written once by app */
    uint32_t magic;                    /* 0 */
    uint32_t version;                  /* 4 */
    uint32_t header_size;              /* 8: TPVR_HEADER_SIZE */
    uint32_t mapping_size;             /* 12: TPVR_MAPPING_SIZE */
    /* seqlock */
    uint64_t sequence;                 /* 16: odd while app writes */
    /* written every app tick, outside seqlock */
    uint64_t app_heartbeat_ms;         /* 24: GetTickCount64() of app */
    /* written by app inside seqlock */
    uint32_t width;                    /* 32: atlas */
    uint32_t height;                   /* 36: atlas */
    uint32_t stride;                   /* 40: bytes per row */
    uint32_t pixel_format;             /* 44: TPVR_FORMAT_* */
    uint32_t flags;                    /* 48: TPVR_FLAG_* */
    uint32_t image_serial;             /* 52: changed when pixels or tiles change */
    float width_meters;                /* 56: canvas width */
    float distance_meters;             /* 60: canvas center in front of viewer (-Z) */
    float vertical_offset_meters;      /* 64: canvas center up (+Y) */
    float horizontal_offset_meters;    /* 68: canvas center right (+X) */
    uint32_t data_offset;              /* 72: TPVR_DATA_OFFSET */
    uint32_t data_capacity;            /* 76: TPVR_MAX_IMAGE_BYTES */
    uint32_t app_pid;                  /* 80 */
    uint32_t canvas_width;             /* 84: pixels, same scale as atlas */
    uint32_t canvas_height;            /* 88 */
    uint32_t tile_count;               /* 92: tiles used in tile table (1 .. TPVR_MAX_TILES when visible) */
    uint8_t reserved_app[32];          /* 96 .. 127 */
    /* written by layer only */
    uint64_t layer_heartbeat_ms;       /* 128: GetTickCount64() at last frame of an OpenXR session */
    uint32_t layer_pid;                /* 136: game process id */
    uint32_t layer_state;              /* 140: TPVR_LAYER_* */
    uint32_t layer_graphics_api;       /* 144: TPVR_GRAPHICS_* */
    int32_t layer_last_result;         /* 148: last failed XrResult (0 none) */
    uint64_t layer_frames_shown;       /* 152: frames submitted with the overlay */
    uint32_t layer_version;            /* 160: TPVR_VERSION of layer */
    uint8_t reserved_layer[92];        /* 164 .. 255 */
} TpvrHeader;

/* Tile table entry (at TPVR_TILE_OFFSET + index * TPVR_TILE_SIZE), written by app inside seqlock */
typedef struct TpvrTile {
    uint32_t atlas_x;                  /* 0: left of tile in atlas */
    uint32_t atlas_y;                  /* 4: top of tile in atlas */
    uint32_t width;                    /* 8: pixels (same size in atlas & canvas) */
    uint32_t height;                   /* 12 */
    uint32_t canvas_x;                 /* 16: left of tile on canvas */
    uint32_t canvas_y;                 /* 20: top of tile on canvas */
    uint8_t reserved[8];               /* 24 .. 31 */
} TpvrTile;

#ifdef __cplusplus
static_assert(sizeof(TpvrHeader) == TPVR_HEADER_SIZE, "TpvrHeader size");
static_assert(offsetof(TpvrHeader, sequence) == 16, "sequence offset");
static_assert(offsetof(TpvrHeader, app_heartbeat_ms) == 24, "app_heartbeat_ms offset");
static_assert(offsetof(TpvrHeader, width_meters) == 56, "width_meters offset");
static_assert(offsetof(TpvrHeader, app_pid) == 80, "app_pid offset");
static_assert(offsetof(TpvrHeader, tile_count) == 92, "tile_count offset");
static_assert(offsetof(TpvrHeader, layer_heartbeat_ms) == 128, "layer_heartbeat_ms offset");
static_assert(offsetof(TpvrHeader, layer_frames_shown) == 152, "layer_frames_shown offset");
static_assert(offsetof(TpvrHeader, layer_version) == 160, "layer_version offset");
static_assert(sizeof(TpvrTile) == TPVR_TILE_SIZE, "TpvrTile size");
static_assert(offsetof(TpvrTile, canvas_y) == 20, "canvas_y offset");
static_assert(TPVR_TILE_OFFSET + TPVR_MAX_TILES * TPVR_TILE_SIZE <= TPVR_DATA_OFFSET, "tile table size");
#endif

#endif /* TINYPEDAL_VR_SHARED_H */
