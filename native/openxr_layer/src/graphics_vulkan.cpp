/*
 * Modern Tiny Pedals - OpenXR overlay layer
 * Copyright (C) 2022-2026 TinyPedal developers, see contributors.md file
 * SPDX-License-Identifier: GPL-3.0-or-later
 *
 * Vulkan sessions (XR_KHR_vulkan_enable & enable2, same binding structure): copy from a host visible
 * buffer on the session queue. Functions come from the vulkan-1.dll already loaded by the game (nothing
 * linked, no Vulkan SDK needed). OpenXR requires the game to synchronize the session queue around
 * xrEndFrame, where this runs. Images are COLOR_ATTACHMENT_OPTIMAL after xrWaitSwapchainImage and must
 * be given back in that layout. The runtime waits on the same queue at release: CPU only waits before
 * the buffer & command buffer are used again.
 */

#include "graphics.h"

#include <cstring>
#include <new>

namespace tpvr {
namespace {

const FormatCandidate kFormats[] = {
    {VK_FORMAT_R8G8B8A8_SRGB, false, true},
    {VK_FORMAT_B8G8R8A8_SRGB, true, true},
    {VK_FORMAT_R8G8B8A8_UNORM, false, false},
    {VK_FORMAT_B8G8R8A8_UNORM, true, false},
};

constexpr uint64_t kFenceTimeoutNs = 500000000ull;

struct VulkanFunctions {
    PFN_vkGetPhysicalDeviceMemoryProperties GetPhysicalDeviceMemoryProperties = nullptr;
    PFN_vkGetDeviceQueue GetDeviceQueue = nullptr;
    PFN_vkCreateCommandPool CreateCommandPool = nullptr;
    PFN_vkDestroyCommandPool DestroyCommandPool = nullptr;
    PFN_vkAllocateCommandBuffers AllocateCommandBuffers = nullptr;
    PFN_vkBeginCommandBuffer BeginCommandBuffer = nullptr;
    PFN_vkEndCommandBuffer EndCommandBuffer = nullptr;
    PFN_vkResetCommandBuffer ResetCommandBuffer = nullptr;
    PFN_vkCmdPipelineBarrier CmdPipelineBarrier = nullptr;
    PFN_vkCmdCopyBufferToImage CmdCopyBufferToImage = nullptr;
    PFN_vkQueueSubmit QueueSubmit = nullptr;
    PFN_vkCreateFence CreateFence = nullptr;
    PFN_vkDestroyFence DestroyFence = nullptr;
    PFN_vkWaitForFences WaitForFences = nullptr;
    PFN_vkResetFences ResetFences = nullptr;
    PFN_vkCreateBuffer CreateBuffer = nullptr;
    PFN_vkDestroyBuffer DestroyBuffer = nullptr;
    PFN_vkGetBufferMemoryRequirements GetBufferMemoryRequirements = nullptr;
    PFN_vkAllocateMemory AllocateMemory = nullptr;
    PFN_vkFreeMemory FreeMemory = nullptr;
    PFN_vkBindBufferMemory BindBufferMemory = nullptr;
    PFN_vkMapMemory MapMemory = nullptr;
    PFN_vkUnmapMemory UnmapMemory = nullptr;
};

template <class T>
bool load(T& function, PFN_vkVoidFunction address) {
    function = reinterpret_cast<T>(address);
    return function != nullptr;
}

class VulkanBackend final : public GraphicsBackend {
public:
    explicit VulkanBackend(const XrGraphicsBindingVulkanKHR& binding) : binding_(binding) {}

