"""IA-2 exams, week of 23 Nov 2026 (7th sem CSE). One-week thing: dates are hardcoded and everything here
goes quiet on its own after STUDY_UNTIL. Delete this file (and its 3 call sites: grep "exams.") after that week."""
import datetime as _dt

D = _dt.datetime
EXAMS = [
    (D(2026, 11, 23, 9, 30), "Parallel Computing", "BCS702"),
    (D(2026, 11, 23, 14, 0), "Big Data Analytics", "BCS714D"),
    (D(2026, 11, 24, 9, 30), "Cryptography and Network Security", "BCS703"),
    (D(2026, 11, 24, 14, 0), "the open elective, E-W-M", "BEC755A"),
    (D(2026, 11, 25, 9, 30), "I-o-T", "BCS701"),
]
DURATION = _dt.timedelta(minutes=90)
STUDY_UNTIL = D(2026, 11, 25, 11, 0)
STALE = 30 * 60      # a reminder more than 30 min late (hub was down) is dropped, not spoken late


def study_mode(now=None):
    """True until Wed 25 Nov 11:00: Nova keeps quiet about non-urgent stuff (buyer messages/orders still speak)."""
    return (now or D.now()) < STUDY_UNTIL


def _clock(t):
    return t.strftime("%I:%M").lstrip("0") + (" AM" if t.hour < 12 else " PM")


def _left(delta):
    m = int(delta.total_seconds() // 60)
    d, h, m = m // 1440, m // 60 % 24, m % 60
    parts = ["%d day%s" % (d, "s" * (d != 1))] if d else []
    if h: parts.append("%d hour%s" % (h, "s" * (h != 1)))
    if not d and m: parts.append("%d minute%s" % (m, "s" * (m != 1)))
    return " ".join(parts) or "less than a minute"


def next_exam(now=None) -> str:
    """'Nova, what's my next exam?' -> subject, when, time left (or 'in progress')."""
    now = now or D.now()
    for t, name, code in EXAMS:
        if t <= now < t + DURATION:
            return "%s (%s) is on right now, until %s." % (name, code, _clock(t + DURATION))
        if now < t:
            day = "today" if t.date() == now.date() else "tomorrow" if t.date() == now.date() + _dt.timedelta(1) else t.strftime("%A")
            return "Your next exam is %s, %s, %s at %s. That's in %s." % (name, code, day, _clock(t), _left(t - now))
    return "No more exams, sir. IA-2 is done."


def reminders():
    """[(due datetime, text)]: 9:30 PM the night before each exam day, 7:30 AM on the day."""
    days = sorted({t.date() for t, _, _ in EXAMS})
    out = []
    for day in days:
        subs = [n for t, n, _ in EXAMS if t.date() == day]
        first = min(t for t, _, _ in EXAMS if t.date() == day)
        what = " and ".join(subs)
        out.append((D.combine(day - _dt.timedelta(1), _dt.time(21, 30)),
                    "Tomorrow: %s. First one at %s. Get some sleep" % (what, _clock(first))))
        out.append((D.combine(day, _dt.time(7, 30)),
                    "Exam day: %s. First one at %s. Leave on time and take your hall ticket" % (what, _clock(first))))
    return out


def arm(add, pending, now=None):
    """Put the future exam reminders into Nova's reminder file (once each). add(secs, msg) = nova._add_reminder."""
    now = now or D.now()
    have = {x["msg"] for x in pending}
    n = 0
    for due, msg in reminders():
        if due > now and msg not in have:
            add((due - now).total_seconds(), msg); n += 1
    return n


if __name__ == "__main__":       # self-check
    S = D(2026, 11, 22, 20, 0)
    assert "Parallel Computing" in next_exam(S) and "tomorrow at 9:30 AM" in next_exam(S) and "13 hours" in next_exam(S), next_exam(S)
    assert "on right now" in next_exam(D(2026, 11, 23, 10, 0))
    assert "Big Data" in next_exam(D(2026, 11, 23, 11, 5)) and "today at 2:00 PM" in next_exam(D(2026, 11, 23, 11, 5))
    assert "No more exams" in next_exam(D(2026, 11, 25, 11, 1))
    r = reminders()
    assert len(r) == 6 and r[0][0] == D(2026, 11, 22, 21, 30) and r[-1][0] == D(2026, 11, 25, 7, 30), r
    assert "Parallel Computing and Big Data Analytics" in r[0][1] and "9:30 AM" in r[0][1]
    assert study_mode(D(2026, 11, 25, 10, 59)) and not study_mode(D(2026, 11, 25, 11, 0))
    got = []
    assert arm(lambda s, m: got.append(m), [], S) == 6 and arm(lambda s, m: got.append(m), [{"msg": m} for m in got], S) == 0
    assert arm(lambda s, m: None, [], D(2026, 11, 24, 8, 0)) == 2      # Tue 21:30 + Wed 7:30 left
    print("exams ok")
