import json
#!/usr/bin/env python3
"""Nova light control panel — a local web UI for the MELK/ELK-BLEDOM BLE strip.

  python3 light_panel.py            # serves http://localhost:8099  (launch from Terminal.app for the mic)
  open http://localhost:8099

Reuses lights.py (same BLE device + command builders) but holds ONE persistent
BLE connection in a background asyncio thread for snappy colour-wheel response.
Features: on/off, colour wheel, brightness, effects + speed, a music-reactive
'Listen' mode (follows Nova's song), and an auto-off timer. Close the phone app first (one BLE link).
"""
import asyncio, threading, queue, time, sys, os, colorsys
import http.server, socketserver, urllib.parse
sys.path.insert(0, os.path.expanduser("~/anish-ai"))
import lights  # ADDR, CHAR, ON, OFF, _rgb, _bri, _effect, _speed, EFFECTS

PORT = 8099
STATE = {"connected": False, "on": False, "listen": False, "timer_at": None}
_listen_thread = None
_timer_thread = None

QS = []      # one queue per strip (bed + table): every command goes to all of them, so they stay in sync
NAMES = {}   # queue -> strip name
VOICE_STRIP = "61"   # name suffix of the TABLE strip (MELK-OA10   61): only it reacts to Nova's voice
NOVA_RGB = (255, 154, 66)   # Nova's amber (#ff9a42, the wall HUD colour): the table breathes in it while Nova speaks
_voice_on = threading.Event()

STRIPS = {"bed": "17", "table": "61"}   # wall HUD rows -> strip name suffix

def _describe():
    """What the panel last set (the strips can't report back): 'WARM 85%', 'PARTY 100%', 'OFF', '--' = unknown."""
    p = LAST.get(4)
    if p is None: return "--"
    if p == lights.OFF: return "OFF"
    m, txt = LAST.get("mode"), "ON"
    if m is not None and m[2] == 5:
        rgb = tuple(m[4:7]); txt = next((k for k, v in lights.COLORS.items() if tuple(v) == rgb), "#%02x%02x%02x" % rgb)
    elif m is not None:
        txt = next((k for k, v in lights.EFFECTS.items() if v == m[3]), "effect %d" % m[3])
    if LAST.get(1): txt += " %d%%" % LAST[1][3]
    return txt.upper()

def _strips_state():
    found = set(NAMES.values()); now = _describe()
    out = {}
    for row, suf in STRIPS.items():
        if not any(n.endswith(suf) for n in found): out[row] = "NOT FOUND"
        elif row == "table" and _voice_on.is_set(): out[row] = "NOVA VOICE"
        else: out[row] = now
    return out

def _voice_breathe(q):
    """Breathe the table strip in Nova's amber until _voice_on clears, then restore its normal state."""
    import math
    t = 0
    while _voice_on.is_set():
        if q.qsize() < 2:                                  # don't outrun the 0.15 s write gap
            lv = 0.15 + 0.85 * (0.5 - 0.5 * math.cos(t))   # 15% -> 100% -> 15%, ~1.5 s per breath
            q.put(lights._rgb(*[int(c * lv) for c in NOVA_RGB])); t += 0.6
        time.sleep(0.12)
    for f in _replay(): q.put(f)
_LIVE = set()

LAST = {}    # current power/mode/brightness/speed packets -> replayed to a strip when it (re)connects

_LAST_F = os.path.expanduser("~/anish-ai/.panel_last.json")   # survives restarts, so the wall knows the strips' state
try: LAST.update({(k if k == "mode" else int(k)): bytes.fromhex(v) for k, v in json.load(open(_LAST_F)).items()})
except Exception: pass

def _replay():
    """Saved state to resend to a strip (TableQ ignores effect frames; _effect_loop animates the table)."""
    return list(LAST.values())

def send(data):
    if len(data) > 3:   # ELK packet byte 2 = type: 4 power, 5 colour, 3 effect (colour/effect = one "mode"), 1 brightness, 2 speed
        k = "mode" if data[2] in (3, 5) else data[2]
        LAST.pop(k, None); LAST[k] = data
        try: json.dump({str(k): v.hex() for k, v in LAST.items()}, open(_LAST_F, "w"))
        except Exception: pass
    for q in QS:
        q.put(data)

