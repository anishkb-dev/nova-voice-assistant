#!/usr/bin/env python3
"""Control the MELK / ELK-BLEDOM BLE LED strip locally over Bluetooth — no app, no cloud.

  python3 lights.py on | off
  python3 lights.py red | blue | warm | "#ff8800"
  python3 lights.py brightness 60
  python3 lights.py color 255 120 0

Nova calls lights("on") / lights("blue") / lights("brightness 50").
ELK-BLEDOM protocol, write char 0xFFF3. BLE allows ONE connection at a time —
if the phone app is connected it blocks this, so close the app.
"""
import asyncio, sys

ADDR = "95A77178-E246-FE4E-B242-F25E93D8F949"    # MELK-OA10 (macOS BLE UUID; re-scan if it ever changes)
CHAR = "0000fff3-0000-1000-8000-00805f9b34fb"

COLORS = {
    "red": (255, 0, 0), "green": (0, 255, 0), "blue": (0, 0, 255), "white": (255, 255, 255),
    "warm": (255, 150, 60), "warmwhite": (255, 150, 60), "yellow": (255, 220, 0),
    "orange": (255, 100, 0), "purple": (160, 0, 255), "pink": (255, 40, 120),
    "cyan": (0, 255, 255), "magenta": (255, 0, 255),
}

ON  = bytes.fromhex("7e0004f00001ff00ef")
OFF = bytes.fromhex("7e0004000000ff00ef")
def _rgb(r, g, b): return bytes([0x7e, 0, 5, 3, r & 255, g & 255, b & 255, 0, 0xef])
def _bri(pct):     return bytes([0x7e, 0, 1, max(0, min(100, pct)), 0, 0, 0, 0, 0xef])  # ponytail: brightness byte unverified — test & adjust if off
def _effect(eid):  return bytes([0x7e, 0, 3, eid & 0xff, 3, 0, 0, 0, 0xef])             # ELK-BLEDOM built-in animations
def _speed(pct):   return bytes([0x7e, 0, 2, max(0, min(100, pct)), 0, 0, 0, 0, 0xef])  # effect speed 0-100

# friendly name -> ELK-BLEDOM effect id. Rename to match what your strip actually does.
EFFECTS = {
    "jump": 0x87, "party": 0x88, "cycle": 0x96, "fade": 0x95, "crossfade": 0x95,
    "pulse": 0x92, "breathe": 0x92, "strobe": 0x9d, "flash": 0x9d, "blink": 0x9d,
}

_dev = None   # found strip, cached for this process

async def _find():
    """macOS gives each Mac its own BLE UUID for the strip, so find it by name (MELK-… / ELK-BLEDOM)."""
    global _dev
    from bleak import BleakScanner
    if _dev is None:
        _dev = await BleakScanner.find_device_by_filter(
            lambda d, ad: (d.name or ad.local_name or "").upper().startswith(("MELK", "ELK")), timeout=12) or ADDR
    return _dev

async def _send(payloads):
    global _dev
    from bleak import BleakClient
    try:
        dev = await _find()
        async with BleakClient(dev, timeout=20) as c:
            for p in payloads:
                await c.write_gatt_char(CHAR, p, response=False)
                await asyncio.sleep(0.15)
    except Exception:
        _dev = None   # strip moved/reset -> rescan next time
        raise

def _tx(payloads):
    # If the light_panel server is running, route through ITS persistent BLE connection
    # (BLE allows one link — this avoids the panel and voice fighting over it).
    try:
        import urllib.request
        urllib.request.urlopen("http://localhost:8099/state", timeout=0.4)
        for p in payloads:
            urllib.request.urlopen("http://localhost:8099/raw?hex=" + p.hex(), timeout=2)
        return True
    except Exception:
        pass
    try:
        asyncio.run(_send(payloads)); return True
    except Exception as e:
        print("[lights]", str(e)[:90], file=sys.stderr); return False

def _color(tokens):
    s = "".join(tokens).lstrip("#")
    if s in COLORS:
        return COLORS[s]
    digs = [int(t) for t in tokens if t.isdigit()]
    if len(digs) >= 3:
        return (digs[0], digs[1], digs[2])
    if len(s) == 6:
        try:
            return tuple(int(s[i:i + 2], 16) for i in (0, 2, 4))
        except Exception:
            return None
    return None

def lights(cmd):
    """cmd: 'on'|'off'|'<colour>'|'brightness N'|'color R G B'. Returns a short spoken reply."""
    parts = str(cmd).lower().replace("colour", "color").split()
    if not parts:
        return "Lights: say on, off, a colour, or brightness."
    head = parts[0]
    # natural phrasing: "turn on/off", "switch off", "lights off", bare "on"/"off"
    if "off" in parts:
        return "Lights off." if _tx([OFF]) else "The lights didn't respond."
    if head == "on" or ("on" in parts and head not in COLORS and head not in EFFECTS):
        return "Lights on." if _tx([ON]) else "The lights didn't respond."
    if head in ("brightness", "dim", "brighten", "bright"):
        n = next((int(t) for t in parts if t.isdigit()), None)
        if n is None:
            n = 30 if head == "dim" else 85            # 'dim' -> low, 'brighten'/'bright' -> high
        return "Brightness %d." % max(0, min(100, n)) if _tx([ON, _bri(n)]) else "The lights didn't respond."
    if head == "effect" or head in EFFECTS:
        key = parts[1] if (head == "effect" and len(parts) > 1) else head
        eid = int(key, 0) if key.replace("0x", "").isdigit() else EFFECTS.get(key)
        if eid is None:
            return "Effects: party, fade, cycle, pulse, strobe (or 'effect <0-157>')."
        return "%s." % key.title() if _tx([ON, _effect(eid)]) else "The lights didn't respond."
    if head in ("speed", "faster", "slower"):
        n = next((int(t) for t in parts if t.isdigit()), None)
        if n is None:
            n = 90 if head == "faster" else 15
        return "Speed %d." % max(0, min(100, n)) if _tx([_speed(n)]) else "The lights didn't respond."
    rest = parts[1:] if head in ("color", "set") else parts
    rgb = _color(rest)
    if rgb:
        name = " ".join(rest).title() or "Colour set"
        return "%s." % name if _tx([ON, _rgb(*rgb)]) else "The lights didn't respond."
    return "Lights: on, off, a colour (red/blue/warm…), brightness N, or color R G B."

def _selftest():
    assert _rgb(255, 0, 0).hex() == "7e000503ff000000ef"
    assert _rgb(0, 0, 255).hex() == "7e0005030000ff00ef"
    assert _color(["red"]) == (255, 0, 0)
    assert _color(["#ff8800"]) == (255, 136, 0)
    assert _color(["255", "120", "0"]) == (255, 120, 0)
    assert _color(["banana"]) is None
    print("selftest OK")

if __name__ == "__main__":
    a = sys.argv[1:]
    if a[:1] == ["selftest"]:
        _selftest()
    else:
        print(lights(" ".join(a) or "on"))
