"""1:1 encoder discs for the FC-51 wheel sensor -> encoder_disc.pdf (A4).
Print at 100%, cut the one that fits inside the rim, glue to card/foam, stick flat on the BACK of the rim.
6 black/white sectors = 6 ticks per wheel turn. Rim inside is 3.5 cm, so 6 (not 8) keeps each sector ~1 cm wide
at the sensor spot — the FC-51 sees a ~5 mm patch."""
import os, matplotlib.pyplot as plt
from matplotlib.backends.backend_pdf import PdfPages
from matplotlib.patches import Wedge, Circle

SECT, HUB = 6, 1.2                               # sectors; hub hole dia (cm) — trim to fit
PW, PH = 29.7, 21.0                              # landscape A4; user's printer drops the right edge -> keep it all left of ~18 cm
fig = plt.figure(figsize=(PW / 2.54, PH / 2.54))
ax = fig.add_axes([0, 0, 1, 1]); ax.set_xlim(0, PW); ax.set_ylim(0, PH); ax.set_aspect("equal"); ax.axis("off")
ax.text(2, 19.6, "Wheel encoder discs (FC-51) - print at 100% / Actual size", fontsize=12, fontweight="bold")
for i, od in enumerate((3.0, 3.2, 3.4)):          # rim inside = 3.5 cm (measured): pick the biggest that sits flat
    for j in range(2):                            # 2 of each: one spare
        cx, cy = 4.0 + i * 4.5, 16.0 - j * 5.0
        for k in range(SECT):
            ax.add_patch(Wedge((cx, cy), od / 2, k * 360 / SECT, (k + 1) * 360 / SECT,
                               fc="black" if k % 2 else "white", ec="black", lw=.5))
        ax.add_patch(Circle((cx, cy), od / 2, fill=False, lw=1))
        ax.add_patch(Circle((cx, cy), HUB / 2, fc="white", ec="black", lw=.8, ls="--"))
        ax.text(cx, cy - od / 2 - .45, f"{od:g} cm", ha="center", fontsize=8)
ax.text(2, 8.2, "1. Measure the flat back of the rim (inside the tyre). Cut out the BIGGEST disc that fits flat.\n"
        "2. Cut the dashed centre hole; widen it until it slips over the hub.\n"
        "3. Glue the paper onto thin card or foam board first (stiff + flat), then hot-glue / double-tape it\n"
        "   flat onto the back of the rim, centred. It covers the spoke holes - fine.\n"
        "4. Sensor on the axle tube, eyes pointing at the disc, 0.5-1 cm away, halfway between hub and edge.\n"
        "5. Turn the wheel slowly: the sensor light must blink 6 times per turn. Tune the blue knob if not.\n"
        "   Black = no reflection, white = reflection. Peel the old spoke tape off first (it confuses it).", fontsize=8.5, va="top")
ax.plot([2, 12], [2, 2], "k", lw=2); ax.plot([2, 2], [1.8, 2.2], "k"); ax.plot([12, 12], [1.8, 2.2], "k")
ax.text(7, 2.3, "10 cm: measure this! If it is not 10 cm, reprint at 100% / Actual size", ha="center", fontsize=7)
out = os.path.join(os.path.dirname(os.path.abspath(__file__)), "encoder_disc.pdf")
with PdfPages(out) as pdf: pdf.savefig(fig)
print(out)
