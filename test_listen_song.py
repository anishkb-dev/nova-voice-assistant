import sys, os, time, wave, numpy as np
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import light_panel as lp
import tempfile; d = tempfile.mkdtemp(); wav = os.path.join(d, "t.wav")
sr = 44100; x = np.zeros(sr * 4, np.float32); x[sr:2 * sr] = 0.8 * np.sin(np.arange(sr) * 2 * np.pi * 440 / sr)   # loud 1-2 s
with wave.open(wav, "w") as w:
    w.setnchannels(2); w.setsampwidth(2); w.setframerate(sr); w.writeframes((np.repeat(x[:, None], 2, 1) * 32767).astype(np.int16).tobytes())
e = lp._envelope(wav)
assert len(e) == 80 and e[30] > 0.9 and e[5] < 0.01 and e[60] < 0.01, (len(e), e[5], e[30], e[60])
import shutil, subprocess
song = os.path.join(d, "nova_track.wav"); shutil.copy(wav, song); os.utime(song, (time.time() - 1.5,) * 2)   # 1.5 s in
s = lp._Song(); assert s.level() == 0.0, "no player yet"
fake = subprocess.Popen(   # stand-in player: its args end in .../nova_track.wav, like afplay's
    [sys.executable, "-c", "import time; time.sleep(30)", song])
try:
    s.chk = 0; lv = s.level()
    assert lv > 0.9, lv
    os.kill(fake.pid, 19); time.sleep(0.6); s.chk = 0; assert s.level() == 0.0, "paused"   # SIGSTOP = pause
finally:
    fake.kill()
s.chk = 0; assert s.level() == 0.0, "player gone"
print("listen-from-song checks passed")