# ---------- table strip: driven by the room ESP32 (DO -> D32) since 2026-11-18, not by its laggy BLE controller ----------
class TableQ:
    """Stands in for a strip queue: decodes the ELK frames everything already sends and publishes the
    resulting colour to home/room/strip/set (instant, so listen mode stays in step with the bed)."""
    def __init__(self):
        import paho.mqtt.client as mqtt
        try: self.c = mqtt.Client(mqtt.CallbackAPIVersion.VERSION2)
        except AttributeError: self.c = mqtt.Client()
        self.c.username_pw_set("nova", open(os.path.join(os.path.dirname(os.path.abspath(__file__)), ".mqtt_key")).read().strip())
        self.c.connect_async("localhost"); self.c.loop_start()
        self.on, self.rgb, self.bri = True, (255, 150, 60), 100
        for f in _replay(): self.put(f)
    def put(self, d):
        if not d or len(d) < 4 or d[1] == 6: return                 # wake marker / clock handshake
        if   d[2] == 4: self.on = d[3] == 0xff
        elif d[2] == 5: self.rgb = tuple(d[4:7])
        elif d[2] == 1: self.bri = d[3]
        else: return                                                 # effect/speed: _effect_loop sends colours instead
        r, g, b = [int(x * self.bri / 100) for x in self.rgb] if self.on else (0, 0, 0)
        self.c.publish("home/room/strip/set", "%d %d %d" % (r, g, b))
        _effect_loop.sent = None          # a solid colour stops the ESP32's effect -> let _effect_loop resend it
    def qsize(self): return 0
    def empty(self): return True

# ---------- effects: the bed runs its controller's built-in effect; the panel imitates it on the ESP32 table ----------
SEVEN = [(255, 0, 0), (0, 255, 0), (0, 0, 255), (255, 255, 0), (0, 255, 255), (255, 0, 255), (255, 255, 255)]
JUMP = {3: SEVEN, 0: SEVEN, 1: SEVEN, 193: SEVEN}   # effect id -> colours to step through (not yet filmed on the bed)
# Filmed on the bed (Mac camera, 2026-11-18) and copied in the ESP32 firmware ("scroll"): effect id -> colour order.
# party (5): long colour bands scroll along the strip; any one spot sees blue -> green -> red, ~2.3 s each at speed 27.
WIPE = {5: [(0, 0, 255), (0, 255, 0), (255, 0, 0)]}
BAND = 28   # calibration knob: LEDs per colour band incl. gap (16 lit + GAP dark, matched by eye to the bed 2026-11-18)
FAST_MS = 400   # calibration knob: table party ms per band at full speed (1000 "matched the bed" but was too slow, 2026-11-18)
GAP = 12    # calibration knob: dark LEDs between bands (3 and 8 looked too small vs the bed)

