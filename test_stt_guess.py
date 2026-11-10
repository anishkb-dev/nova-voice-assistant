"""Self-check for nova_app._vp_guess (guess-and-ask STT learning). Run: python3 test_stt_guess.py"""
import ast, re, sys, types
src = open("app/nova_app.py").read(); t = ast.parse(src)
g = {"re": re}
for n in t.body:   # module constants + DIRECT_CMD
    if isinstance(n, ast.Assign) and any(getattr(x, "id", "") in ("_DEV","_ACT","_ROUTINE","_QUESTION_RE","_SEED_CMDS") for x in n.targets) \
       or isinstance(n, ast.FunctionDef) and n.name == "DIRECT_CMD":
        exec(compile(ast.Module([n], []), "x", "exec"), g)
fn = next(m for c in t.body if isinstance(c, ast.ClassDef) for m in c.body if getattr(m, "name", "") == "_vp_guess")
exec(compile(ast.Module([fn], []), "x", "exec"), g)
class S: vprofile = {}; _save_vprofile = lambda self: None
s = S(); asked = []
def ask(q, a="yes"): asked.append(q); return a
G = lambda c, a="yes": g["_vp_guess"](s, c, lambda q: ask(q, a))
assert G("laser off") == "laser off" and not asked                       # clear cmd: no question
assert G("what time is it") == "what time is it" and not asked            # question passes
assert G("lazy off") == "laser off" and asked[-1] == "Did you mean laser off?"
n = len(asked); assert G("lazy off") == "laser off" and len(asked) == n   # learned: no re-ask
assert G("start dimmer", "no") == "start dimmer"                          # no -> as heard, not learned
assert "start dimmer" not in s.vprofile["phrases"]
print("ok", asked, s.vprofile["phrases"])
for p in ["izzerov","lights of","fan of","stars timmer","good knight","projected on","laser of","a c off",
          "hello there","thanks nova","i'm tired","nice work","that's cool","never mind","stop","shut up"]:
    asked.clear(); r = G(p, "no"); print("%-14s -> %s" % (p, asked[0] if asked else "(no question)"))
# follow-up gate: device commands pass, chatter to other people doesn't
D = g["DIRECT_CMD"]
for p, want in [("set projector to nebula", 1), ("Now a reset projector", 1), ("goodnight", 1),
                ("See you", 0), ("Did he hit him", 0), ("What if I build a mic?", 0)]:
    assert bool(D(p)) == bool(want), p
print("follow-up gate ok")
