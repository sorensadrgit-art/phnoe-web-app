import os
import math
import random
from PIL import Image, ImageDraw, ImageFont, ImageFilter
from reportlab.pdfgen import canvas as pdf_canvas

# Directories
OUT_DIR = r"C:\Users\soren\.gemini\antigravity\scratch\phnoe-web-app\artifacts"
BRAIN_DIR = r"C:\Users\soren\.gemini\antigravity\brain\495c71cb-e3c9-445b-aa12-946a7641450f"
PUBLIC_ART_DIR = r"C:\Users\soren\.gemini\antigravity\scratch\phnoe-web-app\examples\soren-motion-v8\public\assets\art"
FONT_DIR = r"C:\Users\soren\.gemini\config\plugins\anthropic-skills\skills\canvas-design\canvas-fonts"

os.makedirs(OUT_DIR, exist_ok=True)
os.makedirs(BRAIN_DIR, exist_ok=True)
os.makedirs(PUBLIC_ART_DIR, exist_ok=True)

W, H = 2700, 3600
M_LEFT, M_RIGHT = 140, W - 140
M_TOP, M_BOTTOM = 140, H - 140

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

# Font Loader
def get_font(name, size):
    path = os.path.join(FONT_DIR, name)
    try:
        return ImageFont.truetype(path, size)
    except Exception as e:
        print(f"Font load fallback for {name}: {e}")
        return ImageFont.load_default()

font_title = get_font("PoiretOne-Regular.ttf", 52)
font_subtitle = get_font("Jura-Light.ttf", 21)
font_heading = get_font("Jura-Medium.ttf", 20)
font_body = get_font("Jura-Light.ttf", 15)
font_mono_bold = get_font("GeistMono-Bold.ttf", 14)
font_mono = get_font("GeistMono-Regular.ttf", 13)
font_mono_small = get_font("GeistMono-Regular.ttf", 11)
font_mono_micro = get_font("GeistMono-Regular.ttf", 9)

def init_canvas(lum_center_x, lum_center_y):
    img = Image.new("RGBA", (W, H), BG_OBSIDIAN)
    lum_layer = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    lum_draw = ImageDraw.Draw(lum_layer, "RGBA")
    max_r = 1380
    for r in range(max_r, 80, -30):
        factor = 1.0 - (r / max_r)
        alpha = int(24 * (factor ** 2.0))
        lum_draw.ellipse(
            [lum_center_x - r, lum_center_y - r, lum_center_x + r, lum_center_y + r],
            fill=(12, 22, 40, alpha)
        )
    img = Image.alpha_composite(img, lum_layer)
    draw = ImageDraw.Draw(img, "RGBA")
    
    # Outer double border
    draw.rectangle([M_LEFT, M_TOP, M_RIGHT, M_BOTTOM], outline=MID_LINE, width=2)
    draw.rectangle([M_LEFT + 16, M_TOP + 16, M_RIGHT - 16, M_BOTTOM - 16], outline=SUBTLE_LINE, width=1)
    
    # Corner registration marks
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
    
    # Millimeter calibration scales
    for x in range(M_LEFT + 40, M_RIGHT - 30, 10):
        d = x - M_LEFT
        t_len = 8 if d % 100 == 0 else (5 if d % 50 == 0 else 2)
        col = WHITE if d % 100 == 0 else SUBTLE_LINE
        draw.line([(x, M_TOP), (x, M_TOP + t_len)], fill=col, width=1)
        draw.line([(x, M_BOTTOM), (x, M_BOTTOM - t_len)], fill=col, width=1)
        if d % 200 == 0 and x < M_RIGHT - 80:
            draw.text((x - 8, M_TOP + 10), f"{d//10:03d}", font=font_mono_micro, fill=MID_LINE)

    for y in range(M_TOP + 40, M_BOTTOM - 30, 10):
        d = y - M_TOP
        t_len = 8 if d % 100 == 0 else (5 if d % 50 == 0 else 2)
        col = WHITE if d % 100 == 0 else SUBTLE_LINE
        draw.line([(M_LEFT, y), (M_LEFT + t_len, y)], fill=col, width=1)
        draw.line([(M_RIGHT, y), (M_RIGHT - t_len, y)], fill=col, width=1)
        if d % 200 == 0 and y < M_BOTTOM - 80:
            draw.text((M_LEFT + 10, y - 5), f"{d//10:03d}", font=font_mono_micro, fill=MID_LINE)
            
    # Separator headers
    draw.line([(M_LEFT + 24, 380), (M_RIGHT - 24, 380)], fill=MID_LINE, width=1)
    draw.line([(M_LEFT + 24, 384), (M_RIGHT - 24, 384)], fill=GRID_HAIRLINE, width=1)
    
    return img, draw

def apply_grain(img):
    random.seed(42)
    grain_layer = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    grain_draw = ImageDraw.Draw(grain_layer, "RGBA")
    for _ in range(160000):
        gx = random.randint(M_LEFT, M_RIGHT)
        gy = random.randint(M_TOP, M_BOTTOM)
        val = random.randint(190, 255)
        alpha = random.randint(8, 22)
        grain_draw.point((gx, gy), fill=(val, val, val, alpha))
    return Image.alpha_composite(img, grain_layer)

