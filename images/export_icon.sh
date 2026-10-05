#!/bin/bash
echo -e "Export TinyPedal icon, require ImageMagick v7.0+\n"

# Export app icons as ICO & PNG (raster source): icon (light theme), icon_dark (dark theme)
SIZE_ICO="16,24,32,48,64,128,256"
SIZE_APP_PNG="256x256"

for SOURCE_APP in src/icon.webp src/icon_dark.webp; do
    [ -f "${SOURCE_APP}" ] || continue
    echo -e "SOURCE: $(magick identify ${SOURCE_APP})"
    EXPORT_ICO="$(basename ${SOURCE_APP} .webp).ico"
    EXPORT_APP_PNG="$(basename ${SOURCE_APP} .webp).png"
    magick -background none "${SOURCE_APP}" \
        -filter lanczos -define icon:auto-resize="${SIZE_ICO}" \
        "${EXPORT_ICO}"
    echo -e "EXPORT: ${EXPORT_ICO} (${SIZE_ICO})"
    magick -background none "${SOURCE_APP}" \
        -filter lanczos -resize "${SIZE_APP_PNG}" \
        -define png:compression-level=9 \
        -define png:exclude-chunk=all \
        "${EXPORT_APP_PNG}"
    echo -e "EXPORT: ${EXPORT_APP_PNG} (${SIZE_APP_PNG})\n"
done

# Export other icons as PNG-8
for SOURCE_SVG in src/*.svg; do
    echo "SOURCE: $(magick identify ${SOURCE_SVG})"
    EXPORT_PNG="$(basename ${SOURCE_SVG} .svg).png"
    magick -format png -depth 8 \
        -define png:compression-level=9 \
        -define png:exclude-chunk=all \
        -background none \
        "${SOURCE_SVG}" "${EXPORT_PNG}"
    echo -e "EXPORT: ${EXPORT_PNG}\n"
done
