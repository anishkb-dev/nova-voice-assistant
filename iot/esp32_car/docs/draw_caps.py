"""Noise caps: 104 on ESP EN->GND + 3-cap motor suppression -> caps.png   (python3 draw_caps.py)"""
import matplotlib.pyplot as plt
from matplotlib.patches import Rectangle, FancyBboxPatch, Circle

L = ["EN", "VP", "VN", "D34", "D35", "D32", "D33", "D25", "D26", "D27", "D14", "D12", "D13", "GND", "VIN"]
R = ["D23", "D22", "TX0", "RX0", "D21", "D19", "D18", "D5", "TX2", "RX2", "D4", "D2", "D15", "GND", "3V3"]
fig, (a, b) = plt.subplots(1, 2, figsize=(13, 7.5))
for ax in (a, b): ax.set_aspect("equal"); ax.axis("off")

def cap(ax, x1, y1, x2, y2, label="104"):
    mx, my = (x1 + x2) / 2, (y1 + y2) / 2
    ax.plot([x1, mx - .35], [y1, my], color="#c96", lw=2); ax.plot([mx + .35, x2], [my, y2], color="#c96", lw=2)
    ax.add_patch(FancyBboxPatch((mx - .35, my - .28), .7, .56, boxstyle="round,pad=0.05", fc="#f2c14e", ec="#8a6a10"))
    ax.text(mx, my, label, ha="center", va="center", fontsize=8, fontweight="bold")

# --- 1. ESP32 EN cap ---
a.set_title("1. FIRST: 104 cap from EN to GND (stops motor-noise resets)", fontsize=11, fontweight="bold")
a.add_patch(Rectangle((0, 0), 6, 16, fc="#1d1d1d", ec="k")); a.text(3, 8, "ESP32\n(30-pin)", color="w", ha="center", va="center", fontsize=11)
a.add_patch(Rectangle((1.6, 15.2), 2.8, 1.6, fc="#c8a24a", ec="k")); a.text(3, 16, "antenna end", ha="center", va="center", fontsize=7)
a.add_patch(Rectangle((2.2, -1.0), 1.6, 1.0, fc="#aaa", ec="k")); a.text(3, -.5, "USB", ha="center", va="center", fontsize=7)
for i, (l, r) in enumerate(zip(L, R)):
    y = 14.8 - i
    for x, name, ha, dx in ((0, l, "right", -.25), (6, r, "left", .25)):
        hot = name in ("EN", "GND")
        a.add_patch(Circle((x, y), .2, fc="#ffd400" if hot else "#bbb", ec="k"))
        a.text(x + dx, y, name, ha=ha, va="center", fontsize=8.5, fontweight="bold" if hot else None, color="#b00" if hot else "k")
cap(a, -1.2, 14.8, -1.2, 1.8)                      # EN (top left) down to GND (left column, 2nd from bottom)
a.plot([-1.2, -.2], [14.8, 14.8], color="#c96", lw=2); a.plot([-1.2, -.2], [1.8, 1.8], color="#c96", lw=2)
a.text(-3.0, 8.3, "104 cap\n(either way round:\nno + / −)", ha="center", fontsize=9)
a.text(3, -2.6, "On the expansion board: one leg in the EN column's S,\nthe other in any G. Or bend the legs onto the ESP's own\nEN and GND pins and solder. Keep the legs short.", ha="center", fontsize=9)
a.set_xlim(-5, 9); a.set_ylim(-4, 17.5)

# --- 2. 3-cap motor ---
b.set_title("2. ONLY IF IT STILL RESETS: 3 caps on the steering motor", fontsize=11, fontweight="bold")
b.add_patch(Rectangle((0, 0), 6, 7, fc="#8a8a8a", ec="k", lw=2)); b.text(3, 3.5, "motor\nmetal case", ha="center", va="center", fontsize=11, color="w")
b.add_patch(Rectangle((6, 1.5), 1.4, 4, fc="#6b6b6b", ec="k"))
for y, n in ((5.6, "A"), (1.4, "B")):
    b.add_patch(Rectangle((7.4, y - .25), .6, .5, fc="#d4a017", ec="k")); b.text(8.6, y + .45, f"terminal {n}", fontsize=8)
    b.plot([8.0, 13], [y, y], color="#c00" if n == "A" else "k", lw=3)
b.text(13.2, 5.6, "→ L298N OUT3", va="center", fontsize=9); b.text(13.2, 1.4, "→ L298N OUT4", va="center", fontsize=9)
cap(b, 10.5, 5.6, 10.5, 1.4, "104 #1"); b.text(11.3, 3.5, "#1: across the\nterminals\n(you have this)", fontsize=8.5, va="center")
cap(b, 8.6, 5.6, 4.6, 7.0, "104 #2"); cap(b, 8.6, 1.4, 4.6, 0.0, "104 #3")
b.text(3.0, 8.4, "#2: terminal A → case", ha="center", fontsize=9, fontweight="bold")
b.text(3.0, -1.2, "#3: terminal B → case", ha="center", fontsize=9, fontweight="bold")
b.text(7.5, -3.0, "Solder #2 and #3 onto the metal can (scratch it shiny first, quick hot touch).\nShort legs. Twist the two motor wires all the way to the L298N.", ha="center", fontsize=9)
b.set_xlim(-1, 17); b.set_ylim(-4.5, 10)
plt.tight_layout(); plt.savefig(__file__.replace("draw_caps.py", "caps.png"), dpi=110)
