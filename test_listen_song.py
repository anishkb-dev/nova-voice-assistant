import sys, os, time, wave, numpy as np
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import light_panel as lp
import tempfile; d = tempfile.mkdtemp(); wav = os.path.join(d, "t.wav")
sr = 44100; x = np.zeros(sr * 4, np.float32); x[sr:2 * sr] = 0.8 * np.sin(np.arange(sr) * 2 * np.pi * 440 / sr)   # loud 1-2 s
with wave.open(wav, "w") as w:
    w.setnchannels(2); w.setsampwidth(2); w.setframerate(sr); w.writeframes((np.repeat(x[:, None], 2, 1) * 32767).astype(np.int16).tobytes())
e = lp._envelope(wav)
assert len(e) == 80 and e[30] > 0.9 and e[5] < 0.01 and e[60] < 0.01, (len(e), e[5], e[30], e[60])
lp.TRACK_START_F = os.path.join(d, "start")
s = lp._Song(); assert s.level() == 0.0                                    # no start file -> silent
open(lp.TRACK_START_F, "w").write("%d %f %s" % (os.getpid(), time.time() - 1.5, wav))   # 1.5 s into the song
assert s.level() > 0.9, s.level()
open(lp.TRACK_START_F, "w").write("%d %f %s" % (os.getpid(), time.time() - 0.3, wav + "x"))  # unreadable song
assert s.level() == 0.0
open(lp.TRACK_START_F, "w").write("999999 %f %s" % (time.time(), wav))                       # player gone
assert s.level() == 0.0
print("listen-from-song checks passed")
