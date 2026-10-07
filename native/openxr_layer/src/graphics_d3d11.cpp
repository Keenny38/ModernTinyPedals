/*
 * Modern Tiny Pedals - OpenXR overlay layer
 * Copyright (C) 2022-2026 TinyPedal developers, see contributors.md file
 * SPDX-License-Identifier: GPL-3.0-or-later
 *
 * D3D11 sessions (Le Mans Ultimate, rFactor 2 and most OpenXR sim games): UpdateSubresource on the
 * game's immediate context, called from xrEndFrame on the game's render thread. UpdateSubresource
 * changes no pipeline state, nothing to save or restore. A game that turned on D3D11 multithread protection
 * (xrEndFrame on another thread) gets the context locked the same way.
 */

#include "graphics.h"

#include <d3d11_4.h>

#include <new>

namespace tpvr {
namespace {

const FormatCandidate kFormats[] = {
    {DXGI_FORMAT_R8G8B8A8_UNORM_SRGB, false, true},
    {DXGI_FORMAT_B8G8R8A8_UNORM_SRGB, true, true},
    {DXGI_FORMAT_R8G8B8A8_UNORM, false, false},
    {DXGI_FORMAT_B8G8R8A8_UNORM, true, false},
};

class D3D11Backend final : public GraphicsBackend {
public:
    explicit D3D11Backend(ID3D11Device* device) : device_(device) {
        device_->AddRef();
        device_->GetImmediateContext(&context_);
        if (context_ != nullptr &&
            FAILED(context_->QueryInterface(__uuidof(ID3D11Multithread), reinterpret_cast<void**>(&multithread_)))) {
            multithread_ = nullptr;  // before Windows 10 Creators Update
        }
    }

    ~D3D11Backend() override {
        if (multithread_ != nullptr) {
            multithread_->Release();
        }
        if (context_ != nullptr) {
            context_->Release();
        }
        device_->Release();
    }

    bool valid() const { return context_ != nullptr; }

    uint32_t api() const override { return TPVR_GRAPHICS_D3D11; }

    const FormatCandidate* format_candidates(size_t& count) const override {
        count = sizeof(kFormats) / sizeof(kFormats[0]);
        return kFormats;
    }

    bool set_swapchain(XrSwapchain swapchain, PFN_xrEnumerateSwapchainImages enumerate, int64_t) override {
        textures_.clear();
        uint32_t count = 0;
        if (XR_FAILED(enumerate(swapchain, 0, &count, nullptr)) || count == 0 || count > 16) {
            return false;
        }
        std::vector<XrSwapchainImageD3D11KHR> images(count, {XR_TYPE_SWAPCHAIN_IMAGE_D3D11_KHR, nullptr, nullptr});
        if (XR_FAILED(enumerate(swapchain, count, &count, reinterpret_cast<XrSwapchainImageBaseHeader*>(images.data())))) {
            return false;
        }
        for (uint32_t index = 0; index < count; ++index) {
            if (images[index].texture == nullptr) {
                textures_.clear();
                return false;
            }
            textures_.push_back(images[index].texture);  // owned by runtime until swapchain destroyed
        }
        return true;
    }

    bool clear_swapchain() override {
        textures_.clear();
        return true;  // D3D11 keeps resources alive until GPU work using them finished
    }

    bool upload(uint32_t image_index, const uint8_t* pixels, uint32_t width, uint32_t height) override {
        if (image_index >= textures_.size() || pixels == nullptr) {
            return false;
        }
        D3D11_BOX box = {0, 0, 0, width, height, 1};
        const bool lock = multithread_ != nullptr && multithread_->GetMultithreadProtected() != FALSE;
        if (lock) {
            multithread_->Enter();
        }
        context_->UpdateSubresource(textures_[image_index], 0, &box, pixels, width * 4u, 0);
        if (lock) {
            multithread_->Leave();
        }
        return true;
    }

private:
    ID3D11Device* device_;
    ID3D11DeviceContext* context_ = nullptr;
    ID3D11Multithread* multithread_ = nullptr;
    std::vector<ID3D11Texture2D*> textures_;
};

}  // namespace

std::unique_ptr<GraphicsBackend> create_d3d11_backend(const XrGraphicsBindingD3D11KHR& binding) {
    if (binding.device == nullptr) {
        return nullptr;
    }
    std::unique_ptr<D3D11Backend> backend(new (std::nothrow) D3D11Backend(binding.device));
    if (!backend || !backend->valid()) {
        return nullptr;
    }
    return backend;
}

}  // namespace tpvr
