"""Write the drop shadow 9-patch of QML pages (neopedal/ui/qml/components/shadow.png, drawn by TpShadow.qml)

Black rounded rectangle blurred by a Gaussian: alpha 1 under the surface, fading to 0 at REACH pixels outside it.
TpShadow scales it (theme.shadowExtent / REACH) and sets its opacity (theme.shadowOpacity): one static picture,
no shader & no layer. Run again only to change its shape: python tools/gen_shadow.py
"""

import math
import os
import sys

REACH = 32  # blur reach outside the surface (pixels of the picture)
RADIUS = 16  # corner radius of the surface
BORDER = REACH + RADIUS  # 9-patch border (TpShadow.qml): corners, then a stretched middle strip
SIZE = 2 * BORDER + 2
OUTPUT = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                      "neopedal", "ui", "qml", "components", "shadow.png")


def inside(x: float, y: float) -> float:
    """Coverage at pixel center (x, y) of a surface filling everything right of & below its rounded top left
    corner (REACH, REACH): 1 inside, 0 outside, anti-aliased edge"""
    cx, cy = max(x, REACH + RADIUS), max(y, REACH + RADIUS)
    distance = math.hypot(x - cx, y - cy) - RADIUS
    if x < REACH or y < REACH:
        distance = max(distance, 0.5)
    return min(max(0.5 - distance, 0.0), 1.0)


def corner() -> list[list[float]]:
    """Alpha of the top left corner (BORDER + 1 pixels square): the surface corner blurred by a separable Gaussian
    (sigma: reach / 3), the surface going on past the canvas (a straight edge of a large surface, not a small box)"""
    size = BORDER + REACH + 1
    sigma = REACH / 3
    kernel = [math.exp(-(offset * offset) / (2 * sigma * sigma)) for offset in range(-REACH, REACH + 1)]
    total = sum(kernel)
    kernel = [weight / total for weight in kernel]
    mask = [[inside(x + 0.5, y + 0.5) for x in range(size)] for y in range(size)]

    def blur(line: list[float]) -> list[float]:  # past the far end: same as the last pixel (surface goes on)
        return [sum(weight * line[min(max(i + k - REACH, 0), size - 1)] for k, weight in enumerate(kernel))
                for i in range(size)]

    rows = [blur(row) for row in mask]
    columns = [blur([rows[y][x] for y in range(size)]) for x in range(size)]
    return [[columns[x][y] for x in range(BORDER + 1)] for y in range(BORDER + 1)]


def blurred() -> list[list[float]]:
    """Alpha of every pixel: corner mirrored to the 4 corners, its last row & column stretched between them"""
    quarter = corner()

    def index(i: int) -> int:
        return min(i, SIZE - 1 - i, BORDER)

    return [[quarter[index(y)][index(x)] for x in range(SIZE)] for y in range(SIZE)]


def main() -> int:
    from PySide6.QtGui import QColor, QGuiApplication, QImage

    app = QGuiApplication.instance() or QGuiApplication([*sys.argv[:1], "-platform", "offscreen"])
    image = QImage(SIZE, SIZE, QImage.Format.Format_ARGB32)
    for y, row in enumerate(blurred()):
        for x, alpha in enumerate(row):
            image.setPixelColor(x, y, QColor(0, 0, 0, round(alpha * 255)))
    saved = image.save(OUTPUT, "PNG")
    print(("Written " if saved else "Not written ") + OUTPUT)
    del app
    return 0 if saved else 1


if __name__ == "__main__":
    sys.exit(main())
