/*
 * Modern Tiny Pedals - OpenXR overlay layer
 * Copyright (C) 2022-2026 TinyPedal developers, see contributors.md file
 * SPDX-License-Identifier: GPL-3.0-or-later
 *
 * D3D12 sessions: copy from an upload buffer on the session queue (ID3D12CommandQueue is free threaded).
 * OpenXR gives swapchain images in RENDER_TARGET state after xrWaitSwapchainImage and expects them back
 * in that state at xrReleaseSwapchainImage. The runtime waits on the same queue at release, so the copy
 * is never waited on the CPU, only before the upload buffer & command allocator are used again.
 */

#include "graphics.h"

#include <cstring>
#include <new>

namespace tpvr {
namespace {

const FormatCandidate kFormats[] = {
    {DXGI_FORMAT_R8G8B8A8_UNORM_SRGB, false, true},
    {DXGI_FORMAT_B8G8R8A8_UNORM_SRGB, true, true},
    {DXGI_FORMAT_R8G8B8A8_UNORM, false, false},
    {DXGI_FORMAT_B8G8R8A8_UNORM, true, false},
};

constexpr DWORD kFenceTimeoutMs = 500;

template <class T>
void release(T*& pointer) {
    if (pointer != nullptr) {
        pointer->Release();
        pointer = nullptr;
    }
}

class D3D12Backend final : public GraphicsBackend {
public:
    D3D12Backend(ID3D12Device* device, ID3D12CommandQueue* queue) : device_(device), queue_(queue) {
        device_->AddRef();
        queue_->AddRef();
    }

    ~D3D12Backend() override {
        wait_idle();
        release(list_);
        release(allocator_);
        release(upload_);
        release(fence_);
        if (event_ != nullptr) {
            CloseHandle(event_);
        }
        queue_->Release();
        device_->Release();
    }

    bool init() {
        const D3D12_COMMAND_QUEUE_DESC desc = queue_->GetDesc();
        if (desc.Type != D3D12_COMMAND_LIST_TYPE_DIRECT) {
            return false;  // resource state transitions from RENDER_TARGET need a direct queue
        }
        if (FAILED(device_->CreateCommandAllocator(D3D12_COMMAND_LIST_TYPE_DIRECT, __uuidof(ID3D12CommandAllocator),
                                                   reinterpret_cast<void**>(&allocator_)))) {
            return false;
        }
        if (FAILED(device_->CreateCommandList(0, D3D12_COMMAND_LIST_TYPE_DIRECT, allocator_, nullptr,
                                              __uuidof(ID3D12GraphicsCommandList), reinterpret_cast<void**>(&list_)))) {
            return false;
        }
        list_->Close();
        if (FAILED(device_->CreateFence(0, D3D12_FENCE_FLAG_NONE, __uuidof(ID3D12Fence), reinterpret_cast<void**>(&fence_)))) {
            return false;
        }
        event_ = CreateEventW(nullptr, FALSE, FALSE, nullptr);
        return event_ != nullptr;
    }

    uint32_t api() const override { return TPVR_GRAPHICS_D3D12; }

    const FormatCandidate* format_candidates(size_t& count) const override {
        count = sizeof(kFormats) / sizeof(kFormats[0]);
        return kFormats;
    }

    bool set_swapchain(XrSwapchain swapchain, PFN_xrEnumerateSwapchainImages enumerate, int64_t format) override {
        textures_.clear();
        format_ = static_cast<DXGI_FORMAT>(format);
        uint32_t count = 0;
        if (XR_FAILED(enumerate(swapchain, 0, &count, nullptr)) || count == 0 || count > 16) {
            return false;
        }
        std::vector<XrSwapchainImageD3D12KHR> images(count, {XR_TYPE_SWAPCHAIN_IMAGE_D3D12_KHR, nullptr, nullptr});
        if (XR_FAILED(enumerate(swapchain, count, &count, reinterpret_cast<XrSwapchainImageBaseHeader*>(images.data())))) {
            return false;
        }
        for (uint32_t index = 0; index < count; ++index) {
            if (images[index].texture == nullptr) {
                textures_.clear();
                return false;
            }
            textures_.push_back(images[index].texture);
        }
        return true;
    }

    void clear_swapchain() override {
        wait_idle();
        textures_.clear();
    }

