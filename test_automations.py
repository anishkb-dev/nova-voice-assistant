import sys, types, time, datetime, json, os
sys.modules["webview"] = types.ModuleType("webview")
sys.path.insert(0, os.path.expanduser("~/anish-ai/app")); sys.path.insert(0, os.path.expanduser("~/anish-ai"))
import nova_app
A = nova_app.Api
class F:  # minimal stand-in for Api: real tick/helpers, recorded side effects
    ROUTINES, AUTOMATIONS = A.ROUTINES, A.AUTOMATIONS
    _AWAY_F = os.path.join(__import__("tempfile").mkdtemp(), ".away")   # own flag files: never the real hub ones
    _AUTO_F = os.path.join(os.path.dirname(_AWAY_F), "auto_state.json")
    _days_ok, _in_window, _automation_tick = staticmethod(A._days_ok), staticmethod(A._in_window), A._automation_tick
    def __init__(s):
        s._auto_on, s._auto_state, s._ran_today = True, {}, {}
        s._AUTO_F = os.path.join(__import__("tempfile").mkdtemp(), "auto_state.json")   # own rule memory per fake
        s._last_motion_ts = s._motion_end_ts = time.time() - 3600
        s._iot_data = {"online": True, "ts": time.time(), "motion": False, "light": "off", "ac": "off", "temp": 25.0}
        s.fired, s.spoken = [], []
    def _run_routine(s, name, r): s.fired.append(name); return r.get("reply", "")
    def _proactive(s, x): s.spoken.append(x)
    def _day_stats(s, d, t): pass
nova_app.nova.speakable = lambda x: x
import wiz; CUR = []; wiz.state = lambda: CUR[-1]._iot_data["light"]     # the light is the WiZ bulb: stub it with the fake's state
D = datetime.datetime
f = F(); CUR.append(f)
f._automation_tick(D(2026, 11, 6, 19, 0)); assert f.fired == [], f.fired                 # nothing happening
f._iot_data["motion"] = True; f._automation_tick(D(2026, 11, 6, 19, 0))
assert f.fired == ["lights on when I walk in"], f.fired                                    # motion after dark
f._automation_tick(D(2026, 11, 6, 19, 1)); assert len(f.fired) == 1                         # cooldown
f.fired.clear(); f._auto_state.clear(); f._automation_tick(D(2026, 11, 6, 14, 0)); assert f.fired == []  # daytime: no
f._iot_data.update(motion=False, light="on"); f._motion_end_ts = time.time() - 25 * 60
f._automation_tick(D(2026, 11, 6, 15, 0)); assert f.fired == ["lights off when the room is empty"], f.fired
f._automation_tick(D(2026, 11, 6, 15, 1)); assert len(f.fired) == 1                         # once per absence
f.fired.clear(); f._motion_end_ts = time.time() - 40 * 60; f._iot_data.update(temp=29.0, light="off"); f._automation_tick(D(2026, 11, 6, 15, 2))
assert f.fired == [], "AC must not fire when nobody's been around"
f._motion_end_ts = time.time() - 60; f._automation_tick(D(2026, 11, 6, 15, 3))
assert f.fired == ["AC on when hot"] and f.spoken, (f.fired, f.spoken)
f.fired.clear(); f._auto_on = False; f._iot_data.update(motion=True, temp=25.0); f._auto_state.clear()   # AC-when-hot is even_asleep, so cool the room first
f._automation_tick(D(2026, 11, 6, 20, 0)); assert f.fired == [], "paused by goodnight"
f._auto_on = True; f._iot_data["ts"] = time.time() - 600; f._automation_tick(D(2026, 11, 6, 20, 0))
assert f.fired == [], "stale sensor data must not trigger"
import tempfile; F.ROUTINES = tempfile.mktemp(suffix=".json")   # own timed routine: the real file may have none
json.dump({"morning": {"at": "08:00", "days": "weekdays", "steps": []}}, open(F.ROUTINES, "w"))
f._auto_on = False; f._automation_tick(D(2026, 11, 9, 8, 0)); assert f.fired == ["morning"], f.fired   # Mon 08:00
f._automation_tick(D(2026, 11, 9, 8, 0)); assert f.fired == ["morning"]                    # once per day
f.fired.clear(); f._ran_today.clear(); f._automation_tick(D(2026, 11, 7, 8, 0)); assert f.fired == []  # Saturday
assert A._in_window(["22:00", "06:00"], D(2026, 1, 1, 2, 0)) and not A._in_window(["22:00", "06:00"], D(2026, 1, 1, 12, 0))
print("all automation checks passed")
# away mode: never switch the AC on or greet with lights while you're out
g = F(); CUR.append(g); open(g._AWAY_F, "w").write("x"); g._auto_state.clear()
g._iot_data.update(temp=29.0, motion=True); g._motion_end_ts = time.time() - 60
g._automation_tick(D(2026, 11, 6, 19, 0)); assert g.fired == [], ("away", g.fired)
os.remove(g._AWAY_F); print("away checks passed")
# typing at the Mac keeps the room occupied (no lights-off on you) - but not hours after the room last saw you
h = F(); CUR.append(h); h._iot_data.update(light="on", motion=False); h._motion_end_ts = time.time() - 25 * 60
h._mac_active_ts = time.time() - 30; h._automation_tick(D(2026, 11, 6, 15, 0)); assert h.fired == [], ("mac typing", h.fired)
h._motion_end_ts = h._last_motion_ts = time.time() - 200 * 60; h._automation_tick(D(2026, 11, 6, 15, 1))
assert h.fired == ["lights off when the room is empty"], ("laptop left the room", h.fired); print("mac presence checks passed")
# routine phrases: typos match, but questions/reminders/look-alikes must NOT run a routine (2026-11-18 audit)
from nova_automations import Automations as _AU
_au = _AU(); _au.ROUTINES = os.path.join(os.path.dirname(os.path.abspath(__file__)), "routines.json")
_m = lambda t: (_au._match_routine(t.lower()) or ("-",))[0]
for _t, _e in {"good moning": "morning", "goodmorning": "morning", "good nigth": "goodnight", "wake up": "morning",
               "remind me to wake up at 7": "-", "set an alarm to wake up at 6": "-", "make up": "-", "make up a story": "-",
               "tell me a bedtime story": "-", "how do i go to sleep faster": "-", "date night ideas": "-",
               "turn off the lights i'm going to bed": "goodnight", "evening": "evening", "what are my routines": "_list"}.items():
    assert _m(_t) == _e, (_t, _m(_t), _e)
print("routine phrase checks passed")
assert _m("sleep") == "goodnight" and _m("i can't sleep") == "-", "exact-only phrase"
print("exact phrase checks passed")
_tf = os.path.join(__import__("tempfile").mkdtemp(), "r.json")
json.dump({"nudge": {"at": "10:30", "days": "daily", "skip_asleep": True, "skip_when_away": True, "reply": "x", "steps": []}}, open(_tf, "w"))
F.ROUTINES = _tf
k = F(); CUR.append(k); k._auto_on = False; k._automation_tick(D(2026, 11, 10, 10, 30))
assert "nudge" not in k.fired, ("freelance nudge while asleep", k.fired)
k2 = F(); CUR.append(k2); k2._auto_on = True; k2._automation_tick(D(2026, 11, 10, 10, 30))
assert "nudge" in k2.fired, ("freelance nudge when awake", k2.fired); print("timed skip checks passed")
