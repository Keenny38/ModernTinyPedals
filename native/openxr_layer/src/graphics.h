/*
 * Modern Tiny Pedals - OpenXR overlay layer
 * Copyright (C) 2022-2026 TinyPedal developers, see contributors.md file
 * SPDX-License-Identifier: GPL-3.0-or-later
 *
 * Graphics API of the game session: uploads the overlay image into the layer's own swapchain images.
 * Called from xrEndFrame only (game render thread), with the session lock held.
 */

#ifndef TINYPEDAL_GRAPHICS_H
#define TINYPEDAL_GRAPHICS_H

#include "xr_includes.h"

#include <cstdint>
#include <memory>
#include <vector>

#include "shared_frame.h"

namespace tpvr {

class GraphicsBackend {
public:
    virtual ~GraphicsBackend() = default;
    GraphicsBackend() = default;
    GraphicsBackend(const GraphicsBackend&) = delete;
    GraphicsBackend& operator=(const GraphicsBackend&) = delete;

    virtual uint32_t api() const = 0;  // TPVR_GRAPHICS_*
    // Swapchain formats in order of preference
    virtual const FormatCandidate* format_candidates(size_t& count) const = 0;
    // Swapchain created by layer: keep its images (returns false on failure)
    virtual bool set_swapchain(XrSwapchain swapchain, PFN_xrEnumerateSwapchainImages enumerate, int64_t format) = 0;
    // Swapchain about to be destroyed: waits (no timeout) for GPU work using its images, images forgotten.
    // False: GPU work may still use the images, swapchain must be leaked rather than destroyed
    virtual bool clear_swapchain() = 0;
    // Copy pixels (width * height, tightly packed, swapchain byte order) to top left of acquired image
    virtual bool upload(uint32_t image_index, const uint8_t* pixels, uint32_t width, uint32_t height) = 0;
};

// nullptr when binding not usable (never throws)
std::unique_ptr<GraphicsBackend> create_d3d11_backend(const XrGraphicsBindingD3D11KHR& binding);
std::unique_ptr<GraphicsBackend> create_d3d12_backend(const XrGraphicsBindingD3D12KHR& binding);
std::unique_ptr<GraphicsBackend> create_vulkan_backend(const XrGraphicsBindingVulkanKHR& binding);

void log_message(const char* message);

}  // namespace tpvr

#endif  // TINYPEDAL_GRAPHICS_H
