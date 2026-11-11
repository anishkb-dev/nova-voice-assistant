"""Freelance watcher: reads Gmail (IMAP, read-only, never marks read) for Fiverr / Upwork / Contra / data-work
platform mail and tells Anish: real orders, buyer messages, scams, security alerts.
Never replies, clicks, opens attachments or reads codes aloud. Key: ~/anish-ai/.gmail_key (GMAIL_USER, GMAIL_APP_PW).
Spec: freelance-watch-handoff.md"""
import email, email.header, html, imaplib, json, os, re, time

HERE = os.path.dirname(os.path.abspath(__file__))
KEY_F = os.path.join(HERE, ".gmail_key")
STATE_F = os.path.join(HERE, ".mailwatch_state.json")
EVERY = 300                       # seconds between checks
QUIET = (23, 7)                   # quiet hours: only real orders are spoken, the rest goes to Telegram
SENDERS = ("fiverr.com", "upwork.com", "contra.com", "micro1.ai", "outlier.ai", "alignerr.com",
           "turing.com", "dataannotation.tech")
KNOWN_SCAMMERS = {"marina_85319", "c_ell1s_468", "victoire_xlj"}
SAFE_HOSTS = ("fiverr.com", "upwork.com", "contra.com")

FAKE_ORDER = re.compile(r"placed (the|an|your) order|purchased your gig|confirm (it|the order|my order)|waiting for "
                        r"your (approval|confirmation)|work is (finished|done|complete)|review the details|reference is",
                        re.I)
OFF_PLATFORM = re.compile(r"whats\s?app|telegram|wechat|signal app|skype|text me|my (e-?mail|number)|contact me (on|at|via)", re.I)
URL = re.compile(r"(?:https?://)?((?:[a-z0-9-]+\.)+(?:com|net|org|io|online|site|xyz|top|club|shop|info|link|app|me|co|live|pro))\b(\S*)", re.I)
ATTACH = re.compile(r"\b[\w-]+\.(pdf|docx?|zip|rar|exe|xlsx?|html?)\b", re.I)
ORDER_SUBJ = re.compile(r"new order|received (an|a new) order|order (from|received)|offer from|sent you an offer|"
                        r"contract (has )?started|hired you", re.I)
SECURITY_SUBJ = re.compile(r"verif|log ?in|sign.?in|device|browser|password|security|billing|visa|card|payment method|"
                           r"connected to your|two.?factor|2fa|account (was )?(updated|changed)", re.I)


NEWS_SUBJ = re.compile(r"interview|moving forward|accepted|approved|congratulations|selected|next step|assessment|invit", re.I)


def _platform(frm):
    return next((s.split(".")[0].capitalize() for s in SENDERS if s in frm.lower()), "Freelance")


def _no_digits(s):
    """Never pass on codes/card numbers: any 4+ digit run is dropped."""
    return re.sub(r"\d[\d\s-]{3,}\d|\d{4,}", "", s)


def _no_links(s):
    return URL.sub(lambda m: m.group(0) if m.group(1).lower().endswith(SAFE_HOSTS) else "[link removed]", s)


def scam_reasons(sender, text, has_order):
    """Why this buyer message looks like a scam ([] = looks real). Rules from the handoff's 'Scam rules'."""
    r = []
    if sender.lower() in KNOWN_SCAMMERS:
        r.append("is a known scam account")
    if FAKE_ORDER.search(text) and not has_order:
        r.append("claims an order that doesn't exist")
    if any(not m.group(1).lower().endswith(SAFE_HOSTS) for m in URL.finditer(text)):
        r.append("has an outside link")
    if OFF_PLATFORM.search(text):
        r.append("wants to move off the platform")
    if ATTACH.search(text):
        r.append("sends a file in the first message")
    return r


def classify(frm, subject, text, order_buyers=()):
    """-> (kind, spoken line, telegram text). kind: order | scam | message | security | info"""
    plat = _platform(frm)
    subject = " ".join(subject.split())
    m = re.search(r"messages? from (\S+)", subject, re.I)
    if m and plat in ("Fiverr", "Upwork", "Contra"):
        who = m.group(1)
        body = re.search(r"(?:messaged you:|put them all here for you)\s*(.*?)\s*(?:Go to your inbox|Reply|View message|$)", text, re.S)
        body = (body.group(1) if body else text)[:400].strip()
        why = scam_reasons(who, body, who in order_buyers)
        if why:
            return ("scam", "Sir, a message from %s on %s looks like a scam: it %s. Please don't open it."
                    % (who, plat, " and ".join(why)),
                    "\u26a0\ufe0f SCAM? %s message from %s (%s).\n\"%s\"\nDon't open links or files. Report and block."
                    % (plat, who, ", ".join(why), _no_links(_no_digits(body[:200]))))
        first = _no_links(_no_digits(body if len(body) <= 160 else body[:160].rsplit(" ", 1)[0] + "..."))
        return ("message", "New %s message from %s: %s" % (plat, who, first),
                "\U0001F4AC %s message from %s:\n\"%s\"" % (plat, who, _no_links(_no_digits(body[:300]))))
    if ORDER_SUBJ.search(subject):
        return ("order", "Sir, a new order on %s. %s. Download their files and I'll set up the project." % (plat, _no_digits(subject)),
                "\U0001F4B0 NEW %s ORDER: %s\nSave the buyer's files, then on the Mac:\n"
                "python3 ~/Developer/money/new_order.py <buyer> ~/Downloads/<their files>" % (plat.upper(), _no_digits(subject)))
    if SECURITY_SUBJ.search(subject):        # subject only: bodies hold codes
        return ("security", "Sir, a security notice from %s: %s. Please confirm that was you." % (plat, _no_digits(subject)),
                "\U0001F510 %s security: %s. Was this you?" % (plat, _no_digits(subject)))
    if NEWS_SUBJ.search(subject):           # interviews, approvals, offers: worth saying out loud
        return ("news", "Sir, news from %s: %s." % (plat, _no_digits(subject)), "\U0001F31F %s: %s" % (plat, _no_digits(subject)))
    return ("info", "", "\U0001F4E8 %s: %s" % (plat, _no_digits(subject)))