    ~VulkanBackend() override {
        if (device() == VK_NULL_HANDLE || vk_.DestroyFence == nullptr) {
            return;
        }
        if (!wait_idle(UINT64_MAX)) {
            // Copy may still run on the game queue: objects it uses leaked rather than freed under the GPU
            log_message("Vulkan fence wait failed at teardown: upload resources leaked");
            return;
        }
        if (memory_ != VK_NULL_HANDLE) {
            vk_.FreeMemory(device(), memory_, nullptr);
        }
        if (buffer_ != VK_NULL_HANDLE) {
            vk_.DestroyBuffer(device(), buffer_, nullptr);
        }
        if (fence_ != VK_NULL_HANDLE) {
            vk_.DestroyFence(device(), fence_, nullptr);
        }
        if (pool_ != VK_NULL_HANDLE) {
            vk_.DestroyCommandPool(device(), pool_, nullptr);  // frees command buffer
        }
    }

    bool init() {
        HMODULE library = GetModuleHandleW(L"vulkan-1.dll");  // loaded by the game, reference not kept
        if (library == nullptr) {
            return false;
        }
        const auto get_instance_proc = reinterpret_cast<PFN_vkGetInstanceProcAddr>(
            reinterpret_cast<void*>(GetProcAddress(library, "vkGetInstanceProcAddr")));
        if (get_instance_proc == nullptr) {
            return false;
        }
        const auto get_device_proc = reinterpret_cast<PFN_vkGetDeviceProcAddr>(
            get_instance_proc(binding_.instance, "vkGetDeviceProcAddr"));
        if (get_device_proc == nullptr) {
            return false;
        }
        const VkDevice dev = device();
#define TPVR_DEVICE(name) load(vk_.name, get_device_proc(dev, "vk" #name))
        const bool loaded =
            load(vk_.GetPhysicalDeviceMemoryProperties,
                 get_instance_proc(binding_.instance, "vkGetPhysicalDeviceMemoryProperties")) &&
            TPVR_DEVICE(GetDeviceQueue) && TPVR_DEVICE(CreateCommandPool) && TPVR_DEVICE(DestroyCommandPool) &&
            TPVR_DEVICE(AllocateCommandBuffers) && TPVR_DEVICE(BeginCommandBuffer) && TPVR_DEVICE(EndCommandBuffer) &&
            TPVR_DEVICE(ResetCommandBuffer) && TPVR_DEVICE(CmdPipelineBarrier) && TPVR_DEVICE(CmdCopyBufferToImage) &&
            TPVR_DEVICE(QueueSubmit) && TPVR_DEVICE(CreateFence) && TPVR_DEVICE(DestroyFence) &&
            TPVR_DEVICE(WaitForFences) && TPVR_DEVICE(ResetFences) && TPVR_DEVICE(CreateBuffer) &&
            TPVR_DEVICE(DestroyBuffer) && TPVR_DEVICE(GetBufferMemoryRequirements) && TPVR_DEVICE(AllocateMemory) &&
            TPVR_DEVICE(FreeMemory) && TPVR_DEVICE(BindBufferMemory) && TPVR_DEVICE(MapMemory) &&
            TPVR_DEVICE(UnmapMemory);
#undef TPVR_DEVICE
        if (!loaded) {
            vk_ = VulkanFunctions{};
            return false;
        }
        vk_.GetDeviceQueue(dev, binding_.queueFamilyIndex, binding_.queueIndex, &queue_);
        if (queue_ == VK_NULL_HANDLE) {
            return false;
        }
        VkCommandPoolCreateInfo pool_info = {};
        pool_info.sType = VK_STRUCTURE_TYPE_COMMAND_POOL_CREATE_INFO;
        pool_info.flags = VK_COMMAND_POOL_CREATE_RESET_COMMAND_BUFFER_BIT;
        pool_info.queueFamilyIndex = binding_.queueFamilyIndex;
        if (vk_.CreateCommandPool(dev, &pool_info, nullptr, &pool_) != VK_SUCCESS) {
            pool_ = VK_NULL_HANDLE;
            return false;
        }
        VkCommandBufferAllocateInfo allocate_info = {};
        allocate_info.sType = VK_STRUCTURE_TYPE_COMMAND_BUFFER_ALLOCATE_INFO;
        allocate_info.commandPool = pool_;
        allocate_info.level = VK_COMMAND_BUFFER_LEVEL_PRIMARY;
        allocate_info.commandBufferCount = 1;
        if (vk_.AllocateCommandBuffers(dev, &allocate_info, &command_) != VK_SUCCESS) {
            command_ = VK_NULL_HANDLE;
            return false;
        }
        VkFenceCreateInfo fence_info = {};
        fence_info.sType = VK_STRUCTURE_TYPE_FENCE_CREATE_INFO;
        fence_info.flags = VK_FENCE_CREATE_SIGNALED_BIT;
        if (vk_.CreateFence(dev, &fence_info, nullptr, &fence_) != VK_SUCCESS) {
            fence_ = VK_NULL_HANDLE;
            return false;
        }
        return true;
    }

