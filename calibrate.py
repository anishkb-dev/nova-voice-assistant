#!/usr/bin/env python3
"""Voice calibration — measure how YOU actually talk, then tune JARVIS to it.

Records ~20s of you speaking naturally, measures your speaking level, your
pause lengths (so end-of-turn detection matches your rhythm — no clipping, no
lag), and your speaking rate, then writes ~/anish-ai/voice_calib.json which the
listener reads on startup. Run it from the Terminal (mic permission); stop
JARVIS first so it isn't holding the mic.

    python3 ~/anish-ai/calibrate.py
"""
import os, sys, time, json, wave
import numpy as np
import pyaudio

RATE, FRAME = 16000, 1280            # 80ms frames
OUT = os.path.expanduser("~/anish-ai/voice_calib.json")
SCRIPT = [
    "Jarvis, what's the weather like today.",
    "Turn on the air conditioner and set it to twenty two degrees.",
    "Actually, play me some music instead.",
    "Hmm, no — what's on my calendar tomorrow.",
    "Thanks, that's all for now.",
]

def clamp(x, lo, hi): return max(lo, min(hi, x))

def pick_mic(pa):
    for i in range(pa.get_device_count()):
        d = pa.get_device_info_by_index(i)
        if d.get("maxInputChannels", 0) > 0 and ("usb" in d["name"].lower() or "ab13x" in d["name"].lower()):
            return i, d["name"]
    for i in range(pa.get_device_count()):        # fallback: built-in
        d = pa.get_device_info_by_index(i)
        if d.get("maxInputChannels", 0) > 0 and "macbook" in d["name"].lower():
            return i, d["name"]
    return None, "default"

def main():
    pa = pyaudio.PyAudio()
    idx, name = pick_mic(pa)
    s = pa.open(rate=RATE, channels=1, format=pyaudio.paInt16, input=True,
                input_device_index=idx, frames_per_buffer=FRAME)
    print("\n\033[1mVOICE CALIBRATION\033[0m   mic: %s" % name)
    print("Read these lines aloud, naturally, at your normal pace and volume.")
    print("Pause between them like you would in a real conversation.\n")
    for ln in SCRIPT:
        print("   \033[36m" + ln + "\033[0m")
    print("\nStarting in 3..."); time.sleep(1); print("2..."); time.sleep(1); print("1..."); time.sleep(1)
    print("\033[1m>>> GO — read the lines now <<<\033[0m")

    secs = 22
    frames = []
    for _ in range(int(secs * RATE / FRAME)):
        frames.append(np.frombuffer(s.read(FRAME, exception_on_overflow=False), dtype=np.int16))
    s.close()
    print(">>> done, analyzing...")

    pcm = np.concatenate(frames)
    rms = np.array([float(np.sqrt(np.mean(f.astype(np.float32) ** 2))) for f in frames])

    floor = float(np.percentile(rms, 20))                        # quiet gaps = room noise
    loud = rms[rms > max(floor * 2, floor + 20)]
    voice = float(np.percentile(loud, 60)) if loud.size else float(np.percentile(rms, 85))
    speech_thr = floor + 0.4 * (voice - floor)
    is_speech = rms > speech_thr

    # intra-speech gaps (pauses bounded by speech on both sides) -> your natural mid-sentence pause
    gaps, run, seen = [], 0, False
    for sp in is_speech:
        if sp:
            if run > 0 and seen:
                gaps.append(run)
            run = 0; seen = True
        elif seen:
            run += 1
    # 70th pct of intra-speech gaps ~ your natural mid-phrase pause (ignore the long between-sentence ones)
    mid_pause_ms = (float(np.percentile(gaps, 70)) * 80) if gaps else 300.0

    speech_frames = int(is_speech.sum())
    speech_sec = speech_frames * (FRAME / RATE)

    # words per minute (Whisper the recording)
    wpm = None
    try:
        import requests, io
        b = io.BytesIO(); w = wave.open(b, "wb")
        w.setnchannels(1); w.setsampwidth(2); w.setframerate(RATE); w.writeframes(pcm.tobytes()); w.close()
        gk = open(os.path.expanduser("~/anish-ai/.groq_key")).read().strip()
        r = requests.post("https://api.groq.com/openai/v1/audio/transcriptions",
                          headers={"Authorization": "Bearer " + gk},
                          files={"file": ("a.wav", b.getvalue(), "audio/wav")},
                          data={"model": "whisper-large-v3-turbo", "language": "en"}, timeout=25)
        if r.ok:
            txt = r.json().get("text", "")
            nwords = len(txt.split())
            if speech_sec > 1:
                wpm = round(nwords / (speech_sec / 60.0))
            print("   heard: %r  (%d words)" % (txt[:90], nwords))
    except Exception as e:
        print("   (transcription skipped: %s)" % str(e)[:40])
    pa.terminate()

    calib = {
        "trigger":   round(clamp(floor + 0.35 * (voice - floor), 40, 320), 1),
        "hang_ms":   int(clamp(mid_pause_ms + 160, 380, 780)),   # end-of-turn = a bit longer than your mid pause
        "barge_rms": round(clamp(voice * 0.5, 90, 500), 1),
        "floor":     round(floor, 1),
        "voice":     round(voice, 1),
        "wpm":       wpm,
        "mic":       name,
    }
    json.dump(calib, open(OUT, "w"), indent=1)
    print("\n\033[1mCALIBRATED\033[0m -> %s" % OUT)
    for k in ("floor", "voice", "trigger", "hang_ms", "barge_rms", "wpm"):
        print("   %-10s %s" % (k, calib[k]))
    print("\nfloor=room noise · voice=your level · trigger=start-listening · "
          "hang_ms=silence that ends your turn · barge_rms=loud enough to cut in")
    if calib["voice"] < 90:
        print("\033[33m   ⚠ your level is low — move the lavalier closer to your mouth for best results\033[0m")
    print("\nRestart JARVIS to apply.")

if __name__ == "__main__":
    main()
