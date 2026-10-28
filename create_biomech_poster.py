import os
import math
import random
from PIL import Image, ImageDraw, ImageFont, ImageFilter

W, H = 1200, 704
FONT_DIR = r"C:\Users\soren\.gemini\config\plugins\anthropic-skills\skills\canvas-design\canvas-fonts"
V8_MEDIA = r"C:\Users\soren\.gemini\antigravity\scratch\phnoe-web-app\examples\soren-motion-v8\public\media"
HERO_MEDIA = r"C:\Users\soren\.gemini\antigravity\scratch\phnoe-web-app\motion-source\biomechanical-hero"

os.makedirs(V8_MEDIA, exist_ok=True)
os.makedirs(HERO_MEDIA, exist_ok=True)

def get_font(name, size):
    path = os.path.join(FONT_DIR, name)
    try:
        return ImageFont.truetype(path, size)
    except Exception as e:
        return ImageFont.load_default()

font_title = get_font("PoiretOne-Regular.ttf", 36)
font_sub = get_font("Jura-Medium.ttf", 15)
font_mono_bold = get_font("GeistMono-Bold.ttf", 12)
font_mono = get_font("GeistMono-Regular.ttf", 11)
font_mono_small = get_font("GeistMono-Regular.ttf", 9)

# Colors
BG = (6, 9, 14, 255)
CYAN = (56, 189, 248, 255)
GOLD = (222, 188, 128, 255)
WHITE = (245, 248, 252, 255)
MID = (70, 88, 120, 220)
GRID = (26, 35, 52, 150)
ROSE = (244, 63, 94, 255)

img = Image.new("RGBA", (W, H), BG)

# 1. Atmospheric Volumetric Light Cone
cone = Image.new("RGBA", (W, H), (0, 0, 0, 0))
c_draw = ImageDraw.Draw(cone, "RGBA")
cx, cy = W // 2, H // 2 + 30
for r in range(540, 20, -15):
    alpha = int(28 * (1.0 - (r / 540.0)) ** 1.8)
    c_draw.ellipse([cx - r * 1.4, cy - r * 0.9, cx + r * 1.4, cy + r * 0.9], fill=(12, 24, 45, alpha))
cone = cone.filter(ImageFilter.GaussianBlur(radius=8))
img = Image.alpha_composite(img, cone)

draw = ImageDraw.Draw(img, "RGBA")

# 2. Structural Ground Grid in Perspective
y_horizon = 260
for x in range(0, W + 1, 80):
    draw.line([(cx, y_horizon), (x, H)], fill=GRID, width=1)
for y_g in range(y_horizon + 20, H, 35):
    draw.line([(0, y_g), (W, y_g)], fill=GRID, width=1)

# 3. Holographic Digital Twin Kinematic Chain
# Robotic Serial Link (Arm) + Anatomical Knee Pivot
links = [
    (cx - 260, cy + 140), # Base
    (cx - 180, cy + 40),  # Joint 1
    (cx - 90, cy - 60),   # Joint 2 (Shoulder)
    (cx + 20, cy - 20),   # Joint 3 (Elbow)
    (cx + 120, cy + 30),  # Joint 4 (Wrist)
    (cx + 190, cy + 60)   # End-Effector / Contact
]

# Draw glow trail
glow_layer = Image.new("RGBA", (W, H), (0, 0, 0, 0))
g_draw = ImageDraw.Draw(glow_layer, "RGBA")
for i in range(len(links) - 1):
    g_draw.line([links[i], links[i+1]], fill=(56, 189, 248, 140), width=6)
glow_layer = glow_layer.filter(ImageFilter.GaussianBlur(radius=4))
img = Image.alpha_composite(img, glow_layer)
draw = ImageDraw.Draw(img, "RGBA")

# Crisp link geometry
for i in range(len(links) - 1):
    draw.line([links[i], links[i+1]], fill=WHITE, width=2)
    # Joint hubs
    p = links[i]
    draw.ellipse([p[0] - 10, p[1] - 10, p[0] + 10, p[1] + 10], outline=CYAN, width=2)
    draw.ellipse([p[0] - 4, p[1] - 4, p[0] + 4, p[1] + 4], fill=GOLD)
    draw.text((p[0] + 12, p[1] - 8), f"J{i+1}", font=font_mono_small, fill=CYAN)

# Terminal End-Effector Target
ee = links[-1]
draw.ellipse([ee[0] - 16, ee[1] - 16, ee[0] + 16, ee[1] + 16], outline=ROSE, width=2)
draw.ellipse([ee[0] - 5, ee[1] - 5, ee[0] + 5, ee[1] + 5], fill=WHITE)
draw.line([(ee[0] - 24, ee[1]), (ee[0] + 24, ee[1])], fill=ROSE, width=1)
draw.line([(ee[0], ee[1] - 24), (ee[0], ee[1] + 24)], fill=ROSE, width=1)
draw.text((ee[0] + 20, ee[1] - 8), "END-EFFECTOR · CONTACT", font=font_mono_bold, fill=ROSE)

