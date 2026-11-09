"""1:1 printable cutting template (A4, 4 pages) -> template_<name>.pdf
   python3 print_template.py [thickness_cm]   default 0.3 (Umi 3 mm foam board); 0.5 for 5 mm PVC
Print at 100% / "Actual size" — check the 10 cm bar with a ruler before cutting.

Tab-and-slot: every wall has tabs on its bottom edge that push into square holes in the base, so the
box stands square by itself and the glue only has to hold it there. Walls sit M cm in from the base
edge so each slot is a real hole with base material all round it (a slot at the very edge is just a notch)."""
import os, sys
import matplotlib.pyplot as plt
from matplotlib.backends.backend_pdf import PdfPages
from matplotlib.patches import Rectangle, Circle, Polygon

T = float(sys.argv[1]) if len(sys.argv) > 1 else 0.3     # board thickness, cm
L, W, H = 12.0, 17.0, 4.0                    # base: front-back, side-side; wall height above the base (cm, 3D scan)
name = "umi" if T < 0.4 else "pvc"
BASE_T = 2 * T if name == "umi" else T       # Umi base is two sheets glued together
M = 0.6                                      # wall inset from the base edge
TAB_W, FIT = 1.5, 0.05                       # tab width; slots this much bigger so tabs push in snugly
FB = W - 2 * M                               # front/back wall length
SIDE = L - 2 * M - 2 * T                     # side walls fit BETWEEN front and back walls
FB_TABS = (FB * 0.25, FB * 0.75)             # tab centres along each wall
SIDE_TABS = (SIDE * 0.25, SIDE * 0.75)
A4 = (21.0, 29.7)

BASE_O = (2.0, 13.0)                         # where base() draws; v2 moves it for a landscape page

def page(pdf, title, draw, land=False):      # land: user's printer clips the right edge of portrait pages
    pw, ph = (A4[1], A4[0]) if land else A4
    fig = plt.figure(figsize=(pw / 2.54, ph / 2.54))
    ax = fig.add_axes([0, 0, 1, 1]); ax.set_xlim(0, pw); ax.set_ylim(0, ph); ax.axis("off")
    ax.text(1, ph - 1.1, title, fontsize=12, fontweight="bold")
    ax.plot([1, 11], [1, 1], "k", lw=2); ax.plot([1, 1], [0.8, 1.2], "k"); ax.plot([11, 11], [0.8, 1.2], "k")
    ax.text(6, 1.3, "10 cm: measure this! If it is not 10 cm, reprint at 100% / Actual size", ha="center", fontsize=7)
    draw(ax); pdf.savefig(fig); plt.close(fig)

def drill(ax, x, y, d, label=None):
    ax.add_patch(Circle((x, y), d / 2, fill=False, lw=1)); ax.plot([x - .25, x + .25], [y, y], "k", lw=.5)
    ax.plot([x, x], [y - .25, y + .25], "k", lw=.5)
    if label: ax.text(x + d / 2 + .15, y, label, fontsize=6, va="center")

def cutout(ax, x, y, w, h, label=None):
    ax.add_patch(Rectangle((x, y), w, h, fc="#ccc", ec="k", hatch="//", lw=.8))
    if label: ax.text(x + w / 2, y - .25, label, ha="center", va="top", fontsize=6)

def slot(ax, x, y, w, h):                     # a tab hole in the base: solid black = cut right out
    ax.add_patch(Rectangle((x - FIT / 2, y - FIT / 2), w + FIT, h + FIT, fc="black", ec="black"))

def wall(ax, x, y, length, tabs, label):
    """Wall outline with tabs hanging below its bottom edge (tab depth = base thickness)."""
    pts = [(x, y)]
    for c in sorted(tabs):
        a, b = x + c - TAB_W / 2, x + c + TAB_W / 2
        pts += [(a, y), (a, y - BASE_T), (b, y - BASE_T), (b, y)]
    pts += [(x + length, y), (x + length, y + H), (x, y + H)]
    ax.add_patch(Polygon(pts, closed=True, fill=False, lw=1.2))
    ax.text(x + length / 2, y + H - 0.5, label, ha="center", va="top", fontsize=8)
    ax.text(x + length / 2, y - BASE_T - 0.35, "tabs: cut around them, do NOT cut them off", ha="center", fontsize=5.5)

