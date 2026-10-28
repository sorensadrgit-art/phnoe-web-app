import os
import math
import random
from PIL import Image, ImageDraw, ImageFont, ImageFilter
from reportlab.pdfgen import canvas as pdf_canvas

# Directories
OUT_DIR = r"C:\Users\soren\.gemini\antigravity\scratch\phnoe-web-app\artifacts"
BRAIN_DIR = r"C:\Users\soren\.gemini\antigravity\brain\495c71cb-e3c9-445b-aa12-946a7641450f"
FONT_DIR = r"C:\Users\soren\.gemini\config\plugins\anthropic-skills\skills\canvas-design\canvas-fonts"

os.makedirs(OUT_DIR, exist_ok=True)
os.makedirs(BRAIN_DIR, exist_ok=True)

# Canvas Dimensions: High-Res Fine Art Folio (2700 x 3600 at 300 DPI)
W, H = 2700, 3600

# Color Palette (Dark Luxury / Obsidian Mathematical Conservatory)
BG_OBSIDIAN = (6, 8, 12, 255)           # Deep obsidian ground
GRID_HAIRLINE = (24, 32, 48, 140)       # Structural grid
SUBTLE_LINE = (36, 48, 70, 180)         # Minor concentric and tangent rays
MID_LINE = (65, 84, 116, 210)           # Structural armatures & dials
BRIGHT_LINE = (165, 188, 218, 240)      # High-order geometry
WHITE = (245, 248, 252, 255)            # Primary focal lines & typography
CYAN_ACCENT = (56, 189, 248, 255)       # Luminescent electric cobalt / cyan
CYAN_DEEP = (14, 116, 144, 255)         # Deep cyan support
GOLD_ACCENT = (222, 188, 128, 255)      # Muted celestial gold / bronze
GOLD_MUTED = (180, 150, 95, 160)        # Muted gold line
ROSE_ACCENT = (244, 63, 94, 210)        # Kinematic torque limit indicator

# Load TrueType Typography
def get_font(name, size):
    path = os.path.join(FONT_DIR, name)
    try:
        return ImageFont.truetype(path, size)
    except Exception as e:
        print(f"Font load fallback for {name}: {e}")
        return ImageFont.load_default()

font_title = get_font("PoiretOne-Regular.ttf", 54)
font_subtitle = get_font("Jura-Light.ttf", 22)
font_heading = get_font("Jura-Medium.ttf", 20)
font_body = get_font("Jura-Light.ttf", 15)
font_mono_bold = get_font("GeistMono-Bold.ttf", 14)
font_mono = get_font("GeistMono-Regular.ttf", 13)
font_mono_small = get_font("GeistMono-Regular.ttf", 11)
font_mono_micro = get_font("GeistMono-Regular.ttf", 9)
font_serif_italic = get_font("CrimsonPro-Italic.ttf", 17)

print("PASS 2: Initializing pristine fine art canvas...")
base_img = Image.new("RGBA", (W, H), BG_OBSIDIAN)

# 1. Atmospheric Gradient & Optical Centering
print("Synthesizing multi-tier atmospheric luminance field...")
lum_layer = Image.new("RGBA", (W, H), (0, 0, 0, 0))
lum_draw = ImageDraw.Draw(lum_layer, "RGBA")

CX, CY = W // 2, 1560
max_r = 1380
for r in range(max_r, 80, -30):
    factor = 1.0 - (r / max_r)
    alpha = int(24 * (factor ** 2.0))
    lum_draw.ellipse(
        [CX - r, CY - r, CX + r, CY + r],
        fill=(12, 22, 40, alpha)
    )
base_img = Image.alpha_composite(base_img, lum_layer)

draw = ImageDraw.Draw(base_img, "RGBA")

# 2. Archival Framing & Millimeter Graduation
print("Constructing archival borders and precision calibration scales...")
M_LEFT, M_RIGHT = 140, W - 140
M_TOP, M_BOTTOM = 140, H - 140

# Outer double hairline border
draw.rectangle([M_LEFT, M_TOP, M_RIGHT, M_BOTTOM], outline=MID_LINE, width=2)
draw.rectangle([M_LEFT + 16, M_TOP + 16, M_RIGHT - 16, M_BOTTOM - 16], outline=SUBTLE_LINE, width=1)