    bool upload(uint32_t image_index, const uint8_t* pixels, uint32_t width, uint32_t height) override {
        if (image_index >= textures_.size() || pixels == nullptr || width == 0 || height == 0) {
            return false;
        }
        if (!wait_idle()) {
            return false;  // previous copy not finished: upload buffer still in use
        }
        const UINT row_pitch = (width * 4u + D3D12_TEXTURE_DATA_PITCH_ALIGNMENT - 1u) /
                               D3D12_TEXTURE_DATA_PITCH_ALIGNMENT * D3D12_TEXTURE_DATA_PITCH_ALIGNMENT;
        const UINT64 size = static_cast<UINT64>(row_pitch) * height;
        if (!ensure_upload_buffer(size)) {
            return false;
        }
        void* mapped = nullptr;
        const D3D12_RANGE no_read = {0, 0};
        if (FAILED(upload_->Map(0, &no_read, &mapped)) || mapped == nullptr) {
            return false;
        }
        for (uint32_t row = 0; row < height; ++row) {
            std::memcpy(static_cast<uint8_t*>(mapped) + static_cast<size_t>(row_pitch) * row,
                        pixels + static_cast<size_t>(width) * 4u * row, static_cast<size_t>(width) * 4u);
        }
        upload_->Unmap(0, nullptr);

        if (FAILED(allocator_->Reset()) || FAILED(list_->Reset(allocator_, nullptr))) {
            return false;
        }
        ID3D12Resource* texture = textures_[image_index];
        D3D12_RESOURCE_BARRIER barrier = {};
        barrier.Type = D3D12_RESOURCE_BARRIER_TYPE_TRANSITION;
        barrier.Transition.pResource = texture;
        barrier.Transition.Subresource = D3D12_RESOURCE_BARRIER_ALL_SUBRESOURCES;
        barrier.Transition.StateBefore = D3D12_RESOURCE_STATE_RENDER_TARGET;
        barrier.Transition.StateAfter = D3D12_RESOURCE_STATE_COPY_DEST;
        list_->ResourceBarrier(1, &barrier);

        D3D12_TEXTURE_COPY_LOCATION target = {};
        target.pResource = texture;
        target.Type = D3D12_TEXTURE_COPY_TYPE_SUBRESOURCE_INDEX;
        target.SubresourceIndex = 0;
        D3D12_TEXTURE_COPY_LOCATION source = {};
        source.pResource = upload_;
        source.Type = D3D12_TEXTURE_COPY_TYPE_PLACED_FOOTPRINT;
        source.PlacedFootprint.Offset = 0;
        source.PlacedFootprint.Footprint.Format = format_;
        source.PlacedFootprint.Footprint.Width = width;
        source.PlacedFootprint.Footprint.Height = height;
        source.PlacedFootprint.Footprint.Depth = 1;
        source.PlacedFootprint.Footprint.RowPitch = row_pitch;
        list_->CopyTextureRegion(&target, 0, 0, 0, &source, nullptr);

        barrier.Transition.StateBefore = D3D12_RESOURCE_STATE_COPY_DEST;
        barrier.Transition.StateAfter = D3D12_RESOURCE_STATE_RENDER_TARGET;
        list_->ResourceBarrier(1, &barrier);
        if (FAILED(list_->Close())) {
            return false;
        }
        ID3D12CommandList* lists[] = {list_};
        queue_->ExecuteCommandLists(1, lists);
        ++fence_value_;
        return SUCCEEDED(queue_->Signal(fence_, fence_value_));
    }

private:
    bool wait_idle() {
        if (fence_ == nullptr || fence_->GetCompletedValue() >= fence_value_) {
            return true;
        }
        if (event_ == nullptr || FAILED(fence_->SetEventOnCompletion(fence_value_, event_))) {
            return false;
        }
        return WaitForSingleObject(event_, kFenceTimeoutMs) == WAIT_OBJECT_0;
    }

    bool ensure_upload_buffer(UINT64 size) {
        if (upload_ != nullptr && upload_size_ >= size) {
            return true;
        }
        release(upload_);
        upload_size_ = 0;
        D3D12_HEAP_PROPERTIES heap = {};
        heap.Type = D3D12_HEAP_TYPE_UPLOAD;
        heap.CPUPageProperty = D3D12_CPU_PAGE_PROPERTY_UNKNOWN;
        heap.MemoryPoolPreference = D3D12_MEMORY_POOL_UNKNOWN;
        heap.CreationNodeMask = 1;
        heap.VisibleNodeMask = 1;
        D3D12_RESOURCE_DESC desc = {};
        desc.Dimension = D3D12_RESOURCE_DIMENSION_BUFFER;
        desc.Width = size;
        desc.Height = 1;
        desc.DepthOrArraySize = 1;
        desc.MipLevels = 1;
        desc.Format = DXGI_FORMAT_UNKNOWN;
        desc.SampleDesc.Count = 1;
        desc.Layout = D3D12_TEXTURE_LAYOUT_ROW_MAJOR;
        if (FAILED(device_->CreateCommittedResource(&heap, D3D12_HEAP_FLAG_NONE, &desc,
                                                    D3D12_RESOURCE_STATE_GENERIC_READ, nullptr,
                                                    __uuidof(ID3D12Resource), reinterpret_cast<void**>(&upload_)))) {
            upload_ = nullptr;
            return false;
        }
        upload_size_ = size;
        return true;
    }

    ID3D12Device* device_;
    ID3D12CommandQueue* queue_;
    ID3D12CommandAllocator* allocator_ = nullptr;
    ID3D12GraphicsCommandList* list_ = nullptr;
    ID3D12Fence* fence_ = nullptr;
    HANDLE event_ = nullptr;
    UINT64 fence_value_ = 0;
    ID3D12Resource* upload_ = nullptr;
    UINT64 upload_size_ = 0;
    DXGI_FORMAT format_ = DXGI_FORMAT_UNKNOWN;
    std::vector<ID3D12Resource*> textures_;
};

}  // namespace

std::unique_ptr<GraphicsBackend> create_d3d12_backend(const XrGraphicsBindingD3D12KHR& binding) {
    if (binding.device == nullptr || binding.queue == nullptr) {
        return nullptr;
    }
    std::unique_ptr<D3D12Backend> backend(new (std::nothrow) D3D12Backend(binding.device, binding.queue));
    if (!backend || !backend->init()) {
        return nullptr;
    }
    return backend;
}

}  // namespace tpvr