    uint32_t api() const override { return TPVR_GRAPHICS_VULKAN; }

    const FormatCandidate* format_candidates(size_t& count) const override {
        count = sizeof(kFormats) / sizeof(kFormats[0]);
        return kFormats;
    }

    bool set_swapchain(XrSwapchain swapchain, PFN_xrEnumerateSwapchainImages enumerate, int64_t) override {
        images_.clear();
        uint32_t count = 0;
        if (XR_FAILED(enumerate(swapchain, 0, &count, nullptr)) || count == 0 || count > 16) {
            return false;
        }
        std::vector<XrSwapchainImageVulkanKHR> images(count, {XR_TYPE_SWAPCHAIN_IMAGE_VULKAN_KHR, nullptr, VK_NULL_HANDLE});
        if (XR_FAILED(enumerate(swapchain, count, &count, reinterpret_cast<XrSwapchainImageBaseHeader*>(images.data())))) {
            return false;
        }
        for (uint32_t index = 0; index < count; ++index) {
            if (images[index].image == VK_NULL_HANDLE) {
                images_.clear();
                return false;
            }
            images_.push_back(images[index].image);
        }
        return true;
    }

    bool clear_swapchain() override {
        images_.clear();
        return wait_idle(UINT64_MAX);  // not a per frame path: wait for the copy however long it takes
    }

