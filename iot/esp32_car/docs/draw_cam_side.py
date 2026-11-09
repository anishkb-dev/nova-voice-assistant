"""Side view (cross-section through the camera plate) of the front of the car -> cam_side.png
   python3 draw_cam_side.py      Numbers (cm) match print_template.py page 3 and the 3D-scan fit."""
import math, matplotlib.pyplot as plt
from matplotlib.patches import Rectangle, Polygon, Circle

FLOOR = 12.8; BASE_T = 0.6; L = 12.0; M = 0.6; T = 0.3; H = 4.0   # tray floor height on 40mm standoffs
top = FLOOR + BASE_T                                              # tray floor, inside
wi = L - M - T                                                    # front wall inner face (x)
fig, ax = plt.subplots(figsize=(11, 7)); ax.set_aspect("equal"); ax.axis("off")

for wx in (-2.5, 14.5):                                           # wheels, 17cm wheelbase, tyre dia 7
    ax.add_patch(Circle((wx, 3.5), 3.5, fc="#eee", ec="#888"))
ax.add_patch(Rectangle((1.5, 2.8), 9, 6, fc="#f4f4f4", ec="#888")); ax.text(6, 5.5, "chassis box", ha="center", fontsize=7, color="#666")
for sx in (2.5, 9.5):
    ax.add_patch(Rectangle((sx - .2, 8.8), .4, 4.0, fc="#c9a227", ec="k", lw=.5))
ax.text(10, 10.6, "M3 x 40\nstandoffs", fontsize=6.5)

ax.add_patch(Rectangle((0, FLOOR), L, BASE_T, fc="#fff", ec="k", lw=1.2)); ax.text(3, FLOOR - .7, "tray base (2 sheets)", fontsize=6.5)
ax.add_patch(Rectangle((wi, top), T, H, fc="#fff", ec="k", lw=1.2)); ax.text(wi + T + .15, top + H - .4, "front wall", fontsize=6.5)
ax.add_patch(Rectangle((M, top), T, H, fc="#fff", ec="k", lw=1.2)); ax.text(M + .5, top + H - .4, "back wall", fontsize=6.5)

# sonar: cans through the wall at 2.1 above the base (beside the plate, not behind it -> drawn faint)
sy = top + 2.1
ax.add_patch(Rectangle((wi - .2, sy - 1.0), .2, 2.0, fc="#ddd", ec="#999", ls="--"))
ax.add_patch(Rectangle((wi + T, sy - .8), 1.2, 1.6, fc="#e8e8e8", ec="#999", ls="--"))
ax.text(wi + T + 1.4, sy, "sonar (to the side\nof the camera)", fontsize=6.5, color="#777", va="center")

# plate + brace + shim + CAM
ph = H + 4.5
ax.add_patch(Rectangle((wi - T, top), T, ph, fc="#cfe3ff", ec="k", lw=1.2))
ax.text(wi - T - .15, top + ph - .3, "plate", ha="right", fontsize=7)
ax.add_patch(Polygon([(wi - T, top), (wi - T - 2.5, top), (wi - T, top + 6)], fc="#e3eeff", ec="k", lw=1))
ax.text(wi - T - 1.0, top + 1.0, "brace", ha="right", fontsize=7)
wy0 = top + H + 0.2
ax.add_patch(Rectangle((wi - T, wy0), T, 2.4, fc="white", ec="k", lw=.6, hatch="//"))
ax.text(wi - T - .15, wy0 + 1.2, "pin window ->\nwires plug in here", ha="right", fontsize=6.5, va="center")
sh0 = wy0 + 2.4
ax.add_patch(Rectangle((wi, sh0), 0.6, 0.6, fc="#ffe9a8", ec="k", lw=1)); ax.text(wi + .9, sh0 - .5, "tilt shim", fontsize=6.5, va="center")
b0, b1 = (wi, top + H + 0.1), (wi + 0.6, top + H + 4.1)           # CAM board leans on the shim
tilt = math.atan2(b1[0] - b0[0], b1[1] - b0[1])                   # lean from vertical = down-tilt of the lens
ax.plot([b0[0], b1[0]], [b0[1], b1[1]], color="#1a6b2f", lw=4, solid_capstyle="butt")
lx, ly = b0[0] + 0.6 * 0.55 + .1, b0[1] + 4 * 0.55               # lens ~mid-upper board
ax.add_patch(Rectangle((lx, ly - .35), .55, .7, fc="#333", ec="k"))
ax.text(lx + 1.2, ly + 1.6, f"ESP32-CAM (lens ~{ly:.0f} cm up,\ntilted {math.degrees(tilt):.0f} deg down)", fontsize=7)

# field of view: ~+-21 deg vertical around the tilted axis
for half, style in ((21, "-"), (-21, "-"), (0, ":")):
    a = math.radians(-math.degrees(tilt) + half)
    if a < 0:
        d = (ly) / math.tan(-a); ax.plot([lx + .55, lx + .55 + d], [ly, 0], "r" + style, lw=.8)
        if half == -21: ax.text(lx + d, .6, f"sees floor from ~{d:.0f} cm ahead", fontsize=7, color="r", ha="center")
    else:
        ax.plot([lx + .55, lx + .55 + 22], [ly, ly + 22 * math.tan(a)], "r" + style, lw=.8)

ax.annotate("", xy=(-1.5, top + ph), xytext=(-1.5, 0), arrowprops=dict(arrowstyle="<->", lw=.6))
ax.text(-1.7, (top + ph) / 2, f"{top + ph:.1f} cm", rotation=90, ha="right", va="center", fontsize=7)
ax.text(-2, top + ph + 2.2, "SIDE VIEW  (front of the car -> right)", fontsize=10, fontweight="bold")
ax.set_xlim(-6, 48); ax.set_ylim(-1, top + ph + 3.5)
plt.savefig(__file__.replace("draw_cam_side.py", "cam_side.png"), dpi=130, bbox_inches="tight")
