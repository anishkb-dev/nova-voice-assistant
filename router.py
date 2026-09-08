#!/usr/bin/env python3
"""Nova model router — one call, many free brains, automatic fallback.

Nova sends each task to the best FREE model for it, and falls through to the
next provider the moment one is missing a key, errors, or rate-limits — ending
at your local LM Studio / Ollama, which never rate-limit. Every provider here
speaks the OpenAI /chat/completions shape, so it's one uniform call.

    from router import chat
    r = chat("code", [{"role":"user","content":"write a bash one-liner to..."}])
    print(r["content"], "  ← via", r["provider"], r["model"])

Keys: put each in ~/anish-ai/.<name>_key  (same style as .groq_key), or set
<NAME>_KEY in the env. Missing key = that provider is skipped, no error.
Run `python3 router.py` to see which brains are live and ping them.
"""
import os, json, time, urllib.request, urllib.error

HERE = os.path.dirname(os.path.abspath(__file__))

# ---- providers: OpenAI-compatible endpoints. local ones need no key. --------
PROVIDERS = {
    "groq":       {"url": "https://api.groq.com/openai/v1/chat/completions"},
    "cerebras":   {"url": "https://api.cerebras.ai/v1/chat/completions"},
    "gemini":     {"url": "https://generativelanguage.googleapis.com/v1beta/openai/chat/completions"},
    "mistral":    {"url": "https://api.mistral.ai/v1/chat/completions"},
    "openrouter": {"url": "https://openrouter.ai/api/v1/chat/completions"},
    "sambanova":  {"url": "https://api.sambanova.ai/v1/chat/completions"},
    "lmstudio":   {"url": "http://192.168.68.109:1234/v1/chat/completions", "local": True},
    "ollama":     {"url": "http://localhost:11434/v1/chat/completions",    "local": True},
}

# ---- model ids: FREE picks (Sept 2026). Verify/adjust from each provider's
#      model list — slugs drift. A skill just needs one working link in its chain.
M = {
    "groq_fast":     "openai/gpt-oss-20b",   # verified live on your Groq key
    "groq_big":      "openai/gpt-oss-120b",  # verified
    "groq_reason":   "qwen/qwen3.8-27b",     # verified — reasoning model, needs effort control (see EXTRA)
    "cerebras":      "llama-3.3-70b",        # verify at cerebras model list once you add the key
    "gemini":        "gemini-2.5-flash",     # verify at ai.google.dev once you add the key
    "mistral_code":  "codestral-latest",     # verify at mistral once you add the key
    "openrouter_code":"deepseek/deepseek-chat-v3:free",
    "openrouter_gen": "meta-llama/llama-3.3-70b-instruct:free",
    "sambanova":     "Meta-Llama-3.3-70B-Instruct",
    "lmstudio":      "qwen/qwen3.8-27b",     # verified live on your LM Studio box (also has gemma-4-31b, gpt-oss-120b)
    "ollama":        "jarvis:latest",        # verified — your local custom model
}

# per-(provider,model) extra body params, e.g. taming reasoning models
EXTRA = {
    ("groq", M["groq_reason"]): {"reasoning_effort": "none"},  # qwen3: skip thinking -> instant + non-empty
    ("groq", M["groq_fast"]):   {"reasoning_effort": "low"},   # gpt-oss: else it thinks the whole budget away
    ("groq", M["groq_big"]):    {"reasoning_effort": "low"},
}

# ---- routing: skill -> ordered [(provider, model)]. Fastest-good first,
#      local last so Nova always answers even when every free tier is throttled.
CHAINS = {
    "fast":   [("groq", M["groq_fast"]), ("cerebras", M["cerebras"]),
               ("sambanova", M["sambanova"]), ("lmstudio", M["lmstudio"]), ("ollama", M["ollama"])],
    "reason": [("cerebras", M["cerebras"]), ("groq", M["groq_reason"]),
               ("gemini", M["gemini"]), ("lmstudio", M["lmstudio"]), ("ollama", M["ollama"])],
    "code":   [("groq", M["groq_big"]), ("mistral", M["mistral_code"]),
               ("openrouter", M["openrouter_code"]), ("lmstudio", M["lmstudio"]), ("ollama", M["ollama"])],
    "design": [("gemini", M["gemini"]), ("openrouter", M["openrouter_gen"]),
               ("groq", M["groq_big"]), ("lmstudio", M["lmstudio"]), ("ollama", M["ollama"])],
}
DEFAULT_SKILL = "fast"