# Corner Registration Marks
def draw_reg_mark(cx, cy):
    sz = 26
    draw.line([(cx - sz, cy), (cx + sz, cy)], fill=BRIGHT_LINE, width=1)
    draw.line([(cx, cy - sz), (cx, cy + sz)], fill=BRIGHT_LINE, width=1)
    draw.ellipse([cx - 8, cy - 8, cx + 8, cy + 8], outline=GOLD_ACCENT, width=1)
    draw.ellipse([cx - 15, cy - 15, cx + 15, cy + 15], outline=SUBTLE_LINE, width=1)

draw_reg_mark(M_LEFT, M_TOP)
draw_reg_mark(M_RIGHT, M_TOP)
draw_reg_mark(M_LEFT, M_BOTTOM)
draw_reg_mark(M_RIGHT, M_BOTTOM)

# Millimeter tick marks along perimeter
for x in range(M_LEFT + 40, M_RIGHT - 30, 10):
    delta = x - M_LEFT
    t_len = 8 if delta % 100 == 0 else (5 if delta % 50 == 0 else 2)
    col = WHITE if delta % 100 == 0 else SUBTLE_LINE
    draw.line([(x, M_TOP), (x, M_TOP + t_len)], fill=col, width=1)
    draw.line([(x, M_BOTTOM), (x, M_BOTTOM - t_len)], fill=col, width=1)
    if delta % 200 == 0 and x < M_RIGHT - 80:
        val_str = f"{delta // 10:03d}"
        draw.text((x - 8, M_TOP + 10), val_str, font=font_mono_micro, fill=MID_LINE)

for y in range(M_TOP + 40, M_BOTTOM - 30, 10):
    delta = y - M_TOP
    t_len = 8 if delta % 100 == 0 else (5 if delta % 50 == 0 else 2)
    col = WHITE if delta % 100 == 0 else SUBTLE_LINE
    draw.line([(M_LEFT, y), (M_LEFT + t_len, y)], fill=col, width=1)
    draw.line([(M_RIGHT, y), (M_RIGHT - t_len, y)], fill=col, width=1)
    if delta % 200 == 0 and y < M_BOTTOM - 80:
        val_str = f"{delta // 10:03d}"
        draw.text((M_LEFT + 10, y - 5), val_str, font=font_mono_micro, fill=MID_LINE)

# 3. Header Architecture & Plate Identification
print("Rendering typographic plate header and provenance coordinates...")
draw.line([(M_LEFT + 24, 380), (M_RIGHT - 24, 380)], fill=MID_LINE, width=1)
draw.line([(M_LEFT + 24, 384), (M_RIGHT - 24, 384)], fill=GRID_HAIRLINE, width=1)

# Header Left Block
draw.text((M_LEFT + 32, 195), "PLATE NO. VIII · TRANSLATION GEOMETRY", font=font_mono_bold, fill=GOLD_ACCENT)
draw.text((M_LEFT + 32, 220), "SPECIMEN: DPT-2028 · ARTICULATED KINEMATICS", font=font_mono, fill=WHITE)
draw.text((M_LEFT + 32, 245), "DATUM: 40°01'14\"N  75°09'22\"W [GLENSIDE TERRESTRIAL]", font=font_mono_small, fill=MID_LINE)
draw.text((M_LEFT + 32, 268), "INSTRUMENTATION: 7-DOF SERIAL MANIFOLD × RIEMANNIAN PHASE SPACE", font=font_mono_small, fill=MID_LINE)
draw.text((M_LEFT + 32, 290), "METRIC TENSOR: g_ij = J_i^T(q) M(q) J_j(q) · INVARIANT TORSION", font=font_mono_small, fill=CYAN_ACCENT)