def _effect_loop():
    """Runs forever; animates whenever LAST says an effect is on (so restarts, listen exit etc. resume it)."""
    t, hue, nxt = 0, 0.0, 0.0
    while True:
        m, sp = LAST.get("mode"), LAST.get(2)
        if not (m is not None and m[2] == 3 and LAST.get(4) == lights.ON and not STATE["listen"]):
            _effect_loop.sent = None; time.sleep(0.1); continue
        e, step = m[3], 0.2 + 1.3 * (1 - (sp[3] if sp else 50) / 100)   # calibration knob: 1.5 s (slow) .. 0.2 s (fast)
        if e in WIPE:                                                  # the ESP32 animates it; send the command once
            b = LAST[1][3] if LAST.get(1) else 100
            v = sp[3] if sp else 27                                    # calibration knob: 2300 ms per band at speed 27 (filmed),
            ms = int(2300 - (v - 27) * (2300 - FAST_MS) / 73)            # FAST_MS at speed 100
            # bands move away from LED 0, so a spot sees them in reverse list order -> reverse to get blue, green, red
            cmd = "scroll %d %d %d " % (ms, BAND, GAP) + " ".join("%02x%02x%02x" % tuple(int(c * b / 100) for c in rgb) for rgb in WIPE[e][::-1])
            if cmd != _effect_loop.sent or _voice_on.is_set():
                for sq in QS:
                    if isinstance(sq, TableQ) and not _voice_on.is_set(): sq.c.publish("home/room/strip/set", cmd)
                _effect_loop.sent = None if _voice_on.is_set() else cmd
            time.sleep(0.2); continue
        if time.time() < nxt: time.sleep(0.03); continue
        if e in JUMP:  rgb, wait = JUMP[e][t % len(JUMP[e])], step
        elif e == 196: rgb, wait = (SEVEN[t // 2 % 7] if t % 2 == 0 else (0, 0, 0)), max(0.2, step / 3)   # strobe
        else:                                                          # fade/breathe/flow...: smooth rainbow
            hue = (hue + 0.15 / (step * 7)) % 1; rgb, wait = tuple(int(x * 255) for x in colorsys.hsv_to_rgb(hue, 1, 1)), 0.15
        if not _voice_on.is_set():
            for sq in QS:
                if isinstance(sq, TableQ): sq.put(Fast(lights._rgb(*rgb)))
        _effect_loop.sent = None
        t += 1; nxt = time.time() + wait

_effect_loop.sent = None   # last "wipe" command sent to the table

# ---------- BLE: one always-on link per MELK strip, renewed every LINK_MAX_S ----------
# A link held open for minutes went stale on the table controller (reported connected, writes ignored), and
# per-burst links made the table lag (it reconnects slowly). Renewing a live link every 15 s avoids both.
# ponytail: the strips are always held, so the phone app can't connect while the panel runs; close the panel to use it.
async def _strip(dev, q):
    """Always connected: commands go out at once (the table reconnects slowly, so per-burst links made it lag).
    The link is renewed every LINK_MAX_S (the table's link goes stale = writes ignored). Saved state (LAST) is
    replayed only on the first link and after an error, so a renewal never undoes the remote/IR music mode."""
    from bleak import BleakClient
    fresh = True
    while True:
        try:
            async with BleakClient(dev, timeout=20) as c:
                _LIVE.add(dev.address)
                # in listen mode a reconnect must not flash the saved colour (LAST) between listen frames
                for d in [lights._clock()] + (([lights.ON] if STATE["listen"] else _replay()) if fresh else []):
                    await c.write_gatt_char(lights.CHAR, d, response=True); await asyncio.sleep(0.15)
                fresh, born = False, time.time()
                while time.time() - born < LINK_MAX_S:
                    try:
                        d = q.get_nowait()
                        if d:                                            # b"" = old wake-up marker, ignore
                            fast = isinstance(d, Fast)                   # listen frame -> shorter gap
                            # always confirmed: the table controller IGNORES unconfirmed writes (bed accepts them), 2026-11-17
                            t0 = time.time(); await c.write_gatt_char(lights.CHAR, d, response=True)
                            if time.time() - t0 > 0.5: print("BLE %s: slow write %.1fs, %d queued" % (dev.name, time.time() - t0, q.qsize()), flush=True)
                            await asyncio.sleep(FAST_GAP if fast else 0.15)   # the table controller needs the gap
                    except queue.Empty:
                        await asyncio.sleep(0.03)
        except Exception as e:
            print("BLE %s: %s (retry in 2s)" % (dev.name, str(e)[:70]), flush=True)
            fresh = True
            await asyncio.sleep(2)
        _LIVE.discard(dev.address)

async def _ble_loop():
    """Keep scanning: a strip held by the phone app (or unplugged) joins as soon as it advertises again."""
    from bleak import BleakScanner
    known, tasks = set(), []
    while True:
        for d in await BleakScanner.discover(timeout=8):
            if (d.name or "").upper().startswith(("MELK", "ELK")) and d.address not in known \
                    and not (d.name or "").endswith(STRIPS["table"]):   # table = ESP32 now (TableQ)
                known.add(d.address); q = queue.Queue()
                QS.append(q); NAMES[q] = d.name or ""; tasks.append(asyncio.ensure_future(_strip(d, q)))
                print("BLE strip found:", d.name, flush=True)
                STATE["connected"] = True   # links are per-burst now; this means "strips known"
        await asyncio.sleep(30)

def _start_ble():
    asyncio.run(_ble_loop())

# ---------- music-reactive listen mode ----------
class Fast(bytes): """a listen-mode frame: sent with the shorter FAST_GAP"""
LINK_MAX_S = 15     # calibration knob: renew each strip's link this often (stale-link fix); ~1-2 s gap each time
FAST_GAP = 0.06      # calibration knob: gap after a listen frame; raise it if the table skips/flickers
LISTEN_FLOOR = 0.22  # calibration knob: dimmest listen colour (0-1); lower = more contrast, but the table goes dark
LISTEN_LEAD = 0.15   # calibration knob: seconds to read ahead of playback, covers BLE/strip lag; raise if lights trail the beat
HOP = 0.05           # one loudness value per 50 ms of song
LISTEN_DECAY = 0.75  # calibration knob: how fast a flash fades per frame (lower = snappier, higher = smoother)
LISTEN_BEAT = 0.22   # calibration knob: loudness jump that counts as a beat (lower = more colour changes)

def _envelope(path):
    """Loudness of the whole song, 0-1 per HOP, scaled to the song's own loud parts (quiet songs still pulse)."""
    import wave, numpy as np
    with wave.open(path) as w:
        if w.getsampwidth() != 2: return None
        ch, hop = w.getnchannels(), int(w.getframerate() * HOP)
        out = []
        while True:
            raw = w.readframes(hop * 400)                  # 20 s at a time: the old hub has little RAM
            if not raw: break
            x = np.frombuffer(raw, np.int16).reshape(-1, ch).astype(np.float32).mean(1)
            m = len(x) // hop
            if m: out.append(np.sqrt((x[:m * hop].reshape(m, hop) ** 2).mean(1)))
    if not out: return None
    rms = np.concatenate(out)
    lo, hi = np.percentile(rms, 20), np.percentile(rms, 98)   # stretch the song's own range: quiet bits ~0, hits ~1
    return np.clip((rms - lo) / ((hi - lo) or 1.0), 0.0, 1.0) ** 1.5

class _Song:
    """Where Nova's song is right now (pauses = SIGSTOP, so paused time is subtracted) and how loud it is there."""
    def __init__(self): self.key, self.env, self.t0, self.paused, self.chk, self.stopped = None, None, 0.0, 0.0, 0.0, False
    def level(self):
        now = time.time()
        if now - self.chk > 0.5:                                         # every 0.5 s: which song, paused? (too slow per frame)
            import subprocess
            r = subprocess.run(["pgrep", "-fl", "nova_track[.]wav$"], capture_output=True, text=True).stdout.split()
            if not r: self.key = None; return 0.0                        # nothing playing
            pid, path = int(r[0]), r[-1]                                 # "<pid> afplay -v 0.4 /tmp/nova_track.wav" (not yt-dlp's download, whose args end in a URL)
            if (pid, path) != self.key:                                  # new song: nova.py writes the WAV right before afplay
                self.key, self.paused, self.stopped = (pid, path), 0.0, False
                try: self.t0, self.env = os.path.getmtime(path), _envelope(path)
                except Exception as e: print("listen: can't read song:", e); self.env = None
            st = subprocess.run(["ps", "-o", "stat=", "-p", str(pid)], capture_output=True, text=True).stdout.strip()
            if self.stopped: self.paused += now - self.chk
            self.stopped, self.chk = st.startswith("T"), now
        if self.key is None or self.stopped or self.env is None: return 0.0
        # ponytail: pauses are seen at 0.5 s granularity, so each resume can leave the lights up to 0.5 s early
        i = int((now - self.t0 - self.paused + LISTEN_LEAD) / HOP)
        return float(self.env[i]) if 0 <= i < len(self.env) else 0.0

def _listen_loop():
    """Strips follow the song Nova is playing (read from the file, not the mic). No song = slow dim colour drift."""
    try:
        import numpy  # noqa: F401
    except Exception as e:
        print("listen needs numpy:", e); STATE["listen"] = False; return
    song = _Song()
    hue, ema, prev, last = 0.0, 0.0, 0.0, 0.0
    while STATE["listen"]:
        level = song.level()
        ema = level if level > ema else ema * LISTEN_DECAY  # instant attack, quick fade: hits flash, gaps go dim
        if level - prev > LISTEN_BEAT: hue = (hue + 0.17) % 1.0   # a beat (sudden jump) -> new colour
        prev = level
        hue = (hue + 0.004 + ema * 0.02) % 1.0             # plus a slow drift between beats
        # floor 30%: the table controller shows very dim colours as OFF (at 8% it looked dead, 2026-11-17)
        r, g, b = [int(x * 255) for x in colorsys.hsv_to_rgb(hue, 1.0, LISTEN_FLOOR + (1 - LISTEN_FLOOR) * ema)]
        # straight to the queues, NOT send() (listen colours must not replace LAST). Lockstep: a new colour goes to
        # both strips together once both are ready, so they match; after 1 s a stuck/disconnected strip is skipped.
        ready = [sq for sq in QS if sq.empty()]
        if ready and (len(ready) == len(QS) or time.time() - last > 1.0):
            for sq in ready: sq.put(Fast(lights._rgb(r, g, b)))
            last = time.time()
        time.sleep(0.03)
    for sq in QS:                                          # back to how the lights were (incl. off)
        for f in _replay(): sq.put(f)
    print("listen stopped")

def _start_listen():
    global _listen_thread
    if STATE["listen"]:
        return
    STATE["listen"] = True
    for sq in QS: sq.put(lights.ON)                        # lights off -> on for the music (restored after)
    _listen_thread = threading.Thread(target=_listen_loop, daemon=True)
    _listen_thread.start()

def _stop_listen():
    STATE["listen"] = False

# ---------- auto-off timer ----------
def _set_timer(minutes):
    global _timer_thread
    STATE["timer_at"] = time.time() + minutes * 60

    def run(deadline):
        while STATE["timer_at"] == deadline and time.time() < deadline:
            time.sleep(1)
        if STATE["timer_at"] == deadline:                  # not cancelled/replaced
            _stop_listen(); send(lights.OFF); STATE["on"] = False; STATE["timer_at"] = None
            print("timer -> lights off")
    _timer_thread = threading.Thread(target=run, args=(STATE["timer_at"],), daemon=True)
    _timer_thread.start()

def _cancel_timer():
    STATE["timer_at"] = None

# ---------- HTTP ----------
class H(http.server.BaseHTTPRequestHandler):
    def log_message(self, *a): pass

    def _send(self, body, ctype="application/json"):
        b = body.encode() if isinstance(body, str) else body
        self.send_response(200); self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(b))); self.end_headers(); self.wfile.write(b)

    def do_GET(self):
        u = urllib.parse.urlparse(self.path)
        q = urllib.parse.parse_qs(u.query)
        g = lambda k, d=0: int(q.get(k, [d])[0])
        path = u.path

        if path in ("/", "/index.html", "/hub"):               # one landscape page for everything (2026-11-18)
            return self._send(open(HUB_HTML).read(), "text/html; charset=utf-8")
        if path == "/pick":                                   # Mac song-picker popup (opened by nova.pick_song)
            return self._send(open(PICK_HTML).read(), "text/html; charset=utf-8")
        if path == "/api/pause":                              # play/pause toggle: freezes/wakes the player on this hub
            import nova
            return self._send(json.dumps({"say": nova.pause_music()}))
        if path == "/api/state":
            return self._send(json.dumps(_hub_state()))
        if path == "/api/act":                                 # ?f=ac&a=temp 25 - only whitelisted function + argument shapes
            f, a = q.get("f", [""])[0], q.get("a", [""])[0]
            return self._send(json.dumps({"say": _hub_act(f, a)}))
        if path == "/api/hub":                                 # music / routines run inside the Nova app (it owns the queue)
            k, v = q.get("k", [""])[0], q.get("v", [""])[0]
            if k not in ("music", "routine"): return self._send(json.dumps({"say": "no"}))
            if k == "music":                                   # the Nova app runs getattr(nova, fn)(**kw): only these get through
                try:
                    j = json.loads(v); kw = j.get("kw") or {}
                    ok = j["fn"] in MUSIC_OK and set(kw) <= MUSIC_OK[j["fn"]]
                    v = json.dumps({"fn": j["fn"], "kw": {"start": int(kw["start"])} if "start" in kw else
                                    {"shuffle": True} if kw.get("shuffle") else {}})
                except Exception: ok = False
                if not ok: return self._send(json.dumps({"say": "no"}))
            TQ[0].c.publish("home/hub/" + k, v, qos=1)
            return self._send(json.dumps({"say": "ok"}))
        if path == "/api/playlist":
            return self._send(json.dumps(_playlist()))
        if path == "/vol":                                     # volume slider: ?v=0-100 sets; always returns the current level
            if "v" in q: _osa("set volume output volume %d" % max(0, min(100, g("v", 50))))
            return self._send(json.dumps({"v": int(_osa("output volume of (get volume settings)") or 0)}))
        if path == "/on":
            send(lights.ON); STATE["on"] = True
        elif path == "/off":
            _stop_listen(); send(lights.OFF); STATE["on"] = False
        elif path == "/color":
            _stop_listen(); send(lights.ON); send(lights._rgb(g("r"), g("g"), g("b"))); STATE["on"] = True
        elif path == "/brightness":
            send(lights.ON); send(lights._bri(g("v"))); STATE["on"] = True
        elif path == "/effect":
            name = q.get("name", ["party"])[0]
            eid = lights.EFFECTS.get(name, 0x88)
            _stop_listen(); send(lights.ON); send(lights._effect(eid)); send(lights._speed(g("v", 100))); STATE["on"] = True   # no speed = the strip's last (often a slow crawl)
        elif path == "/speed":
            send(lights._speed(g("v", 50)))
        elif path == "/voice":                                 # Nova speaking: table strip breathes in Nova's amber, then back
            tq = [q for q in QS if NAMES.get(q, "").endswith(VOICE_STRIP)]
            if g("on") and LAST.get(4) == lights.ON and tq and not _voice_on.is_set():   # lights off -> stay dark
                _voice_on.set(); threading.Thread(target=_voice_breathe, args=(tq[0],), daemon=True).start()
            elif not g("on"):
                _voice_on.clear()
        elif path == "/strip":                                 # one strip only, e.g. table at night: /strip?name=table&on=1
            suf = STRIPS.get(q.get("name", [""])[0])           # NOT saved to LAST: the next all-strips command
            for sq in [x for x in QS if suf and NAMES.get(x, "").endswith(suf)]:   # syncs both again
                sq.put(lights.ON if g("on") else lights.OFF)
        elif path == "/raw":                                   # voice/lights.py routes raw bytes through here
            try: send(bytes.fromhex(q.get("hex", [""])[0]))
            except Exception: pass
        elif path == "/listen":
            (_start_listen if g("on") else _stop_listen)()
        elif path == "/timer":
            m = g("min"); (_set_timer(m) if m > 0 else _cancel_timer())
        elif path == "/state":
            left = max(0, int(STATE["timer_at"] - time.time())) if STATE["timer_at"] else 0
            return self._send(json.dumps({"connected": STATE["connected"], "on": STATE["on"], "listen": STATE["listen"],
                                          "timer": left, "strips": _strips_state()}))
        else:
            self.send_response(404); self.end_headers(); return
        return self._send('{"ok":true}')




