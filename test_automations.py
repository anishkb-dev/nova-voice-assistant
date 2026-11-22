import sys, types, time, datetime, json, os
sys.modules["webview"] = types.ModuleType("webview")
sys.path.insert(0, os.path.expanduser("~/anish-ai/app")); sys.path.insert(0, os.path.expanduser("~/anish-ai"))
import nova_app
A = nova_app.Api
class F:  # minimal stand-in for Api: real tick/helpers, recorded side effects
    ROUTINES, AUTOMATIONS = A.ROUTINES, A.AUTOMATIONS
    _AWAY_F = os.path.join(__import__("tempfile").mkdtemp(), ".away")   # own flag files: never the real hub ones
    _AUTO_F = os.path.join(os.path.dirname(_AWAY_F), "auto_state.json")
    _STUDY_F = os.path.join(os.path.dirname(_AWAY_F), ".study_mode")
    _days_ok, _in_window, _automation_tick = staticmethod(A._days_ok), staticmethod(A._in_window), A._automation_tick
    def __init__(s):
        s._auto_on, s._auto_state, s._ran_today = True, {}, {}
        s._AUTO_F = os.path.join(__import__("tempfile").mkdtemp(), "auto_state.json")   # own rule memory per fake
        s._last_motion_ts = s._motion_end_ts = time.time() - 3600
        s._iot_data = {"online": True, "ts": time.time(), "motion": False, "light": "off", "ac": "off", "temp": 25.0}
        s.fired, s.spoken = [], []
    def _run_routine(s, name, r, scene=True): s.fired.append(name); return r.get("reply", "")
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
assert _m("submitted") == "clip_submitted" and _m("i submitted it") == "clip_submitted", _m("submitted")
assert _m("i submitted my assignment") != "clip_submitted" and _m("what did i submit") != "clip_submitted"
print("clip phrase checks passed")
_tf = os.path.join(__import__("tempfile").mkdtemp(), "r.json")
json.dump({"nudge": {"at": "10:30", "days": "daily", "skip_asleep": True, "skip_when_away": True, "reply": "x", "steps": []}}, open(_tf, "w"))
F.ROUTINES = _tf
k = F(); CUR.append(k); k._auto_on = False; k._automation_tick(D(2026, 11, 10, 10, 30))
assert "nudge" not in k.fired, ("freelance nudge while asleep", k.fired)
k2 = F(); CUR.append(k2); k2._auto_on = True; k2._automation_tick(D(2026, 11, 10, 10, 30))
assert "nudge" in k2.fired, ("freelance nudge when awake", k2.fired); print("timed skip checks passed")

# --- privacy switch: camera/mic off sticks, mic on keeps a single muted noisy mic ---
import tempfile as _tf, nova as _nv
_d = _tf.mkdtemp(); _nv.CAM_OFF_F, _nv.MIC_MUTE_F = os.path.join(_d, "cam"), os.path.join(_d, "mute")
_hub, _gc = _nv.IS_HUB, _nv.gesture_control
_nv.IS_HUB = True; _calls = []
_nv.gesture_control = lambda a="start": _calls.append(a) or ""
open(_nv.MIC_MUTE_F, "w").write("192.168.68.104\n")
_nv.camera_mic("both", "off")
assert os.path.exists(_nv.CAM_OFF_F) and set(open(_nv.MIC_MUTE_F).read().split()) == {"*", "192.168.68.104"} and _calls == ["stop"]
_nv.gesture_control = _gc
assert "switched off" in _nv.gesture_control("start")          # auto-starts are blocked while off
_nv.gesture_control = lambda a="start": _calls.append(a) or ""
_nv.camera_mic("both", "on")
assert not os.path.exists(_nv.CAM_OFF_F) and open(_nv.MIC_MUTE_F).read().split() == ["192.168.68.104"] and _calls[-1] == "start"
_nv.camera_mic("mic", "off"); _nv.camera_mic("mic", "on")
assert open(_nv.MIC_MUTE_F).read().split() == ["192.168.68.104"]
_nv.IS_HUB, _nv.gesture_control = _hub, _gc
print("privacy switch checks passed")

