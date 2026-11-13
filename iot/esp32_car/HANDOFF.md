# ESP32 car — handoff (2026-09-20)

> **CURRENT STATE: jump to the last entry (2026-10-21).** The "Where things stand" section below is old (pre-rebuild).

> **What to do next lives in `ROADMAP.md`.** This file is the state + history.

Everything from the bench session. Point a new chat at this file.

## Where things stand

Obstacle-avoidance autonomy is **written and compiling** in `esp32_car.ino` but **not flashed**
and **never tested on hardware**. Two non-code blockers:

1. **Servo browns out the board.** The SG90 is still drawing from the ESP's 5V pin. Its surge
   drags the 3.3V rail under the brownout threshold, the chip resets, `setup()` drives the servo
   again — a loop at roughly 8 resets/sec. Needs its own 5V (UBEC, power bank, or 20W plug),
   with that supply's ground tied to the ESP ground.
2. **Battery is dead.** New 7.4V pack ordered, arriving 2026-09-21. No motor power until then.

The sonar half is **confirmed working** on the bench: 25 consecutive readings, no dropouts,
tracked a hand from ~37cm down to ~30cm through the divider on GPIO19.

## Battery

**New 7.4V pack** arrived ~2026-09-22 — the user has a photo of its connector to share. Not yet
wired in or identified. Before connecting anything, establish from the connector/label:
- **Chemistry** — LiPo needs a *balance* charger; a Li-ion 2S with a protection board may use a
  simpler charger. Confirm what charger came with it before charging.
- **Which pins are + and −** — meter it if possible.

**Old pack (dead):** CL 14500 1000mAh, 3.7V × 2 = 7.4V 2S, **SM-4P** connector. With no meter,
the valid +/− pair was found by watching the UBEC's LED light up on the correct pair.

**Wiring rule, non-negotiable:** pack `+` → **L298N `+12V` only**. Pack `−` → L298N GND, tied to
common ground. Never to an ESP pin, never to the 5V rail — that is what killed an earlier board.
The pack also feeds the **UBEC input**; UBEC output (jumper on **5V**, measured 5.42V) feeds the
ESP's 5V and the servo. L298N 5V-EN jumper stays OFF.

**First drive at 7.4V:** set `home/car/speed` low (~40) before touching throttle — it will be far
punchier than the 5V bench runs.

## Hardware

| Item | State |
|---|---|
| Car ESP32 (current) | **working**, MAC `20:50:0d:4d:ec:2c`, CP2102 on `/dev/cu.usbserial-0001`, 40MHz crystal, 4MB |
| Previous ESP32 | **DEAD** — see below |
| HC-SR04 | working, Trig GPIO18, Echo GPIO19 via divider |
| SG90 servo | untested — never had clean power |
| L298N, OLED, motors | as before, unchanged |

### The dead board
Powered (PWR LED lit, 3V3 = 3.3V, EN = 3.3V so not held in reset) yet emitted **nothing** on TX0
across ~30 esptool attempts — own CP2102 and external FTDI, both TX/RX orientations, every baud,
BOOT-held and manual download mode. A working ESP32 prints its ROM banner on every power-up even
with blank flash. No banner + good rails = dead. Replaced.

**Fastest dead-or-alive test:** listen on TX0 at 115200 with DTR/RTS both *asserted* (not toggled)
and tap EN. Live chip prints the ROM banner; dead one gives 0 bytes.

## Toolchain

`arduino-cli` 1.5.1 installed via brew. Its macOS data dir **is** `~/Library/Arduino15`, so it
reuses the IDE's `esp32:esp32 3.3.11` core — no re-download, no board re-config, no clicking Verify.

```bash
# compile
cd ~/anish-ai/iot/esp32_car
arduino-cli compile --fqbn esp32:esp32:esp32 --output-dir /tmp/build .

# flash (460800 works fine on the current board; no BOOT button needed)
ESPTOOL=~/Library/Arduino15/packages/esp32/tools/esptool_py/5.3.1/esptool
BOOT0=~/Library/Arduino15/packages/esp32/hardware/esp32/3.3.11/tools/partitions/boot_app0.bin
$ESPTOOL --chip esp32 --port /dev/cu.usbserial-0001 --baud 460800 --after hard-reset \
  write-flash -z --flash-size 4MB \
  0x1000 build/*.bootloader.bin 0x8000 build/*.partitions.bin \
  0xe000 $BOOT0 0x10000 build/*.ino.bin

# app-only reflash is enough for iteration
$ESPTOOL --chip esp32 --port /dev/cu.usbserial-0001 --baud 460800 --after hard-reset \
  write-flash -z --flash-size 4MB 0x10000 build/*.ino.bin
```

Serial is **115200** (crystal is 40MHz — confirmed via `esptool flash-id`).

## Pin map

| GPIO | To |
|---|---|
| 13 | L298N `ENA` — drive PWM |
| 14 / 27 | L298N `IN1` / `IN2` — drive direction |
| 26 / 25 | L298N `IN3` / `IN4` — steer direction |
| 33 | L298N `ENB` — steer PWM |
| 34 | battery divider ● (input-only, ADC1) |
| 35 | FC-51 IR OUT — wheel ticks (input-only; module VCC on 3V3) |
| 21 / 22 | OLED + MPU6050 SDA / SCL (shared I2C: OLED 0x3C, MPU 0x68) |
| 18 | HC-SR04 Trig (direct) |
| 19 | HC-SR04 Echo — **through the divider** |
| 23 | SG90 signal |
| ~~5~~ | **left empty** — strapping pin; a servo wire here can block download mode |

### Echo divider
`Echo ──[1kΩ]── GPIO19 ──[1.8kΩ]── GND` → 3.21V. User had no 2kΩ; 1.8k beats 2.2k (3.44V) for
headroom. ~9mW, quarter-watt parts are fine. 1kΩ = brown·black·red, 1.8kΩ = brown·**grey**·red.

## Autonomy (written, untested)

In `esp32_car.ino`. Head scans left 40° / ahead 90° / right 140°, one angle per `loop()` pass so
MQTT never goes deaf mid-sweep. Forward while ahead is clear; inside `AVOID_CM` (35) it turns
toward the roomier side; inside `STOP_CM` (15) it reverses with opposite lock first — a crawler
steers with a steering motor and cannot pivot in place, so every heading change costs travel.