def _text(msg):
    """Plain text of an email: text/plain, else HTML with styles/tags stripped."""
    for want in ("text/plain", "text/html"):
        for p in msg.walk():
            if p.get_content_type() == want and not p.get_filename():
                t = p.get_payload(decode=True).decode(p.get_content_charset() or "utf-8", errors="ignore")
                if want == "text/html":
                    t = re.sub(r"<[^>]+>", " ", re.sub(r"(?is)<(style|head|script)[^>]*>.*?</\1>", " ", t))
                return " ".join(html.unescape(t).split())
    return ""


def _load():
    try:
        return json.load(open(STATE_F))
    except Exception:
        return {"uid": 0, "buyers": {}}


def check(state):
    """One pass: new matching mail since state['uid'] -> list of (kind, spoken, telegram)."""
    kv = dict(l.split("=", 1) for l in open(KEY_F).read().split())
    m = imaplib.IMAP4_SSL("imap.gmail.com", timeout=30)
    try:
        m.login(kv["GMAIL_USER"], kv["GMAIL_APP_PW"])
        m.select("INBOX", readonly=True)                      # read-only: nothing gets marked read
        q = '"from:(%s)"' % " OR ".join(SENDERS)
        if not state["uid"]:                                  # first run: start from now, don't replay history
            uids = m.uid("search", None, "X-GM-RAW", q)[1][0].split()
            state["uid"] = int(uids[-1]) if uids else 1
            return []
        uids = [int(u) for u in m.uid("search", None, "UID", "%d:*" % (state["uid"] + 1), "X-GM-RAW", q)[1][0].split()]
        out = []
        for u in sorted(x for x in uids if x > state["uid"]):
            msg = email.message_from_bytes(m.uid("fetch", str(u), "(BODY.PEEK[])")[1][0][1])
            subj = str(email.header.make_header(email.header.decode_header(msg["Subject"] or "")))
            now = time.time()
            state["buyers"] = {b: t for b, t in state["buyers"].items() if now - t < 86400}
            kind, say, tg = classify(msg["From"] or "", subj, _text(msg), state["buyers"])
            if kind == "order":
                b = re.search(r"from (\S+)", subj)
                if b: state["buyers"][b.group(1)] = now
            out.append((kind, say, tg)); state["uid"] = u
        return out
    finally:
        try: m.logout()
        except Exception: pass


def run(speak, telegram):
    """Background loop (hub). speak(text) -> room speaker, telegram(text) -> phone."""
    if not os.path.exists(KEY_F):
        print("[mail] no .gmail_key, watcher off", flush=True); return
    state = _load()
    while True:
        try:
            for kind, say, tg in check(state):
                h = time.localtime().tm_hour
                quiet = h >= QUIET[0] or h < QUIET[1]
                print("[mail]", kind, tg.splitlines()[0][:120], flush=True)
                telegram(tg)
                if say and (kind == "order" or not quiet):
                    speak(say)
                if kind == "order":                           # ponytail: repeat twice; real "acknowledge" when asked
                    for _ in range(2):
                        time.sleep(300); speak("Sir, a reminder: " + say)
            json.dump(state, open(STATE_F, "w"))
        except Exception as e:
            print("[mail]", type(e).__name__, str(e)[:120], flush=True)
        time.sleep(EVERY)


if __name__ == "__main__":       # self-check with the real scam messages from 2026-11-11
    F = "Fiverr <noreply@e.fiverr.com>"
    k = classify(F, "You\u2019ve got new messages from c_ell1s_468",
                 "Hi anish_techy, c_ell1s_468 messaged you: Hello I have placed the order. Please confirm it when you have time and get started. Go to your inbox")
    assert k[0] == "scam" and "doesn't exist" in k[1], k
    k = classify(F, "You\u2019ve got new messages from victoire_xlj",
                 "victoire_xlj sent you messages and we put them all here for you Hi anish_techy I purchased your gig but i need your to review the details. Check this reference is: https://trusttoford.com/project/processed Go to your inbox")
    assert k[0] == "scam" and "outside link" in k[1] and "trusttoford" not in k[2], k
    k = classify(F, "You've got new messages from new_buyer1",
                 "new_buyer1 messaged you: I'd like a bot for invoices.pdf please, see medial-club.online")
    assert k[0] == "scam", k
    k = classify(F, "You've got new messages from real_buyer",
                 "real_buyer messaged you: Hi! Can your chatbot answer from 200 Excel price sheets? What would it cost? Go to your inbox")
    assert k[0] == "message" and "200 Excel" in k[1], k
    k = classify(F, "You've got new messages from real_buyer", "real_buyer messaged you: I placed the order, please confirm. Go to your inbox",
                 {"real_buyer": 1})
    assert k[0] == "message", k                               # real order exists -> not a scam
    k = classify("Upwork <donotreply@upwork.com>", "Verify your login", "Your code is 482913")
    assert k[0] == "security" and "482913" not in k[1] + k[2], k
    assert classify(F, "You've received a new order from abc_co", "")[0] == "order"
    assert classify("Upwork <donotreply@upwork.com>", "Congratulations! Your project has been approved.", "")[0] == "news"
    assert classify("Upwork <donotreply@upwork.com>", "Your weekly freelancer tips", "")[0] == "info"
    assert "4111" not in _no_digits("card 4111 1111 1111 1111")
    print("mailwatch ok")