def _key(name):
    """Read ~/anish-ai/.<name>_key, else env <NAME>_KEY. '' if absent/placeholder."""
    p = os.path.join(HERE, ".%s_key" % name)
    try:
        k = open(p).read().strip()
        if k and "PASTE" not in k.upper():
            return k
    except OSError:
        pass
    return (os.environ.get("%s_KEY" % name.upper()) or "").strip()


def _post(url, headers, body, timeout):
    data = json.dumps(body).encode()
    req = urllib.request.Request(url, data=data, headers=headers, method="POST")
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return json.load(r)


def _call(provider, model, messages, temperature, max_tokens, tools, tool_choice, timeout):
    """One provider attempt. Returns the assistant message dict, or raises."""
    prov = PROVIDERS[provider]
    if not prov.get("local") and not _key(provider):
        raise RuntimeError("no key")                      # skip: unconfigured
    headers = {"Content-Type": "application/json", "User-Agent": "Nova-Router/1.0"}  # non-default UA: Cloudflare 403s "Python-urllib"
    if not prov.get("local"):
        headers["Authorization"] = "Bearer " + _key(provider)
    body = {"model": model, "messages": messages,
            "temperature": temperature, "max_tokens": max_tokens}
    body.update(EXTRA.get((provider, model), {}))
    if tools:
        body["tools"] = tools
        if tool_choice:
            body["tool_choice"] = tool_choice
    j = _post(prov["url"], headers, body, timeout)
    msg = j["choices"][0]["message"]
    if not (msg.get("content") or msg.get("tool_calls")):
        raise RuntimeError("empty reply")                 # treat as failure -> fall through
    return msg


def chat(skill="fast", messages=None, temperature=0.6, max_tokens=1024,
         tools=None, tool_choice=None, timeout=30, verbose=False):
    """Route a chat to the best free brain for `skill`, falling back on any failure.
    Returns {content, tool_calls, provider, model, tried}. Raises only if the
    whole chain (including local) is unreachable."""
    chain = CHAINS.get(skill, CHAINS[DEFAULT_SKILL])
    tried, errors = [], []
    for provider, model in chain:
        tried.append(provider)
        t0 = time.time()
        try:
            msg = _call(provider, model, messages or [], temperature, max_tokens,
                        tools, tool_choice, timeout)
            if verbose:
                print("[router] %s/%s  %.2fs" % (provider, model, time.time() - t0))
            return {"content": msg.get("content") or "", "tool_calls": msg.get("tool_calls"),
                    "provider": provider, "model": model, "tried": tried}
        except Exception as e:                            # missing key / HTTP / timeout / empty
            errors.append("%s: %s" % (provider, str(e)[:60]))
            continue
    raise RuntimeError("all brains failed for '%s' -> %s" % (skill, " | ".join(errors)))


def available():
    """Which providers are usable right now (key present, or local)."""
    return [p for p in PROVIDERS if PROVIDERS[p].get("local") or _key(p)]


def demo():
    """Ping every configured brain once so you can see what's live + how fast."""
    print("Configured brains:", ", ".join(available()) or "(none — add keys!)")
    for skill in CHAINS:
        try:
            t0 = time.time()
            r = chat(skill, [{"role": "user", "content": "reply with the single word: ok"}],
                     max_tokens=64, timeout=20)
            print("  %-7s -> %-10s %-28s %.2fs  %r" %
                  (skill, r["provider"], r["model"], time.time() - t0, (r["content"] or "").strip()[:12]))
        except Exception as e:
            print("  %-7s -> FAILED: %s" % (skill, str(e)[:80]))


if __name__ == "__main__":
    demo()
