"""生成应用图标 app/resources/icon.ico（需要 Pillow）。"""
from __future__ import annotations

from pathlib import Path

from PIL import Image, ImageDraw

OUT_DIR = Path(__file__).resolve().parent.parent / "app" / "resources"
SIZE = 256


def rounded_gradient() -> Image.Image:
    """圆角矩形 + 竖直渐变底板。"""
    import math

    img = Image.new("RGBA", (SIZE, SIZE), (0, 0, 0, 0))
    grad = Image.new("RGBA", (SIZE, SIZE))
    top, bottom = (79, 172, 254), (0, 90, 200)
    px = grad.load()
    for y in range(SIZE):
        t = y / (SIZE - 1)
        r = round(top[0] + (bottom[0] - top[0]) * t)
        g = round(top[1] + (bottom[1] - top[1]) * t)
        b = round(top[2] + (bottom[2] - top[2]) * t)
        for x in range(SIZE):
            px[x, y] = (r, g, b, 255)
    mask = Image.new("L", (SIZE, SIZE), 0)
    ImageDraw.Draw(mask).rounded_rectangle([8, 8, SIZE - 8, SIZE - 8], radius=52, fill=255)
    img.paste(grad, (0, 0), mask)
    return img


def draw_glyph(img: Image.Image) -> None:
    d = ImageDraw.Draw(img)
    white = (255, 255, 255, 255)
    w = 18

    # 向下箭头：竖杆 + 三角头
    d.rounded_rectangle([118, 52, 138, 132], radius=10, fill=white)
    d.polygon([(84, 122), (172, 122), (128, 180)], fill=white)

    # 托盘（开口的盒子）
    tray_y_top, tray_y_bot = 186, 214
    d.rounded_rectangle([60, tray_y_top - 6, 92, tray_y_bot], radius=9, fill=white)
    d.rounded_rectangle([164, tray_y_top - 6, 196, tray_y_bot], radius=9, fill=white)
    d.rounded_rectangle([60, tray_y_bot - 18, 196, tray_y_bot], radius=9, fill=white)


def main() -> None:
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    img = rounded_gradient()
    draw_glyph(img)
    img.save(OUT_DIR / "icon.png")
    img.save(OUT_DIR / "icon.ico",
             sizes=[(256, 256), (128, 128), (64, 64), (48, 48), (32, 32), (24, 24), (16, 16)])
    print("icon written to", OUT_DIR)


if __name__ == "__main__":
    main()
