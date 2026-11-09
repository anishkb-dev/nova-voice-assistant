"""Draws the crawler mounting layout -> layout.png.  python3 draw_layout.py"""
import os
import matplotlib.pyplot as plt
from matplotlib.patches import FancyBboxPatch, Circle, Polygon

C = dict(power="#f4a6a6", motor="#c8c8c8", brain="#9cc3f0", sensor="#a8e0a8",
         cam="#d4b3f0", deck="#e8d8b8", chassis="#8a8a8a")

def box(ax, x, y, w, h, text, kind, fs=8, rot=0):
    ax.add_patch(FancyBboxPatch((x, y), w, h, boxstyle="round,pad=0.05,rounding_size=0.3",
                                fc=C[kind], ec="black", lw=1.2))
    ax.text(x + w / 2, y + h / 2, text, ha="center", va="center", fontsize=fs, rotation=rot)

def note(ax, xy, xytext, text):
    ax.annotate(text, xy=xy, xytext=xytext, fontsize=7.5, color="#333",
                arrowprops=dict(arrowstyle="->", color="#555", lw=0.8))

def setup(ax, title, xlim, ylim):
    ax.set_xlim(*xlim); ax.set_ylim(*ylim); ax.set_aspect("equal"); ax.axis("off")
    ax.set_title(title, fontsize=12, fontweight="bold", loc="left")
    ax.annotate("FRONT", xy=(xlim[1] - 0.5, ylim[0] + 1), xytext=(xlim[1] - 5, ylim[0] + 1),
                fontsize=9, fontweight="bold", va="center",
                arrowprops=dict(arrowstyle="-|>", lw=2))

fig = plt.figure(figsize=(14, 16))

# ---------------- SIDE VIEW ----------------
ax = fig.add_axes([0.03, 0.66, 0.94, 0.32])
setup(ax, "1. SIDE VIEW", (-3, 41), (-1, 21))
for wx in (6, 26):
    ax.add_patch(Circle((wx, 3.5), 3.5, fc="#333", ec="black"))
    ax.add_patch(Circle((wx, 3.5), 1.3, fc="#777"))
box(ax, 1, 4.5, 30, 1, "", "chassis")
ax.text(16, 5, "CHASSIS", ha="center", va="center", color="white", fontsize=8, fontweight="bold")
box(ax, 3, 5.7, 5, 2.4, "drive\nmotor", "motor")
box(ax, 9, 5.7, 4.5, 3.2, "L298N\n(heatsink up)", "power", fs=7)
box(ax, 14.5, 5.7, 7, 2.6, "BATTERY 2S\n(velcro)", "power")
box(ax, 22.5, 5.7, 2.8, 2, "UBEC", "power", fs=7)
box(ax, 26.2, 5.7, 4.3, 2.4, "steer\nmotor", "motor")
for sx in (2, 14, 30):                                   # standoffs
    ax.plot([sx, sx], [5.5, 12], color="#b07000", lw=3)
box(ax, 1, 12, 30, 0.8, "", "deck")
ax.text(16, 11.4, "TOP DECK on 30-40mm standoffs", ha="center", fontsize=7.5, color="#7a5000")
box(ax, 2.5, 12.9, 7, 1.3, "ESP32", "brain")
ax.add_patch(Polygon([[10.5, 12.9], [13.5, 12.9], [13.5, 15.3], [10.5, 14.1]], fc="#222", ec="black"))
ax.text(12, 16, "OLED\n(tilted up)", ha="center", fontsize=7)
box(ax, 17.5, 12.9, 7, 1.1, "Pi Zero 2 WH", "brain", fs=7.5)
box(ax, 25.5, 12.9, 1.6, 2.2, "", "sensor")              # servo
ax.text(26.3, 12.4, "servo", ha="center", fontsize=6.5)
box(ax, 24.5, 15.3, 4, 1.8, "sonar", "sensor", fs=7)
ax.add_patch(Polygon([[30.2, 12.8], [31.8, 12.8], [31.8, 15.2], [30.2, 15.2]], fc="#555", ec="black"))
box(ax, 31.9, 13, 1.6, 2, "", "cam")                     # camera, tilted down
ax.plot([33.5, 38.5], [14, 9.2], "m--", lw=1.2); ax.plot([33.5, 38.5], [14, 14.8], "m--", lw=1.2)
ax.text(37, 16, "camera view\ntilted 10-15° down", fontsize=7, color="purple", ha="center")
note(ax, (32.7, 15.1), (33.5, 19), "Camera Module 3 Wide\non a rigid L-bracket\n(must NEVER move)")
note(ax, (6, 14.2), (1, 18.5), "ESP at the REAR,\nfar from steer motor")
note(ax, (18, 7), (18, 1.2), "battery low + centred\n= won't tip")
note(ax, (28, 8.1), (33, 7), "104 cap on each motor\n+ twisted leads")