# Anatomical Knee Articulation Contours (Femur & Tibia silhouette lines)
# Femoral Condyle Curve
f_pts = []
for deg in range(120, 310, 5):
    rad = math.radians(deg)
    fx = ee[0] + 40 + 75 * math.cos(rad)
    fy = ee[1] - 10 + 95 * math.sin(rad)
    f_pts.append((fx, fy))
for i in range(len(f_pts) - 1):
    draw.line([f_pts[i], f_pts[i+1]], fill=GOLD, width=2)
draw.text((ee[0] + 115, ee[1] - 90), "FEMORAL CONDYLE", font=font_mono_small, fill=GOLD)

# Tibial Plateau Surface Line
draw.line([(ee[0] - 20, ee[1] + 75), (ee[0] + 160, ee[1] + 75)], fill=WHITE, width=2)
draw.text((ee[0] + 30, ee[1] + 85), "TIBIAL PLATEAU", font=font_mono_small, fill=WHITE)

# Instantaneous Helical Axis (IHA) arrow
draw.line([(ee[0] + 40, ee[1] - 10), (ee[0] + 90, ee[1] - 45)], fill=CYAN, width=2)
draw.text((ee[0] + 95, ee[1] - 48), "IHA VECTOR", font=font_mono_small, fill=CYAN)

# 4. Anamorphic Horizontal Flare
flare = Image.new("RGBA", (W, H), (0, 0, 0, 0))
fl_draw = ImageDraw.Draw(flare, "RGBA")
fl_draw.line([(0, cy), (W, cy)], fill=(56, 189, 248, 60), width=2)
fl_draw.line([(cx - 200, cy), (cx + 200, cy)], fill=(245, 248, 252, 140), width=3)
flare = flare.filter(ImageFilter.GaussianBlur(radius=2))
img = Image.alpha_composite(img, flare)
draw = ImageDraw.Draw(img, "RGBA")

# 5. Cinematic HUD & Telemetry Overlays
# Letterbox border lines
draw.line([(40, 40), (W - 40, 40)], fill=MID, width=1)
draw.line([(40, H - 40), (W - 40, H - 40)], fill=MID, width=1)

# Top Left: Recording Status
draw.ellipse([50, 52, 60, 62], fill=ROSE)
draw.text((68, 51), "REC ● 1440p60", font=font_mono_bold, fill=WHITE)
draw.text((175, 51), "|  SHUTTER: 180°  |  TC 00:14:24:00  |  FRAME 0540 / 0900", font=font_mono, fill=MID)

# Top Right: Production Tag
draw.text((W - 380, 51), "SOREN MOTION LAB · REHABILITATION ROBOTICS", font=font_mono, fill=GOLD)

# Bottom Left: Telemetry Matrix
draw.text((50, H - 95), "TELEMETRY: DUAL-ACTUATION SYNCHRONIZATION", font=font_mono_bold, fill=CYAN)
draw.text((50, H - 76), "SAGITTAL ICR: +3.2mm  |  TORQUE: 18.4 Nm  |  ANGULAR VEL: 1.42 rad/s", font=font_mono, fill=WHITE)
draw.text((50, H - 58), "7-DOF SERVO STATE: CONVERGENT [LYAPUNOV λ < 0]", font=font_mono_small, fill=MID)

# Bottom Right: Attribution Notice
draw.text((W - 430, H - 76), "NVIDIA SIMREADY & BODYPARTS3D DIGITAL TWIN", font=font_mono_bold, fill=WHITE)
draw.text((W - 430, H - 58), "CC BY 4.0 ATTRIBUTION · DBCLS & NVIDIA CENTRAL", font=font_mono_small, fill=GOLD)

# Center Title Overlay (Watermark)
title_str = "B I O M E C H A N I C A L   C Y B E R N E T I C   L A B"
tb = font_title.getbbox(title_str)
draw.text(((W - (tb[2] - tb[0])) // 2, 85), title_str, font=font_title, fill=WHITE)
sub_str = "1440P60 CINEMATIC HERO FILM · REMOTION & HYPERFRAMES"
sb = font_sub.getbbox(sub_str)
draw.text(((W - (sb[2] - sb[0])) // 2, 126), sub_str, font=font_sub, fill=CYAN)

# Save Posters
p1 = os.path.join(V8_MEDIA, "biomech-poster.png")
p2 = os.path.join(HERO_MEDIA, "poster.png")
img.save(p1, format="PNG")
img.save(p2, format="PNG")

print(f"Generated hero poster saved to:\n  - {p1}\n  - {p2}")
