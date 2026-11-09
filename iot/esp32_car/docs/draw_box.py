"""Cutting plan for the open-top PVC tray -> box.png
   python3 draw_box.py L W H     (cm: chassis length, width across tyres, wall height)"""
import os, sys
import matplotlib.pyplot as plt
from matplotlib.patches import Rectangle, Circle, Polygon

L, W, H = (float(a) for a in sys.argv[1:4]) if len(sys.argv) == 4 else (24, 16, 4)  # example sizes
T = 0.5                                     # board thickness (5 mm)
SHEET = (21, 29.7)                          # A4, cm
PVC, CUT, HOLE = "#f2f2f2", "#d9534f", "#5b9bd5"

def piece(ax, x, y, w, h, name, fc=PVC):
    ax.add_patch(Rectangle((x, y), w, h, fc=fc, ec="black", lw=1.5))
    ax.text(x + w / 2, y + h / 2, f"{name}\n{w:g} × {h:g} cm", ha="center", va="center", fontsize=9)

def sheet(ax, x, title):
    ax.add_patch(Rectangle((x, 0), *SHEET, fc="none", ec="#999", lw=1, ls="--"))
    ax.text(x + SHEET[0] / 2, SHEET[1] + 0.6, title, ha="center", fontsize=9, color="#666")

fig = plt.figure(figsize=(15, 15))

# ---- 1. cutting plan on A4 sheets ----
ax = fig.add_axes([0.03, 0.52, 0.94, 0.45]); ax.set_aspect("equal"); ax.axis("off")
ax.set_title(f"1. CUT THESE 5 PIECES  (5 mm PVC foam, A4 sheets)   L={L:g}  W={W:g}  H={H:g} cm",
             loc="left", fontsize=13, fontweight="bold")
sheet(ax, 0, "sheet 1"); sheet(ax, 23, "sheet 2")
piece(ax, 0.5, 0.5, W, L, "BASE")
side = L - 2 * T                           # sides fit between front + back walls
for i, (h, n) in enumerate(((side, "SIDE"), (side, "SIDE"), (W, "FRONT"), (W, "BACK"))):
    piece(ax, 23.5 + i * (H + 0.6), 0.5, H, h, n)  # all 4 walls as vertical strips on sheet 2
ax.set_xlim(-1, 46); ax.set_ylim(-1, 32)
ax.text(0, -0.8, "Score 3–4 light passes along a steel ruler, then snap. Sides are 1 cm shorter than L "
        "because they sit BETWEEN the front and back walls.", fontsize=9)

# ---- 2. assembled view ----
ax = fig.add_axes([0.03, 0.05, 0.42, 0.42]); ax.set_aspect("equal"); ax.axis("off")
ax.set_title("2. GLUE: walls stand ON the base edges", loc="left", fontsize=13, fontweight="bold")
dx, dy = 0.45, 0.35                         # oblique depth
def face(pts, fc):
    ax.add_patch(Polygon(pts, fc=fc, ec="black", lw=1.3))
b = [(0, 0), (L, 0), (L + W * dx, W * dy), (W * dx, W * dy)]
face(b, "#e6e6e6")                                                 # base
face([(W*dx, W*dy), (L+W*dx, W*dy), (L+W*dx, W*dy+H), (W*dx, W*dy+H)], "#d0d0d0")  # back wall
face([(0, 0), (W*dx, W*dy), (W*dx, W*dy+H), (0, H)], "#c4c4c4")    # rear side
face([(L, 0), (L+W*dx, W*dy), (L+W*dx, W*dy+H), (L, H)], "#bdbdbd")  # front side
face([(0, 0), (L, 0), (L, H), (0, H)], "#f7f7f7cc")                # near wall
ax.add_patch(Circle((L + W*dx*0.5, W*dy*0.5 + H*0.5), H * 0.18, fc=HOLE, ec="black"))
ax.annotate("sonar window", (L + W*dx*0.5, W*dy*0.5 + H*0.5), (L * 0.6, -3), fontsize=8,
            arrowprops=dict(arrowstyle="->"))
cx, cy = L + W*dx*0.5, W*dy*0.5 + H                       # top-centre of the front wall
face([(cx-1, cy), (cx+0.3, cy), (cx+0.3, cy+2.2), (cx-1, cy+2.2)], "#555")       # L-bracket
face([(cx+0.3, cy+0.6), (cx+1.6, cy+0.3), (cx+1.6, cy+1.9), (cx+0.3, cy+2.0)], "#d4b3f0")  # camera, tilted down
ax.plot([cx+1.6, cx+7], [cy+1.1, cy-2.5], "m--", lw=1); ax.plot([cx+1.6, cx+7], [cy+1.1, cy+3.2], "m--", lw=1)
ax.annotate("Camera Module 3 Wide on a rigid\nL-bracket ON TOP of the front wall,\ntilted 10-15° down (walls must not\nbe in its 120° view)",
            (cx, cy+2.2), (L*0.35, W*dy + H + 4), fontsize=8, arrowprops=dict(arrowstyle="->"))
