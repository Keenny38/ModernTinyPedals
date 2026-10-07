# Modern Tiny Pedals OpenXR overlay layer (implicit API layer, Windows x64)
#
# Build (Windows, Visual Studio 2022 or Build Tools, from the repository root):
#   cmake -S native/openxr_layer -B native/openxr_layer/build -A x64
#   cmake --build native/openxr_layer/build --config Release
# Output: native/openxr_layer/build/bin/TinyPedalXrLayer.dll & TinyPedalXrLayer.json, found there by the app
# when run from source, bundled in lib/openxr_layer by build_pyinstaller.py.
#
# Unit tests of the platform neutral parts (any OS, run by CI on Linux):
#   cmake -S native/openxr_layer -B build-tests -DTPVR_BUILD_LAYER=OFF -DTPVR_BUILD_TESTS=ON
#   cmake --build build-tests && ctest --test-dir build-tests --output-on-failure
#
# Headers only (nothing linked): OpenXR-SDK & Vulkan-Headers fetched at pinned commits. Offline build:
# -DFETCHCONTENT_SOURCE_DIR_OPENXR_SDK=<path> -DFETCHCONTENT_SOURCE_DIR_VULKAN_HEADERS=<path>

cmake_minimum_required(VERSION 3.24)
project(TinyPedalXrLayer VERSION 1.0.0 LANGUAGES CXX)

if(WIN32)
    set(_tpvr_layer_default ON)
else()
    set(_tpvr_layer_default OFF)
endif()
option(TPVR_BUILD_LAYER "Build the OpenXR layer DLL (Windows only)" ${_tpvr_layer_default})
option(TPVR_BUILD_TESTS "Build unit tests of the shared memory reader" OFF)

set(CMAKE_CXX_STANDARD 17)
set(CMAKE_CXX_STANDARD_REQUIRED ON)
set(CMAKE_CXX_EXTENSIONS OFF)
# Static C/C++ runtime: the DLL loads in any game without Visual C++ redistributable
set(CMAKE_MSVC_RUNTIME_LIBRARY "MultiThreaded$<$<CONFIG:Debug>:Debug>")

if(MSVC)
    set(TPVR_WARNINGS /W4 /WX /permissive- /EHsc /utf-8)
else()
    set(TPVR_WARNINGS -Wall -Wextra -Wpedantic -Wshadow -Wconversion -Wno-sign-conversion -Werror)
endif()

add_library(tpvr_shared_frame STATIC src/shared_frame.cpp)
target_include_directories(tpvr_shared_frame PUBLIC include src)
target_compile_options(tpvr_shared_frame PRIVATE ${TPVR_WARNINGS})
set_target_properties(tpvr_shared_frame PROPERTIES POSITION_INDEPENDENT_CODE ON)

if(TPVR_BUILD_LAYER)
    if(NOT WIN32)
        message(FATAL_ERROR "TPVR_BUILD_LAYER: Windows only (or a MinGW-w64 cross toolchain)")
    endif()
    if(NOT CMAKE_SIZEOF_VOID_P EQUAL 8)
        message(FATAL_ERROR "TinyPedalXrLayer: 64-bit build only (games are 64-bit, manifest has one library)")
    endif()

    include(FetchContent)
    # SOURCE_SUBDIR without CMakeLists.txt: sources downloaded only, nothing built
    FetchContent_Declare(openxr_sdk
        GIT_REPOSITORY https://github.com/KhronosGroup/OpenXR-SDK.git
        GIT_TAG f2448a8797c85814aa892efc1ab8707900fbcc78  # release-1.1.63
        SOURCE_SUBDIR headers-only)
    FetchContent_Declare(vulkan_headers
        GIT_REPOSITORY https://github.com/KhronosGroup/Vulkan-Headers.git
        GIT_TAG 6802bb4733b63ed5efd3adb308a6c885ef180ea1  # vulkan-sdk-1.4.363.0
        SOURCE_SUBDIR headers-only)
    FetchContent_MakeAvailable(openxr_sdk vulkan_headers)

    add_library(TinyPedalXrLayer SHARED
        src/layer.cpp
        src/graphics_d3d11.cpp
        src/graphics_d3d12.cpp
        src/graphics_vulkan.cpp)
    target_include_directories(TinyPedalXrLayer SYSTEM PRIVATE
        ${openxr_sdk_SOURCE_DIR}/include
        ${vulkan_headers_SOURCE_DIR}/include)
    target_link_libraries(TinyPedalXrLayer PRIVATE tpvr_shared_frame)
    target_compile_options(TinyPedalXrLayer PRIVATE ${TPVR_WARNINGS})
    target_compile_definitions(TinyPedalXrLayer PRIVATE UNICODE _UNICODE)
    if(MINGW)
        # No libstdc++ / libgcc / winpthread DLL next to the layer
        target_link_options(TinyPedalXrLayer PRIVATE -static -static-libgcc -static-libstdc++)
    endif()
    # Same folder for every configuration ($<0:> removes the per-config subfolder of multi-config generators)
    set(TPVR_OUTPUT_DIR ${CMAKE_BINARY_DIR}/bin)
    set_target_properties(TinyPedalXrLayer PROPERTIES
        PREFIX ""
        RUNTIME_OUTPUT_DIRECTORY ${TPVR_OUTPUT_DIR}$<0:>
        LIBRARY_OUTPUT_DIRECTORY ${TPVR_OUTPUT_DIR}$<0:>)
    add_custom_command(TARGET TinyPedalXrLayer POST_BUILD
        COMMAND ${CMAKE_COMMAND} -E copy_if_different
            ${CMAKE_CURRENT_SOURCE_DIR}/TinyPedalXrLayer.json ${TPVR_OUTPUT_DIR}/TinyPedalXrLayer.json)

    if(TPVR_BUILD_TESTS)
        # Fake OpenXR runtime driving the DLL with real D3D11 / D3D12 / Vulkan devices (skipped when missing)
        add_executable(layer_harness tests/layer_harness.cpp)
        target_include_directories(layer_harness SYSTEM PRIVATE
            ${openxr_sdk_SOURCE_DIR}/include
            ${vulkan_headers_SOURCE_DIR}/include)
        target_include_directories(layer_harness PRIVATE include)
        target_compile_options(layer_harness PRIVATE ${TPVR_WARNINGS})
        target_link_libraries(layer_harness PRIVATE d3d11 d3d12 dxgi)
        if(MINGW)
            target_link_options(layer_harness PRIVATE -static -static-libgcc -static-libstdc++)
        endif()
        add_test(NAME layer_harness COMMAND layer_harness $<TARGET_FILE:TinyPedalXrLayer>)
    endif()
endif()

if(TPVR_BUILD_TESTS)
    enable_testing()
    add_executable(shared_frame_test tests/shared_frame_test.cpp)
    target_link_libraries(shared_frame_test PRIVATE tpvr_shared_frame)
    target_compile_options(shared_frame_test PRIVATE ${TPVR_WARNINGS})
    if(MINGW)
        target_link_options(shared_frame_test PRIVATE -static -static-libgcc -static-libstdc++)
    endif()
    add_test(NAME shared_frame_test COMMAND shared_frame_test)
endif()
