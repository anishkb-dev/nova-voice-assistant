"""Speaking (local voice, hub speaker), speech-to-text, the hands-free mic loop, mic selection, voice profile.
Mixin of nova_app.Api (split out of nova_app.py verbatim, cleanup fix 10, 2026-11-17)."""
from nova_common import *   # noqa: F403 - the constants/helpers nova_app always had at module level


class Voice:

    def _say_wait(self, val):
        """Hub: say a line in Nova's voice and return once it has finished playing (home/hub/say, alarms)."""
        self._hub_speaking = True     # covers the ~1s of synthesis before audio starts
        print("[hub] say %r" % val[:80], flush=True)
        self._table_voice(1)
        try:
            self.speak(val)           # returns when audio STARTS; later chunks follow
            quiet = 0
            while quiet < 4:          # done = nothing playing for 0.8 s (covers chunk gaps)
                time.sleep(0.2); quiet = 0 if (self._say and self._say.poll() is None) else quiet + 1
        finally: self._hub_speaking = False; self._table_voice(0)

    def speak(self, text):
        if not self.voice or not text:
            return
        # Build a clean SPOKEN version (screen still shows the full text/code).
        spoken = re.sub(r"\bN\.?O\.?V\.?A\.?\b", "Nova", text, flags=re.IGNORECASE)
        spoken = re.sub(r"```.*?```", " The code is on your screen, sir. ",
                        spoken, flags=re.DOTALL)          # don't read code blocks aloud
        spoken = spoken.replace("`", "")                  # inline-code backticks
        spoken = re.sub(r"[*_#>|]+", " ", spoken)         # markdown symbols
        spoken = re.sub(r"https?://\S+", "a link", spoken)  # don't spell out URLs
        spoken = re.sub(r"\b(\d{1,2}):(\d{2})\b", lambda m: _say_clock(int(m.group(1)), int(m.group(2))), spoken)
        spoken = re.sub(r"\s*°\s*C\b", " degrees Celsius", spoken)   # Kokoro drops "°" -> "24 C"
        spoken = re.sub(r"\s*°\s*F\b", " degrees Fahrenheit", spoken)
        spoken = spoken.replace("°", " degrees")
        spoken = re.sub(r"\s+", " ", spoken).strip()
        self._last_spoken, self._spoken_at = spoken.lower(), time.time()  # for mic self-echo filtering
        if self._hub_link and not nova.IS_HUB:           # home (hub reachable) -> all speech on the room speaker
            try:
                threading.Thread(target=nova._hub_send, args=("said", spoken.lower()), daemon=True).start()   # hub: tell my voice from yours
                with self._hub_speak_lock:               # one reply at a time: overlapping speaks talked over each other
                    if not self._kokoro_to_hub(spoken):  # local Daniel voice; else hub synthesizes with edge-tts
                        nova._hub_send("say", spoken)
                return
            except Exception as e:
                print("[speak] hub speaker unreachable, using this Mac:", e, flush=True)
        if nova.IS_HUB:                                  # one voice at a time: whatever is playing finishes first (a 9:30 PM exam
                                                         # reminder and clip line used to cut each other off)
            t0 = time.time()
            while (self._clip_on or self._local_talking or (self._audio_q and not self._audio_q.empty())) and time.time() - t0 < 30:
                time.sleep(0.1)
            self._talk_tok = tok = object(); self._local_talking = True
            def _talk_done():                            # clear the flag once this speech goes quiet for 0.8 s
                t1, quiet = time.time(), 0
                while quiet < 4 and time.time() - t1 < 120:
                    time.sleep(0.2); quiet = 0 if (self._say and self._say.poll() is None) or time.time() - t1 < 2 else quiet + 1   # 2 s covers edge-tts synth (<=1.4 s); 5 s held the Mac's reply back after a 1 s "Yes, sir?"
                if self._talk_tok is tok: self._local_talking = False
            threading.Thread(target=_talk_done, daemon=True).start()
        self.stop_speaking()

        self._speak_gen += 1
        gen = self._speak_gen

        # split into sentence-ish chunks so we can speak the first while synthesizing the rest
        chunks = [c.strip() for c in re.split(r"(?<=[.!?])\s+", spoken) if c.strip()] or [spoken]

        def _synth(text, path):
            asyncio.run(edge_tts.Communicate(text, self._voice, rate=self._rate, pitch=self._pitch).save(path))
            return os.path.exists(path) and os.path.getsize(path) > 0

        def _play(path, fallback_text=None):
            # afplay occasionally dies instantly with AudioQueueStart (-66681) when the output device
            # is transitioning; retry once, then fall back to the built-in voice so speech is never lost.
            for attempt in (0, 1):
                p = subprocess.Popen(["afplay", "-v", "1.0", path], stderr=subprocess.DEVNULL)
                time.sleep(0.12)
                if p.poll() is None or p.returncode == 0:
                    return p                      # playing (or already finished cleanly)
                if attempt == 0:
                    time.sleep(0.15)              # brief settle, then retry
            if fallback_text:
                return subprocess.Popen(["say", "-v", "Daniel", "-r", "184", fallback_text])
            return p

        # Synthesize + START the first chunk SYNCHRONOUSLY. speak() returns the instant audio
        # begins, so the caller shows the text at the same moment Nova starts talking (zero gap).
        started = False
        try:
            if edge_tts is not None:
                f0 = "/tmp/nova_tts_0.mp3"
                if _synth(chunks[0], f0) and gen == self._speak_gen:
                    self._say = _play(f0, chunks[0])
                    started = True
        except Exception:
            started = False

        if not started:
            try:  # offline / edge-tts failed -> instant built-in voice
                if gen == self._speak_gen:
                    self._say = subprocess.Popen(["say", "-v", "Daniel", "-r", "184", spoken])
            except Exception:
                nova.swallowed()
            return

        if len(chunks) > 1:                           # remaining chunks: synth + play in the background
            def _rest():
                prev = self._say
                for i in range(1, len(chunks)):
                    if gen != self._speak_gen:
                        return
                    f = "/tmp/nova_tts_%d.mp3" % i
                    try:
                        if not _synth(chunks[i], f):
                            return
                    except Exception:
                        return
                    if gen != self._speak_gen:
                        return
                    try:
                        prev.wait()
                    except Exception:
                        nova.swallowed()
                    if gen != self._speak_gen:
                        return
                    self._say = _play(f, chunks[i])
                    prev = self._say
            threading.Thread(target=_rest, daemon=True).start()

    def _kokoro_up(self):
        """Is the local Kokoro voice server answering? If not, start it (warms ~15s) and say no for now."""
        import urllib.request
        import socket
        try:   # port open = server alive. (An HTTP GET hung while it was busy synthesizing -> false "down"
            socket.create_connection(("127.0.0.1", 8089), timeout=0.3).close(); return True   # -> edge-tts talked over Daniel)
        except Exception:
            nova.swallowed()
        if not (self._kokoro_proc and self._kokoro_proc.poll() is None):
            self._kokoro_proc = subprocess.Popen(
                [os.path.expanduser("~/anish-ai/.mlx/bin/python"), os.path.expanduser("~/anish-ai/tts_server.py")],
                stdout=subprocess.DEVNULL, stderr=open("/tmp/nova_tts.log", "ab"))
        return False

    def _kokoro_to_hub(self, spoken):
        """Synthesize sentence by sentence on the M4 and ship each WAV to the hub as soon as it's ready."""
        import urllib.request
        if not self._kokoro_up():
            return False
        chunks = [c.strip() for c in re.split(r"(?<=[.!?:;])\s+", spoken) if c.strip()] or [spoken]   # ':' ';' too: lists were one 18s chunk
        m = re.match(r"(.{10,}?[,;:—])\s+(.{15,})$", chunks[0])   # long first sentence -> split at its first comma
        if len(chunks[0]) > 45 and m:                       # (synth time grows with length: 0.4s short vs ~1s long)
            chunks[0:1] = [m.group(1), m.group(2)]
        gen = self._speak_gen
        for i, ch in enumerate(chunks):
            if self._speak_gen != gen:                      # "Nova, stop" from the hub -> drop the rest
                return True
            try:
                wav = urllib.request.urlopen(urllib.request.Request(KOKORO_URL, data=ch.encode()), timeout=15).read()
            except Exception as e:
                print("[kokoro] failed: %s" % e, flush=True)
                if i == 0:
                    return False                          # nothing played yet -> caller falls back to edge-tts
                nova._hub_send("say", " ".join(chunks[i:])); return True
            nova._hub_send("audio", wav)
        return True

    _stt_wait = {}     # hub: request id -> [Event, text]

    def _mac_stt(self, wav_bytes, timeout=10.0):   # 4 s dropped follow-ups: Mac STT ~2 s, more while it speaks
        """Hub side: send a WAV to the Mac's local Whisper, wait for the text ('' on timeout)."""
        import uuid
        rid = uuid.uuid4().hex[:8]; ev = threading.Event(); self._stt_wait[rid] = [ev, ""]
        try:
            import paho.mqtt.client as mqtt
            c = nova.mqtt_client()
            nova._pub(c, [("home/mac/stt/" + rid, wav_bytes)])
            ev.wait(timeout)
            return self._stt_wait[rid][1]
        except Exception as e:
            print("[hf] mac stt err:", str(e)[:60], flush=True); return ""
        finally:
            self._stt_wait.pop(rid, None)

    _local_whisper = None

    def _local_stt(self, wav_bytes):
        """Mac side: faster-whisper base.en on CPU (0.6 s on the M4). Fed a numpy array — PyAV's file decode is broken here."""
        import io, wave, numpy as np
        if self._local_whisper is None:
            from faster_whisper import WhisperModel
            type(self)._local_whisper = WhisperModel("small.en", device="cpu", compute_type="int8", cpu_threads=8)
        w = wave.open(io.BytesIO(wav_bytes))
        a = np.frombuffer(w.readframes(w.getnframes()), np.int16).astype(np.float32) / 32768
        segs, _ = self._local_whisper.transcribe(a, language="en", beam_size=1, initial_prompt=STT_PROMPT)
        return " ".join(x.text for x in segs).strip()

    def _warm_stt(self):
        try:
            from faster_whisper import WhisperModel
            type(self)._local_whisper = type(self)._local_whisper or WhisperModel("small.en", device="cpu", compute_type="int8", cpu_threads=8)
        except Exception as e:
            print("[stt] local whisper unavailable:", e, flush=True)

    def _hub_audio_player(self):
        """Hub: play Kokoro WAVs from the Mac in order. _hub_speaking holds the mic off meanwhile."""
        n = 0
        while True:
            wav = self._audio_q.get()
            if time.time() < self._mute_until:      # interrupted -> the rest of that reply is stale
                self._hub_speaking = not self._audio_q.empty(); continue
            if not self._hub_speaking: self._table_voice(1)   # reply starts -> table strip follows the voice
            self._hub_speaking = True
            n += 1; path = "/tmp/nova_k_%d.wav" % (n % 4)
            try:
                with open(path, "wb") as f:
                    f.write(wav)
                print("[hub] play %.1fs" % ((len(wav) - 44) / 48000.0), flush=True)   # timing: reply reached the speaker
                try:                                 # voice fingerprint: remember what we play + when (echofp)
                    self._ref_segs = (self._ref_segs + [(time.time(), echofp.wav_env(wav))])[-8:]
                except Exception:
                    nova.swallowed()
                t0 = time.time()
                while self._local_talking and time.time() - t0 < 30: time.sleep(0.1)   # hub's own speech first
                self._clip_on = True
                self._say = subprocess.Popen(["afplay", path], stderr=subprocess.DEVNULL)
                self._say.wait()
            except Exception as e:
                print("[hub] audio play failed: %s" % e, flush=True)
            finally:
                self._clip_on = False
            if self._audio_q.empty():
                self._hub_speaking = False; self._table_voice(0)

    def _table_voice(self, on):
        """Table strip: its built-in mic mode while Nova talks, back to the room's light mode after (light_panel /voice)."""
        def go():
            import urllib.request
            try: urllib.request.urlopen("http://localhost:8099/voice?on=%d" % on, timeout=3)
            except Exception: nova.swallowed()                   # panel not running -> nothing to animate
        threading.Thread(target=go, daemon=True).start()

    def stop_speaking(self):
        self._speak_gen += 1               # abort any in-flight streaming loop
        try:
            if self._say and self._say.poll() is None:
                self._say.terminate()
        except Exception:
            nova.swallowed()
        subprocess.run(["pkill", "-x", "afplay"], capture_output=True)
        subprocess.run(["killall", "say"], capture_output=True)
        if not nova.IS_HUB:
            nova._hub_send("stop", "1")    # the voice plays on the hub's speaker — cut it there too

    def listen(self):
        """Record from the mic (auto-stops on silence) and transcribe locally with whisper."""
        wav = "/tmp/nova_listen.wav"
        try:
            os.remove(wav)
        except OSError:
            pass
        try:  # record 16k mono; start on sound, stop after ~1.0s of silence, hard cap via timeout
            subprocess.run(["sox", "-q", "-d", "-r", "16000", "-c", "1", wav,
                            "silence", "1", "0.1", "2%", "1", "1.0", "2%"],
                           capture_output=True, timeout=25)
        except subprocess.TimeoutExpired:
            pass
        except FileNotFoundError:
            return {"text": "", "error": "sox not found"}
        except Exception as e:
            return {"text": "", "error": f"mic error: {e}"}
        if not os.path.exists(wav) or os.path.getsize(wav) < 4000:
            return {"text": "", "error": "No audio — check mic access in System Settings"}
        try:
            r = subprocess.run([WHISPER, "-m", WHISPER_MODEL, "-f", wav, "-nt", "-np",
                                "-t", "8", "-bs", "1", "-bo", "1"],
                               capture_output=True, text=True, timeout=60)
            text = re.sub(r"\[.*?\]", "", r.stdout)          # drop [BLANK_AUDIO] etc.
            text = " ".join(text.split()).strip(" .")
            return {"text": text}
        except Exception as e:
            return {"text": "", "error": f"transcribe error: {e}"}

    def set_handsfree(self, on):
        """Toggle always-listening wake-word mode. Say 'Nova, <command>'."""
        on = bool(on)
        if on and nova.mics_off():                  # owner said "mic off": the hub's own mic stays off too (restarts included)
            print("[hf] not listening: mics are switched off (privacy)", flush=True); on = False
        if on and not self._hf:
            if self._hf_thread and self._hf_thread.is_alive():
                self._hf_thread.join(2.0)            # quick mute->unmute: let the old listener exit (no 2 loops on the mic)
            self._hf = True                      # mic selection now happens inside the loop (so a stalled
            self._hf_thread = threading.Thread(target=self._handsfree_loop, daemon=True)   # audio subprocess
            self._hf_thread.start()              # can't block the listener from ever starting)
        elif not on:
            self._hf = False
        return self._hf

    def _vad_session(self):
        if getattr(self, "_vad_sess", None) is None:
            import onnxruntime as ort
            o = ort.SessionOptions(); o.intra_op_num_threads = 1; o.inter_op_num_threads = 1
            self._vad_sess = ort.InferenceSession(os.path.expanduser("~/anish-ai/silero_vad.onnx"),
                                                  sess_options=o, providers=["CPUExecutionProvider"])
        return self._vad_sess

    def _vad_has_speech(self, audio, thr=55):
        """True if the clip is loud enough to be real speech (RMS energy gate). Silero VAD proved
        unreliable on this quiet mic (it rejected actual speech), so we use a low RMS gate to drop
        true silence — Whisper's hallucination blocklist handles the rest."""
        import numpy as np
        try:
            pcm = np.frombuffer(audio.get_raw_data(), dtype=np.int16).astype(np.float32)
            return pcm.size > 0 and float(np.sqrt(np.mean(pcm ** 2))) >= thr
        except Exception:
            return True                                  # never hard-block on error

    def _loud_wav(self, audio, target=2000.0):
        """Amplify quiet mic audio to a target RMS before Whisper, capped so it never clips.
        The built-in mic captures the user at rms ~100 — too quiet for Whisper (returns '');
        boosting to ~2000 makes clear-but-quiet speech readable without touching hardware gain."""
        import numpy as np, io, wave
        try:
            pcm = np.frombuffer(audio.get_raw_data(), dtype=np.int16).astype(np.float32)
            rms = float(np.sqrt(np.mean(pcm ** 2))) if pcm.size else 0.0
            peak = float(np.abs(pcm).max()) or 1.0
            if rms > 0:
                gain = min(target / rms, 30000.0 / peak)   # reach target RMS, but never exceed ~30k peak (no clip)
                pcm = np.clip(pcm * gain, -32768, 32767)
            pcm = pcm.astype(np.int16)
            buf = io.BytesIO()
            with wave.open(buf, "wb") as w:
                w.setnchannels(1); w.setsampwidth(2); w.setframerate(audio.sample_rate)
                w.writeframes(pcm.tobytes())
            return buf.getvalue()
        except Exception:
            return audio.get_wav_data()                    # never hard-fail -> fall back to raw

    def _handsfree_loop(self):
        """Always-listening, Whisper-based wake. Energy-VAD detects an utterance, Whisper transcribes
        it (Whisper handles the user's accent; openWakeWord did not), and if the transcript contains
        'Nova' (fuzzy, WAKE_RE) the rest becomes the command. Nova's own speech is filtered by
        an echo check, so it doesn't answer itself."""
        import numpy as np
        print("[hf] loop entered", flush=True)
        try:
            self._select_input_mic()             # pick the mic (USB lavalier preferred); never blocks startup
        except Exception:
            nova.swallowed()
        def _warm_nr():                          # pre-compile noisereduce's numba JIT so the 1st reply isn't slow
            try:
                import noisereduce as _nr
                _nr.reduce_noise(y=np.zeros(16000, np.float32), sr=16000, stationary=True)
            except Exception:
                nova.swallowed()
            if nova.IS_HUB:                      # model loads: 1st command after a restart paid ~2 s (voice match) + ~3 s (Whisper)
                try:
                    sys.path.insert(0, os.path.expanduser("~/anish-ai")); import localstt, speaker as _sp
                    if localstt.available(): localstt._recognizer(); localstt.has_speech(np.zeros(1600, np.int16))
                    if os.path.exists(_sp.MODEL): _sp._extractor()
                except Exception:
                    nova.swallowed()
        threading.Thread(target=_warm_nr, daemon=True).start()
        try:
            import pyaudio
        except Exception as e:
            self._hf = False
            self._js("window.novaMicReset && window.novaMicReset();")
            self._placeholder("Listener unavailable: " + str(e)[:40])
            print("[hf] import fail:", repr(e), flush=True)
            return

        RATE, FRAME = 16000, 1280            # 80ms int16 frames @ 16kHz
        pa = pyaudio.PyAudio()
        # Pick a REAL, PortAudio-visible input device explicitly. Never trust the system default —
        # _select_input_mic or a USB adapter can point it at a device PortAudio can't read (silence).
        cands = [(i, pa.get_device_info_by_index(i)["name"]) for i in range(pa.get_device_count())
                 if pa.get_device_info_by_index(i).get("maxInputChannels", 0) > 0
                 and "teams" not in pa.get_device_info_by_index(i)["name"].lower()]
        usb     = next((i for i, n in cands if "usb" in n.lower()), None)
        builtin = next((i for i, n in cands if "macbook" in n.lower() or "built-in" in n.lower()), None)
        dev_idx = usb if usb is not None else (builtin if builtin is not None else (cands[0][0] if cands else None))
        dev_name = pa.get_device_info_by_index(dev_idx)["name"] if dev_idx is not None else "default"
        print("[hf] input devices=%s -> using #%s '%s'" % (cands, dev_idx, dev_name), flush=True)
        _nm = None
        _bed_off = os.path.exists(os.path.expanduser("~/anish-ai/.bedmic_off"))   # touch it = use the USB mic
        if _bed_off: print("[hf] bed mic disabled (~/anish-ai/.bedmic_off) -> USB mic", flush=True)
        if nova.IS_HUB and not _bed_off:     # bedside ESP32 mic (iot/esp32_bedmic) wins when it's streaming
            try:
                from netmic import NetMic
                _nm = NetMic()
                _t0 = time.time()
                while time.time() - _t0 < 3 and not _nm.alive():
                    time.sleep(0.1)
            except Exception as e:
                print("[hf] netmic unavailable: %r" % e, flush=True); _nm = None
            _use_net = bool(_nm and _nm.alive())
            self._netmic = _nm if _use_net else None

            def _mic_watch():                # source changed -> exit; launchd relaunches and recalibrates the floor
                seen = 0
                while True:
                    time.sleep(2)
                    if _use_net and not _nm.alive(10):
                        why = "bed mic went silent"
                    elif not _use_net and _nm and _nm.alive(1):
                        seen += 1
                        if seen < 3: continue
                        why = "bed mic came online"
                    else:
                        seen = 0; continue
                    print("[hf] %s -> restarting to switch mics" % why, flush=True)
                    subprocess.run(["pkill", "-f", "cam_presence.py"])   # it outlives us and holds the camera
                    os._exit(3)
            threading.Thread(target=_mic_watch, daemon=True).start()
            if _use_net:
                dev_name = "bedmic"
                print("[hf] using bedside mic (UDP :5005)", flush=True)
        try:
            stream = _nm if (_nm and _use_net) else pa.open(rate=RATE, channels=1, format=pyaudio.paInt16,
                             input=True, input_device_index=dev_idx, frames_per_buffer=FRAME)
        except Exception as e:
            self._hf = False
            self._js("window.novaMicReset && window.novaMicReset();")
            self._placeholder("Mic open failed: " + str(e)[:50])
            print("[hf] MIC FAIL:", repr(e), flush=True)
            return

        _HALLUC = {"thank you", "thanks", "thank you.", "you", "thanks for watching", "bye",
                   "bye.", ".", "..", "...", "so", "okay", "uh", ""}

        def read():
            try:
                return np.frombuffer(stream.read(FRAME, exception_on_overflow=False), dtype=np.int16)
            except Exception:
                return np.zeros(FRAME, dtype=np.int16)

        def rms_of(f):   # plain RMS: a 300-3400 Hz voice-band meter was tried 2026-11-08 and HALVED voice SNR (voice energy sits <300 Hz too)
            return float(np.sqrt(np.mean(f.astype(np.float32) ** 2))) if f.size else 0.0

        def _spk(pcm):
            """Voice fingerprint of a clip (speaker.py); None if unavailable - then nothing is filtered."""
            if not speaker: return None
            try: return speaker.embed(pcm, gate=trigger)   # speech frames only: room noise fingerprints the room
            except Exception as e:
                print("[spk]", type(e).__name__, e, flush=True); return None

        def _spoken(pcm):
            return speaker.voiced(pcm, trigger).size / 16000.0 if speaker else 0.0

        def _keep(pcm, kind, sc=None):
            """Record of the owner's voice (and rejected voices) for tests -> voice_samples/ (speaker.keep)."""
            if speaker and nova.IS_HUB:
                try: speaker.keep(pcm, kind, sc)
                except Exception as e: print("[spk] keep:", e, flush=True)

        def transcribe(pcm):
            if pcm.size < RATE * 0.2:                # <0.2s -> nothing said
                return ""
            p = pcm.astype(np.float32)
            try:                                     # spectral noise reduction: lifts the voice out of
                import noisereduce as _nr            # room/AC noise so Whisper reads a quiet mic correctly
                p = _nr.reduce_noise(y=p, sr=RATE, stationary=True, prop_decrease=0.85).astype(np.float32)
            except Exception:
                nova.swallowed()
            r0 = float(np.sqrt(np.mean(p ** 2))) or 1.0   # then amplify to Whisper's sweet spot, no clip
            pk = float(np.abs(p).max()) or 1.0
            p = np.clip(p * min(2000.0 / r0, 30000.0 / pk), -32768, 32767).astype(np.int16)
            import io, os, wave, shutil, tempfile, subprocess, requests
            buf = io.BytesIO()
            with wave.open(buf, "wb") as w:
                w.setnchannels(1); w.setsampwidth(2); w.setframerate(RATE); w.writeframes(p.tobytes())
            wav_bytes = buf.getvalue()
            try:                                     # keep the last 20 clips -> test STT fixes on real audio
                os.makedirs("/tmp/nova_stt", exist_ok=True)
                open("/tmp/nova_stt/%d.wav" % int(time.time() * 1000), "wb").write(wav_bytes)
                for old in sorted(os.listdir("/tmp/nova_stt"))[:-20]: os.unlink("/tmp/nova_stt/" + old)
            except Exception:
                nova.swallowed()

            txt = ""
            # 1) LOCAL Whisper base.en (sherpa-onnx, ~1 s on the hub): no network, no quota, no limits
            try:
                sys.path.insert(0, os.path.expanduser("~/anish-ai")); import localstt
                if localstt.available():
                    t0 = time.time(); txt = localstt.transcribe(p, RATE)
                    print("[hf] local stt %.2fs: %d chars" % (time.time() - t0, len(txt)), flush=True)   # text not logged: privacy
                    if not txt: return ""            # local heard no speech -> don't burn the cloud quota on noise
            except Exception as e:
                print("[hf] local stt err:", str(e)[:60], flush=True)

            # 2) fall back to Groq only if local gave nothing
            if not txt:
                gk = self._key("groq")
                if gk:
                    try:
                        r = requests.post("https://api.groq.com/openai/v1/audio/transcriptions",
                                          headers={"Authorization": "Bearer " + gk},
                                          files={"file": ("speech.wav", wav_bytes, "audio/wav")},
                                          data={"model": "whisper-large-v3", "language": "en", "temperature": "0",
                                                "prompt": STT_PROMPT},
                                          timeout=5)
                        if r.ok:
                            txt = (r.json().get("text") or "").strip()
                        else:
                            print("[hf] whisper HTTP %s" % r.status_code, flush=True)
                    except Exception as e:
                        print("[hf] whisper err:", str(e)[:60], flush=True)

            # 3) Groq rate-limited/offline -> the Mac's local Whisper (base.en, ~0.6 s) over MQTT
            if not txt and nova.IS_HUB and self._mac_online:
                txt = self._mac_stt(wav_bytes)
                if txt: print("[hf] mac-local stt: %d chars" % len(txt), flush=True)

            if not txt or txt.lower().strip(" .,!?") in _HALLUC:
                return ""
            return self._vp_correct(txt)

        def record_command(floor, seed=None, hang_ms=900, max_s=12.0, start_ms=2500):
            """After the wake word: wait up to start_ms for the command to start, then capture
            until ~hang_ms of trailing silence (or max_s). `seed` is the rolling pre-roll buffer
            (frames captured just before/during the wake) so a command spoken in the same breath
            as 'Hey Nova' isn't truncated at the start. Threshold is RELATIVE to the room."""
            speech = max(floor * 1.8, 45.0)      # far-corner voice peaks ~450-800; 3x floor (836) dropped everything past 1m
            hang = int(hang_ms / 80); start_frames = int(start_ms / 80)
            min_frames = 2                       # 2 loud frames is enough: real speech rarely stays >3x floor for 0.6s
            quiet = max(floor * 1.6, 60.0)       # below this = true silence (room ~270, soft speech ~450-700)
            frames = list(seed) if seed else []; spoke = False; silent = 0; n = 0; spoke_n = 0; _trace = []
            while self._hf and n < int(max_s * 1000 / 80):
                n += 1
                f = read(); frames.append(f)
                _r = rms_of(f); _trace.append(int(_r))
                self._lvl_i = (getattr(self, "_lvl_i", 0) + 1) % 2   # keep the HUD bars live WHILE you speak
                if self._lvl_i == 0:
                    self._js("window.novaLevel&&window.novaLevel(%.3f)"
                             % max(0.0, min(1.0, (_r - floor) / max(1.0, speech * 2 - floor))))
                if _r > speech:
                    spoke = True; silent = 0; spoke_n += 1
                elif spoke and _r > quiet:
                    silent = 0; spoke_n += 1         # still talking softly -> not the end of your turn
                elif spoke:
                    silent += 1
                    if silent >= hang and spoke_n >= min_frames:
                        break
                elif n >= start_frames:
                    break                            # nobody spoke after the beep -> bail
            pcm = np.concatenate(frames) if frames else np.array([], dtype=np.int16)
            print("[hf] recorded %.1fs (thr=%.0f spoke=%s)" % (pcm.size / 16000.0, speech, spoke), flush=True)
            if True:    # level trace (also for rejected tries -> tune far-field) (one value per 80ms) -> tune the end-of-turn threshold from real data
                print("[hf] trace " + " ".join(map(str, _trace)), flush=True)
            return pcm if spoke else pcm[:0]     # only noise -> skip STT (Whisper invents words from hiss, wastes quota)

        def ask(question):
            """Speak a question, wait for it to finish, return what you answer ("" if nothing)."""
            self.speak(question)
            _t = time.time()
            while self._say and self._say.poll() is None and time.time() - _t < 8:
                read()
            subprocess.run(["afplay", "-v", "0.5", EARCON], stderr=subprocess.DEVNULL)   # beep = your turn
            try:                                       # drop Nova's voice + the beep from the buffer
                while stream.get_read_available() >= FRAME: stream.read(FRAME, exception_on_overflow=False)
            except Exception:
                nova.swallowed()
            ans = transcribe(record_command(floor, hang_ms=hang_ms, start_ms=4000)) or ""
            print("[hf] answer=%r" % ans, flush=True)
            return ans

        def train_voice():
            """'learn my voice': Nova reads each command, you repeat it; whatever Whisper hears is stored as
            a fix for that command (phrases), and a misheard "Nova" becomes a wake-word correction."""
            vp = self.vprofile; ph = vp.setdefault("phrases", {}); cor = vp["corrections"]
            self.speak("Voice training, sir: repeat each command after the beep, or say stop to finish")   # one sentence: ask() waits for the first chunk only
            for want in ["Nova"] + _SEED_CMDS:
                for _try in (1, 2):
                    got = ask(want + ".").lower().strip(" .,!?")
                    if got: break
                if got in ("stop", "finish", "done", "enough", "stop training"): break
                print("[train] %r heard as %r" % (want, got), flush=True)
                if len(got) < 3 or got == want.lower() or "skip" in got: continue   # "oh" = clipped, not a mishearing
                if want == "Nova":
                    if len(got.split()) > 2: continue   # a sentence, not the name
                    for w in got.split():   # misheard wake word -> fix that word (not real words like 'no')
                        if w not in ("nova", "no", "now", "know", "oh", "yo", "the", "a", "not", "go") and len(w) > 2:
                            cor[w] = "Nova"
                else:
                    ph[got] = want.lower()
            self._save_vprofile()
            self.speak("Done, sir. I've learned your voice.")
            print("[train] phrases=%d corrections=%d" % (len(ph), len(cor)), flush=True)

        def run_cmd(cmd):
            if nova.IS_HUB and re.search(r"\b(learn|train)\b.*\bvoice\b", cmd.lower()):
                return train_voice()
            cmd = self._vp_guess(cmd, ask)    # learned fix, or "Did you mean ...?" for a garbled short command
            self._vp_learn(cmd)               # just do the task — don't type the heard command into the box
            try:
                _t = time.time()
                if nova.IS_HUB:   # the hub is only ears: the Mac's Nova thinks + answers
                    if self._mac_online:
                        self._mac_busy, self._busy_ts = True, time.time(); nova._hub_send("heard", cmd); print("[hf] -> mac: %r" % cmd, flush=True)
                        subprocess.Popen(["afplay", "-v", "0.35", EARCON], stderr=subprocess.DEVNULL)   # "got it" chime covers the think gap
                        return
                    print("[hf] mac away (lid closed?) — hub answers %r itself" % cmd, flush=True)   # cloud brains + hub speaker
                r = self.chat(cmd)
                print("[hf] brain+speak=%.2fs reply=%r" % (time.time() - _t, (r.get("reply", "") if isinstance(r, dict) else str(r))[:80]), flush=True)
            except Exception as e:
                print("[hf] chat error: %r" % e, flush=True)

        # wait out the startup greeting so the floor isn't polluted by Nova's own voice
        _tw = time.time()
        while self._hf and self._say and self._say.poll() is None and time.time() - _tw < 25:
            read()
        _boot = [rms_of(read()) for _ in range(62)]   # ~5 s of the room; p80 like the rolling floor below
        floor = float(np.percentile(_boot, 80) or 20.0)   # (median of 1.6 s set 121 in a ~300 room -> noise recorded nonstop)
        trigger = max(floor * 1.15, 52.0)        # sensitive: user's voice sits ~75-130, close to the room floor
        # calibration (from calibrate.py): tuned to how THIS user actually talks — level, pauses, speed
        calib = {}
        try:
            calib = json.load(open(os.path.expanduser("~/anish-ai/voice_calib.json")))
        except Exception:
            nova.swallowed()
        if calib.get("mic") and calib["mic"].lower() not in str(dev_name).lower():
            calib = {}                           # calibrated on a different mic -> its levels don't apply here
        if calib.get("trigger"):
            trigger = max(float(calib["trigger"]), floor * 1.15)   # never below the room's own noise
        trigger = max(trigger, floor * 2.2)      # same rule as the rolling floor (1.15x / 1.6x fired on room noise)
        hang_ms  = int(calib.get("hang_ms", 700))       # end-of-turn silence: 900ms felt sluggish (2026-11-08 timing test)
        barge_rms = float(calib.get("barge_rms", 170))  # loudness that counts as you cutting in
        print("[hf] listening (floor=%.0f trigger=%.0f hang=%dms barge=%.0f%s) — say 'Nova ...'"
              % (floor, trigger, hang_ms, barge_rms, " CAL" if calib else ""), flush=True)
        self._placeholder('Say "Nova ..."')
        import collections
        idle = collections.deque(_boot, maxlen=375)   # ~30 s of idle mic levels -> rolling noise floor
        trig_min = max(52.0, float(calib.get("trigger", 0)))
        hot = 0                                  # consecutive frames above trigger
        ring = collections.deque(maxlen=14)      # ~1.1s rolling pre-roll so no start clipping

        def is_echo(t):
            """Did Nova just say (most of) this? Then the mic heard itself -> ignore."""
            last = getattr(self, "_last_spoken", "")
            if not last or time.time() - getattr(self, "_spoken_at", 0) > 20:
                return False
            hw = [w for w in re.findall(r"\w+", t.lower()) if len(w) > 2]
            if len(hw) < 2:
                return False
            lastset = set(re.findall(r"\w+", last))
            return sum(1 for w in hw if w in lastset) / len(hw) >= 0.6

        cooldown = 0
        try:
            while self._hf:
                f = read(); ring.append(f)
                if cooldown > 0:
                    cooldown -= 1
                    continue
                if self._say and self._say.poll() is None:   # Nova is speaking (e.g. the boot greeting)
                    continue                                 # -> don't record its own voice as a command
                _r = rms_of(f)
                idle.append(_r)                     # floor follows the room: startup can be noisy (bed mic at the pillow)
                if len(idle) >= 60 and len(idle) % 25 == 0:
                    # ponytail: p80 not p20 - fan/AC noise comes in bursts; p20*1.6 sat under every burst and
                    # recorded 12 s of noise nonstop (763/763 clips). p80*2.2 + 2 frames: 101/763. Wake model = real fix.
                    floor = float(np.percentile(idle, 80)); trigger = max(trig_min, floor * 2.2)
                # live mic level -> HUD input bars (throttled to every 2nd frame)
                self._lvl_i = (getattr(self, "_lvl_i", 0) + 1) % 2
                if self._lvl_i == 0:
                    _lv = max(0.0, min(1.0, (_r - floor) / max(1.0, trigger * 3 - floor)))
                    self._js("window.novaLevel&&window.novaLevel(%.3f)" % _lv)
                if _r < trigger:                    # wait for speech to clearly begin
                    hot = 0; continue
                hot += 1
                if hot < 2:                         # one loud frame = a noise spike; speech holds >= 160 ms
                    continue
                hot = 0
                # speech detected -> capture the whole utterance (with pre-roll) and transcribe it
                self._placeholder("Listening…")
                _pcm = record_command(floor, seed=list(ring), hang_ms=hang_ms)
                _t = time.time()
                text = transcribe(_pcm)
                spk_ref, spk_s = None, 0.0           # filled below once this turns out to be a real "Nova ..."
                print("[hf] stt=%.2fs" % (time.time() - _t), flush=True)
                ring.clear()
                if not text:
                    continue
                if is_echo(text):                    # Nova heard its own voice
                    print("[hf] echo ignored: %r" % text, flush=True)
                    continue
                if os.path.exists(nova.ALARM_F) and nova.AWAKE_RE.search(text):   # "good morning" stops the alarm (no "Nova" needed)
                    nova.alarm_off("mic"); continue
                m = WAKE_RE.search(text)
                # privacy: only Nova commands are logged word for word; background talk/TV -> just its length
                print("[hf] heard=%r nova=True" % text if m else "[hf] heard (no wake, %d words)" % len(text.split()), flush=True)
                if not m and not DIRECT_CMD(text):
                    continue                          # no 'Nova' and not a clear device command -> background speech
                if self._say and self._say.poll() is None:
                    self.stop_speaking()             # barge-in: cut any current reply
                spk_ref = _spk(_pcm)                 # the voice that woke Nova = the only voice follow-ups accept
                spk_s = _spoken(_pcm)                # seconds of SPEECH behind spk_ref (short = weak, never rejects)
                _keep(_pcm, "wake")
                cmd = re.sub(r"\s+", " ", WAKE_RE.sub(" ", text)).strip(" ,.?!")
                print("[hf] cmd=%r" % cmd, flush=True)
                if not cmd:   # just "Nova" + a pause: you're usually about to say more -> listen 1.5s before "Yes, sir?"
                    _mp = record_command(floor, hang_ms=hang_ms, start_ms=1500)
                    more = transcribe(_mp)
                    if more and not is_echo(more) and _mp.size:   # "Nova?" alone is too short to know the voice
                        spk_ref, spk_s = _spk(np.concatenate([_pcm, _mp])), _spoken(_pcm) + _spoken(_mp)
                    if more and not is_echo(more):
                        cmd = re.sub(r"\s+", " ", WAKE_RE.sub(" ", more)).strip(" ,.?!")
                        print("[hf] cmd (after pause)=%r" % cmd, flush=True)
                if not cmd:
                    self.speak("Yes, sir?")
                else:
                    run_cmd(cmd)

                # CONVERSATION MODE: keep talking naturally — no need to repeat "Nova" — until you go quiet.
                convo = True
                while self._hf and convo:
                    win, win_t, n_stt, barge_cmd, started = [], [], 0, None, False
                    while self._hf and (self._mac_busy or self._hub_speaking) and time.time() - self._busy_ts < 180:
                        f = read()                    # hub: Mac thinking / reply playing
                        started = started or self._hub_speaking      # from the first chunk on, keep listening
                        if not (nova.IS_HUB and started):            # across the gaps between reply chunks
                            continue
                        # INTERRUPT: no echo-cancel here, so listen for the NAME, not loudness. Transcribe 2s
                        # windows of the reply (max 6/reply: Groq STT quota); "Nova ..." in one -> stop talking.
                        win.append(f)                 # capture time = now minus what's still buffered behind this frame
                        win_t.append(time.time() - stream.get_read_available() / float(RATE))
                        if len(win) < 25:
                            continue
                        env = [rms_of(x) for x in win]; t_first = win_t[0] - echofp.FRAME_S
                        pcm, win, win_t = np.concatenate(win), win[-5:], win_t[-5:]
                        if n_stt >= 6 or max(env) < trigger:
                            continue                  # quota used, or silence (Mac still looking it up)
                        fp = echofp.echo_score(env, self._ref_segs, t_first)   # ~1 = Nova's own voice, low = a person
                        if FP_ACTIVE and fp >= echofp.ECHO:
                            print("[fp] %.2f nova's own voice -> skip" % fp, flush=True)
                            continue
                        n_stt += 1
                        heard = transcribe(pcm) or ""
                        print("[hf] over-reply heard %r [fp] %.2f" % (heard[:80], fp), flush=True)
                        wm = WAKE_RE.search(heard)
                        mine = set(re.findall(r"[a-z']+", getattr(self, "_last_spoken", "").lower()))
                        sw = [w for w in re.findall(r"\b(stop|enough|quiet|shut|wait|hold)\b", heard.lower()) if w not in mine]
                        you = FP_ACTIVE and len(heard.split()) >= 2 and not is_echo(heard)   # fingerprint: not Nova -> you
                        if not (wm or sw or you):     # "Nova" blends into my voice ("No, I'll stop") -> a stop word
                            continue                  # that I'M not saying also counts
                        print("[hf] INTERRUPT: %r" % heard, flush=True)
                        self._mute_until = time.time() + 4
                        try:
                            while not self._audio_q.empty(): self._audio_q.get_nowait()
                        except Exception:
                            nova.swallowed()
                        self.stop_speaking(); self._hub_speaking = False
                        nova._hub_send("heard", "__stop__")   # Mac: stop synthesizing the rest
                        rest = (heard[wm.end():] if wm else heard if you and not sw else "").strip(" ,.?!").lower()
                        if rest and not re.fullmatch(r"(stop|wait|enough|quiet|shut up|hold on|pause|ok(ay)?|that'?s enough|thanks?( you)?)[ .,!]*", rest):
                            barge_cmd = rest
                        break
                    if barge_cmd:                     # "Nova, what about tomorrow?" -> answer that instead
                        ring.clear(); run_cmd(barge_cmd); continue
                    barged = False; _bn = 0          # let you cut in by talking over the reply (barge-in)
                    while self._hf and self._say and self._say.poll() is None:
                        bf = read()
                        # hub: the speaker sits next to the mic, so Nova's own voice always "barged in" and cut
                        # every reply off. No echo-cancel here -> no barge-in on the hub; just let it finish.
                        if not nova.IS_HUB and rms_of(bf) > barge_rms:
                            _bn += 1
                            if _bn >= 3:              # ~0.24s of real speech over the reply
                                print("[hf] BARGE — you cut in", flush=True)
                                self.stop_speaking(); ring.clear(); ring.append(bf); barged = True; break
                        else:
                            _bn = 0
                    if not barged:
                        try:                          # drop the echo buffered while it was speaking
                            while stream.get_read_available() >= FRAME:
                                stream.read(FRAME, exception_on_overflow=False)
                        except Exception:
                            nova.swallowed()
                        ring.clear()
                    self._placeholder("Listening… — just talk, no need to say Nova")
                    got = ""; _end = time.time() + 20   # listen ~20s for a follow-up (no wake word needed)
                    while self._hf and time.time() < _end:
                        f2 = read(); ring.append(f2)
                        if rms_of(f2) >= trigger:
                            _fp = record_command(floor, seed=list(ring), hang_ms=hang_ms)
                            ring.clear()
                            _e = _spk(_fp); _sc = speaker.score(spk_ref, _e) if speaker else None
                            print("[spk] follow-up voice match %s (ref %.1fs)" % ("%.2f" % _sc if _sc is not None else "n/a", spk_s), flush=True)
                            if speaker.ENFORCE and _sc is not None and _sc < speaker.SAME and spk_s >= speaker.REF_MIN_S:
                                print("[spk] another voice (TV / someone else) -> ignored", flush=True)
                                _keep(_fp, "other", _sc)
                                continue             # keep the conversation open for the real speaker
                            got = transcribe(_fp)
                            if got and not is_echo(got): _keep(_fp, "you" if _sc is None or _sc >= speaker.SAME else "unsure", _sc)
                            if got and not is_echo(got) and _e is not None:   # learn the voice as we go
                                spk_ref = _e if spk_ref is None else (spk_ref + _e) / np.linalg.norm(spk_ref + _e)
                                spk_s += _spoken(_fp)
                            if got and not is_echo(got):
                                break
                            got = ""             # noise / Nova's own echo -> keep the conversation open
                    ring.clear()
                    if not got or is_echo(got):
                        convo = False; break          # quiet (or heard itself) -> end the conversation
                    follow = re.sub(r"\s+", " ", WAKE_RE.sub(" ", got)).strip(" ,.?!")
                    print("[hf] follow=%r" % follow, flush=True)
                    if not follow:
                        convo = False; break
                    if _END_RE.search(follow):        # "that's all", "thanks Nova" -> close the conversation
                        print("[hf] conversation ended by %r" % follow, flush=True)
                        self.speak("Very good, sir."); convo = False; break
                    # no "Nova asked a question -> accept anything" bypass: TV lines got taken as answers and the
                    # replies (often questions) kept the loop going. TO_NOVA sees Nova's question, so real answers pass.
                    if not (DIRECT_CMD(follow) or WAKE_RE.search(got)) and \
                            not TO_NOVA(follow, getattr(self, "_last_spoken", "")):
                        print("[hf] follow ignored (talking to someone else)", flush=True)
                        convo = False; break
                    run_cmd(follow)
                ring.clear(); cooldown = 4
                self._placeholder('Say "Nova ..."')
        except Exception as e:
            print("[hf] loop fatal:", repr(e), flush=True)
            self._placeholder("Listener error: " + str(e)[:50])
        finally:
            try:
                stream.stop_stream(); stream.close(); pa.terminate()
            except Exception:
                nova.swallowed()

    def _select_input_mic(self):
        """Prefer a plugged-in USB mic (the lavalier adapter) for INPUT; fall back to the built-in mic.
        INPUT device only — never touches the user's output/speakers. Returns the device now selected."""
        sas = "/opt/homebrew/bin/SwitchAudioSource"      # abs path: app may launch with a minimal PATH
        if not os.path.exists(sas):                       # hub: no tool to pick the device, but still set the gain
            if not self._ducked: self._set_input_gain(self._mic_gain)
            return None
        try:
            devs = subprocess.run([sas, "-a", "-t", "input"],
                                  capture_output=True, text=True, timeout=5).stdout
            # Prefer the USB lavalier (AB13X) — a close mic with far better SNR than the built-in
            # (rms ~329 vs ~71). It's a real PortAudio device when properly connected. Make it the
            # system default so the listener's explicit open of it actually delivers audio.
            lines = [l.strip() for l in devs.splitlines() if l.strip()]
            usb = next((l for l in lines if "usb" in l.lower() or "ab13x" in l.lower()), None)
            target = usb or "MacBook Air Microphone"
            cur = subprocess.run([sas, "-c", "-t", "input"],
                                 capture_output=True, text=True, timeout=5).stdout.strip()
            if target in devs and cur != target:
                subprocess.run([sas, "-t", "input", "-s", target], capture_output=True, timeout=5)
            self._mic_gain = 100 if usb else 85  # the AB13X lavalier attenuates below 100 -> keep it at full
            self._close_mic = bool(usb)          # close mic -> skip ducking so barge-in still hears you
            if not self._ducked:                 # don't override while ducked mid-speech
                self._set_input_gain(self._mic_gain)
            return target
        except Exception:
            return None

    def _set_input_gain(self, level):
        subprocess.run(["osascript", "-e", "set volume input volume %d" % level], capture_output=True, timeout=5)

    def _duck_loop(self):
        """While Nova is speaking, drop the mic gain so it barely hears itself; restore the instant
        it stops. Cuts self-echo/self-answering on a single-mic setup. Interrupt still works via
        Esc / click-orb / STOP button (mic-independent)."""
        while True:
            time.sleep(0.15)
            if self._close_mic:                          # close lavalier barely hears the speaker ->
                continue                                 # no ducking, so barge-in stays responsive
            speaking = bool(self._say and self._say.poll() is None)
            if speaking and not self._ducked:
                self._ducked = True
                self._set_input_gain(15)                 # low, not muted — a loud "stop" can still get through
            elif not speaking and self._ducked:
                self._ducked = False
                self._set_input_gain(self._mic_gain)     # back to normal for the current mic

    # ---------- voice profile: learns your timing + vocabulary ----------
    VPROFILE_PATH = os.path.expanduser("~/anish-ai/voice_profile.json")

    def _load_vprofile(self):
        base = {"energy": None, "pause": 2.0, "vocab": {}, "corrections": {}, "n": 0}
        try:
            with open(self.VPROFILE_PATH) as f:
                base.update(json.load(f))
        except Exception:
            nova.swallowed()
        return base

    def _save_vprofile(self):
        try:
            vp = dict(self.vprofile)
            vp["vocab"] = dict(sorted(vp["vocab"].items(), key=lambda kv: -kv[1])[:400])  # keep it bounded
            with open(self.VPROFILE_PATH, "w") as f:
                json.dump(vp, f)
        except Exception:
            nova.swallowed()

    def _vp_learn(self, text):
        """After a successful command, learn your words (builds a personal vocabulary) + adapt timing."""
        vp = self.vprofile
        for w in re.findall(r"[a-z]{3,}", text.lower()):
            vp["vocab"][w] = vp["vocab"].get(w, 0) + 1
        vp["n"] += 1
        # cut-off detection: two commands in quick succession suggests it ended your phrase too early
        now = time.time()
        if 0 < now - self._last_cmd_at < 2.2:
            vp["pause"] = min(3.2, round(vp["pause"] + 0.15, 2))   # wait a touch longer before deciding you're done
        self._last_cmd_at = now
        if vp["n"] % 5 == 0:
            self._save_vprofile()

    def _vp_guess(self, cmd, ask):
        """Learn from your corrections. Known-good commands = every clear device command you've given (+ a seed
        list). A short command that isn't one -> closest known one -> "Did you mean X?" -> yes = run X and
        remember the mishearing, so next time it's fixed silently. Questions/long sentences pass through as heard."""
        import difflib
        vp = self.vprofile
        ph, good = vp.setdefault("phrases", {}), vp.setdefault("good", {})
        low = cmd.lower().strip(" .,!?")
        if low in ph:
            print("[hf] learned fix: %r -> %r" % (low, ph[low]), flush=True)
            return ph[low]
        if DIRECT_CMD(low):
            good[low] = good.get(low, 0) + 1
            return cmd
        if len(low.split()) > 5 or _QUESTION_RE.match(low):
            return cmd
        def score(c):   # same word count -> word-by-word ("lazy off" ~ "laser off", not "ac off"); else whole string
            w1, w2 = low.split(), c.split()
            if len(w1) == len(w2):
                return sum(difflib.SequenceMatcher(None, x, y).ratio() for x, y in zip(w1, w2)) / len(w1)
            return 0.9 * difflib.SequenceMatcher(None, low, c).ratio()
        # ponytail: spelling similarity only; a phonetic match would catch more, add it if guesses miss often
        best = max(set(good) | set(_SEED_CMDS), key=score)
        if score(best) < 0.65:
            return cmd
        m = [best]
        ans = ask("Did you mean %s?" % m[0]).lower()
        if re.search(r"\b(yes|yeah|yep|yup|correct|right|sure|haan|ha|do it|ok(ay)?)\b", ans):
            ph[low] = m[0]; good[m[0]] = good.get(m[0], 0) + 1
            self._save_vprofile()
            print("[hf] learned: %r means %r" % (low, m[0]), flush=True)
            return m[0]
        return cmd                                    # no / silence -> send what was heard

    def _vp_correct(self, text):
        """Fuzzy-snap near-miss words to your frequent vocabulary + apply learned corrections. Fixes
        the words STT keeps mis-hearing for *your* voice (names, apps, jargon)."""
        import difflib
        vp = self.vprofile
        fixes = {**STT_FIXES, **vp["corrections"]}
        text = " ".join(fixes.get(w.lower().strip(".,!?"), w) for w in text.split())   # explicit corrections
        common = [w for w, c in vp["vocab"].items() if c >= 3]
        if not common:
            return text
        out = []
        for w in text.split():
            lw = w.lower()
            if lw in vp["vocab"] or len(lw) < 4:
                out.append(w); continue
            m = difflib.get_close_matches(lw, common, n=1, cutoff=0.82)   # snap only very-near misses
            # never snap a plural onto its singular: "evening lights" -> "evening light" broke routine phrases
            out.append(m[0] if m and lw.rstrip("s") != m[0].rstrip("s") else w)
        return " ".join(out)