    bool upload(uint32_t image_index, const uint8_t* pixels, uint32_t width, uint32_t height) override {
        if (image_index >= images_.size() || pixels == nullptr || width == 0 || height == 0) {
            return false;
        }
        if (!wait_idle()) {
            return false;
        }
        const VkDeviceSize size = static_cast<VkDeviceSize>(width) * height * 4u;
        if (!ensure_buffer(size)) {
            return false;
        }
        void* mapped = nullptr;
        if (vk_.MapMemory(device(), memory_, 0, size, 0, &mapped) != VK_SUCCESS || mapped == nullptr) {
            return false;
        }
        std::memcpy(mapped, pixels, static_cast<size_t>(size));
        vk_.UnmapMemory(device(), memory_);  // host coherent memory, no flush

        if (vk_.ResetCommandBuffer(command_, 0) != VK_SUCCESS) {
            return false;
        }
        VkCommandBufferBeginInfo begin = {};
        begin.sType = VK_STRUCTURE_TYPE_COMMAND_BUFFER_BEGIN_INFO;
        begin.flags = VK_COMMAND_BUFFER_USAGE_ONE_TIME_SUBMIT_BIT;
        if (vk_.BeginCommandBuffer(command_, &begin) != VK_SUCCESS) {
            return false;
        }
        VkImageMemoryBarrier barrier = {};
        barrier.sType = VK_STRUCTURE_TYPE_IMAGE_MEMORY_BARRIER;
        barrier.srcAccessMask = VK_ACCESS_COLOR_ATTACHMENT_WRITE_BIT;
        barrier.dstAccessMask = VK_ACCESS_TRANSFER_WRITE_BIT;
        barrier.oldLayout = VK_IMAGE_LAYOUT_COLOR_ATTACHMENT_OPTIMAL;
        barrier.newLayout = VK_IMAGE_LAYOUT_TRANSFER_DST_OPTIMAL;
        barrier.srcQueueFamilyIndex = VK_QUEUE_FAMILY_IGNORED;
        barrier.dstQueueFamilyIndex = VK_QUEUE_FAMILY_IGNORED;
        barrier.image = images_[image_index];
        barrier.subresourceRange.aspectMask = VK_IMAGE_ASPECT_COLOR_BIT;
        barrier.subresourceRange.levelCount = 1;
        barrier.subresourceRange.layerCount = 1;
        vk_.CmdPipelineBarrier(command_, VK_PIPELINE_STAGE_COLOR_ATTACHMENT_OUTPUT_BIT, VK_PIPELINE_STAGE_TRANSFER_BIT,
                               0, 0, nullptr, 0, nullptr, 1, &barrier);
        VkBufferImageCopy region = {};
        region.imageSubresource.aspectMask = VK_IMAGE_ASPECT_COLOR_BIT;
        region.imageSubresource.layerCount = 1;
        region.imageExtent = {width, height, 1};
        vk_.CmdCopyBufferToImage(command_, buffer_, images_[image_index], VK_IMAGE_LAYOUT_TRANSFER_DST_OPTIMAL, 1,
                                 &region);
        barrier.srcAccessMask = VK_ACCESS_TRANSFER_WRITE_BIT;
        barrier.dstAccessMask = VK_ACCESS_SHADER_READ_BIT | VK_ACCESS_COLOR_ATTACHMENT_WRITE_BIT;
        barrier.oldLayout = VK_IMAGE_LAYOUT_TRANSFER_DST_OPTIMAL;
        barrier.newLayout = VK_IMAGE_LAYOUT_COLOR_ATTACHMENT_OPTIMAL;
        vk_.CmdPipelineBarrier(command_, VK_PIPELINE_STAGE_TRANSFER_BIT, VK_PIPELINE_STAGE_ALL_COMMANDS_BIT, 0, 0,
                               nullptr, 0, nullptr, 1, &barrier);
        if (vk_.EndCommandBuffer(command_) != VK_SUCCESS) {
            return false;
        }
        if (vk_.ResetFences(device(), 1, &fence_) != VK_SUCCESS) {
            return false;
        }
        VkSubmitInfo submit = {};
        submit.sType = VK_STRUCTURE_TYPE_SUBMIT_INFO;
        submit.commandBufferCount = 1;
        submit.pCommandBuffers = &command_;
        if (vk_.QueueSubmit(queue_, 1, &submit, fence_) != VK_SUCCESS) {
            fence_signaled_unknown_ = true;  // fence reset but never signaled: not waited on again
            return false;
        }
        return true;
    }

private:
    VkDevice device() const { return binding_.device; }

    bool wait_idle(uint64_t timeout_ns = kFenceTimeoutNs) {
        if (fence_ == VK_NULL_HANDLE || vk_.WaitForFences == nullptr) {
            return true;
        }
        if (fence_signaled_unknown_) {
            // Submit failed after fence reset: make it signaled again by recreating it
            vk_.DestroyFence(device(), fence_, nullptr);
            fence_ = VK_NULL_HANDLE;
            VkFenceCreateInfo fence_info = {};
            fence_info.sType = VK_STRUCTURE_TYPE_FENCE_CREATE_INFO;
            fence_info.flags = VK_FENCE_CREATE_SIGNALED_BIT;
            if (vk_.CreateFence(device(), &fence_info, nullptr, &fence_) != VK_SUCCESS) {
                fence_ = VK_NULL_HANDLE;
                return false;
            }
            fence_signaled_unknown_ = false;
            return true;
        }
        const VkResult result = vk_.WaitForFences(device(), 1, &fence_, VK_TRUE, timeout_ns);
        // Device lost: no GPU work runs any more, resources may be freed
        return result == VK_SUCCESS || (timeout_ns == UINT64_MAX && result == VK_ERROR_DEVICE_LOST);
    }

