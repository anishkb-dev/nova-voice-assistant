"""Routines (routines.json), delayed steps (.later.json), sensor rules (automations.json), sleep/away flags.
Mixin of nova_app.Api (split out of nova_app.py verbatim, cleanup fix 10, 2026-11-17)."""
from nova_common import *   # noqa: F403 - the constants/helpers nova_app always had at module level


class Automations:

    ROUTINES = os.path.expanduser("~/anish-ai/routines.json")

    def _match_routine(self, low):
        """(name, routine) if the utterance contains one of a routine's phrases. Re-reads the file so edits apply live."""
        try:
            rs = json.load(open(self.ROUTINES))
        except Exception as e:
            print("[routine] can't read routines.json:", e, flush=True); return None
        if re.match(r"^\W*(?:hey\s+|ok\s+|okay\s+|ask\s+|tell\s+)?(?:claude|claud|clod|cloud|clawed)\b", low):
            return None                                   # "Claude, good night" is for Claude, not the routine
        text = " " + re.sub(r"[^a-z' ]", " ", low.replace("’", "'")) + " "
        if re.search(r"\b(list|what)\b.*\broutines?\b", text):
            names = [k for k in rs if not k.startswith("_")]
            return ("_list", {"reply": "Your routines are: " + ", ".join(names) + ".", "steps": []})
        exact = {n.lower(): (n, r) for n, r in rs.items() if not n.startswith("_")}
        exact.update({p.lower(): (n, r) for n, r in rs.items() if not n.startswith("_") for p in r.get("exact", [])})   # "sleep"
        if text.strip() in exact: return exact[text.strip()]          # "Nova, evening" = the routine
        if self.NOT_ROUTINE.search(text): return None                   # "remind me to wake up", "bedtime story", "how do I go to sleep"
        for name, r in rs.items():
            if name.startswith("_"):
                continue
            if text.strip() == name.lower() or any(" %s " % p.lower() in text for p in r.get("phrases", [])):   # "Nova, evening" = the routine
                return (name, r)
        return self._fuzzy_routine(rs, text.split())

    # a question, a reminder/alarm or a request that merely contains a routine phrase is not that routine (2026-11-18)
    NOT_ROUTINE = re.compile(r"\b(remind|reminder|alarm|timer|story|stories|ideas?|how|why|what|when|who|explain|meaning|song|music)\b")

    FUZZY = 0.85   # calibration knob: typos score 0.87-0.96 ("good moning"); different routines <= 0.80 (good evening/morning 0.75)

    @classmethod
    def _fuzzy_routine(cls, rs, words):
        """Typo-tolerant pass: 'good moning', 'gud morning', 'goodmorning' -> morning. Compares each phrase with
        word windows of the same length (+-1 word, so 'goodmorning' meets 'good morning')."""
        from difflib import SequenceMatcher
        best = (cls.FUZZY, None)
        if len(words) > 4: return None                    # typo match only for a short command that IS the phrase
        for name, r in rs.items():
            if name.startswith("_"): continue
            for p in r.get("phrases", []):
                p = p.lower()
                if len(p) < 6: continue                       # too short to tell typo from another word ("im up")
                n = len(p.split())
                for k in {max(1, n - 1), n, n + 1}:
                    for i in range(len(words) - k + 1):
                        w = " ".join(words[i:i + k])
                        if w[:1] != p[:1]: continue           # typos keep the first letter; "make up" is not "wake up"
                        sc = SequenceMatcher(None, w, p).ratio()
                        if sc > best[0]: best = (sc, (name, r))
        return best[1]

    # Routine brightness is capped by the hour (calibration knob): (from_hour, max %), latest match wins.
    BRIGHT_CAP = [(0, 35), (6, 85), (18, 100), (21, 60), (23, 35)]

    @classmethod
    def _time_cap(cls, arg):
        """'brightness 100' at 22:00 -> 'brightness 60'. Lower values (goodnight fade) pass through."""
        import re
        m = re.fullmatch(r"brightness (\d+)", str(arg))
        if not m: return arg
        h = time.localtime().tm_hour
        cap = [c for f, c in cls.BRIGHT_CAP if h >= f][-1]
        return "brightness %d" % min(int(m.group(1)), cap)

    def _routine_step(self, st):
        do, arg = st.get("do"), st.get("arg")
        if do in ("bulb", "lights"): arg = self._time_cap(arg)
        if do == "ac":     return nova.ac(str(arg), routine=True)   # scheduled steps don't cancel each other
        if do == "lights": return nova.lights(str(arg), mirror=False)   # routines set the bulb themselves: the mirror
                                                     # turned it back on after goodnight's bulb-off (2026-11-16)
        if do == "mic":    return str(self.set_handsfree(arg in (True, "on")))
        if do == "camera": return str(self.set_camera(arg in (True, "on")))
        if do == "bulb":                              # WiZ ceiling bulb (wiz.py), reachable from the Mac and the hub
            import wiz
            r = wiz.bulb(str(arg))
            if "can't reach" in r:                    # a missed UDP reply left the light on after goodnight (2026-11-15)
                time.sleep(2); r = wiz.bulb(str(arg))
            if "can't reach" in r and not nova.IS_HUB:   # last try: the hub, which sits next to the bulb
                nova._hub_send("later", json.dumps({"name": "bulb", "st": {"do": "bulb", "arg": arg, "after_min": 0}}))
                r = "Bulb handed to the hub."
            return r
        if do == "display":                           # the hub's wall screen (only the hub drives it)
            if nova.IS_HUB: subprocess.Popen(["pmset", "displaysleepnow"] if arg == "off" else ["caffeinate", "-u", "-t", "2"])
            else: nova._hub_send("display", arg)
            return "display " + str(arg)
        if do == "away":                              # leaving: no rule may turn the AC on until you're back
            if nova.IS_HUB: self._set_away(arg in (True, "on"))
            else: nova._hub_send("away", "on" if arg in (True, "on") else "off")
            return "away " + str(arg)
        if do == "automations":                       # goodnight pauses sensor rules, morning/home resume them
            self._auto_on = arg in (True, "on")
            if not nova.IS_HUB: nova._hub_send("automations", "on" if self._auto_on else "off")   # they run on the hub
            return "automations " + ("on" if self._auto_on else "paused")
        fn = nova.FUNCS.get(do)
        if not fn:
            return "unknown step %r" % do
        return str(fn(**arg) if isinstance(arg, dict) else fn() if arg is None else fn(arg))

    def _run_routine(self, name, r, scene=True):
        """Spoken steps run now (their results join the reply); the rest run in the background so
        a slow device (BLE strip, IR cloud) never delays the answer. after_min steps are scheduled."""
        lr = getattr(self, "_last_routine", None)         # a 2nd tap while morning is still fetching the weather
        if lr and lr[0] == name and time.time() - lr[1] < 30:    # used to run the whole scene again
            print("[routine] %s again within 30 s -> skipped" % name, flush=True); return "Already on it, sir."
        self._last_routine = (name, time.time())          # wall HUD: goodnight -> night mode
        if name == "morning":     # running Morning (button, voice, Telegram) = you're up: stop a ringing alarm and
            try:                  # mark awake, so no later alarm rings today (owner 2026-11-21)
                nova.alarm_off("morning routine") if nova.IS_HUB else nova._hub_send("awake", "morning routine")
            except Exception: nova.swallowed()
        if scene:   # a new mode replaces the last one: goodnight's leftover steps (and its 60-min AC/projector
            self._scene = gen = getattr(self, "_scene", 0) + 1     # timer) used to keep firing over movie/morning
            self._later_edit(lambda j: [])
        said = [r.get("reply", "Done, sir.")]
        later = []
        for st in r.get("steps", []):
            if st.get("speak") and not st.get("after_min"):
                try: said.append(self._routine_step(st))
                except Exception as e: print("[routine] %s step %s failed: %s" % (name, st.get("do"), e), flush=True)
            else:
                later.append(st)
        def _bg():
            for st in later:
                if scene and self._scene != gen:
                    print("[routine] %s superseded, %d steps dropped" % (name, len(later) - later.index(st)), flush=True); return
                if st.get("after_min") and not nova.IS_HUB:     # the Mac may sleep (lid closed) -> the hub keeps the timer
                    try: nova._hub_send("later", json.dumps({"name": name, "st": st})); continue
                    except Exception as e: print("[routine] hub unreachable, timing locally:", e, flush=True)
                if st.get("after_min"):
                    self._later(name, st)
                else:
                    self._safe_step(name, st)
        threading.Thread(target=_bg, daemon=True).start()
        print("[routine] %s: %d steps" % (name, len(r.get("steps", []))), flush=True)
        return " ".join(x for x in said if x)

    # Delayed routine steps used to live only in Timers: a hub restart at night lost goodnight's
    # AC easing (21 -> 24 -> 25 -> 26), leaving the AC on 21 full fan till morning. Now on disk.
    _LATER_F = os.path.expanduser("~/anish-ai/.later.json")
    LATER_GRACE_MIN = 30          # a step overdue by more than this after a restart is dropped, not run late

    def _later_edit(self, fn):
        with self.__dict__.setdefault("_later_lock", threading.Lock()):
            try: jobs = json.load(open(self._LATER_F))
            except Exception: jobs = []
            jobs = fn(jobs)
            try: json.dump(jobs, open(self._LATER_F, "w"))
            except Exception as e: print("[later] save failed:", e, flush=True)
            return jobs

    def _later(self, name, st, due=None):
        """Run routine step `st` after st['after_min'] minutes; survives restarts (hub)."""
        due = due if due is not None else round(time.time() + float(st.get("after_min", 0)) * 60, 1)
        job = {"due": due, "name": name, "st": st}      # resumed jobs keep their saved due -> no duplicate
        if nova.IS_HUB: self._later_edit(lambda j: j + [job] if job not in j else j)
        def _fire():
            time.sleep(max(0, due - time.time()))
            if nova.IS_HUB and job not in self._later_edit(lambda j: j): return   # already handled
            if nova.IS_HUB: self._later_edit(lambda j: [x for x in j if x != job])
            self._safe_step(name, st)
        threading.Thread(target=_fire, daemon=True).start()

    def _resume_later(self):
        now = time.time()
        for job in self._later_edit(lambda j: j):
            if now - job["due"] > self.LATER_GRACE_MIN * 60:
                print("[later] dropped stale %s %s(%r), %.0f min overdue" % (job["name"], job["st"].get("do"),
                      job["st"].get("arg"), (now - job["due"]) / 60), flush=True)
                self._later_edit(lambda j: [x for x in j if x != job])
            else:
                print("[later] resumed %s %s(%r)" % (job["name"], job["st"].get("do"), job["st"].get("arg")), flush=True)
                self._later(job["name"], job["st"], due=job["due"])

    def _safe_step(self, name, st):
        try:
            print("[routine] %s -> %s(%r): %s" % (name, st.get("do"), st.get("arg"), self._routine_step(st)[:80]), flush=True)
        except Exception as e:
            print("[routine] %s step %s failed: %s" % (name, st.get("do"), e), flush=True)

    # ---- AUTOMATIONS: timed routines ("at" in routines.json) + sensor rules (automations.json) ----
    AUTOMATIONS = os.path.expanduser("~/anish-ai/automations.json")
    _ASLEEP_F = os.path.expanduser("~/anish-ai/.asleep")   # HUB ONLY: exists = good night is on; survives restarts
    _AWAY_F = os.path.expanduser("~/anish-ai/.away")       # HUB ONLY: exists = you left; AC rules can't switch it on

    def _set_away(self, on):
        try:
            if on: open(self._AWAY_F, "w").write(time.strftime("%Y-%m-%d %H:%M"))
            elif os.path.exists(self._AWAY_F): os.remove(self._AWAY_F)
            print("[hub] away", "on" if on else "off", flush=True)
        except Exception as e: print("[hub] away flag failed:", e, flush=True)

    _hub_asleep = False                                     # Mac: mirror of the hub's state (retained MQTT "home/sleep")

    @property
    def _auto_on(self):
        return not os.path.exists(self._ASLEEP_F) if nova.IS_HUB else not self._hub_asleep

    @_auto_on.setter
    def _auto_on(self, on):
        if not nova.IS_HUB:
            self._hub_asleep = not on; return              # caller also sends the hub "automations" job
        try:
            if on: os.remove(self._ASLEEP_F)
            else: open(self._ASLEEP_F, "w").write(time.strftime("%Y-%m-%d %H:%M"))
        except FileNotFoundError:
            pass
        self._pub_sleep()

    # The broker keeps retained messages in RAM only: a hub reboot wiped the AC state, so the
    # temperature rules ("if ac off/on") could never fire. The hub keeps a copy and re-publishes
    # whatever the broker lost. ponytail: a change made while the hub was down (IR remote) isn't
    # seen; the next AC command corrects it.
    _ROOM_F = os.path.expanduser("~/anish-ai/.room_state.json")

    def _save_room_state(self, key, val):
        if not nova.IS_HUB: return
        getattr(self, "_room_seen", set()).add(key)
        try: st = json.load(open(self._ROOM_F))
        except Exception: st = {}
        if st.get(key) != val:
            st[key] = val
            try: json.dump(st, open(self._ROOM_F, "w"))
            except Exception as e: print("[mqtt] room state save failed:", e, flush=True)

    def _restore_room_state(self):
        time.sleep(4)                                     # let the broker's own retained copies arrive first
        try: st = json.load(open(self._ROOM_F))
        except Exception: return
        for key, val in st.items():
            if key not in self._room_seen:
                print("[mqtt] broker lost home/room/%s -> restoring %r" % (key, val), flush=True)
                self._pub_retained("home/room/" + key, val)

    def _pub_sleep(self):
        self._pub_retained("home/sleep", "0" if self._auto_on else "1")

    @staticmethod
    def _pub_retained(topic, payload):
        try:
            c = nova.mqtt_client()
            c.connect(nova._IOT_BROKER, 1883, nova.MQTT_KEEPALIVE); c.loop_start()
            c.publish(topic, payload, qos=1, retain=True).wait_for_publish(3)
            c.disconnect(); c.loop_stop()
        except Exception as e:
            print("[mqtt] publish %s failed:" % topic, e, flush=True)

    # HUB: today's room stats for the good-night recap (nova.night_summary). A "day" starts 06:00,
    # so a 3 AM bedtime still reports the day you just had. Retained on home/hub/daystats.
    _day, _day_pub = {}, 0.0
    _auto_state = {}       # rule name -> {"last": fire ts, "armed": bool}
    _AUTO_F = os.path.expanduser("~/anish-ai/.auto_state.json")
    _ran_today = {}        # timed routine name -> date it last ran
    _motion_end_ts = 0.0   # when the PIR last went quiet (set by _iot_listener)

    @staticmethod
    def _days_ok(days, now):
        wd = now.weekday()
        if not days or days == "daily": return True
        if days == "weekdays": return wd < 5
        if days == "weekends": return wd >= 5
        return ["mon", "tue", "wed", "thu", "fri", "sat", "sun"][wd] in [x[:3].lower() for x in days]

    @staticmethod
    def _in_window(win, now):
        if not win: return True
        a, b, t = win[0], win[1], now.strftime("%H:%M")
        return a <= t < b if a <= b else (t >= a or t < b)      # "22:00"-"06:00" wraps midnight

    def _automation_loop(self):
        import datetime
        while True:
            time.sleep(20)
            try: self._automation_tick(datetime.datetime.now())
            except Exception as e: print("[auto] tick failed:", e, flush=True)

    def _automation_tick(self, now):
        hm, today, t = now.strftime("%H:%M"), now.date(), time.time()
        try: rs = json.load(open(self.ROUTINES))
        except Exception: rs = {}
        for name, r in rs.items():                                   # 1) timed routines
            if name.startswith("_") or not r.get("at"): continue
            if r["at"] == hm and self._ran_today.get(name) != today and self._days_ok(r.get("days"), now):
                if name == "freelance_online" and __import__("exams").study_mode(now):   # IA-2 week: no nags
                    self._ran_today[name] = today; print("[auto] timed routine skipped (study mode):", name, flush=True); continue
                if (r.get("skip_when_away") and os.path.exists(self._AWAY_F)) or (r.get("skip_asleep") and not self._auto_on):
                    self._ran_today[name] = today; print("[auto] timed routine skipped (away/asleep):", name, flush=True); continue
                self._ran_today[name] = today
                print("[auto] timed routine:", name, flush=True)
                self._proactive(nova.speakable(self._run_routine(name, r)))
        asleep = not self._auto_on
        try: rules = json.load(open(self.AUTOMATIONS)).get("rules", [])
        except Exception: return
        d = self._iot_data
        if not d.get("online") or t - d.get("ts", 0) > 120: return  # node offline/stale -> never act on old data
        self._day_stats(d, t)
        moving = bool(d.get("motion"))
        if asleep and moving and 8 <= now.hour < 12:               # forgot "good morning" -> first motion after 8 resumes rules
            # ponytail: PIR can't tell bed-tossing from getting up; raise the start hour if it wakes things too early
            self._auto_on, asleep = True, False
            print("[auto] morning motion -> automations resumed", flush=True)
        try: cam_seen = os.path.getmtime("/tmp/nova_cam_seen")    # hub webcam saw movement (cam_presence.py)
        except OSError: cam_seen = 0
        seen = max(self._last_motion_ts, self._motion_end_ts, cam_seen)
        mac = getattr(self, "_mac_active_ts", 0)   # typing at the Mac counts, but only within 90 min of the room
        # sensors seeing you: it's a laptop, it may have left the room with you (ponytail: mmWave sensor is the real fix)
        last_move = t if moving else max(seen, mac if mac - seen < MAC_PRESENCE_MAX else 0)
        empty_for = t - self.__dict__.setdefault("_seen_move", t)   # how long the room was still before this tick
        self._seen_move = last_move
        if not self._auto_state:                                     # rule memory survives restarts (a restart re-armed
            try: self._auto_state.update(json.load(open(self._AUTO_F)))   # "AC on when hot" and it fired again)
            except Exception: nova.swallowed()
        before = json.dumps(self._auto_state, sort_keys=True)
        if any("light" in ru.get("if", {}) for ru in rules):         # the light is the WiZ bulb, not the dead relay K1
            import wiz
            d = dict(d, light=wiz.state())
        for i, ru in enumerate(rules):                               # 2) sensor rules
            if not ru.get("enabled", True) or not self._in_window(ru.get("between"), now): continue
            if asleep and not ru.get("even_asleep"): continue           # sleep mode pauses all but even_asleep rules
            if os.path.exists(self._AWAY_F) and any(x.get("do") == "ac" and x.get("arg") != "off" for x in ru.get("steps", [])):
                continue                                                # you're out -> never switch the AC on
            if ru.get("skip_when_away") and os.path.exists(self._AWAY_F): continue
            key = ru.get("name", str(i))
            st = self._auto_state.setdefault(key, {"last": 0, "armed": True})
            w = ru.get("when", {})
            if any(d.get(dev) != want for dev, want in ru.get("if", {}).items()): continue   # e.g. {"light": "off"}
            if "present_min" in ru and not asleep and t - last_move > ru["present_min"] * 60: continue   # asleep = you're in bed      # only while you're around
            if t - st["last"] < ru.get("cooldown_min", 0) * 60: continue
            if "motion" in w:                                       # after_empty_min: only on coming back, not
                fire = moving and empty_for >= w.get("after_empty_min", 0) * 60   # on moving about in the room
            elif "no_motion_min" in w:
                if last_move > st["last"]: st["armed"] = True        # you came back -> can fire again
                if os.path.exists(nova.CAM_OFF_F): continue          # camera off = PIR alone, misses you sitting still
                # (2026-11-22 it switched lights + AC off on the owner at the desk) -> "room empty" can't be trusted
                fire = st["armed"] and not moving and t - last_move > w["no_motion_min"] * 60
            elif "temp_above" in w:
                tc = d.get("temp")
                if tc is None: continue
                if tc < w.get("reset_below", w["temp_above"] - 2): st["armed"] = True
                fire = st["armed"] and tc >= w["temp_above"]
            elif "temp_below" in w:
                tc = d.get("temp")
                if tc is None: continue
                if tc > w.get("reset_above", w["temp_below"] + 2): st["armed"] = True
                fire = st["armed"] and tc <= w["temp_below"]
            else:
                continue
            if fire:
                st["last"], st["armed"] = t, False
                print("[auto] rule fired:", key, flush=True)
                said = self._run_routine(key, {"reply": ru.get("say", ""), "steps": ru.get("steps", [])}, scene=False)
                if said: self._proactive(said)
        if json.dumps(self._auto_state, sort_keys=True) != before:
            try: json.dump(self._auto_state, open(self._AUTO_F, "w"))
            except Exception as e: print("[auto] state save failed:", e, flush=True)