# --- IA-2 study week: freelance nudge silent until Wed 25 Nov 11:00, then back; late exam reminders dropped ---
_rt = os.path.join(__import__("tempfile").mkdtemp(), "r.json"); F.ROUTINES = _rt
json.dump({"freelance_online": {"at": "10:30", "days": "daily", "reply": "x", "steps": []}}, open(_rt, "w"))
k3 = F(); CUR.append(k3); k3._auto_on = True; k3._automation_tick(D(2026, 11, 23, 10, 30))
assert "freelance_online" not in k3.fired, ("nudge during study week", k3.fired)
k4 = F(); CUR.append(k4); k4._auto_on = True; k4._automation_tick(D(2026, 11, 26, 10, 30))
assert "freelance_online" in k4.fired, ("nudge back after exams", k4.fired)
import nova as _nv2, time as _t2
_spoke = []; _sr = _nv2._speak_reminder; _nv2._speak_reminder = _spoke.append
_rf = _nv2._REM_F; _nv2._REM_F = os.path.join(__import__("tempfile").mkdtemp(), "rem.json")
_nv2._schedule(_t2.time() - 3600, "late exam", banner=False, stale=1800)    # an hour late -> silent
_nv2._schedule(_t2.time() - 60, "slightly late", banner=False, stale=1800)  # a minute late -> spoken
_t2.sleep(0.5)
assert _spoke == ["slightly late"], _spoke
_nv2._speak_reminder, _nv2._REM_F = _sr, _rf
print("study week checks passed")

# --- "Nova, submitted": flips only the last-announced post's submitted flag, keeps the file's layout ---
import shutil as _sh, nova as _nv3
_cd = __import__("tempfile").mkdtemp(); _cdir = _nv3.CLIP_DIR; _nv3.CLIP_DIR = _cd
open(os.path.join(_cd, "posts.json"), "w").write('[\n {"id": 1, "at": "x", "campaign": "SEGA Metaphor", "networks": ["YT"], "submitted": false},\n {"id": 2, "at": "y", "campaign": "Call of Duty DMZ", "networks": ["IG"], "submitted": false}\n]\n')
assert "Nothing waiting" in _nv3.clip_submitted()
json.dump({"1": {"first": 100, "repeat": True}, "2": {"first": 200, "repeat": False}}, open(os.path.join(_cd, ".announced.json"), "w"))
assert "Call of Duty" in _nv3.clip_submitted()
_after = open(os.path.join(_cd, "posts.json")).read()
assert '"id": 2, "at": "y", "campaign": "Call of Duty DMZ", "networks": ["IG"], "submitted": true}' in _after and '"id": 1' in _after and _after.count("true") == 1, _after
assert "SEGA" in _nv3.clip_submitted() and "Nothing waiting" in _nv3.clip_submitted()
_nv3.CLIP_DIR = _cdir
print("clip submitted checks passed")

# --- "mic off" also switches off the hub's own mic (HANDSFREE hook), "mic on" brings it back ---
import nova as _nv4, tempfile as _tf4
_hf = []; _nv4.HANDSFREE = _hf.append; _h4 = _nv4.IS_HUB; _nv4.IS_HUB = True
_m4, _c4 = _nv4.MIC_MUTE_F, _nv4.CAM_OFF_F; _d4 = _tf4.mkdtemp(); _nv4.MIC_MUTE_F, _nv4.CAM_OFF_F = os.path.join(_d4, "m"), os.path.join(_d4, "c")
_nv4.camera_mic("mic", "off"); assert _hf == [False] and _nv4.mics_off()
_nv4.camera_mic("mic", "on"); assert _hf == [False, True] and not _nv4.mics_off()
_nv4.HANDSFREE, _nv4.IS_HUB, _nv4.MIC_MUTE_F, _nv4.CAM_OFF_F = None, _h4, _m4, _c4
print("hub mic privacy checks passed")