# ==============================================================================
# PLATE 1: KINEMATIC MONISM · TRANSLATION GEOMETRY
# ==============================================================================
def render_plate_1():
    print("Synthesizing Plate I: Kinematic Monism (Translation Geometry)...")
    CX, CY = W // 2, 1560
    img, draw = init_canvas(CX, CY)
    
    # Header
    draw.text((M_LEFT + 32, 195), "PLATE NO. VIII · TRANSLATION GEOMETRY", font=font_mono_bold, fill=GOLD_ACCENT)
    draw.text((M_LEFT + 32, 220), "SPECIMEN: DPT-2028 · ARTICULATED KINEMATICS", font=font_mono, fill=WHITE)
    draw.text((M_LEFT + 32, 245), "DATUM: 40°01'14\"N  75°09'22\"W [GLENSIDE TERRESTRIAL]", font=font_mono_small, fill=MID_LINE)
    draw.text((M_LEFT + 32, 268), "INSTRUMENTATION: 7-DOF SERIAL MANIFOLD × RIEMANNIAN PHASE SPACE", font=font_mono_small, fill=MID_LINE)
    draw.text((M_LEFT + 32, 290), "METRIC TENSOR: g_ij = J_i^T(q) M(q) J_j(q) · INVARIANT TORSION", font=font_mono_small, fill=CYAN_ACCENT)

    title_text = "K I N E M A T I C   M O N I S M"
    tw = font_title.getbbox(title_text)[2] - font_title.getbbox(title_text)[0]
    draw.text(((W - tw) // 2, 205), title_text, font=font_title, fill=WHITE)

    sub_text = "THE SPATIAL GEOMETRY OF ARTICULATED MANIFOLDS"
    sw = font_subtitle.getbbox(sub_text)[2] - font_subtitle.getbbox(sub_text)[0]
    draw.text(((W - sw) // 2, 272), sub_text, font=font_subtitle, fill=GOLD_ACCENT)

    sub_meta = "A HARMONIC SYNTHESIS OF HUMAN BIOMECHANICS & INDUSTRIAL ROBOTIC DEGREES OF FREEDOM"
    smw = font_mono_small.getbbox(sub_meta)[2] - font_mono_small.getbbox(sub_meta)[0]
    draw.text(((W - smw) // 2, 310), sub_meta, font=font_mono_small, fill=MID_LINE)

    draw.text((M_RIGHT - 390, 195), "SYSTEM METRIC: SO(3) × SE(3)", font=font_mono_bold, fill=CYAN_ACCENT)
    draw.text((M_RIGHT - 390, 220), "DEGREE OF FREEDOM: 07 [q₁..q₇]", font=font_mono, fill=WHITE)
    draw.text((M_RIGHT - 390, 245), "ANGULAR ENVELOPE: 0.00° → 135.24°", font=font_mono_small, fill=MID_LINE)
    draw.text((M_RIGHT - 390, 268), "VELOCITY VECTOR: θ̇(t) ∈ C²[0, T]", font=font_mono_small, fill=MID_LINE)
    draw.text((M_RIGHT - 390, 290), "STATUS: VERIFIED MATHEMATICAL STUDY", font=font_mono_small, fill=GOLD_ACCENT)

    # Central Mandala
    R_OUTER = 720
    R_NODES = 670
    rings = [720, 670, 600, 520, 440, 360, 270, 180, 90, 45]
    for r in rings:
        col = WHITE if r in [720, 440, 45] else (CYAN_ACCENT if r == 600 else (GOLD_MUTED if r == 360 else GRID_HAIRLINE))
        w = 2 if r in [720, 440] else 1
        draw.ellipse([CX - r, CY - r, CX + r, CY + r], outline=col, width=w)

    for deg in range(360):
        rad = math.radians(deg)
        cos_a, sin_a = math.cos(rad), math.sin(rad)
        if deg % 30 == 0:
            r_in, col, w = 696, WHITE, 2
            lr = 746
            t_box = font_mono_micro.getbbox(f"{deg:03d}°")
            draw.text((CX + lr * cos_a - (t_box[2] - t_box[0]) / 2, CY + lr * sin_a - (t_box[3] - t_box[1]) / 2), f"{deg:03d}°", font=font_mono_micro, fill=GOLD_ACCENT)
        elif deg % 5 == 0:
            r_in, col, w = 708, BRIGHT_LINE, 1
        else:
            r_in, col, w = 714, SUBTLE_LINE, 1
        draw.line([(CX + 720 * cos_a, CY + 720 * sin_a), (CX + r_in * cos_a, CY + r_in * sin_a)], fill=col, width=w)

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
        nx, ny = CX + R_NODES * cos_a, CY + R_NODES * sin_a
        draw.ellipse([nx - 12, ny - 12, nx + 12, ny + 12], outline=CYAN_ACCENT, width=2)
        draw.ellipse([nx - 4, ny - 4, nx + 4, ny + 4], fill=WHITE)
        draw.line([(nx - 18, ny), (nx + 18, ny)], fill=CYAN_ACCENT, width=1)
        draw.line([(nx, ny - 18), (nx, ny + 18)], fill=CYAN_ACCENT, width=1)
        draw.line([(nx, ny), (CX + 45 * cos_a, CY + 45 * sin_a)], fill=GRID_HAIRLINE, width=1)
        tx, ty = CX + (R_NODES - 55) * cos_a, CY + (R_NODES - 55) * sin_a
        draw.text((tx - 40, ty - 14), f"{dof_data[i][0]} {dof_data[i][1]}", font=font_mono_bold, fill=WHITE)
        draw.text((tx - 40, ty + 2), dof_data[i][2], font=font_mono_micro, fill=MID_LINE)

    # Epicycloids
    glow = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    g_draw = ImageDraw.Draw(glow, "RGBA")
    pts = []
    for i in range(3601):
        t = (i / 3600) * (8 * math.pi)
        x = (400 - 100) * math.cos(t) + 150 * math.cos(300 * t / 100)
        y = (400 - 100) * math.sin(t) - 150 * math.sin(300 * t / 100)
        pts.append((CX + x, CY + y))
    for i in range(len(pts) - 1):
        g_draw.line([pts[i], pts[i+1]], fill=(56, 189, 248, 120), width=5)
    glow = glow.filter(ImageFilter.GaussianBlur(radius=4))
    img = Image.alpha_composite(img, glow)
    draw = ImageDraw.Draw(img, "RGBA")
    for i in range(len(pts) - 1):
        draw.line([pts[i], pts[i+1]], fill=CYAN_ACCENT, width=1)

    # Sagittal wave
    g_pts = []
    for i in range(2400):
        t = (i / 2400) * (4 * math.pi)
        d = 180 + 130 * math.sin(3.5 * t) + 30 * math.cos(7.0 * t)
        g_pts.append((CX + d * math.cos(t), CY + d * math.sin(t)))
    for i in range(len(g_pts) - 1):
        draw.line([g_pts[i], g_pts[i+1]], fill=GOLD_ACCENT if i % 3 == 0 else WHITE, width=1)

    # Center Gimbal
    draw.ellipse([CX - 45, CY - 45, CX + 45, CY + 45], outline=GOLD_ACCENT, width=2)
    draw.ellipse([CX - 22, CY - 22, CX + 22, CY + 22], outline=WHITE, width=1)
    draw.ellipse([CX - 8, CY - 8, CX + 8, CY + 8], fill=GOLD_ACCENT)
    draw.line([(CX - 70, CY), (CX + 70, CY)], fill=GOLD_ACCENT, width=1)
    draw.line([(CX, CY - 70), (CX, CY + 70)], fill=GOLD_ACCENT, width=1)
    draw.text((CX + 14, CY + 14), "ICR · O", font=font_mono_bold, fill=WHITE)

    # Auxiliary systems
    # Top-Left Dial
    D1_X, D1_Y, D1_R = 380, 640, 115
    draw.ellipse([D1_X - D1_R, D1_Y - D1_R, D1_X + D1_R, D1_Y + D1_R], outline=MID_LINE, width=1)
    draw.arc([D1_X - D1_R + 24, D1_Y - D1_R + 24, D1_X + D1_R - 24, D1_Y + D1_R - 24], start=210, end=350, fill=CYAN_ACCENT, width=2)
    draw.text((D1_X - 95, D1_Y - D1_R - 28), "FIG. 01 · SAGITTAL PROJECTION", font=font_mono_bold, fill=WHITE)
    draw.text((D1_X - 95, D1_Y - D1_R - 12), "TIBIOFEMORAL RANGE: 0°–135°", font=font_mono_micro, fill=MID_LINE)
    draw.text((D1_X - 40, D1_Y + D1_R + 14), "ICR OFFSET: +3.2mm", font=font_mono_small, fill=GOLD_ACCENT)

    # Top-Right Dial
    D2_X, D2_Y, D2_R = W - 380, 640, 115
    draw.ellipse([D2_X - D2_R, D2_Y - D2_R, D2_X + D2_R, D2_Y + D2_R], outline=MID_LINE, width=1)
    draw.arc([D2_X - 70, D2_Y - 70, D2_X + 70, D2_Y + 70], start=30, end=190, fill=GOLD_ACCENT, width=2)
    draw.text((D2_X - 95, D2_Y - D2_R - 28), "FIG. 02 · ORTHOGONAL SO(3)", font=font_mono_bold, fill=WHITE)
    draw.text((D2_X - 95, D2_Y - D2_R - 12), "EULER ROTATION MATRIX [α, β, γ]", font=font_mono_micro, fill=MID_LINE)
    draw.text((D2_X - 48, D2_Y + D2_R + 14), "DET(R) = +1.00000", font=font_mono_small, fill=CYAN_ACCENT)

    # Left DH Matrix
    COL_L_X, COL_L_Y = 200, 1080
    draw.text((COL_L_X, COL_L_Y), "DENAVIT-HARTENBERG COORDINATE CHAIN", font=font_mono_bold, fill=GOLD_ACCENT)
    draw.text((COL_L_X, COL_L_Y + 20), "KINEMATIC LINK TRANSFORMATION MATRICES", font=font_mono_micro, fill=MID_LINE)
    draw.line([(COL_L_X, COL_L_Y + 36), (COL_L_X + 340, COL_L_Y + 36)], fill=MID_LINE, width=1)
    for idx in range(7):
        row_y = COL_L_Y + 52 + idx * 82
        draw.text((COL_L_X, row_y), f"LINK {idx+1:02d}", font=font_mono_bold, fill=WHITE)
        draw.text((COL_L_X + 80, row_y), f"θ_{idx+1} = {(-45 + idx * 28.5):+06.1f}°", font=font_mono, fill=CYAN_ACCENT)
        draw.text((COL_L_X + 80, row_y + 16), f"α: {0 if idx%2==0 else 90}° | d: {idx*45}mm", font=font_mono_micro, fill=MID_LINE)
        draw.rectangle([COL_L_X + 80, row_y + 34, COL_L_X + 320, row_y + 39], outline=GRID_HAIRLINE, width=1)
        draw.rectangle([COL_L_X + 80, row_y + 34, COL_L_X + 80 + int((idx + 1) / 7.0 * 240), row_y + 39], fill=CYAN_ACCENT)

    # Right Phase Attractor
    COL_R_X, COL_R_Y = 2160, 1080
    draw.text((COL_R_X, COL_R_Y), "FIG. 03 · PHASE SPACE ATTRACTOR", font=font_mono_bold, fill=GOLD_ACCENT)
    draw.text((COL_R_X, COL_R_Y + 20), "ANGULAR DISPLACEMENT vs. VELOCITY [θ vs. θ̇]", font=font_mono_micro, fill=MID_LINE)
    draw.line([(COL_R_X, COL_R_Y + 36), (COL_R_X + 340, COL_R_Y + 36)], fill=MID_LINE, width=1)
    P_BOX = [COL_R_X, COL_R_Y + 52, COL_R_X + 340, COL_R_Y + 52 + 540]
    draw.rectangle(P_BOX, outline=GRID_HAIRLINE, width=1)
    draw.line([(P_BOX[0] + 170, P_BOX[1]), (P_BOX[0] + 170, P_BOX[3])], fill=GRID_HAIRLINE, width=1)
    draw.line([(P_BOX[0], P_BOX[1] + 270), (P_BOX[2], P_BOX[1] + 270)], fill=GRID_HAIRLINE, width=1)
    for c_i in range(5):
        rx, ry = 35 + c_i * 25, 50 + c_i * 40
        c_pts = [(P_BOX[0] + 170 + rx * math.cos(math.radians(dg)) + 12 * math.sin(math.radians(dg * 2)),
                  P_BOX[1] + 270 + ry * math.sin(math.radians(dg))) for dg in range(0, 365, 5)]
        col = CYAN_ACCENT if c_i == 3 else (GOLD_ACCENT if c_i == 4 else SUBTLE_LINE)
        for p_i in range(len(c_pts) - 1):
            draw.line([c_pts[p_i], c_pts[p_i+1]], fill=col, width=1)

    # Bottom Left Harmonics
    WAVE_X, WAVE_Y = 200, 2380
    draw.text((WAVE_X, WAVE_Y), "FIG. 04 · GROUND REACTION FORCE HARMONICS", font=font_mono_bold, fill=WHITE)
    draw.text((WAVE_X, WAVE_Y + 20), "FOURIER SPECTRAL DECOMPOSITION OF STRIDE CADENCE", font=font_mono_micro, fill=MID_LINE)
    draw.line([(WAVE_X, WAVE_Y + 36), (WAVE_X + 680, WAVE_Y + 36)], fill=MID_LINE, width=1)
    for h_i in range(4):
        yb = WAVE_Y + 75 + h_i * 52
        draw.line([(WAVE_X, yb), (WAVE_X + 680, yb)], fill=GRID_HAIRLINE, width=1)
        w_p = [(WAVE_X + xs, yb + (28 / (h_i + 1)) * math.sin(xs * 0.02 * (h_i + 1) * 2.2) * math.cos(xs * 0.005)) for xs in range(0, 680, 4)]
        for p_i in range(len(w_p) - 1):
            draw.line([w_p[p_i], w_p[p_i+1]], fill=CYAN_ACCENT if h_i == 0 else (GOLD_ACCENT if h_i == 1 else BRIGHT_LINE), width=1)

    # Bottom Right Histogram
    TORQ_X, TORQ_Y = W - 920, 2380
    draw.text((TORQ_X, TORQ_Y), "FIG. 05 · SERIAL TORQUE TRANSMISSION", font=font_mono_bold, fill=WHITE)
    draw.text((TORQ_X, TORQ_Y + 20), "ACTUATOR POWER vs. MUSCULOSKELETAL MOMENT ARM", font=font_mono_micro, fill=MID_LINE)
    draw.line([(TORQ_X, TORQ_Y + 36), (TORQ_X + 720, TORQ_Y + 36)], fill=MID_LINE, width=1)
    b_hs = [130, 185, 210, 150, 105, 80, 40]
    for b_i in range(7):
        bx = TORQ_X + 25 + b_i * 96
        by_b = TORQ_Y + 250
        draw.rectangle([bx, by_b - b_hs[b_i], bx + 55, by_b], outline=GRID_HAIRLINE, width=1)
        draw.rectangle([bx + 4, by_b - int(b_hs[b_i] * 0.75), bx + 51, by_b], fill=CYAN_ACCENT)
        draw.text((bx + 12, by_b + 8), f"J{b_i+1}", font=font_mono_bold, fill=WHITE)

    # Lower Section
    LOWER_Y = 2820
    draw.line([(M_LEFT + 24, LOWER_Y), (M_RIGHT - 24, LOWER_Y)], fill=MID_LINE, width=1)
    AX1_X = M_LEFT + 40
    draw.text((AX1_X, LOWER_Y + 40), "[AXIOM 01 · RIEMANNIAN KINEMATICS]", font=font_mono_bold, fill=GOLD_ACCENT)
    draw.text((AX1_X, LOWER_Y + 70), "Space and form do not merely contain movement;", font=font_body, fill=WHITE)
    draw.text((AX1_X, LOWER_Y + 95), "they are the crystallized residual trace of motion itself.", font=font_body, fill=WHITE)
    draw.text((AX1_X, LOWER_Y + 120), "The boundary between mechanical serial chains and biological limbs", font=font_body, fill=MID_LINE)
    draw.text((AX1_X, LOWER_Y + 145), "dissolves into continuous vector manifolds and invariant coordinate strata.", font=font_body, fill=MID_LINE)
    draw.text((AX1_X, LOWER_Y + 180), "d/dt(∂L/∂q̇) - ∂L/∂q = τ - J_c^T(q)·λ  |  ∇H(p, q) = 0", font=font_mono, fill=CYAN_ACCENT)

    SEAL_X = W // 2
    SEAL_Y = LOWER_Y + 140
    draw.ellipse([SEAL_X - 105, SEAL_Y - 105, SEAL_X + 105, SEAL_Y + 105], outline=GOLD_ACCENT, width=2)
    draw.ellipse([SEAL_X - 60, SEAL_Y - 60, SEAL_X + 60, SEAL_Y + 60], outline=WHITE, width=1)
    st_pts = [(SEAL_X + (52 if si % 2 == 0 else 24) * math.cos(math.radians(si * 25.7 - 90)),
               SEAL_Y + (52 if si % 2 == 0 else 24) * math.sin(math.radians(si * 25.7 - 90))) for si in range(14)]
    for si in range(14):
        draw.line([st_pts[si], st_pts[(si + 1) % 14]], fill=CYAN_ACCENT, width=1)
    sb1 = font_mono_micro.getbbox("ARCADIA MOVEMENT SCIENCE")
    draw.text((SEAL_X - (sb1[2] - sb1[0]) // 2, SEAL_Y + 115), "ARCADIA MOVEMENT SCIENCE", font=font_mono_micro, fill=GOLD_ACCENT)

    AX2_X = W - M_LEFT - 680
    draw.text((AX2_X, LOWER_Y + 40), "[AXIOM 02 · KINETIC EQUILIBRIUM]", font=font_mono_bold, fill=CYAN_ACCENT)
    draw.text((AX2_X, LOWER_Y + 70), "Every articulation obeys an overarching harmonic law.", font=font_body, fill=WHITE)
    draw.text((AX2_X, LOWER_Y + 95), "In biological structures and artificial manipulators alike,", font=font_body, fill=WHITE)
    draw.text((AX2_X, LOWER_Y + 120), "force and compliance achieve resolution without decorative excess.", font=font_body, fill=MID_LINE)
    draw.text((AX2_X, LOWER_Y + 145), "Information lives in design, precision, and spatial cadence.", font=font_body, fill=MID_LINE)
    draw.text((AX2_X, LOWER_Y + 180), "T_7^0(q) = ∏ A_i(q_i)  |  rank(J(q)) = 6  |  det(M) > 0", font=font_mono, fill=GOLD_ACCENT)

    draw.line([(M_LEFT + 24, H - 180), (M_RIGHT - 24, H - 180)], fill=MID_LINE, width=1)
    draw.text((M_LEFT + 32, H - 165), "PLATE NO. VIII · FINE ART EDITION 1 OF 3", font=font_mono_bold, fill=WHITE)
    cmb = font_mono_small.getbbox("EXHIBITED AT THE CONVERGENCE OF HUMAN MOVEMENT SCIENCE & COMPUTATIONAL TECHNOLOGY")
    draw.text(((W - (cmb[2] - cmb[0])) // 2, H - 165), "EXHIBITED AT THE CONVERGENCE OF HUMAN MOVEMENT SCIENCE & COMPUTATIONAL TECHNOLOGY", font=font_mono_small, fill=GOLD_ACCENT)
    draw.text((M_RIGHT - 340, H - 165), "DESIGNED VIA KINEMATIC MONISM", font=font_mono_bold, fill=CYAN_ACCENT)

    img = apply_grain(img)
    return img

# ==============================================================================
# PLATE 2: TIBIOFEMORAL KINEMATICS · BIOMECHANICAL ARTICULATION
# ==============================================================================
def render_plate_2():
    print("Synthesizing Plate II: Tibiofemoral Kinematics (Biological Anatomy)...")
    CX, CY = W // 2, 1560
    img, draw = init_canvas(CX, CY)
    
    # Header
    draw.text((M_LEFT + 32, 195), "PLATE NO. IX · BIOMECHANICAL ARTICULATION", font=font_mono_bold, fill=GOLD_ACCENT)
    draw.text((M_LEFT + 32, 220), "SPECIMEN: ANATOMICAL FEMUR-TIBIA JOINT (CC BY 4.0 DBCLS)", font=font_mono, fill=WHITE)
    draw.text((M_LEFT + 32, 245), "INSTANTANEOUS HELICAL AXIS: J-CURVE EVOLUTE MANIFOLD", font=font_mono_small, fill=MID_LINE)
    draw.text((M_LEFT + 32, 268), "FEMORAL ROLLBACK: +18.4mm AP TRANSLATION OVER 135° FLEXION", font=font_mono_small, fill=CYAN_ACCENT)
    draw.text((M_LEFT + 32, 290), "CONTACT STRESS TENSOR: σ_ij = C_ijkl · ε_kl (MEDIAL/LATERAL)", font=font_mono_small, fill=MID_LINE)

    title_text = "T I B I O F E M O R A L   K I N E M A T I C S"
    tw = font_title.getbbox(title_text)[2] - font_title.getbbox(title_text)[0]
    draw.text(((W - tw) // 2, 205), title_text, font=font_title, fill=WHITE)

    sub_text = "INSTANTANEOUS HELICAL AXES & CONTACT STRESS MANIFOLDS"
    sw = font_subtitle.getbbox(sub_text)[2] - font_subtitle.getbbox(sub_text)[0]
    draw.text(((W - sw) // 2, 272), sub_text, font=font_subtitle, fill=GOLD_ACCENT)

    sub_meta = "A PARAMETRIC STUDY OF HUMAN KNEE ROLLBACK, LIGAMENT STRAIN & SCREW-HOME ROTATION"
    smw = font_mono_small.getbbox(sub_meta)[2] - font_mono_small.getbbox(sub_meta)[0]
    draw.text(((W - smw) // 2, 310), sub_meta, font=font_mono_small, fill=MID_LINE)

    draw.text((M_RIGHT - 390, 195), "SCREW-HOME: 15° EXT ROT", font=font_mono_bold, fill=CYAN_ACCENT)
    draw.text((M_RIGHT - 390, 220), "CRUCIATE BUNDLES: ACL / PCL", font=font_mono, fill=WHITE)
    draw.text((M_RIGHT - 390, 245), "MENISCAL COMPLIANCE: E = 12 MPa", font=font_mono_small, fill=MID_LINE)
    draw.text((M_RIGHT - 390, 268), "CONVERGENCE: FOUR-BAR LINKAGE", font=font_mono_small, fill=MID_LINE)
    draw.text((M_RIGHT - 390, 290), "ARCADIA DPT KINELAB SPECIMEN", font=font_mono_small, fill=GOLD_ACCENT)

    # Central Biomechanical Evolute Astrolabe
    R_OUTER = 720
    draw.ellipse([CX - R_OUTER, CY - R_OUTER, CX + R_OUTER, CY + R_OUTER], outline=WHITE, width=2)
    draw.ellipse([CX - 670, CY - 670, CX + 670, CY + 670], outline=GRID_HAIRLINE, width=1)
    draw.ellipse([CX - 560, CY - 560, CX + 560, CY + 560], outline=CYAN_ACCENT, width=1)
    draw.ellipse([CX - 420, CY - 420, CX + 420, CY + 420], outline=GOLD_MUTED, width=1)
    draw.ellipse([CX - 240, CY - 240, CX + 240, CY + 240], outline=WHITE, width=1)

    # 360-degree vernier ticks
    for deg in range(360):
        rad = math.radians(deg)
        if deg % 15 == 0:
            draw.line([(CX + 720 * math.cos(rad), CY + 720 * math.sin(rad)), (CX + 700 * math.cos(rad), CY + 700 * math.sin(rad))], fill=BRIGHT_LINE, width=1)
        else:
            draw.line([(CX + 720 * math.cos(rad), CY + 720 * math.sin(rad)), (CX + 712 * math.cos(rad), CY + 712 * math.sin(rad))], fill=SUBTLE_LINE, width=1)

    # The Classical J-Curve Evolute (Instantaneous Center of Rotation Locus)
    glow = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    g_draw = ImageDraw.Draw(glow, "RGBA")
    j_pts = []
    for step in range(141):
        t = step / 140.0
        # Sagittal ICR locus moves postero-superiorly as flexion increases
        x = CX - 180 + 320 * t - 140 * (t ** 2)
        y = CY - 120 + 260 * (t ** 1.5) - 80 * math.sin(t * math.pi)
        j_pts.append((x, y))
    for i in range(len(j_pts) - 1):
        g_draw.line([j_pts[i], j_pts[i+1]], fill=(56, 189, 248, 140), width=6)
    glow = glow.filter(ImageFilter.GaussianBlur(radius=5))
    img = Image.alpha_composite(img, glow)
    draw = ImageDraw.Draw(img, "RGBA")
    for i in range(len(j_pts) - 1):
        draw.line([j_pts[i], j_pts[i+1]], fill=WHITE, width=2)

    # Radiating Femoral Condyle Curvature Normals (15 Flexion Stations: 0° to 140°)
    for st in range(0, 141, 10):
        t = st / 140.0
        pt = j_pts[st]
        ang = math.radians(200 - st * 1.1)
        # Normal vector projecting to femoral condylar contact
        nx = pt[0] + 380 * math.cos(ang)
        ny = pt[1] + 380 * math.sin(ang)
        draw.line([pt, (nx, ny)], fill=(56, 189, 248, 160) if st % 20 == 0 else SUBTLE_LINE, width=1)
        draw.ellipse([nx - 5, ny - 5, nx + 5, ny + 5], fill=GOLD_ACCENT if st % 20 == 0 else BRIGHT_LINE)
        draw.text((nx + 10, ny - 6), f"{st}°", font=font_mono_micro, fill=WHITE if st % 20 == 0 else MID_LINE)

    # Opposing Cruciate Ligament Torsion Hyperbolas (ACL & PCL isometric envelopes)
    for c_step in range(180):
        t = c_step / 180.0
        # ACL: Anteromedial & Posterolateral bundles
        acl_x = CX - 220 + 440 * t
        acl_y = CY + 80 * math.sinh(t * 1.8 - 0.9)
        # PCL: Anterolateral & Posteromedial bundles
        pcl_x = CX + 220 - 440 * t
        pcl_y = CY - 80 * math.sinh(t * 1.8 - 0.9)
        draw.point((acl_x, acl_y), fill=CYAN_ACCENT)
        draw.point((pcl_x, pcl_y), fill=GOLD_ACCENT)

    # ICR Focal Hub
    draw.ellipse([CX - 40, CY - 40, CX + 40, CY + 40], outline=GOLD_ACCENT, width=2)
    draw.line([(CX - 60, CY), (CX + 60, CY)], fill=GOLD_ACCENT, width=1)
    draw.line([(CX, CY - 60), (CX, CY + 60)], fill=GOLD_ACCENT, width=1)
    draw.text((CX + 12, CY + 12), "ICR · CENTROID", font=font_mono_bold, fill=WHITE)

    # Auxiliary Flanking Figures
    # AUX 1: Top-Left — Medial/Lateral Tibial Plateau Stress Isobars
    D1_X, D1_Y = 380, 640
    draw.ellipse([D1_X - 115, D1_Y - 115, D1_X + 115, D1_Y + 115], outline=MID_LINE, width=1)
    # Dual kidney-shaped condyle contact zones
    draw.ellipse([D1_X - 85, D1_Y - 45, D1_X - 15, D1_Y + 45], outline=CYAN_ACCENT, width=2)
    draw.ellipse([D1_X + 15, D1_Y - 45, D1_X + 85, D1_Y + 45], outline=GOLD_ACCENT, width=2)
    draw.text((D1_X - 95, D1_Y - 145), "FIG. 01 · PLATEAU CONTACT ISOBARS", font=font_mono_bold, fill=WHITE)
    draw.text((D1_X - 95, D1_Y - 128), "MEDIAL: 60% LOAD | LATERAL: 40% LOAD", font=font_mono_micro, fill=MID_LINE)
    draw.text((D1_X - 45, D1_Y + 125), "PEAK STRESS: 3.4 MPa", font=font_mono_small, fill=CYAN_ACCENT)

    # AUX 2: Top-Right — Screw-Home Rotation Mechanism
    D2_X, D2_Y = W - 380, 640
    draw.ellipse([D2_X - 115, D2_Y - 115, D2_X + 115, D2_Y + 115], outline=MID_LINE, width=1)
    draw.arc([D2_X - 85, D2_Y - 85, D2_X + 85, D2_Y + 85], start=270, end=345, fill=CYAN_ACCENT, width=3)
    draw.line([(D2_X, D2_Y), (D2_X + 85 * math.cos(math.radians(345)), D2_Y + 85 * math.sin(math.radians(345)))], fill=GOLD_ACCENT, width=2)
    draw.text((D2_X - 95, D2_Y - 145), "FIG. 02 · SCREW-HOME TORSION", font=font_mono_bold, fill=WHITE)
    draw.text((D2_X - 95, D2_Y - 128), "EXTERNAL ROTATION IN LAST 30° EXTENSION", font=font_mono_micro, fill=MID_LINE)
    draw.text((D2_X - 40, D2_Y + 125), "ANGULAR ROTATION: +15°", font=font_mono_small, fill=GOLD_ACCENT)

    # AUX 3: Left Midfield — Muscle Activation Envelopes (EMG)
    COL_L_X, COL_L_Y = 200, 1080
    draw.text((COL_L_X, COL_L_Y), "ELECTROMYOGRAPHIC ENVELOPES", font=font_mono_bold, fill=GOLD_ACCENT)
    draw.text((COL_L_X, COL_L_Y + 20), "NORMALIZED MUSCLE ACTIVATION CYCLES (% MVC)", font=font_mono_micro, fill=MID_LINE)
    draw.line([(COL_L_X, COL_L_Y + 36), (COL_L_X + 340, COL_L_Y + 36)], fill=MID_LINE, width=1)
    muscles = [
        ("RECTUS FEMORIS", 82),
        ("VASTUS LATERALIS", 94),
        ("VASTUS MEDIALIS", 91),
        ("BICEPS FEMORIS", 68),
        ("SEMITENDINOSUS", 74),
        ("GASTROCNEMIUS MED", 62),
        ("TIBIALIS ANTERIOR", 55)
    ]
    for idx, (m_name, m_val) in enumerate(muscles):
        row_y = COL_L_Y + 52 + idx * 82
        draw.text((COL_L_X, row_y), m_name, font=font_mono_bold, fill=WHITE)
        draw.text((COL_L_X + 220, row_y), f"{m_val}% MVC", font=font_mono, fill=CYAN_ACCENT)
        draw.rectangle([COL_L_X, row_y + 26, COL_L_X + 320, row_y + 31], outline=GRID_HAIRLINE, width=1)
        draw.rectangle([COL_L_X, row_y + 26, COL_L_X + int(m_val / 100.0 * 320), row_y + 31], fill=CYAN_ACCENT)

    # AUX 4: Right Midfield — Patellofemoral Joint Stress Vectors
    COL_R_X, COL_R_Y = 2160, 1080
    draw.text((COL_R_X, COL_R_Y), "FIG. 03 · PATELLOFEMORAL FORCE", font=font_mono_bold, fill=GOLD_ACCENT)
    draw.text((COL_R_X, COL_R_Y + 20), "JOINT REACTION FORCE vs. SQUAT DEPTH", font=font_mono_micro, fill=MID_LINE)
    draw.line([(COL_R_X, COL_R_Y + 36), (COL_R_X + 340, COL_R_Y + 36)], fill=MID_LINE, width=1)
    P_BOX = [COL_R_X, COL_R_Y + 52, COL_R_X + 340, COL_R_Y + 52 + 540]
    draw.rectangle(P_BOX, outline=GRID_HAIRLINE, width=1)
    pf_pts = []
    for deg in range(0, 140, 2):
        t = deg / 140.0
        px = P_BOX[0] + 20 + t * 300
        # Patellofemoral reaction force peaks at deep flexion
        py = P_BOX[3] - 20 - 460 * math.sin(t * (math.pi / 2.0)) ** 1.6
        pf_pts.append((px, py))
    for p_i in range(len(pf_pts) - 1):
        draw.line([pf_pts[p_i], pf_pts[p_i+1]], fill=CYAN_ACCENT, width=2)
    draw.text((P_BOX[0] + 12, P_BOX[3] - 22), "PEAK PFJRF: 7.8 × BODY WEIGHT", font=font_mono_micro, fill=WHITE)
    draw.text((P_BOX[2] - 110, P_BOX[3] - 22), "@ 90°–105° FLEXION", font=font_mono_micro, fill=GOLD_ACCENT)

    # AUX 5: Bottom-Left — Meniscal Hoop Stress Distribution
    WAVE_X, WAVE_Y = 200, 2380
    draw.text((WAVE_X, WAVE_Y), "FIG. 04 · MENISCAL HOOP STRESS HOOKES LAW", font=font_mono_bold, fill=WHITE)
    draw.text((WAVE_X, WAVE_Y + 20), "CIRCUMFERENTIAL TENSILE FIBER RECRUITMENT", font=font_mono_micro, fill=MID_LINE)
    draw.line([(WAVE_X, WAVE_Y + 36), (WAVE_X + 680, WAVE_Y + 36)], fill=MID_LINE, width=1)
    for c_ring in range(5):
        y_c = WAVE_Y + 80 + c_ring * 50
        draw.line([(WAVE_X, y_c), (WAVE_X + 680, y_c)], fill=GRID_HAIRLINE, width=1)
        w_p = [(WAVE_X + xs, y_c + 24 * math.sin(xs * 0.015 * (c_ring + 1)) * math.exp(-xs * 0.002)) for xs in range(0, 680, 4)]
        for p_i in range(len(w_p) - 1):
            draw.line([w_p[p_i], w_p[p_i+1]], fill=CYAN_ACCENT if c_ring < 2 else GOLD_ACCENT, width=1)

    # AUX 6: Bottom-Right — Cartilage Viscoelastic Hysteresis
    TORQ_X, TORQ_Y = W - 920, 2380
    draw.text((TORQ_X, TORQ_Y), "FIG. 05 · VISCOELASTIC HYSTERESIS LOOP", font=font_mono_bold, fill=WHITE)
    draw.text((TORQ_X, TORQ_Y + 20), "ENERGY DISSIPATION IN ARTICULAR CARTILAGE", font=font_mono_micro, fill=MID_LINE)
    draw.line([(TORQ_X, TORQ_Y + 36), (TORQ_X + 720, TORQ_Y + 36)], fill=MID_LINE, width=1)
    h_box = [TORQ_X + 80, TORQ_Y + 60, TORQ_X + 640, TORQ_Y + 260]
    draw.rectangle(h_box, outline=GRID_HAIRLINE, width=1)
    h_pts_up = [(h_box[0] + (step / 50.0) * 560, h_box[3] - 180 * math.sqrt(step / 50.0)) for step in range(51)]
    h_pts_dn = [(h_box[0] + (step / 50.0) * 560, h_box[3] - 180 * ((step / 50.0) ** 1.8)) for step in range(51)]
    for p_i in range(50):
        draw.line([h_pts_up[p_i], h_pts_up[p_i+1]], fill=CYAN_ACCENT, width=2)
        draw.line([h_pts_dn[p_i], h_pts_dn[p_i+1]], fill=GOLD_ACCENT, width=2)
    draw.text((h_box[0] + 16, h_box[1] + 16), "LOADING: RECOVERY PHASE", font=font_mono_micro, fill=WHITE)
    draw.text((h_box[0] + 16, h_box[1] + 32), "AREA = DISSIPATED ENERGY", font=font_mono_micro, fill=MID_LINE)

    # Lower Section
    LOWER_Y = 2820
    draw.line([(M_LEFT + 24, LOWER_Y), (M_RIGHT - 24, LOWER_Y)], fill=MID_LINE, width=1)
    AX1_X = M_LEFT + 40
    draw.text((AX1_X, LOWER_Y + 40), "[AXIOM 03 · BIOLOGICAL OPTIMIZATION]", font=font_mono_bold, fill=GOLD_ACCENT)
    draw.text((AX1_X, LOWER_Y + 70), "The knee joint is an asymmetric four-bar linkage in continuous equilibrium.", font=font_body, fill=WHITE)
    draw.text((AX1_X, LOWER_Y + 95), "Articular surfaces conform under load to minimize shear energy dissipation.", font=font_body, fill=WHITE)
    draw.text((AX1_X, LOWER_Y + 120), "Femoral condylar geometry balances mobility with terminal screw-home stability.", font=font_body, fill=MID_LINE)
    draw.text((AX1_X, LOWER_Y + 145), "Bone mineral density models dynamically in response to applied stress tensors.", font=font_body, fill=MID_LINE)
    draw.text((AX1_X, LOWER_Y + 180), "σ = E·ε + η·dε/dt  |  WOLFF'S LAW CONTINUUM FORMULATION", font=font_mono, fill=CYAN_ACCENT)

    SEAL_X = W // 2
    SEAL_Y = LOWER_Y + 140
    draw.ellipse([SEAL_X - 105, SEAL_Y - 105, SEAL_X + 105, SEAL_Y + 105], outline=GOLD_ACCENT, width=2)
    draw.ellipse([SEAL_X - 60, SEAL_Y - 60, SEAL_X + 60, SEAL_Y + 60], outline=WHITE, width=1)
    st_pts = [(SEAL_X + (52 if si % 2 == 0 else 24) * math.cos(math.radians(si * 25.7 - 90)),
               SEAL_Y + (52 if si % 2 == 0 else 24) * math.sin(math.radians(si * 25.7 - 90))) for si in range(14)]
    for si in range(14):
        draw.line([st_pts[si], st_pts[(si + 1) % 14]], fill=CYAN_ACCENT, width=1)
    sb1 = font_mono_micro.getbbox("ARCADIA BIOMECHANICS LAB")
    draw.text((SEAL_X - (sb1[2] - sb1[0]) // 2, SEAL_Y + 115), "ARCADIA BIOMECHANICS LAB", font=font_mono_micro, fill=GOLD_ACCENT)

    AX2_X = W - M_LEFT - 680
    draw.text((AX2_X, LOWER_Y + 40), "[AXIOM 04 · ANATOMICAL CONTINUUM]", font=font_mono_bold, fill=CYAN_ACCENT)
    draw.text((AX2_X, LOWER_Y + 70), "Every biological movement traces an invariant mathematical path.", font=font_body, fill=WHITE)
    draw.text((AX2_X, LOWER_Y + 95), "From muscular motor units to ground reaction vectors,", font=font_body, fill=WHITE)
    draw.text((AX2_X, LOWER_Y + 120), "human gait embodies evolutionary architectural efficiency.", font=font_body, fill=MID_LINE)
    draw.text((AX2_X, LOWER_Y + 145), "Kinematic intelligence resides within morphological structure itself.", font=font_body, fill=MID_LINE)
    draw.text((AX2_X, LOWER_Y + 180), "ICR(t) = v(t) × ω(t) / ||ω(t)||²  |  INVARIANT ROTATION AXIS", font=font_mono, fill=GOLD_ACCENT)

    draw.line([(M_LEFT + 24, H - 180), (M_RIGHT - 24, H - 180)], fill=MID_LINE, width=1)
    draw.text((M_LEFT + 32, H - 165), "PLATE NO. IX · FINE ART EDITION 2 OF 3", font=font_mono_bold, fill=WHITE)
    cmb = font_mono_small.getbbox("EXHIBITED AT THE CONVERGENCE OF HUMAN MOVEMENT SCIENCE & COMPUTATIONAL TECHNOLOGY")
    draw.text(((W - (cmb[2] - cmb[0])) // 2, H - 165), "EXHIBITED AT THE CONVERGENCE OF HUMAN MOVEMENT SCIENCE & COMPUTATIONAL TECHNOLOGY", font=font_mono_small, fill=GOLD_ACCENT)
    draw.text((M_RIGHT - 340, H - 165), "DESIGNED VIA KINEMATIC MONISM", font=font_mono_bold, fill=CYAN_ACCENT)

    img = apply_grain(img)
    return img

# ==============================================================================
# PLATE 3: CYBERNETIC MANIPULATION · 7-DOF WORKSPACE TOPOLOGY
# ==============================================================================
def render_plate_3():
    print("Synthesizing Plate III: Cybernetic Manipulation (Synthetic Robotics)...")
    CX, CY = W // 2, 1560
    img, draw = init_canvas(CX, CY)
    
    # Header
    draw.text((M_LEFT + 32, 195), "PLATE NO. X · WORKSPACE TOPOLOGY", font=font_mono_bold, fill=GOLD_ACCENT)
    draw.text((M_LEFT + 32, 220), "SPECIMEN: NVIDIA SIMREADY FRANKA RESEARCH 3 (CC BY 4.0)", font=font_mono, fill=WHITE)
    draw.text((M_LEFT + 32, 245), "MANIPULABILITY INDEX: w = √(det(J(q)·J^T(q))) = 0.142", font=font_mono_small, fill=MID_LINE)
    draw.text((M_LEFT + 32, 268), "CARTESIAN REACHABLE WORKSPACE ENVELOPE: RADIUS = 855mm", font=font_mono_small, fill=CYAN_ACCENT)
    draw.text((M_LEFT + 32, 290), "SINGULARITY HULL: det(J) = 0 [WRIST/SHOULDER ALIGNMENT]", font=font_mono_small, fill=MID_LINE)

    title_text = "C Y B E R N E T I C   M A N I P U L A T I O N"
    tw = font_title.getbbox(title_text)[2] - font_title.getbbox(title_text)[0]
    draw.text(((W - tw) // 2, 205), title_text, font=font_title, fill=WHITE)

    sub_text = "7-DOF JACOBIAN MANIPULABILITY & SINGULARITY HULLS"
    sw = font_subtitle.getbbox(sub_text)[2] - font_subtitle.getbbox(sub_text)[0]
    draw.text(((W - sw) // 2, 272), sub_text, font=font_subtitle, fill=GOLD_ACCENT)

    sub_meta = "A TOPOLOGICAL INVESTIGATION OF ISOTROPIC DEXTERITY, TORQUE LIMITS & END-EFFECTOR VELOCITIES"
    smw = font_mono_small.getbbox(sub_meta)[2] - font_mono_small.getbbox(sub_meta)[0]
    draw.text(((W - smw) // 2, 310), sub_meta, font=font_mono_small, fill=MID_LINE)

    draw.text((M_RIGHT - 390, 195), "PAYLOAD: 3.0 kg RATED", font=font_mono_bold, fill=CYAN_ACCENT)
    draw.text((M_RIGHT - 390, 220), "REPEATABILITY: ±0.1mm", font=font_mono, fill=WHITE)
    draw.text((M_RIGHT - 390, 245), "CONTROL CYCLE: 1000 Hz", font=font_mono_small, fill=MID_LINE)
    draw.text((M_RIGHT - 390, 268), "TORQUE SENSORS: 7 × STRAIN", font=font_mono_small, fill=MID_LINE)
    draw.text((M_RIGHT - 390, 290), "NVIDIA SIMREADY CENTRAL", font=font_mono_small, fill=GOLD_ACCENT)

    # Central Robotics Manipulability Astrolabe
    R_OUTER = 720
    draw.ellipse([CX - R_OUTER, CY - R_OUTER, CX + R_OUTER, CY + R_OUTER], outline=WHITE, width=2)
    draw.ellipse([CX - 670, CY - 670, CX + 670, CY + 670], outline=GRID_HAIRLINE, width=1)
    draw.ellipse([CX - 580, CY - 580, CX + 580, CY + 580], outline=CYAN_ACCENT, width=1)
    draw.ellipse([CX - 460, CY - 460, CX + 460, CY + 460], outline=GOLD_MUTED, width=1)
    draw.ellipse([CX - 280, CY - 280, CX + 280, CY + 280], outline=WHITE, width=1)

    for deg in range(360):
        rad = math.radians(deg)
        if deg % 15 == 0:
            draw.line([(CX + 720 * math.cos(rad), CY + 720 * math.sin(rad)), (CX + 700 * math.cos(rad), CY + 700 * math.sin(rad))], fill=BRIGHT_LINE, width=1)
        else:
            draw.line([(CX + 720 * math.cos(rad), CY + 720 * math.sin(rad)), (CX + 712 * math.cos(rad), CY + 712 * math.sin(rad))], fill=SUBTLE_LINE, width=1)

    # Yoshikawa Manipulability Ellipsoids (Concentric Principal Axes Projections)
    glow = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    g_draw = ImageDraw.Draw(glow, "RGBA")
    
    # Draw nested 3D workspace ellipsoids at varying orientations
    for el_i in range(8):
        ang_rot = el_i * (math.pi / 8.0)
        a_axis = 440 - el_i * 35
        b_axis = 220 + el_i * 18
        e_pts = []
        for d in range(361):
            theta = math.radians(d)
            x_raw = a_axis * math.cos(theta)
            y_raw = b_axis * math.sin(theta)
            xr = x_raw * math.cos(ang_rot) - y_raw * math.sin(ang_rot)
            yr = x_raw * math.sin(ang_rot) + y_raw * math.cos(ang_rot)
            e_pts.append((CX + xr, CY + yr))
        for p_i in range(len(e_pts) - 1):
            g_draw.line([e_pts[p_i], e_pts[p_i+1]], fill=(56, 189, 248, 80), width=4)
            
    glow = glow.filter(ImageFilter.GaussianBlur(radius=4))
    img = Image.alpha_composite(img, glow)
    draw = ImageDraw.Draw(img, "RGBA")

    for el_i in range(8):
        ang_rot = el_i * (math.pi / 8.0)
        a_axis = 440 - el_i * 35
        b_axis = 220 + el_i * 18
        e_pts = []
        for d in range(361):
            theta = math.radians(d)
            xr = a_axis * math.cos(theta) * math.cos(ang_rot) - b_axis * math.sin(theta) * math.sin(ang_rot)
            yr = a_axis * math.cos(theta) * math.sin(ang_rot) + b_axis * math.sin(theta) * math.cos(ang_rot)
            e_pts.append((CX + xr, CY + yr))
        for p_i in range(len(e_pts) - 1):
            col = CYAN_ACCENT if el_i == 0 else (GOLD_ACCENT if el_i == 4 else SUBTLE_LINE)
            draw.line([e_pts[p_i], e_pts[p_i+1]], fill=col, width=1)

    # 7-DOF Serial Kinematic Vector Armature
    link_lengths = [95, 120, 110, 105, 95, 75, 55]
    link_angles = [0, 45, -30, 60, -45, 90, 15]
    cur_x, cur_y = CX, CY
    accum_ang = -90
    for idx in range(7):
        accum_ang += link_angles[idx]
        rad = math.radians(accum_ang)
        next_x = cur_x + link_lengths[idx] * math.cos(rad)
        next_y = cur_y + link_lengths[idx] * math.sin(rad)
        draw.line([(cur_x, cur_y), (next_x, next_y)], fill=WHITE, width=3)
        draw.ellipse([cur_x - 8, cur_y - 8, cur_x + 8, cur_y + 8], outline=CYAN_ACCENT, width=2)
        draw.ellipse([cur_x - 3, cur_y - 3, cur_x + 3, cur_y + 3], fill=GOLD_ACCENT)
        draw.text((cur_x + 12, cur_y - 6), f"LINK 0{idx+1}", font=font_mono_micro, fill=WHITE)
        cur_x, cur_y = next_x, next_y

    # End-Effector Terminal Target
    draw.ellipse([cur_x - 14, cur_y - 14, cur_x + 14, cur_y + 14], outline=ROSE_ACCENT, width=2)
    draw.ellipse([cur_x - 4, cur_y - 4, cur_x + 4, cur_y + 4], fill=WHITE)
    draw.text((cur_x + 18, cur_y - 8), "END-EFFECTOR [p_e, R_e]", font=font_mono_bold, fill=ROSE_ACCENT)

    # Auxiliary Figures
    # AUX 1: Top-Left — Cartesian Velocity Limits
    D1_X, D1_Y = 380, 640
    draw.ellipse([D1_X - 115, D1_Y - 115, D1_X + 115, D1_Y + 115], outline=MID_LINE, width=1)
    draw.arc([D1_X - 85, D1_Y - 85, D1_X + 85, D1_Y + 85], start=45, end=270, fill=CYAN_ACCENT, width=3)
    draw.text((D1_X - 95, D1_Y - 145), "FIG. 01 · JOINT VELOCITY SATURATION", font=font_mono_bold, fill=WHITE)
    draw.text((D1_X - 95, D1_Y - 128), "LIMIT: ±150°/s [JOINTS 1..4] | ±180°/s [5..7]", font=font_mono_micro, fill=MID_LINE)
    draw.text((D1_X - 45, D1_Y + 125), "MAX LIN SPEED: 1.7 m/s", font=font_mono_small, fill=CYAN_ACCENT)

    # AUX 2: Top-Right — Cartesian Stiffness Ellipsoid (Impedance Control)
    D2_X, D2_Y = W - 380, 640
    draw.ellipse([D2_X - 115, D2_Y - 115, D2_X + 115, D2_Y + 115], outline=MID_LINE, width=1)
    draw.ellipse([D2_X - 85, D2_Y - 45, D2_X + 85, D2_Y + 45], outline=GOLD_ACCENT, width=2)
    draw.text((D2_X - 95, D2_Y - 145), "FIG. 02 · IMPEDANCE STIFFNESS", font=font_mono_bold, fill=WHITE)
    draw.text((D2_X - 95, D2_Y - 128), "CARTESIAN STIFFNESS TENSOR: K_x, K_y, K_z", font=font_mono_micro, fill=MID_LINE)
    draw.text((D2_X - 40, D2_Y + 125), "K_t: 3000 N/m | K_r: 300 Nm/rad", font=font_mono_small, fill=GOLD_ACCENT)

    # AUX 3: Left Midfield — Forward Kinematics Transformation Chain
    COL_L_X, COL_L_Y = 200, 1080
    draw.text((COL_L_X, COL_L_Y), "FORWARD KINEMATICS CHAIN", font=font_mono_bold, fill=GOLD_ACCENT)
    draw.text((COL_L_X, COL_L_Y + 20), "SE(3) HOMOGENEOUS MATRIX MULTIPLICATION", font=font_mono_micro, fill=MID_LINE)
    draw.line([(COL_L_X, COL_L_Y + 36), (COL_L_X + 340, COL_L_Y + 36)], fill=MID_LINE, width=1)
    for idx in range(7):
        row_y = COL_L_Y + 52 + idx * 82
        draw.text((COL_L_X, row_y), f"T_{idx+1}^{idx}", font=font_mono_bold, fill=WHITE)
        draw.text((COL_L_X + 80, row_y), f"R_{idx+1} ∈ SO(3) | p_{idx+1} ∈ ℝ³", font=font_mono, fill=CYAN_ACCENT)
        draw.text((COL_L_X + 80, row_y + 16), f"DH: a={0}mm, α={90 if idx%2==1 else 0}°, d={120+idx*20}mm", font=font_mono_micro, fill=MID_LINE)
        draw.rectangle([COL_L_X + 80, row_y + 34, COL_L_X + 320, row_y + 39], outline=GRID_HAIRLINE, width=1)
        draw.rectangle([COL_L_X + 80, row_y + 34, COL_L_X + 80 + int((idx + 1) / 7.0 * 240), row_y + 39], fill=GOLD_ACCENT)

    # AUX 4: Right Midfield — Singularity Hull Distance (Damped Least Squares)
    COL_R_X, COL_R_Y = 2160, 1080
    draw.text((COL_R_X, COL_R_Y), "FIG. 03 · SINGULARITY HULL", font=font_mono_bold, fill=GOLD_ACCENT)
    draw.text((COL_R_X, COL_R_Y + 20), "DAMPED LEAST SQUARES REGULARIZATION", font=font_mono_micro, fill=MID_LINE)
    draw.line([(COL_R_X, COL_R_Y + 36), (COL_R_X + 340, COL_R_Y + 36)], fill=MID_LINE, width=1)
    P_BOX = [COL_R_X, COL_R_Y + 52, COL_R_X + 340, COL_R_Y + 52 + 540]
    draw.rectangle(P_BOX, outline=GRID_HAIRLINE, width=1)
    s_pts = []
    for deg in range(0, 140, 2):
        t = deg / 140.0
        px = P_BOX[0] + 20 + t * 300
        # Singularity metric dips near wrist alignment
        py = P_BOX[3] - 20 - 460 * (1.0 - math.exp(-((t - 0.5) ** 2) / 0.04))
        s_pts.append((px, py))
    for p_i in range(len(s_pts) - 1):
        draw.line([s_pts[p_i], s_pts[p_i+1]], fill=ROSE_ACCENT, width=2)
    draw.text((P_BOX[0] + 12, P_BOX[3] - 22), "MIN SINGULAR VALUE: σ_min > 0.015", font=font_mono_micro, fill=WHITE)
    draw.text((P_BOX[2] - 110, P_BOX[3] - 22), "DLS DAMPING: λ² = 0.001", font=font_mono_micro, fill=CYAN_ACCENT)

    # AUX 5: Bottom-Left — Joint Actuator Frequency Response (Bode Plot)
    WAVE_X, WAVE_Y = 200, 2380
    draw.text((WAVE_X, WAVE_Y), "FIG. 04 · ACTUATOR BODE RESPONSE", font=font_mono_bold, fill=WHITE)
    draw.text((WAVE_X, WAVE_Y + 20), "FREQUENCY RESPONSE OF CLOSED-LOOP CURRENT CONTROLLER", font=font_mono_micro, fill=MID_LINE)
    draw.line([(WAVE_X, WAVE_Y + 36), (WAVE_X + 680, WAVE_Y + 36)], fill=MID_LINE, width=1)
    for b_lane in range(3):
        yb = WAVE_Y + 80 + b_lane * 65
        draw.line([(WAVE_X, yb), (WAVE_X + 680, yb)], fill=GRID_HAIRLINE, width=1)
        w_p = [(WAVE_X + xs, yb + 28 * (1.0 / (1.0 + (xs / 200.0) ** (b_lane + 1.5))) - 14) for xs in range(0, 680, 4)]
        for p_i in range(len(w_p) - 1):
            draw.line([w_p[p_i], w_p[p_i+1]], fill=CYAN_ACCENT if b_lane == 0 else GOLD_ACCENT, width=2)

    # AUX 6: Bottom-Right — Kinetic Energy Distribution Across Links
    TORQ_X, TORQ_Y = W - 920, 2380
    draw.text((TORQ_X, TORQ_Y), "FIG. 05 · KINETIC ENERGY DISTRIBUTION", font=font_mono_bold, fill=WHITE)
    draw.text((TORQ_X, TORQ_Y + 20), "GENERALIZED INERTIA MATRIX QUADRATIC FORM", font=font_mono_micro, fill=MID_LINE)
    draw.line([(TORQ_X, TORQ_Y + 36), (TORQ_X + 720, TORQ_Y + 36)], fill=MID_LINE, width=1)
    ke_vals = [220, 185, 140, 110, 80, 50, 25]
    for b_i in range(7):
        bx = TORQ_X + 25 + b_i * 96
        by_b = TORQ_Y + 250
        draw.rectangle([bx, by_b - ke_vals[b_i], bx + 55, by_b], outline=GRID_HAIRLINE, width=1)
        draw.rectangle([bx + 4, by_b - int(ke_vals[b_i] * 0.8), bx + 51, by_b], fill=CYAN_ACCENT)
        draw.text((bx + 12, by_b + 8), f"L{b_i+1}", font=font_mono_bold, fill=WHITE)

    # Lower Section
    LOWER_Y = 2820
    draw.line([(M_LEFT + 24, LOWER_Y), (M_RIGHT - 24, LOWER_Y)], fill=MID_LINE, width=1)
    AX1_X = M_LEFT + 40
    draw.text((AX1_X, LOWER_Y + 40), "[AXIOM 05 · DIFFERENTIAL ROBOTICS]", font=font_mono_bold, fill=GOLD_ACCENT)
    draw.text((AX1_X, LOWER_Y + 70), "The manipulator mapping between joint rates and Cartesian space", font=font_body, fill=WHITE)
    draw.text((AX1_X, LOWER_Y + 95), "is governed by the linear Jacobian operator v_e = J(q)·q̇.", font=font_body, fill=WHITE)
    draw.text((AX1_X, LOWER_Y + 120), "Through redundant degrees of freedom, the null-space projection", font=font_body, fill=MID_LINE)
    draw.text((AX1_X, LOWER_Y + 145), "optimizes joint torque and posture without altering end-effector velocity.", font=font_body, fill=MID_LINE)
    draw.text((AX1_X, LOWER_Y + 180), "q̇ = J^#(q)·v_e + (I - J^# J)·q̇_0  |  NULL-SPACE INVARIANCE", font=font_mono, fill=CYAN_ACCENT)

    SEAL_X = W // 2
    SEAL_Y = LOWER_Y + 140
    draw.ellipse([SEAL_X - 105, SEAL_Y - 105, SEAL_X + 105, SEAL_Y + 105], outline=GOLD_ACCENT, width=2)
    draw.ellipse([SEAL_X - 60, SEAL_Y - 60, SEAL_X + 60, SEAL_Y + 60], outline=WHITE, width=1)
    st_pts = [(SEAL_X + (52 if si % 2 == 0 else 24) * math.cos(math.radians(si * 25.7 - 90)),
               SEAL_Y + (52 if si % 2 == 0 else 24) * math.sin(math.radians(si * 25.7 - 90))) for si in range(14)]
    for si in range(14):
        draw.line([st_pts[si], st_pts[(si + 1) % 14]], fill=CYAN_ACCENT, width=1)
    sb1 = font_mono_micro.getbbox("NVIDIA SIMREADY & ARCADIA")
    draw.text((SEAL_X - (sb1[2] - sb1[0]) // 2, SEAL_Y + 115), "NVIDIA SIMREADY & ARCADIA", font=font_mono_micro, fill=GOLD_ACCENT)

    AX2_X = W - M_LEFT - 680
    draw.text((AX2_X, LOWER_Y + 40), "[AXIOM 06 · CONSERVATION OF MOMENTUM]", font=font_mono_bold, fill=CYAN_ACCENT)
    draw.text((AX2_X, LOWER_Y + 70), "Generalized momentum in articulated serial chains conforms", font=font_body, fill=WHITE)
    draw.text((AX2_X, LOWER_Y + 95), "to closed Hamiltonian dynamics across all operational manifolds.", font=font_body, fill=WHITE)
    draw.text((AX2_X, LOWER_Y + 120), "Torque saturation boundaries demarcate physical interaction safety.", font=font_body, fill=MID_LINE)
    draw.text((AX2_X, LOWER_Y + 145), "Real-time cybernetics bridges digital simulation with physical reality.", font=font_body, fill=MID_LINE)
    draw.text((AX2_X, LOWER_Y + 180), "M(q)·q̈ + C(q, q̇)·q̇ + g(q) = τ  |  EULER-LAGRANGE ROBOTICS", font=font_mono, fill=GOLD_ACCENT)

    draw.line([(M_LEFT + 24, H - 180), (M_RIGHT - 24, H - 180)], fill=MID_LINE, width=1)
    draw.text((M_LEFT + 32, H - 165), "PLATE NO. X · FINE ART EDITION 3 OF 3", font=font_mono_bold, fill=WHITE)
    cmb = font_mono_small.getbbox("EXHIBITED AT THE CONVERGENCE OF HUMAN MOVEMENT SCIENCE & COMPUTATIONAL TECHNOLOGY")
    draw.text(((W - (cmb[2] - cmb[0])) // 2, H - 165), "EXHIBITED AT THE CONVERGENCE OF HUMAN MOVEMENT SCIENCE & COMPUTATIONAL TECHNOLOGY", font=font_mono_small, fill=GOLD_ACCENT)
    draw.text((M_RIGHT - 340, H - 165), "DESIGNED VIA KINEMATIC MONISM", font=font_mono_bold, fill=CYAN_ACCENT)

    img = apply_grain(img)
    return img

# ==============================================================================
# MAIN COMPILATION PIPELINE
# ==============================================================================
if __name__ == "__main__":
    print("Beginning Kinematic Monism Fine Art Trilogy generation...")
    
    p1 = render_plate_1()
    p2 = render_plate_2()
    p3 = render_plate_3()
    
    # Save PNG plates
    plates = [
        ("plate-01-translation-geometry.png", p1),
        ("plate-02-tibiofemoral-kinematics.png", p2),
        ("plate-03-cybernetic-manipulation.png", p3)
    ]
    
    for filename, p_img in plates:
        path_out = os.path.join(OUT_DIR, filename)
        path_brain = os.path.join(BRAIN_DIR, filename)
        path_public = os.path.join(PUBLIC_ART_DIR, filename)
        
        print(f"Exporting {filename} (300 DPI Fine Art)...")
        p_img.save(path_out, format="PNG", dpi=(300, 300))
        p_img.save(path_brain, format="PNG", dpi=(300, 300))
        p_img.save(path_public, format="PNG", dpi=(300, 300))
        
    # Also overwrite the primary plate in root artifacts for backward-compat
    p1.save(os.path.join(OUT_DIR, "kinematic-monism-plate.png"), format="PNG", dpi=(300, 300))
    p1.save(os.path.join(BRAIN_DIR, "kinematic-monism-plate.png"), format="PNG", dpi=(300, 300))
    
    # Generate Multi-Page PDF Folio: Kinematic Monism Trilogy
    print("Compiling 3-Page Archival Folio PDF...")
    pdf_trilogy_path = os.path.join(OUT_DIR, "kinematic-monism-trilogy.pdf")
    pdf_brain_path = os.path.join(BRAIN_DIR, "kinematic-monism-trilogy.pdf")
    
    PDF_W, PDF_H = 1296, 1728
    c = pdf_canvas.Canvas(pdf_trilogy_path, pagesize=(PDF_W, PDF_H))
    
    for filename, _ in plates:
        png_path = os.path.join(OUT_DIR, filename)
        c.drawImage(png_path, 0, 0, width=PDF_W, height=PDF_H)
        c.showPage()
        
    c.save()
    
    import shutil
    shutil.copyfile(pdf_trilogy_path, pdf_brain_path)
    shutil.copyfile(pdf_trilogy_path, os.path.join(PUBLIC_ART_DIR, "kinematic-monism-trilogy.pdf"))
    
    print("ALL TRILOGY PLATES AND MULTI-PAGE ARCHIVAL FOLIO GENERATED SUCCESSFULLY!")