_deck_lock = threading.Lock()


# ---------- the hub page (hub_page.html): live room state, whitelisted actions, playlist ----------
HUB_HTML = os.path.join(os.path.dirname(os.path.abspath(__file__)), "hub_page.html")
PICK_HTML = os.path.join(os.path.dirname(os.path.abspath(__file__)), "pick_page.html")
TQ = []        # the table's MQTT client, reused: subscribes to home/room/# and publishes hub jobs
MUSIC_OK = {"play_playlist": {"start", "shuffle"}, "next_song": set(), "stop_music": set(), "pick_song": set()}   # fn -> allowed kw
ROOM = {}      # latest home/room/<key> values (retained ones arrive on connect)
ACT_OK = {     # function -> allowed argument shape (the page can only send these)
    "ac": r"on|off|increase|decrease|temp (1[6-9]|2\d|30)|fan (low|medium|high|auto)|mode (cool|dry|fan|auto)",
    "bulb": r"on|off|warm|white|cool|daylight|brightness \d{1,3}|[a-z ]{3,20}",
    "lights": r"on|off|[a-z]{3,12}|brightness \d{1,3}|speed \d{1,3}",
    "projector": r"on|off|toggle|colour|laser|laser on|laser off|brighter|dimmer|faster|slower|timer|reset|is on|is off|"
                 r"green|nebula|red|blue|green two|pink|aqua|rainbow",
    "fan": r"on|off",
    "nova_mute": r"on|off",
}


