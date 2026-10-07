/*
 * Integration test of TinyPedalXrLayer.dll (Windows, or Wine): a fake OpenXR runtime below the layer,
 * the app side written like tinypedal/vr_shared.py, real D3D11 / D3D12 / Vulkan devices when available
 * (an API without a device is skipped). Checks the layer loads & negotiates like the OpenXR loader does,
 * appends the overlay quad, uploads correct pixels, and stays a pure pass-through when it should.
 *
 *   layer_harness <path to TinyPedalXrLayer.dll>
 */

#include "../src/xr_includes.h"

#include <dxgi1_4.h>

#include <cmath>
#include <cstdio>
#include <cstring>
#include <map>
#include <string>
#include <vector>

#include "tinypedal_vr_shared.h"

namespace {

int failures = 0;

void check(bool condition, const char* what, int line) {
    if (!condition) {
        std::printf("  FAILED line %d: %s\n", line, what);
        ++failures;
    }
}

#define CHECK(condition) check((condition), #condition, __LINE__)

template <class T>
T fake_handle(uintptr_t value) {
    return reinterpret_cast<T>(value);
}

// -----------------------------------------------------------------------------------------------------------
// App side (same as tinypedal/vr_shared.py)

struct App {
    HANDLE mapping = nullptr;
    uint8_t* view = nullptr;
    uint32_t serial = 0;

    bool open() {
        mapping = CreateFileMappingA(INVALID_HANDLE_VALUE, nullptr, PAGE_READWRITE, 0, TPVR_MAPPING_SIZE, TPVR_MAPPING_NAME);
        if (mapping == nullptr) {
            return false;
        }
        view = static_cast<uint8_t*>(MapViewOfFile(mapping, FILE_MAP_ALL_ACCESS, 0, 0, TPVR_MAPPING_SIZE));
        if (view == nullptr) {
            return false;
        }
        TpvrHeader& h = header();
        h.magic = TPVR_MAGIC;
        h.version = TPVR_VERSION;
        h.header_size = TPVR_HEADER_SIZE;
        h.mapping_size = TPVR_MAPPING_SIZE;
        h.data_offset = TPVR_DATA_OFFSET;
        h.data_capacity = TPVR_MAX_IMAGE_BYTES;
        return true;
    }

    void close() {
        if (view != nullptr) {
            UnmapViewOfFile(view);
        }
        if (mapping != nullptr) {
            CloseHandle(mapping);
        }
        view = nullptr;
        mapping = nullptr;
    }

    TpvrHeader& header() { return *reinterpret_cast<TpvrHeader*>(view); }

    void heartbeat() { header().app_heartbeat_ms = GetTickCount64(); }

    // Image: pixel (x, y) = (x * 10, y * 10, 100, 200), RGBA straight alpha
    void write(uint32_t width, uint32_t height, bool visible, bool attach) {
        TpvrHeader& h = header();
        h.sequence += 1;
        h.width = width;
        h.height = height;
        h.stride = width * 4u;
        h.pixel_format = TPVR_FORMAT_RGBA8_STRAIGHT;
        h.flags = (visible ? TPVR_FLAG_VISIBLE : 0u) | (attach ? TPVR_FLAG_ATTACH_TO_HEADSET : 0u);
        h.image_serial = ++serial;
        h.width_meters = 0.5f;
        h.distance_meters = 1.25f;
        h.vertical_offset_meters = -0.25f;
        h.horizontal_offset_meters = 0.125f;
        uint8_t* pixels = view + TPVR_DATA_OFFSET;
        for (uint32_t y = 0; y < height; ++y) {
            for (uint32_t x = 0; x < width; ++x) {
                uint8_t* pixel = pixels + (static_cast<size_t>(y) * width + x) * 4u;
                pixel[0] = static_cast<uint8_t>(x * 10u);
                pixel[1] = static_cast<uint8_t>(y * 10u);
                pixel[2] = 100;
                pixel[3] = 200;
            }
        }
        h.sequence += 1;
        heartbeat();
    }
};

// -----------------------------------------------------------------------------------------------------------
// Fake runtime

enum class Api { D3D11, D3D12, Vulkan, OpenGL };

struct FakeSwapchain {
    XrSwapchainCreateInfo info = {};
    std::vector<ID3D11Texture2D*> d3d11;
    std::vector<ID3D12Resource*> d3d12;
    std::vector<VkImage> vulkan;
    std::vector<VkDeviceMemory> vulkan_memory;
    uint32_t next_index = 0;
    int acquired = -1;
    bool waited = false;
    int last_released = -1;
    int acquire_count = 0;
};

struct VulkanContext;

struct Runtime {
    Api api = Api::D3D11;
    std::vector<int64_t> formats;
    ID3D11Device* d3d11 = nullptr;
    ID3D12Device* d3d12 = nullptr;
    VulkanContext* vulkan = nullptr;
    std::map<XrSwapchain, FakeSwapchain*> swapchains;
    uintptr_t next_handle = 0x1000;
    int spaces_alive = 0;
    bool refuse_extra_layers = false;
    int end_frame_calls = 0;
    std::vector<uint32_t> submitted_counts;
    XrCompositionLayerQuad last_quad = {};
    XrSpace view_space = XR_NULL_HANDLE;
    XrSpace local_space = XR_NULL_HANDLE;
    bool order_error = false;
};

Runtime runtime;

struct VulkanContext {
    HMODULE library = nullptr;
    PFN_vkGetInstanceProcAddr gipa = nullptr;
    VkInstance instance = VK_NULL_HANDLE;
    VkPhysicalDevice physical = VK_NULL_HANDLE;
    VkDevice device = VK_NULL_HANDLE;
    uint32_t family = 0;
    VkQueue queue = VK_NULL_HANDLE;
    PFN_vkGetDeviceProcAddr gdpa = nullptr;

    template <class T>
    T device_fn(const char* name) {
        return reinterpret_cast<T>(gdpa(device, name));
    }

