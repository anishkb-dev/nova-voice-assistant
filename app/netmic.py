"""Bedside ESP32 mic (iot/esp32_bedmic) as a PyAudio-stream lookalike.
UDP :5005, each packet = 16-byte key (~/anish-ai/.mic_key) + int16 LE mono PCM @ 16 kHz."""
import array, hmac, os, socket, threading, time
import numpy as np
from scipy.signal import butter, sosfilt, sosfilt_zi

HP_HZ = 200                                 # calibration knob: below this is thump/DC, not voice (table mic 2026-11-18: 99% <150 Hz)
HP = butter(2, HP_HZ, "highpass", fs=16000, output="sos")

KEY = open(os.path.expanduser("~/anish-ai/.mic_key"), "rb").read()[:16]
MAX_BUF = 16000 * 2 * 5                     # keep at most 5 s; older audio is dropped
SWITCH_X, SWITCH_N = 1.5, 2                 # calibration knobs: louder by 1.5x for 2 frames (160 ms) -> change mic
MUTE = os.path.expanduser("~/anish-ai/.mic_mute")   # sender IPs to ignore, one per line (a noisy mic); re-read every 2 s


class NetMic:
    """Any number of keyed ESP32 mics (bed, table) on one port. Each read returns the chunk from whichever mic
    hears the most right now (loudest wins per ~80 ms frame), so a dead or far mic never drowns the near one."""
    def __init__(self, port=5005):
        self.sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        self.sock.bind(("", port))
        self.bufs, self.seen, self.last, self.cv = {}, {}, 0.0, threading.Condition()   # per sender IP
        self.lvl = {}                       # per sender IP: [quietest, loudest] frame level since levels() was last called
        self.mute, self._mt = set(), 0.0
        self.cur, self.flip = None, 0       # mic in use + frames another one has been clearly louder
        self.zi = {}                        # per sender IP: high-pass filter state (packets are one continuous stream)
        threading.Thread(target=self._rx, daemon=True).start()

    def _rx(self):
        while True:
            try:
                d, (ip, _) = self.sock.recvfrom(4096)
            except OSError:
                return                      # closed
            if len(d) <= 16 or not hmac.compare_digest(d[:16], KEY):
                continue                    # not our mic -> ignore (stops LAN audio injection)
            if time.time() - self._mt > 2:
                self._mt = time.time()
                try: self.mute = set(open(MUTE).read().split())
                except OSError: self.mute = set()
            if ip in self.mute or "*" in self.mute:   # "*" = owner said "mic off"
                continue                    # its leftover buffer drains in a few reads
            pcm = self._hp(ip, d[16:])
            with self.cv:
                b = self.bufs.setdefault(ip, bytearray())
                b += pcm
                if len(b) > MAX_BUF:
                    del b[:len(b) - MAX_BUF]
                self.last = self.seen[ip] = time.time()
                self.cv.notify()

    def _hp(self, ip, raw):
        """High-pass each mic's stream: drops thumps/DC wander (power or ground noise) that would out-shout real voices."""
        x = np.frombuffer(raw, "<i2").astype(np.float32)
        zi = self.zi.get(ip)
        if zi is None: zi = sosfilt_zi(HP) * x[0]
        y, self.zi[ip] = sosfilt(HP, x, zi=zi)
        return np.clip(y, -32768, 32767).astype("<i2").tobytes()

    def alive(self, within=2.0):
        return time.time() - self.last < within

    def live(self, within=5.0):
        """Sender IPs streaming in the last `within` s."""
        return [ip for ip, t in self.seen.items() if time.time() - t < within]

    def get_read_available(self):
        return max((len(b) for b in self.bufs.values()), default=0) // 2

    def read(self, n, exception_on_overflow=False):
        with self.cv:
            while not any(len(b) >= n * 2 for b in self.bufs.values()):
                if not self.cv.wait(1.0):
                    return bytes(n * 2)     # mics dropped -> silence, never block forever
            got = {}
            for ip, b in self.bufs.items():
                if len(b) < n * 2:
                    continue                # this mic is a bit behind -> it joins next frame
                chunk = bytes(b[:n * 2]); del b[:n * 2]
                e = sum(abs(v) for v in array.array("h", chunk)[::8])
                m = e / max(1, len(chunk) // 16)  # mean |sample| (every 8th of len/2 samples)
                lv = self.lvl.setdefault(ip, [m, m]); lv[0] = min(lv[0], m); lv[1] = max(lv[1], m)
                got[ip] = (chunk, e)
            top = max(got, key=lambda ip: got[ip][1])
            # sticky: flipping mics every 80 ms stitched bed + table audio mid-word (level jumps, clicks) -> STT misheard.
            # Switch only when another mic is clearly louder (SWITCH_X) for SWITCH_N frames in a row.
            if self.cur in got and top != self.cur:
                self.flip = self.flip + 1 if got[top][1] > SWITCH_X * got[self.cur][1] else 0
                if self.flip < SWITCH_N: top = self.cur
            if top != self.cur: self.cur, self.flip = top, 0
            best = got[top][0]
            live = [self.bufs[ip] for ip in self.live(1.0) if ip in self.bufs]
            if len(live) > 1:               # mic clocks drift: keep mics in step, but never drop a lone mic's
                low = min(len(b) for b in live) + n * 2 * 3      # backlog (Nova reads late while STT runs)
                for b in live:
                    if len(b) > low: del b[:len(b) - low]
            return best

    def levels(self):
        """{ip: (floor, peak)} mean |sample| per frame since the last call. Peak 0 = the mic streams pure silence (wiring)."""
        with self.cv:
            out = {ip: (round(a), round(b)) for ip, (a, b) in self.lvl.items()}
            self.lvl = {}
        return out

    def stop_stream(self):
        pass

    def close(self):
        self.sock.close()


if __name__ == "__main__":                  # self-check: loopback a keyed packet and a forged one
    import array
    m = NetMic(port=5099)
    m._hp = lambda ip, raw: raw             # mixing logic first, unfiltered; the filter is checked at the end
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    s.sendto(b"x" * 16 + array.array("h", [999] * 512).tobytes(), ("127.0.0.1", 5099))
    s.sendto(KEY + array.array("h", [7] * 512).tobytes(), ("127.0.0.1", 5099))
    time.sleep(0.2)
    assert m.alive() and m.get_read_available() == 512, m.get_read_available()
    assert set(array.array("h", m.read(512))) == {7}      # forged packet rejected
    t = time.time(); assert m.read(1280) == bytes(2560) and time.time() - t < 1.5
    t = np.arange(16000) / 16000.0          # high-pass: 30 Hz thump gone, 1 kHz voice kept
    for hz, lo, hi in ((30, 0, 0.05), (1000, 0.9, 1.1)):
        zi = sosfilt_zi(HP) * 0; y, _ = sosfilt(HP, np.sin(2 * np.pi * hz * t) * 5000, zi=zi)
        r = np.abs(y[8000:]).max() / 5000; assert lo <= r <= hi, (hz, r)
    with m.cv:                              # a 2nd mic (macOS has no 127.0.0.2: fake its sender IP)
        m.bufs["10.0.0.2"] = bytearray(array.array("h", [900] * 1280).tobytes()); m.seen["10.0.0.2"] = time.time()
    s.sendto(KEY + array.array("h", [5] * 1280).tobytes(), ("127.0.0.1", 5099))
    time.sleep(0.2)
    m.cur = None                            # no mic chosen yet -> the louder one wins straight away
    assert len(m.live()) == 2 and set(array.array("h", m.read(1280))) == {900}   # louder mic wins
    s.sendto(KEY + array.array("h", [6] * 1280).tobytes(), ("127.0.0.1", 5099))  # only mic 1 talks now
    time.sleep(0.1)
    assert set(array.array("h", m.read(1280))) == {6}                             # silent mic 2 doesn't block
    lv = m.levels(); assert lv["10.0.0.2"] == (900, 900) and lv["127.0.0.1"] == (5, 7), lv   # per-mic floor + peak
    assert m.levels() == {}                                                       # reset after reading
    m.cur, m.flip = "A", 0                  # sticky: a mic only 1.2x louder doesn't steal the stream ...
    with m.cv:
        for ip, v in (("A", 1000), ("B", 1200)): m.bufs[ip] = bytearray(array.array("h", [v] * 1280).tobytes()); m.seen[ip] = time.time()
    assert set(array.array("h", m.read(1280))) == {1000}
    for k in (1, 2):                        # ... one 3x louder takes over on its 2nd frame
        with m.cv:
            for ip, v in (("A", 1000), ("B", 3000)): m.bufs[ip] = bytearray(array.array("h", [v] * 1280).tobytes()); m.seen[ip] = time.time()
        got = set(array.array("h", m.read(1280)))
    assert got == {3000} and m.cur == "B", (got, m.cur)
    with m.cv: m.bufs.clear(); m.seen.clear()
    del m._hp                               # real filter: a 30 Hz thump through the socket comes out near silent
    thump = (np.sin(2 * np.pi * 30 * np.arange(4096) / 16000) * 8000).astype("<i2")
    for i in range(0, 4096, 512): s.sendto(KEY + thump[i:i + 512].tobytes(), ("127.0.0.1", 5099))
    time.sleep(0.2); m.read(2560)
    assert max(map(abs, array.array("h", m.read(1280)))) < 400, "thump not filtered"
    print("netmic ok")
