"""Real-size cut-and-glue cardboard enclosure template for the Nova room node.
Run: python3 make_enclosure.py  ->  enclosure_template.pdf (3 A4 pages, PRINT AT 100% / "Actual size").
Change the box size/holes below if your boards measure differently."""
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib.backends.backend_pdf import PdfPages
from matplotlib.patches import Rectangle, Circle, Polygon

L, W, H = 180, 76, 60      # INNER box size, mm (ESP32 HW-777 board + 4-relay module side by side)
T = 3                      # cardboard thickness allowance for the lid, mm
TAB = 10                   # glue-tab width, mm
A4 = (210, 297)

def page(title):
    fig = plt.figure(figsize=(A4[0] / 25.4, A4[1] / 25.4))
    ax = fig.add_axes([0, 0, 1, 1]); ax.set_xlim(0, A4[0]); ax.set_ylim(0, A4[1])
    ax.set_aspect("equal"); ax.axis("off")
    ax.text(105, 292, title, ha="center", va="top", fontsize=9, weight="bold")
    # scale check: must measure exactly 50 mm when printed
    ax.plot([150, 200], [6, 6], "k", lw=1.2); ax.plot([150, 150], [4.5, 7.5], "k"); ax.plot([200, 200], [4.5, 7.5], "k")
    ax.text(175, 8, "must measure 50 mm", ha="center", fontsize=5)
    return fig, ax

def cut(ax, x, y, w, h):  ax.add_patch(Rectangle((x, y), w, h, fill=False, lw=0.8, ec="k"))
def fold(ax, x1, y1, x2, y2): ax.plot([x1, x2], [y1, y2], "--", lw=0.6, color="#1565c0")
def hole(ax, x, y, d, label):
    ax.add_patch(Circle((x, y), d / 2, fc="#ccc", ec="k", lw=0.6)); ax.text(x, y - d / 2 - 2.5, label, ha="center", fontsize=4.5)
def slot(ax, cx, cy, w, h, label=None):
    ax.add_patch(Rectangle((cx - w / 2, cy - h / 2), w, h, fc="#ccc", ec="k", lw=0.6))
    if label: ax.text(cx, cy - h / 2 - 2.5, label, ha="center", fontsize=4.5)
def tab(ax, pts):  ax.add_patch(Polygon(pts, closed=True, fill=False, lw=0.6, ec="k", hatch="////", alpha=0.6))
def label(ax, x, y, s, rot=0, fs=6): ax.text(x, y, s, ha="center", va="center", fontsize=fs, rotation=rot, color="#555")

pdf = PdfPages(__file__.replace("make_enclosure.py", "enclosure_template.pdf"))

# ---------- PAGE 1: base + front + back (one piece, fold up the two long walls) ----------
fig, ax = page("NOVA ROOM NODE BOX  1/3  base + front + back   (solid = cut, blue dashed = fold, grey = cut out)")
bx = (A4[0] - W) / 2; by = (A4[1] - L) / 2 - 4
cut(ax, bx - H, by, W + 2 * H, L)
fold(ax, bx, by, bx, by + L); fold(ax, bx + W, by, bx + W, by + L)
label(ax, bx + W / 2, by + L / 2, "BASE  %d x %d" % (W, L), rot=90, fs=8)
# board footprints (dashed grey) to help placement — ESP end is the bottom of this page
ax.add_patch(Rectangle((bx + 8, by + 5), 60, 80, fill=False, ls=":", ec="#888")); label(ax, bx + 38, by + 45, "ESP32 HW-777\n~60x80", 90, 5)
ax.add_patch(Rectangle((bx + 10, by + 98), 55, 75, fill=False, ls=":", ec="#888")); label(ax, bx + 38, by + 135, "4-relay module\n~55x75", 90, 5)
# FRONT wall (left): height runs outward = leftward from the fold
fx = lambda h: bx - h
label(ax, fx(H / 2) + 12, by + 75, "FRONT (faces the room / AC)", rot=90)
hole(ax, fx(42), by + 125, 23, "PIR dome  Ø23")
hole(ax, fx(45), by + 40, 5.5, "IR LED  Ø5.5")
# BACK wall (right)
kx = lambda h: bx + W + h
label(ax, kx(H / 2) - 12, by + 75, "BACK", rot=90)
slot(ax, kx(13), by + 135, 10, 30, "relay load wires")
ax.text(105, by - 4, "ESP end (USB)  ↓        relay end  ↑ top", ha="center", fontsize=5, va="top")
pdf.savefig(fig); plt.close(fig)