def base(ax, v2=False):
    # FRONT at the top: page-x = side-side (0..W), page-y = front-back (0..L)
    ox, oy = BASE_O
    ax.add_patch(Rectangle((ox, oy), W, L, fill=False, lw=1.2))
    ax.text(ox + W / 2, oy + L - 1.6, f"BASE  {W:g} x {L:g} cm" +
            ("   (Umi: cut TWO, glue them together, THEN cut the slots through both)" if name == "umi" else ""),
            ha="center", va="top", fontsize=7.5)
    ax.text(ox + W / 2, oy + L + .3, "FRONT  (sonar + camera side)", ha="center", fontsize=8, fontweight="bold")
    ax.text(ox + W / 2, oy - .6, "BACK  (ESP USB side)", ha="center", fontsize=8, fontweight="bold")
    # where the walls stand (dotted) + their tab slots (black)
    for yw in (oy + M, oy + L - M - T):                       # back, front walls
        ax.add_patch(Rectangle((ox + M, yw), FB, T, fill=False, ls=":", lw=.6))
        for c in FB_TABS: slot(ax, ox + M + c - TAB_W / 2, yw, TAB_W, T)
    for xw in (ox + M, ox + W - M - T):                       # side walls, between front and back
        ax.add_patch(Rectangle((xw, oy + M + T), T, SIDE, fill=False, ls=":", lw=.6))
        for c in SIDE_TABS: slot(ax, xw, oy + M + T + c - TAB_W / 2, T, TAB_W)
    ax.text(ox + W / 2, oy + M + T + 0.25, "black = tab slots: cut right through", ha="center", fontsize=6)
    if v2: return                                # v2: no bolts / centre hole — riser + two holes instead (base_v2)
    for dx in (-2.5, 2.5):                       # standoffs sit on the 9 x 6 cm chassis box -> 5 x 7 cm, centred
        for dy in (-3.5, 3.5):
            drill(ax, ox + W / 2 + dx, oy + L / 2 + dy, 0.32, "M3")
    ax.text(ox + W / 2, oy + L / 2 + 4.0, "4 bolt holes: 5 cm x 7 cm apart, centred", ha="center", fontsize=6.5)
    cutout(ax, ox + W / 2 - 1.6, oy + L / 2 - 0.5, 3.2, 3.0, "wire hole (wires from below)")

def walls(ax):
    ox = 2.0
    wall(ax, ox, 22.8, FB, FB_TABS, f"FRONT WALL  {FB:g} x {H:g}")
    for dx in (-1.3, 1.3):                        # HC-SR04 transducers: 16 mm dia, 26 mm apart
        drill(ax, ox + FB / 2 + dx, 22.8 + 2.1, 1.7)
    ax.text(ox + FB / 2, 22.8 + 0.3, "sonar: 2 holes 17 mm, check against YOUR sonar", ha="center", fontsize=6)
    cutout(ax, ox + 12.8 - 1.15, 22.8 + 1.4, 2.3, 1.2)       # OLED screen window (base x 3.6 = car's left; this is the OUTSIDE view)
    ax.text(ox + 12.8, 22.8 + 2.75, "OLED window 2.3 x 1.2: check vs YOUR screen", ha="center", fontsize=5.5)
    ax.text(ox + CAM_X, 22.8 + H + .15, "camera bracket on top here", ha="center", fontsize=6)
    wall(ax, ox, 16.9, FB, FB_TABS, f"BACK WALL  {FB:g} x {H:g}")
    cutout(ax, ox + 0.8, 16.9 + 0.5, 2.6, 2.0, "USB slot (line up with ESP port)")
    wall(ax, ox, 11.0, SIDE, SIDE_TABS, f"SIDE WALL  {SIDE:g} x {H:g}")
    wall(ax, ox, 5.1, SIDE, SIDE_TABS, f"SIDE WALL  {SIDE:g} x {H:g}")
    ax.text(ox, 2.6, "1. Push every wall's tabs into the base slots: front + back first, then slide the sides in between.\n"
            "2. Dry-fit with NO glue first; shave a tab with the knife if it is too tight.\n"
            "3. Then hot glue: a bead along each inside corner and under each tab.\n"
            + ("Umi = paper-faced foam: HOT GLUE (cool 2-3 s) or Fevicol. NOT Flex Kwik: it melts the foam."
               if name == "umi" else "PVC: Flex Kwik or hot glue both work."), fontsize=6.5)

