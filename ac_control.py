#!/usr/bin/env python3
"""Control the AC through the HomeMate / Tuya Smart-IR blaster (cloud IR API).

  python3 ac_control.py on|off
  python3 ac_control.py temp 24
  python3 ac_control.py mode cool
  python3 ac_control.py fan high
  python3 ac_control.py status

Jarvis calls ac("on") / ac("temp 24") / ac("mode cool") / ac("status").
Must use Tuya's IR-Control-Hub API — the generic device command returns
success but fires NO IR. Credentials from ~/tinytuya.json (tinytuya wizard).
"""
import os, json, sys

CONF   = os.path.expanduser("~/tinytuya.json")
_ids   = json.load(open(CONF)) if os.path.exists(CONF) else {}
IR     = _ids.get("infrared_id", "")   # Smart-IR hub id — stored in ~/tinytuya.json (git-ignored, outside repo)
REMOTE = _ids.get("remote_id", "")     # the "Air" AC remote id — stored in ~/tinytuya.json

# infrared_ac value maps. If a word does the wrong thing on your AC, swap the number here.
MODE = {"cool": 0, "heat": 1, "auto": 2, "fan": 3, "dry": 4, "humidity": 4, "dehumidify": 4}
FAN  = {"auto": 0, "low": 1, "mid": 2, "medium": 2, "high": 3}
_MODE_NAME = {0: "cool", 1: "heat", 2: "auto", 3: "fan", 4: "dry"}
_FAN_NAME  = {0: "auto", 1: "low", 2: "mid", 3: "high"}

_C = None
def _cloud():
    global _C
    if _C is None:
        import tinytuya
        k = json.load(open(CONF))
        _C = tinytuya.Cloud(apiRegion=k["apiRegion"], apiKey=k["apiKey"],
                            apiSecret=k["apiSecret"], apiDeviceID=k["apiDeviceID"])
    return _C

def _cmd(code, value):
    p = "/v2.0/infrareds/%s/air-conditioners/%s/command" % (IR, REMOTE)
    r = _cloud().cloudrequest(p, post={"code": code, "value": value})
    return bool(isinstance(r, dict) and r.get("success"))

def _status():
    p = "/v2.0/infrareds/%s/remotes/%s/ac/status" % (IR, REMOTE)
    r = _cloud().cloudrequest(p)
    return r.get("result", {}) if isinstance(r, dict) else {}

def _first_int(parts):
    for tok in parts:
        d = "".join(ch for ch in tok if ch.isdigit())
        if d:
            return int(d)
    return None

def ac(cmd):
    """cmd: 'on'|'off'|'temp 24'|'mode cool'|'fan high'|'status'. Returns a short spoken reply."""
    parts = str(cmd).lower().replace("degrees", " ").replace("degree", " ").split()
    if not parts:
        return "AC command? Say on, off, temp, mode, fan, or status."
    head = parts[0]
    arg  = parts[1] if len(parts) > 1 else ""

    if head in ("on", "off"):
        return ("AC on." if head == "on" else "AC off.") if _cmd("power", 1 if head == "on" else 0) else "The AC didn't respond."

    if head in ("status", "state"):
        s = _status()
        if not s:
            return "Couldn't read the AC."
        return "AC is %s, %s mode, %s degrees, fan %s." % (
            "on" if str(s.get("power")) == "1" else "off",
            _MODE_NAME.get(int(s.get("mode", -1)), "?"),
            s.get("temp", "?"),
            _FAN_NAME.get(int(s.get("wind", -1)), "?"))

    if head in ("temp", "temperature", "set", "cool", "heat"):
        if head in ("cool", "heat"):
            _cmd("mode", MODE[head])
        t = _first_int(parts)
        if t is None:
            return "What temperature? 16 to 30."
        t = max(16, min(30, t))
        return "Set to %d degrees." % t if _cmd("temp", t) else "The AC didn't respond."

    if head == "mode":
        m = MODE.get(arg)
        if m is None:
            return "Modes are cool, heat, auto, dry, and fan."
        return "%s mode." % arg.title() if _cmd("mode", m) else "The AC didn't respond."

    if head == "fan":
        w = FAN.get(arg)
        if w is None:
            return "Fan can be low, mid, high, or auto."
        return "Fan %s." % arg if _cmd("wind", w) else "The AC didn't respond."

    return "AC controls: on, off, temp N, mode X, fan X, status."

def _selftest():
    """Offline parser check — stubs the network so it fires no real IR."""
    global _cmd, _status
    calls = []
    _cmd    = lambda code, value: (calls.append((code, value)) or True)
    _status = lambda: {"power": "1", "mode": "0", "temp": "24", "wind": "0"}
    assert ac("on")  == "AC on."  and calls[-1] == ("power", 1)
    assert ac("off") == "AC off." and calls[-1] == ("power", 0)
    assert "24" in ac("set the temperature to 24") and calls[-1] == ("temp", 24)
    assert ac("temp 99") and calls[-1] == ("temp", 30)          # clamp
    assert ac("mode cool") == "Cool mode." and calls[-1] == ("mode", 0)
    assert ac("fan high")  == "Fan high."  and calls[-1] == ("wind", 3)
    assert ac("cool 22") and ("mode", 0) in calls and calls[-1] == ("temp", 22)
    assert "on" in ac("status") and "cool" in ac("status")
    print("selftest OK")

if __name__ == "__main__":
    a = sys.argv[1:]
    if a[:1] == ["selftest"]:
        _selftest()
    else:
        print(ac(" ".join(a) or "status"))
