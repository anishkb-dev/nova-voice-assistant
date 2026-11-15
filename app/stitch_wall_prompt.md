Design a NEW screen in this project: "NOVA Wall Display" — an always-on, glance-only HUD for a 24-inch 1920×1080 monitor on my bedroom wall, read from across the room (2–4 m away, often from bed). Same visual language as my existing NOVA Tactical Holographic HUD v3: deep near-black background (#050302), amber #FF9A42 primary, pale amber #FFD9A8 highlights, dim rust #9A4A12 for secondary lines, thin 1px amber panel borders with small glowing corner brackets, subtle dot grid and faint scanlines, Rajdhani for labels and JetBrains Mono for numbers. Iron Man / Stark workshop feel. NO blue or cyan anywhere.

This screen is DISPLAY ONLY: nobody touches it. No buttons, no D-pad, no text input box, no toggles, no light switches, no presets, no menus. Everything must be readable at distance: the smallest text 18px, key numbers 64–140px. Fewer, bigger things — not dense dashboard tiles.

Frame: exactly 1920×1080, fixed, no scrolling.

LAYOUT (three zones):

1. CENTRE (the hero, ~45% of the width): the arc reactor — the same style as v3 (outer tick dial, segmented arcs, 10 trapezoid coils, glowing white-amber core), but larger, ~560px. Directly under it, one voice-state line: "LISTENING" / "PROCESSING" / "SPEAKING" in big tracked Rajdhani with a thin waveform beside it. Under that, the conversation: my last command in dim pale amber in quotes (e.g. “turn on the bulb”), and Nova's reply below it, larger and bright (e.g. "Bulb on, sir."), max two lines, centred.

2. LEFT column: 
   - A huge clock: "21:47" (~140px JetBrains Mono, pale amber glow), seconds small beside it, and the date "SUN 15 NOV" under it.
   - ROOM block: temperature "24.8°C" and humidity "62%" as two large numbers each with a thin arc gauge; a motion line "MOTION: CLEAR" / "MOTION: DETECTED" with a small dot that glows when detected.
   - WEATHER block: outside temperature, condition word (e.g. "LIGHT RAIN"), today's high/low.

3. RIGHT column:
   - DEVICES block, read-only status rows with a small diamond indicator each: "CEILING BULB  ON · WARM 70%", "BED LIGHTS  ON · ORANGE", "AC  ON · 21°C", "PROJECTOR  OFF". Status only — these are not buttons.
   - SYSTEM block: "HUB  ONLINE", "ROOM NODE  ONLINE", hub CPU % and memory % as two slim bars, Wi-Fi name + signal %.
   - RC CRAWLER block (small): "LINKED" / "NO LINK", last seen "3s AGO", signal "-58 dBm". No controls.

TOP edge: a thin header line — "NOVA" wordmark with a small amber diamond on the left; on the right a small "WAKE WORD: NOVA".

BOTTOM edge: one thin ticker line in dim rust, e.g. "NEXT ROUTINE: GOOD NIGHT 23:30  //  CLAUDE SESSION 65K / 200K  //  UPTIME 7D 13H".

Mood and motion hints (static mock is fine, but design so these read clearly): the reactor is the one thing that moves — it glows brighter and its halo swells while Nova speaks. Everything else is calm and still. Large negative space between blocks; panels breathe. Night-friendly: keep overall brightness low except the reactor core, the clock and Nova's reply.

Also design a second variant, "NOVA Wall Display — Night": the same layout dimmed to ~30% brightness, only the clock, reactor core (very faint) and room temperature remain readable; everything else nearly invisible.
