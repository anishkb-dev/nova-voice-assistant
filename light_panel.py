import json
#!/usr/bin/env python3
"""Nova light control panel — a local web UI for the MELK/ELK-BLEDOM BLE strip.

  python3 light_panel.py            # serves http://localhost:8099  (launch from Terminal.app for the mic)
  open http://localhost:8099

Reuses lights.py (same BLE device + command builders) but holds ONE persistent
BLE connection in a background asyncio thread for snappy colour-wheel response.
Features: on/off, colour wheel, brightness, effects + speed, a music-reactive
'Listen' mode (mic), and an auto-off timer. Close the phone app first (one BLE link).
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
            ms = int(2300 - (v - 27) * 1300 / 73)                      # 1000 ms at speed 100 (judged by eye vs the bed)
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
LISTEN_FLOOR = 0.3   # calibration knob: dimmest listen colour (0-1); lower = more contrast, but the table goes dark
def _listen_loop():
    try:
        import pyaudio, numpy as np
    except Exception as e:
        print("listen needs pyaudio/numpy:", e); STATE["listen"] = False; return
    pa = pyaudio.PyAudio()
    try:
        st = pa.open(rate=16000, channels=1, format=pyaudio.paInt16, input=True, frames_per_buffer=1024)
    except Exception as e:
        print("mic open failed:", e); STATE["listen"] = False; pa.terminate(); return
    hue, ema, last = 0.0, 0.0, 0.0
    while STATE["listen"]:
        try:
            buf = np.frombuffer(st.read(1024, exception_on_overflow=False), dtype=np.int16).astype(np.float32)
        except Exception:
            break
        rms = float(np.sqrt(np.mean(buf ** 2)))
        level = min(1.0, rms / 2500.0)
        ema = 0.6 * ema + 0.4 * level                      # smooth the loudness
        hue = (hue + 0.006 + ema * 0.04) % 1.0             # hue drifts, faster when louder
        # floor 30%: the table controller shows very dim colours as OFF (at 8% it looked dead, 2026-11-17)
        r, g, b = [int(x * 255) for x in colorsys.hsv_to_rgb(hue, 1.0, LISTEN_FLOOR + (1 - LISTEN_FLOOR) * ema)]
        # straight to the queues, NOT send() (listen colours must not replace LAST). Lockstep: a new colour goes to
        # both strips together once both are ready, so they match; after 1 s a stuck/disconnected strip is skipped.
        ready = [sq for sq in QS if sq.empty()]
        if ready and (len(ready) == len(QS) or time.time() - last > 1.0):
            for sq in ready: sq.put(Fast(lights._rgb(r, g, b)))
            last = time.time()
        time.sleep(0.05)
    try: st.close()
    except Exception: pass
    pa.terminate()
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

        if path in ("/", "/index.html"):
            return self._send(PAGE, "text/html; charset=utf-8")
        if path == "/deck":
            return self._send(DECK_PAGE, "text/html; charset=utf-8")
        if path == "/do":                                      # deck button: only the fixed DECK list, by index
            return self._send(json.dumps({"say": _deck_do(g("i", -1))}))
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


PAGE = r"""<!doctype html><html lang="en"><head>
<meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1,viewport-fit=cover">
<title>Nova Lights</title>
<style>
  :root{--bg:#07090e;--panel:#111722;--line:#223047;--ink:#e8eefc;--dim:#7d8aa3;
    --accent:#22d3ee;--accent2:#ff8a3c;--ok:#39e08f;}
  *{box-sizing:border-box;-webkit-tap-highlight-color:transparent;user-select:none}
  body{margin:0;background:radial-gradient(900px 500px at 50% -10%,#101a2e,var(--bg));
    color:var(--ink);font-family:ui-rounded,system-ui,-apple-system,"Segoe UI",sans-serif;
    min-height:100dvh;padding:18px;display:flex;flex-direction:column;align-items:center;gap:16px}
  h1{font-size:18px;letter-spacing:3px;font-weight:700;margin:4px 0 0;color:#fff}
  h1 small{display:block;font-size:11px;letter-spacing:4px;color:var(--accent);font-weight:600;margin-top:2px}
  .dot{display:inline-block;width:8px;height:8px;border-radius:50%;background:var(--dim);margin-right:6px;vertical-align:middle}
  .dot.on{background:var(--ok);box-shadow:0 0 8px var(--ok)}
  .card{width:100%;max-width:420px;background:var(--panel);border:1px solid var(--line);
    border-radius:18px;padding:16px;box-shadow:0 10px 40px rgba(0,0,0,.4)}
  /* colour wheel */
  .wheelwrap{display:flex;justify-content:center;margin:4px 0 10px}
  #wheel{position:relative;width:240px;height:240px;border-radius:50%;cursor:pointer;touch-action:none;
    background:
      radial-gradient(circle,#fff 0%,rgba(255,255,255,0) 70%),
      conic-gradient(red,#ff0,lime,cyan,blue,magenta,red);
    box-shadow:0 0 0 3px var(--line),inset 0 0 40px rgba(0,0,0,.25)}
  #mk{position:absolute;width:22px;height:22px;border-radius:50%;border:3px solid #fff;
    transform:translate(-50%,-50%);box-shadow:0 0 8px rgba(0,0,0,.6);left:50%;top:50%;pointer-events:none}
  .row{display:flex;gap:8px;margin-top:10px}
  .row.wrap{flex-wrap:wrap}
  button{flex:1;font-family:inherit;font-size:13px;font-weight:700;letter-spacing:1px;color:var(--ink);
    background:#192234;border:1px solid var(--line);border-radius:12px;padding:12px 8px;cursor:pointer;transition:.1s}
  button:active{transform:translateY(1px)}
  button.p{background:var(--accent);color:#06121a;border-color:transparent}
  button.o{background:var(--accent2);color:#1a0d04;border-color:transparent}
  button.live{outline:2px solid var(--ok)}
  .lbl{font-size:11px;letter-spacing:2px;color:var(--dim);margin:14px 0 6px;text-transform:uppercase}
  input[type=range]{width:100%;accent-color:var(--accent)}
  .swatch{width:34px;height:34px;border-radius:9px;border:2px solid var(--line);flex:none}
  .fx{display:grid;grid-template-columns:repeat(4,1fr);gap:8px}
  .fx button{padding:11px 4px;font-size:12px}
  .timer{display:flex;gap:8px;align-items:center}
  .timer input{width:70px;background:#192234;border:1px solid var(--line);color:var(--ink);
    border-radius:10px;padding:10px;font-family:inherit;font-size:15px;text-align:center}
  .t{font-size:12px;color:var(--dim);min-height:16px}
</style></head><body>
  <h1><span class="dot" id="cdot"></span>NOVA LIGHTS<small>BLUETOOTH · LOCAL</small></h1>

  <div class="card">
    <div class="wheelwrap"><div id="wheel"><div id="mk"></div></div></div>
    <div class="row">
      <button class="p" onclick="go('/on')">⏻ ON</button>
      <div class="swatch" id="sw"></div>
      <button onclick="go('/off')">OFF</button>
    </div>

    <div class="lbl">Brightness</div>
    <input type="range" id="bri" min="1" max="100" value="100" oninput="bri(this.value)">

    <div class="lbl">Effects</div>
    <div class="fx">
      <button onclick="fx('party')">Party</button>
      <button onclick="fx('fade')">Fade</button>
      <button onclick="fx('cycle')">Cycle</button>
      <button onclick="fx('strobe')">Strobe</button>
    </div>
    <div class="lbl">Effect speed</div>
    <input type="range" id="spd" min="1" max="100" value="50" oninput="spd(this.value)">

    <div class="lbl">Listen (music → colour)</div>
    <div class="row"><button id="lbtn" class="o" onclick="toggleListen()">🎵 START LISTENING</button></div>

    <div class="lbl">Auto-off timer</div>
    <div class="timer">
      <input type="number" id="min" placeholder="min" min="1" value="30">
      <button onclick="timer()">Set</button>
      <button onclick="go('/timer?min=0');msg('')">Cancel</button>
    </div>
    <div class="t" id="tmsg"></div>
  </div>

<script>
const $=s=>document.querySelector(s);
let listening=false;
function go(p){return fetch(p).catch(()=>{});}
function msg(t){$("#tmsg").textContent=t;}

// colour wheel
const wheel=$("#wheel"), mk=$("#mk"), sw=$("#sw");
let dragging=false, lastSend=0;
function hsv2rgb(h,s,v){let f=(n,k=(n+h*6)%6)=>v-v*s*Math.max(Math.min(k,4-k,1),0);
  return [f(5),f(3),f(1)].map(x=>Math.round(x*255));}
function pick(e){
  const r=wheel.getBoundingClientRect(), cx=r.left+r.width/2, cy=r.top+r.height/2, R=r.width/2;
  let x=e.clientX-cx, y=e.clientY-cy; let d=Math.hypot(x,y);
  if(d>R){x*=R/d; y*=R/d; d=R;}                              // clamp inside the wheel
  const sat=Math.min(1,d/R);
  let hue=((Math.atan2(x,-y)*180/Math.PI)+360)%360/360;      // clockwise from TOP = conic-gradient order (red@top)
  mk.style.left=(50+x/R*50)+"%"; mk.style.top=(50+y/R*50)+"%";  // marker sits under the finger
  const [rr,gg,bb]=hsv2rgb(hue,sat,1); sw.style.background=`rgb(${rr},${gg},${bb})`;
  const now=Date.now(); if(now-lastSend>70){lastSend=now; go(`/color?r=${rr}&g=${gg}&b=${bb}`); setListen(false);}
}
wheel.addEventListener("pointerdown",e=>{dragging=true;wheel.setPointerCapture(e.pointerId);pick(e);});
wheel.addEventListener("pointermove",e=>{if(dragging)pick(e);});
wheel.addEventListener("pointerup",e=>{dragging=false;pick(e);});

function bri(v){go(`/brightness?v=${v}`);}
function spd(v){go(`/speed?v=${v}`);}
function fx(n){go(`/effect?name=${n}`);setListen(false);}
function timer(){const m=+$("#min").value||0; if(m>0){go(`/timer?min=${m}`);msg(`Off in ${m} min.`);}}
function setListen(on){listening=on; $("#lbtn").classList.toggle("live",on);
  $("#lbtn").textContent=on?"🎵 LISTENING… (tap to stop)":"🎵 START LISTENING";}
function toggleListen(){setListen(!listening); go(`/listen?on=${listening?1:0}`);}

// poll state (connection dot + timer countdown)
setInterval(async()=>{try{const s=await (await fetch("/state")).json();
  $("#cdot").classList.toggle("on",s.connected);
  if(s.timer>0)msg(`Off in ${Math.ceil(s.timer/60)} min.`);
  if(s.listen!==listening)setListen(s.listen);
}catch(e){}},1500);
</script>
</body></html>"""


# ---------- touch deck (/deck): one button = one fixed Nova action. Works while the Nova app is off. ----------
DECK = [   # (group, label, nova function, args) - add a button = add a line
    ("Ceiling", "On", "bulb", ("on",)), ("Ceiling", "Off", "bulb", ("off",)), ("Ceiling", "Warm", "bulb", ("warm",)),
    ("Ceiling", "Dim", "bulb", ("brightness 20",)), ("Ceiling", "Bright", "bulb", ("brightness 100",)),
    ("Strips", "On", "lights", ("on",)), ("Strips", "Off", "lights", ("off",)), ("Strips", "Warm", "lights", ("warm",)),
    ("Strips", "Party", "lights", ("party",)), ("Strips", "Blue", "lights", ("blue",)),
    ("AC", "On", "ac", ("on",)), ("AC", "Off", "ac", ("off",)), ("AC", "24°", "ac", ("temp 24",)), ("AC", "26°", "ac", ("temp 26",)),
    ("Fan", "On", "iot_control", ("fan", "on")), ("Fan", "Off", "iot_control", ("fan", "off")),
    ("Projector", "Power", "projector", ("toggle",)), ("Projector", "Colour", "projector", ("colour",)),
    ("Projector", "Laser", "projector", ("laser",)),
    ("Music", "Stop", "stop_music", ()),
]
_deck_lock = threading.Lock()


def _deck_do(i):
    if not 0 <= i < len(DECK): return "Unknown button."
    _, label, fn, args = DECK[i]
    with _deck_lock:                                   # one at a time: a double-tap can't fire a toggle twice in parallel
        try:
            import nova                                # lazy: ~2 s the first time, then cached
            return str(nova.FUNCS[fn](*args))
        except Exception as e:
            print("[deck]", fn, args, e, flush=True); return "%s failed: %s" % (label, str(e)[:60])


def _deck_page():
    import html, itertools
    out = []
    for grp, items in itertools.groupby(enumerate(DECK), key=lambda x: x[1][0]):
        btns = "".join('<button data-i="%d">%s</button>' % (i, html.escape(d[1])) for i, d in items)
        out.append('<section><h2>%s</h2><div class="row">%s</div></section>' % (html.escape(grp), btns))
    return DECK_HTML.replace("{{BODY}}", "".join(out))


DECK_HTML = r"""<!doctype html><html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1,viewport-fit=cover"><title>Nova Deck</title>
<meta name="apple-mobile-web-app-capable" content="yes"><meta name="theme-color" content="#0b0908">
<style>
:root{--bg:#0b0908;--tile:#1a1512;--tile2:#241c17;--fg:#ffdbc9;--dim:#a08a7c;--acc:#ff9a42}
*{box-sizing:border-box;-webkit-tap-highlight-color:transparent}
body{margin:0;background:var(--bg);color:var(--fg);font:16px/1.3 -apple-system,system-ui,sans-serif;padding:16px 16px 90px;user-select:none}
h1{font-size:20px;margin:4px 0 14px;color:var(--acc);letter-spacing:.5px}
h2{font-size:13px;text-transform:uppercase;letter-spacing:1.5px;color:var(--dim);margin:18px 0 8px}
.row{display:grid;grid-template-columns:repeat(auto-fill,minmax(96px,1fr));gap:10px}
button{height:84px;border:1px solid #2e241d;border-radius:16px;background:var(--tile);color:var(--fg);font:600 17px system-ui,sans-serif;touch-action:manipulation}
button:active{background:var(--tile2);transform:scale(.96)}
button.busy{border-color:var(--acc);color:var(--acc)}
#toast{position:fixed;left:16px;right:16px;bottom:16px;padding:14px 16px;border-radius:14px;background:#241c17;border:1px solid #3a2d24;opacity:0;transition:opacity .2s}
#toast.on{opacity:1}
</style></head><body><h1>NOVA</h1>{{BODY}}<div id="toast"></div>
<script>
const t=document.getElementById("toast");let h;
document.querySelectorAll("button[data-i]").forEach(b=>b.onclick=async()=>{
  if(b.classList.contains("busy"))return; b.classList.add("busy");
  try{const r=await (await fetch("/do?i="+b.dataset.i)).json();t.textContent=r.say}catch(e){t.textContent="Hub not reachable."}
  b.classList.remove("busy");t.classList.add("on");clearTimeout(h);h=setTimeout(()=>t.classList.remove("on"),3000);
});
</script></body></html>"""
DECK_PAGE = _deck_page()
assert DECK_PAGE.count("data-i=") == len(DECK) and "{{BODY}}" not in DECK_PAGE   # self-check: every button rendered


def main():
    tq = TableQ(); QS.append(tq); NAMES[tq] = "ESP32 table " + STRIPS["table"]
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