def _hub_act(f, a):
    import re
    if f not in ACT_OK or not re.fullmatch(ACT_OK[f], a or ""): return "Not allowed."
    if f == "nova_mute":                               # fast: never waits behind a slow AC/BLE button
        import nova; return str(nova.nova_mute(a))
    with _deck_lock:
        try:
            import nova
            if f == "fan": return str(nova.FUNCS["iot_control"]("fan", a))
            return str(nova.FUNCS[f](a))
        except Exception as e:
            print("[hub page]", f, a, e, flush=True); return "Failed: %s" % str(e)[:60]


def _hub_state():
    import subprocess
    try: title = open("/tmp/nova_now.txt").read().strip()
    except OSError: title = ""
    playing = subprocess.run(["pgrep", "-f", "nova_track[.]"], capture_output=True).returncode == 0
    import nova
    return {"room": ROOM, "muted": nova.voice_muted(), "playing": playing, "paused": playing and nova.music_paused(), "title": title if playing else "",
            "projector": os.path.exists(os.path.expanduser("~/anish-ai/.projector_on")),
            "strips": _strips_state(), "on": STATE.get("on"),
            "routines": [k for k, v in json.load(open(os.path.expanduser("~/anish-ai/routines.json"))).items()
                         if not k.startswith("_") and not v.get("at")]}