# Header Center Title (Calculated Precise Optical Alignment)
title_text = "K I N E M A T I C   M O N I S M"
bbox = font_title.getbbox(title_text)
tw = bbox[2] - bbox[0]
draw.text(((W - tw) // 2, 205), title_text, font=font_title, fill=WHITE)

sub_text = "THE SPATIAL GEOMETRY OF ARTICULATED MANIFOLDS"
s_bbox = font_subtitle.getbbox(sub_text)
sw = s_bbox[2] - s_bbox[0]
draw.text(((W - sw) // 2, 272), sub_text, font=font_subtitle, fill=GOLD_ACCENT)

sub_meta = "A HARMONIC SYNTHESIS OF HUMAN BIOMECHANICS & INDUSTRIAL ROBOTIC DEGREES OF FREEDOM"
sm_bbox = font_mono_small.getbbox(sub_meta)
smw = sm_bbox[2] - sm_bbox[0]
draw.text(((W - smw) // 2, 310), sub_meta, font=font_mono_small, fill=MID_LINE)

# Header Right Block
draw.text((M_RIGHT - 390, 195), "SYSTEM METRIC: SO(3) × SE(3)", font=font_mono_bold, fill=CYAN_ACCENT)
draw.text((M_RIGHT - 390, 220), "DEGREE OF FREEDOM: 07 [q₁..q₇]", font=font_mono, fill=WHITE)
draw.text((M_RIGHT - 390, 245), "ANGULAR ENVELOPE: 0.00° → 135.24°", font=font_mono_small, fill=MID_LINE)
draw.text((M_RIGHT - 390, 268), "VELOCITY VECTOR: θ̇(t) ∈ C²[0, T]", font=font_mono_small, fill=MID_LINE)
draw.text((M_RIGHT - 390, 290), "STATUS: VERIFIED MATHEMATICAL STUDY", font=font_mono_small, fill=GOLD_ACCENT)

# 4. Central Astrolabe & Epicycloid Mandala
# Pass 2: R_outer scaled to 720px for flawless 80px breathing margins to left/right columns
print("Constructing calibrated central astrolabe with flawless breathing margins...")
R_OUTER = 720
R_NODES = 670
rings = [720, 670, 600, 520, 440, 360, 270, 180, 90, 45]

for r in rings:
    col = WHITE if r in [720, 440, 45] else (CYAN_ACCENT if r == 600 else (GOLD_MUTED if r == 360 else GRID_HAIRLINE))
    w = 2 if r in [720, 440] else 1
    draw.ellipse([CX - r, CY - r, CX + r, CY + r], outline=col, width=w)

# 360-Degree Vernier Dial on Outer Ring (R = 720)
for deg in range(360):
    rad = math.radians(deg)
    cos_a, sin_a = math.cos(rad), math.sin(rad)
    
    if deg % 30 == 0:
        r_in = 696
        col = WHITE
        w = 2
        label_str = f"{deg:03d}°"
        lr = 746
        lx = CX + lr * cos_a
        ly = CY + lr * sin_a
        t_box = font_mono_micro.getbbox(label_str)
        tw, th = t_box[2] - t_box[0], t_box[3] - t_box[1]
        draw.text((lx - tw / 2, ly - th / 2), label_str, font=font_mono_micro, fill=GOLD_ACCENT)
    elif deg % 5 == 0:
        r_in = 708
        col = BRIGHT_LINE
        w = 1
    else:
        r_in = 714
        col = SUBTLE_LINE
        w = 1
        
    draw.line([(CX + 720 * cos_a, CY + 720 * sin_a), (CX + r_in * cos_a, CY + r_in * sin_a)], fill=col, width=w)

# Seven Nodal Joint Stations (Degrees of Freedom 1 to 7)
dof_data = [
    ("q₁: HIP ROT", "+12.4°", "FEMOROACETABULAR"),
    ("q₂: CORONAL", "-08.1°", "AB-ADDUCTION 45°"),
    ("q₃: TIBIOFEM", "+64.5°", "SAGITTAL FLEXION"),
    ("q₄: BASE AXIS", "-14.2°", "FRANKA J1 ROTATION"),
    ("q₅: ELEVATION", "+88.0°", "FRANKA J2 PITCH"),
    ("q₆: TORSION", "-31.6°", "WRIST PRONATION"),
    ("q₇: TERMINAL", "+05.2°", "END-EFFECTOR 3.8N")
]

for i in range(7):
    ang = i * (360 / 7) - 90
    rad = math.radians(ang)
    cos_a, sin_a = math.cos(rad), math.sin(rad)
    nx = CX + R_NODES * cos_a
    ny = CY + R_NODES * sin_a
    
    # Nodal Crosshairs
    draw.ellipse([nx - 12, ny - 12, nx + 12, ny + 12], outline=CYAN_ACCENT, width=2)
    draw.ellipse([nx - 4, ny - 4, nx + 4, ny + 4], fill=WHITE)
    draw.line([(nx - 18, ny), (nx + 18, ny)], fill=CYAN_ACCENT, width=1)
    draw.line([(nx, ny - 18), (nx, ny + 18)], fill=CYAN_ACCENT, width=1)
    
    # Radial structural link to core
    draw.line([(nx, ny), (CX + 45 * cos_a, CY + 45 * sin_a)], fill=GRID_HAIRLINE, width=1)
    
    # Inscribed Callout Label (positioned just inside the node ring)
    tx = CX + (R_NODES - 55) * cos_a
    ty = CY + (R_NODES - 55) * sin_a
    q_name, q_val, q_desc = dof_data[i]
    draw.text((tx - 40, ty - 14), f"{q_name} {q_val}", font=font_mono_bold, fill=WHITE)
    draw.text((tx - 40, ty + 2), q_desc, font=font_mono_micro, fill=MID_LINE)

# Epicycloid Trajectory Layers with Luminous Bloom Pass
print("Computing multi-stage luminous epicycloids...")
glow_layer = Image.new("RGBA", (W, H), (0, 0, 0, 0))
glow_draw = ImageDraw.Draw(glow_layer, "RGBA")

num_pts = 3600
epicycloid_pts = []
R_base = 400
r_roll = 100
d_pen = 150

for i in range(num_pts + 1):
    t = (i / num_pts) * (8 * math.pi)
    x = (R_base - r_roll) * math.cos(t) + d_pen * math.cos((R_base - r_roll) * t / r_roll)
    y = (R_base - r_roll) * math.sin(t) - d_pen * math.sin((R_base - r_roll) * t / r_roll)
    epicycloid_pts.append((CX + x, CY + y))

for i in range(len(epicycloid_pts) - 1):
    glow_draw.line([epicycloid_pts[i], epicycloid_pts[i+1]], fill=(56, 189, 248, 120), width=5)

glow_layer = glow_layer.filter(ImageFilter.GaussianBlur(radius=4))
base_img = Image.alpha_composite(base_img, glow_layer)
draw = ImageDraw.Draw(base_img, "RGBA")

for i in range(len(epicycloid_pts) - 1):
    draw.line([epicycloid_pts[i], epicycloid_pts[i+1]], fill=CYAN_ACCENT, width=1)

# Second Epicycloid: Sagittal Harmonic Wave (Human Gait Envelope)
gait_pts = []
for i in range(2400):
    t = (i / 2400) * (4 * math.pi)
    rad_dist = 180 + 130 * math.sin(3.5 * t) + 30 * math.cos(7.0 * t)
    x = rad_dist * math.cos(t)
    y = rad_dist * math.sin(t)
    gait_pts.append((CX + x, CY + y))

for i in range(len(gait_pts) - 1):
    col = GOLD_ACCENT if i % 3 == 0 else WHITE
    draw.line([gait_pts[i], gait_pts[i+1]], fill=col, width=1)

# Tangent chords (Harmonic Moiré Network)
for k in range(0, 360, 12):
    rad1 = math.radians(k)
    rad2 = math.radians((k * 3) % 360)
    p1 = (CX + 360 * math.cos(rad1), CY + 360 * math.sin(rad1))
    p2 = (CX + 360 * math.cos(rad2), CY + 360 * math.sin(rad2))
    draw.line([p1, p2], fill=(40, 55, 80, 85), width=1)

# Central Core Gimbal (Golden ICR Locus)
draw.ellipse([CX - 45, CY - 45, CX + 45, CY + 45], outline=GOLD_ACCENT, width=2)
draw.ellipse([CX - 22, CY - 22, CX + 22, CY + 22], outline=WHITE, width=1)
draw.ellipse([CX - 8, CY - 8, CX + 8, CY + 8], fill=GOLD_ACCENT)
draw.line([(CX - 70, CY), (CX + 70, CY)], fill=GOLD_ACCENT, width=1)
draw.line([(CX, CY - 70), (CX, CY + 70)], fill=GOLD_ACCENT, width=1)
draw.text((CX + 14, CY + 14), "ICR · O", font=font_mono_bold, fill=WHITE)

# 5. Flanking Auxiliary Projection Dials (Calibrated Clearances)
print("Rendering auxiliary projection dials and midfield matrices...")

# AUX 1: Top-Left Dial — Sagittal Plane Deviation (Center: 380, 640; R=115)
D1_X, D1_Y, D1_R = 380, 640, 115
draw.ellipse([D1_X - D1_R, D1_Y - D1_R, D1_X + D1_R, D1_Y + D1_R], outline=MID_LINE, width=1)
draw.ellipse([D1_X - D1_R + 12, D1_Y - D1_R + 12, D1_X + D1_R - 12, D1_Y + D1_R - 12], outline=SUBTLE_LINE, width=1)
for deg in range(0, 360, 15):
    rad = math.radians(deg)
    draw.line([
        (D1_X + (D1_R - 8) * math.cos(rad), D1_Y + (D1_R - 8) * math.sin(rad)),
        (D1_X + D1_R * math.cos(rad), D1_Y + D1_R * math.sin(rad))
    ], fill=BRIGHT_LINE, width=1)

draw.arc([D1_X - D1_R + 24, D1_Y - D1_R + 24, D1_X + D1_R - 24, D1_Y + D1_R - 24], start=210, end=350, fill=CYAN_ACCENT, width=2)
draw.text((D1_X - 95, D1_Y - D1_R - 28), "FIG. 01 · SAGITTAL PROJECTION", font=font_mono_bold, fill=WHITE)
draw.text((D1_X - 95, D1_Y - D1_R - 12), "TIBIOFEMORAL RANGE: 0°–135°", font=font_mono_micro, fill=MID_LINE)
draw.text((D1_X - 40, D1_Y + D1_R + 14), "ICR OFFSET: +3.2mm", font=font_mono_small, fill=GOLD_ACCENT)

# AUX 2: Top-Right Dial — Coronal SO(3) Euler Space (Center: W-380, 640; R=115)
D2_X, D2_Y, D2_R = W - 380, 640, 115
draw.ellipse([D2_X - D2_R, D2_Y - D2_R, D2_X + D2_R, D2_Y + D2_R], outline=MID_LINE, width=1)
draw.ellipse([D2_X - D2_R + 12, D2_Y - D2_R + 12, D2_X + D2_R - 12, D2_Y + D2_R - 12], outline=SUBTLE_LINE, width=1)
for deg in range(0, 360, 15):
    rad = math.radians(deg)
    draw.line([
        (D2_X + (D2_R - 8) * math.cos(rad), D2_Y + (D2_R - 8) * math.sin(rad)),
        (D2_X + D2_R * math.cos(rad), D2_Y + D2_R * math.sin(rad))
    ], fill=BRIGHT_LINE, width=1)

draw.ellipse([D2_X - D2_R + 25, D2_Y - 40, D2_X + D2_R - 25, D2_Y + 40], outline=GRID_HAIRLINE, width=1)
draw.ellipse([D2_X - 40, D2_Y - D2_R + 25, D2_X + 40, D2_Y + D2_R - 25], outline=GRID_HAIRLINE, width=1)
draw.arc([D2_X - 70, D2_Y - 70, D2_X + 70, D2_Y + 70], start=30, end=190, fill=GOLD_ACCENT, width=2)
draw.text((D2_X - 95, D2_Y - D2_R - 28), "FIG. 02 · ORTHOGONAL SO(3)", font=font_mono_bold, fill=WHITE)
draw.text((D2_X - 95, D2_Y - D2_R - 12), "EULER ROTATION MATRIX [α, β, γ]", font=font_mono_micro, fill=MID_LINE)
draw.text((D2_X - 48, D2_Y + D2_R + 14), "DET(R) = +1.00000", font=font_mono_small, fill=CYAN_ACCENT)

# AUX 3: Left Midfield — Denavit-Hartenberg Parameter Matrix Column (X: 200..540; Y: 1080..1960)
COL_L_X = 200
COL_L_Y = 1080
draw.text((COL_L_X, COL_L_Y), "DENAVIT-HARTENBERG COORDINATE CHAIN", font=font_mono_bold, fill=GOLD_ACCENT)
draw.text((COL_L_X, COL_L_Y + 20), "KINEMATIC LINK TRANSFORMATION MATRICES", font=font_mono_micro, fill=MID_LINE)
draw.line([(COL_L_X, COL_L_Y + 36), (COL_L_X + 340, COL_L_Y + 36)], fill=MID_LINE, width=1)

for idx in range(7):
    row_y = COL_L_Y + 52 + idx * 82
    joint_id = f"LINK {idx+1:02d}"
    theta_val = f"θ_{idx+1} = {(-45 + idx * 28.5):+06.1f}°"
    alpha_val = f"α: {0 if idx%2==0 else 90}° | d: {idx*45}mm"
    
    draw.text((COL_L_X, row_y), joint_id, font=font_mono_bold, fill=WHITE)
    draw.text((COL_L_X + 80, row_y), theta_val, font=font_mono, fill=CYAN_ACCENT)
    draw.text((COL_L_X + 80, row_y + 16), alpha_val, font=font_mono_micro, fill=MID_LINE)
    
    draw.rectangle([COL_L_X + 80, row_y + 34, COL_L_X + 320, row_y + 39], outline=GRID_HAIRLINE, width=1)
    bar_fill = int((idx + 1) / 7.0 * 240)
    draw.rectangle([COL_L_X + 80, row_y + 34, COL_L_X + 80 + bar_fill, row_y + 39], fill=CYAN_ACCENT)

# AUX 4: Right Midfield — Dynamic Phase Portrait (X: 2160..2500; Y: 1080..1960)
COL_R_X = 2160
COL_R_Y = 1080
draw.text((COL_R_X, COL_R_Y), "FIG. 03 · PHASE SPACE ATTRACTOR", font=font_mono_bold, fill=GOLD_ACCENT)
draw.text((COL_R_X, COL_R_Y + 20), "ANGULAR DISPLACEMENT vs. VELOCITY [θ vs. θ̇]", font=font_mono_micro, fill=MID_LINE)
draw.line([(COL_R_X, COL_R_Y + 36), (COL_R_X + 340, COL_R_Y + 36)], fill=MID_LINE, width=1)

P_BOX = [COL_R_X, COL_R_Y + 52, COL_R_X + 340, COL_R_Y + 52 + 540]
draw.rectangle(P_BOX, outline=GRID_HAIRLINE, width=1)
draw.line([(P_BOX[0] + 170, P_BOX[1]), (P_BOX[0] + 170, P_BOX[3])], fill=GRID_HAIRLINE, width=1)
draw.line([(P_BOX[0], P_BOX[1] + 270), (P_BOX[2], P_BOX[1] + 270)], fill=GRID_HAIRLINE, width=1)

pc_cx, pc_cy = P_BOX[0] + 170, P_BOX[1] + 270
for cycle_idx in range(5):
    rad_x = 35 + cycle_idx * 25
    rad_y = 50 + cycle_idx * 40
    pts = []
    for deg in range(0, 365, 5):
        rad = math.radians(deg)
        x = pc_cx + rad_x * math.cos(rad) + 12 * math.sin(rad * 2)
        y = pc_cy + rad_y * math.sin(rad)
        pts.append((x, y))
    col = CYAN_ACCENT if cycle_idx == 3 else (GOLD_ACCENT if cycle_idx == 4 else SUBTLE_LINE)
    for p_i in range(len(pts) - 1):
        draw.line([pts[p_i], pts[p_i+1]], fill=col, width=1)

draw.text((P_BOX[0] + 12, P_BOX[3] - 22), "LIMIT CYCLE: CONVERGENT", font=font_mono_micro, fill=WHITE)
draw.text((P_BOX[2] - 110, P_BOX[3] - 22), "LYAPUNOV: λ < 0", font=font_mono_micro, fill=CYAN_ACCENT)

# AUX 5: Bottom-Left Waveform Panel — Ground Reaction Harmonics (Y: 2380..2720)
WAVE_X = 200
WAVE_Y = 2380
draw.text((WAVE_X, WAVE_Y), "FIG. 04 · GROUND REACTION FORCE HARMONICS", font=font_mono_bold, fill=WHITE)
draw.text((WAVE_X, WAVE_Y + 20), "FOURIER SPECTRAL DECOMPOSITION OF STRIDE CADENCE", font=font_mono_micro, fill=MID_LINE)
draw.line([(WAVE_X, WAVE_Y + 36), (WAVE_X + 680, WAVE_Y + 36)], fill=MID_LINE, width=1)

for h_idx in range(4):
    y_base = WAVE_Y + 75 + h_idx * 52
    draw.line([(WAVE_X, y_base), (WAVE_X + 680, y_base)], fill=GRID_HAIRLINE, width=1)
    w_pts = []
    freq = (h_idx + 1) * 2.2
    amp = 28 / (h_idx + 1)
    for x_step in range(0, 680, 4):
        x_c = WAVE_X + x_step
        y_c = y_base + amp * math.sin(x_step * 0.02 * freq) * math.cos(x_step * 0.005)
        w_pts.append((x_c, y_c))
    w_col = CYAN_ACCENT if h_idx == 0 else (GOLD_ACCENT if h_idx == 1 else BRIGHT_LINE)
    for p_i in range(len(w_pts) - 1):
        draw.line([w_pts[p_i], w_pts[p_i+1]], fill=w_col, width=1)
    draw.text((WAVE_X + 690, y_base - 7), f"f_{h_idx+1} = {freq*1.2:.1f}Hz", font=font_mono_micro, fill=MID_LINE)

# AUX 6: Bottom-Right Histogram Panel — Serial Torque Distribution (Y: 2380..2720)
TORQ_X = W - 920
TORQ_Y = 2380
draw.text((TORQ_X, TORQ_Y), "FIG. 05 · SERIAL TORQUE TRANSMISSION", font=font_mono_bold, fill=WHITE)
draw.text((TORQ_X, TORQ_Y + 20), "ACTUATOR POWER vs. MUSCULOSKELETAL MOMENT ARM", font=font_mono_micro, fill=MID_LINE)
draw.line([(TORQ_X, TORQ_Y + 36), (TORQ_X + 720, TORQ_Y + 36)], fill=MID_LINE, width=1)

for b_idx in range(7):
    bx = TORQ_X + 25 + b_idx * 96
    by_base = TORQ_Y + 250
    b_h = [130, 185, 210, 150, 105, 80, 40][b_idx]
    draw.rectangle([bx, by_base - b_h, bx + 55, by_base], outline=GRID_HAIRLINE, width=1)
    draw.rectangle([bx + 4, by_base - b_h + 4, bx + 51, by_base], fill=(20, 32, 50, 200))
    draw.rectangle([bx + 4, by_base - int(b_h * 0.75), bx + 51, by_base], fill=CYAN_ACCENT)
    draw.text((bx + 12, by_base + 8), f"J{b_idx+1}", font=font_mono_bold, fill=WHITE)
    draw.text((bx + 4, by_base - b_h - 18), f"{b_h*1.4:.0f}Nm", font=font_mono_micro, fill=GOLD_ACCENT)

# 6. Lower Philosophical & Technical Foundation Section
print("Typesetting lower philosophical axioms and archival seal...")
LOWER_Y = 2820
draw.line([(M_LEFT + 24, LOWER_Y), (M_RIGHT - 24, LOWER_Y)], fill=MID_LINE, width=1)
draw.line([(M_LEFT + 24, LOWER_Y + 4), (M_RIGHT - 24, LOWER_Y + 4)], fill=GRID_HAIRLINE, width=1)

# Column 1 (Left): Axiom 01
AX1_X = M_LEFT + 40
draw.text((AX1_X, LOWER_Y + 40), "[AXIOM 01 · RIEMANNIAN KINEMATICS]", font=font_mono_bold, fill=GOLD_ACCENT)
draw.text((AX1_X, LOWER_Y + 70), "Space and form do not merely contain movement;", font=font_body, fill=WHITE)
draw.text((AX1_X, LOWER_Y + 95), "they are the crystallized residual trace of motion itself.", font=font_body, fill=WHITE)
draw.text((AX1_X, LOWER_Y + 120), "The boundary between mechanical serial chains and biological limbs", font=font_body, fill=MID_LINE)
draw.text((AX1_X, LOWER_Y + 145), "dissolves into continuous vector manifolds and invariant coordinate strata.", font=font_body, fill=MID_LINE)
draw.text((AX1_X, LOWER_Y + 180), "d/dt(∂L/∂q̇) - ∂L/∂q = τ - J_c^T(q)·λ  |  ∇H(p, q) = 0", font=font_mono, fill=CYAN_ACCENT)
draw.text((AX1_X, LOWER_Y + 210), "LEIBNIZ DIFFERENTIAL CONTINUUM · ARC LENGTH S = ∫ ||r'(t)|| dt", font=font_mono_micro, fill=MID_LINE)

# Column 2 (Center): Concentric Archival Seal of Precision
SEAL_X = W // 2
SEAL_Y = LOWER_Y + 140
draw.ellipse([SEAL_X - 105, SEAL_Y - 105, SEAL_X + 105, SEAL_Y + 105], outline=GOLD_ACCENT, width=2)
draw.ellipse([SEAL_X - 95, SEAL_Y - 95, SEAL_X + 95, SEAL_Y + 95], outline=SUBTLE_LINE, width=1)
draw.ellipse([SEAL_X - 60, SEAL_Y - 60, SEAL_X + 60, SEAL_Y + 60], outline=WHITE, width=1)

star_pts = []
for s_i in range(14):
    s_r = 52 if s_i % 2 == 0 else 24
    s_ang = math.radians(s_i * (360 / 14) - 90)
    star_pts.append((SEAL_X + s_r * math.cos(s_ang), SEAL_Y + s_r * math.sin(s_ang)))
for s_i in range(len(star_pts)):
    draw.line([star_pts[s_i], star_pts[(s_i + 1) % len(star_pts)]], fill=CYAN_ACCENT, width=1)

draw.ellipse([SEAL_X - 7, SEAL_Y - 7, SEAL_X + 7, SEAL_Y + 7], fill=GOLD_ACCENT)

s_txt1 = "ARCADIA MOVEMENT SCIENCE"
sb1 = font_mono_micro.getbbox(s_txt1)
draw.text((SEAL_X - (sb1[2] - sb1[0]) // 2, SEAL_Y + 115), s_txt1, font=font_mono_micro, fill=GOLD_ACCENT)

s_txt2 = "VERIFIED MASTERWORK ARCHIVE · FOLIO 2028"
sb2 = font_mono_micro.getbbox(s_txt2)
draw.text((SEAL_X - (sb2[2] - sb2[0]) // 2, SEAL_Y + 132), s_txt2, font=font_mono_micro, fill=WHITE)

# Column 3 (Right): Axiom 02
AX2_X = W - M_LEFT - 680
draw.text((AX2_X, LOWER_Y + 40), "[AXIOM 02 · KINETIC EQUILIBRIUM]", font=font_mono_bold, fill=CYAN_ACCENT)
draw.text((AX2_X, LOWER_Y + 70), "Every articulation obeys an overarching harmonic law.", font=font_body, fill=WHITE)
draw.text((AX2_X, LOWER_Y + 95), "In biological structures and artificial manipulators alike,", font=font_body, fill=WHITE)
draw.text((AX2_X, LOWER_Y + 120), "force and compliance achieve resolution without decorative excess.", font=font_body, fill=MID_LINE)
draw.text((AX2_X, LOWER_Y + 145), "Information lives in design, precision, and spatial cadence.", font=font_body, fill=MID_LINE)
draw.text((AX2_X, LOWER_Y + 180), "T_7^0(q) = ∏ A_i(q_i)  |  rank(J(q)) = 6  |  det(M) > 0", font=font_mono, fill=GOLD_ACCENT)
draw.text((AX2_X, LOWER_Y + 210), "CC BY 4.0 ATTRIBUTION · DBCLS BODYPARTS3D & NVIDIA SIMREADY", font=font_mono_micro, fill=MID_LINE)

# Colophon Bottom Bar
draw.line([(M_LEFT + 24, H - 180), (M_RIGHT - 24, H - 180)], fill=MID_LINE, width=1)
draw.text((M_LEFT + 32, H - 165), "FIG. 8.4 — FINE ART EDITION 1 OF 1", font=font_mono_bold, fill=WHITE)

colo_mid = "EXHIBITED AT THE CONVERGENCE OF HUMAN MOVEMENT SCIENCE & COMPUTATIONAL TECHNOLOGY"
cmb = font_mono_small.getbbox(colo_mid)
draw.text(((W - (cmb[2] - cmb[0])) // 2, H - 165), colo_mid, font=font_mono_small, fill=GOLD_ACCENT)

draw.text((M_RIGHT - 340, H - 165), "DESIGNED VIA KINEMATIC MONISM", font=font_mono_bold, fill=CYAN_ACCENT)

# 7. Fine Microscopic Archival Rag Grain
print("Applying microscopic archival paper grain...")
random.seed(42)
grain_layer = Image.new("RGBA", (W, H), (0, 0, 0, 0))
grain_draw = ImageDraw.Draw(grain_layer, "RGBA")

for _ in range(160000):
    gx = random.randint(M_LEFT, M_RIGHT)
    gy = random.randint(M_TOP, M_BOTTOM)
    val = random.randint(190, 255)
    alpha = random.randint(8, 22)
    grain_draw.point((gx, gy), fill=(val, val, val, alpha))

base_img = Image.alpha_composite(base_img, grain_layer)

# Export Master 300 DPI PNG
png_out_path = os.path.join(OUT_DIR, "kinematic-monism-plate.png")
brain_png_path = os.path.join(BRAIN_DIR, "kinematic-monism-plate.png")

print(f"Exporting polished master 300 DPI raster to {png_out_path}...")
base_img.save(png_out_path, format="PNG", dpi=(300, 300))
base_img.save(brain_png_path, format="PNG", dpi=(300, 300))
print("Raster export completed successfully!")

# Export Companion Vector PDF
print("Compiling companion vector PDF document...")
pdf_out_path = os.path.join(OUT_DIR, "kinematic-monism-plate.pdf")
brain_pdf_path = os.path.join(BRAIN_DIR, "kinematic-monism-plate.pdf")

PDF_W, PDF_H = 1296, 1728
c = pdf_canvas.Canvas(pdf_out_path, pagesize=(PDF_W, PDF_H))
c.drawImage(png_out_path, 0, 0, width=PDF_W, height=PDF_H)
c.save()

import shutil
shutil.copyfile(pdf_out_path, brain_pdf_path)
print(f"Companion PDF saved to {pdf_out_path} and {brain_pdf_path}")
print("SECOND PASS MASTERWORK AUDIT & RENDER COMPLETE.")
