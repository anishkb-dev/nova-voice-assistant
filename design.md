# J.A.R.V.I.S. — Design System

The rules every Jarvis UI follows so it stays consistent and tasteful. When
changing the interface, read this first; when adding something new, extend the
tokens here rather than inventing one-off values.

Taste = constraints. Few colors, a fixed spacing scale, two fonts, motion with
a reason. Everything below exists to keep those constraints.

---

## 1. Color

A single accent (cyan) on near-black. Semantic states are the *only* other hues.

| Token | Value | Use |
|---|---|---|
| `--bg` | `#02060b` | Page ground (near-black, cyan-biased) |
| `--panel` | `rgba(8,22,32,.7)` | Panel fill (translucent + blur) |
| `--cy` | `#26e6ff` | **Primary accent** — the one hero color |
| `--cy2` | `#12a8d8` | Accent, darker (gradients, hovers) |
| `--ice` | `#bff6ff` | Bright text / values (emphasis) |
| `--txt` | `#bfeaff` | Body text |
| `--dim` | `#4f7d8c` | Labels, secondary text, inactive |
| `--line` | `rgba(38,230,255,.2)` | Hairline borders |

**State colors** (never used as decoration — only to signal state):
`--grn #38ffa8` listening/ok · `--amber #ffb020` thinking/warn · `--red #ff5470` critical/motion.

Rule: one accent. If something needs to stand out, use `--ice` (brightness),
not a new color.

## 2. Spacing

A 4-based scale. Nothing between the steps.

`4 · 8 · 12 · 16 · 20 · 24 · 32`

Layout padding is responsive: `clamp(12px, 2vw, 32px)`. Gaps use `gap`, never
per-element margins (avoids collapse/double-margin bugs).

## 3. Type

Two faces, one scale.

- **Display / headings:** `Space Grotesk` — wordmark, big numbers.
- **Body / data / labels:** `JetBrains Mono` — everything else; `tabular-nums` on any aligned digits.

| Role | Size | Tracking | Weight |
|---|---|---|---|
| Wordmark | 28px | .14em | 700 |
| Section label | 11px | .2–.28em, UPPERCASE | 700 |
| Body | 13–14px | .02em | 400 |
| Big value | 24–40px | — | 600 |
| Micro label | 9–10px | .2em, UPPERCASE | 700, `--dim` |

Uppercase everything that's a label; keep sentence case for readable content.

## 4. Motion  ← the part that makes it feel premium

Motion communicates state and cause. Never decorate with it.

**Easing** (define once as tokens):
- `--ease-out: cubic-bezier(.22,1,.36,1)` — for things **entering** (fast→slow, feels instant)
- `--ease-in-out: cubic-bezier(.65,0,.35,1)` — for state changes / moves

**Duration:** 180–320ms for UI. `--t-fast:180ms` `--t:260ms` `--t-slow:420ms`.
Ambient loops (orb pulse, scanline) are separate and slow (3–10s).

**Choreography:**
- Entrances **stagger**, they don't all fire at once. Order = reading order
  (left panel → center → right panel → command bar), ~80ms apart.
- One thing draws focus at a time.

**Rules:**
- Enter with `--ease-out` + slight translate (8–12px) + fade.
- State transitions (color, width, arc) animate through tokens, not instantly.
- Hover: subtle (border/opacity/glow), `--t-fast`.
- **Always** honor `@media (prefers-reduced-motion: reduce)` — kill transforms/loops.

## 5. Structure

- Corner **reticle brackets** frame panels (signals "instrument", not "webpage").
- Panels: 1px hairline border + translucent fill + `backdrop-filter: blur`.
- Wide content (charts, tables) scrolls inside its own `overflow-x:auto`.
- Interactive things must *look* interactive (cursor, hover state, focus ring).

## 6. Voice / copy

- Labels name what a person recognizes (`NETWORK LINK`, not `wlan0`).
- A control says what happens (`EXECUTE`, `ALL OFF`).
- Jarvis speaks in character; the UI stays terse and technical.

---

*Change the look? Change a token here, and it propagates. Don't hardcode a
color or a duration in a component — reach for the token.*
