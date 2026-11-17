"""Bedside ESP32 mic (iot/esp32_bedmic) as a PyAudio-stream lookalike.
UDP :5005, each packet = 16-byte key (~/anish-ai/.mic_key) + int16 LE mono PCM @ 16 kHz."""
import array, hmac, os, socket, threading, time

KEY = open(os.path.expanduser("~/anish-ai/.mic_key"), "rb").read()[:16]
MAX_BUF = 16000 * 2 * 5                     # keep at most 5 s; older audio is dropped


class NetMic:
    """Any number of keyed ESP32 mics (bed, table) on one port. Each read returns the chunk from whichever mic
    hears the most right now (loudest wins per ~80 ms frame), so a dead or far mic never drowns the near one."""
    def __init__(self, port=5005):
        self.sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        self.sock.bind(("", port))
        self.bufs, self.seen, self.last, self.cv = {}, {}, 0.0, threading.Condition()   # per sender IP
        self.lvl = {}                       # per sender IP: [quietest, loudest] frame level since levels() was last called
        threading.Thread(target=self._rx, daemon=True).start()

    def _rx(self):
        while True:
            try:
                d, (ip, _) = self.sock.recvfrom(4096)
            except OSError:
                return                      # closed
            if len(d) <= 16 or not hmac.compare_digest(d[:16], KEY):
                continue                    # not our mic -> ignore (stops LAN audio injection)
            with self.cv:
                b = self.bufs.setdefault(ip, bytearray())
                b += d[16:]
                if len(b) > MAX_BUF:
                    del b[:len(b) - MAX_BUF]
                self.last = self.seen[ip] = time.time()
                self.cv.notify()

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
            best, best_e = None, -1
            for ip, b in self.bufs.items():
                if len(b) < n * 2:
                    continue                # this mic is a bit behind -> it joins next frame
                chunk = bytes(b[:n * 2]); del b[:n * 2]
                e = sum(abs(v) for v in array.array("h", chunk)[::8])
                m = e / max(1, len(chunk) // 16)  # mean |sample| (every 8th of len/2 samples)
                lv = self.lvl.setdefault(ip, [m, m]); lv[0] = min(lv[0], m); lv[1] = max(lv[1], m)
                if e > best_e:
                    best, best_e = chunk, e
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
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    s.sendto(b"x" * 16 + array.array("h", [999] * 512).tobytes(), ("127.0.0.1", 5099))
    s.sendto(KEY + array.array("h", [7] * 512).tobytes(), ("127.0.0.1", 5099))
    time.sleep(0.2)
    assert m.alive() and m.get_read_available() == 512, m.get_read_available()
    assert set(array.array("h", m.read(512))) == {7}      # forged packet rejected
    t = time.time(); assert m.read(1280) == bytes(2560) and time.time() - t < 1.5
    with m.cv:                              # a 2nd mic (macOS has no 127.0.0.2: fake its sender IP)
        m.bufs["10.0.0.2"] = bytearray(array.array("h", [900] * 1280).tobytes()); m.seen["10.0.0.2"] = time.time()
    s.sendto(KEY + array.array("h", [5] * 1280).tobytes(), ("127.0.0.1", 5099))
    time.sleep(0.2)
    assert len(m.live()) == 2 and set(array.array("h", m.read(1280))) == {900}   # louder mic wins
    s.sendto(KEY + array.array("h", [6] * 1280).tobytes(), ("127.0.0.1", 5099))  # only mic 1 talks now
    time.sleep(0.1)
    assert set(array.array("h", m.read(1280))) == {6}                             # silent mic 2 doesn't block
    lv = m.levels(); assert lv["10.0.0.2"] == (900, 900) and lv["127.0.0.1"] == (5, 7), lv   # per-mic floor + peak
    assert m.levels() == {}                                                       # reset after reading
    print("netmic ok")
