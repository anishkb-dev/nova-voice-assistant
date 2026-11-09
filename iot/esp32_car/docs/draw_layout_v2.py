"""Rebuild layout, TO SCALE from measured parts -> layout_v2.png
   python3 draw_layout_v2.py      x = side-side 0..17 (car's left = 0), y = back 0 -> front 12, cm.
   5 mm PVC walls 0.6 in from the edge -> inside of the tray is x 1.1..15.9, y 1.1..10.9.
   Hole / slot positions here must match base_v2() + walls_v2() in print_template.py."""
import matplotlib.pyplot as plt
from matplotlib.patches import Rectangle, FancyBboxPatch, Circle, FancyArrowPatch

fig, (a, b) = plt.subplots(1, 2, figsize=(17, 8.5), gridspec_kw={"width_ratios": [1.55, 1]})
for ax in (a, b): ax.set_aspect("equal"); ax.axis("off")

def part(ax, x, y, w, h, label, fc, fs=7, tc="k", ls="-", alpha=1):
    ax.add_patch(FancyBboxPatch((x, y), w, h, boxstyle="round,pad=0,rounding_size=0.12", fc=fc, ec="k", lw=1, ls=ls, alpha=alpha))
    ax.text(x + w / 2, y + h / 2, label, ha="center", va="center", fontsize=fs, color=tc)

def route(ax, pts, col, lw=2.2, ls="-"):
    xs, ys = zip(*pts); ax.plot(xs, ys, color=col, lw=lw, ls=ls, solid_capstyle="round", alpha=.9, zorder=5)

BLUE, RED, ORANGE, BLACK = "#2f6fdf", "#e04b3a", "#f08a24", "#333"

# ---------------- TOP VIEW ----------------
a.set_title("UPPER BASE — top view, to scale (cm), front of car at the top", fontsize=12, fontweight="bold")
a.add_patch(Rectangle((0, 0), 17, 12, fc="#f7f3ea", ec="k", lw=1.5))
for r in [(0.6, 0.6, 15.8, .5), (0.6, 10.9, 15.8, .5), (0.6, 1.1, .5, 9.8), (15.9, 1.1, .5, 9.8)]:
    a.add_patch(Rectangle(r[:2], r[2], r[3], fc="#999", ec="none"))                         # walls
for i in range(18): a.text(i, -.25, str(i), ha="center", va="top", fontsize=5, color="#888")   # cm ruler
for j in range(13): a.text(-.25, j, str(j), ha="right", va="center", fontsize=5, color="#888")
for (x, y, w, d) in [(5.55, 3.25, 1.95, .5), (9.5, 3.25, 1.95, .5), (5.55, 8.25, 1.95, .5), (9.5, 8.25, 1.95, .5),
                     (5.55, 3.75, .5, 1.25), (5.55, 7.0, .5, 1.25), (10.95, 3.75, .5, 1.25), (10.95, 7.0, .5, 1.25)]:   # riser corner posts below, open sides
    a.add_patch(Rectangle((x, y), w, d, fill=False, ec="#b5651d", lw=1.4, ls="--", zorder=4))
a.text(8.5, 3.15, "riser posts below (open sides)", ha="center", va="top", fontsize=6.5, color="#b5651d", zorder=6)