# --- wake alarm: rings + reads, keeps ringing until "good morning", then reads again; skips ring once awake ---
import nova as _nv5, tempfile as _tf5, threading as _th5, time as _t5
_d5 = _tf5.mkdtemp(); _sv5 = (_nv5.ALARM_F, _nv5.ALARM_ACK_F, _nv5.ALARM_WAV, _nv5.SNOOZE, _nv5._osa)
_nv5.ALARM_F, _nv5.ALARM_ACK_F = os.path.join(_d5, "on"), os.path.join(_d5, "ack")
_nv5.ALARM_WAV, _nv5.SNOOZE, _nv5._osa = "/nonexistent.wav", 1, lambda s: "50"
_said5 = []
_w5 = _th5.Thread(target=_nv5.wake, args=("Your clip is live.", _said5.append)); _w5.start()
_t5.sleep(2.5); assert os.path.exists(_nv5.ALARM_F) and _said5 == ["Your clip is live."], _said5   # still ringing
assert _nv5.AWAKE_RE.search("uh good morning") and _nv5.AWAKE_RE.search("I'm awake") and not _nv5.AWAKE_RE.search("morning news")
assert _nv5.alarm_off("test"); _w5.join(5); assert not _w5.is_alive() and not os.path.exists(_nv5.ALARM_F)
assert _said5[-1] == "Good morning, sir. Your clip is live.", _said5
_nv5.wake("Ten minutes left.", _said5.append); assert _said5[-1] == "Ten minutes left."       # awake now: no ring
# answering while the room is in night mode runs Morning; answered in day mode -> doesn't
_sent5, _sv5b = [], (_nv5.ASLEEP_F, _nv5._hub_send, _nv5.AWAKE_FOR)
_nv5.ASLEEP_F, _nv5._hub_send, _nv5.AWAKE_FOR = os.path.join(_d5, "asleep"), lambda *a: _sent5.append(a), 0
for _night in (True, False):
    if _night: open(_nv5.ASLEEP_F, "w").close()
    elif os.path.exists(_nv5.ASLEEP_F): os.remove(_nv5.ASLEEP_F)
    _w5 = _th5.Thread(target=_nv5.wake, args=("x", _said5.append)); _w5.start(); _t5.sleep(1.5)
    _nv5.alarm_off("test"); _w5.join(5)
    assert _sent5 == [("routine", "morning")], _sent5          # once, from the night-mode round only
_nv5.ASLEEP_F, _nv5._hub_send, _nv5.AWAKE_FOR = _sv5b
_nv5.ALARM_F, _nv5.ALARM_ACK_F, _nv5.ALARM_WAV, _nv5.SNOOZE, _nv5._osa = _sv5
print("wake alarm checks passed")

# --- a 2nd tap on a routine within 30 s doesn't run it again; privacy switch blocks every camera opener ---
import types as _ty, time as _tm
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "app"))
import nova_automations as _na, cam_presence as _cp
_o = _ty.SimpleNamespace(_routine_step=lambda st: "", _safe_step=lambda n, st: None, _later_edit=lambda f: f([]))
_rr = lambda name: _na.Automations._run_routine(_o, name, {"reply": "Morning.", "steps": []})
assert _rr("morning") == "Morning." and _rr("morning") == "Already on it, sir." and _rr("focus") == "Morning."
_o._last_routine = ("morning", _tm.time() - 31); assert _rr("morning") == "Morning."
# a new mode stops the old one's leftover steps and its timed (60-min) steps
import threading as _th
_ev, _ran, _jobs = _th.Event(), [], [{"due": 1}]
_o._safe_step = lambda n, st: (_ran.append((n, st["do"])), n == "goodnight" and _ev.wait(2))
_o._later_edit = lambda f: _jobs.__setitem__(slice(None), f(list(_jobs)))
_na.Automations._run_routine(_o, "goodnight", {"steps": [{"do": "a"}, {"do": "b"}]}); _tm.sleep(0.1)
_na.Automations._run_routine(_o, "movie", {"steps": [{"do": "c"}]}); _ev.set(); _tm.sleep(0.3)
assert ("goodnight", "b") not in _ran and ("movie", "c") in _ran and _jobs == [], (_ran, _jobs)
_cf = os.path.expanduser("~/anish-ai/.camera_off"); _had = os.path.exists(_cf)
open(_cf, "a").close()
try: _cp.pick_camera(); raise AssertionError("camera opened with privacy off")
except PermissionError: pass
finally:
    if not _had: os.remove(_cf)
print("routine debounce + camera privacy checks passed")

# --- morning Telegram overview: counts per kind, never the texts (owner 2026-11-22) ---
import nova as _nvt
_r = [{"text": t} for t in ("Table mic quiet", "Bed mic back", "Just posted: clip 3", "Contra: new job",
                             "Day recap: 4 clips", "Table mic quiet", "Something odd")]
_o = _nvt._tg_spoken(_r); print(_o)
assert _o.startswith("Overnight, your Telegram bot sent 6 messages: 2 device alerts") and "1 clip update" in _o \
    and "1 freelance message" in _o and "1 day recap" in _o and "1 other message" in _o and "Contra" not in _o, _o
