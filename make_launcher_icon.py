"""Create a high-contrast, multi-resolution KineLab PT Windows shortcut icon."""
import math
from pathlib import Path

from PIL import Image, ImageDraw, ImageFilter

BASE = Path(__file__).resolve().parent
SIZE = 1024
OUT = BASE / "assets"
OUT.mkdir(exist_ok=True)

# Carefully scaled dark, rounded app tile with a subtle deep-cyan highlight.
tile = Image.new("RGBA", (SIZE, SIZE))
px = tile.load()
if px is None:
    raise RuntimeError("Pillow returned no pixel access for the new icon tile")
for y in range(SIZE):
    for x in range(SIZE):
        illumination = max(0.0, 1 - math.hypot((x - 270) / 850, (y - 190) / 870))
        px[x, y] = (
            round(9 + illumination * 19),
            round(14 + illumination * 31),
            round(25 + illumination * 47),
            255,
        )
mask = Image.new("L", (SIZE, SIZE), 0)
md = ImageDraw.Draw(mask)
md.rounded_rectangle((38, 38, 986, 986), radius=225, fill=255)
tile.putalpha(mask)

base = Image.new("RGBA", (SIZE, SIZE), (0, 0, 0, 0))
base.alpha_composite(tile)
d = ImageDraw.Draw(base, "RGBA")
d.rounded_rectangle((40, 40, 984, 984), radius=223, outline=(87, 194, 212, 100), width=8)
d.arc((122, 135, 920, 925), start=238, end=44, fill=(60, 155, 178, 47), width=9)
d.arc((177, 192, 854, 867), start=56, end=230, fill=(74, 205, 218, 41), width=7)

# Luminous pose/keypoint-inspired K mark remains clear at 32px.
strokes = [
    ((308, 266), (308, 764)),
    ((340, 515), (685, 245)),
    ((342, 512), (704, 780)),
]
glow = Image.new("RGBA", (SIZE, SIZE), (0, 0, 0, 0))
g = ImageDraw.Draw(glow, "RGBA")
for pts in strokes:
    g.line(pts, fill=(9, 234, 246, 205), width=67, joint="curve")
for p in ((308, 266), (308, 764), (685, 245), (704, 780), (342, 512)):
    g.ellipse((p[0] - 40, p[1] - 40, p[0] + 40, p[1] + 40), fill=(17, 250, 249, 240))
base.alpha_composite(glow.filter(ImageFilter.GaussianBlur(radius=30)))

d = ImageDraw.Draw(base, "RGBA")
for pts in strokes:
    d.line(pts, fill=(6, 127, 157, 255), width=83, joint="curve")
    d.line(pts, fill=(79, 238, 243, 255), width=52, joint="curve")
    d.line(pts, fill=(186, 254, 251, 215), width=13, joint="curve")
for p in ((308, 266), (308, 764), (685, 245), (704, 780), (342, 512)):
    d.ellipse((p[0] - 35, p[1] - 35, p[0] + 35, p[1] + 35), fill=(7, 55, 79, 255))
    d.ellipse((p[0] - 25, p[1] - 25, p[0] + 25, p[1] + 25), fill=(177, 253, 250, 255))
# Three tiny orange motion markers make the symbol recognizable among dark app icons.
for x, y, radius in ((789, 367, 8), (802, 397, 7), (798, 427, 6)):
    d.ellipse((x - radius, y - radius, x + radius, y + radius), fill=(245, 168, 110, 205))

png = OUT / "kinelab-pt-icon.png"
ico = OUT / "kinelab-pt.ico"
base.save(png)
base.save(ico, sizes=[(16,16), (24,24), (32,32), (48,48), (64,64), (128,128), (256,256)])
print(f"ICON_PNG={png}")
print(f"ICON_ICO={ico}")