_pl = {"t": 0, "items": []}
def _playlist():
    """The owner's playlist titles (index = position), cached 12 h: listing 400+ songs takes ~10-20 s."""
    if time.time() - _pl["t"] > 12 * 3600 or not _pl["items"]:
        import nova
        _pl["items"] = [t for _, t in nova._flat(nova.MY_PLAYLIST, "1-2000")]; _pl["t"] = time.time()
    return _pl["items"]


def _osa(cmd):
    import subprocess
    return subprocess.run(["osascript", "-e", cmd], capture_output=True, text=True).stdout.strip()




def main():
    tq = TableQ(); QS.append(tq); NAMES[tq] = "ESP32 table " + STRIPS["table"]; TQ.append(tq)
    def _room_msg(c, u, m):
        k = m.topic.split("/", 2)[2]
        if "/" not in k: ROOM[k] = m.payload.decode(errors="replace")[:120]
    tq.c.on_message = _room_msg
    tq.c.on_connect = lambda c, *a: c.subscribe("home/room/#")
    tq.c.subscribe("home/room/#")      # in case it connected before on_connect was set
    threading.Thread(target=_effect_loop, daemon=True).start()
    threading.Thread(target=_start_ble, daemon=True).start()
    socketserver.ThreadingTCPServer.allow_reuse_address = True
    srv = socketserver.ThreadingTCPServer(("0.0.0.0", PORT), H)
    print("Nova Lights panel -> http://localhost:%d  (close the phone app first)" % PORT)
    try:
        srv.serve_forever()
    except KeyboardInterrupt:
        pass


if __name__ == "__main__":
    main()