assert _nvt._tg_spoken([]) == ""; print("tg overview ok")

# --- relay board unplugged: fan/plug commands say so instead of a fake "turned on" ---
assert "unplugged" in _nvt.iot_control("fan", "on") and "unplugged" in _nvt.iot_control("plug", "off"); print("relay msg ok")

# --- study mode: flag quiets freelance nags; routine has breaks every 50 min, off routine clears them ---
k5 = F(); CUR.append(k5); k5._auto_on = True; open(F._STUDY_F, "w").close()
k5._automation_tick(D(2026, 11, 26, 10, 30)); os.remove(F._STUDY_F)
import json as _j; _R = _j.load(open(A.ROUTINES))
_st = _R["focus"]["steps"]
assert [x["after_min"] for x in _st if x["do"] == "say"] == [50, 60, 110, 120, 180] and {"do": "study", "arg": "on"} in _st
assert {"do": "study", "arg": "off"} in _R["study_off"]["steps"] and "stop studying" in _R["study_off"]["phrases"]
print("study mode ok")

# --- longest phrase wins: "study mode off" must stop, not start, study mode ---
_m = F(); _m.ROUTINES = A.ROUTINES; _m.NOT_ROUTINE = A.NOT_ROUTINE; _m._fuzzy_routine = A._fuzzy_routine.__get__(_m)
_mr = lambda s: A._match_routine(_m, s)
assert _mr("nova study mode off")[0] == "study_off" and _mr("study mode")[0] == "focus" and _mr("i'm done studying")[0] == "study_off"
assert _mr("good night")[0] == "goodnight" and _mr("good evening")[0] == "evening"
print("phrase match ok")

# --- think like the user: real ways the owner talks to Nova -> routine (or "-" = not a routine, goes to the brain) ---
USER_SAYS = {"nova good night": "goodnight", "good nite": "goodnight", "im going to sleep": "goodnight", "gud morning": "morning",
    "im up": "morning", "i'm leaving": "leaving", "im back home": "home", "movie time": "movie", "lets study": "focus",
    "i need to focus": "focus", "start studying": "focus", "work mode": "focus", "stop studying": "study_off",
    "study mode off": "study_off", "clip submitted": "clip_submitted",
    "remind me to study at 5": "-", "how do i focus better": "-", "what is study mode": "-", "play study music": "-",
    "set a timer for study": "-", "good night story": "-", "why is the light purple": "-", "i can't sleep": "-",
    "i'm going to the shop": "-", "ac off": "-"}
_bad = {u: (want, (_mr(u) or ["-"])[0]) for u, want in USER_SAYS.items() if (_mr(u) or ["-"])[0] != want}
assert not _bad, _bad
print("user phrase sim ok (%d)" % len(USER_SAYS))

# --- fast mute: flag toggles; the kill pattern hits Nova's speech, never music or the alarm ---
import re as _re, tempfile as _tf2
_nm = _nvt; _saved = (_nm.IS_HUB, _nm.VOICE_MUTE_F, _nm.subprocess.run); _ran = []
_nm.IS_HUB, _nm.VOICE_MUTE_F = True, os.path.join(_tf2.mkdtemp(), ".voice_mute")
_nm.subprocess.run = lambda cmd, **k: _ran.append(cmd)
try:
    assert _nm.nova_mute("on") == "Nova muted." and _nm.voice_muted()
    assert _nm.nova_mute("toggle") == "Nova unmuted, sir." and not _nm.voice_muted()
    _pat = [c for c in _ran if c[0] == "pkill"][0][2]
    assert _re.search(_pat, "afplay /tmp/nova_k_2.wav") and _re.search(_pat, "afplay -v 1.0 /tmp/nova_tts_0.mp3")
    assert not _re.search(_pat, "afplay -v 0.6 /tmp/nova_track.wav") and not _re.search(_pat, "afplay /Users/x/anish-ai/alarm.wav")
finally:
    _nm.IS_HUB, _nm.VOICE_MUTE_F, _nm.subprocess.run = _saved
import light_panel as _lp
assert _lp.ACT_OK["nova_mute"] == "on|off" and not hasattr(_lp, "DECK")   # one deck: the hub page
_hp = open(os.path.join(os.path.dirname(os.path.abspath(__file__)), "hub_page.html")).read()
assert "act('nova_mute'" in _hp and "btn-nova-mute" in _hp
print("fast mute ok")
