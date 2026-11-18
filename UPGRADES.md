# Future upgrades: Nova and the room

Parked on 2026-11-18. Items were skipped or deferred, not rejected. Pick any one and say "do #N".

## Reliability
1. **Room node power.** Give it its own 5 V 2 A charger, a short thick cable, and a separate strip supply (join GND only), plus a 470–1000 µF capacitor on 5 V.
   - Today it froze and needed a USB unplug, so power is the likely cause.
2. **Room node watchdog and restart reason.** Reboot itself if frozen for 60 s, and report why it last restarted. Needs one USB flash.
3. **Router address reservation.** In the Deco app: More → Advanced → Address Reservation.
   - Room node: .104 (it was .108 before 2026-11-18).
   - Bed mic: .107.
4. **Reseat the table mic wires.** They caused low thumps. The 200 Hz software filter hides them, but the cause is still there.
5. **Bed strip Bluetooth drops** cause a 2–3 s lag behind the table. Fix with a shorter distance or fewer obstacles between the hub and the bed strip.

## Voice
6. **Accept "Now…"/"No…" as the wake word only when you're close to a mic.** About 1 hour of work. Catches most misses without the TV waking Nova.
7. **A trained "Nova" wake-word model** (openWakeWord). Needs about 200+ recordings of you; there are 29 now.
   - Best accuracy, and it stops the hub transcribing all speech.
   - Run it side by side with the current method before switching.
8. **Skip empty recordings.** About 80% of STT jobs come back empty. The Silero VAD test missed 4 of 44 real clips; retry with a lower threshold.
9. **Speaker vs mic echo.** Keep the speakers away from the table mic. Echo fingerprinting is dad's idea; see `nova-echo-fingerprint-plan`.

## Projector
10. **Real on/off state.** For now, say "Nova, the projector is on/off". Better options:
    - put its USB power on the K4 relay (₹0, if it switches itself on when power returns);
    - a Tuya plug with power reading (~₹800);
    - an LDR on the bed-mic ESP32 (DO→GPIO27, VCC→GPIO26).

## Lights
11. **Copy the bed's other effects to the table** (fade, flow, wave…). Film each on the bed, as was done for party.
12. ~~Give evening its own look~~ **done 2026-11-18**: sunset bulb at 70%, orange strips at 60%.
13. **Focus routine's rainbow fade speed.** It starts at full speed; slow it down if it's distracting.

## Desk and control
14. **Desk touchscreen panel** (parked 2026-11-18: "do we need it?" → not yet; use /deck on the phone for a week first).
    - Pick: **Robu.in 2.8" SPI Touch Screen Module 240×320 V1.2, SKU R260027, ₹779**
      (https://robu.in/product/ntl-28-inch-spi-touch-screen-module-tft-interface-240320-v12/). Resistive touch plus stylus,
      ILI9341 or ST7789 (either may ship), 3.3 V logic.
    - Drive it from the user's **spare ESP32**, never the room node or the bed mic. Needs ~14 F-F jumper wires.
    - Firmware to write: the same buttons as `DECK` in light_panel.py, sent over MQTT, ~12 per page.
    - Skip: Amazon oceanlabz ₹1,000 (same screen); UNO parallel shields (₹356–850; wrong bus); the ₹629 "without Touch" listing.
    - All-in-one alternative: CYD ESP32-2432S028R (~₹1–1.5k Robu, ₹3,833 Amazon).
15. **Room node box.** Design in `desk/HANDOFF.md`. First answer: does K4 switch 230 V?
16. **The ₹0 desk tidy-up.** See `desk/HANDOFF.md`.

## Other
17. **Sleep-cycle tracker.** Requested 2026-11-16; overdue.
18. **Delete the old `nova.log.1`.** It holds background-speech transcripts from before the privacy fix. Deleting is permanent.
19. **Raspberry Pi vision offload.** See `jarvis-architecture-roadmap`.