| Topic | Payload |
|---|---|
| `home/car/mode` | `auto` / `manual` |
| ~~`home/car/scan`~~ | removed 2026-10-09 (fixed sonar) — use `home/car/distance` |
| `home/car/distance` | cm ahead, 1Hz |

Interlocks: auto starts **OFF** every boot; any manual throttle/steer kills auto; the 15cm stop
applies in **both** modes; MQTT loss disarms. Auto uses duty 200, not teleop's 255.

Tunables at the top of the file: `STOP_CM`, `AVOID_CM`, `SCAN_ANG`, `SETTLE_MS`, `BACK_MS`,
`TURN_MS`, `AUTO_DUTY`.

## Bench sketch

`sonar_servo_test/sonar_servo_test.ino` — standalone, no WiFi/MQTT/motors. Scans and points the
head away from the nearest obstacle. Has a `selfTest()` that asserts the avoid logic against five
synthetic cases at boot and prints PASS/FAIL before anything moves.

## Gotchas that cost real time

- **Never run two esptool loops at once.** They fight for the port and every handshake returns
  "Invalid head of packet", which reads exactly like hardware noise. Check `pgrep -fl esptool`.
- **`cmd | tail && break`** in a retry loop breaks on the first iteration regardless of failure —
  the pipeline's status is `tail`'s. Use `if cmd > log 2>&1; then ... fi`.
- **Arduino IDE's `serial-monitor` helper silently re-grabs the port.** `pkill -f serial-monitor`
  before every probe.
- **A charge-only micro-USB cable** powers the board (PWR LED lit) but the CP2102 never
  enumerates — the `/dev/cu.usbserial-*` entry just vanishes. Check `ls /dev/cu.*` first.
- **Byte-rate heuristics lie on this CP2102 driver.** It reported 27KB/s on a 115200 port, which
  is physically impossible. Judge by content, not throughput.
- **Battery `+` touches the L298N `+12V` and nothing else.** Ever. That killed an earlier board.
- **Tug-test every dupont.** A loose jumper has cost hours twice on this build.

## Diagrams

- Bench rig (sonar + servo, hole by hole): https://claude.ai/artifact/4KB9NMpcHFC2cY1Hxn4pj9
- Whole car (power domains, pin map, jumpers): https://claude.ai/artifact/XQUpWr38c9pQVEKrVrjj8h

## Next steps

1. Give the servo its own 5V + common ground; confirm the board stops reset-looping.
2. Flash `esp32_car.ino`, check `home/car/scan` publishes sane left/ahead/right.
3. Battery in on the 21st → wheels-up test of auto mode before letting it on the floor.
4. Tune `AVOID_CM` / `TURN_MS` against how the crawler actually turns.

---

## SESSION UPDATE — 2026-09-27 (car split into its own chat)

**Broker IP drifted → firmware updated.** The Mac's IP moves on DHCP; `secrets.h` `SECRET_BROKER_IP` is now **`192.168.68.112`** (was `.105`). This *will* break again on the next shuffle. **Real fix: a DHCP reservation / static IP** for the Mac (broker) + each ESP + the cameras, so nothing drifts. Until then, when the car goes silent on MQTT, check the Mac's IP (`ipconfig getifaddr en0`) and re-point `secrets.h` + reflash.

**Car ESP is alive & online** (MAC `68:09:47:59:bc:b8`… note: MACs seen across boards — `b4:bf:e9:02:27:38` and `20:50:0d:4d:ec:2c` too; confirm the physical one). On `/dev/cu.usbserial-0001`, flashes clean at 460800, no BOOT-hold. Publishes `home/car/{status,telemetry,scan,distance,battery,i2c}`.

