"""Find My for Nova: ring a device if it's here, else Telegram its location.

  python3 findmy.py login     # one time, YOU type Apple ID + password + 2FA code
  python3 findmy.py list      # show devices + distance from this Mac
  python3 findmy.py           # offline self-check
"""
import math, os, socket, subprocess, sys

HERE = os.path.dirname(os.path.abspath(__file__))
USER_F = os.path.join(HERE, ".icloud_user_key")   # Apple ID only; password lives in the macOS keychain
NEAR_M = 150      # "same place" radius; Find My fixes indoors drift ~50-100 m


def _dist_m(a, b):
    la1, lo1, la2, lo2 = map(math.radians, (a["latitude"], a["longitude"], b["latitude"], b["longitude"]))
    h = math.sin((la2 - la1) / 2) ** 2 + math.cos(la1) * math.cos(la2) * math.sin((lo2 - lo1) / 2) ** 2
    return 6371000 * 2 * math.asin(math.sqrt(h))


def _api():
    from pyicloud import PyiCloudService
    api = PyiCloudService(open(USER_F).read().strip())   # password from keychain, session cookies cached
    if api.requires_2fa:
        raise RuntimeError("iCloud session expired — run: python3 ~/anish-ai/findmy.py login")
    return api


def _norm(t):
    return (t or "").lower().replace("\u2019", "'")


def _owner():
    me = subprocess.run(["scutil", "--get", "ComputerName"], capture_output=True, text=True).stdout
    return _norm(me).split("'")[0].strip()      # "Anish's MacBook Air" -> "anish"


def _mine(devs):
    """Only the owner's devices — Family Sharing ones (e.g. a partner's) are never located or rung."""
    o = _owner()
    return [d for d in devs if _norm(d["name"]).startswith(o)]


_MGR = None


def _devices(fresh=True):
    """Cached iCloud session (login + device list ~4 s, so do it once); retry once if it went stale."""
    global _MGR
    for attempt in (0, 1):
        try:
            if _MGR is None:
                _MGR = _api().devices
            elif fresh:
                _MGR.refresh(locate=True)        # ~1.4 s fresh fix
            return _mine(_MGR)
        except FileNotFoundError:
            raise
        except Exception:
            _MGR = None
            if attempt:
                raise


def warm():
    try:
        _devices(fresh=False)
    except Exception:
        pass


def _pick(devs, name, owner=""):
    name = _norm(name or "phone")
    alias = {"phone": "iphone", "mobile": "iphone", "watch": "watch", "tablet": "ipad", "laptop": "mac"}
    want = alias.get(name, name)
    hits = [d for d in devs if name in _norm(d["name"])] or \
           [d for d in devs if want in _norm(d["name"]) or want in _norm(d["deviceDisplayName"])]
    hits.sort(key=lambda d: not (owner and _norm(d["name"]).startswith(owner)))   # your own device before family's
    return hits[0] if hits else None


def _here(devs):
    me = subprocess.run(["scutil", "--get", "ComputerName"], capture_output=True, text=True).stdout.strip().lower()
    macs = [d for d in devs if "mac" in (d["deviceDisplayName"] or "").lower() and d.location]
    for d in macs:
        if d["name"].lower() == me:
            return d.location
    return macs[0].location if macs else None


def _telegram(text):
    import guard
    chat = open(guard.CHAT_F).read().strip()
    guard._tg("sendMessage", data={"chat_id": chat, "text": text})


def find_device(device: str = "phone") -> str:
    try:
        devs = _devices()
    except FileNotFoundError:
        return "Find My isn't linked yet, sir. Run python3 ~/anish-ai/findmy.py login in Terminal once."
    except Exception as e:
        return "I couldn't reach Find My, sir: %s" % str(e)[:120]
    d = _pick(devs, device, _owner())
    if not d:
        return "I don't see a %s on your Find My, sir. I have: %s." % (device, ", ".join(x["name"] for x in devs))
    loc, here = d.location, _here(devs)
    if loc and here and _dist_m(loc, here) > NEAR_M:
        link = "https://maps.google.com/?q=%s,%s" % (loc["latitude"], loc["longitude"])
        try:
            _telegram("📍 %s is about %.1f km away: %s" % (d["name"], _dist_m(loc, here) / 1000, link))
            return "Your %s isn't here, sir — it's about %.1f kilometres away. I've sent its location to your Telegram." % (d["name"], _dist_m(loc, here) / 1000)
        except Exception as e:
            return "Your %s is about %.1f km away, sir, but Telegram failed: %s" % (d["name"], _dist_m(loc, here) / 1000, str(e)[:80])
    d.play_sound("Nova: find my device")
    if not loc:
        return "I couldn't get a location fix, sir, so I've rung your %s anyway." % d["name"]
    return "Ringing your %s now, sir — it's here somewhere." % d["name"]


def login():
    import getpass
    from pyicloud import PyiCloudService
    from pyicloud.utils import store_password_in_keyring
    user = input("Apple ID: ").strip()
    pw = getpass.getpass("Apple ID password (not shown): ")
    api = PyiCloudService(user, pw)
    if api.requires_2fa:
        if not api.validate_2fa_code(input("2FA code from your iPhone: ").strip()):
            sys.exit("Wrong code.")
        if not api.is_trusted_session:
            api.trust_session()
    store_password_in_keyring(user, pw)
    open(USER_F, "w").write(user); os.chmod(USER_F, 0o600)
    print("Linked. Devices:", ", ".join(d["name"] for d in api.devices))


if __name__ == "__main__":
    if sys.argv[1:] == ["login"]:
        login()
    elif sys.argv[1:] == ["list"]:
        devs = _mine(_api().devices); here = _here(devs)
        for d in devs:
            loc = d.location
            print("%-28s %s" % (d["name"], "%.0f m" % _dist_m(loc, here) if loc and here else "no fix"))
    else:
        a = {"latitude": 12.9716, "longitude": 77.5946}
        assert _dist_m(a, a) == 0
        assert 1000 < _dist_m(a, {"latitude": 12.9806, "longitude": 77.5946}) < 1010   # 0.009° lat ≈ 1 km
        class D(dict): pass
        devs = [D(name="Anish's iPhone", deviceDisplayName="iPhone 15"), D(name="AirPods", deviceDisplayName="AirPods Pro")]
        assert _pick(devs, "phone")["name"] == "Anish's iPhone" and _pick(devs, "airpods")["name"] == "AirPods"
        assert _pick(devs, "ipad") is None
        fam = [D(name="Sweety\u2019s iphone", deviceDisplayName="iPhone"), D(name="Anish\u2019s iPhone", deviceDisplayName="iPhone")]
        assert _pick(fam, "phone", "anish")["name"].startswith("Anish")
        assert _pick(fam, "sweety's iphone", "anish")["name"].startswith("Sweety")
        print("ok")
