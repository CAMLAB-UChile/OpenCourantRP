"""Generate resources/icon.png and icon.ico (Windows fonts required; the outputs are committed)."""

from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

OUT = Path(__file__).resolve().parents[1] / "src" / "opencourantrp" / "resources"
S = 1024  # work large, downscale for quality
FONT = r"C:\Windows\Fonts\GOTHIC.TTF"  # Century Gothic: geometric, close to the OpenCourantLab icon


def lerp(a, b, t):
    return tuple(round(a[i] + (b[i] - a[i]) * t) for i in range(3))


def vertical_gradient(size, top, bottom):
    col = Image.new("RGB", (1, size))
    for y in range(size):
        col.putpixel((0, y), lerp(top, bottom, y / (size - 1)))
    return col.resize((size, size))


def text_mask(text, font, box_w, y_center):
    """Mask with `text` stretched by tracking to fill box_w, centred vertically on y_center."""
    m = Image.new("L", (S, S), 0)
    d = ImageDraw.Draw(m)
    widths = [d.textlength(ch, font=font) for ch in text]
    gap = (box_w - sum(widths)) / (len(text) - 1)
    x = (S - box_w) / 2
    for ch, w in zip(text, widths):
        bb = d.textbbox((0, 0), ch, font=font)
        y = y_center - (bb[1] + bb[3]) / 2
        d.text((x, y), ch, font=font, fill=255)
        x += w + gap
    return m


def ink_box(ch, font):
    """Visible (left, top, right, bottom) of a glyph relative to its drawing origin."""
    m = Image.new("L", (S, S), 0)
    ImageDraw.Draw(m).text((200, 200), ch, font=font, fill=255)
    l, t, r, b = m.point(lambda v: 255 if v > 127 else 0).getbbox()
    return (l - 200, t - 200, r - 200, b - 200)


def ink_mask(text, font, ink_gap, y_center):
    """Mask with the glyphs' visible edges `ink_gap` apart, centred horizontally on the icon."""
    m = Image.new("L", (S, S), 0)
    d = ImageDraw.Draw(m)
    boxes = [ink_box(ch, font) for ch in text]
    total = sum(b[2] - b[0] for b in boxes) + ink_gap * (len(text) - 1)
    x = (S - total) / 2
    for ch, bb in zip(text, boxes):
        d.text((x - bb[0], y_center - (bb[1] + bb[3]) / 2), ch, font=font, fill=255)
        x += bb[2] - bb[0] + ink_gap
    global RP_SPAN
    RP_SPAN = ((S - total) / 2, total)
    return m


RP_SPAN = (0, S)


def build() -> Image.Image:
    bg = vertical_gradient(S, (0x2A, 0x3A, 0x57), (0x12, 0x1A, 0x2B))
    corner = Image.new("L", (S, S), 0)
    ImageDraw.Draw(corner).rounded_rectangle((56, 56, S - 56, S - 56), radius=200, fill=255)
    img = Image.new("RGBA", (S, S), (0, 0, 0, 0))
    img.paste(bg, (0, 0), corner)

    font = ImageFont.truetype(FONT, 410)
    box_w = 640
    d = ImageDraw.Draw(Image.new("L", (S, S)))
    # ink gap between O and C as laid out by text_mask (negative = they overlap)
    wO, wC = d.textlength("O", font=font), d.textlength("C", font=font)
    gap = (box_w - wO - wC)
    o_right = (S - box_w) / 2 + ink_box("O", font)[2]
    c_left = (S - box_w) / 2 + wO + gap + ink_box("C", font)[0]
    ink_gap = 0  # R and P just touch, like O and C
    # "OC" in off-white
    white = Image.new("RGB", (S, S), (0xE8, 0xEB, 0xF0))
    img.paste(white, (0, 0), text_mask("OC", font, box_w, 363))
    # "RP" with the blue -> teal horizontal gradient of the original "LAB"
    rp = ink_mask("RP", font, ink_gap, 691)
    grad = Image.new("RGB", (S, S))
    for x in range(S):
        t = min(max((x - RP_SPAN[0]) / RP_SPAN[1], 0), 1)
        c = lerp((0x4B, 0xA0, 0xFD), (0x37, 0xD4, 0xC6), t)
        for y in range(0, S, S):  # one column at a time
            grad.paste(c, (x, 0, x + 1, S))
    img.paste(grad, (0, 0), rp)
    return img


if __name__ == "__main__":
    img = build()
    OUT.mkdir(parents=True, exist_ok=True)
    img.resize((256, 256), Image.LANCZOS).save(OUT / "icon.png")
    img.save(OUT / "icon.ico", sizes=[(16, 16), (24, 24), (32, 32), (48, 48), (64, 64), (128, 128), (256, 256)])
    print("wrote", OUT / "icon.png", OUT / "icon.ico")
