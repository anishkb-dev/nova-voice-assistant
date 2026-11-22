"""Chat: command shortcuts, LLM tiers (Groq / local MLX / Ollama / Claude), tool calls, safety confirm + audit.
Mixin of nova_app.Api (split out of nova_app.py verbatim, cleanup fix 10, 2026-11-17)."""
from nova_common import *   # noqa: F403 - the constants/helpers nova_app always had at module level


class Brain:

    def chat(self, user):
        """One user turn. Deterministic intercepts first, then the tiered brain (Claude->Groq->Qwen)."""
        self._js("window.novaHeard&&window.novaHeard(%s)" % json.dumps(user))   # HUD shows voice commands too
        low = user.lower()
        wants_stop = re.search(r"\b(stop|pause|halt|silence|quiet|shut up|enough|turn it off)\b", low)
        mpv_on = nova.music_playing()                     # mpv here, afplay on the hub
        if wants_stop and (mpv_on or "music" in low or "song" in low or "playing" in low):
            nova.FUNCS["stop_music"]()
            reply = "Music stopped, sir."
            self.messages += [{"role": "user", "content": user},
                              {"role": "assistant", "content": reply}]
            self.speak(reply)
            return {"reply": reply, "activity": ["stop_music()"]}

        # ROUTINES (~/anish-ai/routines.json): "good night", "I'm leaving", "movie time"... -> run a scene.
        _rt = self._match_routine(low)
        if _rt:
            reply = self._run_routine(*_rt)
            self.messages += [{"role": "user", "content": user}, {"role": "assistant", "content": reply}]
            self.messages = self.messages[-20:]; self.speak(reply)
            return {"reply": reply, "activity": ["routine:%s" % _rt[0]]}

        # CLAUDE: "Claude, ..." / "ask Claude ..." -> straight to Claude Code (ongoing thread), bypass the local brain.
        # STT often writes Claude as cloud/clod/clawed/claud.
        _cm = re.match(r"^\W*(?:hey\s+|ok\s+|okay\s+|ask\s+|tell\s+)?(?:claude|claud|clod|cloud|clawed)\b[\s,:.!?-]*(.*)$",
                       user, re.IGNORECASE | re.S)
        if _cm:
            q = _cm.group(1).strip()
            if not q:
                reply = "I'm listening, sir."
            else:
                new = bool(re.fullmatch(r"(start\s+)?(a\s+)?(new|fresh)\s+(chat|conversation|thread)|start over|reset", q.lower().strip(" .!?")))
                if new:
                    import os as _os
                    try: _os.remove(_os.path.expanduser("~/anish-ai/nova_claude/.session"))
                    except OSError: pass
                    try:                                   # token bar: conversation size back to zero
                        import json as _j; _u = nova.claude_usage(); _u["ctx"] = 0; _j.dump(_u, open(nova.CLAUDE_USAGE, "w"))
                    except Exception: nova.swallowed()
                    reply = "Fresh Claude conversation started, sir."
                else:
                    self.speak("One moment, sir.")
                    reply = nova.FUNCS["claude"](q)   # full markdown reply -> shown in the HUD as-is
            self.messages += [{"role": "user", "content": user}, {"role": "assistant", "content": reply}]
            self.messages = self.messages[-20:]; self.speak(nova.speakable(reply))
            return {"reply": reply, "activity": ["claude()"]}

        # INSTANT fast-paths: the most common simple commands skip the LLM entirely (no wait).
        def _instant(reply, act):
            self._audit(act.split("(")[0], {"call": act}, "ok: " + str(reply)[:120].replace("\n", " "))   # fast path logs too
            self.messages += [{"role": "user", "content": user}, {"role": "assistant", "content": reply}]
            self.messages = self.messages[-20:]; self.speak(reply)
            return {"reply": reply, "activity": [act]}
        words = low.strip(" .?!").split()
        if re.search(r"\bwhat('?s| is)?\s+(the\s+)?time\b|\btime is it\b", low):
            return _instant(nova.FUNCS["get_datetime"](), "get_datetime()")
        # AC: fire the IR deterministically (it's a stateless one-way remote) so the model can't
        # decide it's "already on" and skip the tool. AC mention OR a room-temperature set -> act now.
        _temp_set = (re.search(r"\b(temp(erature)?|degrees?)\b", low) and re.search(r"\b(1[6-9]|2\d|30)\b", low)
                     and re.search(r"\b(set|make|to|adjust|change|put)\b", low))   # "set room temp to 21" -> AC
        if re.search(r"\b(ac|a\.c\.|air\s*con(?:ditioner)?)\b", low) or _temp_set:
            dur = re.search(r"\bfor\s+\d+(?:\.\d+)?\s*(?:h|hrs?|hours?|m|mins?|minutes?)\b", low)   # "... for 5 min"
            temp = re.search(r"\b(1[6-9]|2\d|30)\b", low[:dur.start()] + low[dur.end():] if dur else low)
            fan_sp = re.search(r"\b(low|mid|medium|high|auto)\b", low)
            mode = re.search(r"\b(cool|heat|dry|auto)\b", low)
            acmd = None
            if re.search(r"\b(off|shut)\b|switch\s+off|turn\s+off", low):
                acmd = "off"
            elif temp and re.search(r"\b(set|to|degrees?|make|temperature)\b", low):
                acmd = "temp " + temp.group(1)
            elif "fan" in low and fan_sp:
                acmd = "fan " + fan_sp.group(1)
            elif "mode" in low and mode:
                acmd = "mode " + mode.group(1)
            elif re.search(r"\b(on|start)\b|switch\s+on|turn\s+on|\bcool\b|\bheat\b", low):
                acmd = "on" if not mode else None
                if acmd is None and mode:
                    nova.FUNCS["ac"]("mode " + mode.group(1)); acmd = "on"
            if acmd:
                if dur: acmd += " " + dur.group(0)
                return _instant(nova.FUNCS["ac"](acmd), "ac(%s)" % acmd)
        # WIZ BULB (room ceiling light): "bulb ..." or a WiZ scene name with "light(s)" -> wiz.py parses the rest.
        if re.search(r"\bbulb\b", low) or (re.search(r"\blights?\b", low) and not re.search(r"\bbed\s*light|\bstrip\b|\bled\b", low)
                and re.search(r"\b(ocean|romance|romantic|sunset|fireplace|cozy|cosy|forest|pastel|bedtime|focus|relax|movie|tv|jungle|club|christmas|halloween|candle\w*|golden|diwali|snowy?)\b", low)):
            import wiz
            return _instant(wiz.bulb(low), "wiz(%s)" % low[:30])
        # BED LIGHTS (Bluetooth LED strip) — MUST come before the room-relay light so 'bed lights',
        # 'the strip', or any colour/effect routes to the strip, not the ESP ceiling light.
        _col = re.search(r"\b(blue|red|green|white|warm|yellow|orange|purple|pink|cyan|magenta)\b", low)
        _fx  = re.search(r"\b(party|strobe|fade|cycle)\b", low)
        _strip_only = re.search(r"\bbed\s*light|\bstrip\b|\bled\b", low)
        if _strip_only or (re.search(r"\blights?\b", low) and (_col or _fx or re.search(r"\bdim\w*|brightness|\bbrighte[nr]\b|\d+\s*%", low))):
            if re.search(r"\b(off|kill)\b|switch\s+off|turn\s+off", low):    _lc = "off"
            elif _fx:                                                        _lc = _fx.group(1)
            elif _col:                                                       _lc = _col.group(1)
            elif re.search(r"brightness\s+(\d+)", low):                      _lc = "brightness " + re.search(r"brightness\s+(\d+)", low).group(1)
            elif re.search(r"\bto\s+(\d+)", low):                            _lc = "brightness " + re.search(r"\bto\s+(\d+)", low).group(1)
            elif re.search(r"\bdim\b", low):                                 _lc = "dim"
            elif re.search(r"\bbright(en)?\b", low):                         _lc = "brighten"
            else:                                                            _lc = "on"
            if re.search(r"\d+\s*%", low) and not re.search(r"\d", _lc): _lc = "brightness " + re.search(r"(\d+)\s*%", low).group(1)
            said = nova.FUNCS["lights"](_lc)
            if not _strip_only:                          # plain "lights ..." = strip AND bulb in sync
                import wiz
                if wiz.parse(_lc): wiz.bulb(_lc); said = "Lights %s, sir." % _lc
            return _instant(said, "lights(%s)%s" % (_lc, "" if _strip_only else "+bulb"))

        # light / fan / plug: fire the relay deterministically so the model can't skip the tool (and
        # handle natural phrasing — "light up the room", "kill the lights", "it's too dark").
        _dev = ("light" if re.search(r"\blights?\b|\blamp\b|\bbulb\b", low)
                else "fan" if re.search(r"\bfan\b", low)
                else "plug" if re.search(r"\bplug\b|\bsocket\b", low) else None)
        if _dev:
            _act = ("off" if re.search(r"\b(off|kill)\b|switch\s+off|turn\s+off|too\s+bright", low)
                    else "on" if re.search(r"\b(on|dark|bright(en)?)\b|switch\s+on|turn\s+on|light\s+up", low) else None)
            if _act:
                said = nova.FUNCS["iot_control"](_dev, _act)
                if _dev == "light" and not re.search(r"\bbulb\b|\bceiling\b", low):
                    nova.FUNCS["lights"](_act)           # "lights on/off" switches the bed strip too
                return _instant(said, "iot_control(%s,%s)" % (_dev, _act))
        m = re.match(r"^(?:hey\s+)?(?:nova[ ,]+)?(?:please\s+)?(?:open|launch|start up|start)\s+(?:the\s+|my\s+)?(.+)$", low)
        if m and len(words) <= 5 and not re.search(r"\b(and|then|door|file|up the|tell|what|why|how)\b", m.group(1)):
            app = m.group(1).strip(" .?!")
            return _instant(nova.FUNCS["open_app"](app), "open_app(%s)" % app)

        # CLAUDE MODE (default): everything that isn't an instant command is a turn in the ongoing Claude session.
        _ml = low.strip(" .!?")
        if re.fullmatch(r"(?:switch to |go to |use )?(?:normal|quick|fast|local) mode", _ml):
            self._claude_mode = False
            return _instant("Quick mode, sir. Say Claude mode to switch back.", "mode(quick)")
        if re.fullmatch(r"(?:switch to |go to |use |turn on |enable )?private mode(?: on)?", _ml):
            self._private = True
            threading.Thread(target=self._mlx_warm, daemon=True).start()   # load + cache the prompt while we talk
            return _instant("Private mode, sir. Everything stays on this Mac now.", "mode(private)")
        if re.fullmatch(r"(?:switch to |go to |use )?(?:online|cloud|public) mode|(?:turn off |disable )?private mode off|"
                        r"(?:turn off|disable|exit|leave) private mode", _ml):
            self._private = False
            self._mlx_down()
            return _instant("Back online, sir.", "mode(online)")
        if re.fullmatch(r"(?:switch to |go to |use )?(?:claude|talk|build) mode", _ml):
            self._claude_mode = True
            return _instant("Claude mode, sir. Just talk to me.", "mode(claude)")
        # Only real WORK goes to the Claude Code agent (~10s); chat/questions use the fast brain (~1-2s).
        if self._claude_mode and not self._private and not re.search(_DEV, low) and re.search(   # devices: fast brain ("make the stars blue" took Claude ~20 s)
                r"\b(build|make|create|write|code|program|script|fix|debug|refactor|install|deploy|"
                r"set ?up|edit|update|change|add|delete|rename|file|folder|project|repo|commit|"
                r"research|look up|find out|search|plan|design|automate|run)\b", low):
            return self.chat("Claude, " + user)   # reuses the Claude branch above

        # CODE: delegate coding tasks to the Claude Code agent (voice -> `claude -p`). Ack, then run.
        if (re.search(r"\b(write|build|make|create|code|fix|refactor|debug|generate)\b", low)
                and re.search(r"\b(script|program|code|function|app|website|web ?site|bug|scraper|"
                              r"cli|api|python|javascript|java|c\+\+|html|css|snippet|automation)\b", low)):
            self.speak("On it, sir — coding that now. One moment.")
            return _instant(nova.FUNCS["code"](user), "code(...)")

        # DESIGN: generate a self-contained HTML design and open it (poster/page/flyer/card).
        if re.search(r"\b(design|poster|flyer|banner|brochure|infographic|mock ?up|landing page|"
                     r"web ?page|invitation|menu card)\b", low):
            self.speak("Designing that now, sir — one moment.")
            return _instant(nova.FUNCS["design"](user), "design(...)")

        # DEEP REASON: hard questions go to the strongest reasoning brain, not the fast chat model.
        if re.search(r"\b(think (hard|deeply|carefully|it through)|reason (through|about|it out)|"
                     r"explain in depth|deep[- ]?dive|work (it|this) out|analys?e this|figure out)\b", low):
            self.speak("Let me think that through, sir.")
            return _instant(nova.FUNCS["think"](user), "think(...)")

        # "Can you see me?" -> answer from the real webcam state (HUD WEBCAM switch = the hub's room camera).
        if re.search(r"\b(can|do) (you|u) see me\b|\bare you (watching|looking at) me\b|\bis (the|your) (webcam|camera) on\b", low):
            return _instant("Yes, sir. I can see you through the room camera." if self._cam_on
                            else "No, sir. The room camera is switched off.", "camera-state")

        # SCREEN VISION: look at the SCREEN (never the webcam) and answer. Respects the no-camera rule.
        if re.search(r"\b(on (my|the) screen|read (this|the screen)|look at (my|the) screen|"
                     r"describe (this|the screen)|what('?s| is) (this|on (my|the) screen)|"
                     r"what does (this|the) (error|chart|graph|code|message|screen))\b", low):
            self.speak("Looking at your screen, sir.")
            return _instant(nova.FUNCS["look"](user), "look(...)")

        self.messages.append({"role": "user", "content": user})
        self.messages = self.messages[-20:]              # cap history
        for name, fn in self._brains():
            if time.time() < self._brain_cool.get(name, 0):
                continue                                   # rate-limited a moment ago -> don't waste a round trip
            try:
                reply, activity = fn()
            except Exception as e:
                print("[brain] %s failed: %s" % (name, str(e)[:140]), flush=True)
                if "429" in str(e) or "rate" in str(e).lower():
                    self._brain_cool[name] = time.time() + 60   # free tiers refill per minute
                continue
            reply = (reply or "").strip()
            if reply:
                self.messages.append({"role": "assistant", "content": reply})
                self._save_convo()          # persist so it remembers across restarts
                self.speak(reply)
                return {"reply": reply, "activity": ["via " + name] + activity}
        return {"reply": "All my brains appear to be offline, sir.", "activity": []}

    # ---- tiered brain ----
    def _key(self, name):
        try:
            with open(os.path.expanduser("~/anish-ai/.%s_key" % name)) as f:
                k = f.read().strip()
            return "" if (not k or "PASTE" in k.upper()) else k
        except Exception:
            return ""

    def _mlx_up(self):
        """Start the local MLX server if it isn't answering (first load ~10s, then ~2-5s replies)."""
        import urllib.request
        try:
            urllib.request.urlopen(MLX_URL + "/models", timeout=1); return True
        except Exception:
            nova.swallowed()
        # GPU memory can't swap: loading with too little free RAM froze the whole Mac (2026-11-08).
        if psutil.virtual_memory().available < 7 * 2**30:
            print("[private] refusing to load MLX: only %.1f GB free" % (psutil.virtual_memory().available / 2**30), flush=True)
            return False
        if not (self._mlx_proc and self._mlx_proc.poll() is None):
            self._mlx_proc = subprocess.Popen(
                [os.path.expanduser("~/anish-ai/.mlx/bin/python"), "-m", "mlx_lm", "server", "--model", MLX_MODEL,
                 "--host", "127.0.0.1", "--port", "8088"], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        for _ in range(60):
            try:
                urllib.request.urlopen(MLX_URL + "/models", timeout=1); return True
            except Exception:
                time.sleep(1)
        return False

    def _mlx_warm(self):
        """Free ollama's RAM (both models at once = swap = 90s+ replies), then pre-fill the
        persona+tools prefix so MLX's prompt cache makes the first real reply ~4s instead of ~25s."""
        subprocess.run(["ollama", "stop", "nova"], capture_output=True)
        if not self._mlx_up():
            return
        try:
            import requests
            requests.post(MLX_URL + "/chat/completions", timeout=120, json={
                "model": MLX_MODEL, "max_tokens": 1, "tools": nova.TOOLS,
                "chat_template_kwargs": {"enable_thinking": False},
                "messages": [{"role": "system", "content": self._persona()}, {"role": "user", "content": "hi"}]})
            print("[private] mlx warm", flush=True)
        except Exception as e:
            print("[private] warm failed: %s" % e, flush=True)

    def _mlx_down(self):
        """Free the ~5GB the model holds when leaving private mode."""
        if self._mlx_proc and self._mlx_proc.poll() is None:
            self._mlx_proc.terminate()
        self._mlx_proc = None

    def _brains(self):
        if self._private:   # nothing leaves the Mac: local MLX first, ollama as backup
            def _mlx():
                if not self._mlx_up():
                    raise RuntimeError("mlx server didn't start")
                return self._brain_openai(MLX_URL, "local", MLX_MODEL, 90, 1)
            return [("mlx", _mlx), ("qwen", self._brain_ollama)]
        out = []
        gk = self._key("groq")
        if gk:   # Groq PRIMARY + a 2nd Groq model — separate per-model rate limit, so a 429 stays fast
            out.append(("groq", lambda: self._brain_openai("https://api.groq.com/openai/v1", gk, GROQ_MODEL, 20, 1)))
            out.append(("groq-alt", lambda: self._brain_openai("https://api.groq.com/openai/v1", gk, GROQ_ALT_MODEL, 20, 1)))
            out.append(("groq-alt2", lambda: self._brain_openai("https://api.groq.com/openai/v1", gk, GROQ_ALT2_MODEL, 20, 1)))
        ck = self._key("claude")
        if ck:   # Claude fallback: only used if both Groq models are down
            out.append(("claude", lambda: self._brain_claude(ck)))
        # (NVIDIA/kimi dropped — its key 403'd every call, just added a dead round-trip)
        # Nova mesh: extra FREE brains from router.py (Cerebras/Gemini/Mistral/OpenRouter/SambaNova + LM Studio).
        # Only providers with a key join (local box needs none) — cross-provider fallback before slow local ollama.
        try:
            import router
            mesh = [  # cerebras dropped (402 payment), gemini dropped (tool calls need thought_signature)
                    ("mistral", router.M["mistral_code"]), ("openrouter", router.M["openrouter_gen"]),
                    ("sambanova", router.M["sambanova"]), ("lmstudio", router.M["lmstudio"])]
            for prov, model in mesh:
                base = router.PROVIDERS[prov]["url"].replace("/chat/completions", "")
                if router.PROVIDERS[prov].get("local"):
                    out.append((prov, (lambda b=base, m=model: self._brain_openai(b, "local", m, 30, 1))))
                elif router._key(prov):
                    k = router._key(prov)
                    out.append((prov, (lambda b=base, kk=k, m=model: self._brain_openai(b, kk, m, 20, 1))))
        except Exception as e:
            print("[brain] router mesh unavailable: %s" % str(e)[:100], flush=True)
        out.append(("qwen", self._brain_ollama))   # local last resort (slow on 16GB, but never offline)
        return out

    def _tools_for(self):
        recent = " ".join(m["content"] for m in self.messages[-3:] if m.get("role") == "user").lower()
        want = set(CORE_TOOLS)
        for rx, extra in TOOL_HINTS:
            if re.search(rx, recent):
                want |= extra
        return [t for t in nova.TOOLS if t["function"]["name"] in want]

    def _hist(self, n=None):
        msgs = self.messages if n is None else self.messages[-n:]
        return [{"role": m["role"], "content": m["content"]} for m in msgs]

    def _label(self, fn, args):
        return fn + "(" + ", ".join("%s=%s" % (k, v) for k, v in (args or {}).items()) + ")"

    def _safe_tool(self, fn, args):
        try:
            return self._run_tool(fn, args or {})
        except Exception as e:
            return "Tool %s errored: %s" % (fn, e)

    def _brain_ollama(self):
        msgs = [{"role": "system", "content": self._persona()}] + self._hist()
        activity = []
        for _ in range(6):
            m = ollama.chat(model="nova", messages=msgs, tools=nova.TOOLS)["message"]
            calls = m.get("tool_calls") or []
            if not calls:
                return m.get("content", "") or "", activity
            msgs.append({"role": "assistant", "content": m.get("content", ""), "tool_calls": calls})
            for tc in calls:
                fn = tc["function"]["name"]; args = tc["function"].get("arguments", {}) or {}
                activity.append(self._label(fn, args))
                msgs.append({"role": "tool", "content": str(self._safe_tool(fn, args)), "tool_name": fn})
        return "", activity

    def _brain_openai(self, base_url, api_key, model, timeout=20, retries=1):
        from openai import OpenAI
        client = OpenAI(base_url=base_url, api_key=api_key, timeout=timeout, max_retries=0)
        msgs = [{"role": "system", "content": self._persona()}] + self._hist()
        activity = []

        # gpt-oss is a REASONING model: without this it spends the whole token budget "thinking"
        # and returns empty content -> Nova hears you but says nothing. 'low' makes it answer fast.
        extra = ({"reasoning_effort": "low"} if "gpt-oss" in model
                 else {"reasoning_effort": "none"} if "qwen" in model   # skip qwen3 thinking -> ~2x faster
                 else {"chat_template_kwargs": {"enable_thinking": False}} if "mlx-community" in model   # local qwen3: no thinking
                 else {})

        def _create():
            # NVIDIA load-balances models across nodes; some return a transient 404/429.
            # Retry a few times to land on a node that actually serves the model.
            last = None
            for attempt in range(retries):
                try:
                    return client.chat.completions.create(model=model, messages=msgs,
                                                          tools=self._tools_for(), temperature=0.6,
                                                          extra_body=extra)
                except Exception as e:
                    code = getattr(e, "status_code", None)
                    if code in (404, 429, 500, 502, 503) and attempt < retries - 1:
                        time.sleep(0.6 * (attempt + 1))
                        last = e
                        continue
                    raise
            if last:
                raise last

        for _ in range(6):
            m = _create().choices[0].message
            if not m.tool_calls:
                return m.content or "", activity
            msgs.append({"role": "assistant", "content": m.content or "",
                         "tool_calls": [{"id": tc.id, "type": "function",
                                         "function": {"name": tc.function.name,
                                                      "arguments": tc.function.arguments}}
                                        for tc in m.tool_calls]})
            if not activity and {tc.function.name for tc in m.tool_calls} & {"get_weather", "search_web", "read_webpage", "find_device"}:
                threading.Thread(target=self.speak, args=("One moment, sir.",), daemon=True).start()   # no 1-2s silence on lookups
            for tc in m.tool_calls:
                fn = tc.function.name
                try:
                    args = json.loads(tc.function.arguments or "{}")
                except Exception:
                    args = {}
                activity.append(self._label(fn, args))
                msgs.append({"role": "tool", "tool_call_id": tc.id, "content": str(self._safe_tool(fn, args))})
        return "", activity

    def _brain_claude(self, api_key):
        import anthropic
        client = anthropic.Anthropic(api_key=api_key, timeout=30)
        tools = [{"name": t["function"]["name"], "description": t["function"]["description"],
                  "input_schema": t["function"].get("parameters", {"type": "object", "properties": {}})}
                 for t in nova.TOOLS]
        msgs = self._hist(6)               # only recent turns -> fewer input tokens
        while msgs and msgs[0]["role"] != "user":
            msgs.pop(0)
        activity = []
        for _ in range(6):
            resp = client.messages.create(model=CLAUDE_MODEL, system=self._persona(), messages=msgs,
                                          tools=tools, max_tokens=400)   # short spoken replies = cheap
            uses = [c for c in resp.content if c.type == "tool_use"]
            text = " ".join(c.text for c in resp.content if c.type == "text").strip()
            if not uses:
                return text, activity
            msgs.append({"role": "assistant", "content": resp.content})
            msgs.append({"role": "user", "content": [
                {"type": "tool_result", "tool_use_id": u.id, "content": str(self._safe_tool(u.name, u.input or {}))}
                for u in uses]})
            for u in uses:
                activity.append(self._label(u.name, u.input or {}))
        return "", activity

    # commands that can wreck things, leak secrets, or exfiltrate data -> confirm; else run freely
    DANGER_RE = re.compile(
        r"(\b(rm\s+-rf|rm\s+-fr|sudo|dd\s|mkfs|shutdown|reboot|halt|diskutil\s+erase|"
        r"killall|chmod\s+-R\s+777|chown\s+-R|fdisk|launchctl\s+(unload|remove)|defaults\s+delete)\b"
        r"|:\(\)\s*\{|>\s*/dev/|/dev/sd|/dev/tcp"                       # fork bomb / raw device / reverse shell
        r"|\.ssh|id_rsa|id_ed25519|\.aws|\.env|keychain|security\s+find|_key\b|\.pem"  # secrets/credentials
        r"|\bnc\b|\bncat\b|\bnetcat\b|\btelnet\b|\bscp\b|\bsftp\b|\bssh\s+[^-]"          # network shells/transfer
        r"|curl[^|]*(-d|--data|-F|--form|-T|--upload|-X\s*POST|-X\s*PUT)"                # curl uploads (exfil)
        r"|wget[^|]*(--post|--body)|\|\s*(sh|bash|zsh)\b|curl[^|]*\|\s*(sh|bash))",      # pipe-to-shell
        re.IGNORECASE)

    # Only these run without a click: read-only, single command, no shell syntax at all. Everything else asks
    # (a denylist alone is bypassable: base64/python/obfuscation, or a prompt injected via a web page Nova read).
    SAFE_CMD_RE = re.compile(r"^\s*(ls|pwd|date|cal|whoami|uptime|df|du|sw_vers|uname|hostname|pmset\s+-g|"
                             r"system_profiler\s+SP\w+|top\s+-l\s*1|ps|vm_stat|ifconfig|which)\b[^;&|`$<>(){}\\\n]*$")

    def _confirm(self, prompt):
        try:
            if DISPLAY: return False         # kiosk screen: nobody there to click, never block
            return bool(webview.windows[0].evaluate_js("window.confirm(" + json.dumps(prompt) + ")"))
        except Exception:
            return False                      # headless hub / no window -> deny

    AUDIT_PATH = os.path.expanduser("~/anish-ai/audit.log")

    def _audit(self, fn, args, outcome):
        """Append-only record of every action Nova takes (secrets redacted)."""
        try:
            safe = {}
            for k, v in (args or {}).items():
                s = str(v)
                if re.search(r"key|token|secret|password|passwd|\.pem|id_rsa", k + " " + s, re.I):
                    s = "[redacted]"
                safe[k] = s[:160]
            line = "%s | %s | %s | %s\n" % (time.strftime("%Y-%m-%d %H:%M:%S"), fn, json.dumps(safe), outcome)
            with open(self.AUDIT_PATH, "a") as f:
                f.write(line)
            try:
                os.chmod(self.AUDIT_PATH, 0o600)
            except OSError:
                pass
        except Exception:
            nova.swallowed()

    def _run_tool(self, fn, args):
        result = self._exec_tool(fn, args)
        # log a short, non-sensitive outcome
        r = str(result)
        outcome = ("denied" if ("denied" in r or "cancelled" in r) else "ok") + ": " + r[:120].replace("\n", " ")
        self._audit(fn, args, outcome)
        return result

    def _exec_tool(self, fn, args):
        if fn == "run_command":
            cmd = args.get("command", "")
            if self.DANGER_RE.search(cmd) or not self.SAFE_CMD_RE.match(cmd):
                warn = "a potentially DANGEROUS" if self.DANGER_RE.search(cmd) else "a"
                if not self._confirm("Nova wants to run %s command:\n\n%s\n\nAllow?" % (warn, cmd)):
                    return "The user denied permission to run that command."
            r = subprocess.run(cmd, shell=True, capture_output=True, text=True, timeout=30)
            return ((r.stdout + r.stderr).strip() or "(command ran, no output)")[:2000]
        if fn == "write_file":   # could overwrite ~/.zshrc, a LaunchAgent, etc. -> always confirm
            if not self._confirm("Nova wants to write %d characters to:\n\n%s\n\nAllow?"
                                 % (len(args.get("content", "") or ""), args.get("path", "?"))):
                return "The user denied permission to write that file."
        if fn == "remember":     # memory lives on the Api (persists across sessions)
            return self.remember(args.get("fact", ""))
        if fn in ("send_imessage", "send_whatsapp"):   # outbound message to a person -> always confirm
            how = "an iMessage" if fn == "send_imessage" else "a WhatsApp message"
            prompt = ("Nova wants to send %s to %s:\n\n%s\n\nSend it?"
                      % (how, args.get("to", "?"), args.get("message", "")))
            try:
                ok = webview.windows[0].evaluate_js("window.confirm(" + json.dumps(prompt) + ")")
            except Exception:
                ok = False
            if not ok:
                return "The user cancelled sending the message."
        f = nova.FUNCS.get(fn)
        return f(**args) if f else f"Unknown tool: {fn}"

    def _persona(self):
        m = self.memory
        extra = ""
        if m.get("facts"):
            extra = " What you remember about the user: " + "; ".join(m["facts"]) + "."
        return PERSONA + extra
