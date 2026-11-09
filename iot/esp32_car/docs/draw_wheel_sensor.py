"""Rear-wheel tick sensor: back-of-wheel view + top cross-section -> wheel_sensor.png
   python3 draw_wheel_sensor.py   (sizes ~cm, from photos: tyre dia 7, 5-spoke rim, holes between spokes)"""
import math, matplotlib.pyplot as plt
from matplotlib.patches import Circle, Wedge, Rectangle, FancyBboxPatch

fig, (a, b) = plt.subplots(1, 2, figsize=(13, 6.2))
for ax in (a, b): ax.set_aspect("equal"); ax.axis("off")

# --- 1. back of the wheel, face on ---
a.set_title("1. BACK of the rear wheel (the side facing the car)", fontsize=11, fontweight="bold")
a.add_patch(Circle((0, 0), 3.5, fc="#333", ec="k"))                 # tyre
a.add_patch(Circle((0, 0), 2.3, fc="#555", ec="k"))                 # rim
a.add_patch(Circle((0, 0), 1.95, fc="#555", ec="#222"))
for i in range(5):                                                  # holes between spokes
    c = 90 + i * 72 + 36
    a.add_patch(Wedge((0, 0), 1.9, c - 22, c + 22, width=1.0, fc="white", ec="#888"))
for i in range(5):                                                  # tape on each spoke
    c = math.radians(90 + i * 72)
    x, y = 1.4 * math.cos(c), 1.4 * math.sin(c)
    a.add_patch(Rectangle((x - .25, y - .25), .5, .5, angle=0, fc="#fffbe0", ec="#c9a227", lw=1.5))
a.add_patch(Circle((0, 0), 0.6, fc="#222", ec="k")); a.text(0, 0, "hub", color="w", ha="center", va="center", fontsize=8)
a.add_patch(Circle((1.4 * math.cos(math.radians(90)), 1.4), 0.38, fill=False, ec="red", lw=2.5, ls="--"))
a.annotate("sensor looks HERE\n(1.5 cm out from the centre)", xy=(0.3, 1.6), xytext=(1.6, 4.3), color="red",
           fontsize=9, arrowprops=dict(arrowstyle="->", color="red"))
a.annotate("white tape on each\nspoke (5 pieces)", xy=(1.4 * math.cos(math.radians(162)), 1.4 * math.sin(math.radians(162))),
           xytext=(-5.2, 3.2), fontsize=9, arrowprops=dict(arrowstyle="->"))
a.annotate("open holes\n(see-through = 'no')", xy=(1.4 * math.cos(math.radians(234)), 1.4 * math.sin(math.radians(234))),
           xytext=(-5.4, -3.6), fontsize=9, arrowprops=dict(arrowstyle="->"))
a.text(0, -4.6, "white spoke -> tick, hole -> nothing:  5 ticks per wheel turn", ha="center", fontsize=9.5, fontweight="bold")
a.set_xlim(-6, 6); a.set_ylim(-5.2, 5.2)

# --- 2. seen from above: axle tube, sensor, wheel ---
b.set_title("2. Seen from ABOVE (rear left corner)", fontsize=11, fontweight="bold")
b.add_patch(Rectangle((-6, -.5), 5.2, 1.0, fc="#444", ec="k")); b.text(-3.4, 0, "rear axle tube", color="w", ha="center", va="center", fontsize=8.5)
b.add_patch(Rectangle((-8, -1.6), 2.0, 3.2, fc="#666", ec="k")); b.text(-7, 0, "gear\nbox", color="w", ha="center", va="center", fontsize=8)
b.add_patch(Rectangle((0, -3.5), 3.0, 7.0, fc="#333", ec="k")); b.text(1.5, 2.6, "tyre", color="w", ha="center", fontsize=8.5)
b.add_patch(Rectangle((-0.2, -2.3), 0.5, 4.6, fc="#555", ec="k")); b.text(0.05, -2.8, "spokes\n+ tape", ha="center", va="top", fontsize=8)
b.add_patch(Rectangle((-0.8, -0.35), 0.8, 0.7, fc="#222", ec="k"))    # hub
# sensor: clipped under/beside the tube end, eyes facing the spokes
b.add_patch(FancyBboxPatch((-3.2, 0.75), 1.9, 0.9, boxstyle="round,pad=0.02", fc="#1f4e9c", ec="k"))
b.text(-2.25, 1.2, "FC-51", color="w", ha="center", va="center", fontsize=8)
b.add_patch(Circle((-1.2, 1.0), 0.14, fc="#ddd", ec="k")); b.add_patch(Circle((-1.2, 1.4), 0.14, fc="k"))
b.annotate("", xy=(-0.25, 1.2), xytext=(-1.1, 1.2), arrowprops=dict(arrowstyle="<->", color="red", lw=1.5))
b.text(-0.7, 1.95, "0.5-1 cm", color="red", ha="center", fontsize=9, fontweight="bold")
b.plot([-2.6, -2.6], [-0.6, 1.7], color="#c9a227", lw=3); b.text(-2.6, -1.0, "zip tie +\nhot glue", ha="center", va="top", fontsize=8)
b.add_patch(Rectangle((-5.2, 1.9), 0.8, 2.3, fc="none", ec="#b05", hatch="///")); b.text(-4.8, 4.4, "shock spring:\nkeep clear", color="#b05", ha="center", fontsize=8)
b.annotate("wire: along the tube,\nzip-tie it, leave a\nslack loop -> pin 35", xy=(-3.2, 1.2), xytext=(-8.6, 3.2), fontsize=8.5,
           arrowprops=dict(arrowstyle="->"))
b.text(-3, -4.6, "Sensor rides on the axle tube, so the gap stays the same when the suspension moves.", ha="center", fontsize=9)
b.set_xlim(-9, 3.5); b.set_ylim(-5.2, 5.2)
plt.tight_layout()
plt.savefig(__file__.replace("draw_wheel_sensor.py", "wheel_sensor.png"), dpi=120)
