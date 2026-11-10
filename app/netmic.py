"""Bedside ESP32 mic (iot/esp32_bedmic) as a PyAudio-stream lookalike.
UDP :5005, each packet = 16-byte key (~/anish-ai/.mic_key) + int16 LE mono PCM @ 16 kHz."""
import hmac, os, socket, threading, time

KEY = open(os.path.expanduser("~/anish-ai/.mic_key"), "rb").read()[:16]
MAX_BUF = 16000 * 2 * 5                     # keep at most 5 s; older audio is dropped


class NetMic:
    def __init__(self, port=5005):
        self.sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        self.sock.bind(("", port))
        self.buf, self.last, self.cv = bytearray(), 0.0, threading.Condition()
        threading.Thread(target=self._rx, daemon=True).start()

    def _rx(self):
        while True:
            try:
                d = self.sock.recvfrom(4096)[0]
            except OSError:
                return                      # closed
            if len(d) <= 16 or not hmac.compare_digest(d[:16], KEY):
                continue                    # not our mic -> ignore (stops LAN audio injection)
            with self.cv:
                self.buf += d[16:]
                if len(self.buf) > MAX_BUF:
                    del self.buf[:len(self.buf) - MAX_BUF]
                self.last = time.time()
                self.cv.notify()

    def alive(self, within=2.0):
        return time.time() - self.last < within

    def get_read_available(self):
        return len(self.buf) // 2

    def read(self, n, exception_on_overflow=False):
        with self.cv:
            while len(self.buf) < n * 2:
                if not self.cv.wait(1.0):
                    return bytes(n * 2)     # mic dropped -> silence, never block forever
            out = bytes(self.buf[:n * 2])
            del self.buf[:n * 2]
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
    print("netmic ok")