# ---------- PAGE 2: two end walls with glue tabs ----------
fig, ax = page("NOVA ROOM NODE BOX  2/3  end walls  (tabs fold inward and glue to base + side walls)")
def end_wall(x, y, name, holes):
    cut(ax, x, y, W, H)
    tab(ax, [(x, y), (x + W, y), (x + W - 4, y - TAB), (x + 4, y - TAB)])            # bottom tab -> base
    tab(ax, [(x, y), (x - TAB, y + 4), (x - TAB, y + H - 4), (x, y + H)])            # side tabs -> walls
    tab(ax, [(x + W, y), (x + W + TAB, y + 4), (x + W + TAB, y + H - 4), (x + W, y + H)])
    fold(ax, x, y, x + W, y); fold(ax, x, y, x, y + H); fold(ax, x + W, y, x + W, y + H)
    label(ax, x + W / 2, y + H - 6, name)
    for f in holes: f(x, y)
ex = (A4[0] - W) / 2
end_wall(ex, 185, "ESP END", [lambda x, y: slot(ax, x + W / 2, y + 20, 14, 12, "USB cable slot (check height vs your board)")])
end_wall(ex, 75, "RELAY END", [lambda x, y: hole(ax, x + W / 2, y + 45, 6, "DHT22 wires Ø6 (sensor mounts OUTSIDE)")] +
                         [lambda x, y, k=k: slot(ax, x + W / 2, y + 12 + 6 * k, 40, 3) for k in range(4)])
ax.text(105, 40, "DHT22 goes on the OUTSIDE of the relay end — inside, the ESP's heat makes it read 2-4 °C high.\n"
                 "Point the FRONT wall at the AC: the IR LED needs line of sight (it reaches ~5 m with the 2N2222).",
        ha="center", fontsize=5.5)
pdf.savefig(fig); plt.close(fig)

# ---------- PAGE 3: lid (slips over the top, skirts fold down) ----------
fig, ax = page("NOVA ROOM NODE BOX  3/3  lid  (skirts fold down, corner tabs glue inside)")
LW, LL, S = W + 2 * T, L + 2 * T, 15
lx = (A4[0] - LW) / 2; ly = (A4[1] - LL) / 2 - 4
cut(ax, lx, ly, LW, LL)
for (x1, y1, x2, y2) in [(lx, ly, lx + LW, ly), (lx, ly + LL, lx + LW, ly + LL), (lx, ly, lx, ly + LL), (lx + LW, ly, lx + LW, ly + LL)]:
    fold(ax, x1, y1, x2, y2)
cut(ax, lx - S, ly, S, LL); cut(ax, lx + LW, ly, S, LL)                 # long skirts
cut(ax, lx, ly - S, LW, S); cut(ax, lx, ly + LL, LW, S)                 # short skirts
# corner glue tabs on the short skirts
tab(ax, [(lx, ly - S), (lx - S + 3, ly - S + 3), (lx - S + 3, ly), (lx, ly)])
tab(ax, [(lx + LW, ly - S), (lx + LW + S - 3, ly - S + 3), (lx + LW + S - 3, ly), (lx + LW, ly)])
tab(ax, [(lx, ly + LL + S), (lx - S + 3, ly + LL + S - 3), (lx - S + 3, ly + LL), (lx, ly + LL)])
tab(ax, [(lx + LW, ly + LL + S), (lx + LW + S - 3, ly + LL + S - 3), (lx + LW + S - 3, ly + LL), (lx + LW, ly + LL)])
label(ax, lx + LW / 2, ly + LL / 2 + 30, "LID  %d x %d" % (LW, LL), rot=90, fs=8)
for k in range(6):                                                       # vents over the ESP (bottom = ESP end)
    slot(ax, lx + LW / 2, ly + 20 + 8 * k, 40, 3)
label(ax, lx + LW / 2, ly + 75, "vents over ESP", fs=5)
pdf.savefig(fig); plt.close(fig)
pdf.close()
print("wrote enclosure_template.pdf")