ax.annotate("hot-glue bead along\nevery INSIDE corner", (W*dx + 1, W*dy + 0.3), (-2, W*dy + H + 3),
            fontsize=8, arrowprops=dict(arrowstyle="->"))
ax.annotate("FRONT →", (L + W*dx + 1, W*dy/2), fontsize=10, fontweight="bold")
ax.set_xlim(-4, L + W*dx + 9); ax.set_ylim(-5, W*dy + H + 9)

# ---- 3. holes + layout, top view (tray sits on standoffs ABOVE the tyres) ----
# ponytail: placements are hand-tuned for the measured 12 x 17 cm tray; re-tune if L/W change a lot
ax = fig.add_axes([0.52, 0.05, 0.45, 0.42]); ax.set_aspect("equal"); ax.axis("off")
ax.set_title("3. LAYOUT + HOLES (top view)", loc="left", fontsize=13, fontweight="bold")
ax.add_patch(Rectangle((0, 0), L, W, fc=PVC, ec="black", lw=2))
def hole(x, y, w, h, label, lx, ly, c=HOLE):
    ax.add_patch(Rectangle((x, y), w, h, fc=c, ec="black"))
    if label: ax.annotate(label, (x + w/2, y + h/2), (lx, ly), fontsize=8, arrowprops=dict(arrowstyle="->", lw=0.8))
def part(x, y, w, h, n, fc="none"):
    ax.add_patch(Rectangle((x, y), w, h, fc=fc, ec="#666", ls="--" if fc == "none" else "-"))
    ax.text(x + w/2, y + h/2, n, ha="center", va="center", fontsize=7, color="#333")
hole(-T, 1.4, T*2, 2.6, "USB slot in BACK wall\n(flash the ESP)", -7, W + 2)
hole(L-T, W/2 - 2.2, T*2, 4.4, "sonar window\nin FRONT wall", L + 1.5, -4.5)
hole(L/2 - 0.5, W/2 - 1.6, 3, 3.2, "wire hole in the BASE:\nwires up from L298N,\nUBEC, battery below", -7, -4.5, CUT)
# standoffs stand on the CHASSIS BOX (~9 x 6 cm, from the 3D scan) -> holes in a 7 x 5 cm rectangle, centred
for x, y in ((L/2 - 3.5, W/2 - 2.5), (L/2 + 3.5, W/2 - 2.5), (L/2 - 3.5, W/2 + 2.5), (L/2 + 3.5, W/2 + 2.5)):
    ax.add_patch(Circle((x, y), 0.3, fc="black"))
ax.annotate("4 M3 holes, 7 x 5 cm apart,\nCENTRED (match the chassis box)", (L/2 + 3.5, W/2 + 2.5), (L + 1.5, W + 2),
            fontsize=8, arrowprops=dict(arrowstyle="->", lw=0.8))
part(0.5, 0.4, 7.6, 5.0, "ESP32 on screw board\n(keep clear of bolt heads)")
part(0.6, W*0.68, 2.7, 2.7, "OLED")
part(L/2 - 3.2, W/2 - 1, 1.6, 2, "IMU")
part(L - 2.3, W/2 - 2.2, 1.8, 4.4, "sonar")
part(L/2 - 1.5, W - 4.6, 6.5, 3, "Pi Zero 2 WH (later)", "#9cc3f0")
ax.add_patch(Rectangle((L-0.2, W - 4.3), 1.4, 1.8, fc="#d4b3f0", ec="black"))
ax.annotate("camera on top of\nfront wall", (L+0.5, W - 2.5), (L + 2, W*0.68 + 4), fontsize=8,
            arrowprops=dict(arrowstyle="->", lw=0.8))
ax.text(L/2, -2.2, "UNDER the tray, on the chassis: battery (low, centred), L298N, UBEC",
        ha="center", fontsize=8, style="italic")
ax.annotate("FRONT →", (L + 1.2, W*0.45), fontsize=10, fontweight="bold")
ax.set_xlim(-9, L + 9); ax.set_ylim(-6, W + 5)

out = os.path.join(os.path.dirname(os.path.abspath(__file__)), "box.png")
fig.savefig(out, dpi=100, bbox_inches="tight", facecolor="white"); print(out)