**Battery voltage display — CODE DONE, HARDWARE UNFINISHED.**
- Firmware added: reads a divider on **GPIO34** (ADC1, input-only), shows `X.XV` centered in the OLED top bar, publishes `home/car/battery` + `vbat` in telemetry, and the phone app (`~/anish-ai/app/car_control.html`) now has a colour-coded **BATTERY** row. Constants at top of `esp32_car.ino`: `VBAT_PIN 34`, `VBAT_R1 99000`, `VBAT_R2 26500` (measured actual resistor values, not nominal), `vbatCal 1.000`. Compiles + flashes clean.
- **Divider — resistors fixed, reading still low (2026-09-27 pm).** The "33k" was actually **33Ω** (orange·orange·**black**) — that was the 0.57V. Replaced with a **27k** (measured 26.5k; 100k measured 99k; series 125.5k ✓). Wiring: `balance-plug red →[100k]→ ● →[27k]→ ESP GND`, balance-plug black → ESP GND, ● → GPIO34. Pack metered **8.17V**; the ● metered **1.69V** vs ESP GND = correct.
- **DONE — soldered + calibrated.** Joints soldered (twists/duponts were the flakiness). ADC reads this pin ~27% low, so **`vbatCal 1.373`** (meter 8.17 ÷ reading 5.95). It wanders for ~1 min after boot, then holds **8.03–8.08V**, OLED **82%**. No capacitor on hand; a 100nF (or any 10nF–10µF) ● → GND would steady it further. **Permanent wiring done (2026-09-27):** pack now feeds the car via the **SM-4P** → L298N `+12V`/`GND`; divider taps **L298N `+12V` →[100k]→ ● →[27k]→ L298N GND**, ● → GPIO34. Reads **7.94–8.06V**, positive = polarity correct. Balance plug is free again (charging only). ⚠️ **Battery reading is only valid on battery power.** With USB plugged in alongside the pack it drops to ~4.5V (verified: unplug USB → back to ~8.0). Ignore `vbat` while flashing.
- **Battery % (pack is 2S Li-ion):** firmware `battPct()` = piecewise Li-ion resting curve (6.60V=0 · 7.04=10 · 7.24=20 · 7.44=40 · 7.66=60 · 7.96=80 · 8.30=100), 5-point display hysteresis, published as `pct` in telemetry; OLED + phone app both show that one number (`--%` = no pack, e.g. USB only). ~20s EMA on `vbat`.
- **Low-battery cutoff:** raw `vbat < LOW_CUT_V` (6.4V = 3.2V/cell loaded) for **30 consecutive seconds** (one false trip from a wiggled wire happened when it used the smoothed value), ignored for the first 60s after boot and when <5V (USB-only ~0.9, USB+pack ~4.5) → **latches** `lowBatt`: drive+steer locked off (enforced inside `drive()`/`steer()`, so auto can't bypass), OLED shows `LOW`, telemetry `"low":true`, app shows "LOW — CHARGE". Clears only on power-cycle.

**Sonar = `-1`** (scan l/a/r + distance all -1) — HC-SR04 not responding. Was confirmed working before, so it's **unplugged/unpowered** — check VCC→5V, Trig→18, Echo→19 (1k/1.8k divider). NOTE: PIR on the *room* node also uses GPIO34 — that's a different board, no conflict.

**Motors/servo = untested** — need the battery on L298N `+12V` (+ servo's own 5V). Wheels-up, start `home/car/speed` low (8.4V is punchy).

**Battery pack + power connector:**
- New **2S pack, fully charged to ~8.4V.** Charge via the **white balance lead → iMAX B3 `2S` port** (CELL3 LED stays off/ignore for 2S; done = CELL1+CELL2 green; meter ~8.4V).
- **Power source right now (2026-09-27):** pack voltage is fed from the **white balance/charging port** — but only to **test the battery reader** (ESP + divider, µA draw). That's fine; the thin balance wire handles µA easily. It is **NOT powering the motors.**
- ⚠️ **Before any drive test, switch to a thick connector.** The balance lead can't carry motor current (1–3A → overheat/melt + cell imbalance). Use the **red T-plug** (cut→bare leads into L298N, or a male pigtail) or the **SM-4P 4-pin** (middle two = pack ±, polarity-checked). Balance lead stays charging-only.
- The SM-4P 4-pin option (not used): its **middle two wires = pack+/−**, **outer two = the joined series bridge** (leave alone), **match polarity** or it fries the ESP. No male T-plug pigtail on hand; SP Road has a ₹30 one same-day.

**Toolchain:** `arduino-cli` config at `~/anish-ai/.arduino/arduino-cli.yaml` (libs installed there: PubSubClient, Adafruit SSD1306/GFX/BusIO, ESP32Servo). Compile: `arduino-cli --config-file ~/anish-ai/.arduino/arduino-cli.yaml compile --fqbn esp32:esp32:esp32 --output-dir <dir> .` — needed because macOS TCC blocks the shell from `~/Documents/Arduino/libraries`.

**Cameras (Phase B, adjacent):** CAM 01 drifted `.106 → .115 → .114` (2026-09-27 eve; MAC `68:25:dd:2e:7c:14` — find it with `arp -a | grep 68:25:dd`; dashboard key now `nova.cams.v4`) (live, grayscale 240×240 stream at `http://192.168.68.115:81/stream`). CAM 02 `.118` offline. Dashboard `~/anish-ai/app/nova_vision.html` updated to `.115` (storage key bumped to `nova.cams.v3`); served via `python3 -m http.server 8080 --directory ~/anish-ai/app`.

**Next steps: see `ROADMAP.md`** (ordered, phases 0–3, including the Raspberry Pi upgrade). The old lists above are superseded.

## SESSION UPDATE — 2026-09-27 evening (controls)

- **Control lag / "not responding" fixed:** `onMqtt()` used to call `showOLED()` on every command — a full SSD1306 frame at the default 100kHz I2C blocks ~100ms, and the phone joystick published a steer msg on every `pointermove` (~60/s). Commands queued behind redraws and the 600ms deadman expired mid-hold. Now: no redraw in `onMqtt` (loop redraws every 120ms), `Wire.setClock(400000)`, and `car_control.html` sends steer only when the (5%-stepped) value changes.
- **Steering too weak:** proportional floor raised 130 → **205** (`map(mag,12,100,205,255)`), `STEER_PWM` 220 → 255. Toy steer motor fights a return spring; steers far easier while rolling.
- **`car_control.html` broker** is now `ws://<page host>:9001` — served from the Mac, so IP drift can't break it. Battery gauge bar added (uses firmware `pct`/`low`).
- **Charger:** iMAX B3 won't top up a pack at ~4.05V/cell (shows all green) — normal. Always plug **charger power first, then pack** (reverse order misdetects cells → CELL3 red). Pack is 2S **Li-ion** (4.2V/cell, fine on this LiPo charger).
- **Broker Nagle fix:** added `set_tcp_nodelay true` to `/opt/homebrew/etc/mosquitto/mosquitto.conf` (backup `.bak`), `brew services restart mosquitto`. Small teleop packets were being batched (Nagle + ESP delayed ACK) → lag spikes.
- **Steering joystick → ◀ ▶ hold buttons** in `car_control.html` (full steer power, release = center). Joystick version saved in the session scratchpad only.
- **Steering reset the ESP (root-caused 2026-09-27):** every steer press rebooted the car (`home/car/boot` = `poweron`; ESP32 reports EN-pin glitches as poweron). Pack held 8.05V and ESP 5V held 5.14V under steer; with the steer motor unplugged there were zero resets; motor = 4.4Ω (healthy). → **brush noise from the steering motor.** Fix that worked: **twist the steer motor's two leads tightly + route away from the ESP**. Firmware also does kick (255) then hold (`STEER_HOLD 160`) on heartbeat repeats. **Still to do: solder a 104 (100nF) cap across the steer motor terminals** (and ideally the drive motors) — belt and braces.
- `home/car/boot` (retained) = last reset reason + uptime at connect. Check it first whenever the car "stops responding".
- Test harness: a script that re-sends commands every 200ms like the phone and timestamps telemetry — a reboot shows as a telemetry gap + `status offline/online` + fresh `boot`.

**Mounting (2026-09-28):** ESP32, L298N, battery pack, UBEC and OLED are now mounted, all on the top of the chassis (single layer). Target layout drawing: `docs/layout.png` (regenerate with `python3 docs/draw_layout.py`). Keep the front ~7×5cm free for the Pi Zero 2 WH + Camera Module 3 Wide.

**Motor noise fixed (2026-10-02):** 104 caps soldered across the steering motor wires (~2–3cm from motor) and across BOTH drive motors' wires (the OUT1/OUT2 pair splits to two motors — front + rear, ~1Ω combined; caps outside the gearbox, not opened). Steering leads re-twisted full length. Before the drive caps, forward/back also reset the ESP (`poweron`/`wdt`). Verified: held steer left 3s + right 3s on battery → no new `home/car/boot`, wheels turned both ways. Firmware unchanged (STEER_PWM 255 / STEER_HOLD 160). Not yet done: cap on the divider (● → GND); optional 104 from ESP `EN` → GND if resets ever return; firmware soft-start held in reserve.

**Hang after brownout → loop watchdog (2026-10-02):** carrying the car around gave a `brownout` reset, after which the car hung: OLED frozen, ESP pingable on WiFi (.100), but MQTT dead for minutes (LWT "offline"); only a battery replug cleared it. Firmware now calls `enableLoopWDT()` at the end of `setup()` (feeds inside the WiFi/MQTT retry loops, `mqtt.setSocketTimeout(4)`), so a stuck loop >5s resets as `task_wdt` and reconnects itself. Flashed + back online. Brownout root cause likely a loose UBEC→ESP 5V/GND wire — reseat if it recurs. Range test still to redo (first attempt logged nothing — car was hung).

**First floor drive (2026-10-02):** drove on the floor from the phone (buttons UI) — forward, reverse and both steering directions work, no resets (video in WhatsApp). Wiring is a tangle of long jumper loops arching over the car; plan is a single wide PVC-foam tray (open-top box, ≤ tyre width, clears the wheels) + moving the ESP onto the screw-terminal expansion board and cutting wires to length.

**Battery spec (from Amazon order 2026-09-19):** main pack = **ELBOTICS 7.4V 2600mAh 2S Li-ion, 3–5C, SM plug** (~8A+ continuous — fine for both drive motors + steering + Pi). Also owned: Heattack 2× 7.4V 500mAh 14500 packs (SM-4P) — too small for driving with the Pi; spares only. UBEC = **3A** (user read the label 2026-10-02) — enough for ESP + sensors + Pi Zero 2 W + camera (~1.5A peak).

**Pending (2026-10-02, not ordered yet — sitting in the Amazon cart, ₹1,217):** Robocraze GY-521 MPU6050 · Robocraze TCRT5000 ×2 (wheel speed: white tape on driveshaft) · 5× round rocker switch (power switch in pack + line) · Lakeer A4 PVC foam board 5mm ×4 (open-top tray, `docs/box.png`, regenerate `python3 docs/draw_box.py L W H` once measured) · Pidilite Flex Kwik · Scotch 3M mounting tape. Still to pick: M3 screw/nut set + M3 brass standoffs (length = chassis→tyre-top gap + ~1cm; user to measure). Sonar wiring plan: expansion board JUMP → 3.3V, sonar VCC → top-edge `VCC` (5V) pin, Echo via 1k/1.8k → D19·S.

**Car stripped for the rebuild (2026-10-03):** user removed all electronics from the chassis to rebuild into the 12×17cm PVC tray on M3×40mm standoffs (tyres never rise above the chassis-box top — measured: 3cm below at rest, level when fully compressed; the L298N heatsink ~3cm is the tallest thing under the tray). MPU6050 arrived. Firmware with MPU support (`home/car/imu`, 10Hz, raw I2C, DLPF 44Hz) + telemetry buffer fix (payload 96→192; telemetry JSON hits 100 chars) is compiled but NOT flashed yet.

**3D scan (2026-10-03, Scaniverse https://scaniverse.com/scan/mg4s2loqsz6pxdrv, saved `docs/car_scan.spz` — Gaussian splat v3, decodable with numpy):** scaled to the measured 17cm tyre width (scan raw ×0.91): car ≈ **24 × 17 × 11 cm**, wheelbase ≈ 17cm, tyre Ø ≈ 7cm, **chassis box ≈ 9 × 6 cm, top ≈ 8.8cm** above floor, tyre tops 7.4 at rest / ~8.8 compressed, shock towers 9.8. With M3×40mm standoffs on the box the tray floor is at 12.8cm — 3cm above the highest moving part. **Tray bolt holes must be a 7×5cm rectangle CENTRED** (standoffs stand on the narrow chassis box, not at the tray corners). Fit drawing: `docs/car_scan_fit.png`; cutting plan `docs/box.png` (`python3 docs/draw_box.py 12 17 4`).

**Tray built (2026-10-04)** from Umi foam board using `docs/template_umi.pdf` (tab-and-slot walls, inset 0.6cm, double base). Scanned (https://scaniverse.com/scan/bzuj2fgvobuvq5jh, `docs/tray_scan.spz`): **17.2 × 11.9 × 4.9 cm** — matches the plan. Overlay of tray scan on car scan: `docs/tray_on_car.png` — clears everything on 40mm standoffs. Waiting on standoffs (~10 Oct) + bolts (~12 Oct) to mount.

**Broker by name (2026-10-04):** the Mac drifted .112 → **.111** again. Firmware now resolves the broker via mDNS (`MDNS.queryHost("Anishs-MacBook-Air")`, re-resolved on every MQTT connect attempt), falling back to `SECRET_BROKER_IP` (now .111). IP drift on the Mac no longer strands the car. Also: `enableLoopWDT()` moved before the connect loops (feeding it before enabling spammed "task not found"). Bench test on USB: i2c = `0x3C 0x68` ✓, `home/car/imu` streaming (|a| ≈ 1.0 g ✓, gyro bias ~0.5°/s), `home/car/odo` publishing ticks. NB the car got DHCP **.114** this boot — same as CAM 01's last address; DHCP reservations (roadmap 0.4) still needed.

## 2026-10-09 — wheel sensor swap
- Both TCRT5000 boards are dead (D0 stuck 0, A0 ~820 flat at 3.3V and 5V, knob no effect). Kept, not returned.
- Replaced by an FC-51 IR obstacle module (VCC 3V3, GND, OUT -> GPIO35). Bench-tested: OUT 1 = clear, 0 = object; the existing FALLING interrupt counts it, no firmware change.
  Plan: zip-tie + hot-glue to the REAR axle housing, aimed at 4 white tape strips on the inner rim ~0.5-1 cm away -> 4 ticks/wheel turn.
- Later upgrade: LM393 slot "H206" speed sensor + 20-hole disc on the rear hub (same pin, same code) -> 20 ticks/turn.
- One spare ESP32 devkit is dead (no ROM output via its CP2102 or a YP-05 FT232). Labelled. tcrt_test/ = bench sketch: D0 on 35, A0 on 34.
- **Sonar = option A (2026-10-09):** servo head dropped. HC-SR04 fixed in the tray front wall, pinged every 60ms (`pingTick`). Auto mode escapes by ALTERNATING left/right (can't see sides). `home/car/scan` topic removed; `distance` stays. GPIO23 now free. Compiled, not yet flashed.
- **2026-10-10 ~01:00 — car ESP died during the stage-1 power rewire.** Wiring: UBEC +5V -> expansion top-edge `VCC`, JUMP on 3.3V, divider middle accidentally on VIN (harmless via 100k/27k). After battery on: ESP LED on but never joined WiFi; on USB alone, off the board, no ROM output ("Invalid head of packet 0x00") = same as the dead spare. Suspect: top-edge VCC follows the JUMP rail (i.e. 5.4V into 3V3). UNVERIFIED — MEASURE the board's VCC / V / 3V3 / VIN pins with no ESP fitted before trusting it with another ESP.
- **CORRECTION (same night): the car ESP is NOT dead.** On USB alone (on the expansion board) it boots, joins WiFi (rssi -41) and runs stably. The 0x00/no-output state was a hang after a `brownout` reset (needed an RTS reset). Brownouts only on USB+battery -> suspect the twisted UBEC-output joint / UBEC 5V not arriving cleanly. Since the ESP survived, "VCC follows the 3.3V jumper" is unlikely (that would have cooked it) but still worth a meter check. The earlier "dead spare" (also 0x00, USB dropping, through a USB hub) may have been the same power problem — retest it straight into a Mac port.
- **Rewire progress (2026-10-10, ~2am):** stages 1–4 done and verified on battery alone: (1) power — UBEC out -> top-edge VCC/GND (twisted+taped joint, solder later), divider ● -> D34 reads 8.17V/92%; (2) motors — NOT yet rewired (user doing them last); (3) OLED on 21/22 columns + MPU on the board's extra 21/22 header -> i2c 0x3C 0x68; (4) HC-SR04 VCC top-edge 5V, Trig 18, Echo via a NEW 1k/1.8k divider (2.76k total, metered) -> 19, reads 10–63cm. Left: stage 5 FC-51 (35 column V/G/S), then stage 2 motors (ENA13 IN1 14 IN2 27 IN3 26 IN4 25 ENB33, wheels up). Watch: after any power glitch the ESP can hang until EN is pressed (hang may be in setup, before the loop WDT is enabled).
- **2026-10-10 ~6am:** the brownouts/zeros were the UBEC +5V wire plugged onto a **3.3V pin** (5.4V into the 3V3 rail) — moved back to top-edge VCC; ESP survived, all sensors answer. Car now DHCP **.117** (`b4:bf:e9:02:27:38`). Camera on the car is **CAM 02** = `.118`, MAC `c8:85:41:e3:ef:0c` (CameraWebServer: `/status`, `/capture` work; grayscale 240x240), powered from a Y-split off the UBEC +5V, mounted on the page-3 bracket (spacer block on the ESP32 can, jumpers through the plate hole). NAS answers on .103/.116 (ports 5000/5001) — not cameras.
- **OLED = sci-fi HUD (2026-10-10, flashed, user: "perfect").** Face/eyes removed. Yellow strip: NET 5-seg RSSI bar (blinks empty if MQTT down) | 5-seg battery bar + % (blinks at LOW); MANUAL/AUTO | CAM dot (blinks = CAM_IP :80 answers, probed every 5s, hollow = down). Blue: corner brackets, D-pad (lit arrows = throttle/steer, filled centre = stopped), big SPD (wheel ticks/s), DST cm + 0-200cm bar with the STOP_CM line, tilt horizon (roll/pitch from accel, zeroed at boot -> boot on flat ground). `CAM_IP` is hard-coded .118 (DHCP — reserve it). Preview: `docs/hud_preview.png/.gif`.
- **Tray mount = no screws (2026-10-10).** Umi foam can't hold screws and the 5x7 hole pattern didn't land on solid chassis. Got 9× M3x40 brass male-female standoffs (B07T5JPG25) — now spares. Instead: hollow foam riser standing INSIDE the chassis box (the old RC-board bay; usable floor INSIDE 6.0 side-side x 5.6 front-back (fit-checked), depth 1.2) -> front/back walls 5.9 x 5.2 (wire notch in both), sides 5.5 x 5.2, glued to floor + box walls; L298N inside it; tray on top with velcro; zip ties through the box's corner lid-screw tabs. Finger-jointed corners (studs into notches, thirds of the height). + 4 right-angle gussets 3 x 4 (2 rectangles cut on the diagonal) on the LEFT/RIGHT riser walls, under the tray. One-page PDFs: `python3 docs/print_template.py 0.3 riser` -> `docs/riser_umi.pdf` (3 mm), `0.5 riser` -> `riser_pvc.pdf` (5 mm). The bottom of the box is the old battery bay — our 2S pack doesn't fit; stays on the tray.
- **Wheel ticks (2026-10-11):** FC-51 on the rear axle tube aimed at taped spokes worked once (57 ticks / ~1s, peak 40 t/s free-spinning at 60%) but the spokes are too small to aim at reliably. Next: printed 6-sector black/white encoder disc (rim inside = 3.5 cm; sizes 2.8–3.4) hot-glued on Umi to the back of the rear spokes, or thin card clamped behind the wheel (`docs/print_encoder_disc.py` -> `encoder_disc.pdf`) -> 6 ticks/turn. Rear drive motor + L298N signals wired and driving both ways with no resets; the earlier wdt resets during motor runs came with bursts of 150+ fake ticks (noise on the sensor line) and stopped after the user's re-wiring.
- **Full function check PASSED (2026-10-11):** wheels up, battery only: forward, back, steer left, right at speed 60 — no reset, ESP online throughout; wheel ticks counted (465->474), sonar 89–133 cm, IMU streaming (gyro saw up to 24 deg/s), battery steady 8.17V/92%, CAM 02 up (now DHCP .107 — CAM_IP in firmware still .118 -> HUD CAM dot hollow until a Deco address reservation or reflash). Earlier in the session: steering pulses (STEER_PWM 255) caused `poweron` resets until the power wiring was redone; the back direction failing was a loose IN1 jumper (re-seated). Still to do: solder the UBEC 5V 3-way joint, hot-glue the signal jumpers, encoder disc on the rear rim, riser + tray mount, Deco reservations (car .117 b4:bf:e9:02:27:38, cam .118 c8:85:41:e3:ef:0c, Mac .111).
- **Wheel ticks WORKING (2026-10-11):** 6-sector printed disc on the back of the rear rim + FC-51 lying along the BACK of the rear axle tube (zip ties + foam tape), eyes ~7 mm from the disc. Gotcha: inkjet "black" is IR-transparent — the black sectors had to be made IR-black (electrical tape / soft pencil) and the knob set with margin (off on black + 1/8 turn) or it chatters (thousands of fake ticks). Now: idle 0, ~30 t/s steady at speed 60 wheels-up (~5 rev/s). Estimate ~3.7 cm/tick (7 cm tyre, 6 ticks/rev) — calibrate with a 1 m floor run.
- **2026-10-11 ~7:30pm — car can't reach the broker (MQTT rc=-2), Mac-side.** Car WiFi fine (.117, rssi -23), TCP to router:80 OK, TCP to Mac .111:1883 FAIL every try; the phone app can't connect either -> the Mac is dropping ALL inbound LAN connections. NOT the macOS firewall (fails with it off too; one lucky connect with it off misled us). No pf/VPN active (Urban VPN configured, disconnected). Next: restart the Mac. Debug probe in `connectMqtt()` (router:80 + mac:1883 TCP tests, feeds the WDT) — remove once fixed. Also added: mDNS result ignores 127.x. Earlier same day: the UBEC Y-joint was intermittent (OLED came on when pressed) — re-done; car stable on USB.
- **FIXED by restarting the Mac (2026-10-11 ~7:45pm).** After reboot the car connects in ~2 s (`poweron up=2s`), i2c 0x3C 0x68, sonar 67 cm. Debug probe removed; kept the mDNS 127.x guard + "broker <ip> (mdns|fallback)" serial line. If the car (or phone app) ever can't connect again while TCP to the router works: the Mac's network stack is wedged — reboot the Mac first.
- **Phone app = full HUD (2026-10-11):** `~/anish-ai/app/car_control.html` (served `python3 -m http.server 8080 --directory ~/anish-ai/app`, open `http://192.168.68.111:8080/car_control.html`). Live camera window (MJPEG `http://<cam>:81/stream`, default .107, `?cam=IP` overrides + remembered; tap = enlarge; ESP32-CAM serves ONE stream client at a time), pill = CAR ONLINE/OFFLINE from `home/car/status`, tiles DIST (warn <25 cm) / SPEED km/h / TRAVEL m (since page load, 3.7 cm/tick estimate) / TILT (zeroed on first IMU msg) / TURN deg/s / VOLT; SIG + BAT bars. THROTTLE/STEER/MODE text rows dropped (the arrows + mode buttons show them). Firmware FLASHED: CAM_IP -> .107, telemetry gains `"cam":true|false` (verified true).
- **Autonomy v2 (2026-10-11, flashed):** AUTO (app button or `home/car/mode auto`) uses everything: sonar (slow < 70 cm, escape < 35, back-out < 15), camera (Mac `~/anish-ai/worldmodel/vision_avoid.py [cam_ip]` publishes `home/car/vision "l,c,r"` clutter 0-99 ~4/s; centre > 60 = blocked, escape turns toward the lower of l/r; stale > 800 ms -> sonar-only alternate turns), wheel ticks (driving but < 1 t/s for 900 ms = wedged -> back out; skipped if the sensor never ticked), MPU (|a| > 1.8 g = bump -> back out; tilt > 35 deg -> auto OFF). Any arrow / STOP = manual (`autoOff()` restores the manual duty). Steering now soft-starts (ramp 60->255 over ~40 ms) after instant crashes on steer (SW_CPU_RESET / OWDT_RESET, no backtrace = electrical). Vision heuristic = |third - floor patch| + edge density, `--selftest` passes; live room frame scored 60/51/36 — tune GAIN/EDGE on real floor. NOT yet tested driving.
- **Battery reading FIXED (2026-10-15):** it was frozen at 8.17 V since the first calibration because GPIO34's ADC attenuation wasn't set — the pin clipped at ~1.25 V (node is ~1.6–1.7 V), and the "reads 27% low" `vbatCal 1.373` was papering over the clipping. Now `analogSetPinAttenuation(VBAT_PIN, ADC_11db)` in setup, `vbatCal 1.0`; car ~8.14 V vs meter 8.11 V. The 27k (GND side) of the divider had also snapped — replaced, strain-relieved. Low-battery cutoff now actually works. Camera drifted to .103, car to .112 (DHCP) — Deco reservations still needed (CAM_IP in firmware is .107).
- **Battery sensing OFF (2026-10-15, flashed):** the divider middle point measures right on a meter (1.63 V unplugged), but this ESP's pins clamp anything above ~1.25 V (both GPIO34 and GPIO32 read a frozen 1256 mV / raw 1365; grounded reads 0) — damage from the 5.4V-on-3V3 incident. That fake 5.95 V kept latching the low-battery lock (motors dead). `VBAT_OK=false`: vbat reports 0 / pct -1 ("--" on OLED + app), no cutoff. Divider wire now on D32 (`VBAT_PIN 32`). **INA3221 (REES52, B0D3HYNCHF) ordered/in cart, arriving 16 Oct** -> read battery over I2C (addr 0x40, wire bus-voltage only: IN+ and IN- both to battery +), then re-enable the cutoff. Until then: check the pack with a meter, charge at ~7.0 V.
- **Open issue (2026-10-15 eve): ESP restarts (`sw`/`task_wdt`/`poweron`) whenever motors run on battery only.** Battery 7.94 V (meter) = fine. Camera unplugged: still resets (not camera load). With Mac USB plugged in: NO resets (USB holds 5 V). Fake wheel-tick bursts (100–250 t/s) during motor runs = noise on the lines too. Next tests, in order: (1) ESP on a phone charger/power bank (not the Mac) + battery driving motors — no resets => the UBEC 5 V path (UBEC / Y-joint / wires); (2) feed board VCC from the L298N 5V terminal (jumper ON) instead of the UBEC; (3) 470–1000 µF ≥10 V electrolytic across top-edge VCC/GND (stripe to GND); (4) 2 more 104s motor-terminal->case on the steering motor; 104 EN->GND on the ESP (`docs/caps.png`). INA3221 arrives 16 Oct.
- **Plan for 2026-10-16: full strip + rebuild, one module at a time.** User is removing all wires tonight. Parts: spare ESP32 (known-good, replaces the one with clamped ADC pins — flash car firmware onto it first, set `VBAT_OK`/battery per INA3221), INA3221 (arrives 16 Oct), 1000 µF 25V caps x10 (17 Oct: one across board VCC/GND, one across L298N power in), extension board (in cart). Suggested (not yet ordered): nylon M3 F-F 20 mm standoffs, Wago 221-413 (replace the twisted 5V/GND Y-joints), 5 mm PVC base (Umi foam can't hold screws), adhesive tie mounts + spiral wrap. Layout: power left / signals right, cross at 90 deg, one labelled plug per module with slack loops, switch + ESP USB + charge lead all at the back wall; L298N + UBEC + caps in the riser/chassis bay. Rebuild order: power -> ESP -> verify 5V/3V3 -> I2C (OLED, MPU, INA3221) -> sonar -> wheel sensor -> motors (wheels up) -> camera; test after each.
- **Old car ESP health check (2026-10-15, `esp_selftest/`):** WiFi fine, ADC fine — G32/G34 read 142 on GND and 2369 on 3V3 (2.37–2.45 V is the ESP32's normal ceiling at 11 dB, NOT damage). So the frozen 1256 mV battery reading was most likely a firmware/wiring issue (missing common GND or the 2.5 dB-range read), not a dead ADC — dropped because the INA3221 (I2C) replaces the divider. This ESP is usable; spare goes in tomorrow anyway.

**2026-10-17 — rebuild started, paused for parts.** Car fully stripped. Car firmware re-flashed (full flash @115200 from a scratchpad build) — boots, WiFi .112, MQTT to .111 OK. Next step when parts are in: POWER (batt + → switch → L298N +12V, batt − → GND, UBEC in on same terminals, UBEC out unconnected; then meter). Parts: standoffs/spiral/velcro delivered; PVC/caps/tie mounts due 17 Oct; Wagos Mon 19 Oct; INA3221 + Anchor ext board ordered 17 Oct (due 18 Oct).

**2026-10-18 — INA3221 (CJMCU-3221) works: I2C scan 0x40.** Needed: header soldered (long pins up), A0→GND solder bridge (front pads; unbridged = no ACK). VPU left UNCONNECTED — works without it (OLED/MPU boards supply bus pull-ups). Pins used: VS→3V3, GND, SCL→22, SDA→21. Battery sense later: POW pad → batt + (after switch), side GND → batt −; CH1 bus voltage = battery. Firmware does NOT read it yet — add when power stage is wired (replaces the dead divider, VBAT_OK).

**2026-10-18 — layout v2 redrawn TO SCALE** (`docs/layout_v2.png`, `docs/draw_layout_v2.py`; template `python3 docs/print_template.py 0.5 v2` -> `docs/base_v2_pvc.pdf`, 4 LANDSCAPE pages, all content x<=19 cm because the printer clips the right edge). Measured: battery 7x3.7x1.8, ESP exp board 6.8x5, UBEC 4.5x1.7 (stands ON EDGE behind the battery), OLED 2.5x2.7 (now in the FRONT WALL, 2.3x1.2 window, car's left), MPU 2x1.6 (front-left, NOT on the battery), INA (right, above the Wagos). Battery is removable (velcro+strap only); its switch rides on the battery lead -> no switch hole; car side is just a plug -> 8V Wago A / GND Wago. 3 Wagos (8V A, 8V B, GND); UBEC out straight to ESP board 5V. Camera bracket moved to the car's RIGHT (CAM_X=3.5 outside view); 6 spacers. Holes S/P are 0.9x2 slots inside the riser. Main power path in thick (20-22 AWG) wire, not jumpers.

**2026-10-18 — riser v2 = open SIDES** (`python3 docs/print_template.py 0.5 riser2` -> `docs/riser_v2_pvc.pdf`): 4 closed L corner posts (front/back strip 1.95x5.2 with a 1.0 top tab + side strip 1.25x5.2 butt-glued inside it), 2 cm opening mid-side on all 4 sides (motor wires + air, no notches). Tabs drop into 4 slots in the tray base (not glued -> tray lifts off). Bottoms hot-glued to the bay floor; 4 gussets on the side strips. Holes S/P moved just inside the side posts (0.54x2.0 at x 6.08 / 10.38) — the old ones overlapped the riser walls. Camera bracket centre now base x 13.2 (CAM_X 3.2). 3D model: https://claude.ai/artifact/D6buYdMUseud1Bk1WnPqHa (`docs/car_3d.html`).

**2026-10-21 — tray built, power stage wired + metered (READ THIS FIRST for current state).**

Mechanical:
- Tray (base + 4 walls) built from `docs/base_v2_pvc.pdf` (6 pages, one part per page at the BOTTOM of the sheet — printer clips the top/right). Sonar hot-glued in the front-wall holes. S/P wire holes, 2 strap slots, 4 riser tab slots cut.
- Riser: the 4 L corner posts are GLUED UNDER THE TRAY (in its tab slots), gussets glued -> tray+riser is one removable unit sitting in the chassis bay around the L298N. Test-fitted OK. Hold-down plan: zip ties (post -> chassis-box corner lug, or 2 small holes in the tray over a chassis bar) +/- velcro under the posts. NO glue to the chassis (L298N must stay reachable).
- Not yet cut: OLED window (front wall), wheel-sensor hole (back wall, ~6 mm).

Electrical (done, battery-tested):
- Motors: drive -> L298N OUT1/OUT2, steering -> OUT3/OUT4 (polarity unverified; swap pair if direction wrong at wheels-up test). 0.1 uF ceramic soldered across EACH motor's leads just outside its gearbox (tabs are inside the boxes; boxes NOT opened), taped.
- L298N 3-pin terminal: 12V <- 8V B Wago + 1000 uF cap long leg; GND <- GND Wago + cap short/stripe leg (legs taped; no solder, screw clamp); 5V EMPTY, its regulator jumper left on.
- Wagos 221-413 (one colour per Wago; user once put red+black in one Wago — caught before power):
  - 8V A: battery-connector red | jumper -> 8V B | UBEC in +
  - 8V B: jumper from A | L298N 12V | SPARE (INA POW later)
  - GND : battery-connector black | L298N GND | UBEC in -
- Battery: switch rides on the battery lead; car side = mating connector pigtail into the Wagos.
- Removed from the old build: all soldered Y-joints (incl. UBEC 5V Y for the camera), the VBAT resistor divider (pin 32 now unused — INA replaces it).
- Metered: continuity 8V<->GND no beep (576 reading = load, not a short); 8V A and 8V B = 8.29 V; UBEC out unloaded = 5.47 V (first read 5.84; acceptable, re-check under load, >5.5 loaded = investigate).

In progress / next (in order):
1. L298N signal jumpers (user doing them NOW, before the tray goes on): pull ENA/ENB caps; ENA 13, IN1 14, IN2 27, IN3 26, IN4 25, ENB 33, + GND -> ESP board GND; bundle up hole S, label ends; hot-glue/tape the housings (NOT superglue).
2. Thread 8V/GND up hole P, tray on, zip-tie down, mount parts in their dashed boxes (Wagos right, plug back-right, UBEC on edge at the back, battery velcro+strap centre, ESP board left on nylon standoffs, USB to back slot). Power = right side, signals = left, nothing over the battery.
3. ESP power: UBEC out red -> board 5V, black -> GND; 1000 uF across another 5V/GND pair (stripe to GND). USB UNPLUGGED while on battery. Expect 5V ~5 V, 3V3 ~3.3 V, then WiFi .112 / MQTT online.
4. I2C (OLED, MPU, INA all on 3V3/GND/21/22), add INA3221 battery read to firmware (replaces VBAT_PIN/VBAT_OK), INA POW -> 8V B spare hole.
5. Sonar (5V, Trig 18, Echo via 1k/1.8k -> 19), wheel sensor (3V3, OUT 35), motors wheels-up ONLY when the user says "test", camera last (5V/GND from the ESP board; fix CAM_IP .107 -> .103).

User style: short plain-English steps, one thing at a time; sends WhatsApp photos — check every photo for red/black in the same Wago and cap polarity before any power-on. Never run motor tests without the user saying "go"/"test".

**2026-11-12 — ESP powered from the UBEC: OK.** ESP board mounted in the tray, L298N signal jumpers (ribbon) plugged, UBEC out -> board 5V/GND header pins, 1000 uF on the board 5V/GND (not on the Wagos — all 9 Wago holes in use). USB unplugged. 3V3 = 3.30 V. MQTT: status online, boot wdt, i2c=none (nothing on I2C yet), vbat 0 (divider removed), distance -1 (no sonar yet), rssi -75. Ping to .112 timed out but MQTT works. Next: I2C (OLED/MPU/INA) + INA battery read in firmware.

**2026-11-12 — motors tested wheels-up: steer L/R OK, drive fwd + back OK. CORRECTION: the ESP DID reset after motor runs (missed by reading only the retained boot msg — always watch boot/status with timestamps over 30–45 s).** Back first failed: IN2 (GPIO27) jumper was loose/misplaced, reseated. Pulse 450 ms. Next: I2C (OLED first), then INA battery read in firmware.


**2026-11-13 — motor resets ROOT-CAUSED: noise enters via the FC-51 wheel-sensor wires.**
- Wiring found mixed: front-drive and steering pairs were swapped (forward drove rear + steering). Fixed: front+rear drive on OUT1/OUT2 (reds OUT2, blacks OUT1 — swapped once because both ran backwards), steering on OUT3/OUT4. Drive fwd/back now OK with no resets.
- Steering still froze/reset the ESP (poweron/sw/wdt/panic). Serial log over USB (UBEC off the ESP, GND jumper ESP->L298N; script pattern in session scratchpad serlog3.py: open port dtr/rts False, wait for "MQTT up" before sending) showed: instant CPU freeze on "left", RTC WDT reboot ~9 s later, once "esp_image checksum failed" at boot = flash reads corrupted -> noise on the chip's 3V3/GND.
- Ruled out: power (froze on Mac USB too), steer stall (150 ms pulse froze too), OLED code (firmware fix: oled.begin() returned true with no OLED -> now ACK-probed first; flashed), wheel ISR code, steering motor (4.3–4.7 ohm), shorts. Steering motor now has 3 caps (across + each tab->can; one tab beeps to the can — harmless, can is isolated).
- Steering motor unplugged -> no freeze. CORRECTION: the FC-51 was NOT plugged in during these tests. What stopped the freeze was removing **the big 1000 uF cap and the small 104 EN->GND cap from the ESP board** (battery on, motor turning, 4 steer cmds, no freeze). Next: put them back one at a time (checking pins + polarity: stripe to GND) to find the bad one.
- A TEST build with the wheel ISR off is on the ESP — rebuild + flash ~/anish-ai/iot/esp32_car (source unchanged) to restore.