    bool create();
    VkImage create_image(const XrSwapchainCreateInfo& info, VkDeviceMemory& memory);
    void destroy_image(VkImage image, VkDeviceMemory memory);
    std::vector<uint8_t> read(VkImage image, uint32_t width, uint32_t height);
    void destroy();
};

XRAPI_ATTR XrResult XRAPI_CALL rt_xrGetInstanceProcAddr(XrInstance, const char* name, PFN_xrVoidFunction* function);

XRAPI_ATTR XrResult XRAPI_CALL rt_xrCreateApiLayerInstance(const XrInstanceCreateInfo*, const XrApiLayerCreateInfo* info,
                                                           XrInstance* instance) {
    if (info == nullptr || info->nextInfo != nullptr) {
        return XR_ERROR_INITIALIZATION_FAILED;  // layer must remove itself from the chain
    }
    *instance = fake_handle<XrInstance>(0x10);
    return XR_SUCCESS;
}

XRAPI_ATTR XrResult XRAPI_CALL rt_xrDestroyInstance(XrInstance) { return XR_SUCCESS; }

XRAPI_ATTR XrResult XRAPI_CALL rt_xrCreateSession(XrInstance, const XrSessionCreateInfo*, XrSession* session) {
    *session = fake_handle<XrSession>(runtime.next_handle++);
    return XR_SUCCESS;
}

XRAPI_ATTR XrResult XRAPI_CALL rt_xrDestroySession(XrSession) { return XR_SUCCESS; }

XRAPI_ATTR XrResult XRAPI_CALL rt_xrGetSystemProperties(XrInstance, XrSystemId, XrSystemProperties* properties) {
    properties->graphicsProperties.maxLayerCount = 16;
    properties->graphicsProperties.maxSwapchainImageWidth = 4096;
    properties->graphicsProperties.maxSwapchainImageHeight = 4096;
    return XR_SUCCESS;
}

XRAPI_ATTR XrResult XRAPI_CALL rt_xrEnumerateSwapchainFormats(XrSession, uint32_t capacity, uint32_t* count, int64_t* formats) {
    *count = static_cast<uint32_t>(runtime.formats.size());
    if (capacity == 0) {
        return XR_SUCCESS;
    }
    if (capacity < runtime.formats.size()) {
        return XR_ERROR_SIZE_INSUFFICIENT;
    }
    std::memcpy(formats, runtime.formats.data(), runtime.formats.size() * sizeof(int64_t));
    return XR_SUCCESS;
}

XRAPI_ATTR XrResult XRAPI_CALL rt_xrCreateSwapchain(XrSession, const XrSwapchainCreateInfo* info, XrSwapchain* swapchain) {
    auto* fake = new FakeSwapchain;
    fake->info = *info;
    for (int index = 0; index < 3; ++index) {
        if (runtime.api == Api::D3D11) {
            D3D11_TEXTURE2D_DESC desc = {};
            desc.Width = info->width;
            desc.Height = info->height;
            desc.MipLevels = 1;
            desc.ArraySize = 1;
            desc.Format = static_cast<DXGI_FORMAT>(info->format);
            desc.SampleDesc.Count = 1;
            desc.Usage = D3D11_USAGE_DEFAULT;
            desc.BindFlags = D3D11_BIND_RENDER_TARGET | D3D11_BIND_SHADER_RESOURCE;
            ID3D11Texture2D* texture = nullptr;
            if (FAILED(runtime.d3d11->CreateTexture2D(&desc, nullptr, &texture))) {
                delete fake;
                return XR_ERROR_RUNTIME_FAILURE;
            }
            fake->d3d11.push_back(texture);
        } else if (runtime.api == Api::D3D12) {
            D3D12_HEAP_PROPERTIES heap = {};
            heap.Type = D3D12_HEAP_TYPE_DEFAULT;
            D3D12_RESOURCE_DESC desc = {};
            desc.Dimension = D3D12_RESOURCE_DIMENSION_TEXTURE2D;
            desc.Width = info->width;
            desc.Height = info->height;
            desc.DepthOrArraySize = 1;
            desc.MipLevels = 1;
            desc.Format = static_cast<DXGI_FORMAT>(info->format);
            desc.SampleDesc.Count = 1;
            desc.Flags = D3D12_RESOURCE_FLAG_ALLOW_RENDER_TARGET;
            ID3D12Resource* texture = nullptr;
            if (FAILED(runtime.d3d12->CreateCommittedResource(&heap, D3D12_HEAP_FLAG_NONE, &desc,
                                                               D3D12_RESOURCE_STATE_RENDER_TARGET, nullptr,
                                                               __uuidof(ID3D12Resource), reinterpret_cast<void**>(&texture)))) {
                delete fake;
                return XR_ERROR_RUNTIME_FAILURE;
            }
            fake->d3d12.push_back(texture);
        } else if (runtime.api == Api::Vulkan) {
            VkDeviceMemory memory = VK_NULL_HANDLE;
            VkImage image = runtime.vulkan->create_image(*info, memory);
            if (image == VK_NULL_HANDLE) {
                delete fake;
                return XR_ERROR_RUNTIME_FAILURE;
            }
            fake->vulkan.push_back(image);
            fake->vulkan_memory.push_back(memory);
        }
    }
    *swapchain = fake_handle<XrSwapchain>(runtime.next_handle++);
    runtime.swapchains[*swapchain] = fake;
    return XR_SUCCESS;
}

XRAPI_ATTR XrResult XRAPI_CALL rt_xrDestroySwapchain(XrSwapchain swapchain) {
    auto found = runtime.swapchains.find(swapchain);
    if (found == runtime.swapchains.end()) {
        return XR_ERROR_HANDLE_INVALID;
    }
    FakeSwapchain* fake = found->second;
    for (auto* texture : fake->d3d11) {
        texture->Release();
    }
    for (auto* texture : fake->d3d12) {
        texture->Release();
    }
    for (size_t index = 0; index < fake->vulkan.size(); ++index) {
        runtime.vulkan->destroy_image(fake->vulkan[index], fake->vulkan_memory[index]);
    }
    delete fake;
    runtime.swapchains.erase(found);
    return XR_SUCCESS;
}

XRAPI_ATTR XrResult XRAPI_CALL rt_xrEnumerateSwapchainImages(XrSwapchain swapchain, uint32_t capacity, uint32_t* count,
                                                             XrSwapchainImageBaseHeader* images) {
    auto found = runtime.swapchains.find(swapchain);
    if (found == runtime.swapchains.end()) {
        return XR_ERROR_HANDLE_INVALID;
    }
    *count = 3;
    if (capacity == 0) {
        return XR_SUCCESS;
    }
    for (uint32_t index = 0; index < 3 && index < capacity; ++index) {
        if (runtime.api == Api::D3D11) {
            auto* image = reinterpret_cast<XrSwapchainImageD3D11KHR*>(images) + index;
            if (image->type != XR_TYPE_SWAPCHAIN_IMAGE_D3D11_KHR) {
                return XR_ERROR_VALIDATION_FAILURE;
            }
            image->texture = found->second->d3d11[index];
        } else if (runtime.api == Api::D3D12) {
            auto* image = reinterpret_cast<XrSwapchainImageD3D12KHR*>(images) + index;
            if (image->type != XR_TYPE_SWAPCHAIN_IMAGE_D3D12_KHR) {
                return XR_ERROR_VALIDATION_FAILURE;
            }
            image->texture = found->second->d3d12[index];
        } else {
            auto* image = reinterpret_cast<XrSwapchainImageVulkanKHR*>(images) + index;
            if (image->type != XR_TYPE_SWAPCHAIN_IMAGE_VULKAN_KHR) {
                return XR_ERROR_VALIDATION_FAILURE;
            }
            image->image = found->second->vulkan[index];
        }
    }
    return XR_SUCCESS;
}

XRAPI_ATTR XrResult XRAPI_CALL rt_xrAcquireSwapchainImage(XrSwapchain swapchain, const XrSwapchainImageAcquireInfo*,
                                                          uint32_t* index) {
    FakeSwapchain* fake = runtime.swapchains.at(swapchain);
    if (fake->acquired >= 0) {
        runtime.order_error = true;
        return XR_ERROR_CALL_ORDER_INVALID;
    }
    fake->acquired = static_cast<int>(fake->next_index);
    fake->waited = false;
    fake->next_index = (fake->next_index + 1) % 3;
    ++fake->acquire_count;
    *index = static_cast<uint32_t>(fake->acquired);
    return XR_SUCCESS;
}

XRAPI_ATTR XrResult XRAPI_CALL rt_xrWaitSwapchainImage(XrSwapchain swapchain, const XrSwapchainImageWaitInfo*) {
    FakeSwapchain* fake = runtime.swapchains.at(swapchain);
    if (fake->acquired < 0 || fake->waited) {
        runtime.order_error = true;
        return XR_ERROR_CALL_ORDER_INVALID;
    }
    fake->waited = true;
    return XR_SUCCESS;
}

XRAPI_ATTR XrResult XRAPI_CALL rt_xrReleaseSwapchainImage(XrSwapchain swapchain, const XrSwapchainImageReleaseInfo*) {
    FakeSwapchain* fake = runtime.swapchains.at(swapchain);
    if (fake->acquired < 0 || !fake->waited) {
        runtime.order_error = true;
        return XR_ERROR_CALL_ORDER_INVALID;
    }
    fake->last_released = fake->acquired;
    fake->acquired = -1;
    return XR_SUCCESS;
}

XRAPI_ATTR XrResult XRAPI_CALL rt_xrCreateReferenceSpace(XrSession, const XrReferenceSpaceCreateInfo* info, XrSpace* space) {
    *space = fake_handle<XrSpace>(runtime.next_handle++);
    if (info->referenceSpaceType == XR_REFERENCE_SPACE_TYPE_VIEW) {
        runtime.view_space = *space;
    } else if (info->referenceSpaceType == XR_REFERENCE_SPACE_TYPE_LOCAL) {
        runtime.local_space = *space;
    }
    ++runtime.spaces_alive;
    return XR_SUCCESS;
}

XRAPI_ATTR XrResult XRAPI_CALL rt_xrDestroySpace(XrSpace) {
    --runtime.spaces_alive;
    return XR_SUCCESS;
}

XRAPI_ATTR XrResult XRAPI_CALL rt_xrEndFrame(XrSession, const XrFrameEndInfo* info) {
    ++runtime.end_frame_calls;
    runtime.submitted_counts.push_back(info->layerCount);
    if (info->layerCount > 1) {
        if (runtime.refuse_extra_layers) {
            return XR_ERROR_LAYER_INVALID;
        }
        const auto* last = info->layers[info->layerCount - 1];
        if (last->type == XR_TYPE_COMPOSITION_LAYER_QUAD) {
            runtime.last_quad = *reinterpret_cast<const XrCompositionLayerQuad*>(last);
            auto found = runtime.swapchains.find(runtime.last_quad.subImage.swapchain);
            if (found == runtime.swapchains.end() || found->second->last_released < 0) {
                runtime.order_error = true;  // swapchain never released
            }
        }
    }
    return XR_SUCCESS;
}

XRAPI_ATTR XrResult XRAPI_CALL rt_xrGetInstanceProcAddr(XrInstance, const char* name, PFN_xrVoidFunction* function) {
#define RT_FUNCTION(fn)                                              \
    if (std::strcmp(name, #fn) == 0) {                               \
        *function = reinterpret_cast<PFN_xrVoidFunction>(rt_##fn);   \
        return XR_SUCCESS;                                           \
    }
    RT_FUNCTION(xrGetInstanceProcAddr)
    RT_FUNCTION(xrDestroyInstance)
    RT_FUNCTION(xrCreateSession)
    RT_FUNCTION(xrDestroySession)
    RT_FUNCTION(xrGetSystemProperties)
    RT_FUNCTION(xrEnumerateSwapchainFormats)
    RT_FUNCTION(xrCreateSwapchain)
    RT_FUNCTION(xrDestroySwapchain)
    RT_FUNCTION(xrEnumerateSwapchainImages)
    RT_FUNCTION(xrAcquireSwapchainImage)
    RT_FUNCTION(xrWaitSwapchainImage)
    RT_FUNCTION(xrReleaseSwapchainImage)
    RT_FUNCTION(xrCreateReferenceSpace)
    RT_FUNCTION(xrDestroySpace)
    RT_FUNCTION(xrEndFrame)
#undef RT_FUNCTION
    *function = nullptr;
    return XR_ERROR_FUNCTION_UNSUPPORTED;
}

// -----------------------------------------------------------------------------------------------------------
// Readback of a swapchain image (RGBA or BGRA bytes, width x height)

std::vector<uint8_t> read_d3d11(ID3D11Texture2D* texture) {
    D3D11_TEXTURE2D_DESC desc = {};
    texture->GetDesc(&desc);
    desc.Usage = D3D11_USAGE_STAGING;
    desc.BindFlags = 0;
    desc.CPUAccessFlags = D3D11_CPU_ACCESS_READ;
    ID3D11Texture2D* staging = nullptr;
    std::vector<uint8_t> pixels;
    if (FAILED(runtime.d3d11->CreateTexture2D(&desc, nullptr, &staging))) {
        return pixels;
    }
    ID3D11DeviceContext* context = nullptr;
    runtime.d3d11->GetImmediateContext(&context);
    context->CopyResource(staging, texture);
    D3D11_MAPPED_SUBRESOURCE mapped = {};
    if (SUCCEEDED(context->Map(staging, 0, D3D11_MAP_READ, 0, &mapped))) {
        pixels.resize(static_cast<size_t>(desc.Width) * desc.Height * 4u);
        for (UINT row = 0; row < desc.Height; ++row) {
            std::memcpy(pixels.data() + static_cast<size_t>(row) * desc.Width * 4u,
                        static_cast<uint8_t*>(mapped.pData) + static_cast<size_t>(row) * mapped.RowPitch,
                        static_cast<size_t>(desc.Width) * 4u);
        }
        context->Unmap(staging, 0);
    }
    context->Release();
    staging->Release();
    return pixels;
}

ID3D12CommandQueue* g_d3d12_queue = nullptr;

std::vector<uint8_t> read_d3d12(ID3D12Resource* texture, uint32_t width, uint32_t height) {
    std::vector<uint8_t> pixels;
    ID3D12Device* device = runtime.d3d12;
    D3D12_RESOURCE_DESC texture_desc = texture->GetDesc();
    D3D12_PLACED_SUBRESOURCE_FOOTPRINT footprint = {};
    UINT64 total = 0;
    device->GetCopyableFootprints(&texture_desc, 0, 1, 0, &footprint, nullptr, nullptr, &total);
    D3D12_HEAP_PROPERTIES heap = {};
    heap.Type = D3D12_HEAP_TYPE_READBACK;
    D3D12_RESOURCE_DESC desc = {};
    desc.Dimension = D3D12_RESOURCE_DIMENSION_BUFFER;
    desc.Width = total;
    desc.Height = 1;
    desc.DepthOrArraySize = 1;
    desc.MipLevels = 1;
    desc.SampleDesc.Count = 1;
    desc.Layout = D3D12_TEXTURE_LAYOUT_ROW_MAJOR;
    ID3D12Resource* buffer = nullptr;
    ID3D12CommandAllocator* allocator = nullptr;
    ID3D12GraphicsCommandList* list = nullptr;
    ID3D12Fence* fence = nullptr;
    if (FAILED(device->CreateCommittedResource(&heap, D3D12_HEAP_FLAG_NONE, &desc, D3D12_RESOURCE_STATE_COPY_DEST, nullptr,
                                               __uuidof(ID3D12Resource), reinterpret_cast<void**>(&buffer))) ||
        FAILED(device->CreateCommandAllocator(D3D12_COMMAND_LIST_TYPE_DIRECT, __uuidof(ID3D12CommandAllocator),
                                              reinterpret_cast<void**>(&allocator))) ||
        FAILED(device->CreateCommandList(0, D3D12_COMMAND_LIST_TYPE_DIRECT, allocator, nullptr,
                                         __uuidof(ID3D12GraphicsCommandList), reinterpret_cast<void**>(&list))) ||
        FAILED(device->CreateFence(0, D3D12_FENCE_FLAG_NONE, __uuidof(ID3D12Fence), reinterpret_cast<void**>(&fence)))) {
        return pixels;
    }
    D3D12_RESOURCE_BARRIER barrier = {};
    barrier.Type = D3D12_RESOURCE_BARRIER_TYPE_TRANSITION;
    barrier.Transition.pResource = texture;
    barrier.Transition.Subresource = D3D12_RESOURCE_BARRIER_ALL_SUBRESOURCES;
    barrier.Transition.StateBefore = D3D12_RESOURCE_STATE_RENDER_TARGET;
    barrier.Transition.StateAfter = D3D12_RESOURCE_STATE_COPY_SOURCE;
    list->ResourceBarrier(1, &barrier);
    D3D12_TEXTURE_COPY_LOCATION target = {};
    target.pResource = buffer;
    target.Type = D3D12_TEXTURE_COPY_TYPE_PLACED_FOOTPRINT;
    target.PlacedFootprint = footprint;
    D3D12_TEXTURE_COPY_LOCATION source = {};
    source.pResource = texture;
    source.Type = D3D12_TEXTURE_COPY_TYPE_SUBRESOURCE_INDEX;
    list->CopyTextureRegion(&target, 0, 0, 0, &source, nullptr);
    barrier.Transition.StateBefore = D3D12_RESOURCE_STATE_COPY_SOURCE;
    barrier.Transition.StateAfter = D3D12_RESOURCE_STATE_RENDER_TARGET;
    list->ResourceBarrier(1, &barrier);
    list->Close();
    ID3D12CommandList* lists[] = {list};
    g_d3d12_queue->ExecuteCommandLists(1, lists);
    g_d3d12_queue->Signal(fence, 1);
    HANDLE event = CreateEventW(nullptr, FALSE, FALSE, nullptr);
    fence->SetEventOnCompletion(1, event);
    WaitForSingleObject(event, 5000);
    CloseHandle(event);
    void* mapped = nullptr;
    if (SUCCEEDED(buffer->Map(0, nullptr, &mapped))) {
        pixels.resize(static_cast<size_t>(width) * height * 4u);
        for (uint32_t row = 0; row < height; ++row) {
            std::memcpy(pixels.data() + static_cast<size_t>(row) * width * 4u,
                        static_cast<uint8_t*>(mapped) + footprint.Offset + static_cast<size_t>(row) * footprint.Footprint.RowPitch,
                        static_cast<size_t>(width) * 4u);
        }
        buffer->Unmap(0, nullptr);
    }
    fence->Release();
    list->Release();
    allocator->Release();
    buffer->Release();
    return pixels;
}

// -----------------------------------------------------------------------------------------------------------
// Vulkan device (lavapipe under Wine, any driver on Windows)

bool VulkanContext::create() {
    library = LoadLibraryW(L"vulkan-1.dll");
    if (library == nullptr) {
        return false;
    }
    gipa = reinterpret_cast<PFN_vkGetInstanceProcAddr>(reinterpret_cast<void*>(GetProcAddress(library, "vkGetInstanceProcAddr")));
    if (gipa == nullptr) {
        return false;
    }
    auto create_instance = reinterpret_cast<PFN_vkCreateInstance>(gipa(VK_NULL_HANDLE, "vkCreateInstance"));
    VkApplicationInfo app = {};
    app.sType = VK_STRUCTURE_TYPE_APPLICATION_INFO;
    app.apiVersion = VK_API_VERSION_1_1;
    VkInstanceCreateInfo instance_info = {};
    instance_info.sType = VK_STRUCTURE_TYPE_INSTANCE_CREATE_INFO;
    instance_info.pApplicationInfo = &app;
    if (create_instance == nullptr || create_instance(&instance_info, nullptr, &instance) != VK_SUCCESS) {
        return false;
    }
    auto enumerate = reinterpret_cast<PFN_vkEnumeratePhysicalDevices>(gipa(instance, "vkEnumeratePhysicalDevices"));
    uint32_t count = 1;
    if (enumerate(instance, &count, &physical) < 0 || count == 0) {
        return false;
    }
    auto families = reinterpret_cast<PFN_vkGetPhysicalDeviceQueueFamilyProperties>(
        gipa(instance, "vkGetPhysicalDeviceQueueFamilyProperties"));
    uint32_t family_count = 0;
    families(physical, &family_count, nullptr);
    std::vector<VkQueueFamilyProperties> properties(family_count);
    families(physical, &family_count, properties.data());
    family = UINT32_MAX;
    for (uint32_t index = 0; index < family_count; ++index) {
        if (properties[index].queueFlags & VK_QUEUE_GRAPHICS_BIT) {
            family = index;
            break;
        }
    }
    if (family == UINT32_MAX) {
        return false;
    }
    const float priority = 1.0f;
    VkDeviceQueueCreateInfo queue_info = {};
    queue_info.sType = VK_STRUCTURE_TYPE_DEVICE_QUEUE_CREATE_INFO;
    queue_info.queueFamilyIndex = family;
    queue_info.queueCount = 1;
    queue_info.pQueuePriorities = &priority;
    VkDeviceCreateInfo device_info = {};
    device_info.sType = VK_STRUCTURE_TYPE_DEVICE_CREATE_INFO;
    device_info.queueCreateInfoCount = 1;
    device_info.pQueueCreateInfos = &queue_info;
    auto create_device = reinterpret_cast<PFN_vkCreateDevice>(gipa(instance, "vkCreateDevice"));
    if (create_device(physical, &device_info, nullptr, &device) != VK_SUCCESS) {
        return false;
    }
    gdpa = reinterpret_cast<PFN_vkGetDeviceProcAddr>(gipa(instance, "vkGetDeviceProcAddr"));
    device_fn<PFN_vkGetDeviceQueue>("vkGetDeviceQueue")(device, family, 0, &queue);
    return true;
}

uint32_t memory_type(VulkanContext& context, uint32_t bits, VkMemoryPropertyFlags wanted) {
    auto properties_fn = reinterpret_cast<PFN_vkGetPhysicalDeviceMemoryProperties>(
        context.gipa(context.instance, "vkGetPhysicalDeviceMemoryProperties"));
    VkPhysicalDeviceMemoryProperties properties = {};
    properties_fn(context.physical, &properties);
    for (uint32_t index = 0; index < properties.memoryTypeCount; ++index) {
        if ((bits & (1u << index)) && (properties.memoryTypes[index].propertyFlags & wanted) == wanted) {
            return index;
        }
    }
    return UINT32_MAX;
}

// One time command buffer, submitted & waited
template <class Record>
void vulkan_submit(VulkanContext& context, Record&& record) {
    VkCommandPool pool = VK_NULL_HANDLE;
    VkCommandPoolCreateInfo pool_info = {};
    pool_info.sType = VK_STRUCTURE_TYPE_COMMAND_POOL_CREATE_INFO;
    pool_info.queueFamilyIndex = context.family;
    context.device_fn<PFN_vkCreateCommandPool>("vkCreateCommandPool")(context.device, &pool_info, nullptr, &pool);
    VkCommandBufferAllocateInfo allocate = {};
    allocate.sType = VK_STRUCTURE_TYPE_COMMAND_BUFFER_ALLOCATE_INFO;
    allocate.commandPool = pool;
    allocate.level = VK_COMMAND_BUFFER_LEVEL_PRIMARY;
    allocate.commandBufferCount = 1;
    VkCommandBuffer command = VK_NULL_HANDLE;
    context.device_fn<PFN_vkAllocateCommandBuffers>("vkAllocateCommandBuffers")(context.device, &allocate, &command);
    VkCommandBufferBeginInfo begin = {};
    begin.sType = VK_STRUCTURE_TYPE_COMMAND_BUFFER_BEGIN_INFO;
    context.device_fn<PFN_vkBeginCommandBuffer>("vkBeginCommandBuffer")(command, &begin);
    record(command);
    context.device_fn<PFN_vkEndCommandBuffer>("vkEndCommandBuffer")(command);
    VkSubmitInfo submit = {};
    submit.sType = VK_STRUCTURE_TYPE_SUBMIT_INFO;
    submit.commandBufferCount = 1;
    submit.pCommandBuffers = &command;
    context.device_fn<PFN_vkQueueSubmit>("vkQueueSubmit")(context.queue, 1, &submit, VK_NULL_HANDLE);
    context.device_fn<PFN_vkQueueWaitIdle>("vkQueueWaitIdle")(context.queue);
    context.device_fn<PFN_vkDestroyCommandPool>("vkDestroyCommandPool")(context.device, pool, nullptr);
}

void image_barrier(VulkanContext& context, VkCommandBuffer command, VkImage image, VkImageLayout from, VkImageLayout to) {
    VkImageMemoryBarrier barrier = {};
    barrier.sType = VK_STRUCTURE_TYPE_IMAGE_MEMORY_BARRIER;
    barrier.srcAccessMask = VK_ACCESS_MEMORY_WRITE_BIT;
    barrier.dstAccessMask = VK_ACCESS_MEMORY_READ_BIT | VK_ACCESS_MEMORY_WRITE_BIT;
    barrier.oldLayout = from;
    barrier.newLayout = to;
    barrier.srcQueueFamilyIndex = VK_QUEUE_FAMILY_IGNORED;
    barrier.dstQueueFamilyIndex = VK_QUEUE_FAMILY_IGNORED;
    barrier.image = image;
    barrier.subresourceRange = {VK_IMAGE_ASPECT_COLOR_BIT, 0, 1, 0, 1};
    context.device_fn<PFN_vkCmdPipelineBarrier>("vkCmdPipelineBarrier")(
        command, VK_PIPELINE_STAGE_ALL_COMMANDS_BIT, VK_PIPELINE_STAGE_ALL_COMMANDS_BIT, 0, 0, nullptr, 0, nullptr, 1, &barrier);
}

VkImage VulkanContext::create_image(const XrSwapchainCreateInfo& info, VkDeviceMemory& memory) {
    VkImageCreateInfo image_info = {};
    image_info.sType = VK_STRUCTURE_TYPE_IMAGE_CREATE_INFO;
    image_info.imageType = VK_IMAGE_TYPE_2D;
    image_info.format = static_cast<VkFormat>(info.format);
    image_info.extent = {info.width, info.height, 1};
    image_info.mipLevels = 1;
    image_info.arrayLayers = 1;
    image_info.samples = VK_SAMPLE_COUNT_1_BIT;
    image_info.tiling = VK_IMAGE_TILING_OPTIMAL;
    image_info.usage = VK_IMAGE_USAGE_COLOR_ATTACHMENT_BIT | VK_IMAGE_USAGE_SAMPLED_BIT |
                       VK_IMAGE_USAGE_TRANSFER_DST_BIT | VK_IMAGE_USAGE_TRANSFER_SRC_BIT;
    image_info.initialLayout = VK_IMAGE_LAYOUT_UNDEFINED;
    VkImage image = VK_NULL_HANDLE;
    if (device_fn<PFN_vkCreateImage>("vkCreateImage")(device, &image_info, nullptr, &image) != VK_SUCCESS) {
        return VK_NULL_HANDLE;
    }
    VkMemoryRequirements requirements = {};
    device_fn<PFN_vkGetImageMemoryRequirements>("vkGetImageMemoryRequirements")(device, image, &requirements);
    VkMemoryAllocateInfo allocate = {};
    allocate.sType = VK_STRUCTURE_TYPE_MEMORY_ALLOCATE_INFO;
    allocate.allocationSize = requirements.size;
    allocate.memoryTypeIndex = memory_type(*this, requirements.memoryTypeBits, 0);
    device_fn<PFN_vkAllocateMemory>("vkAllocateMemory")(device, &allocate, nullptr, &memory);
    device_fn<PFN_vkBindImageMemory>("vkBindImageMemory")(device, image, memory, 0);
    // OpenXR: image in COLOR_ATTACHMENT_OPTIMAL when given to the application
    vulkan_submit(*this, [&](VkCommandBuffer command) {
        image_barrier(*this, command, image, VK_IMAGE_LAYOUT_UNDEFINED, VK_IMAGE_LAYOUT_COLOR_ATTACHMENT_OPTIMAL);
    });
    return image;
}

void VulkanContext::destroy_image(VkImage image, VkDeviceMemory memory) {
    device_fn<PFN_vkQueueWaitIdle>("vkQueueWaitIdle")(queue);
    device_fn<PFN_vkDestroyImage>("vkDestroyImage")(device, image, nullptr);
    device_fn<PFN_vkFreeMemory>("vkFreeMemory")(device, memory, nullptr);
}

std::vector<uint8_t> VulkanContext::read(VkImage image, uint32_t width, uint32_t height) {
    std::vector<uint8_t> pixels;
    device_fn<PFN_vkQueueWaitIdle>("vkQueueWaitIdle")(queue);  // layer copy finished
    VkBufferCreateInfo buffer_info = {};
    buffer_info.sType = VK_STRUCTURE_TYPE_BUFFER_CREATE_INFO;
    buffer_info.size = static_cast<VkDeviceSize>(width) * height * 4u;
    buffer_info.usage = VK_BUFFER_USAGE_TRANSFER_DST_BIT;
    VkBuffer buffer = VK_NULL_HANDLE;
    device_fn<PFN_vkCreateBuffer>("vkCreateBuffer")(device, &buffer_info, nullptr, &buffer);
    VkMemoryRequirements requirements = {};
    device_fn<PFN_vkGetBufferMemoryRequirements>("vkGetBufferMemoryRequirements")(device, buffer, &requirements);
    VkMemoryAllocateInfo allocate = {};
    allocate.sType = VK_STRUCTURE_TYPE_MEMORY_ALLOCATE_INFO;
    allocate.allocationSize = requirements.size;
    allocate.memoryTypeIndex = memory_type(*this, requirements.memoryTypeBits,
                                           VK_MEMORY_PROPERTY_HOST_VISIBLE_BIT | VK_MEMORY_PROPERTY_HOST_COHERENT_BIT);
    VkDeviceMemory memory = VK_NULL_HANDLE;
    device_fn<PFN_vkAllocateMemory>("vkAllocateMemory")(device, &allocate, nullptr, &memory);
    device_fn<PFN_vkBindBufferMemory>("vkBindBufferMemory")(device, buffer, memory, 0);
    vulkan_submit(*this, [&](VkCommandBuffer command) {
        image_barrier(*this, command, image, VK_IMAGE_LAYOUT_COLOR_ATTACHMENT_OPTIMAL, VK_IMAGE_LAYOUT_TRANSFER_SRC_OPTIMAL);
        VkBufferImageCopy region = {};
        region.imageSubresource = {VK_IMAGE_ASPECT_COLOR_BIT, 0, 0, 1};
        region.imageExtent = {width, height, 1};
        device_fn<PFN_vkCmdCopyImageToBuffer>("vkCmdCopyImageToBuffer")(
            command, image, VK_IMAGE_LAYOUT_TRANSFER_SRC_OPTIMAL, buffer, 1, &region);
        image_barrier(*this, command, image, VK_IMAGE_LAYOUT_TRANSFER_SRC_OPTIMAL, VK_IMAGE_LAYOUT_COLOR_ATTACHMENT_OPTIMAL);
    });
    void* mapped = nullptr;
    if (device_fn<PFN_vkMapMemory>("vkMapMemory")(device, memory, 0, buffer_info.size, 0, &mapped) == VK_SUCCESS) {
        pixels.assign(static_cast<uint8_t*>(mapped), static_cast<uint8_t*>(mapped) + buffer_info.size);
        device_fn<PFN_vkUnmapMemory>("vkUnmapMemory")(device, memory);
    }
    device_fn<PFN_vkDestroyBuffer>("vkDestroyBuffer")(device, buffer, nullptr);
    device_fn<PFN_vkFreeMemory>("vkFreeMemory")(device, memory, nullptr);
    return pixels;
}

void VulkanContext::destroy() {
    if (device != VK_NULL_HANDLE) {
        device_fn<PFN_vkDestroyDevice>("vkDestroyDevice")(device, nullptr);
    }
    if (instance != VK_NULL_HANDLE) {
        reinterpret_cast<PFN_vkDestroyInstance>(gipa(instance, "vkDestroyInstance"))(instance, nullptr);
    }
}

// -----------------------------------------------------------------------------------------------------------
// Layer as seen by the OpenXR loader

struct Layer {
    HMODULE module = nullptr;
    PFN_xrNegotiateLoaderApiLayerInterface negotiate = nullptr;
    XrNegotiateApiLayerRequest request = {};
    XrInstance instance = XR_NULL_HANDLE;
    PFN_xrGetInstanceProcAddr gipa = nullptr;

    template <class T>
    T get(const char* name) {
        PFN_xrVoidFunction function = nullptr;
        if (XR_FAILED(gipa(instance, name, &function))) {
            return nullptr;
        }
        return reinterpret_cast<T>(function);
    }
};

XrNegotiateLoaderInfo loader_info() {
    XrNegotiateLoaderInfo info = {};
    info.structType = XR_LOADER_INTERFACE_STRUCT_LOADER_INFO;
    info.structVersion = XR_LOADER_INFO_STRUCT_VERSION;
    info.structSize = sizeof(XrNegotiateLoaderInfo);
    info.minInterfaceVersion = 1;
    info.maxInterfaceVersion = XR_CURRENT_LOADER_API_LAYER_VERSION;
    info.minApiVersion = XR_MAKE_VERSION(1, 0, 0);
    info.maxApiVersion = XR_MAKE_VERSION(1, 0x3ff, 0xfff);
    return info;
}

XrNegotiateApiLayerRequest layer_request() {
    XrNegotiateApiLayerRequest request = {};
    request.structType = XR_LOADER_INTERFACE_STRUCT_API_LAYER_REQUEST;
    request.structVersion = XR_API_LAYER_INFO_STRUCT_VERSION;
    request.structSize = sizeof(XrNegotiateApiLayerRequest);
    return request;
}

bool load_layer(const char* path, Layer& layer) {
    layer.module = LoadLibraryA(path);
    if (layer.module == nullptr) {
        std::printf("cannot load %s (error %lu)\n", path, GetLastError());
        return false;
    }
    layer.negotiate = reinterpret_cast<PFN_xrNegotiateLoaderApiLayerInterface>(
        reinterpret_cast<void*>(GetProcAddress(layer.module, "xrNegotiateLoaderApiLayerInterface")));
    if (layer.negotiate == nullptr) {
        std::printf("xrNegotiateLoaderApiLayerInterface not exported\n");
        return false;
    }
    std::printf("negotiation\n");
    XrNegotiateLoaderInfo info = loader_info();
    XrNegotiateApiLayerRequest request = layer_request();
    CHECK(layer.negotiate(&info, "XR_APILAYER_OTHER_name", &request) == XR_ERROR_INITIALIZATION_FAILED);
    XrNegotiateLoaderInfo bad = info;
    bad.structSize = 4;
    CHECK(layer.negotiate(&bad, "XR_APILAYER_TINYPEDAL_overlay", &request) == XR_ERROR_INITIALIZATION_FAILED);
    CHECK(layer.negotiate(nullptr, "XR_APILAYER_TINYPEDAL_overlay", &request) == XR_ERROR_INITIALIZATION_FAILED);
    XrNegotiateLoaderInfo old_loader = info;  // loader of OpenXR 1.0 games
    old_loader.maxApiVersion = XR_MAKE_VERSION(1, 0, 9);
    request = layer_request();
    CHECK(layer.negotiate(&old_loader, "XR_APILAYER_TINYPEDAL_overlay", &request) == XR_SUCCESS);
    CHECK(request.layerApiVersion == XR_MAKE_VERSION(1, 0, 0));
    request = layer_request();
    CHECK(layer.negotiate(&info, "XR_APILAYER_TINYPEDAL_overlay", &request) == XR_SUCCESS);
    CHECK(request.getInstanceProcAddr != nullptr && request.createApiLayerInstance != nullptr);
    CHECK(request.layerInterfaceVersion == 1);
    layer.request = request;
    layer.gipa = request.getInstanceProcAddr;

    XrApiLayerNextInfo next = {};
    next.structType = XR_LOADER_INTERFACE_STRUCT_API_LAYER_NEXT_INFO;
    next.structVersion = XR_API_LAYER_NEXT_INFO_STRUCT_VERSION;
    next.structSize = sizeof(next);
    const char layer_name[] = "XR_APILAYER_TINYPEDAL_overlay";
    std::memcpy(next.layerName, layer_name, sizeof(layer_name));
    next.nextGetInstanceProcAddr = rt_xrGetInstanceProcAddr;
    next.nextCreateApiLayerInstance = rt_xrCreateApiLayerInstance;
    XrApiLayerCreateInfo create = {};
    create.structType = XR_LOADER_INTERFACE_STRUCT_API_LAYER_CREATE_INFO;
    create.structVersion = XR_API_LAYER_CREATE_INFO_STRUCT_VERSION;
    create.structSize = sizeof(create);
    create.nextInfo = &next;
    XrInstanceCreateInfo instance_info = {};
    instance_info.type = XR_TYPE_INSTANCE_CREATE_INFO;
    CHECK(request.createApiLayerInstance(&instance_info, &create, &layer.instance) == XR_SUCCESS);
    // Hooked functions given back, others forwarded unchanged
    CHECK(layer.get<PFN_xrEndFrame>("xrEndFrame") != rt_xrEndFrame && layer.get<PFN_xrEndFrame>("xrEndFrame") != nullptr);
    CHECK(layer.get<PFN_xrAcquireSwapchainImage>("xrAcquireSwapchainImage") == rt_xrAcquireSwapchainImage);
    PFN_xrVoidFunction unknown = nullptr;
    CHECK(layer.gipa(layer.instance, "xrUnknownFunction", &unknown) == XR_ERROR_FUNCTION_UNSUPPORTED && unknown == nullptr);
    return failures == 0;
}

// -----------------------------------------------------------------------------------------------------------

// Game frame with one projection layer, or none (loading, session not visible)
uint32_t end_frame(Layer& layer, XrSession session, uint32_t layer_count = 1) {
    static const XrCompositionLayerProjection projection = [] {
        XrCompositionLayerProjection value = {};
        value.type = XR_TYPE_COMPOSITION_LAYER_PROJECTION;
        return value;
    }();
    const XrCompositionLayerBaseHeader* layers[] = {reinterpret_cast<const XrCompositionLayerBaseHeader*>(&projection)};
    XrFrameEndInfo info = {};
    info.type = XR_TYPE_FRAME_END_INFO;
    info.displayTime = 1;
    info.environmentBlendMode = XR_ENVIRONMENT_BLEND_MODE_OPAQUE;
    info.layerCount = layer_count;
    info.layers = layer_count != 0 ? layers : nullptr;
    const XrResult result = layer.get<PFN_xrEndFrame>("xrEndFrame")(session, &info);
    CHECK(result == XR_SUCCESS);
    return runtime.submitted_counts.empty() ? 0 : runtime.submitted_counts.back();
}

FakeSwapchain* quad_swapchain() {
    auto found = runtime.swapchains.find(runtime.last_quad.subImage.swapchain);
    return found != runtime.swapchains.end() ? found->second : nullptr;
}

std::vector<uint8_t> read_released(FakeSwapchain* swapchain) {
    const int index = swapchain->last_released;
    if (index < 0) {
        return {};
    }
    if (runtime.api == Api::D3D11) {
        return read_d3d11(swapchain->d3d11[static_cast<size_t>(index)]);
    }
    if (runtime.api == Api::D3D12) {
        return read_d3d12(swapchain->d3d12[static_cast<size_t>(index)], swapchain->info.width, swapchain->info.height);
    }
    return runtime.vulkan->read(swapchain->vulkan[static_cast<size_t>(index)], swapchain->info.width, swapchain->info.height);
}

double srgb_to_linear(int value) {
    const double srgb = value / 255.0;
    return srgb <= 0.04045 ? srgb / 12.92 : std::pow((srgb + 0.055) / 1.055, 2.4);
}

// Pixel (x, y) of swapchain image compared with app image (format order & color encoding)
void check_pixels(const std::vector<uint8_t>& pixels, uint32_t swapchain_width, uint32_t width, uint32_t height, bool bgra,
                  bool linear) {
    CHECK(!pixels.empty());
    if (pixels.empty()) {
        return;
    }
    int wrong = 0;
    for (uint32_t y = 0; y < height; ++y) {
        for (uint32_t x = 0; x < width; ++x) {
            const uint8_t* pixel = pixels.data() + (static_cast<size_t>(y) * swapchain_width + x) * 4u;
            int expected[4] = {static_cast<int>(x * 10u % 256u), static_cast<int>(y * 10u % 256u), 100, 200};
            if (linear) {
                for (int channel = 0; channel < 3; ++channel) {
                    expected[channel] = static_cast<int>(std::lround(srgb_to_linear(expected[channel]) * 255.0));
                }
            }
            const int red = bgra ? pixel[2] : pixel[0];
            const int blue = bgra ? pixel[0] : pixel[2];
            if (red != expected[0] || pixel[1] != expected[1] || blue != expected[2] || pixel[3] != expected[3]) {
                if (wrong++ == 0) {
                    std::printf("  pixel %u,%u = %d %d %d %d, expected %d %d %d %d\n", x, y, red, pixel[1], blue, pixel[3],
                                expected[0], expected[1], expected[2], expected[3]);
                }
            }
        }
    }
    // Transparent border right & bottom (bilinear filtering of the image edge)
    for (uint32_t y = 0; y <= height; ++y) {
        if (pixels[(static_cast<size_t>(y) * swapchain_width + width) * 4u + 3u] != 0) {
            ++wrong;
        }
    }
    CHECK(wrong == 0);
}

XrSession create_session(Layer& layer, const void* binding) {
    XrSessionCreateInfo info = {};
    info.type = XR_TYPE_SESSION_CREATE_INFO;
    info.next = binding;
    info.systemId = 1;
    XrSession session = XR_NULL_HANDLE;
    CHECK(layer.get<PFN_xrCreateSession>("xrCreateSession")(layer.instance, &info, &session) == XR_SUCCESS);
    return session;
}

void destroy_session(Layer& layer, XrSession session) {
    CHECK(layer.get<PFN_xrDestroySession>("xrDestroySession")(session) == XR_SUCCESS);
    CHECK(runtime.swapchains.empty());  // layer swapchain destroyed
    CHECK(runtime.spaces_alive == 0);
}

// Full scenario on one graphics API
void run_scenario(Layer& layer, App& app, const void* binding, uint32_t api_id, bool bgra, bool linear) {
    runtime.submitted_counts.clear();
    runtime.order_error = false;
    runtime.refuse_extra_layers = false;
    TpvrHeader& header = app.header();
    header.layer_heartbeat_ms = 0;
    header.layer_state = 0;

    app.write(30, 12, true, false);
    XrSession session = create_session(layer, binding);
    // First image read during a frame without layers (session starting): uploaded on next frame with layers
    CHECK(end_frame(layer, session, 0) == 0);
    CHECK(end_frame(layer, session) == 2);  // overlay quad appended
    const XrCompositionLayerQuad& quad = runtime.last_quad;
    CHECK(quad.type == XR_TYPE_COMPOSITION_LAYER_QUAD);
    CHECK(quad.space == runtime.local_space);  // seated placement
    CHECK(quad.layerFlags == (XR_COMPOSITION_LAYER_BLEND_TEXTURE_SOURCE_ALPHA_BIT | XR_COMPOSITION_LAYER_UNPREMULTIPLIED_ALPHA_BIT));
    CHECK(quad.subImage.imageRect.extent.width == 30 && quad.subImage.imageRect.extent.height == 12);
    CHECK(std::fabs(quad.size.width - 0.5f) < 1e-6f && std::fabs(quad.size.height - 0.2f) < 1e-6f);
    CHECK(quad.pose.position.x == 0.125f && quad.pose.position.y == -0.25f && quad.pose.position.z == -1.25f);
    CHECK(quad.pose.orientation.w == 1.0f);
    FakeSwapchain* swapchain = quad_swapchain();
    CHECK(swapchain != nullptr);
    if (swapchain == nullptr) {
        return;
    }
    CHECK(swapchain->info.width == 64 && swapchain->info.height == 64);
    CHECK(swapchain->acquire_count == 1);
    check_pixels(read_released(swapchain), swapchain->info.width, 30, 12, bgra, linear);
    // Status written back for the app
    CHECK(header.layer_state == TPVR_LAYER_ACTIVE && header.layer_graphics_api == api_id);
    CHECK(header.layer_pid == GetCurrentProcessId() && header.layer_heartbeat_ms != 0);
    CHECK(header.layer_version == TPVR_VERSION);

    // Unchanged image: no upload, quad still submitted
    app.heartbeat();
    CHECK(end_frame(layer, session) == 2);
    CHECK(swapchain->acquire_count == 1);
    CHECK(header.layer_frames_shown >= 1);

    // New image, attached to headset
    app.write(20, 10, true, true);
    CHECK(end_frame(layer, session) == 2);
    CHECK(runtime.last_quad.space == runtime.view_space);
    CHECK(runtime.last_quad.subImage.imageRect.extent.width == 20);
    CHECK(swapchain->acquire_count == 2);
    check_pixels(read_released(swapchain), swapchain->info.width, 20, 10, bgra, linear);

    // New image read during a frame without layers (game loading): not lost, uploaded on next frame
    app.write(24, 10, true, true);
    CHECK(end_frame(layer, session, 0) == 0);
    CHECK(swapchain->acquire_count == 2);
    CHECK(end_frame(layer, session) == 2);
    CHECK(runtime.last_quad.subImage.imageRect.extent.width == 24);
    CHECK(swapchain->acquire_count == 3);
    check_pixels(read_released(swapchain), swapchain->info.width, 24, 10, bgra, linear);

    // Bigger image: swapchain created again
    app.write(100, 40, true, true);
    CHECK(end_frame(layer, session) == 2);
    swapchain = quad_swapchain();
    CHECK(swapchain != nullptr && swapchain->info.width == 128 && swapchain->info.height == 64);
    if (swapchain != nullptr) {
        check_pixels(read_released(swapchain), swapchain->info.width, 100, 40, bgra, linear);
    }

    // Hidden: game frame unchanged
    app.write(100, 40, false, true);
    CHECK(end_frame(layer, session) == 1);
    app.write(100, 40, true, true);
    CHECK(end_frame(layer, session) == 2);

    // App gone (no heartbeat for more than the timeout): game frame unchanged
    header.app_heartbeat_ms = GetTickCount64() - TPVR_APP_TIMEOUT_MS - 100;
    CHECK(end_frame(layer, session) == 1);
    app.heartbeat();
    CHECK(end_frame(layer, session) == 2);

    // Invalid header written by app: game frame unchanged
    header.sequence += 2;
    header.width = 1000000;
    CHECK(end_frame(layer, session) == 1);
    app.write(100, 40, true, true);
    CHECK(end_frame(layer, session) == 2);

    // App writing (odd sequence): last image kept
    header.sequence += 1;
    CHECK(end_frame(layer, session) == 2);
    header.sequence += 1;

    // Runtime refuses the quad: frame submitted again unchanged, overlay stopped for session
    runtime.refuse_extra_layers = true;
    const size_t calls = runtime.submitted_counts.size();
    CHECK(end_frame(layer, session) == 1);
    CHECK(runtime.submitted_counts.size() == calls + 2);
    CHECK(end_frame(layer, session) == 1);
    CHECK(header.layer_state == TPVR_LAYER_FAILED && header.layer_last_result == XR_ERROR_LAYER_INVALID);
    runtime.refuse_extra_layers = false;
    CHECK(!runtime.order_error);

    destroy_session(layer, session);
    CHECK(header.layer_heartbeat_ms == 0);  // no session any more
}

}  // namespace

int main(int argc, char** argv) {
    if (argc < 2) {
        std::printf("usage: layer_harness <TinyPedalXrLayer.dll>\n");
        return 2;
    }
    App app;
    if (!app.open()) {
        std::printf("cannot create shared memory\n");
        return 1;
    }
    Layer layer;
    if (!load_layer(argv[1], layer)) {
        std::printf("FAILED: layer load\n");
        return 1;
    }
    int skipped = 0;

    // D3D11 (LMU, rF2): sRGB RGBA format preferred, then BGRA without sRGB (swizzle & linear colors)
    ID3D11Device* d3d11 = nullptr;
    for (D3D_DRIVER_TYPE type : {D3D_DRIVER_TYPE_HARDWARE, D3D_DRIVER_TYPE_WARP}) {
        if (SUCCEEDED(D3D11CreateDevice(nullptr, type, nullptr, 0, nullptr, 0, D3D11_SDK_VERSION, &d3d11, nullptr, nullptr))) {
            break;
        }
        d3d11 = nullptr;
    }
    if (d3d11 != nullptr) {
        runtime.api = Api::D3D11;
        runtime.d3d11 = d3d11;
        XrGraphicsBindingD3D11KHR binding = {};
        binding.type = XR_TYPE_GRAPHICS_BINDING_D3D11_KHR;
        binding.device = d3d11;
        std::printf("D3D11 (R8G8B8A8_UNORM_SRGB)\n");
        runtime.formats = {DXGI_FORMAT_B8G8R8A8_UNORM_SRGB, DXGI_FORMAT_R8G8B8A8_UNORM_SRGB, DXGI_FORMAT_R10G10B10A2_UNORM};
        run_scenario(layer, app, &binding, TPVR_GRAPHICS_D3D11, false, false);
        std::printf("D3D11 (B8G8R8A8_UNORM)\n");
        runtime.formats = {DXGI_FORMAT_R16G16B16A16_FLOAT, DXGI_FORMAT_B8G8R8A8_UNORM};
        run_scenario(layer, app, &binding, TPVR_GRAPHICS_D3D11, true, true);
    } else {
        std::printf("D3D11: SKIPPED (no device)\n");
        ++skipped;
    }

    // D3D12
    ID3D12Device* d3d12 = nullptr;
    if (FAILED(D3D12CreateDevice(nullptr, D3D_FEATURE_LEVEL_11_0, __uuidof(ID3D12Device), reinterpret_cast<void**>(&d3d12)))) {
        d3d12 = nullptr;
        IDXGIFactory4* factory = nullptr;
        IDXGIAdapter* warp = nullptr;
        if (SUCCEEDED(CreateDXGIFactory1(__uuidof(IDXGIFactory4), reinterpret_cast<void**>(&factory))) &&
            SUCCEEDED(factory->EnumWarpAdapter(__uuidof(IDXGIAdapter), reinterpret_cast<void**>(&warp))) &&
            FAILED(D3D12CreateDevice(warp, D3D_FEATURE_LEVEL_11_0, __uuidof(ID3D12Device), reinterpret_cast<void**>(&d3d12)))) {
            d3d12 = nullptr;
        }
    }
    if (d3d12 != nullptr) {
        D3D12_COMMAND_QUEUE_DESC queue_desc = {};
        queue_desc.Type = D3D12_COMMAND_LIST_TYPE_DIRECT;
        d3d12->CreateCommandQueue(&queue_desc, __uuidof(ID3D12CommandQueue), reinterpret_cast<void**>(&g_d3d12_queue));
        runtime.api = Api::D3D12;
        runtime.d3d12 = d3d12;
        runtime.formats = {DXGI_FORMAT_R8G8B8A8_UNORM_SRGB};
        XrGraphicsBindingD3D12KHR binding = {};
        binding.type = XR_TYPE_GRAPHICS_BINDING_D3D12_KHR;
        binding.device = d3d12;
        binding.queue = g_d3d12_queue;
        std::printf("D3D12 (R8G8B8A8_UNORM_SRGB)\n");
        run_scenario(layer, app, &binding, TPVR_GRAPHICS_D3D12, false, false);
    } else {
        std::printf("D3D12: SKIPPED (no device)\n");
        ++skipped;
    }

    // Vulkan
    VulkanContext vulkan;
    if (vulkan.create()) {
        runtime.api = Api::Vulkan;
        runtime.vulkan = &vulkan;
        runtime.formats = {VK_FORMAT_B8G8R8A8_SRGB, VK_FORMAT_R8G8B8A8_SRGB};
        XrGraphicsBindingVulkanKHR binding = {};
        binding.type = XR_TYPE_GRAPHICS_BINDING_VULKAN_KHR;
        binding.instance = vulkan.instance;
        binding.physicalDevice = vulkan.physical;
        binding.device = vulkan.device;
        binding.queueFamilyIndex = vulkan.family;
        binding.queueIndex = 0;
        std::printf("Vulkan (R8G8B8A8_SRGB)\n");
        run_scenario(layer, app, &binding, TPVR_GRAPHICS_VULKAN, false, false);
    } else {
        std::printf("Vulkan: SKIPPED (no device)\n");
        ++skipped;
    }

    // OpenGL: pure pass-through, reported as unsupported
    {
        std::printf("OpenGL (pass-through)\n");
        runtime.submitted_counts.clear();
        XrBaseInStructure binding = {};  // XrGraphicsBindingOpenGLWin32KHR (OpenGL headers not needed)
        binding.type = XR_TYPE_GRAPHICS_BINDING_OPENGL_WIN32_KHR;
        app.write(30, 12, true, false);
        XrSession session = create_session(layer, &binding);
        CHECK(end_frame(layer, session) == 1);
        CHECK(app.header().layer_state == TPVR_LAYER_UNSUPPORTED);
        CHECK(app.header().layer_graphics_api == TPVR_GRAPHICS_OPENGL);
        destroy_session(layer, session);
    }

    // App closed (mapping gone): pass-through
    {
        std::printf("No app (pass-through)\n");
        if (d3d11 != nullptr) {
            runtime.api = Api::D3D11;
            runtime.formats = {DXGI_FORMAT_R8G8B8A8_UNORM_SRGB};
            app.header().app_heartbeat_ms = 0;
            XrGraphicsBindingD3D11KHR binding = {};
            binding.type = XR_TYPE_GRAPHICS_BINDING_D3D11_KHR;
            binding.device = d3d11;
            XrSession session = create_session(layer, &binding);
            CHECK(end_frame(layer, session) == 1);
            destroy_session(layer, session);
        }
    }

    CHECK(layer.get<PFN_xrDestroyInstance>("xrDestroyInstance")(layer.instance) == XR_SUCCESS);
    vulkan.destroy();
    app.close();
    if (failures != 0) {
        std::printf("%d check(s) failed\n", failures);
        return 1;
    }
    std::printf("layer_harness: all checks passed (%d graphics API skipped)\n", skipped);
    return 0;
}