CAM_W, CAM_UP = 4.0, 4.5                       # bracket plate width; how far it rises above the front wall
CAM_X = 3.2                                      # plate centre along the front wall seen from OUTSIDE (= base x 13.2,
                                                 # the car's right, 3 cm from the side wall): clear of the sonar PCB (FB/2 +- 2.25)

def camera(ax, ox=2.0, oy=15.0, view=True, ty=2.4):
    """ESP32-CAM bracket: an upright plate glued to the INSIDE of the front wall, standing on the base.
    The CAM's pins point BACK (same side as the ESP32 chip) along both long edges, so it can't lie flat:
    it sits on a foam spacer block glued to the chip's flat metal can, pins pointing into the gap."""
    ph = H + CAM_UP
    ax.add_patch(Rectangle((ox, oy), CAM_W, ph, fill=False, lw=1.2))
    ax.text(ox + CAM_W / 2, oy + ph + .3, f"PLATE  {CAM_W:g} x {ph:g}  (cut 1)", ha="center", fontsize=8)
    ax.plot([ox, ox + CAM_W], [oy + H, oy + H], "k:", lw=.6)
    ax.text(ox + CAM_W + .15, oy + H, "top of front wall", fontsize=5.5, va="center")
    ax.text(ox + CAM_W / 2, oy + H / 2, "glue this part\nto the INSIDE of\nthe front wall", ha="center", va="center", fontsize=6)
    ax.add_patch(Rectangle((ox + (CAM_W - 2.7) / 2, oy + H + 0.1), 2.7, 4.0, fill=False, ls="--", lw=.6))
    ax.add_patch(Rectangle((ox + (CAM_W - 1.5) / 2, oy + H + 1.1), 1.5, 2.5, fc="#ffe9a8", ec="k", lw=.6))
    ax.text(ox + CAM_W / 2, oy + H + 2.35, "spacer\nhere", ha="center", va="center", fontsize=5.5)
    cutout(ax, ox + (CAM_W - 2.8) / 2, oy + H + 0.15, 2.8, 0.8)       # jumper hole: bottom 2 pins of either row
    ax.text(ox + CAM_W + .15, oy + H + 0.55, "jumper hole: 5V + GND plugs\n(bottom pins) push through", fontsize=5.5, va="center")
    ax.text(ox + CAM_W / 2, oy + H + 4.3, "ESP32-CAM outline (lens/antenna end UP)", ha="center", fontsize=5.5)
    for i in range(2):                          # gussets: back of the plate <-> base floor
        gx = ox + 6.5 + i * 3.5
        ax.add_patch(Polygon([(gx, oy), (gx + 2.5, oy), (gx, oy + 6)], closed=True, fill=False, lw=1.2))
        ax.text(gx + .2, oy - .35, "BRACE 2.5 x 6", fontsize=6)
    ax.text(ox + 6.5, oy + 6.6, "long edge -> back of plate (near its sides), short edge -> base", fontsize=5.5)
    for i in range(6):                          # 3 sheets = 9 mm clears ~1 cm pins minus the 3 mm chip can; 3 spares to go thicker
        ax.add_patch(Rectangle((ox + 14 + (i // 3) * 2, oy + (i % 3) * 2.8), 1.5, 2.5, fill=False, lw=1.2))
    ax.add_patch(Rectangle((ox + 14, oy + 8.6), 1.5, 1.2, fill=False, lw=1.2))
    ax.text(ox + 15.75, oy + 10.2, "SPACER 1.5 x 2.5 (cut 6: glue 3, add more\nif the pins still touch) + TILT 1.5 x 1.2", ha="center", fontsize=6)
    # where it goes: front wall seen from INSIDE the tray
    fy = 6.0
    if view:
      ax.add_patch(Rectangle((ox, fy), FB, H, fill=False, lw=1))
      ax.add_patch(Rectangle((ox + FB / 2 - 2.25, fy + 0.6), 4.5, 2.0, fc="#ddd", ec="k", lw=.6))
      ax.text(ox + FB / 2, fy + 1.6, "sonar PCB", ha="center", fontsize=6)
      ax.add_patch(Rectangle((ox + FB - CAM_X - CAM_W / 2, fy), CAM_W, H + CAM_UP, fill=False, lw=1.2, ls="--"))
      ax.text(ox + FB / 2, fy + H + .3, "FRONT WALL from inside (mirror of page 2)", ha="center", fontsize=7)
      ax.text(ox + FB - CAM_X, fy + H + CAM_UP + .2, "plate", ha="center", fontsize=6)
    ax.text(ox, ty, "1. Plate stands on the base, glued to the inside of the front wall, centre 3 cm from the side wall\n"
            "   (seen from the FRONT of the car it is on the LEFT of the sonar = the car's right side). Braces behind it.\n"
            "2. Glue the 3 spacers into one 9 mm block. Glue the small TILT piece on the block's top half\n"
            "   (top sticks out 3 mm more -> lens tilts ~7 deg down). Block goes on the plate where marked.\n"
            "3. Plug jumpers on the CAM's 5V + GND pins (bottom end of a pin row) and feed them through the\n"
            "   jumper hole (cut right out). A dab of hot glue where they pass through stops them sliding.\n"
            "4. Foam tape on the CAM's flat metal ESP32 can -> press onto the block, lens end UP. Pins must not touch the plate.\n"
            "5. Wires: CAM 5V -> top-edge VCC, GND -> G. Twist the pair.", fontsize=6.3)

BOX_DEPTH = 1.2                                   # chassis box: floor -> rim top (measured)
RISER_H = BOX_DEPTH + 4.0                         # tray stays 4 cm above the rim, clear of the shocks
RISER_L, RISER_W = 6.0 - 0.1, 5.6 - 0.1           # usable floor INSIDE: 6.0 side-side x 5.6 front-back (measured by fit-check); 1 mm slip fit

def finger_wall(ax, x, y, length, h, studs_outer, notch=None):
    """Wall outline with finger joints at both ends, height split in thirds. studs_outer=True: thirds 1+3
    reach the end, the middle third is a notch T deep (front/back). False: only the middle third reaches
    the end as a stud (sides). Studs of one wall drop into the notches of the next."""
    t3, d = h / 3, T
    def end(xe, inward):                          # end profile, bottom -> top, at x = xe
        full, cut = xe, xe + inward * d
        a, b2 = (full, cut) if studs_outer else (cut, full)
        return [(a, y), (a, y + t3), (b2, y + t3), (b2, y + 2 * t3), (a, y + 2 * t3), (a, y + h)]
    right = end(x + length, -1)
    left = end(x, +1)[::-1]
    pts = [left[-1]]                                # bottom edge (with the optional wire notch)
    if notch:
        nx, nw, nh = notch
        pts += [(nx, y), (nx, y + nh), (nx + nw, y + nh), (nx + nw, y)]
    pts += right + left
    ax.add_patch(Polygon(pts, closed=True, fill=False, lw=1.2))

def riser(ax):
    """No screws: a hollow foam box standing INSIDE the chassis box on its floor, glued to the box walls;
    the L298N sits inside it, the tray on top (velcro), zip ties through the box's old lid-screw tabs.
    Corners are finger-jointed (studs into notches) so it squares itself before the glue."""
    fx, fy = 2.0, 20.6
    ax.add_patch(Rectangle((fx, fy), RISER_L, RISER_W, fill=False, lw=1.2, ls="--"))
    ax.text(fx + RISER_L / 2, fy + RISER_W / 2, f"FIT CHECK  {RISER_L:g} x {RISER_W:g}\ndon't cut - lay it on the box\nfloor (the part you marked):\nshould just fit inside", ha="center", va="center", fontsize=7)
    ax.text(fx + RISER_L / 2, fy + RISER_W + .2, "<- side to side ->   (car's front is up)", ha="center", fontsize=6)
    ax.text(11.0, 26.6, "CHECK BEFORE CUTTING", fontsize=8, fontweight="bold")
    ax.text(11.0, 26.1, f"a) This sheet is for {T*10:g} mm board. Wrong\n   thickness = joints won't fit: use the\n   other PDF (riser_umi = 3 mm, riser_pvc = 5 mm).\n"
            "b) Outline above fits inside the marked\n   floor area? If not: STOP, send the size.\n"
            f"c) Walls are {RISER_H:g} cm = {BOX_DEPTH:g} cm box depth + 4 cm\n   above the rim.", fontsize=6.5, va="top")
    for i in range(2):                                # front + back: studs top & bottom thirds
        x, y = 2.0 + i * 8.5, 13.6
        finger_wall(ax, x, y, RISER_L, RISER_H, True, notch=(x + RISER_L / 2 - 1.0, 2.0, 1.2))   # both: front + rear motor wires
        ax.text(x + RISER_L / 2, y + RISER_H / 2 + .5, f"{'FRONT' if i == 0 else 'BACK'} WALL\n{RISER_L:g} x {RISER_H:g}", ha="center", va="center", fontsize=7.5)
        ax.text(x + RISER_L / 2, y + 1.35, "wire notch", ha="center", fontsize=5.5)
    for i in range(2):                                # sides: stud in the middle third
        x, y = 2.0 + i * 8.5, 7.4
        finger_wall(ax, x, y, RISER_W, RISER_H, False)
        ax.text(x + RISER_W / 2, y + RISER_H / 2, f"SIDE WALL\n{RISER_W:g} x {RISER_H:g}", ha="center", va="center", fontsize=7.5)
    GH, GW = RISER_H - BOX_DEPTH, 3.0                 # gusset: the riser height above the rim x 3 cm reach under the tray
    for i in range(2):                                # 2 rectangles, each cut on the diagonal = 4 right-angle gussets
        gx, gy = 11.0 + i * (GW + 0.6), 19.4
        ax.add_patch(Rectangle((gx, gy), GW, GH, fill=False, lw=1.2))
        ax.plot([gx, gx + GW], [gy, gy + GH], "k", lw=1.2)
        ax.text(gx + GW * .3, gy + GH * .72, "G", ha="center", fontsize=8, fontweight="bold")
        ax.text(gx + GW * .7, gy + GH * .28, "G", ha="center", fontsize=8, fontweight="bold")
    ax.text(18.0, 22.6, f"4 GUSSETS\n{GW:g} x {GH:g}:\ncut each box\non the diagonal", fontsize=6.5, va="top")
    ax.text(2.0, 6.6, "1. Cut ON the lines, studs included - don't cut the studs off. Dry-fit: every stud drops into a notch\n"
            "   and the corners close square. Shave a stud if tight. Then hot-glue each corner inside.\n"
            "2. Stand it INSIDE the chassis box on the floor you marked, notches front + back. Hot-glue it to the\n"
            "   floor and to the box walls all round.\n"
            "3. L298N inside the riser (heatsink up); motor wires in through the notches; battery + signal wires\n"
            "   up through the tray's centre wire hole.\n"
            "4. Tray on top, centred: velcro.  5. Zip ties through 2 of the box's corner tabs + the tray base.\n"
            f"6. GUSSETS (G): {GH:g} edge glued down the riser's LEFT and RIGHT walls (2 each, near the corners),\n"
            f"   {GW:g} edge flat under the tray base. Not on front/back: shocks + steering live there. Glue them\n"
            "   to the riser first, then to the tray when it goes on (skip the tray side if you want it removable).\n"
            "7. Push the tray down, steer full left + right: nothing may touch.", fontsize=6.5, va="top")

GAP = 2.0                                         # open SIDES: an opening this wide in the middle of every side; corners stay closed
RX0, RY0 = 5.55, 3.25                             # riser outer corner on the base (base coords)
FBL = (RISER_L - GAP) / 2                         # front/back strip: full corner-to-gap length
SDL = (RISER_W - GAP) / 2 - T                     # side strip butts against the INSIDE face of the front/back strip
RTAB = 1.0                                        # top tab on each front/back strip
def riser_panels():                               # (x, y, w, d) footprints on the base, for base_v2 / the layout / the 3D view
    out = []
    for y in (RY0, RY0 + RISER_W - T):                                   # back, front strips (2 each)
        out += [(RX0, y, FBL, T), (RX0 + RISER_L - FBL, y, FBL, T)]
    for x in (RX0, RX0 + RISER_L - T):                                   # left, right strips (2 each)
        out += [(x, RY0 + T, T, SDL), (x, RY0 + RISER_W - T - SDL, T, SDL)]
    return out

def strip(ax, x, y, L, label, tab):
    pts = [(x, y), (x + L, y), (x + L, y + RISER_H)]
    if tab:
        a, b = x + L / 2 - RTAB / 2, x + L / 2 + RTAB / 2
        pts += [(b, y + RISER_H), (b, y + RISER_H + T), (a, y + RISER_H + T), (a, y + RISER_H)]
    ax.add_patch(Polygon(pts + [(x, y + RISER_H)], closed=True, fill=False, lw=1.2))
    ax.text(x + L / 2, y + RISER_H / 2, f"{label}\n{L:g} x {RISER_H:g}", ha="center", va="center", fontsize=6.5)

def riser_v2(ax):
    """Open-SIDE riser: 4 closed L-shaped corner posts (a front/back strip + a side strip butt-glued), a GAP-wide opening
    in the middle of every side for motor wires + air. Bottoms glued to the bay floor; front/back strip tabs drop into the base."""
    for i in range(4): strip(ax, 1.5 + i * (FBL + .7), 12.5, FBL, "FRONT/BACK\nstrip\n(cut 4)" if i == 0 else "F/B", True)
    for i in range(4): strip(ax, 1.5 + i * (SDL + .7), 5.6, SDL, "SIDE\n(cut 4)" if i == 0 else "S", False)
    GH, GW = RISER_H - BOX_DEPTH, 3.0
    for i in range(2):                            # 2 rectangles cut on the diagonal = 4 gussets
        gx, gy = 12.0 + i * (GW + 0.6), 12.5
        ax.add_patch(Rectangle((gx, gy), GW, GH, fill=False, lw=1.2)); ax.plot([gx, gx + GW], [gy, gy + GH], "k", lw=1.2)
        ax.text(gx + GW * .3, gy + GH * .72, "G", ha="center", fontsize=8, fontweight="bold")
        ax.text(gx + GW * .7, gy + GH * .28, "G", ha="center", fontsize=8, fontweight="bold")
    ax.text(12.0, 12.1, f"4 GUSSETS {GW:g} x {GH:g}: cut each box on the diagonal", fontsize=6, va="top")
    fx, fy = 11.0, 5.6                            # top-down fit check, real size
    ax.add_patch(Rectangle((fx, fy), RISER_L, RISER_W, fill=False, ls=":", lw=.8))
    for (x, y, w, d) in riser_panels():
        ax.add_patch(Rectangle((fx + x - RX0, fy + y - RY0), w, d, fc="#ddd", ec="k", lw=.8))
    ax.text(fx + RISER_L / 2, fy + RISER_W / 2, f"TOP VIEW, real size\n{RISER_L:g} x {RISER_W:g} outside\n{GAP:g} cm open sides\n(front = up)", ha="center", va="center", fontsize=6)
    ax.text(fx + RISER_L + .3, fy + RISER_W - .2, "Lay this on the box floor:\nthe dotted outline must\njust fit inside the bay.", fontsize=6, va="top")
    ax.text(1.5, 4.6, "1. Cut ON the lines; keep the tabs on the 4 front/back strips.\n"
            "2. Make 4 corner posts: glue the end of a SIDE strip to the INSIDE face of a FRONT/BACK strip, at its outer end, square (L shape).\n"
            f"3. Stand the 4 posts in the corners of the chassis-box bay, tabs up. The {GAP:g} cm gaps in the middle of each side are the openings:\n"
            "   motor wires in front + back, air through the sides. L298N in the middle, heatsink up. Hot-glue the bottoms to the floor.\n"
            "4. Gussets (G): long edge down the outside of each SIDE strip, short edge flat on top (under the tray).\n"
            "5. Lower the tray on: the 4 tabs drop into the base's riser slots. Don't glue them, so the tray comes off. Zip ties hold it down.", fontsize=6.3, va="top")

out = os.path.join(os.path.dirname(os.path.abspath(__file__)), f"template_{name}.pdf")
# ---- v2 rebuild (docs/layout_v2.png): extra holes on the base + back wall. Base coords: x side-side, y back->front ----
def base_v2(ax):                                  # positions = draw_layout_v2.py (layout_v2.png), keep in sync
    base(ax, v2=True)
    ox, oy = BASE_O
    ax.add_patch(Rectangle((ox + RX0, oy + RY0), RISER_L, RISER_W, fill=False, ec="#b5651d", ls="--", lw=.8))
    ax.text(ox + 8.5, oy + 3.05, "riser below (open sides): black = its 4 tab slots", ha="center", va="top", fontsize=5.5, color="#b5651d")
    for (x, y, w, d) in riser_panels():                                        # riser tab slots: one per front/back strip
        if w > d: slot(ax, ox + x + w / 2 - RTAB / 2, oy + y, RTAB, T)
    for x, lab in ((6.08, "S"), (10.38, "P")):                                 # signal / power holes, just inside the side panels
        cutout(ax, ox + x, oy + 4.1, 0.54, 1.9); ax.text(ox + x + .27, oy + 6.05, lab, ha="center", fontsize=7, fontweight="bold")
    for x in (6.25, 10.45):                                                     # battery strap slots
        ax.add_patch(Rectangle((ox + x, oy + 6.35), .3, 1.5, fc="black"))
    ax.text(ox + 8.5, oy + 7.1, "<- strap slots ->", ha="center", va="center", fontsize=5.5)
    for (x, y, w, h, lab) in ((1.2, 1.2, 5.0, 6.8, "ESP board 6.8 x 5\nmark its 4 holes from\nthe real board, drill 3 mm"),
                              (6.65, 2.15, 3.7, 7.0, "battery\n(velcro)"), (6.4, 1.15, 4.5, 0.9, "UBEC on edge"),
                              (4.0, 8.6, 2.0, 1.6, "MPU"), (11.2, 7.9, 4.0, 3.0, "camera\nbracket"),
                              (11.5, 3.4, 2.65, 2.0, "Wagos"), (13.75, 1.2, 1.3, 2.0, "Wago"),
                              (15.55, 3.4, 0.35, 4.0, "INA\non\nwall")):
        ax.add_patch(Rectangle((ox + x, oy + y), w, h, fill=False, ls="--", lw=.6, ec="#666"))
        ax.text(ox + x + w / 2, oy + y + h / 2, lab, ha="center", va="center", fontsize=5.5, color="#666")

WY = 2.2                                           # every wall page: wall sits at the bottom of the sheet
def front_v2(ax):                        # seen from the FRONT of the car
    ox, wy = 1.5, WY
    wall(ax, ox, wy, FB, FB_TABS, f"FRONT WALL (seen from the front of the car)   {FB:g} x {H:g}")
    for dx in (-1.3, 1.3):                        # HC-SR04 transducers: 16 mm dia, 26 mm apart
        drill(ax, ox + FB / 2 + dx, wy + 2.1, 1.7)
    ax.text(ox + FB / 2, wy + 0.3, "sonar: 2 holes 17 mm, check against YOUR sonar", ha="center", fontsize=6)
    cutout(ax, ox + 12.8 - 1.15, wy + 1.4, 2.3, 1.2)            # OLED window: base x 3.6 = car's left
    ax.text(ox + 12.8, wy + 2.75, "OLED window 2.3 x 1.2\ncheck vs YOUR screen", ha="center", fontsize=5.5)
    ax.add_patch(Rectangle((ox + CAM_X - CAM_W / 2, wy), CAM_W, H + CAM_UP, fill=False, ls="--", lw=.7))
    ax.text(ox + CAM_X, wy + H + CAM_UP + .15, "camera plate stands behind here", ha="center", fontsize=5.5)

def back_v2(ax):                         # seen from BEHIND the car = same left/right as the base page
    ox, wy = 1.5, WY
    wall(ax, ox, wy, FB, FB_TABS, f"BACK WALL (seen from behind the car)   {FB:g} x {H:g}")
    cutout(ax, ox + 2.4 - M, wy + 0.5, 2.6, 2.0, "USB slot (line up with ESP port)")
    drill(ax, ox + 1.6 - M, wy + 3.2, 0.6, "wheel sensor")
    cutout(ax, ox + 9.2 - M, wy + 2.2, 0.8, 1.2, "charge lead")

def side_v2(ax):
    ox = 1.5
    for x in (ox, ox + SIDE + 1.0):               # both side walls, side by side
        wall(ax, x, WY, SIDE, SIDE_TABS, f"SIDE WALL  {SIDE:g} x {H:g}")
    ax.text(ox, WY + H + .9, "1. Push every wall's tabs into the base slots: front + back first, then slide the sides in between.\n"
            "2. Dry-fit with NO glue first; shave a tab with the knife if it is too tight.\n"
            "3. Then glue: Flex Kwik or hot glue, a bead along each inside corner and under each tab.", fontsize=6.5, va="bottom")

LOW = 10.5                                         # user's printer: keep the TOP half of every landscape page empty
def page_low(pdf, title, draw):
    """Landscape A4, one part per page, sitting at the BOTTOM of the sheet, left of x = 19 (the printer clips the right edge)."""
    fig = plt.figure(figsize=(A4[1] / 2.54, A4[0] / 2.54))
    ax = fig.add_axes([0, 0, 1, 1]); ax.set_xlim(0, A4[1]); ax.set_ylim(0, A4[0]); ax.axis("off")
    draw(ax)
    ax.plot([1, 11], [.8, .8], "k", lw=2); ax.plot([1, 1], [.6, 1.0], "k"); ax.plot([11, 11], [.6, 1.0], "k")
    ax.text(11.4, .8, "10 cm: measure this! If it is not 10 cm, reprint at 100% / Actual size", fontsize=6.5, va="center")
    ax.text(1, .25, title, fontsize=8, fontweight="bold", va="center")
    pdf.savefig(fig); plt.close(fig)

def riser_low(ax):                                # same pieces as riser_v2(), packed into the bottom half
    for i in range(4): strip(ax, 1.5 + i * (FBL + .5), 4.15, FBL, "F/B" if i else "FRONT/BACK\n(cut 4)", True)
    for i, (x, y) in enumerate([(1.5, 1.35), (7.2, 1.35), (1.5, 2.75), (7.2, 2.75)]):
        ax.add_patch(Rectangle((x, y), RISER_H, SDL, fill=False, lw=1.2))   # side strips lying down: 5.2 long x 1.25 tall
        ax.text(x + RISER_H / 2, y + SDL / 2, "SIDE (cut 4)" if i == 0 else "SIDE", ha="center", va="center", fontsize=6)
    GH, GW = RISER_H - BOX_DEPTH, 3.0
    for i in range(2):
        gx, gy = 11.6 + i * (GW + .5), 4.8
        ax.add_patch(Rectangle((gx, gy), GW, GH, fill=False, lw=1.2)); ax.plot([gx, gx + GW], [gy, gy + GH], "k", lw=1.2)
        ax.text(gx + GW * .3, gy + GH * .72, "G", ha="center", fontsize=8, fontweight="bold")
        ax.text(gx + GW * .7, gy + GH * .28, "G", ha="center", fontsize=8, fontweight="bold")
    ax.text(11.6, 4.5, f"4 GUSSETS {GW:g} x {GH:g}: cut each box on the diagonal", fontsize=6, va="top")

if "v2" in sys.argv:                               # python3 print_template.py 0.5 v2 -> base_v2_pvc.pdf (2 pages)
    out = os.path.join(os.path.dirname(os.path.abspath(__file__)), f"base_v2_{name}.pdf")
    with PdfPages(out) as pdf:
        BASE_O = (1.5, 2.0)                    # whole base, bottom of the sheet
        page_low(pdf, f"1/6 BASE  {T*10:g} mm - LANDSCAPE, 100%", base_v2)
        page_low(pdf, f"2/6 FRONT WALL  {T*10:g} mm - LANDSCAPE, 100%", front_v2)
        page_low(pdf, f"3/6 BACK WALL  {T*10:g} mm - LANDSCAPE, 100%", back_v2)
        page_low(pdf, f"4/6 SIDE WALLS (x2)  {T*10:g} mm - LANDSCAPE, 100%", side_v2)
        page_low(pdf, f"5/6 CAMERA BRACKET  {T*10:g} mm - LANDSCAPE, 100%", lambda ax: camera(ax, 1.5, 2.6, False, 14.0))
        page_low(pdf, f"6/6 RISER (open sides)  {T*10:g} mm - LANDSCAPE, 100%", riser_low)
    print(out); sys.exit()

if "riser2" in sys.argv:                         # python3 print_template.py 0.5 riser2 -> riser_v2_pvc.pdf (open sides)
    out = os.path.join(os.path.dirname(os.path.abspath(__file__)), f"riser_v2_{name}.pdf")
    with PdfPages(out) as pdf:
        page_low(pdf, f"RISER (open sides)  {T*10:g} mm - LANDSCAPE, 100%", riser_low)
    print(out); sys.exit()

if "riser" in sys.argv:                          # python3 print_template.py 0.3 riser -> just the riser page
    out = out.replace("template_", "riser_")
    with PdfPages(out) as pdf:
        page(pdf, f"Car tray RISER (replaces the standoffs) - {T*10:g} mm board", riser)
    print(out); sys.exit()
with PdfPages(out) as pdf:
    page(pdf, f"Car tray: page 1/4: BASE  (board {T*10:g} mm)", base)
    page(pdf, f"Car tray: page 2/4: WALLS with tabs  (board {T*10:g} mm)", walls)
    page(pdf, f"Car tray: page 3/4: CAMERA BRACKET  (board {T*10:g} mm)", camera)
    page(pdf, f"Car tray: page 4/4: RISER (no screws)  (board {T*10:g} mm)", riser)
print(out)