    bool ensure_buffer(VkDeviceSize size) {
        if (buffer_ != VK_NULL_HANDLE && buffer_size_ >= size) {
            return true;
        }
        if (memory_ != VK_NULL_HANDLE) {
            vk_.FreeMemory(device(), memory_, nullptr);
            memory_ = VK_NULL_HANDLE;
        }
        if (buffer_ != VK_NULL_HANDLE) {
            vk_.DestroyBuffer(device(), buffer_, nullptr);
            buffer_ = VK_NULL_HANDLE;
        }
        buffer_size_ = 0;
        VkBufferCreateInfo buffer_info = {};
        buffer_info.sType = VK_STRUCTURE_TYPE_BUFFER_CREATE_INFO;
        buffer_info.size = size;
        buffer_info.usage = VK_BUFFER_USAGE_TRANSFER_SRC_BIT;
        buffer_info.sharingMode = VK_SHARING_MODE_EXCLUSIVE;
        if (vk_.CreateBuffer(device(), &buffer_info, nullptr, &buffer_) != VK_SUCCESS) {
            buffer_ = VK_NULL_HANDLE;
            return false;
        }
        VkMemoryRequirements requirements = {};
        vk_.GetBufferMemoryRequirements(device(), buffer_, &requirements);
        VkPhysicalDeviceMemoryProperties properties = {};
        vk_.GetPhysicalDeviceMemoryProperties(binding_.physicalDevice, &properties);
        const VkMemoryPropertyFlags wanted = VK_MEMORY_PROPERTY_HOST_VISIBLE_BIT | VK_MEMORY_PROPERTY_HOST_COHERENT_BIT;
        uint32_t type_index = UINT32_MAX;
        for (uint32_t index = 0; index < properties.memoryTypeCount && index < VK_MAX_MEMORY_TYPES; ++index) {
            if ((requirements.memoryTypeBits & (1u << index)) != 0 &&
                (properties.memoryTypes[index].propertyFlags & wanted) == wanted) {
                type_index = index;
                break;
            }
        }
        if (type_index == UINT32_MAX) {
            return false;
        }
        VkMemoryAllocateInfo allocate_info = {};
        allocate_info.sType = VK_STRUCTURE_TYPE_MEMORY_ALLOCATE_INFO;
        allocate_info.allocationSize = requirements.size;
        allocate_info.memoryTypeIndex = type_index;
        if (vk_.AllocateMemory(device(), &allocate_info, nullptr, &memory_) != VK_SUCCESS) {
            memory_ = VK_NULL_HANDLE;
            return false;
        }
        if (vk_.BindBufferMemory(device(), buffer_, memory_, 0) != VK_SUCCESS) {
            return false;
        }
        buffer_size_ = size;
        return true;
    }

    XrGraphicsBindingVulkanKHR binding_;
    VulkanFunctions vk_;
    VkQueue queue_ = VK_NULL_HANDLE;
    VkCommandPool pool_ = VK_NULL_HANDLE;
    VkCommandBuffer command_ = VK_NULL_HANDLE;
    VkFence fence_ = VK_NULL_HANDLE;
    bool fence_signaled_unknown_ = false;
    VkBuffer buffer_ = VK_NULL_HANDLE;
    VkDeviceMemory memory_ = VK_NULL_HANDLE;
    VkDeviceSize buffer_size_ = 0;
    std::vector<VkImage> images_;
};

}  // namespace

std::unique_ptr<GraphicsBackend> create_vulkan_backend(const XrGraphicsBindingVulkanKHR& binding) {
    if (binding.instance == VK_NULL_HANDLE || binding.physicalDevice == VK_NULL_HANDLE ||
        binding.device == VK_NULL_HANDLE) {
        return nullptr;
    }
    std::unique_ptr<VulkanBackend> backend(new (std::nothrow) VulkanBackend(binding));
    if (!backend || !backend->init()) {
        return nullptr;
    }
    return backend;
}

}  // namespace tpvr