# ---------------- CHASSIS (BOTTOM) TOP VIEW ----------------
ax = fig.add_axes([0.03, 0.34, 0.94, 0.30])
setup(ax, "2. CHASSIS LAYER, seen from above", (-3, 41), (-3, 21))
for wx in (6, 26):
    for wy in (-1.5, 15.5):
        box(ax, wx - 3, wy, 6, 3, "", "motor")
box(ax, 0.5, 1.5, 31, 14, "", "chassis")
box(ax, 2, 6, 4.5, 5, "drive\nmotor", "motor")
box(ax, 8, 4, 5.5, 5.5, "L298N\nM3 screws +\nnylon spacers", "power", fs=7)
box(ax, 14.5, 4.5, 8, 8, "BATTERY 2S\n\nvelcro strap\n+ pad under", "power")
box(ax, 23.5, 11, 3.5, 3, "UBEC\nfoam tape", "power", fs=6.5)
box(ax, 26.5, 5.5, 4.5, 5, "steer\nmotor", "motor")
box(ax, 8.5, 11, 4.5, 1.6, "divider (shrink)", "power", fs=6)
ax.plot([22.5, 24.5], [4.8, 2.4], color="red", lw=2)
ax.text(24.6, 1.8, "SM-4P = power switch\n(reachable)", fontsize=7)
ax.plot([14.5, 12.8], [12, 14.6], color="white", lw=2)
ax.text(8.2, 13.6, "white balance lead\n(charging, reachable)", fontsize=6.5, color="white")
ax.plot([6.5, 8], [8.5, 7.5], color="black", lw=2.5)
ax.plot([26.5, 25, 13, 13], [6, 3.9, 3.9, 4], color="black", lw=2.5, ls=(0, (3, 1)))
ax.text(19, 2.6, "twisted motor leads along the frame", fontsize=6.5, ha="center")

# ---------------- TOP DECK TOP VIEW ----------------
ax = fig.add_axes([0.03, 0.02, 0.94, 0.30])
setup(ax, "3. TOP DECK, seen from above", (-3, 41), (-3, 21))
box(ax, 0.5, 1.5, 31, 14, "", "deck")
for sx, sy in ((2, 2.5), (2, 14.5), (14, 2.5), (14, 14.5), (30, 2.5), (30, 14.5)):
    ax.add_patch(Circle((sx, sy), 0.5, fc="#b07000"))
box(ax, 2.5, 4.5, 5, 8.5, "ESP32\n\nfoam tape\nor header\nboard", "brain", fs=7)
ax.annotate("USB at the edge\n(flashing)", xy=(2.5, 11), xytext=(-2.8, 17.5), fontsize=7,
            arrowprops=dict(arrowstyle="->", lw=0.8))
box(ax, 9, 9.5, 4, 3, "OLED", "brain", fs=7)
box(ax, 18, 4, 9, 5, "Pi Zero 2 WH\nM2.5 standoffs", "brain", fs=7.5)
box(ax, 22, 11, 4, 3, "servo +\nsonar", "sensor", fs=7)
box(ax, 29.3, 6.5, 2.2, 3, "CAM", "cam", fs=7)
ax.plot([27, 29.3], [6.5, 8], color="purple", lw=3)
ax.text(27.2, 5.2, "ribbon", fontsize=6.5, color="purple")
ax.plot([31.5, 39], [8, 3], "m--", lw=1.2); ax.plot([31.5, 39], [8, 13], "m--", lw=1.2)
ax.text(35.5, 8, "120°\nview", fontsize=8, color="purple", ha="center", va="center")
ax.text(9, 3, "wires from the chassis\ncome up through a hole here", fontsize=6.5, ha="center")

# legend
for i, (k, lab) in enumerate([("power", "power"), ("motor", "motors"), ("brain", "brains/display"),
                              ("sensor", "sonar/servo"), ("cam", "camera")]):
    fig.patches.append(FancyBboxPatch((0.55 + i * 0.09, 0.325), 0.015, 0.008, transform=fig.transFigure,
                                      fc=C[k], ec="black", boxstyle="square,pad=0"))
    fig.text(0.568 + i * 0.09, 0.329, lab, fontsize=8, va="center")

out = os.path.join(os.path.dirname(os.path.abspath(__file__)), "layout.png")
fig.savefig(out, dpi=110, bbox_inches="tight", facecolor="white")
print(out)
