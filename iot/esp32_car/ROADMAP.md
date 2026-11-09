# Nova Crawler — roadmap to a world model

The one ordered list. Do the steps top to bottom; each has a **done when** so there's no guessing.
Current state lives in `HANDOFF.md`; this file is *what's next*. Tick `[x]` as you go.

End goal: the car learns a model of how its camera view changes when it drives, then plans its own
moves by imagining ahead. The ESP32 stays the dumb, safe motor executor the whole way through.

```
 Phase 0  make the car reliable        (now, ~₹100)
 Phase 1  record data on the cam we have  (free — builds the whole pipeline)
 Phase 2  Raspberry Pi camera upgrade   (~₹6,500 — the real dataset)
 Phase 3  train the world model + let it drive
```

---

## Phase 0 — make the car reliable

Nothing downstream works if the car reboots or the IPs move.

- [x] **0.1 Buy (one SP Road trip):** 104 ceramic caps (100nF, 50V+) ×10 (need 4).
      Online fallback: Robomart 104 ×20 ₹23 / Amazon.in Electrobot 104 ×100.
- [x] **0.2 Solder a 104 across the steering motor terminals** (and one across each drive motor).
      *Done when:* holding steer 5s never changes `home/car/boot` (still resets = cap too far from motor).
- [ ] **0.3 Solder a 104 across the battery divider's 27k** (● → GND).
      *Done when:* OLED % holds within ±2% over 5 min parked.
- [ ] **0.4 Fixed IPs (DHCP reservations)** in the router (192.168.68.1) for: the Mac (broker),
      car ESP32, CAM 01 (`68:25:dd:2e:7c:14`), later the Pi. Find MACs with `arp -a`.
      Then set `secrets.h` broker IP once and forget it.
      *Done when:* a router reboot changes nothing.
- [ ] **0.5 Reconnect the sonar** (reads `-1`): VCC→5V, Trig→18, Echo→19 via 1k/1.8k divider.
      *Done when:* `home/car/distance` tracks a hand at 10–100cm.
- [ ] **0.6 Steering hold check:** hold ◀/▶ on the phone — wheels must *stay* turned.
      Drifting back → raise `STEER_HOLD` (160) in `esp32_car.ino`.
- [ ] **0.7 Battery mount:** velcro strap; mark `+` on both SM-4P halves if it isn't keyed.
- [x] **0.8 Floor drive test** (after wheels-up passes): CRAWL, then SPORT. Note turning circle.

## Phase 1 — data pipeline on the ESP32-CAM we already have

Low-quality data, but it builds and debugs *every* piece we'll reuse with the Pi.

- [ ] **1.1 Mount CAM 01 on the car**, facing forward, low. Power from the UBEC 5V (check the UBEC's
      amp rating covers ESP + cam + servo; cam peaks ~500mA). Twist its power leads.
      *Done when:* car + cam both stay online through a 2-min drive (check `home/car/boot`).
- [ ] **1.2 Recorder test** — `python3 ~/anish-ai/worldmodel/record.py` (written, self-test passes).
      *Done when:* 60s run → frames + `log.csv`, steady fps, throttle/steer columns match what you did.
- [ ] **1.3 Replay viewer** — `worldmodel/replay.py`: plays a run back with the action overlaid.
      This is how bad data gets caught before training on it.
- [ ] **1.4 Collect ~30 min** of varied teleop: straights, turns both ways, reversing, approaching
      walls, different rooms/light. Many short runs beat one long one.
- [ ] **1.5 First tiny model on the Mac** (M4, PyTorch MPS): 64×64 grayscale, action-conditioned
      next-frame predictor (small conv encoder → GRU → decoder).
      *Done when:* predicted next frames beat "copy the last frame" on held-out runs. Proves the loop.

## Phase 2 — Raspberry Pi upgrade (the real dataset)

Why: 30fps steady, 120° colour, and frames recorded **on the car** with exact timestamps, so WiFi
drops can't corrupt the dataset. Also the planned "Pi vision offload" from the JARVIS roadmap.

- [ ] **2.1 Buy:**
      | Part | ~₹ | Note |
      |---|---|---|
      | Raspberry Pi Zero 2 W | 1,750 | Robu / ThingBits / Evelta (check stock) |
      | Camera Module 3 **Wide** (120°) | 4,380 | Robocraze / Robu |
      | **Pi Zero camera cable** | 150 | the Zero's camera port is smaller — standard cable won't fit |
      | microSD 32GB (A1/A2) | 400 | |
- [ ] **2.2 Set up the Pi:** Raspberry Pi OS Lite 64-bit (Imager: set WiFi + SSH + hostname
      `nova-pi`), reserve its IP (0.4), `ssh`, `sudo apt install python3-picamera2 python3-paho-mqtt`.
      *Done when:* `rpicam-still -o test.jpg` works over SSH.
- [ ] **2.3 Power it from the car:** UBEC 5V → Pi 5V + GND pins (Pi ~0.5A + cam ~0.25A; confirm the
      UBEC's rating first). Never from the pack directly.
      *Done when:* 10-min drive with no Pi reboot (`uptime`) and no car reboot.
- [ ] **2.4 Port the recorder to the Pi** (`worldmodel/record_pi.py`): picamera2 at 30fps, save
      small frames (e.g. 160×120) + the **same `log.csv` columns** so Phase 1 tools work unchanged;
      MQTT from the Mac broker for actions; write to SD; `rsync` runs to the Mac after.
- [ ] **2.5 Live FPV:** Pi serves an MJPEG preview → add it as a camera in `nova_vision.html`.
- [ ] **2.6 Collect 2–5 hours** of varied driving (same rules as 1.4). This is the training set.
- [ ] *(later, optional)* Pi ↔ ESP over UART instead of WiFi for lower control latency.

## Phase 3 — world model + let it drive

- [ ] **3.1 Train** a latent world model (DreamerV3-style RSSM) on the Phase-2 data, 64×64 colour.
      Mac MPS for small runs; rent a cloud GPU for full ones.
      *Done when:* 2–3s open-loop "dream" videos look like the real drive for the same actions.
- [ ] **3.2 Planner:** imagine many action sequences in the model, pick the best (CEM/MPC), send the
      first action via MQTT — runs on the Mac (or the Pi for small models).
- [ ] **3.3 Closed loop, wheels-up first**, then floor. The firmware's safety stays in charge:
      15cm sonar stop, deadman pulse, LOW-battery lockout, MQTT-loss stop.
- [ ] **3.4 First task:** drive around a room without hitting anything; then "drive to the <object>".

---

## Rules that never change
- Battery `+` touches the L298N `+12V` only — never an ESP/Pi pin.
- New motion code runs **wheels-up** first.
- Car stops responding → check `home/car/boot` (reset reason) before anything else.
- Unplug the SM-4P before plugging USB in to flash.