# signal side (left)
part(a, 1.2, 1.2, 5.0, 6.8, "ESP32 +\nexpansion board\n6.8 x 5\n\n4 nylon standoffs\nUSB -> back slot\n\n1000µF on its\n5V + GND pins", "#dce8fb", 7.5)
part(a, 2.35, 10.25, 2.5, 0.6, "OLED (front wall)", "#e6e6e6", 5.5)
part(a, 4.0, 8.6, 2.0, 1.6, "MPU\n2.0 x 1.6", "#d8f0ff")
# centre
part(a, 6.65, 2.15, 3.7, 7.0, "BATTERY 2S\n7 x 3.7 x 1.8\n\nvelcro + strap\n(lifts out)", "#ffe7a3", 8)
part(a, 6.4, 1.15, 4.5, 0.9, "UBEC ON ITS EDGE\n5V out ←   ← 8V in", "#ffd0c8", 5.5)
part(a, 6.25, 10.15, 4.5, 0.7, "sonar PCB (in front wall)", "#cfe8cf", 6)
# power side (right)
part(a, 11.2, 7.9, 4.0, 3.0, "camera bracket\n+ ESP32-CAM\n(plate + braces)", "#e8dff5")
for (x, y, lab, c) in ((13.75, 1.2, "8V\nA", RED), (12.85, 3.4, "8V\nB", RED), (11.5, 3.4, "GND", BLACK)):
    part(a, x, y, 1.3, 2.0, f"Wago\n{lab}", "#fff", 6.5)
    a.add_patch(Rectangle((x, y + 1.75), 1.3, .25, fc=c, ec="none"))
part(a, 15.55, 3.4, 0.35, 4.0, "", "#d8f0ff"); a.text(15.2, 5.4, "INA3221 4 x 3\nstanding on the\nright wall", ha="right", va="center", fontsize=6)
a.add_patch(Rectangle((14.2, 3.3), 1.7, 2.3, fc="none", ec="#aaa", ls=":", lw=1))
a.text(15.05, 4.45, "spare", ha="center", va="center", fontsize=6, color="#888")
part(a, 11.2, 1.1, 2.4, 1.9, "battery plug\n(switch rides on\nthe battery lead)", "#bfe8c8", 5.5)
# holes through the base, inside the riser footprint
part(a, 6.08, 4.1, 0.54, 1.9, "S", BLUE, 7, "w")
part(a, 10.38, 4.1, 0.54, 1.9, "P", RED, 7, "w")
for x in (6.25, 10.45): a.add_patch(Rectangle((x, 6.35), .3, 1.5, fc="k"))                  # battery strap slots
# back wall holes
a.add_patch(Circle((1.6, 0.85), .3, fc="#7d5", ec="k")); a.text(1.6, -.75, "wheel\nsensor", ha="center", va="top", fontsize=6)
a.add_patch(Rectangle((2.4, 0.6), 2.6, .5, fc="#555", ec="k")); a.text(3.7, -.75, "USB slot", ha="center", va="top", fontsize=6)
a.add_patch(Rectangle((9.2, 0.6), 0.8, .5, fc="#ffe7a3", ec="k")); a.text(9.6, -.75, "charge lead\n(high, above\nthe UBEC)", ha="center", va="top", fontsize=6)

