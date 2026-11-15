"""Philips WiZ bulb over its local UDP API (port 38899) - no cloud, stdlib only.
bulb("on" | "off" | "dim" | "brighter" | "brightness 40" | "warm" | "cool" | "white" | "blue" | "night")"""
import json, os, re, socket

PORT = 38899
_IP_FILE = os.path.expanduser("~/anish-ai/.wiz_ip")
COLOURS = {"red": (255, 0, 0), "green": (0, 255, 0), "blue": (0, 0, 255), "purple": (140, 0, 255),
           "pink": (255, 40, 120), "orange": (255, 100, 0), "yellow": (255, 200, 0),
           "aqua": (0, 255, 200), "teal": (0, 160, 140), "cyan": (0, 255, 255)}
TEMPS = {"warm": 2700, "white": 4000, "neutral": 4000, "cool": 6000, "daylight": 6500}


def _send(ip, msg, timeout=1.5, bcast=False):
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    s.settimeout(timeout)
    if bcast:
        s.setsockopt(socket.SOL_SOCKET, socket.SO_BROADCAST, 1)
    try:
        s.sendto(json.dumps(msg).encode(), (ip, PORT))
        data, addr = s.recvfrom(2048)
        return json.loads(data), addr[0]
    finally:
        s.close()


def find(timeout=2.0):
    """Broadcast getPilot; first WiZ bulb that answers wins. Cached so DHCP moves self-heal."""
    for dst in ("255.255.255.255", "192.168.68.255"):
        try:
            _, ip = _send(dst, {"method": "getPilot", "params": {}}, timeout, bcast=True)
            open(_IP_FILE, "w").write(ip)
            return ip
        except (OSError, ValueError):
            continue
    return None


def _call(params, method="setPilot"):
    ip = open(_IP_FILE).read().strip() if os.path.exists(_IP_FILE) else find()
    for _ in range(2):
        if not ip:
            break
        try:
            r = _send(ip, {"method": method, "params": params})[0]
            if "error" in r:                  # e.g. -32602 when "Allow local communication" is off in the WiZ app
                raise PermissionError("bulb refused: %s" % r["error"].get("message"))
            return r
        except PermissionError:
            raise
        except (OSError, ValueError):
            ip = find()                       # bulb moved or cache stale -> rediscover once
    raise OSError("no WiZ bulb answered on the LAN")


def parse(cmd):
    """Text -> setPilot params (None = needs current state)."""
    c = cmd.lower().strip()
    if c in ("on", "turn on"): return {"state": True}
    if c in ("off", "turn off"): return {"state": False}
    if c in ("night", "night light", "nightlight"): return {"state": True, "sceneId": 14}
    m = re.search(r"(\d+)", c)
    if m and ("bright" in c or "dim" in c or "%" in c): return {"state": True, "dimming": max(10, min(100, int(m.group(1))))}
    for k, t in TEMPS.items():
        if k in c: return {"state": True, "temp": t}
    for k, (r, g, b) in COLOURS.items():
        if k in c: return {"state": True, "r": r, "g": g, "b": b}
    if "dim" in c or "darker" in c: return {"_step": -25}
    if "bright" in c: return {"_step": 25}
    return {}


def state():
    """'on' / 'off', or None if the bulb can't be reached (rules then don't fire)."""
    try:
        return "on" if _call({}, "getPilot").get("result", {}).get("state") else "off"
    except OSError:
        return None


def bulb(command: str) -> str:
    p = parse(command)
    if not p:
        return "I can turn the bulb on or off, dim it, or set warm, cool or a colour, sir."
    try:
        if "_step" in p:
            cur = _call({}, "getPilot").get("result", {}).get("dimming", 60)
            p = {"state": True, "dimming": max(10, min(100, cur + p["_step"]))}
        _call(p)
    except PermissionError:
        return "The bulb is refusing my commands, sir. Please allow local communication in the WiZ app."
    except OSError:
        return "I can't reach the bulb, sir. Is it powered and on the Wi-Fi?"
    return "Bulb %s, sir." % command.strip()


if __name__ == "__main__":                    # self-check against a fake bulb on localhost
    import threading
    assert parse("off") == {"state": False}
    assert parse("dim to 30%") == {"state": True, "dimming": 30}
    assert parse("make it warm") == {"state": True, "temp": 2700}
    assert parse("blue")["b"] == 255 and parse("dimmer") == {"_step": -25}
    got = []
    srv = socket.socket(socket.AF_INET, socket.SOCK_DGRAM); srv.bind(("127.0.0.1", PORT))
    def fake():
        for _ in range(2):
            d, a = srv.recvfrom(2048); m = json.loads(d); got.append(m)
            srv.sendto(json.dumps({"result": {"dimming": 60} if m["method"] == "getPilot" else {"success": True}}).encode(), a)
    threading.Thread(target=fake, daemon=True).start()
    _IP_FILE = "/tmp/.wiz_ip_test"; open(_IP_FILE, "w").write("127.0.0.1")
    assert bulb("dimmer") == "Bulb dimmer, sir."
    assert got[1]["params"] == {"state": True, "dimming": 35}, got
    print("wiz ok")
