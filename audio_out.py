"""Keep the hub's default audio output on the USB speakers (GeneralPlus "USB Audio Device").
macOS falls back to the internal speakers when the dongle is replugged; this puts it back every 10 s.
Run by launchd: ~/Library/LaunchAgents/com.nova.audio-out.plist (hub only). Added 2026-11-18."""
import time
import ctypes, ctypes.util, struct, sys
CA = ctypes.cdll.LoadLibrary(ctypes.util.find_library("CoreAudio"))
CF = ctypes.cdll.LoadLibrary(ctypes.util.find_library("CoreFoundation"))
def fourcc(s): return struct.unpack(">I", s.encode())[0]
class Addr(ctypes.Structure):
    _fields_ = [("sel", ctypes.c_uint32), ("scope", ctypes.c_uint32), ("elem", ctypes.c_uint32)]
SYS, GLOB, OUT = 1, fourcc("glob"), fourcc("outp")
def get(obj, sel, scope, buf, size):
    a = Addr(fourcc(sel), scope, 0); s = ctypes.c_uint32(size)
    r = CA.AudioObjectGetPropertyData(obj, ctypes.byref(a), 0, None, ctypes.byref(s), buf)
    return r, s.value
CF.CFStringGetCString.argtypes = [ctypes.c_void_p, ctypes.c_char_p, ctypes.c_long, ctypes.c_uint32]
CF.CFRelease.argtypes = [ctypes.c_void_p]
def name(d):
    p = ctypes.c_void_p(); get(d, "lnam", GLOB, ctypes.byref(p), 8)
    b = ctypes.create_string_buffer(256); CF.CFStringGetCString(p, b, 256, 0x08000100); CF.CFRelease(p); return b.value.decode()
def outch(d):
    a = Addr(fourcc("slay"), OUT, 0); s = ctypes.c_uint32()
    if CA.AudioObjectGetPropertyDataSize(d, ctypes.byref(a), 0, None, ctypes.byref(s)) or s.value == 0: return 0
    buf = ctypes.create_string_buffer(s.value); get(d, "slay", OUT, buf, s.value)
    nb = struct.unpack_from("I", buf.raw, 0)[0]
    return sum(struct.unpack_from("I", buf.raw, 8 + i * 16)[0] for i in range(nb))  # mNumberChannels

WANT = "USB Audio Device"
def devices():
    a = Addr(fourcc("dev#"), GLOB, 0); sz = ctypes.c_uint32()
    CA.AudioObjectGetPropertyDataSize(SYS, ctypes.byref(a), 0, None, ctypes.byref(sz))
    ids = (ctypes.c_uint32 * (sz.value // 4))(); get(SYS, "dev#", GLOB, ids, sz.value); return list(ids)
def tick():
    cur = ctypes.c_uint32(); get(SYS, "dOut", GLOB, ctypes.byref(cur), 4)
    if name(cur.value) == WANT: return
    tgt = [d for d in devices() if name(d) == WANT and outch(d) > 0]
    if not tgt: return                       # speakers unplugged: leave whatever macOS chose
    a = Addr(fourcc("dOut"), GLOB, 0); v = ctypes.c_uint32(tgt[0])
    CA.AudioObjectSetPropertyData(SYS, ctypes.byref(a), 0, None, 4, ctypes.byref(v))
    print(time.strftime("%F %T"), "output was", name(cur.value), "-> set to", WANT, flush=True)
while True:
    try: tick()
    except Exception as e: print("err", e, flush=True)
    time.sleep(10)