# wires: blue = signal, red = 8V, orange = 5V, black = GND
route(a, [(6.35, 4.8), (5.9, 4.8)], BLUE)                                        # 6 L298N signals up S
route(a, [(3.6, 10.25), (3.0, 9.0), (2.6, 7.95)], BLUE, 2)                       # OLED I2C
route(a, [(5.0, 8.6), (5.0, 7.95)], BLUE, 2)                                     # MPU I2C
route(a, [(15.55, 7.2), (10.6, 7.2), (10.6, 10.05), (6.6, 10.05), (6.0, 7.95)], BLUE, 1.6)   # INA I2C -> ESP via the front gap
route(a, [(6.5, 10.15), (6.45, 8.0), (6.15, 7.8)], BLUE, 2)                      # sonar
route(a, [(10.35, 2.4), (11.2, 2.3)], RED)                                       # battery lead (with its switch) -> plug
route(a, [(13.6, 2.1), (13.75, 2.1)], RED)                                       # plug + -> 8V A
route(a, [(14.1, 3.2), (13.8, 3.4)], RED, 1.8)                                   # 8V A -> 8V B link
route(a, [(13.2, 5.4), (13.2, 5.7), (10.65, 5.7), (10.65, 5.5)], RED)              # 8V B -> P (L298N +12V)
route(a, [(13.0, 3.4), (13.0, 3.2), (10.95, 1.8)], RED, 1.8)                     # 8V B -> UBEC in +
route(a, [(13.9, 5.4), (13.9, 5.55), (15.55, 5.55)], RED, 1.3)                                  # 8V B -> INA POW
route(a, [(10.35, 2.6), (10.8, 3.2), (11.7, 3.4)], BLACK, 1.8)                               # battery - -> GND
route(a, [(10.9, 4.4), (11.5, 4.4)], BLACK)                                     # P (L298N GND) -> GND
route(a, [(11.9, 3.4), (11.9, 3.25), (10.95, 1.5)], BLACK, 1.8)                  # GND -> UBEC in -
route(a, [(6.4, 1.6), (6.2, 1.6)], ORANGE)                                       # UBEC out -> ESP 5V
route(a, [(6.2, 7.6), (6.55, 9.95), (10.9, 9.95)], ORANGE, 1.3, ":")             # ESP 5V/GND -> camera
a.text(8.5, -2.4, "Blue = signals, red = 8V, black = GND, orange = 5V.  S / P = signal / power holes (inside the riser).\n"
       "Black bars beside the battery = strap slots.  No wire crosses the battery; the front gap carries sonar, cam 5V and the INA I2C.\nBattery lifts out: only its plug + strap hold it.  Front gap (battery <-> sonar) = 1 cm for the wire bundle.",
       ha="center", fontsize=8)
a.set_xlim(-1, 18); a.set_ylim(-3.2, 12.3)

# ---------------- SIDE VIEW ----------------
b.set_title("RISER BAY — side view (cut through the middle)", fontsize=12, fontweight="bold")
b.add_patch(Rectangle((0, -.3), 10, .3, fc="#555", ec="k")); b.add_patch(Rectangle((0, -.3), .3, 1.5, fc="#555")); b.add_patch(Rectangle((9.7, -.3), .3, 1.5, fc="#555"))
b.text(9.0, 1.45, "chassis box\n(1.2 deep)", fontsize=7, ha="center")
b.add_patch(Rectangle((2.05, .1), 5.9, 5.2, fill=False, ec="#b5651d", lw=2)); b.text(8.2, 4.8, "riser: 4 corner posts,\n2 cm open sides\n5.2 tall", fontsize=8, color="#b5651d")
b.add_patch(Rectangle((-1.5, 5.3), 13, .5, fc="#f7f3ea", ec="k")); b.text(-1.3, 5.55, "upper base (5 mm PVC)", fontsize=8, va="center")
part(b, 2.9, .3, 4.3, .25, "", "#c33"); b.text(5.05, .1, "L298N board", ha="center", va="top", fontsize=7)
part(b, 3.3, .55, 3.5, 2.5, "heatsink", "#bbb", 8)
part(b, 2.3, .55, .9, 1.0, "C", "#2b6", 7, "w"); b.text(1.9, 1.7, "1000µF across\n+12V / GND", fontsize=7, ha="right")
b.text(1.5, -.2, "2 cm open sides:\nmotor wires + air in", fontsize=7, ha="center", va="top")
for x, c, lab in ((3.0, BLUE, "6 signal wires\nup hole S"), (6.6, RED, "8V + GND\ndown hole P")):
    b.add_patch(FancyArrowPatch((x, 3.2), (x, 6.6), arrowstyle="<->", mutation_scale=12, color=c, lw=2))
    b.text(x, 6.8, lab, ha="center", fontsize=7.5, color=c)
b.text(5, -1.6, "Everything noisy (L298N, motor wires) stays DOWN here;\nthe tray above only gets 2 thick power wires + 6 thin signals.", ha="center", fontsize=8.5)
b.set_xlim(-2, 12); b.set_ylim(-2.3, 8)
plt.tight_layout(); plt.savefig(__file__.replace("draw_layout_v2.py", "layout_v2.png"), dpi=110)
