"""Nova desktop app (pywebview window + voice + devices). Most of Api lives in mixins:
  nova_voice.py (speak, STT, hands-free loop)  nova_brain.py (chat + LLM tiers + tools)  nova_automations.py (routines + sensor rules)
  nova_common.py (constants + module helpers).  Run:  python3 ~/anish-ai/app/nova_app.py"""
import sys, os
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from nova_common import *   # noqa: F403
from nova_voice import Voice
from nova_brain import Brain
from nova_automations import Automations


class Api(Voice, Brain, Automations):
    CONVO_PATH = os.path.expanduser("~/anish-ai/conversation.json")

    def __init__(self):
        self.messages = self._load_convo()   # remember recent conversation across restarts
        self._net = psutil.net_io_counters()
        self._t = time.monotonic()
        psutil.cpu_percent(percpu=True)  # prime per-core reading
        self.voice = True
        self._voice = "en-GB-RyanNeural"    # Alfred-style distinguished British butler
        self._rate = "-6%"                  # measured but not sluggish
        self._pitch = "-9Hz"                # gravitas without sounding robotic
        self._say = None
        self._stt_lock = threading.Lock()   # Mac: one fallback transcription at a time
        self._ref_segs = []                 # [(play start time, loudness envelope)] of Nova's recent replies
        self._speak_gen = 0                 # bumped on each speak()/stop() to abort stale streams
        self._hf = False                    # hands-free (wake-word) mode
        self._hf_thread = None
        self.memory = self._load_memory()   # cross-session memory (facts about the user)
        self._alerted = {}                  # de-dupe proactive alerts
        self._iot_data = {"temp": None, "humidity": None, "motion": False, "online": False, "ts": 0}
        self._car_data = {"throttle": "stop", "steer": "center", "rssi": None, "online": False, "ts": 0}
        self._last_motion_ts = time.time()   # suppress a welcome for the first few min after boot
        self._last_welcome_ts = 0
        threading.Thread(target=self._iot_listener, daemon=True).start()  # live climate for the HUD
        nova.SPEAK = self.speak                 # reminders fire in Daniel's voice on the room speaker
        if nova.IS_HUB: nova.HANDSFREE = self.set_handsfree   # "mic off" also stops the hub's own mic
        nova.SAY_WAIT = self._say_wait          # alarm: speak a line and return when it has finished
        nova.resume_reminders()                 # re-arm timed reminders saved before a restart
        if nova.IS_HUB: self._resume_later()    # same for routine steps (goodnight's fade + AC easing)
        if not nova.IS_HUB:
            threading.Thread(target=self._volume_mirror, daemon=True).start()
            threading.Thread(target=self._presence_ping, daemon=True).start()
        threading.Thread(target=self._health_watch, daemon=True).start()   # Telegram when hub/ESP32 drop off
        if not nova.IS_HUB:                     # scan every new download before it's opened (filecheck.py)
            threading.Thread(target=self._downloads_watch, daemon=True).start()
        if nova.IS_HUB:                         # freelance mail: orders, buyer messages, scams (mailwatch.py)
            import mailwatch
            threading.Thread(target=mailwatch.run, args=(self.speak, self._tg_alert), daemon=True).start()
        if os.path.exists(os.path.expanduser("~/anish-ai/.icloud_user_key")):   # Mac only: pre-login Find My
            threading.Thread(target=__import__("findmy").warm, daemon=True).start()
        self._mic_gain = 100 if nova.IS_HUB else 70   # hub: USB webcam mic, and no SwitchAudioSource there to set it
        self._close_mic = False             # lavalier/USB: close mic rejects the speaker -> no ducking needed
        self._ducked = False                # mic ducked while Nova speaks (reduces self-echo)
        threading.Thread(target=self._duck_loop, daemon=True).start()
        if not nova.IS_HUB:   # hub's screen is broken: its HUD volume bar cost an osascript every 300 ms for nobody
            threading.Thread(target=self._volume_loop, daemon=True).start()  # live volume bar in the HUD
        threading.Thread(target=self._warm_face, daemon=True).start()    # preload face-recognition model
        self.vprofile = self._load_vprofile()   # learns your voice timing + vocabulary over time
        self._last_cmd_at = 0
        self._cam_on = True                 # HUD WEBCAM button toggles this (set_camera)
        try:
            if not ON_SENSES or os.environ.get("NOVA_GESTURES") == "0": raise RuntimeError("gestures off here")
            print(nova.gesture_control("start"), flush=True)  # always-on: webcam room presence
        except Exception as e:
            print("[gesture] autostart failed:", e, flush=True)
        import atexit
        atexit.register(lambda: nova.gesture_control("stop"))  # release camera when Nova exits

    # ---------- cross-session memory ----------
    MEM_PATH = os.path.expanduser("~/anish-ai/memory.json")

    def _load_memory(self):
        try:
            with open(self.MEM_PATH) as f:
                return json.load(f)
        except Exception:
            return {"name": "sir", "facts": []}

    def _save_memory(self):
        try:
            with open(self.MEM_PATH, "w") as f:
                json.dump(self.memory, f, indent=2)
        except Exception:
            nova.swallowed()

    def _load_convo(self):
        try:
            with open(self.CONVO_PATH) as f:
                return json.load(f)[-12:]
        except Exception:
            return []

    def _save_convo(self):
        try:
            with open(self.CONVO_PATH, "w") as f:
                json.dump(self.messages[-12:], f)
        except Exception:
            nova.swallowed()

    def remember(self, fact):
        """Store a durable fact about the user for future sessions."""
        fact = (fact or "").strip()
        if fact and fact not in self.memory.get("facts", []):
            self.memory.setdefault("facts", []).append(fact)
            self.memory["facts"] = self.memory["facts"][-40:]
            self._save_memory()
        return "Noted, sir."

    def _presence_ping(self):
        """Mac: typing/mouse in the last 90 s -> tell the hub you're here, so the empty-room rules don't switch
        the lights/AC off while you sit still at the desk (the camera only sees movement). Cleanup fix 2, 2026-11-17."""
        while True:
            time.sleep(60)
            try:
                o = subprocess.run(["ioreg", "-c", "IOHIDSystem"], capture_output=True, text=True, timeout=5).stdout
                idle = int(re.search(r'"HIDIdleTime" = (\d+)', o).group(1)) / 1e9
                if idle < 90: nova._hub_send("present", str(time.time()))
            except Exception as e:
                print("[presence] ping failed:", str(e)[:60], flush=True)

    def _volume_mirror(self):
        """Keep the hub speaker (Nova's voice) at the Mac's volume — keys, Nova, anything; muted = 0."""
        last = None
        while True:
            try:
                seen = getattr(self, "_vol_seen", None)   # the HUD volume bar already reads it every 1 s:
                if seen and time.time() - seen[2] < 3:    # a 2nd osascript poll cost ~0.23 s every 2 s
                    v, m = seen[0], seen[1]
                else:
                    v, m = self._read_volume()
                lvl = 0 if m else int(v)
                if lvl != last:
                    nova._hub_send("volume", lvl); last = lvl
            except Exception:
                nova.swallowed()
            time.sleep(2)   # ponytail: polled, ~2 s lag; no CoreAudio listener needed

    def _day_stats(self, d, t):
        day = time.strftime("%Y-%m-%d", time.localtime(t - 6 * 3600))
        if self._day.get("date") != day:
            self._day = {"date": day, "tmin": None, "tmax": None, "ac_min": 0.0, "alerts": 0, "_t": t}
        s = self._day
        dt, s["_t"] = min(t - s["_t"], 60), t                 # cap gaps (hub asleep / node offline)
        tc = d.get("temp")
        if tc is not None:
            s["tmin"] = tc if s["tmin"] is None else min(s["tmin"], tc)
            s["tmax"] = tc if s["tmax"] is None else max(s["tmax"], tc)
        if d.get("ac") == "on": s["ac_min"] += dt / 60
        if t - self._day_pub > 300:
            self._day_pub = t
            threading.Thread(target=self._pub_retained, args=("home/hub/daystats",
                             json.dumps({k: v for k, v in s.items() if k != "_t"})), daemon=True).start()

    def set_camera(self, on):
        """HUD WEBCAM button: on = gesture watcher owns the camera; off = camera released (light goes out)."""
        self._cam_on = bool(on)
        print("[cam]", nova.gesture_control("start" if self._cam_on else "stop"), flush=True)
        return self._cam_on

    def set_voice(self, on):
        self.voice = bool(on)
        if not self.voice:
            self.stop_speaking()
        return self.voice

    def attach_file(self):
        """Open a native file picker; load the file into context so Nova can read/edit/discuss it."""
        try:
            paths = webview.windows[0].create_file_dialog(webview.OPEN_DIALOG, allow_multiple=False)
        except Exception as e:
            return {"ok": False, "msg": str(e)[:60]}
        if not paths:
            return {"ok": False, "msg": "cancelled"}
        path = paths[0]
        name = os.path.basename(path)
        try:
            with open(path, "r", errors="ignore") as f:
                content = f.read()
            note = ("The user attached a file '%s' (path: %s). Its contents:\n\n%s"
                    % (name, path, content[:6000]))
        except Exception:
            note = ("The user attached a file '%s' (path: %s). It's not plain text (image/binary); "
                    "use tools on the path if needed." % (name, path))
        self.messages.append({"role": "user", "content": note})
        return {"ok": True, "name": name, "path": path}

    def _js(self, code):
        if not webview.windows: return               # no HUD window (yet): was an IndexError on every call
        t = time.time()
        try:
            webview.windows[0].evaluate_js(code)
        except Exception:
            nova.swallowed()
        if time.time() - t > 0.1: print("[js] slow HUD update %.2fs: %s" % (time.time() - t, code[:40]), flush=True)   # blocks the caller

    def _placeholder(self, msg):
        self._js('var b=document.getElementById("box"); if(b) b.placeholder=' + json.dumps(msg) + ';')

    WELCOME_GAP = 300   # seconds of no motion that counts as "away" -> greet on return

    def _maybe_welcome(self, motion):
        """Greet only when motion resumes after a real absence (not on every PIR pulse)."""
        if not motion:
            return
        now = time.time()
        away = now - self._last_motion_ts
        self._last_motion_ts = now
        if away > self.WELCOME_GAP and now - self._last_welcome_ts > self.WELCOME_GAP:
            self._last_welcome_ts = now
            threading.Thread(target=self._welcome_if_owner, args=(away,), daemon=True).start()

    def _greeting(self):
        """First greeting of the morning (5-12) = "Very good morning", otherwise "Welcome back" (owner's wording)."""
        today = time.strftime("%Y-%m-%d")
        if 5 <= time.localtime().tm_hour < 12 and getattr(self, "_gm_day", None) != today:
            self._gm_day = today
            return "Very good morning, sir."
        return "Welcome back, sir."

    def _welcome_if_owner(self, away):
        """Motion after an absence -> hand the Lapcare from gesture control to the face-check
        (you're away, not gesturing), verify it's you, then resume gesture. Never uses the Mac cam."""
        if not self._auto_on:                              # good night -> no "welcome back" at 3am
            return
        import random
        sys.path.insert(0, os.path.expanduser("~/anish-ai"))
        import face_id
        if not os.path.exists(face_id.OWNER):             # owner's rule: greet ONLY on a recognised face, never on motion
            print("[face] not enrolled — no greeting. Enroll: python3 ~/anish-ai/face_id.py enroll", flush=True); return
        if not self._cam_on:                             # webcam switched off in the HUD -> never open it (so no greeting)
            return
        who = None
        gesture_was_on = False
        try:
            gesture_was_on = nova.gesture_control("stop").startswith("Gesture control off")  # free the Lapcare
            time.sleep(1.2)                              # let the camera actually release
        except Exception:
            nova.swallowed()
        try:
            import face_id
            who = face_id.is_owner(timeout=3.0)          # True=you, False=someone else, None=no face/not enrolled
        except Exception as e:
            print("[face] error: %s" % str(e)[:70], flush=True)
        if gesture_was_on:
            try:
                nova.gesture_control("start")          # hand the camera back to gesture control
            except Exception:
                nova.swallowed()
        if who is not True:                               # someone else, or no face seen -> stay quiet
            print("[iot] motion, face not recognised (%s) — staying quiet" % who, flush=True); return
        if os.path.exists(self._AWAY_F): self._set_away(False)   # it's you -> back home
        self.speak(self._greeting())
        print("[iot] welcome-back (away %.0fs, owner=%s)" % (away, who), flush=True)

    def _warm_face(self):
        if not ON_SENSES:                                # face checks only run where the camera is (hub)
            return
        try:
            sys.path.insert(0, os.path.expanduser("~/anish-ai"))
            import face_id; face_id._app()               # preload the model so the first check is fast
            print("[face] recognition model loaded", flush=True)
        except Exception as e:
            print("[face] warm-up failed: %s" % str(e)[:70], flush=True)

    def drive(self, command):
        """HUD drive control for the RC crawler — forward/back/stop/left/right/center, or 'speed <0-100>'."""
        try:
            cmd = (command or "").lower().strip()
            if cmd.startswith("speed"):
                import paho.mqtt.client as mqtt
                c = nova.mqtt_client()
                c.connect(nova._IOT_BROKER, 1883, 5)
                c.publish("home/car/speed", "".join(ch for ch in cmd if ch.isdigit()) or "100")
                c.disconnect()
                return "ok"
            return nova.drive(cmd)
        except Exception as e:
            return "drive error: %s" % e

    _mac_online = False
    _mac_change_ts = time.time()       # startup counts as a change -> 60s grace before guarding

    MAC_HOST = "Anishs-MacBook-Air.local"
    _mac_busy, _busy_ts = False, 0.0      # hub: Mac is answering -> hold the follow-up window
    _hub_speaking = False                 # hub: synthesizing a reply the Mac sent
    _hub_link = False                     # Mac: connected to the hub's broker (= at home)
    _private = False                      # "private mode": only the local MLX/ollama brains, nothing leaves the Mac
    _mlx_proc = None
    _kokoro_proc = None
    _brain_cool = {}                      # brain name -> time it's usable again (after a 429)
    _audio_q = None                       # hub: queue of Kokoro WAVs from the Mac
    _clip_on = _local_talking = False     # hub: one voice at a time (Mac reply clip vs hub's own speech)
    _talk_tok = _netmic = None
    _hub_speak_lock = threading.Lock()    # Mac: serialize speak() -> hub so replies never overlap
    _mute_until = 0.0                     # hub: after "Nova, stop" drop reply chunks still arriving from the Mac
    _claude_mode = True                   # Mac: talk to Claude by default ("quick mode" -> local brain)   # awake on the Wi-Fi = you're home, even if Nova isn't open

    def _home(self):
        """You're home if the Mac's Nova is connected or the Mac answers a ping (checked at most every 20s)."""
        if self._mac_online: return True
        now = time.time()
        if now - getattr(self, "_ping_ts", 0) > 20:
            self._ping_ts = now
            self._ping_ok = subprocess.run(["ping", "-c1", "-t2", self.MAC_HOST], capture_output=True).returncode == 0
            if self._ping_ok: self._mac_change_ts = now      # seen just now -> restart the 60s grace
        return self._ping_ok
    # ponytail: the Mac asleep at home = "away" -> you may get a photo of yourself; add phone presence if that bites

    def _guard_loop(self):
        """Hub: while you're away (Mac gone), the webcam guards the room (photo to Telegram on motion)."""
        sys.path.insert(0, os.path.expanduser("~/anish-ai"))
        import guard
        while True:
            time.sleep(5)
            if self._home() or time.time() - self._mac_change_ts < 60 or not os.path.exists(guard.CHAT_F):
                continue
            nova.gesture_control("stop"); time.sleep(1.5)     # free the webcam
            try:
                guard.watch(lambda: not self._home(), log=lambda m: print(m, flush=True))
            except Exception as e:
                print("[guard] error: %r" % e, flush=True); time.sleep(30)
            if self._home(): nova.gesture_control("start")

    def _iot_listener(self):
        """Persistent MQTT subscriber -> keeps self._iot_data fresh for the HUD's live climate readout."""
        import paho.mqtt.client as mqtt, json as _json
        def on_connect(c, u, f, rc, *a):
            c.subscribe("home/room/#")
            c.subscribe("home/car/#")           # RC crawler telemetry for the HUD
            if nova.IS_HUB:
                c.subscribe("home/hub/#")          # jobs the Mac's Nova hands to the hub
                c.subscribe("home/mac/#")          # status (retained + last-will), busy, said
                threading.Thread(target=self._pub_sleep, daemon=True).start()   # re-announce sleep state (broker restarts drop retained)
                self._room_seen = set()
                threading.Thread(target=self._restore_room_state, daemon=True).start()   # same for AC + projector
                c.publish("home/hub/status", "online", retain=True)
            else:
                c.subscribe("home/hub/heard")      # what the hub's mic heard -> we think + answer
                c.subscribe("home/mac/stt/#")      # hub's STT fallback -> local Whisper here
                c.subscribe("home/mac/pick")       # deck / hub "pick a song" -> song-picker popup here
                c.subscribe("home/sleep")          # hub owns sleep mode (good night); we mirror it
                c.subscribe("home/hub/status")     # hub Nova app alive (retained + last-will)
                c.subscribe("home/nova/off")       # Telegram "Nova off" (hub supervisor.py) -> pause this mic too
                if self._local_whisper is None:    # preload (~1 s) so the first fallback isn't slow
                    threading.Thread(target=self._warm_stt, daemon=True).start()
                self._hub_link = True
                self._kokoro_up()                  # start/warm the local Daniel voice in the background
                c.publish("home/mac/status", "online", retain=True)
        def on_msg(c, u, m):
            if m.topic == "home/hub/audio":
                if nova.IS_HUB:
                    if self._audio_q is None:
                        import queue
                        self._audio_q = queue.Queue()
                        threading.Thread(target=self._hub_audio_player, daemon=True).start()
                    self._audio_q.put(m.payload)
                return
            if m.topic == "home/hub/status":
                self._hub_app_on = m.payload == b"online"; return
            if m.topic == "home/nova/off":             # only on a change, and give back the mic state you had
                off = m.payload == b"1"
                if off != getattr(self, "_nova_off", False):
                    self._nova_off = off
                    if off: self._hf_before_off = self._hf; self.set_handsfree(False)
                    elif getattr(self, "_hf_before_off", False): self.set_handsfree(True)
                    print("[nova] Telegram %s -> mic %s" % ("off" if off else "on", "paused" if off else "restored"), flush=True)
                return
            if m.topic == "home/sleep":
                if not nova.IS_HUB: self._hub_asleep = m.payload == b"1"
                return
            if m.topic.startswith("home/mac/stt/") and not nova.IS_HUB:     # Mac: transcribe for the hub
                def _do(rid=m.topic.rsplit("/", 1)[1], wav=m.payload):
                    # one at a time: a pile of parallel jobs (noise clips) made EVERY job too slow and real commands
                    # timed out. Queue briefly (hub waits 10 s); still busy after 6 s -> answer "" so it moves on.
                    if not self._stt_lock.acquire(timeout=6):
                        c.publish("home/hub/stt/" + rid, "", qos=1); return
                    try: txt = self._local_stt(wav)
                    except Exception as e: print("[stt] local failed:", e, flush=True); txt = ""
                    finally: self._stt_lock.release()
                    c.publish("home/hub/stt/" + rid, txt, qos=1)
                threading.Thread(target=_do, daemon=True).start(); return
            if m.topic.startswith("home/hub/stt/"):
                if nova.IS_HUB:
                    w = self._stt_wait.get(m.topic.rsplit("/", 1)[1])
                    if w: w[1] = m.payload.decode(); w[0].set()
                return
            key, val = m.topic.split("/")[-1], m.payload.decode()
            if m.topic == "home/mac/status":
                on = val == "online"
                if on != self._mac_online: self._mac_change_ts = time.time(); print("[hub] mac", val, flush=True)
                self._mac_online = on
                if not on: self._mac_busy = False
                return
            if m.topic == "home/hub/privacy" and nova.IS_HUB:   # Mac-typed or Telegram "cam/mic on/off"
                dev, _, act = val.partition(" ")
                print("[hub] privacy", nova.camera_mic(dev, act), flush=True); return
            if m.topic == "home/mac/pick":
                if not nova.IS_HUB: nova.pick_song()   # the Mac opens its own fixed URL; the payload is ignored
                return
            if m.topic == "home/mac/busy":
                self._mac_busy, self._busy_ts = val == "1", time.time(); return
            if m.topic in ("home/mac/said", "home/hub/said"):   # what the Mac speaks -> hub's echo/interrupt filter
                self._last_spoken, self._spoken_at = val, time.time(); return
            if m.topic == "home/hub/heard" and not nova.IS_HUB:
                if val == "__stop__":                  # you said "Nova ..." over the reply -> stop sending it
                    self._speak_gen += 1; print("[hub] interrupted -> reply stopped", flush=True); return
                def _answer(val=val, c=c):
                    c.publish("home/mac/busy", "1")
                    try:
                        self._vp_learn(val); self.chat(val)
                    finally:
                        while self._say and self._say.poll() is None: time.sleep(0.2)
                        c.publish("home/mac/said", getattr(self, "_last_spoken", ""))
                        c.publish("home/mac/busy", "0")
                threading.Thread(target=_answer, daemon=True).start(); return
            if m.topic.startswith("home/hub/"):           # ---- hub jobs from the Mac ----
                if key == "gestures":
                    print("[hub] gestures", val, "->", nova.gesture_control(val), flush=True)
                elif key == "awake":                      # Mac ran Morning: you're up -> stop/skip alarms (nova.alarm_off)
                    nova.alarm_off(val or "mac")
                elif key == "say":
                    if val.startswith("[alarm] "):      # morning clip announcement: ring until "good morning"
                        threading.Thread(target=nova.wake, args=(val[8:],), daemon=True).start()
                    else: threading.Thread(target=self._say_wait, args=(val,), daemon=True).start()
                elif key in ("lights", "strips"):          # strips = a routine step: strips only, no bulb mirror
                    if not getattr(self, "_strip_q", None):          # one worker = strip commands run in arrival order
                        import queue; self._strip_q = queue.Queue()
                        def _strip_worker():
                            while True:
                                k, v = self._strip_q.get()
                                print("[hub] %s" % k, v, "->", nova.lights(v, mirror=(k == "lights")), flush=True)
                        threading.Thread(target=_strip_worker, daemon=True).start()
                    self._strip_q.put((key, val))
                elif key == "present":                    # Mac keyboard/mouse in use (see _presence_ping)
                    self._mac_active_ts = float(val)
                elif key == "ac_manual":                  # you set the AC yourself: pending AC steps made before that are dropped
                    t = float(val)                        # (their sleeping timers find the job gone and skip)
                    old = lambda x: x["st"].get("do") == "ac" and x["due"] - float(x["st"].get("after_min", 0)) * 60 < t - 1
                    dropped = []
                    self._later_edit(lambda j: [x for x in j if not (old(x) and not dropped.append(x))])
                    if dropped: print("[hub] manual AC -> dropped %d scheduled AC step(s)" % len(dropped), flush=True)
                elif key == "later":                      # a delayed routine step the Mac handed over
                    j = json.loads(val); st = j["st"]
                    self._later(j["name"], st)
                    print("[hub] later %s in %s min: %s(%r)" % (j["name"], st["after_min"], st.get("do"), st.get("arg")), flush=True)
                elif key == "display":                    # goodnight sleeps the wall screen, morning wakes it
                    subprocess.Popen(["pmset", "displaysleepnow"] if val == "off" else ["caffeinate", "-u", "-t", "2"])
                elif key == "automations":
                    self._auto_on = (val == "on"); print("[hub] automations", val, flush=True)
                elif key == "away":
                    self._set_away(val == "on")
                elif key == "stop":                       # Mac's stop button / interrupt
                    self._mute_until = time.time() + 2    # drop WAV chunks still in flight
                    while self._audio_q and not self._audio_q.empty(): self._audio_q.get_nowait()
                    self.stop_speaking(); self._hub_speaking = False
                    print("[hub] stop", flush=True)
                elif key == "routine":                    # the hub page's mode buttons: same as saying it
                    def _routine_here(name=val):
                        rs = json.load(open(self.ROUTINES)); r = rs.get(name)
                        if not r or name.startswith("_"): print("[hub] no routine", name, flush=True); return
                        said = self._run_routine(name, r)
                        if said: self._proactive(nova.speakable(said))
                    threading.Thread(target=_routine_here, daemon=True).start()
                elif key == "volume":
                    print("[hub] volume", val, "->", nova.set_volume(val), flush=True)
                elif key == "music":                      # the Mac's brain: music always plays on this speaker
                    def _music_here(j=json.loads(val)):
                        r = getattr(nova, j["fn"])(**j["kw"])
                        print("[hub] music %s -> %s" % (j["fn"], r[:100]), flush=True)
                        if not r.startswith(("Now playing", "Music stopped", "Nothing was", "Cancelled", "replaced", "Pick a song")):
                            nova._hub_send("say", r)      # tell him why (no fetch, private playlist...)
                    threading.Thread(target=_music_here, daemon=True).start()
                return
            if m.topic.startswith("home/car/"):          # ---- RC car ----
                cd = self._car_data
                try:
                    if   key == "status":    cd["online"] = (val == "online")
                    elif key == "throttle":  cd["throttle"] = val
                    elif key == "steer":     cd["steer"] = val
                    elif key == "telemetry":
                        t = _json.loads(val)
                        cd["throttle"] = t.get("throttle", cd["throttle"])
                        cd["steer"] = t.get("steer", cd["steer"])
                        cd["rssi"] = t.get("rssi", cd["rssi"])
                        cd["online"] = True
                    cd["ts"] = time.time()
                except Exception:
                    nova.swallowed()
                return
            d = self._iot_data
            try:
                if   key in ("light", "fan", "plug"):
                    d[key] = val                          # real relay state "on"/"off" (retained) -> HUD switches
                elif key == "temp":      d["temp"] = float(val)
                elif key == "humidity":  d["humidity"] = int(float(val))
                elif key == "motion":
                    now_m = val not in ("0", "", "False")
                    if ON_SENSES and self._mac_online: self._maybe_welcome(now_m)
                    if d.get("motion") and not now_m: self._motion_end_ts = time.time()   # for no-motion rules
                    d["motion"] = now_m
                    if now_m:
                        self._js("window.novaMotion&&window.novaMotion()")  # flash the HUD instantly
                elif key == "status":    d["online"] = (val == "online")
                elif key == "ac":                         # "on 24 cool auto lg m-1": "on" for rules, whole state for the wall
                    d["ac"], d["ac_full"] = (val.split() or [""])[0], val
                    self._save_room_state(key, val)
                elif key == "projector":
                    d["projector"] = val                  # Nova's tracked projector state (nova._proj_report)
                    self._save_room_state(key, val)
                elif key == "telemetry":
                    t = _json.loads(val)
                    if "temp" in t:     d["temp"] = float(t["temp"])
                    if "humidity" in t: d["humidity"] = int(t["humidity"])
                    if "motion" in t:   d["motion"] = bool(t["motion"])
            except Exception:
                return
            d["ts"] = time.time()
        while True:
            try:
                c = nova.mqtt_client()
                c.on_connect, c.on_message = on_connect, on_msg
                c.on_disconnect = lambda *a: setattr(self, "_hub_link", False)   # away -> speak on this Mac
                if not nova.IS_HUB: c.will_set("home/mac/status", "offline", retain=True)   # broker says we left
                else: c.will_set("home/hub/status", "offline", retain=True)
                c.connect(nova._IOT_BROKER, 1883, 30)
                c.loop_forever()             # blocks + auto-reconnects
            except Exception:
                time.sleep(5)                # broker down -> retry

    _hub_app_on = True
    _health_st = {}

    @staticmethod
    def _gw_mac():
        """Router's MAC = which network we're on (home vs away), no Location permission needed."""
        try:
            ip = re.search(r"gateway: (\S+)", subprocess.run(["route", "-n", "get", "default"],
                           capture_output=True, text=True, timeout=3).stdout).group(1)
            return re.search(r" at (\S+)", subprocess.run(["arp", "-n", ip], capture_output=True,
                             text=True, timeout=3).stdout).group(1)
        except Exception:
            return None

    def _health(self, key, down, label, after=180):
        """Telegram once when `key` has been down `after` s, once more when it's back."""
        st = self._health_st.setdefault(key, [None, False])     # [down since, alerted]
        now = time.time()
        if down:
            st[0] = st[0] or now
            if not st[1] and now - st[0] > after:
                st[1] = True; self._day["alerts"] = self._day.get("alerts", 0) + 1; msg = "⚠️ %s has been offline for %d min." % (label, (now - st[0]) // 60)
                self._tg_alert(msg)
        else:
            if st[1]: self._tg_alert("✅ %s is back online." % label)
            st[0], st[1] = None, False

    @staticmethod
    def _tg_alert(text):
        try:
            import guard
            guard._tg("sendMessage", data={"chat_id": open(guard.CHAT_F).read().strip(), "text": text})
        except Exception as e:
            print("[health] telegram failed:", nova.redact(e), flush=True)

    @staticmethod
    def _mem_report():
        """(trouble?, text): swap, free RAM, and the 3 biggest processes."""
        vm, sw = psutil.virtual_memory(), psutil.swap_memory()
        procs = sorted((p.info for p in psutil.process_iter(["name", "memory_info", "cmdline"]) if p.info["memory_info"]),
                       key=lambda i: -i["memory_info"].rss)[:3]
        def nm(i):
            cl = i.get("cmdline") or []
            return os.path.basename(next((a for a in cl[1:] if a.endswith(".py")), cl[0] if cl else i["name"] or "?"))
        top = ", ".join("%s %d MB" % (nm(i), i["memory_info"].rss >> 20) for i in procs)
        bad = sw.used > 2 << 30 or vm.available < 300 << 20
        return bad, "Hub memory: %.1f GB free of %.0f, swap %.1f GB. Biggest: %s." % (
            vm.available / 2**30, vm.total / 2**30, sw.used / 2**30, top)

    def _downloads_watch(self):
        """New file in ~/Downloads -> malware/scam check -> Nova says the verdict (danger also to Telegram).
        Files already there at startup are left alone; nothing is opened or run."""
        import filecheck
        d = os.path.expanduser("~/Downloads")
        DOCS = (".pdf", ".doc", ".docx", ".xls", ".xlsx", ".ppt", ".pptx", ".zip", ".rar", ".7z", ".rtf", ".txt", ".csv")
        try: seen = set(os.listdir(d))
        except Exception as e:
            print("[files] can't read Downloads:", e, flush=True); return
        sizes, fresh = {}, 0
        while True:
            time.sleep(4)
            if time.time() - fresh > 86400 and os.path.exists("/opt/homebrew/bin/freshclam"):   # daily virus-signature update
                fresh = time.time()
                subprocess.Popen(["/opt/homebrew/bin/freshclam", "--quiet"], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            try:
                for n in os.listdir(d):
                    p = os.path.join(d, n)
                    if n in seen or n.startswith(".") or n.endswith((".crdownload", ".download", ".part", ".tmp")) or not os.path.isfile(p):
                        continue
                    sz = os.path.getsize(p)
                    if sizes.get(n) != sz:                     # still being written: wait for it to settle
                        sizes[n] = sz; continue
                    seen.add(n); sizes.pop(n, None)
                    verdict, line, why = filecheck.spoken(p)
                    print("[files]", verdict, n, flush=True)
                    if verdict != "clean" or n.lower().endswith(DOCS):
                        self.speak(line)
                    if verdict == "danger":
                        self._tg_alert("\u26d4 Don't open %s: %s" % (n, "; ".join(why[:3])))
            except Exception as e:
                print("[files]", type(e).__name__, e, flush=True)

    def _health_watch(self):
        home_gw, mem_day = None, None
        _wk_f = os.path.expanduser("~/anish-ai/.weekly_sent")    # on disk: a restart in the 11:00 hour must not resend
        mem_week = open(_wk_f).read().strip() if os.path.exists(_wk_f) else None
        time.sleep(120)                                          # startup grace
        while True:
            try:
                if nova.IS_HUB:                                  # heartbeat for supervisor.py (it does the device checks)
                    hf = bool(self._hf and self._hf_thread and self._hf_thread.is_alive())
                    nm = self._netmic
                    json.dump({"ts": time.time(), "hf": hf, "mics": nm.live() if nm else [],   # IPs of streaming ESP32 mics
                               "lvl": nm.levels() if nm else {}},          # {ip: (floor, peak)} over the last 30 s
                              open("/tmp/nova_hb.json", "w"))
                    bad, rep = self._mem_report()
                    if bad and mem_day != time.strftime("%F"):           # at most one alert a day
                        mem_day = time.strftime("%F"); self._tg_alert("\U0001F9E0 " + rep)
                    if time.strftime("%a %H") == "Sun 11" and mem_week != time.strftime("%F"):
                        mem_week = time.strftime("%F"); open(_wk_f, "w").write(mem_week); self._tg_alert("\U0001F4CA Weekly. " + rep)
                else:
                    # ponytail: "at home" = same router as when we last reached the hub; a Mac restarted
                    # while the hub is already down never learns it, so no alert until the hub is seen once.
                    gw = self._gw_mac()
                    if self._hub_link: home_gw = gw or home_gw
                    home = home_gw is not None and gw == home_gw
                    # the hub's own supervisor.py watches its apps + devices; this only covers the hub being gone
                    self._health("broker", home and not self._hub_link, "Nova hub (broker / old Mac)")
            except Exception as e:
                print("[health]", e, flush=True)
            time.sleep(30)

    def _read_volume(self):
        try:
            out = subprocess.run(
                ["osascript", "-e", "set s to (get volume settings)",
                 "-e", 'return (output volume of s as string) & "," & (output muted of s as string)'],
                capture_output=True, text=True, timeout=2).stdout.strip()
            v, m = out.split(",")
            return int(v), (m.strip() == "true")
        except Exception:
            return None, False

    def _volume_loop(self):
        """Drive the HUD volume bar. During gestures, read the value the gesture watcher
        writes to .vol_state (20Hz, no osascript contention -> stays in sync). When no gesture
        is active, fall back to osascript ~3x/s to catch keyboard-volume and mute changes."""
        vf = os.path.expanduser("~/anish-ai/.vol_state")
        last, tick = None, 0
        while True:
            v, muted, fresh = None, False, False
            try:
                raw = open(vf).read().strip().split(",")
                if time.time() - float(raw[1]) < 1.2:   # written in the last ~1s => gesture active
                    v, fresh = int(raw[0]), True
            except Exception:
                nova.swallowed()
            tick += 1
            if not fresh and tick % 20 == 0:            # ~every 1 s when idle (300 ms loaded the Mac for a volume bar)
                rv, rm = self._read_volume()
                if rv is not None:
                    v, muted = rv, rm; self._vol_seen = (rv, rm, time.time())   # _volume_mirror reuses it
            if v is not None and (v, muted) != last:
                self._js("window.novaVolume && window.novaVolume(%d,%s);"
                         % (v, "true" if muted else "false"))
                last = (v, muted)
            time.sleep(0.05)

    def _mac_vitals(self, cpu, mem_pct, bat):
        """Real Mac vitals for the DIAGNOSTICS panel — maps the original labels to live data:
        CORE TEMP = battery temperature (°C), VOLTAGE = battery pack voltage (V) — both read via
        ioreg (no sudo, cached a few sec since they drift slowly); INTEGRITY = live system-health %
        (falls under CPU/memory/thermal load); STATUS = NOMINAL / ELEVATED / CRITICAL / CHARGING."""
        now = time.time()
        cache = getattr(self, "_vit_bat", None)
        if not cache or now - cache[0] > 4:
            temp = volt = None
            try:
                out = subprocess.check_output(["ioreg", "-rn", "AppleSmartBattery"],
                                              text=True, timeout=2)
                mt = re.search(r'"Temperature"\s*=\s*(\d+)', out)
                mv = re.search(r'"Voltage"\s*=\s*(\d+)', out)
                if mt: temp = int(mt.group(1)) / 100.0
                if mv: volt = int(mv.group(1)) / 1000.0
            except Exception:
                nova.swallowed()
            cache = (now, temp, volt)
            self._vit_bat = cache
        _, temp, volt = cache
        integ = 100.0 - cpu * 0.45 - max(0, mem_pct - 55) * 0.6   # load eats "integrity"
        if temp:
            integ -= max(0, temp - 34) * 2.0                     # thermal penalty
        integ = int(max(1, min(100, round(integ))))
        status = ("CHARGING" if bat.get("plug") else
                  "NOMINAL" if integ >= 85 else
                  "ELEVATED" if integ >= 60 else "CRITICAL")
        return {"integrity": integ, "temp": temp, "voltage": volt, "status": status}

    def stats(self):
        """Live system stats for the HUD, polled by the front-end."""
        cpu = psutil.cpu_percent()
        cores = psutil.cpu_percent(percpu=True)
        mem = psutil.virtual_memory()
        # macOS APFS: "/" is the read-only system volume (misleading %); the real
        # user storage is the Data volume, which matches "About This Mac".
        try:
            disk = psutil.disk_usage("/System/Volumes/Data")
        except Exception:
            disk = psutil.disk_usage("/")
        now, net = time.monotonic(), psutil.net_io_counters()
        dt = max(now - self._t, 1e-3)
        down = (net.bytes_recv - self._net.bytes_recv) / dt / 1024
        up = (net.bytes_sent - self._net.bytes_sent) / dt / 1024
        self._net, self._t = net, now
        ncore = psutil.cpu_count() or 1

        bat = {"pct": None, "plug": None}
        try:
            b = psutil.sensors_battery()
            if b:
                bat = {"pct": round(b.percent), "plug": bool(b.power_plugged)}
        except Exception:
            nova.swallowed()
        try:
            load1 = round(os.getloadavg()[0], 2)
        except Exception:
            load1 = 0
        top = {"name": "—", "cpu": 0}
        try:
            best = None
            for p in psutil.process_iter(["name"]):
                try: c = p.cpu_percent()
                except (psutil.AccessDenied, psutil.NoSuchProcess): continue   # kernel_task etc. aborted the whole scan
                if best is None or c > best[1]:
                    best = (p.info.get("name") or "?", c)
            if best:
                top = {"name": best[0][:16], "cpu": round(best[1] / ncore)}
        except Exception:
            nova.swallowed()

        return {"cpu": round(cpu), "cores": [round(c) for c in cores], "ncore": ncore,
                "mem": round(mem.percent), "mem_gb": round((mem.total - mem.available) / 1024**3, 1),   # matches mem.percent (macOS "used" undercounts)
                "mem_tot": round(mem.total / 1024**3),
                "swap": round(psutil.swap_memory().percent),
                "claude": nova.claude_usage(),   # HUD token bar
                "disk": round(disk.percent), "disk_free": round(disk.free / 1024**3),
                "disk_tot": round(disk.total / 1024**3),
                "down": round(down), "up": round(up),
                "bat": bat, "uptime": int(time.time() - psutil.boot_time()),
                "procs": len(psutil.pids()), "load": load1, "top": top,
                "wifi": self._wifi(),
                "vitals": self._mac_vitals(cpu, mem.percent, bat),
                "car": {**self._car_data, "fresh": (time.time() - self._car_data["ts"]) < 12},
                "iot": {**self._iot_data, "fresh": (time.time() - self._iot_data["ts"]) < 12}}

    def hud(self):
        """Cheap state for nova_hud.html (stats() walks every process -- too heavy to poll)."""
        now = time.time()
        if now - getattr(self, "_bulb_ts", 0) > 10:            # WiZ UDP round-trip: at most every 10 s
            self._bulb_ts = now
            try: import wiz; self._bulb_desc = wiz.describe(); self._bulb = None if self._bulb_desc is None else ("off" if self._bulb_desc == "OFF" else "on")
            except Exception: self._bulb = self._bulb_desc = None
        bat = {"pct": None, "plug": None}
        try:
            b = psutil.sensors_battery()
            if b: bat = {"pct": round(b.percent), "plug": bool(b.power_plugged)}
        except Exception: nova.swallowed()
        return {"iot": {**self._iot_data, "fresh": (now - self._iot_data["ts"]) < 12}, "bat": bat,
                "hub": True if nova.IS_HUB else getattr(self, "_hub_app_on", None), "bulb": getattr(self, "_bulb", None), "bulb_desc": getattr(self, "_bulb_desc", None)}

    def wall(self):
        """Wall HUD extras: weather (wttr.in, 15 min cache), last device commands, next timed routine, night flag."""
        now = time.time()
        if now - getattr(self, "_wx_ts", 0) > 900:
            self._wx_ts = now
            try:
                j = json.loads(subprocess.run(["curl", "-s", "-m", "10", "https://wttr.in/?format=j1"],   # curl: hub python lacks CA certs
                                              capture_output=True, timeout=15).stdout)
                c, d = j["current_condition"][0], j["weather"][0]
                self._wx = {"temp": c["temp_C"], "cond": c["weatherDesc"][0]["value"], "hi": d["maxtempC"], "lo": d["mintempC"],
                            "rain": max(int(h.get("chanceofrain", 0)) for h in d["hourly"]), "wind": c["windspeedKmph"],
                            "dir": c["winddir16Point"], "place": j["nearest_area"][0]["areaName"][0]["value"]}
            except Exception as e:
                self._wx_ts = now - 780                       # retry in ~2 min
                print("[wall] weather:", e, flush=True)
        nxt = None
        try:
            rs = json.load(open(self.ROUTINES)); t = datetime.datetime.now()
            for k, r in rs.items():   # ponytail: ignores 'days' -- fine while every timed routine is daily
                if isinstance(r, dict) and r.get("at"):
                    h, m = map(int, r["at"].split(":")); at = t.replace(hour=h, minute=m, second=0)
                    if at <= t: at += datetime.timedelta(days=1)
                    if not nxt or at < nxt[1]: nxt = (k, at)
        except Exception: nova.swallowed()
        lr = getattr(self, "_last_routine", None)
        strips = None
        try:
            import urllib.request
            strips = json.load(urllib.request.urlopen("http://localhost:8099/state", timeout=0.3)).get("strips")
        except Exception: nova.swallowed()
        return {"wx": getattr(self, "_wx", None), "dev": nova.dev_last(), "strips": strips,
                "ac": self._iot_data.get("ac_full"), "projector": self._iot_data.get("projector"),
                "next": [nxt[0].replace("_", " ").upper(), nxt[1].strftime("%H:%M")] if nxt else None,
                "night": bool(lr and lr[0] == "goodnight" and now - lr[1] < 10 * 3600)}

    def _wifi(self):
        """WiFi SSID + signal % (cached ~12s; querying is slow)."""
        now = time.time()
        if hasattr(self, "_wifi_cache") and now - getattr(self, "_wifi_t", 0) < (600 if nova.IS_HUB else 60):   # system_profiler takes ~3 s of CPU
            return self._wifi_cache
        info = {"ssid": "—", "signal": 0, "up": False}
        try:
            sp = subprocess.run(["system_profiler", "SPAirPortDataType"],
                                capture_output=True, text=True, timeout=10).stdout
            idx = sp.find("Current Network Information:")
            if idx >= 0:
                block = sp[idx:idx + 500]
                for ln in block.splitlines()[1:]:      # SSID = first indented "Name:" line
                    t = ln.strip()
                    if t.endswith(":") and len(t) > 1 and not t.startswith(("PHY", "Channel", "Signal", "Security", "Network")):
                        info["ssid"] = t[:-1]
                        info["up"] = True
                        break
                m = re.search(r"Signal\s*/\s*Noise:\s*(-?\d+)", block)  # RSSI -> % (‑30 great … ‑90 poor)
                if m:
                    info["signal"] = max(0, min(100, round((int(m.group(1)) + 90) / 60 * 100)))
                    info["up"] = True
        except Exception:
            nova.swallowed()
        self._wifi_cache, self._wifi_t = info, now
        return info

    # ---------- proactive presence ----------
    def status_brief(self):
        """Spoken boot report, NOVA-style."""
        h = time.localtime().tm_hour
        part = "morning" if h < 12 else "afternoon" if h < 18 else "evening"
        try:
            cpu = round(psutil.cpu_percent(interval=0.3))
            mem = round(psutil.virtual_memory().percent)
            b = psutil.sensors_battery()
            bat = ("battery at %d%%%s" % (round(b.percent), " and charging" if b and b.power_plugged else "")) if b else ""
        except Exception:
            cpu, mem, bat = 0, 0, ""
        name = self.memory.get("name", "sir")
        parts = ["Good %s, %s. All systems online." % (part, name),
                 "Processor at %d percent, memory at %d percent%s." % (cpu, mem, ", " + bat if bat else ""),
                 "How may I be of service?"]
        brief = " ".join(parts)
        self._js('window.novaSay && window.novaSay(' + json.dumps(brief) + ');')   # full report stays on the HUD
        self.speak(parts[0])                         # spoken: just the greeting (the full report was too long)

    def _monitor(self):
        """Watch the system and speak up proactively (deduped)."""
        while True:
            time.sleep(60)
            self._select_input_mic()      # re-follow the lavalier if it was (un)plugged since last check
            if self._say and self._say.poll() is None:
                continue
            try:
                b = psutil.sensors_battery()
                lvl = next((t for t in (5, 10, 20) if b and not b.power_plugged and b.percent <= t), None)
                if lvl and lvl < self._alerted.get("bat", 101):      # warn at 20, again at 10 and 5
                    self._alerted["bat"] = lvl
                    msg = "Sir, battery is at %d percent. %s" % (round(b.percent), "Please plug in the charger now."
                          if lvl <= 10 else "You may wish to connect a charger.")
                    if lvl <= 10:                                    # urgent: speaks even in good-night quiet mode
                        self._js('window.novaSay && window.novaSay(' + json.dumps(msg) + ');'); self.speak(msg)
                    else:
                        self._proactive(msg)
                    continue
                if b and b.power_plugged:
                    self._alerted["bat"] = 101
                # (no memory-pressure nagging — macOS manages it, and it oscillated ~85-92% and kept re-firing)
                # room climate — Nova notices the real sensor and speaks up (deduped, only when fresh)
                io = self._iot_data
                fresh = io.get("temp") is not None and (time.time() - io.get("ts", 0) < 30)
                if fresh:
                    t = io["temp"]
                    if t >= 30 and not self._alerted.get("hot"):
                        self._alerted["hot"] = True
                        self._proactive("It's getting rather warm in here, sir — %.0f degrees. Shall I do something about it?" % t)
                    elif t <= 26:
                        self._alerted["hot"] = False
                    if t <= 16 and not self._alerted.get("cold"):
                        self._alerted["cold"] = True
                        self._proactive("Rather chilly in here, sir — only %.0f degrees." % t)
                    elif t >= 19:
                        self._alerted["cold"] = False
            except Exception:
                nova.swallowed()

    def _proactive(self, text):
        if not self._auto_on:                              # asleep (good night paused automations): don't speak up unasked
            print("[quiet] held: %s" % text[:60], flush=True); return
        self._js('window.novaSay && window.novaSay(' + json.dumps(text) + ');')
        self.speak(text)


def main():
    # single-instance lock via a local file lock (no network port -> nothing listening to attack)
    import fcntl
    global _LOCK_FH
    _LOCK_FH = open(os.path.expanduser("~/anish-ai/.nova.lock"), "w")
    try:
        fcntl.flock(_LOCK_FH, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except OSError:
        print("[nova] another instance is already running — exiting", flush=True)
        return
    api = Api()
    if DISPLAY:        # biggest screen = the external monitor (the hub's own panel is broken)
        scr = max(webview.screens, key=lambda s: s.width * s.height) if webview.screens else None
        # kiosk: a borderless window over the whole screen at screen-saver level (above Dock, menu bar,
        # notification banners and every other app), with app switching disabled while we're active
        webview.create_window("Nova", url=os.path.join(os.path.dirname(HTML), "nova_wall.html"), js_api=api, frameless=True,
                              x=scr.x if scr else 0, y=scr.y if scr else 0, width=scr.width if scr else 1920,
                              height=scr.height if scr else 1080, screen=scr, background_color="#050302")
    elif not HEADLESS: webview.create_window("Nova", url=HTML, js_api=api,
                          width=1120, height=740, min_size=(900, 600),
                          background_color="#020608")

    def _kiosk():
        """Pin the wall HUD over everything. `touch /tmp/nova_kiosk_off` on the hub releases it (to use the hub)."""
        import AppKit
        from PyObjCTools import AppHelper
        off = os.path.exists("/tmp/nova_kiosk_off")
        def apply():
            try:
                w = webview.windows[0].native
                if not w: return
                app = AppKit.NSApplication.sharedApplication()
                if off:
                    app.setPresentationOptions_(0); w.setLevel_(AppKit.NSNormalWindowLevel); w.orderOut_(None); return   # hide HUD -> desktop
                w.setFrame_display_(w.screen().frame(), True)
                w.setLevel_(AppKit.NSScreenSaverWindowLevel)
                w.orderFrontRegardless()
                w.setCollectionBehavior_(AppKit.NSWindowCollectionBehaviorCanJoinAllSpaces | AppKit.NSWindowCollectionBehaviorStationary)
                app.activateIgnoringOtherApps_(True)
                app.setPresentationOptions_(AppKit.NSApplicationPresentationHideDock | AppKit.NSApplicationPresentationHideMenuBar
                                            | AppKit.NSApplicationPresentationDisableProcessSwitching
                                            | AppKit.NSApplicationPresentationDisableHideApplication
                                            | AppKit.NSApplicationPresentationDisableAppleMenu)
            except Exception as e:
                print("[kiosk]", e, flush=True)
        AppHelper.callAfter(apply)

    if DISPLAY:        # monitor shared via HDMI switch: when it comes back to the hub, relaunch so the HUD
        def _screen_watch():   # reopens fullscreen on it (launchd KeepAlive restarts us in ~20 s)
            import ctypes
            cg = ctypes.CDLL("/System/Library/Frameworks/CoreGraphics.framework/CoreGraphics")
            def n():      # the set of active display ids: with the broken internal panel, switching the HDMI
                ids = (ctypes.c_uint32 * 8)(); c = ctypes.c_uint32(0)   # back can swap internal -> external at the
                cg.CGGetActiveDisplayList(8, ids, ctypes.byref(c))       # SAME count, so compare ids, not the count
                return tuple(sorted(ids[:c.value]))
            last, k = n(), 0
            while True:
                time.sleep(5)
                k += 1
                if k % 2 == 1: _kiosk()          # every 10 s: re-take the screen if anything got in front
                now = n()
                new = [d for d in now if d not in last and not cg.CGDisplayIsBuiltin(d)]   # an EXTERNAL display appeared
                if new:            # (switching away brings back the broken internal panel -> ignore that)
                    print("[display] monitor back %s -> relaunching HUD" % (now,), flush=True); time.sleep(3); os._exit(0)
                last = now
        threading.Thread(target=_screen_watch, daemon=True).start()

    def _autostart():          # always-on: begin listening a moment after the window loads
        time.sleep(2.0)
        if WORKER:            # hub: devices + automations only; the Mac's Nova does the talking
            threading.Thread(target=api._automation_loop, daemon=True).start()
            return
        try:
            if ON_SENSES: api.set_handsfree(True)   # START LISTENING FIRST — never let a later step block it
        except Exception:
            nova.swallowed()
        if nova.IS_HUB:       # timed routines, sensor rules + room guard live on the hub only (else they'd fire twice)
            threading.Thread(target=api._automation_loop, daemon=True).start()
            threading.Thread(target=nova.ensure_panel, daemon=True).start()   # strips' BLE server, survives hub reboots
            threading.Thread(target=api._guard_loop, daemon=True).start()
        try:  # only un-strand a low output volume; never change the user's chosen audio device
            v = subprocess.run(["osascript", "-e", "output volume of (get volume settings)"],
                               capture_output=True, text=True, timeout=5).stdout.strip()   # timeout: never hang boot
            if v.isdigit() and int(v) < 25:
                subprocess.run(["osascript", "-e", "set volume output volume 55"], capture_output=True, timeout=5)
        except Exception:
            nova.swallowed()
        try:
            time.sleep(1.5)
            if not nova.IS_HUB: api.status_brief()   # NOVA-style spoken boot report (the Mac talks, not the hub)
        except Exception:
            nova.swallowed()
        threading.Thread(target=api._monitor, daemon=True).start()   # proactive alerts
    if HEADLESS and not DISPLAY:   # hub (broken screen): no window; UI calls fail soft, confirm dialogs auto-deny
        _autostart()
        threading.Event().wait()
    threading.Thread(target=_autostart, daemon=True).start()
    def _dock_icon():          # Mac: the process is Python.app, so set Nova's own Dock icon (app/nova_icon.png)
        try:
            import AppKit
            img = AppKit.NSImage.alloc().initWithContentsOfFile_(os.path.join(os.path.dirname(HTML), "nova_icon.png"))
            from PyObjCTools import AppHelper                       # AppKit wants the main thread
            if img: AppHelper.callAfter(AppKit.NSApplication.sharedApplication().setApplicationIconImage_, img)
        except Exception as e:
            print("[ui] dock icon:", str(e)[:60], flush=True)
    webview.start(_dock_icon if not nova.IS_HUB else None)


if __name__ == "__main__":
    main()
