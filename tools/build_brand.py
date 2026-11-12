"""Render the approved connected DC monogram; no font files are redistributed."""

from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

ROOT = Path(__file__).resolve().parents[1]
ASSETS = ROOT / "dc_assistant" / "assets"
NAVY = "#142746"
WHITE = "#F3F7FC"
CYAN = "#60CFE6"


def monogram(size):
    scale = 4
    side = size * scale
    image = Image.new("RGBA", (side, side))
    draw = ImageDraw.Draw(image)
    draw.rounded_rectangle((0, 0, side - 1, side - 1), radius=side * 0.20, fill=NAVY)
    font = ImageFont.truetype(r"C:\Windows\Fonts\segoeuib.ttf", round(side * 0.45))
    spacing = side * 0.095
    width_d = font.getlength("D")
    width_c = font.getlength("C")
    layout_width = width_d + width_c - spacing * 2
    x = (side - side * 0.08 - layout_width) / 2
    bounds = font.getbbox("DC")
    y = (side - (bounds[3] - bounds[1])) / 2 - bounds[1]
    draw.text((x, y), "D", font=font, fill=WHITE)
    draw.text((x + width_d - spacing, y), "C", font=font, fill=CYAN)
    return image.resize((size, size), Image.Resampling.LANCZOS)


def main():
    ASSETS.mkdir(parents=True, exist_ok=True)
    for size in (16, 24, 32, 48, 64, 80, 96, 128, 256):
        monogram(size).save(ASSETS / f"dc-{size}.png")
    monogram(256).save(
        ASSETS / "dc-assistant.ico",
        sizes=[(size, size) for size in (16, 24, 32, 48, 64, 128, 256)],
    )
    canvas = Image.new("RGBA", (410, 96))
    canvas.alpha_composite(monogram(80), (0, 8))
    draw = ImageDraw.Draw(canvas)
    font = ImageFont.truetype(r"C:\Windows\Fonts\segoeuib.ttf", 30)
    draw.text((100, 14), "DC Assistant", font=font, fill=WHITE)
    small = ImageFont.truetype(r"C:\Windows\Fonts\segoeui.ttf", 11)
    x = 101
    for character in "DOCUMENT CONTROL":
        draw.text((x, 60), character, font=small, fill="#B9C8DE")
        x += small.getlength(character) + 2
    canvas.save(ASSETS / "dc-logo.png")
    installer = ROOT / "installer" / "assets"
    installer.mkdir(parents=True, exist_ok=True)
    sidebar = Image.new("RGB", (164, 314), "#0B1426")
    sidebar.paste(monogram(96), (34, 58), monogram(96))
    label = ImageDraw.Draw(sidebar)
    label_font = ImageFont.truetype(r"C:\Windows\Fonts\segoeuib.ttf", 17)
    label.text((82, 176), "DC Assistant", font=label_font, fill=WHITE, anchor="mt")
    label_font = ImageFont.truetype(r"C:\Windows\Fonts\segoeui.ttf", 10)
    label.text(
        (82, 205), "DOCUMENT CONTROL", font=label_font, fill="#B9C8DE", anchor="mt"
    )
    sidebar.save(installer / "sidebar.bmp")


if __name__ == "__main__":
    main()
