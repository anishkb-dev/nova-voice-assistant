import sys, types, time, datetime, json, os
sys.modules["webview"] = types.ModuleType("webview")
sys.path.insert(0, os.path.expanduser("~/anish-ai/app")); sys.path.insert(0, os.path.expanduser("~/anish-ai"))
import nova_app
A = nova_app.Api
class F:  # minimal stand-in for Api: real tick/helpers, recorded side effects
    ROUTINES, AUTOMATIONS = A.ROUTINES, A.AUTOMATIONS
    _days_ok, _in_window, _automation_tick = staticmethod(A._days_ok), staticmethod(A._in_window), A._automation_tick
    def __init__(s):
        s._auto_on, s._auto_state, s._ran_today = True, {}, {}
        s._last_motion_ts = s._motion_end_ts = time.time() - 3600
        s._iot_data = {"online": True, "ts": time.time(), "motion": False, "light": "off", "temp": 25.0}
        s.fired, s.spoken = [], []
    def _run_routine(s, name, r): s.fired.append(name); return r.get("reply", "")
    def _proactive(s, x): s.spoken.append(x)
    def _day_stats(s, d, t): pass
nova_app.nova.speakable = lambda x: x
import wiz; wiz.state = lambda: f._iot_data["light"]     # the light is the WiZ bulb: stub it with the fake's state
D = datetime.datetime
f = F()
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
