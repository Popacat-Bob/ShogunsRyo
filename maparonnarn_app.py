# Maparonnarn (Fennic Elven / Snow Elf dialect): dictionary + translator.
# Lean rebuild on the Shou-Chiang app scaffold. Vocabulary is read from a Google Doc.
# ── Gradio 5.9.1 gradio_client schema bug workaround (same as app.py) ──
try:
    import gradio_client.utils as _gcu
    _o1 = _gcu._json_schema_to_python_type
    def _s1(schema, defs=None):
        if not isinstance(schema, dict): return "Any"
        if "additionalProperties" in schema and not isinstance(schema["additionalProperties"], dict):
            schema = {k: v for k, v in schema.items() if k != "additionalProperties"}
        return _o1(schema, defs)
    _gcu._json_schema_to_python_type = _s1
    _o2 = _gcu.get_type
    def _s2(schema):
        if not isinstance(schema, dict): return "Any"
        return _o2(schema)
    _gcu.get_type = _s2
except Exception:
    pass

import os, re, time, json, random, threading, unicodedata, urllib.request, difflib
import gradio as gr

DOC_ID = "1W-116l4867x-l49Sjh8Wsox5y-SXZ2Zsz_Pw302d_DM"   # doc must be shared "anyone with the link"
DOC_URL = f"https://docs.google.com/document/d/{DOC_ID}/export?format=txt"
HERE = os.path.dirname(os.path.abspath(__file__))
CACHE = os.path.join(HERE, "maparonnarn_cache.txt")        # last successful live copy
SNAPSHOT = os.path.join(HERE, "maparonnarn_snapshot.txt")  # bundled copy, used if offline
SHEET_ID = "1VRkqLhSXYRvWEFtWNwlprYyNJtJmznOuwXMPXMeaVDM"   # Vel'luah sheet, shared "anyone with the link"
DARK_TABS = [("Special Words", "1721718391", "words"), ("Dictionary", "0", "dict"), ("Grammar", "1887383092", "grammar")]   # (title, gid, layout); add the Grammar tab's gid here if wanted
DARK_SNAPSHOT = os.path.join(HERE, "maparonnarn_dark_snapshot.csv")   # bundled copy of the Special Words tab
DARK_SNAPSHOTS = {"1721718391": DARK_SNAPSHOT, "1887383092": os.path.join(HERE, "maparonnarn_dark_grammar_snapshot.csv")}   # the Dictionary tab has none: it is live only
SAVED_FILE = os.path.join(HERE, "saved_lines.txt")   # lines you save from the line builder
MY_FILE = os.path.join(HERE, "my_words.txt")   # your own words: "Fennic = English", one per line
WIKI_FILE = os.path.join(HERE, "maparonnarn_wiki_snapshot.txt")  # bundled Common Elven wiki list (static)
TTL = 300                                                  # seconds between automatic re-syncs

# header line in the doc -> how its "A = B" lines are read
SECTIONS = {
    "race names": "rev", "pronouns": "rev",
    "words": "fwd", "married nouns": "fwd", "married verbs": "fwd", "adverbs": "fwd", "adjectives": "fwd",
    "greetings": "phr", "farewells": "phr", "common sayings": "phr", "insults": "phr", "blessings": "phr",
    "family structure": "fam", "counting": "num", "prefix/suffix": "aff",
    "grammar rules": "gram", "grammar in detail": "gram",
}
FE_FIRST = {"bortu"}   # the doc writes this one race line Fennic-first
STOP = {"the", "a", "an", "is", "are", "am", "be", "been", "being", "do", "does", "to", "of"}
PAST = {"was", "were", "did", "had", "yesterday"}
FUT = {"will", "shall", "gonna", "tomorrow"}
ALIAS = {"he": "him", "she": "her", "them": "they", "their": "theirs"}

def norm(s):
    s = unicodedata.normalize("NFKD", s.lower())
    s = "".join(c for c in s if not unicodedata.combining(c))
    return re.sub(r"[’‘'`\-]", "", s).strip()

def clean_def(m):
    if " — " in m: return m.split(" — ")[0].strip()   # dark elf entries: "direct translation — explanation"
    m = re.sub(r"\(.*?\)", "", m)
    m = re.split(r"\bLit\b\.?", m, 1, flags=re.I)[0].strip(" .,;/") or m.strip()
    return re.split(r"[.;:/] ", m, 1)[0] if len(m) > 60 else m

def en_keys(meaning):
    m = re.sub(r"\(.*?\)", "", meaning)
    m = re.split(r"\bLit\b\.?", m, 1, flags=re.I)[0]
    keys = []
    for part in re.split(r"[/,;]", m):
        p = re.sub(r"^(to|a|an|the)\s+", "", part.strip(" .!?'\"").lower())
        if p: keys.append(p)
    return keys

def _adder(W, E):
    def add(form, meaning, label, index=None):
        form = form.strip().strip(".!?, ")
        meaning = meaning.strip()
        if not form or not meaning: return
        if " " in form: return
        k = norm(form)
        if not k: return
        e = W.setdefault(k, {"form": form, "defs": [], "sec": label})
        if meaning not in e["defs"]: e["defs"].append(meaning)
        for key in (en_keys(meaning) if index is None else index):
            lst = E.setdefault(key, [])
            if form not in lst: lst.append(form)
    return add

def parse_wiki(text):
    """Common Elven (Lord of the Craft wiki): '## Section' headers, 'word: meaning' lines."""
    W, E = {}, {}
    add, label = _adder(W, E), "Wiki"
    for raw in text.split("\n"):
        line = raw.strip()
        if line.startswith("## "): label = "Wiki: " + line[3:]; continue
        if ": " in line:
            form, meaning = line.split(": ", 1); add(form, meaning, label)
    return {"WW": W, "WE": E}

NUMS = ["zero", "one", "two", "three", "four", "five", "six", "seven", "eight", "nine", "ten"]

DICT_CATS = ["Prefixes", "Suffixes", "Verbs", "Nouns", "Pronouns", "Articles", "Question Words", "Conjunctions", "Prepositions", "Adjectives", "Adverbs"]

def _parse_dict_tab(rows, add, P, A, label):
    """Dictionary tab: a (Common | Vel'luah) column pair per word type, spacer columns between."""
    if not rows: return
    head = rows[0]
    starts = [i for i in range(len(head) - 1) if head[i].strip().lower() == "common" and "vel" in head[i + 1].lower()]
    for c, i in enumerate(starts):
        cat = DICT_CATS[c] if c < len(DICT_CATS) else f"Column {i + 1}"
        for row in rows[1:]:
            en = row[i].strip() if i < len(row) else ""
            ve = row[i + 1].strip() if i + 1 < len(row) else ""
            if not en or not ve: continue
            if cat in ("Prefixes", "Suffixes") or ve.startswith("-") or ve.endswith("-"):
                A.append((ve, en)); continue
            if " " in ve: P.append((ve, en, f"{label} / {cat}"))
            else: add(ve, en, f"{label} / {cat}", index=en_keys(re.sub(r"\[.*?\]", "", en)))

def parse_dark(sources):
    """Vel'luah sheet tabs as CSV: A word, B meaning, C direct translation, F/G numeral or suffix."""
    import csv, io
    W, E, P, N, A, DL, DG = {}, {}, [], {}, [], {}, []
    add = _adder(W, E)
    for title, kind, text in sources:
        label = "Dark Elf: " + title
        if kind == "grammar":
            DG += [r[0].strip() for r in csv.reader(io.StringIO(text)) if r and r[0].strip()]; continue
        if kind == "dict":
            _parse_dict_tab(list(csv.reader(io.StringIO(text))), add, P, A, label); continue
        for i, row in enumerate(csv.reader(io.StringIO(text))):
            if i == 0: continue
            form, mean, direct, num, nw = ((row + [""] * 8)[j].strip() for j in (0, 1, 2, 5, 6))
            lt, gl = (row + [""] * 8)[3].strip(), (row + [""] * 8)[4].strip()
            if lt and gl: DL[lt[0].lower()] = gl   # letter table for the script tab
            if num and nw:
                if num.isdigit():
                    N[int(num)] = nw
                    if int(num) < len(NUMS): add(nw, f"number {num}", "Dark Elf: numerals", index=[NUMS[int(num)]])
                else: A.append((nw, f"suffix for {num}"))
            if not form: continue
            ok = bool(direct) and direct.upper() != "N/A"
            meaning = f"{direct} — {mean}" if ok else mean
            keys = en_keys(direct) if ok and not re.search(r"insult|derogatory", mean, re.I) else []
            for f in re.split(r"\s*/\s*|\s*\|\s*", form):
                g = re.search(r"\((fem|masc)\)", f)
                f = re.sub(r"\s*\((fem|masc)\)", "", f).strip()
                m = f"({g.group(1)}) {meaning}" if g else meaning
                if not f: continue
                if " " in f: P.append((f, m, label))
                else: add(f, m, label, index=keys)
    return {"DW": W, "DE": E, "DP": P, "DN": N, "DA": A, "DL": DL, "DG": "\n\n".join(DG)}

def load_mine():
    W, E, MP = {}, {}, []
    add = _adder(W, E)
    for raw in (_read(MY_FILE) if os.path.exists(MY_FILE) else "").split("\n"):
        if "=" in raw and not raw.lstrip().startswith("#"):
            a, b = raw.split("=", 1); add(a, b, "My words")
            if " " in a.strip(): MP.append((a.strip(), b.strip(), "My words"))
    return {"MW": W, "ME": E, "MP": MP}

def get_mine():
    return _read(MY_FILE) if os.path.exists(MY_FILE) else "# Fennic = English, one per line. Your words win over every dialect.\n"

def save_mine(text):
    try:
        with open(MY_FILE, "w", encoding="utf-8") as f: f.write(text or "")
    except OSError as e:
        return f"Could not save: {e}"
    d = load(); d.update(load_mine())
    return f"Saved. {len(d['MW'])} word(s) in your list."

# The 19 letters from the sheet's Grammar tab, built in so the script tab works even if the sheet can't be reached
DEFAULT_LETTERS = dict(zip("mztubgelkdyraxvhons", "ɱչȶʊɮɠɛʅӄðψᵲα" "ᛪʋɦ¤ռʂ"))

def to_script(text, translate=True):
    """Latin letters -> Vel'luah script. With translate on, English is put into Vel'luah (Dark Elf dictionary) first."""
    L = {**DEFAULT_LETTERS, **load().get("DL", {})}
    conv = lambda t: "".join(L.get(c.lower(), c) for c in t)
    if not translate: return conv(text or "")
    res = to_fennic(text, [DARK])
    if res.startswith("Type"): return ""
    latin = res.split("\n")[0].replace("### ", "", 1)
    kept = {k.lower() for k in re.findall(r"\*\*(.+?)\*\*: not in the dictionary", res)}   # words with no Vel'luah entry stay in Latin letters
    script = re.sub(r"\S+", lambda m: m.group(0) if m.group(0).lower().strip(".,;:!?") in kept else conv(m.group(0)), latin)
    return f"{latin}\n{script}"

def fetch_sheet(gid, timeout=15):
    url = f"https://docs.google.com/spreadsheets/d/{SHEET_ID}/export?format=csv&gid={gid}"
    req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        text = r.read().decode("utf-8-sig", "replace")
    if text.lstrip()[:15].lower().startswith(("<!doctype", "<html")):
        raise ValueError("Google returned a web page, not the sheet (is it shared as 'anyone with the link'?)")
    return text

def load_dark():
    sources, kinds, errs = [], set(), []
    for n, (title, gid, kind) in enumerate(DARK_TABS):
        cache = os.path.join(HERE, f"maparonnarn_dark_{gid}.csv")
        try:
            text, src = fetch_sheet(gid), "live Google Sheet"
            try:
                with open(cache, "w", encoding="utf-8") as f: f.write(text)
            except OSError:
                pass
        except Exception as e:
            errs.append(f"{title}: {type(e).__name__}: {e}"[:150])
            text, src = None, ""
            for p, k in ((cache, "last saved copy"), (DARK_SNAPSHOTS.get(gid, ""), "built-in copy")):
                if p and _snap(p): text, src = _snap(p), k; break
        if text: sources.append((title, kind, text)); kinds.add(src)
    return dict(parse_dark(sources), dsrc=" + ".join(sorted(kinds)) or "none", derr=" | ".join(errs))

def parse(text):
    W, E, P, N, A, G = {}, {}, [], {}, [], []
    sec = None
    add = _adder(W, E)
    for raw in text.split("\n"):
        line = raw.strip()
        key = line.rstrip(":").strip().lower()
        if key in SECTIONS:
            sec = SECTIONS[key]; label = key.title(); continue
        if not line or sec is None: continue
        kind = sec
        if kind == "gram":
            G.append(line); continue
        if kind == "num":
            m = re.match(r"^(\w+)\s*=\s*(\d+)\s*$", line)
            if m: N[int(m.group(2))] = m.group(1)
            continue
        if kind == "fam":
            m = re.match(r"^([^,=]+),\s*(.+)$", line)
            if m: add(m.group(1), m.group(2), label)
            continue
        if kind == "aff":
            if "=" in line:
                a, b = line.split("=", 1); A.append((a.strip(), b.strip()))
            continue
        if "=" in line:
            left, right = (s.strip() for s in line.split("=", 1))
            if not left or not right: continue
            if kind == "rev":
                en, fe = (right, left) if norm(left) in FE_FIRST else (left, right)
                m = re.match(r"^(.*?)\s*\((.*)$", fe)
                note, fe = (m.group(2).rstrip(") "), m.group(1)) if m else ("", fe)
                for f in fe.split("/"):
                    add(f, f"{en} ({note})" if note else en, label)
                continue
            if kind == "phr": P.append((left, right, label))
            add(left, right, label)
            continue
        if kind == "phr":
            m = re.match(r"^(.+?)\s*\((.+)\)\s*$", line)
            if m:
                P.append((m.group(1).strip(), m.group(2).strip(), label)); add(m.group(1), m.group(2), label)
    return {"W": W, "E": E, "P": P, "N": N, "A": A, "G": re.sub(r"\n{3,}", "\n\n", "\n".join(G))}

def fetch_doc(timeout=15):
    req = urllib.request.Request(DOC_URL, headers={"User-Agent": "Mozilla/5.0"})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        raw = r.read().decode("utf-8-sig", "replace")
    text = raw.replace("\r\n", "\n").replace("\r", "\n")
    if text.lstrip()[:15].lower().startswith(("<!doctype", "<html")) or text.count("=") < 50:
        raise ValueError("Google returned a web page, not the text (is the doc shared as 'anyone with the link'?)")
    return text

_lock, _DB = threading.Lock(), {}

def _read(p):
    with open(p, encoding="utf-8") as f: return f.read()

def _snap(p):
    """A snapshot file next to the app if it exists, otherwise the copy built into this file (see the end)."""
    return _read(p) if os.path.exists(p) else _EMBEDDED.get(os.path.basename(p), "")

def load(force=False):
    global _DB
    with _lock:
        if _DB and not force and time.time() - _DB["t"] < TTL: return _DB
        err, text, src = "", None, ""
        try:
            text, src = fetch_doc(), "live Google Doc"
            try:
                with open(CACHE, "w", encoding="utf-8") as f: f.write(text)
            except OSError:
                pass
        except Exception as e:
            err = f"{type(e).__name__}: {e}"[:160]
            if _DB:
                _DB["t"], _DB["err"] = time.time(), err
                return _DB
            for p, name in ((CACHE, "last saved copy"), (SNAPSHOT, "built-in copy")):
                if _snap(p):
                    text, src = _snap(p), name; break
            if text is None: text, src = "", "nothing (offline and no snapshot)"
        _DB = parse(text)
        _DB.update(parse_wiki(_snap(WIKI_FILE)))
        _DB.update(load_dark())
        _DB.update(load_mine())
        _DB.update(src=src, err=err, t=time.time(), stamp=time.strftime("%Y-%m-%d %H:%M"))
        return _DB

def status_md(d):
    s = f"**Source:** {d['src']} · synced {d['stamp']} · **{len(d['W'])}** words · **{len(d['P'])}** phrases · numbers {len(d['N'])}/100 · wiki list: **{len(d['WW'])}** words (bundled) · dark elf: **{len(d['DW'])}** words, **{len(d['DP'])}** phrases ({d['dsrc']}) · my words: **{len(d['MW'])}**"
    if d.get("derr"): s += f"\n\n⚠️ Dark Elf sheet could not be downloaded: {d['derr']}. Special Words and Grammar use the built-in copy; the Dictionary tab has no built-in copy, so its words are missing until the download works."
    if d.get("err"): s += f"\n\n⚠️ Live sync failed ({d['err']}). Still showing the {d['src']} from {d['stamp']}."
    return s

MODES = ["Snow Elf (doc)", "Common Elven (wiki)", "Dark Elf (Vel'luah)"]
SNOW, WIKI, DARK = MODES

def _sel(mode):
    """Ticked dialects as a set (a plain string works too); nothing ticked falls back to Snow Elf."""
    sel = {mode} if isinstance(mode, str) else set(mode or [])
    return (sel & set(MODES)) or {SNOW}

def view(d, mode):
    """Words/English index for the ticked dialects. Priority when mixing: Snow Elf, then Dark Elf, then wiki."""
    sel = _sel(mode)
    parts = [(t, wk, ek) for t, wk, ek in ((SNOW, "W", "E"), (DARK, "DW", "DE"), (WIKI, "WW", "WE")) if t in sel]
    if d["MW"]: parts.insert(0, ("My words", "MW", "ME"))
    if len(parts) == 1: return d[parts[0][1]], d[parts[0][2]]
    tags = {SNOW: "snow", DARK: "dark", WIKI: "wiki", "My words": "mine"}
    W, E = {}, {}
    for t, wk, ek in parts:
        for k, e in d[wk].items():
            if k in W: W[k]["defs"] += [f"({tags[t]}) " + x for x in e["defs"]]
            else: W[k] = dict(e, defs=list(e["defs"]))
        for k, v in d[ek].items():
            lst = E.setdefault(k, [])
            lst += [f for f in v if f not in lst]
    return W, E

# ── translation ───────────────────────────────────────────────────────────
def variants(w):
    """Possible base forms of an English word, with what the ending was ('s', 'ing', 'ed', 'ly')."""
    out = []
    if w.endswith("ies") and len(w) > 4: out.append((w[:-3] + "y", "s"))
    if w.endswith("es") and len(w) > 3: out.append((w[:-2], "s"))
    if w.endswith("s") and len(w) > 3 and not w.endswith("ss"): out.append((w[:-1], "s"))
    for suf in ("ing", "ed"):
        if w.endswith(suf) and len(w) > len(suf) + 2:
            b = w[:-len(suf)]
            out += [(b, suf), (b + "e", suf)] + ([(b[:-1], suf)] if len(b) > 2 and b[-1] == b[-2] else [])
    if w.endswith("ly") and len(w) > 4: out.append((w[:-2], "ly"))
    return out

def find_en(w, E):
    """English word -> (Fennic candidates, ending kind). Exact match first, then base forms (hates, hating, hated...)."""
    c = E.get(w) or E.get(ALIAS.get(w, w))
    if c: return c, None
    for b, k in variants(w):
        c = E.get(b)
        if c: return c, k
    return None, None

def phrase_maps(d, mode):
    """Multi-word phrases of the ticked dialects (plus your own): English words -> Fennic, and Fennic words -> English."""
    sel = _sel(mode)
    rows = list(d["MP"]) + (d["P"] if SNOW in sel else []) + (d["DP"] if DARK in sel else [])
    e2f, f2e = {}, {}
    for fe, en, _ in rows:
        fe = fe.strip().rstrip(".!?")
        mean = clean_def(en)
        kf = tuple(norm(w) for w in fe.split())
        if len(kf) > 1: f2e.setdefault(kf, mean)
        ke = tuple(re.findall(r"[a-z']+", mean.lower().replace("’", "'")))
        if 1 < len(ke) <= 6: e2f.setdefault(ke, fe)
    return e2f, f2e

ARTICLES = {"the": "el", "a": "o", "an": "ga"}   # Vel'luah articles attach to the back of nouns
DARK_PAST, DARK_FUT = {"did", "had"}, {"shall", "gonna"}   # "was/were" and "will" have their own Vel'luah words

def attach(word, sfx):
    """Latch a suffix onto a word; if the word already ends with the suffix's first letter, that letter is skipped."""
    return word + (sfx[1:] if sfx[0].isalpha() and word.lower().endswith(sfx[0].lower()) else sfx)

def to_fennic(text, mode=MODES[0], sov=False):
    d, out, verbs, notes, tense = load(), [], [], [], None
    W, E = view(d, mode)
    e2f, _ = phrase_maps(d, mode)
    snow = SNOW in _sel(mode)               # Snow Elf grammar wins when ticked: tense ia, plural 'len, possessive au'
    dark = DARK in _sel(mode) and not snow  # otherwise Vel'luah grammar: a'/e' tense, -zh plural, -el/-o/-ga articles, 'uhn possessive
    pend_t = pend_a = None
    toks = re.findall(r"[A-Za-z][A-Za-z'’]*", text or "")
    i = 0
    while i < len(toks):
        hit = None
        for n in range(min(6, len(toks) - i), 1, -1):   # whole phrases first (longest match)
            k = tuple(t.lower().replace("’", "'") for t in toks[i:i + n])
            if k in e2f: hit = (n, e2f[k]); break
        if hit:
            out.append(hit[1]); verbs.append(False); i += hit[0]; continue
        raw = toks[i]; w = raw.lower().replace("’", "'"); i += 1
        if snow and w in PAST: tense = "past"; continue
        if snow and w in FUT: tense = "future"; continue
        if snow and w == "going" and i < len(toks) and toks[i].lower() == "to": tense = "future"; i += 1; continue
        if snow and w in STOP: continue
        if dark and not E.get(w):
            if w in DARK_PAST: pend_t = "a’"; continue
            if w in DARK_FUT: pend_t = "e’"; continue
            if w in ARTICLES: pend_a = ARTICLES[w]; continue
        poss = (snow or dark) and w.endswith("'s")
        if poss: w = w[:-2]
        c, kind = find_en(w, E)
        if not c and w in ("i", "my"): c = E.get("me")   # wiki list only has "me"
        ent = W.get(norm(c[0]), {}) if c else {}
        isverb = "Verbs" in ent.get("sec", "") or any(x.lower().startswith("to ") for x in ent.get("defs", []))
        isnoun = "Nouns" in ent.get("sec", "")
        if c:
            f = c[0]
            if len(c) > 1: notes.append(f"- **{raw}**: also {', '.join(c[1:6])}")
        else:
            f = raw[:-2] if poss else raw   # not in the chosen dictionary: left in English (without its 's)
            if not raw[0].isupper(): notes.append(f"- **{raw}**: not in the dictionary, left in English")
        if kind == "s":                     # a plural noun, or a verb ending in -s
            if snow and not isverb: f += "’len"
            elif dark and isnoun: f = attach(f, "zh")
        elif kind == "ed":
            if snow: tense = "past"
            elif dark and isverb: pend_t = pend_t or "a’"
        elif kind == "ing" and dark and isverb: f = attach(f, "ule")
        if dark and pend_t and isverb: f, pend_t = pend_t + f, None
        if dark and pend_a and isnoun: f, pend_a = attach(f, pend_a), None
        if poss: f = attach(f, "’uhn") if dark else "au’" + f
        out.append(f); verbs.append(isverb)
    if not out: return "Type an English sentence."
    moved = sov and snow and any(verbs)
    if moved: out = [f for f, v in zip(out, verbs) if not v] + [f for f, v in zip(out, verbs) if v]
    if tense == "past": out[0] = "Ia’" + out[0]
    elif tense == "future": out[0] += "’ia"
    order = ("Word order is as typed; the Snow Elf doc's order is Subject, Object, Verb." if snow and not moved else
             "Verbs moved to the end (Subject, Object, Verb) as a best guess; check the result." if moved else
             "Word order is as typed; in Vel'luah the predicate follows the subject." if dark else "Word order is as typed.")
    return f"### {' '.join(out)}\n\n{order}\n\n" + "\n".join(notes)

# ── pick-which-words mode (roleplay: translate only a few words, keep the rest as typed) ──
def lookup_en(raw, E, affixes=True):
    """English word -> Fennic form or None; handles base forms (likes, liking, liked), plural 's and possessive 's."""
    w = raw.lower().replace("’", "'")
    poss = affixes and w.endswith("'s")
    if poss: w = w[:-2]
    c, kind = find_en(w, E)
    if not c and w in ("i", "my"): c = E.get("me")
    if not c: return None
    f = c[0] + ("’len" if affixes and kind == "s" else "")
    return "au’" + f if poss else f

def word_options(text, mode=MODES[0]):
    _, E = view(load(), mode)
    aff = SNOW in _sel(mode)
    seen, choices = set(), []
    for raw in re.findall(r"[A-Za-z][A-Za-z'’]*", text or ""):
        w, f = raw.lower().replace("’", "'"), lookup_en(raw, E, aff)
        if f and w not in seen:
            seen.add(w); choices.append((f"{raw} → {f}", w))
    return gr.update(choices=choices, value=[])

STYLES = ["Plain", "Italics", "Bold", "With the original word in brackets"]

def partial(text, picks, mode=MODES[0], style=STYLES[0]):
    _, E = view(load(), mode)
    aff = SNOW in _sel(mode)
    picks = set(picks or [])
    def sub(m):
        raw = m.group(0)
        f = lookup_en(raw, E, aff) if raw.lower().replace("’", "'") in picks else None
        if not f: return raw
        return {"Italics": f"*{f}*", "Bold": f"**{f}**", STYLES[3]: f"{f} ({raw})"}.get(style, f)
    return re.sub(r"[A-Za-z][A-Za-z'’]*", sub, text or "")

def gloss_word(W, base, split=True):
    e = W.get(norm(base))
    if e: return clean_def(e["defs"][0]), "; ".join(e["defs"])
    parts = [p for p in re.split(r"[’‘'\-]", base) if p]
    if split and len(parts) > 1:
        es = [W.get(norm(p)) for p in parts]
        if any(es): return " + ".join(clean_def(x["defs"][0]) if x else "?" for x in es), ""
    return None, ""

def gloss_token(W, tok):
    """One Fennic word -> (short gloss, all meanings, endings found such as past or plural)."""
    t = tok.strip(".").replace("‘", "’").replace("'", "’")
    g, allm = gloss_word(W, t, split=False)
    flags, b = [], t
    if g is None:
        if b.lower().startswith("ia’"): flags.append("past"); b = b[3:]
        if b.lower().endswith("’ia"): flags.append("future"); b = b[:-3]
        if b.lower().startswith("au’"): flags.append("possessive"); b = b[3:]
        if b.lower().endswith("’len"): flags.append("plural"); b = b[:-4]
        if b.lower().startswith("tr’"): flags.append("verb"); b = b[3:]
        g, allm = gloss_word(W, b, split=False)
    if g is None: g, allm = gloss_word(W, b)
    if g is None: g, allm = b, "not in the dictionary, left as written"
    return g, allm, flags

TOKEN_RE = r"[^\s,;:!?()\[\]]+"

def to_english(text, mode=MODES[0]):
    d, sent, rows = load(), [], []
    W, _ = view(d, mode)
    _, f2e = phrase_maps(d, mode)
    toks = re.findall(TOKEN_RE, text or "")
    i = 0
    while i < len(toks):
        hit = None
        for n in range(min(6, len(toks) - i), 1, -1):   # whole phrases first (longest match)
            k = tuple(norm(t.strip(".")) for t in toks[i:i + n])
            if k in f2e: hit = (n, f2e[k]); break
        if hit:
            n, g = hit
            sent.append(g); rows.append(f"| {' '.join(toks[i:i + n])} | {g} | phrase |"); i += n; continue
        tok = toks[i]; i += 1
        g, allm, flags = gloss_token(W, tok)
        if flags: g += f" ({'/'.join(flags)})"
        sent.append(g)
        rows.append(f"| {tok} | {g} | {allm.replace('|', '/')} |")
    if not sent: return "Type a Fennic sentence."
    return f"### {' · '.join(sent)}\n\n| Fennic | Gloss | All meanings |\n|---|---|---|\n" + "\n".join(rows)

def word_options_rev(text, mode=MODES[0]):
    W, _ = view(load(), mode)
    seen, choices = set(), []
    for tok in re.findall(TOKEN_RE, text or ""):
        g, allm, _ = gloss_token(W, tok)
        key = tok.strip(".").lower()
        if "not in the dictionary" not in allm and key not in seen:
            seen.add(key); choices.append((f"{tok.strip('.')} → {g}", key))
    return gr.update(choices=choices, value=[])

def partial_rev(text, picks, mode=MODES[0], style=STYLES[0]):
    W, _ = view(load(), mode)
    picks = set(picks or [])
    def sub(m):
        tok = m.group(0); core = tok.rstrip("."); tail = tok[len(core):]
        if core.lower() not in picks: return tok
        g = gloss_token(W, core)[0]
        return {"Italics": f"*{g}*", "Bold": f"**{g}**", STYLES[3]: f"{g} ({core})"}.get(style, g) + tail
    return re.sub(TOKEN_RE, sub, text or "")

# ── roleplay line builder and saved lines ──
LINE_FORMATS = ["Name says, “…”", "Name: …", "“…” Name says", "Just the words"]

def build_line(speaker, english, mode=MODES[0], fmt=LINE_FORMATS[0], note=False, emote="", sov=False):
    res = to_fennic(english, mode, sov)
    if res.startswith("Type"): return ""
    fen = res.split("\n")[0].replace("### ", "", 1)
    who = (speaker or "").strip()
    if not who: line = f"“{fen}”" if fmt != LINE_FORMATS[3] else fen
    else: line = {LINE_FORMATS[0]: f"{who} says, “{fen}”", LINE_FORMATS[1]: f"{who}: {fen}", LINE_FORMATS[2]: f"“{fen}” {who} says"}.get(fmt, fen)
    if (emote or "").strip(): line = f"*{emote.strip()}* " + line
    return line + (f" ({english.strip()})" if note else "")

def get_saved():
    return _read(SAVED_FILE) if os.path.exists(SAVED_FILE) else ""

def write_saved(text):
    try:
        with open(SAVED_FILE, "w", encoding="utf-8") as f: f.write(text or "")
    except OSError as e:
        return f"Could not save: {e}"
    return "Saved."

def add_saved(line):
    if not (line or "").strip(): return "Build a line first.", get_saved()
    cur = get_saved().rstrip("\n")
    msg = write_saved(cur + ("\n" if cur else "") + line.strip() + "\n")
    return ("Added to your saved lines." if msg == "Saved." else msg), get_saved()

# ── practice cards ──
DIRS = ["Fennic → English", "English → Fennic"]

def new_card(direction, mode=MODES[0], st=""):
    W, E = view(load(), mode)
    pool = [e for e in W.values() if e["defs"] and 0 < len(clean_def(e["defs"][0])) <= 40]
    try: c = json.loads(st or "{}")
    except ValueError: c = {}
    score = f"{c.get('c', 0)}/{c.get('t', 0)}"
    if not pool: return "No words loaded for the ticked dialects.", "", "", st
    e = random.choice(pool); meaning = clean_def(e["defs"][0])
    if direction == DIRS[1]:
        keys = en_keys(e["defs"][0]) or [meaning.lower()]
        answers = sorted({norm(f) for f in {e["form"]} | {x for k in keys for x in E.get(k, [])}})
        prompt, shown = f"### {meaning}\nHow do you say it?", e["form"]
    else:
        answers = sorted({norm(k) for dfn in e["defs"] for k in en_keys(dfn)} | {norm(meaning.lower())})
        prompt, shown = f"### {e['form']}\nWhat does it mean?", meaning
    state = json.dumps({"a": answers, "s": shown, "all": "; ".join(e["defs"])[:160], "c": c.get("c", 0), "t": c.get("t", 0), "done": False})
    return f"{prompt}\n\nScore so far: {score}", "", "", state

def check_card(answer, st=""):
    try: c = json.loads(st or "")
    except ValueError: return "Press **New card** first.", st
    a = norm((answer or "").strip().lower().strip(" .!?,"))
    ok = bool(a) and a in c["a"]
    if not c.get("done"): c["t"] += 1; c["c"] += 1 if ok else 0; c["done"] = True
    fb = f"✅ Correct: **{c['s']}** ({c['all']})" if ok else f"❌ Not quite. Answer: **{c['s']}** ({c['all']})"
    return f"{fb}\n\nScore: {c['c']}/{c['t']}", json.dumps(c)

# ── dictionary, browse, numbers ───────────────────────────────────────────
def search(q, mode=MODES[0]):
    d, q = load(), (q or "").strip()
    W, E = view(d, mode)
    if not q: return "Type a Fennic or English word."
    k, ql, hits = norm(q), q.lower(), []
    if k in W: hits.append(k)
    for ek, forms in E.items():
        if ek == ql: hits += [norm(f) for f in forms]
    for kk, e in W.items():
        if kk.startswith(k) or any(ql in m.lower() for m in e["defs"]): hits.append(kk)
    hits += difflib.get_close_matches(k, list(W), n=6, cutoff=0.75)
    seen, lines = set(), []
    for kk in hits:
        if kk in seen or kk not in W: continue
        seen.add(kk); e = W[kk]
        lines.append(f"- **{e['form']}**: {'; '.join(e['defs'])} · *{e['sec']}*")
        if len(lines) >= 40: break
    return "\n".join(lines) or f"Nothing found for “{q}”."

def browse(kind, flt, mode=MODES[0]):
    d, f = load(), (flt or "").lower()
    W, _ = view(d, mode)
    sel = _sel(mode)
    sn, dk = SNOW in sel, DARK in sel
    if kind == "Phrases":
        rows = ([list(r) for r in d["P"]] if sn else []) + ([list(r) for r in d["DP"]] if dk else [])
    elif kind == "Numbers":
        rows = ([[w, str(n), "Snow Elf numbers"] for n, w in sorted(d["N"].items())] if sn else []) + ([[w, str(n), "Dark Elf (Vel'luah) numerals"] for n, w in sorted(d["DN"].items())] if dk else [])
    elif kind == "Affixes":
        rows = ([[a, b, "Prefix/Suffix"] for a, b in d["A"]] if sn else []) + ([[a, b, "Vel'luah suffixes"] for a, b in d["DA"]] if dk else [])
    elif kind == "Overlaps":
        seen = {}
        for t, wk in ((SNOW, "W"), (DARK, "DW"), (WIKI, "WW")):
            if t in sel:
                for k, e in d[wk].items(): seen.setdefault(k, []).append((t.split(" (")[0], e))
        rows = [[v[0][1]["form"], " | ".join(f"{t}: " + "; ".join(e["defs"]) for t, e in v), "Overlap"] for k, v in sorted(seen.items()) if len(v) > 1]
    else: rows = [[e["form"], "; ".join(e["defs"]), e["sec"]] for e in sorted(W.values(), key=lambda e: norm(e["form"]))]
    if f: rows = [r for r in rows if f in " ".join(r).lower()]
    return rows[:1000]

def snow_number(v, d):
    if v >= 10**10: return "Use 0 to 9,999,999,999."
    if len(d["N"]) < 100: return "The doc's 0-99 table is incomplete."
    s, groups = str(v), []
    while s: groups.insert(0, int(s[-2:])); s = s[:-2]
    sfx = ["", "’firr", "’ilk", "’elam", "’karr"]
    return ", ".join(d["N"][g] + sfx[len(groups) - 1 - i] for i, g in enumerate(groups))

DEFAULT_NUMBERS = dict(enumerate("sly az nyt hek zag kru vho reu xyn bex unz".split()))

def dark_number(v, d):
    """Vel'luah: number words 0-10, factor suffixes -ah (10s) -ee (100s) -he (1000s), factors joined by hyphens, zero places skipped."""
    N = {**DEFAULT_NUMBERS, **d["DN"]}
    if v == 0: return N[0]
    if v >= 10000: return "The sheet's rules are only clear up to 9,999."
    th, r = divmod(v, 1000); h, r = divmod(r, 100); t, u = divmod(r, 10)
    parts = []
    if th: parts.append(attach(N[th], "he"))
    if h: parts.append(attach(N[h], "ee"))
    if t == 1 and u == 0: parts.append(N[10])   # ten has its own word
    elif t: parts.append(attach(N[t], "ah"))
    if u: parts.append(N[u])
    return "-".join(parts)

def number(n, mode=MODES[0]):
    d, sel, lines = load(), _sel(mode), []
    try: v = int(str(n).strip().replace(",", ""))
    except ValueError: return "Enter a whole number."
    if v < 0: return "Use a whole number from 0 up."
    if SNOW in sel: lines.append(f"{SNOW}: {snow_number(v, d)}")
    if DARK in sel: lines.append(f"{DARK}: {dark_number(v, d)}")
    if WIKI in sel: lines.append(f"{WIKI}: the wiki list has number words but no number system, so there is no converter.")
    return "\n".join(lines)

def grammar_text(d, mode):
    sel, out = _sel(mode), []
    if SNOW in sel: out.append("══ Snow Elf (doc) ══\n" + (d["G"] or "(no grammar loaded)"))
    if DARK in sel: out.append("══ Dark Elf (Vel'luah) ══\n" + (d["DG"] or "(Grammar tab not loaded; check the sheet is shared as 'anyone with the link')"))
    if WIKI in sel: out.append("══ Common Elven (wiki) ══\nNo grammar notes are bundled for the wiki list. It is used as a plain word list, and the Snow Elf and Vel'luah rules are not applied to it.")
    return "\n\n".join(out)

def do_sync(kind, flt, mode=MODES[0]):
    d = load(force=True)
    return status_md(d), browse(kind, flt, mode), grammar_text(d, mode)

def refresh(kind, flt, mode=MODES[0]):
    d = load()
    return status_md(d), browse(kind, flt, mode), grammar_text(d, mode)

# ── UI ────────────────────────────────────────────────────────────────────
with gr.Blocks(title="Maparonnarn · Fennic Elven") as demo:
    gr.Markdown("# Maparonnarn · Fennic Elven (Snow Elf dialect)")
    status = gr.Markdown()
    sync_btn = gr.Button("🔄 Sync from Google Doc")
    mode = gr.CheckboxGroup(MODES, value=[MODES[0]], label="Dialects: tick one, or two or three to mix them (Snow Elf wins, then Dark Elf, then wiki)")
    with gr.Tabs():
        with gr.Tab("Translate"):
            e_in = gr.Textbox(label="English → Fennic", placeholder="I was cold")
            sov = gr.Checkbox(label="Snow Elf: move verbs to the end (Subject, Object, Verb; a best guess)", value=False)
            e_btn = gr.Button("Translate to Fennic")
            e_out = gr.Markdown()
            pick_btn = gr.Button("Or pick which words to translate…")
            pick = gr.Dropdown(multiselect=True, allow_custom_value=True, choices=[], label="Pick the words to translate (the rest stay as typed). You can also type a word.")
            style = gr.Radio(STYLES, value=STYLES[0], label="Output style")
            p_out = gr.Textbox(label="Your sentence", lines=3, interactive=False, show_copy_button=True)
            f_in = gr.Textbox(label="Fennic → English", placeholder="Ia’Ayred ehyubor")
            f_btn = gr.Button("Translate to English")
            f_out = gr.Markdown()
            pick_btn_r = gr.Button("Or pick which Fennic words to translate…")
            pick_r = gr.Dropdown(multiselect=True, allow_custom_value=True, choices=[], label="Pick the Fennic words to translate (the rest stay as typed)")
            p_out_r = gr.Textbox(label="Your sentence", lines=3, interactive=False, show_copy_button=True)
        with gr.Tab("Line builder"):
            lb_name = gr.Textbox(label="Speaker (optional)", placeholder="Valyra")
            lb_in = gr.Textbox(label="What they say, in English", placeholder="good, thanks")
            lb_fmt = gr.Radio(LINE_FORMATS, value=LINE_FORMATS[0], label="Format")
            lb_emote = gr.Textbox(label="Action in italics before the line (optional)", placeholder="bows her head")
            lb_note = gr.Checkbox(label="Add the English in brackets after the line", value=False)
            lb_btn = gr.Button("Build the line")
            lb_out = gr.Textbox(label="Ready to paste", lines=3, interactive=False, show_copy_button=True)
            lb_save = gr.Button("Save this line")
            lb_msg = gr.Markdown()
        with gr.Tab("Practice"):
            pr_dir = gr.Radio(DIRS, value=DIRS[0], label="Quiz direction (uses the dialects ticked above)")
            pr_card = gr.Markdown()
            pr_ans = gr.Textbox(label="Your answer")
            pr_new = gr.Button("New card")
            pr_chk = gr.Button("Check")
            pr_fb = gr.Markdown()
            pr_st = gr.State("")
        with gr.Tab("Saved lines"):
            gr.Markdown("Lines you save from the line builder. Edit freely, then press Save changes. On a free host the file can reset when it restarts.")
            sv_box = gr.Textbox(lines=14, label="saved_lines.txt")
            sv_btn = gr.Button("Save changes")
            sv_msg = gr.Markdown()
        with gr.Tab("Search"):
            q = gr.Textbox(label="Word (either language)")
            q_btn = gr.Button("Search")
            q_out = gr.Markdown()
        with gr.Tab("Browse"):
            kind = gr.Radio(["Words", "Phrases", "Numbers", "Affixes", "Overlaps"], value="Words", label="Show")
            flt = gr.Textbox(label="Filter")
            table = gr.Dataframe(headers=["Fennic", "English", "Section"], interactive=False, wrap=True)
        with gr.Tab("Numbers"):
            n_in = gr.Textbox(label="Number (written in each language ticked above)", placeholder="1203")
            n_btn = gr.Button("Write the number")
            n_out = gr.Textbox(label="Result, by language", lines=3, interactive=False)
        with gr.Tab("My words"):
            gr.Markdown("One per line: `Fennic = English`. Your words win over every dialect. Saved next to the app (on a free host the file can reset when it restarts).")
            mine = gr.Textbox(lines=14, label="my_words.txt")
            mine_btn = gr.Button("Save my words")
            mine_msg = gr.Markdown()
        with gr.Tab("Vel'luah script"):
            sc_in = gr.Textbox(label="English, or Vel'luah in Latin letters", placeholder="good thanks")
            sc_tr = gr.Checkbox(label="Translate from English first (Dark Elf dictionary)", value=True)
            sc_out = gr.Textbox(label="Vel'luah (Latin) and script", lines=2, interactive=False, show_copy_button=True)
            gr.Markdown("With translation on, the first line is the Vel'luah and the second is the script. Words the dictionary doesn't have stay in English letters. Letters with no glyph stay as typed.")
        with gr.Tab("Grammar"):
            gram = gr.Textbox(label="Grammar notes (follow the dialects ticked above)", lines=28, interactive=False)
    outs = [status, table, gram]
    sync_btn.click(do_sync, [kind, flt, mode], outs, api_name=False)
    demo.load(refresh, [kind, flt, mode], outs, api_name=False)
    mode.change(refresh, [kind, flt, mode], outs, api_name=False)
    kind.change(refresh, [kind, flt, mode], outs, api_name=False)
    flt.change(refresh, [kind, flt, mode], outs, api_name=False)
    e_btn.click(to_fennic, [e_in, mode, sov], e_out, api_name=False); e_in.submit(to_fennic, [e_in, mode, sov], e_out, api_name=False)
    pick_btn.click(word_options, [e_in, mode], pick, api_name=False)
    pick.change(partial, [e_in, pick, mode, style], p_out, api_name=False)
    style.change(partial, [e_in, pick, mode, style], p_out, api_name=False)
    pick_btn_r.click(word_options_rev, [f_in, mode], pick_r, api_name=False)
    pick_r.change(partial_rev, [f_in, pick_r, mode, style], p_out_r, api_name=False)
    style.change(partial_rev, [f_in, pick_r, mode, style], p_out_r, api_name=False)
    mine_btn.click(save_mine, mine, mine_msg, api_name=False)
    demo.load(get_mine, None, mine, api_name=False)
    sc_in.change(to_script, [sc_in, sc_tr], sc_out, api_name=False)
    sc_tr.change(to_script, [sc_in, sc_tr], sc_out, api_name=False)
    f_btn.click(to_english, [f_in, mode], f_out, api_name=False); f_in.submit(to_english, [f_in, mode], f_out, api_name=False)
    q_btn.click(search, [q, mode], q_out, api_name=False); q.submit(search, [q, mode], q_out, api_name=False)
    n_btn.click(number, [n_in, mode], n_out, api_name=False); n_in.submit(number, [n_in, mode], n_out, api_name=False)
    lb_args = [lb_name, lb_in, mode, lb_fmt, lb_note, lb_emote, sov]
    lb_btn.click(build_line, lb_args, lb_out, api_name=False); lb_in.submit(build_line, lb_args, lb_out, api_name=False)
    lb_save.click(add_saved, lb_out, [lb_msg, sv_box], api_name=False)
    sv_btn.click(write_saved, sv_box, sv_msg, api_name=False)
    demo.load(get_saved, None, sv_box, api_name=False)
    pr_new.click(new_card, [pr_dir, mode, pr_st], [pr_card, pr_fb, pr_ans, pr_st], api_name=False)
    pr_chk.click(check_card, [pr_ans, pr_st], [pr_fb, pr_st], api_name=False); pr_ans.submit(check_card, [pr_ans, pr_st], [pr_fb, pr_st], api_name=False)

# ── Built-in copies of the bundled data files (used only when the file isn't next to the app) ──
_EMBEDDED = {
    'maparonnarn_snapshot.txt': "=== TAB: Maparonnarn | The Snow Elf Dialect\n  Errrrrrr\nRace names\nDark elf = Mali’ker / Mali’Hevu (suicidal bravery. Lit. Rooster)\n\nWood elf = Mali’wen / Wen (Annoying, lit. Grass)\n\n‘Thill =‘Thel / Thel’tarr (Thel, silver, pointless/prideful. Thel’tarr worthless and easily influenced)\n\nSnow elf = Mali’fenn (Elves of snow)\n\nHumans = Vala’ (Lit. Childish)\n\nOrcs = Urk (Lit. Nonsensical babble)\n\nToga. Bronze elves = Maerul (Lit. Brain rot\n\nBortu = Dwarves (Lit. Cave dwellers)\n\nHalfings = Igne’aethurr abopelu (Lit. Soul enslaved by fire air (smoke)) / Raelpelu (Lit. Slaves to the love of self)\n\n\nGrammar rules\nBasic sentence structure is Subject, object, verb. Ex, Onve dishes cleaning. This can be expanded upon, experiments are below\nSubjects, verbs and objects are in [], implied words that do not exist are in ()\n\n[Onve] [dishes] should (be) [cleaning]\n\n[Onve] where (is)?\n\n[Onve] very well [dishes] [cleaning]\n\n[Onve] very well [dishes] should be without error [cleaning]\n\n[Onve] open [gate] because [sees], he [laughs]\n\nThere are few connecting words like ‘is’ or ‘the’ instead words are joined together with context. Think…. “Why many word, few work” commas and pauses can be extremely important.\n\nThe tense of a sentence is entirely defined by the subject and the position of ia in relationship to it. If ia is a prefix the entire statement is past tense, if it is a suffix it is future tense. If absent it is present tense.\n\nTwo kanji characters can be joined together to make a new word. The left word is the primary definer, that is modified by the right word. Ex. Ker (night) alyu (good). Keraylu (Good night) Ayluker (Night is good)\n\nWhen joining Kanji, if there is a sound where the two words join, flanked on either side by the same sound, it, and the character immediately to the right of it is removed. Ex. Soce’weyu becomes Soce’yu\n\nIn the case of one sound being surrounded by three, or four of the same sound the procedure is as follows: the parent word keeps all sound, and the offending sounds on the donor word are removed. \n\nIf in the process of removing offending sounds a vowel is removed (a, e, i, o, u) the last proper vowel from the parent word is slotted as close as grammatically allowed to the parent word\n\nYou can never go wrong not marrying words. You can go very wrong marrying them\n\nTo make a word possessive, the prefix au’ is added. To make a word plural, the suffix ‘len is added.\n\n\nGrammar in detail\n\nA few ground rules for Fennic Elven must first be laid. Fennic Elven’s structure follows as such: Subject, object, verb.\n\nI like mangos becomes ‘I mangos like’\n\nI hate Jennifer becomes ‘I Jennifer hate’\n\n\tFennic elven is unique because of its short, yet diverse kanji-esque dictionary. From it, all expressions commonly used by Mali’fenn flow.\n\nSo too in Fennic Elven, lets take the words for I (Eyi) the word for platonic love (Uelei) and a name, Malin. These words would piece together as:\n\n“Eyi Malin uelei.” or “I (platonically) love Malin.”\n\n\n\tIn Fennic elven, the distinctions between distinct words can be dropped in the case of common words. These are what are regarded as the ‘simple phrases.’ Ex, good morning, how are you, are you wounded. Lets try it in comparison to some simple elven phrases we all know\n\nKarin’ayla (Good day) -----> Karnaylu (Good light.)\nKer’ayla (Good night)  -----> Keraylu (Good dark.)\n\n\tNotice how in Fennic Elven the literal translation changes somewhat. Karn and ker literally translate to light and dark and are used elsewhere. Where elven has a seperate word for darkness unrelated to Ker’ which strictly means night.\n\n\tNow lets try get a bit deeper into grammar. There are some words when merged that will have a letter sandwiched between two of the same sounds. Ikurn, the word for iron or warfare,  and indar, relating to study, are combined below. Watch the ‘i’ in the middle of the word, sandwiched between two n’s.\n\nIkurnindar -----> Ikurndar\n\n\tIn the case of a word mergence where the words sandwich a letter between two sounds the sound, and the invited sound from the introduced word (the one to the right) are removed.\n\n\tAn interesting case is that of Fenn (Literally meaning snow, or cold) and anorr (Meaning land). Because of a double n on the end of Fenn, a, and n must still be removed and replaced with the last vowel, e.\n\nFennanorr -----> Fenneorr\n\n\tSome verbs can also have a preparatory syllable or word. ‘Simple statements’ consist of no adjectives or adverbs. Instead they are a group of nouns, sometimes mixed with a verb that express actions.\n\nAy(‘)ehyubor -----> (Ayred is sleeping. Lit. Ayred bear cave. Ay = Ayred.  Ehyu = Bear. Bor = Cave)\n\t\nLet's put it in past and future tense. To do this there are slightly different grammar rules. The prefix Ia denotes past tense for the whole sentence, it's attached to the noun. The suffix of the same ‘Ia is also attached to the noun. Let's try it\n\nIa’Ayehyubor for past tense\n\nAy’ia(‘)ehyubor for future tense\n\nIn a normal sentence:\n\nIa’Ayred ehyubor\n\nAyred’ia ehyubor\n\n\n\nMarried Nouns\nAystra’isvin = Sin, heresy, crime against the holy\nKuurl’akur = pumpkin\nTrem’metr = Comb, brush\nSil’ikurn = Sword, war sword\nSil’madru = Sword, training sword\nOrohe’riko = Eternal victory\nIkurn’bu’im = Thanium\nMar’aea = Young mind\nLesorai’maer = Ancestral wisdom\nIkurn’mal = Battlements, fortress\nMaer’rivir = Council\nRivir’rivir = Army\nRivir'rivir’rivir = Army Group, coalition \nAethurr’regu = storm\nOm’feyu = duel \nOm’feyu’rii = duel to the death, or seperation\nMaer'taar = stubbornness. Goat\nvir’ivae = national glory\nTu’belier = The Fennic system of hospitality, my house is your house.\nSil’seleryu = Flamberge type great sword.\nLeru’tu = Library \nKhel’mali = An elf that wanders, an unfamiliar elf.\nBair’\n\nMarried Verbs\nTr’ae = to cause confusion\nAethurr’dur = to breathe\nNeh’fānri = to nod no\nTi’fānri = to nod yes\nTi-neh= Yeah Nah\nTiaoru’aethurr = To sigh in sadness\nEhyu’bor = To sleep\nTr’maer’rivir = to take council \nRelisu’doer = to choose from a set of options\nMaer'doer = to select wisdom\nDoer’maer = to choose with wisdom\nAdur’pyorai = to desire to a be a prince\nTiarou’tultul = to spend a small amount\nMarlae’kanel = to greet, to invite inside\nAū’rii = to demand \nIvae’vhai = to moving to protect something\nYala’adar = to stand up \nTr’surra = To see\nTr’odr = To change\nVhai’idar = to raise, to bring up for defense\nAdverbs\nUel = quickly, specifically relating to moving.\nMarsyl’ahe = Retired\n\nAdjectives\nWal’aylu = Bored\nMarsyl’ahe = Retired\nPronouns\n\nI/me = Kai\n\nMine/my = Aukai\n\nYou = Nay\n\nYours = Aunay\n\nHim/her/it/they = Hae\n\nHis/hers/its/theirs = auhae\n\nWe/Us = Yir\t\n\nOur/ours = auyir\n\nIt, that, this (Nonliving, items) = Riir\n\nGreetings\nWyrvun il’aylu (Wyrvun is good)\n\nKarnaylu (Good light)\n\nKeraylu (Good dark)\n\n\n\nFarewells\n\nVhaiaylu (Good travels)\n\nNay’ia Feylir’yie sanir = Throw yourself off a cliff\n\nWyrvun il’aylu (Wyrvun is good)\n\n\nCommon sayings\n\nVhalu (Thanks, you're welcome)\n\nau’Wyrvun Sural’bair (A humble servant of Wyrvun, Wyrvun’s humble servant)\n\nLun (Sorry)\n\nKai Lun (Forgive me)\n\nKuruae’biayu (Children, lit. Groin goblins)\n\nAu’ilru (child, lit. My creation)\n\nNay ahtho tr’nuryu (Nice to meet you)\n\nIa’nay Adrutael (Name) (have you seen (the) _____)\n\nKai’ia Eerulu (item) (Give me the _____)\n\nFol’adur! (At least try)\n\nNeh voln (Generally used to express displeasure, bad luck. Just a way of saying ‘no dice’ or ‘no sense!’)\n\nKeraylu (Good night)\n\nKarnaylu (Good day)\n\nFenn tr’adar ( A coincidence)\n\nKace’ai (Expression of exhaustion, bewilderment ‘ugh’.)\n\nFamily structure\n\nLaer’lar, wife.\n\nLaer'mar, husband.\n\nMalerru, parents, aunts, uncles.\n\nLesorai, grandparents.\n\nAunn, siblings or cousin.\n\nAur, children of your siblings or cousin, or their grandchildren.\n\nAu’ilru, your children, and grandchildren.\n\n\n\n\nCounting:\n\nFennic counting is split into two categories, those who use a more traditional method in a twelve base system, and those who use a ten base system.\n\nThe twelve base system counts the finger bones in one finger, using the thumb. Then counts orders of twelve, on the opposite hand, starting from the thumb to the pinky. 12, 24, 36, 48, 60. With each individual number up to 60 having it's own unique word. From there it is counted as “60 and 20. Alternatively one could say “Ten 60s.”\n\nThis system was once the basis for all counting, in reality, common (that is English) holds a 24 hour day, split into 12 hour sections as a result of this system. This system of counting, now extinct and forgotten also is the reason that the “teens” in spoken common being only after twelve.\n\nThe old system, though known of, is extinct and only exists as flavor lore.\n\nThe more popular system is the common system, that is the ten base. 10, 20, 30, etc are considered round numbers. However this system does remain influenced by the older style of counting; each word up to 99 in the modern system owns its own unique word, with no specific pattern. However unlike the old system, it has a written equal, and is organized into groups of two numbers. The resulting effect is numbers that in common would be written as thus: 100,000,000; would instead be written as 1,00,00,00,00. Each pair of two letters has an associated suffix.\n\nIn common, spoken: “One hundred million”\n\nIn Fennic, spoken: “Om’karr” as an example,  “Om’karr, nil’elam, nil’ilk, nil’firr, nil.”\n1,             00,         00,    00,      00.\n\nNul = 0\nOm = 1\nIr = 2\nOee = 3\nPal = 4\nFei = 5\nFal = 6\nGar = 7\nNesh = 8\nKai = 9\nUrm = 10\nTue = 11\nJo = 12\nJai = 13\nTurm = 14\nJaer = 15 \nCai = 16\nPon = 17\nTun = 18\nUna= 19\nUrru = 20\nHab = 21\nFir = 22\nGuy = 23\nPasu = 24\nBarta = 25\nPerdi = 26\nCurn = 27\nKue = 28\nHaer = 29\nMarsyl = 30\nTeru = 31\nVie = 32\nSho = 33\nAer = 34\nUeal = 35\nMarl = 36\nParen = 37\nAylr = 38\nLayl = 39\nAseru = 40\nCho = 41\nJuol = 42\nRela = 43\nCres = 44\nSoue = 45\nUler = 46\nCol = 47\nCaar = 48\nIthar = 49\nPel = 50\nChalm = 51\nWyr = 52\nTha = 53\nVilue = 54\nDal = 55\nFarel = 56\nHalei = 57\nTheer = 58\nSot = 59\nSlar = 60\nBela = 61\nSelar = 62\nCalar = 63\nTes = 64\nGaca = 65\nFael = 66\nPorel = 67\nOer = 68\nChol = 69\nWir = 70\nSilaan = 71\nCero = 72\nSeir = 73\nVil = 74\nJela = 75\nJilaa = 76\nDaram = 77\nHerarr = 78\nItarr = 79\nIra = 80\nKeva = 81\nDoltr = 82\nCir = 83\nSio = 84\nLelar = 85\nNouln = 86\nAela = 87\nYoel = 88\nUil = 89\nRer = 90\nTerru = 91\nGarla = 92\nSamp= 93\nNaral = 94\nUiral = 95\nVersi = 96\nJal = 97\nKio = 98\nCep = 99\n\n‘firr = --,00\n‘ilk = --,00,00\n‘elam = --,00,00,00\n‘karr = --,00,00,00,00\n\nThese are common denominations, I reason no further is needed but more can be added upon your request.\nInsults:\n\nAgeaiul = maggot\n\nKai’ia soryu’sorae ageia nay. = I'm going to slowly crush you like a bug.\n\nSewahe = Someone who appears pleasant, but is not. Lit. Bitter stew\n\nGohalir = An idiot, one who acts without thinking. (Lit. One who tries to steal the void)not \n\nSilfol = The equal to saying “Not the sharpest tool in the shed” (Lit. Dull sword)\n\nVuru’su = Unreliable, dead weight. (Lit. Cut knot)\n\n\n\nBlessings\n\nTarnay = Don't die\n\nAurii = Stay safe (More affection version of Tarnay)\n\nWyrvunaylu, Yir’ivae, Nayau anorr’ivae, Yirau celu’ivae, Nay ivae’yir. Yirau haelr’maer Malen. = Wyrvun is great, protect us, protect your land, protect our city, (it is) you we honor. Speak wisdom to our leaders.\n\nNay suek = You are kind/sweet. (Lit. You are sugar)\n\nNay soryu karu = Age slowly, or age gracefully.\n\n\nPrefix/Suffix\n‘rii = Suffix meaning extreme, lit. Very\n‘tir = Suffix meaning child of. An example of citing heritage = “Onve’tir Lyceia. Lyecia’tir Ayred. Ayred'tir Tulu. Tulu’tir Emaelia. Emaelia’tir Nessa. Nessa'tir Celennor Drakon.”\n‘ia’ = prefix or suffix denoting future or past tense.\n\nau’ = prefix denoting property of the noun. Can only be used in present tense. Attached to the object if not present tense with the same rules as ‘ia’.\n\ntr’ = A prefix added to any noun that makes it an verb, literally ‘action’ or ‘to’\n\n‘len = suffix denoting pluralization.\n\n\nWords\n\n\n\n\n\n\nAal = Now\nAdar = down, backwards\nAdur = To desire, to want, consent.\nAea = Growth/Grow\nAehlir = Discipline, obey, selfless\nAel= soul\nAelar = Diamond\nAelir = Skill\nAelnar = Sea breeze\nAelro = Loud\nAeltyr = Shock, surprise.\nAelur = Beer\nAengal = Aengul\nAeru = Otter\nAesir = Challenge, difficult, test\nAethuur = Air\nAga = Neck\nAgeai = Bug\nAhcu = Boat\nAhe = Bitter/poison/expired\nAhtho = Nice, wonderful.\naillerun = Loved one (an affectionate term for family) ? -pintape\nAilyu = Love, eros\nAkal = Gold\nAkaln = Bribe, corruption (sinful gold)\nAkur = Red, orange\nAlersu = Ancient, old, aged\nAli = Tax, fee, fine\nAlir = Steal\nAllirm = Hilt of a sword\nAlthar = Sickness, affliction,\nAmo = Wood, tree\nAneri = Hope, a reason to hope\nAnim = Mechanical\nAnorr = Land/ land of\nAnur = Path, road\nArchon = Family leader\nArja = work\nAsral = Promise, sworn\nAther = Knee\nAudr = Hunt/Gather/Collect\nAulra = Plough\nAun = Life\nAunn = Any blood sibling, brother, sister or any cousin younger, or the same age\nAur = Child of your cousin, siblings children.\nAurha = Survive, keep life\nAurkr = To need\nAuylu = Submissive / Lit. Coward\nAu’ = owns, property, of\nAyirr = Distance\nAylu = A lot / Big. Good\nAyras = Shadow\nAystra = Evil/Criminal\nAzradrai = Dragon, Azdrazi\nBaern = Clay\nBair = Quiet\nBalara = name\nBalarso = Pantry, food storage.\nBarbu = Coal \nBarsar = Thunder, crack, the fire of a cannon.\nBelier = showing, to display\nBelin = Follow, track,\nBerias = nearby, short travel\nBerir = Crawl\nBiayu = Groin\nBluyu = Flower, beauty.\nBor = Cave\nBurim = Cold\nBurr = Bow\nCaarie = Injury\nCaesu = Pleasant Sound / Lit. Laughter . . An equal to “Aha!”\nCaruur = Cloth from a plant, cotton.\nCearar = Vegetable\nCei = Star\nCelaen = One who kicks\nCelu = City / Place of settlement\nCerferux = Cross (As in crucifix)\nCetru = Copper\nChiraeu = wing\nCoflae = Coffee\nCur = A cup\nCurru = Strong\nDaemir = Daemon\nDaemon = Daemon\nDalu = Whole of the body\nDar = Arm\nDeon = Age\nDorotar = Physical purity\nDoso = Hen / Fear.\nDra = Measured wrath, focused anger.\nDraam = True, truth\nDrae = “. . . What?” Lit. Confusion\nDraemae = Blanket\nDrakkirr = Dragons, the Draconic\nDraley = Wet wood\nDranekir = Wyverns\nDrimar= Guide, to be a person of instruction in charge.\nDrui = Druid\nDurae = Shield\nEal = Any vehicle.\nEerulu = Give\nEhyu = Bear\nEilae = Emerald\nEirr = Log\nElkar = Monsters, horrific constructs,\nEloir = Persistence \nEmae = choose, elect.\nEmel= Joke, jest, humor\nEsalar = Back (Physical back)\nEsaran = To be rejuvenated, refreshed.\nEslar = Frost\nEsti = trust\nEthar = Immobility, stiffness, paralized\nEurrue = Mirror, reflection, twin.\nEveran = A humble shadow\nFae/Fay = The Fay, mischief, mischievous\nFaenir = Foreshadowing a critical event, calm before the storm, prophesy \nFalei = Alchemy\nFel = Love, philia.\nFelar = To eat, to drink\nFemer = Listen, hear.\nFenn =  Snow\nFeslar = Moderate frostbite, injuries of exposure, stage 2\nFeteal = Achieved purity, fennic purity\nFetir = Solid ice\nFeylir = Mountain\nFeyu = Fight, fighting.\nFol = Dull / Purposeless / Meaningless\nFsh = Fish\nFānri = Head\nGayu = Cow.\nGelaru = Traditional tent, yurt\nGoha = Create from nothing, the void.\nHaelr = Speech, talking\nHarsel = Rabbit\nHeliu = Sun\nHelwhyr = Stamina \nHerreu = after\nHevu = Rooster / Suicidal Bravery / Dark Elf\nHeyan = A request for clarification. Roughly“Say again”\nHilae = Custodian, keeper, one who holds\nIa = Denoting present or past tense.\nIadr = Forward, up\nIakir = Barrel for storage\nIalar = Sign, physical sign post.\nIar = All foodwards\nIbaar = White\nIbaarakii = Light blue\nIbheir - wind\nIblanu = Unhonorable\nIblu = Corruption / Adversary / Literally Iblees\nIgne = Fire / Warm\nIkael = Animal\nIkar = Strike, hit, can also mean to forge.\nIkurn = Iron/warfare\nIl = Left\nIlas = Dead\nIle = Compare, can be used as ‘what’ in a circumstance of ‘what spite.’ A word denoting comparison.\nIlitar = Equipment.\nIllar = Sharp, able to cut\nIlliar = Pick up the can\nIlo = Bone \nIlru = Create, raise\nIlsar = Be free, release\nIlse = complete, fullness\nIlthae = Precise, accurate, exact.\nIlu = North\nIlyar = Device, tool, item (Ex. Time’device = clock)\nIndar = Study, profession\nIrulil = Meat\nIskar = Heavy frostbite, stage 3, \nIslir = Very light frostbite, numb finger, stage 1 or pre stage 1\nIsol = Impossible, physically incapable, absurd.\nIsvilcil = Martyr\nIsvin = Mali’fenn afterlife / Holy\nIta = Feather, dexterous\nIvae = Protect, honor.\nIvdilin = Companion\nJaeia = Chair\nJalir = ash\nJara = Arrow, bolt.\nJauii = Body of a blade\nJiusae = Savior\nJothae = Cross (As in crossing a river)\nJuriao = Chest, stomach, torso\nKace = Sound / Unpleasant noise\nKael = Curved\nKaesa = requirement, need, cost \nKahalar = Choke, to be strangled\nKai = I\nKalar = Ability\nKalfir = Shin\nKali = Debt\nKalina = A fresh blanket of snow after a blizard\nKalsa = To guard, a sentry.\nKanel = Inside, within, contain, sometimes upon\nKanelu = Rope\nKanir = In front\nKarn = Light, day\nKarthel = Northern Traveler, Tundra Wanderer\nKaru = Age\nKarusu = Canyon\nKas = East\nKau = Forget, dismiss. / Go away\nKelai = Unstoppable force, thundersnow\nKelar = Weakness, failure\nKelesu = Rabid, foaming at the mouth.\nKeisa = To build knowledge, to discover new things, to study.\nKel’ = Prefix meaning ‘in comparison to’ denoting it as less preferable\nKer = Dark, night\nKetchrr = Kitchen\nKeyrur = Any alcoholic drink, lit. alcohol\nKhel = Wander, lost\nKhifil = Plan, goal\nKhola = Ghoul, unthinking undead\nKilthae = Death by exposure to cold, death that results from frostbite.\nKi’iu = ball, sphere\nKlao = Backthink\nKlar = Simple, easy\nKur = Black\nKuril = Person\nKuruae = Goblin / Small, annoying person\nKurue = Ink\nKuurl = Melon\nLaer = Agree, equal to, equal\nLalei = Frame\nLar = Woman\nLarehbaern = Brick, fired clay (rock clay)\nLeras = Bastard\nLeri = Paper, letter\nLeribu = Anvil, unyielding, unbending\nLerseu = Leather\nLeru = Book\nLeyu = Lion / leader\nLiaesar = Lapis\nLiirn = Yellow\nLin = Music / Song\nLisuu = pray\nLler= Friend, something or someone you enjoy\nLoreiir = Spiritual purity\nLun = Sorry, mercy\nMadru = Iron/civilian/forge iron\nMaer = Head / wisdom / lit. Thinking\nMaesae = History\nMagi =  Magic\nMal = Wall, male.\nMalen = Boss, ruler, manager\nMalerru= Father, mother, aunts and uncles\nMalīn = Malin\nMaparonnarn = The Fennic system of speaking, the Fennic alphabet.\nMar = Man\nMarl = Hammer\nMarlae = Bring together, mix.\nMarna = Wealth, something of immense value\nMarsyl = Enlistment, service, expectation, purpose\nMasei = Autonomy, accountability to the self.\nMeir = Why\nMetil = Time, moon\nMetir = Bird / Mystery\nMetr = Unit, sometimes stick\nMeylii = Javelin\nMeylr = spear\nMina = Circle, mina\nMir = And\nMiral = Straight\nMiu = Paint\nMoorn = Pure, innocent\nMori = Unredeemable evil / highest evil\nMorolu = Love, agape, respect.\nMurr = Pike, stack\nNaeru = Field, farmable land, farm\nNales = Pancake\nNarmi = Door\nNedia = Illnesses, to be ill.\nNeh = No\nNelar = Perfect, flawless, without issue\nNesu = Axe\nNilu = Knowledge / Understanding\nNirka = Behind\nNuryu = Any gathering or meeting\nOdu = Change, modify.\nOela = Issue, problem, \nOelm = Branch\nOelra = Sky, weather\nOetah = Long\nOler = Slushy ice, broken up ice.\nOlie = Pinch\nOltha = South\nOnarsir = Daemonsteel\nOraeu = street, walkway.\nOrohe = Success, victory, glory\nOurier = Water\nOurierstiyr = Beaver\nPaay = Cut\nPalor = Method, type\nPanvu = Suffering, emotional pain\nPas = All types of bread\nPelri = Cat\nPelu = Slave, enslaved\nPer = Horse\nPeru = Leg\nPetu = Sour\nPiralfal = Within courtship, the one who inspects possible suitors.\nPoralu = Rooted vegetable\nPotu = Obvious, transparent / Glass. Easy.\nPyorai = Prince\nRael = Love, self\nRaeli = Medic, herb, healer\nRakii = Blue\nRal= Opposite\nRalar = A box for storage\nRas = Curious\nRegu = Anger.\nRelisu = Outcome, amount\nRi = Right\nRianir = Hole\nRiko = Unending, eternal\nRivir = Squadron, group.\nRolur = Ideas, concepts,\nRoru = Round\nRurl = Question, do not understand, problem\nRuvel = Blood red, ruby.\nSae = Increase, grow, spread\nSaele = Budding flower\nSai = Height\nSail = Speak, to make a noise.\nSanir = Throw\nSar = Season\nSareu = Polearm\nSarr = Final, last\nSayn = Cut\nSelar = Spirits, alcohol\nSeleryu = Snake\nSelu = Child, small one, not related\nSeras = Turn, to face\nSeurr = Skin\nSew = Soup, stew\nShrer = Tongue\nSiedam = Begin to fight, battle is joined, I'm ready to fight\nSiest = trust, can also mean foundation.\nSil = Sword\nSkyth = Scythe\nSoce = Fruit\nSoli = Alone, isolated / Lit. Ghost / Unseen / Stealth\nSorae = Kill\nSoryr = Representative\nSoryu = Sloth, slow, slowly\nStae = Polearm, glaive.\nStaelurr = Lead, to be in charge\nStau = Nuts, almonds, etc\nStiyr = pause, stop.\nSuek = Sweet, palatable / Pleasant / Lit. Sugar\nSurae = Sentinel, Commander\nSural = Servant\nSurluae = Law, order, structure\nSuro = Clothing.\nSurra = Sight, eye\nSuru = Torture, prison (Sail’suru = politics)\nTa = as a result of, because.\nTaal = A young soldier, or greenhorn.\nTael = Touch\nTaerlu = payment\nTal = Stone/Cut stone.\nTalu = Pig.\nTar = Death, die\nTariu = Loose rocks, gravel to cobblestone.\nTarna = Stick\nTarr = Stupid, sheepish, foolish / Lit. sheep\nTas = West\nTayn = Blood / Family\nTayr = Green\nTel = Excess, extra\nTeleth = Gossip\nTersu = Leave, exit, go out\nTetra = Straight/Line\nThal = Air vapor seen while speaking in cold environments, mist, breath,\nThar = Raw, uncooked / Untrained / Unrefined / Trainee Lit. Ore\nThel = Without use / Blinding pride. / Mali’thill / Lit. Silver\nThuia= Non edible plant\nThuso = Pain, harm, damage.\nTi = Yes\nTiaoru = Sad. / A small amount / Small /\nTirrar = Attack\nTon = Cloth (cotton)\nTor = Foot\nTraelr = Large stick, sometimes staff. / Shaftcook\nTrath = Numbers\nTrem = Hair, wool.\nTu  = Home, house\nTultul = Trade, exchange. Can also mean price\nTus = unfarmable land\nTusilru = Waste, excrements (unusable creation)\nTuyr = garlic\nUel = Fast, speed\nUelam = The feeling of nausea\nUelar = Wine\nUelear = burn\nUelei = Moon / Platonic love\nUelie = Pressure point\nUeliir = To allow something to happen\nUelthir = Heir, successor, elected\nUilm = Edge of a blade\nUl = Rot, decay. / Bad Smell\nUram = Empty.\n Urel = Emotion, feeling\nUrisa= Remember, recall, memory\nUrk = nonsense/crazy, babble, Orc\nUrsalir = Middle/Center\nUval = Powder\nVaeli = Berry\nVala = Childish, silly, Human\nValaera = Cooked, prepared food\nVali = Liquid.\nVearu = Tooth\nVelryae = Cry, tears, mourning\nVeltha = Love, stroge, love for a family member.\nVespera = A guiding star\nVesya = Peace, quietude\nVeyi = Armor (Veyi’fanri = helmet) Lit. Sarcophagus\nVhai = Travel/move, lets go\nVier = Hand / Grab\nVir = People, nation\nVirras = Vigilant, religious concept, can also mean priest or paragon.\nVolit = Unstable, volatile / Volatile / Lit. Explosive /\nVoln = Cunning, crafty / Fox\nVon = Happiness / Satisfaction / Happy\nVor = Open, clear.\nVuru = Knot, tied.\nWael = Heal, repair.\nWal = Wait, do nothing, standby\nWen = Grass / Annoying / Wood Elf\nWeyu = Egg\nWihlae = Lie\nWihn = Grain, wheat\nWurru = Dry wood\nWy = appendage, see ancient elven\nWyrvun = Mali’fenn diety\nYaal = Stand, see verbs.\nYie = Edge, end of. I\nYoeir = Wrist \nYuilae = Fuller of a blade\n ‘Lalm = suffix, meaning to wear\nIlen = above\nTelar = important\nAsle = Large,\nKeli ",
    'maparonnarn_wiki_snapshot.txt': "## Seed words\nacal: valuable, golden, cursed\nadil: needy, desiring, wanton\nadont: requesting, awaiting\nadri: evil, immoral, hate\naelor: abomination, faithless, demon\naengul: Aengul, race of semi-divine beings affiliated with light\naetah: age\naeth: aether\naher: to bless\nakal: valuable, golden\nallim: sin\nana: to be\nandria: hope\nanny: dance\nasul: sun\nata: ugly, tainted\nathri: serpent, snake\nailer: wizard, conjurer, heretic\nalor: salt\name: forest\nannil: guiding\nante: last\narche: infrequent, sporadic, rare\narhil: just, fair\nasimulum: sanctuary, glade, asylum\naver: to wander, to roam\navento: to follow\nayal: yellow\nayil: to like (a person or thing)\nayl: to like (a thing)\nayla: good\nbanih: six\nbarbu: dark, black, hedgehog\nberr: bow\nbelou: pink\nbida: to drink\nbilok: to create, to make\nbortu: dwarf\ncaele: sky\ncelia: star\nceru: strong, mighty\nchae: tea\nchirr: wolf\nchil: descend\nchul: to must\ncihi: city\ncinh: to stop, to cease\nciw: to sleep\ncrua: hurting, suffering\ndaemon: Daemon, race of semi-divines affiliated with smoke and fire\ndagr: war\ndant: to fall, to drop\ndiraar: guard, sentinel\ndion: long\ndrui: druid\ndraoi: evil druid, warlock, sorcerer\nehier: to find\nenaer: guest\nento: next\nern: to can, to be able to\nestel: trust\nesun: eight\neth: end, to end, to die\nevar: to protect, preserve\ney: use, application\nfaesu: horse\nfer: tool\nfenn: ice\nfeta: cold\nfih: to eat, to feed\nfin: region\nfiyem: reborn, renewed, revitalized\nfyu: full\nha: it\nhae: her\nhael: three\nhaelun: mother\nhaesiea: to forget\nhaler: to promise, to pledge\nharriel: square\nheial: circle, council\nhier: near\nhileia: peace\nhiuw: to twitch, to move\nhiyl: health\nibar: white, owl\nigne: flame, fire\nirham: industry\niheiuh: wind\nihn: stick\nikur: wrought, cold, gray\nikru: foolish\niller: to give, to grant\nilum: glowing\ninder: to read, study, memorize\nindor: book\nirrin: glass\nito: to, here, within\niyat: thought\niylanh: to place\nkae: me\nkalem: Malin's year\nkaliri: event, party\nkarim: fortday\nkarin: sunrise, day\nkath: feud\nker: dark, sunset, night\nkhel: darkness\nkina: murdered, killed, death\nkrafeh: corpse\nkrey: single\nkulin: five\nlae: him\nlaier: seven\nlar: sturdy, steadfast\nlari: female\nlareh: boulder, mountain, rock\nlarebil: anvil\nlarueth: netherrack\nlaureh: chosen, favored, noble\nlaurir: noble\nlen: song\nlenaern: inn\nlenniel: melody\nlent: to grow\nlenti: growth, moss\nlentos: brown\nleyu: graceful, beautiful\nliewyn: smile\nlle: kindness, good intention\nlie: dishonest, untrue, false, deceitful\nllir: friend\nlin: home, place\nllum: sorrowful, mourning\nllun: sorry\nllyt: aggressive, intimidating\nlom: to fragment, to splinter\nlomi: fragment, splinter, pebble\nlomal: flint\nluci: grape\nlu: prison, cage, bind, dungeon, restriction\nluth: enchant, spell\nlye: we\nlyu: silent\nmabidar: to suck\nmaehr: wisdom, knowledge\nmaelu: to know\nmagara: cave, cavern\nmahnih: wall\nmal: male\nmali: elf, elven\nmalin: Father of Elves, king\nmasuleh: anvil\nmedi: helping, helpful\nmetta: bird\nmeracahe: balance\nmiar: lava\nmira: warm\nmiruel: red\nmoiel: nine\nmordu: titan\nmya: mercy\nmyumier: to carry, to bring\nna: to\nnae: you\nnaeri: devout one, cleric\nnam: if\nnarn: to walk, travel through\nne: no\nnealu: to teach\nniut: two\nnor: land\no: why\noem: one\nohn: like (similar to)\noment: to meet\nokar: to safeguard\norrar: to hunt\nothelu: sharp\npario: to fail\nparir: harbinger\npern: potato\nparsaer: to conceive, to kindle\nperith: to remember\nprenu: take\npuer: to write, to draw, to scribble\npuerith: to write down, to record\nres: wayward, unpredictable, capricious\nrhil: vengeful, scorned\nriv: claw\nriurn: swamp\nraell: carrot, root, herb\nrost: rain\nsan: word, news\nsaneyr: to debate, discuss\nsalum: to feel, to sense\nseth: void\nsew: soup, stew\nsiimah: tower\nsil: sword\nsiol: lone, lonely\nsirame: honor\nsiru: mushroom\nsiyuer: to play\nsohae: devout one, cleric\nsuika: sugar\nsul: light\nsulier: to see\nsulii: eye\nsynal: power\ntaeleh: mind\ntaelu: to learn\ntahorran: hawk\ntahu: high\ntahn: peak, height\ntalar: horizon\ntaliyna: body, living being\ntaliiyher: to bleed\ntaliyu: secret\ntalonnii: family, bloodline\ntarem: Elven week\ntayna: life\ntaynei: green\ntaynuel: vitality, energetic, alive\ntelu: ten\ntenna: until\ntennallar: ocean\nterh: to grind, process, churn\ntillun: forgive\ntinuviel: nightingale\ntir'id: risk, danger\ntiuth: triangle\nthrur: explosive, volatile\nthill: pure, refined, delicate\nthul: raw, unrefined, brusque\nti: yes\ntilr: submission, servitude\ntir: law\ntos: desert, wasteland, barren ground\ntufer: to construct, to prop\ntur: bone\nturr: sheep\ntuva: everything, all\ntuveh: wool, something soft\nueth: nether\nuhier: to seek\nulln: rot, withering\nunya: then\nuradh: to scowl\nuriar: to shout\nurth: to rule\nuruk: orc\nut: because\nuvul: powder\nvaedrar: to melt\nvailu: four\nvalah: human\nvallei: water\nvalein: milk\nvallel: blue\nvallum: crying, grieving\nvalm: art\nvalmuel: purple\nvan: to go, to fare\nvelulaei: moon\nvihai: whisper\nvilut: cow\nvira: vigilant, mournful\nvularale: bat\nvull: to deceive, to trick\nwaleh: to heal\nwehn: grass, grain\nwelier: to listen, to hear\nwy: appendage\nwyl: while\nwyn: happy\ny: upon\nyallr: to live\nyuln: gemstone\n## Compound words\nacalin: shop\nacaln: gold\nadont'ahern: please\nael'tireth: misjudgement\nael'tirether: to misjudge\naetahu: aged, old\nahavento: to worship\nahavento'lin: temple, church, shrine\naheral'leh: highelven\nahern: blessing\nahernan: thank you\nakaleh: wealth, money, valuables\nakaleh'ii: worth\nakaln: gold\nalliman: sinful\nallimar: to sin\nallimir: sinner\nalor'bidan: brine\naloronn: salmon, fish\naloru: salty, saline\name'leh: woodelven\name'lie: orchard, food forest\name'nor: woodland\namenor: wilderness\name'sae: forestry\namesair: forester\namonn: wood\nanah'wy: head\nanaln: the past\nanalnu: past, previous\naneh'wy: right hand\nanih'wy: left hand\nanoh'wy: foot\nanoh'wyan: feet\nanuh'wy: hand\nanuh'wyan: hands\nanniler: to guide, direct\nannyer: to dance\nasulu: sunny, sunlit\navern: wanderer, confused person\nayilu: liked, likable\nayler: to improve, to make better\nbeloun: pig\nberrir: archer\nbida'lin: tavern\nbidan: drink, beverage, liquid\nbilokonn: to fornicate\nbilok'sair: craftsman\nbortuler: to mine, to delve\nbortu'lin: mineshaft\nceruer: to strengthen, to fortify\nceru'lin: stronghold, fort\ncerun: strength\nchiler: to descend\nchil'onn: descendant\nchirr'ii: puppy, cub, whelp\nchirr'lin: den, lair\nciwn: sleep\nciwu: sleepy\ndagre: to fight\ndagre'sae: fighting, war\ndionn: length\ndioner: to lengthen\ndionne: short\ndionner: to shorten\ndionsil: longsword\ndionnesil: shortsword\ndiv'andria: hopeless\ndiv'ciwn: sleepless\ndiv'eth: endless\ndiv'ey: useless\ndiv'lin: homeless\ndiv'sanern: speechless\ndiv'sirame: honourless\ndiv'tayna: lifeless, dead\ndiv'tir: lawless\ndiv'tur: boneless, spineless\ndivu: empty\ndivun: emptiness\nelanah: north\nelanoh: south\nelanih: east\nelaneh: west\nel'santalian: the alphabet\nestelle: to trust\nesun'wy: octopus\nevarir: protector\nevaru: protected, preserved\neyr: to use, to apply\neyrir: user\nfaesu'lin: stable\nfenn'leh: snowelven\nfennu: icy\nfer'ame: axe\nfer'bilok: hammer\nfer'nor: shovel\nfer'norsae: hoe\nfer'puer: quill, pen\nfer'sul: torch\nfer'thuln: pickaxe\nfin'urthir: duke\nfisaen: seed\nhalern: promise, pledge, oath\nhaeluner: to mother, to care for\nhaelunor: motherland\nhaelunu: motherly\nheialu: round\nheialyem: to return, to circle back\nhiuwu: twitchy\nhiyl'lin: clinic, hospital\nhiylne: sickness\nhiylneu: sickly\nhiyl'sair: medic, doctor\nhiylu: healthy, spirited\nhiylun: healthiness\nigne'ame: firewood, fuel\nigner: to burn\nignerir: burner\nignern: a burn, a brand\nigne'sae: destruction, war\nigneu: firey\niheiuhii: voice, breath\niheiuh'tehrlin: windmill\niheiuhu: windy\nihnsil: spear, lance\nihnsilir: spearman, lancer\niinu: young\nikurn: iron\nil'celian: constellation, starsign\nilumr: to glow\nindor'lin: library\ninder'lin: school, college, university\nirham'lin: workshop\nitone: you're welcome\niyath: to think\niyat'sae: philosophy\niyatsair: philosopher\niyl'karin: today\nkather: to feud\nkathir: foe\nkarin'ante: yesterday\nkarin'ento: tomorrow\nker'leh: darkelven\nkrafeh'lin: grave, tomb\nkrafeh'nor: graveyard, cemetary\nkreyn: pair\nlarehu: rocky, mountainous\nlarehne: valley\nlari'maronn: female cousin\nlari'onn: sister\nlenir: singer, musician\nlentiu: mossy\nlensair: bard, minstrel, troubadour\nliear: to lie\nlien: lie\nliewynh: to smile\nliewyn'saer: to entertain, to amuse\nlinan'sae: town\nlin'urthir: baron\nlliran: friends\nlliru: friendly\nllirer: to befriend\nllum'saer: to sadden\nllyth: to strike\nluan: prisons, cages, dungeons\nlucionn: sour\nlucionn'bidan: vinegar\nluci'sair: vintner, winemaker\nluci'tehral: wine\nluer: to imprison, to cage, to bind\nluerir: captor\nluerlent: flowerpot\nluir: prisoner, captive\nluir'sair: serf, slave, thrall\nluther: to enchant\nluthien: enchanting\nluthu: enchanted\nlye'leh: public\nlyeleh'lin: republic\nlye'synal: democracy\nlye'synalir: democrat\nlye'urthir: demagogue\nlyuer: to silence\nlyun: silence\nlyu'saer: to censor\nmaceru: almighty\nmadion: longer\nmadionne: shorter\nmaetahu: older, parent\nmalaurir: prince\nmaleyuln: diamond\nmali'aheral: high elf\nmali'ame: wood elf\nmaliear: to betray\nmalieir: traitor\nmaliewynh: to laugh\nmali'fenn: snow elf\nmali'ker: dark elf\nmalii'lari: daughter\nmalii'larionn: niece\nmalii'mal: son\nmalii'malonn: nephew\nmal'maronn: male cousin\nmaln: father\nmalner: to father\nmal'onn: brother\nmarayla: perfect\nmaraylan: perfection\nmaraylanir: paragon\nmarayler: to perfect\nmar'haelun: grandmother\nmarlari'onn: aunt\nmarmadion: longest\nmarmadionne: shortest\nmarmaetahu: oldest\nmar'maln: grandfather\nmarmal'onn: uncle\nmarn: more\nmarenne: less\nmarurthir: tyrant\nmasair: master\nmasilir: knight\nmasuleh'sair: blacksmith, smith\nmarmatelu: thousand\nmatelu: hundred\nmataliame: log\nmayl: love\nmayler: to love\nmayil: love (for a person)\nmaylu: beloved, loved\nmayilun: beloved, loved one\nmawyn: bliss\nmawynu: blissfully\nmetta'lin: aviary, birdhouse\nmiar'sae: griefing, harming, spiting\nmirueler: to redden, to blush\nmyumierir: carrier, container\nnaeluir: teacher\nnaelun: teaching, lesson\nnalin: homeward\nnarn'acaele: fly\nnarneth: destination, goal\nnarn'faesu: horsetravel\nnarn'tennallar: sail\nnarn'vallei: swim\nnen: without, lacking\nnen'lu: free, without restriction\nnen'luan: limitless\nnen'lun: freedom, liberty\nnenlu'norsair: freeholder, freeman, tenant\nne'sirame: dishonour\nne'sirameu: dishonourable\nnor'sae: farming\nnor'saer: to farm\nnorsae'lin: farmstead\nnorsae'nor: farmland\nnor'sair: farmer\nnor'puerith: geography\nnorurth: realm, country\nnorturth'lye: countrymen\nokarn: oasis\nonner: to birth, to give birth\nonnerir: parent\norrarir: hunter\norrarn: hunt\npar'karinah: dawn\npar'karinante: ereyesterday\npar'ker: dusk\npar'narneth: predestination\nraell'tehral: salve, potion\nraellu: herbal\nres'karinento: overmorrow\nresne: predictable, consistent\nresnen: prediction\nresner: to predict\nresvuleth: catastrophe\nreth: fate\nrhiln: vengeance, scorn\nriurnor: swampland\nrost'ame: rainforest\nrostu: rainy, wet, damp\nsanan'inder: dictionary\nsaner: to speak\nsanern: speech, language\nsaneyir: debater, public speaker, orator\nsan'tali: letter\nsan'talian: letters\nsair: worker, spreader\nsewer: to stew\nsewonn: hearty\nsilir: swordsman, swordfighter\nsilma: greatsword, broadsword\nsirameu: honourable\nsiruonn: bitter, umami\nsiyuerir: player, actor\nsiyuern: play, performance\nsohaer: ruler\nsuikaonn: sweet\nsulasul: sunlight\nsulcelia: starlight\nsul'irrin: glowstone\nsynalli: powerful\ntaeleher: to mind, to consider\ntaher: to ascend, to rise, to climb\ntahorranii: hawks\ntalareh: stone\ntaliame: tree\ntalivalah: halfling\ntaliuth: oppressor\ntal'uruk: goblin\ntayna'puerith: biography\ntehrir: miller\ntehr'lin: mill\ntennallarii: sea\nthruer: to explode\nthrurn: explosive, dynamite\nthilln: silver\nthulith: metal\nthuln: ore, raw material\ntilrer: to serve, to submit\ntilrir: servant\ntilru: servile, submissive\ntilru'chirr: dog\ntireth: doom, judgement\ntirether: to deem, to judge\ntirethir: doomsman, judge\ntiru: lawful, legal\ntirune: illegal\ntos'sae: razing, pillaging\ntosu: dry\nturu: boney, spindly\nturru: sheepish\ntuva'aenguln: pantheon\ntuva'lye: everyone\ntuvalye'hiylne: pandemic\ntuva'maln: All Father\nullr: rot, decay, wither\nullral: monster, undead\nuradir: naysayer\nuriarir: crier, shouter, announcer, herald\nuriarn: claim\nuriaru: loud\nurthir: ruler\nuvul'igne: ash\nuvul'thrurn: gunpowder\nuvul'wehn: flour\nvalein'tehral: cheese\nvallei'tehrlin: watermill\nvalmer: to paint, to sculpt, to do art\nvalmir: artist\nvihaier: to whisper\nvuln: fox\nwehn'bidan: ale, beer\nwehnor: grassland\nwehn'sae: baking\nwehn'sair: baker\nwehn'tehral: bread\nwelieryem: to repeat, to echo\nwynn: happiness\nwyn'resvuleth: eucatastrophe\n## Fiyem expansion\nacalicne: kindlefen\naela: bad\nahaces: glory\nailacaln: arcaurum\nakalenponn: tomato\nalmen: ship\nalmenor: haven, port\name'chaewa: king's ivy\name'felis: lynx\name'felisii: wildcat\namelarn: hazel\name'lucii: huckleberry\namorn: bush\nar'fetan: winter\nar'vell: autumn, fall\nar'lent: spring\nar'miran: summer\nathrihnan: serpent's stalk\nayal'cionn: lemon\nayuacatel: avocado\nazdrazi'masu: dracanium\nbarbu'lucii: blackberry\nbelou'akaln: rose gold\nberrorn: yew\nberu: bronze\nbilo: hare, rabbit\nbiloemer: to unite\nbilok'carn: beaver\nbilo'lin: warren\ncaelonn: nickel\ncaer: deer\ncaerleh: antler\ncaer'lucii: raspberry\ncantar: to sit\ncarn: rodent, rat\ncarnii: mouse\nchaewa: coffee\ncheru: oak\ncherularn: acorn\ncionn: citrus\nciver: to lay\nciwienti: night sap\ndaemon'masu: daemonsteel\ndioler: to reach\ndraelareh: dralachite\nelumer: to shine\neth'larum: border, edge\nethlarum'nor: borderland, march, frontier\nettonn: egg\nenti: flower\nentien: flowering, blooming, blossoming\nentiu: flowery\nfae: fae, fairy\nfaekhetsu: mule\nfaeser: to ride\nfae'siruan: faerie truffles\nfelis: cat\nfennuvul: athin\nferuer: feather\nfetalor: gelunite\nfisaen'lucii: strawberry\nfisaenponn: pomegranate\nhamat: dolphin\nheiluner: to embrace, to hug\nhesin: tundra\nhucarer: to stick\nhucaru: sticky\nigon: smoke\nigoner: to smoke\nihnorn: coppice\nilentor: to take\nillam: bismuth\nillam'beru: bismuth bronze\nillaruman: striped\nillaruman'felis: tiger\nillaruman'mecarn: chipmunk\nillener: to attune\nilln: zinc\nilsolynan: spotted, dotted, speckled\nilsolynan'felis: leopard\nilsolynan'felisii: cheetah\nilum'lucii: glowberry\niper: birch\niuver: to shake\nkaluca: chicken\nkastalarn: chestnut\nkeelareh: magnetus\nkerilum: nightglow\nker'lucii: black currant\nker'beru: black bronze\nketta: nightbird\nkhetsu: donkey\nkwak: raven\nlaer: to stand\nlaker: to offend\nlan: leaf\nlanu: leafy\nlarn: nut\nlarn'lenponn: quince\nlarum: stripe, line\nlem: hair\nlemu: hairy\nlenponn: apple, fruit\nlentilem: beardweed\nlentoslarn: walnut\nleran: goat\nlucii: berry\nluciorn: grapevine\nmalen: melon\nmali'lem: elf's hair vine\nmanileh: animals\nmasu: steel\nmecarn: squirrel\nmettaponn: cherry\nmirayal: orange (color)\nmirayal'tosorn: acacia\nmiriurn: mangrove\nmiruel'lucii: red currant\nmirun: copper\nmorma: bear\nmus: banana\nnarier: to run\nneanar: to hide, to disappear\nnemiis: spider\nnory: shore, coast, strand, beach\nokhel: beech\nokarn'larn: coconut\nokarn'orn: palm\nokarn'ponn: date\notheraell: blisterthorn\nparpilocer: to prepare\npar'vell: apricot\npeponn: pumpkin\npilocer: to work\npirost: pear\nponn: fruit\nren: road, way, path, street\nrhenponn: peach\nriurn'carn: muskrat\nriurn'lucii: cranberry\nrostame'felis: jaguar\nrostame'felisii: ocelot\nsaylar: to praise\nseliar: to look\nsimar: spruce\nsolyn: spot, dot, speck\nsorr: crow\nsuika'lucii: sweet berry\nsuika'orn: maple\nsuika'wehnonn: pastry\ntaehar: to raise, to lift\ntal'beru: brass\nthilln'ii: platinum\nthilln'tivern: pewter\nthrurlareh: volatite\nthrur'masu: boomsteel\ntivern: tin\ntosorn: desert tree or shrub, dead bush\ntualer: to cook\nuel: color\nvaed: lead\nvaeler: to stream, to flow\nvaeln: stream, brook, creek\nvaelnarn: bridge, crossing, ford\nvaelnarner: to cross, to ford\nvaelren: river\nvallel'lucii: blueberry\nvallier: willow\nvallon: fog\nvalmuellen: plum\nvanter: to come\nvekurth: hall\nvell: harvest, waning\nvelulareh: lunarite\nvuln'lucii: lingonberry\nwaelu: fame\nwehnonn: cake\nwelieyetta: parrot\nwyar: to stomp, to stamp\nyamar: to charge\nyeluer: to connect\n",
    'maparonnarn_dark_snapshot.csv': 'Vel\'luah,Meaning,Direct Common Translation,Uppercase Latin,Vel\'luah Script,Qalasheen Numeral / Factor,Vel\'luah,Vel\'luah Script\r\nAhernyn,An informal ‘thanks’. Derived from ancient elven.,thanks,Mm,ɱ,0,sly,\r\nAlyetwon,No literal translation: a being that is evil or a person with evil intent; used where ‘dark spawn’ would be.,N/A,Zz,չ,1,az,\r\nBashkymyr,"Insult for a non-dark elf who pursues a dark elven mate, fixated on aesthetics over personality, ability or culture. Very shameful.",N/A,Tt,ȶ,2,nyt,\r\nBe’a-velulael,"Used in sunlight hours like ‘good day’, with less cheerful connotations.",without the moon,Uu,ʊ,3,hek,\r\nBolso,"Highly derogatory label for a Kharajyr, implying they are feral and cut off from their fallen empire and dead goddess; the proper term is ‘velubol’.",cat,Bb,ɮ,4,zag,\r\nEtamaehr,"An elf of at least half dark elf descent crossed with another subrace, not deemed worthy of ‘maehr’. Meant respectfully but can be controversial.",N/A,Gg,ɠ,5,kru,\r\nHaeuze,"A person with long uncut hair, often from piety; respectful to religious clans, but an insult implying fragility to martial bands.",N/A,Ee,ɛ,6,vho,\r\nHelun-Velulaeya hon laht,A blessing for others.,Mother-Moon guide you,Ll,ʅ,7,reu,\r\nHelun-Velulaeya tom uhv’lye honyr,A blessing for a personal group.,Mother-Moon be our guide.,Kk,ӄ,8,xyn,\r\nKaryn-ye,Reserved for the morning: a neutral greeting and an observation that dawn has come. Literally ‘little sun’.,little sun,Dd,ð,9,bex,\r\nKasyana,Title for the maehr considered the high venure of the nation at the time.,N/A,Yy,ψ,10,unz,\r\nKerayal,"An informal greeting, more intimate than ‘vraz’; derived from ancient elven ‘good evening’ but used at any time.",N/A,Rr,ᵲ,10s,-ah,\r\nKeren,"Best translated ‘Drow’: umbrella term for dark elves and mori’quessir, sometimes dark dwarves. Some use it over malyker to leave out the ‘elf’.",drow,Aa,α,100s,-ee,\r\nLabaley,"Derogatory: fusion of labek ‘white’ and leytura ‘rose’, for heartlander and highlander humans, especially zealous canonists.",N/A,Xx,ᛪ,1000s,-he,\r\nLebbaro,"Affectionate word for someone silly, playful or goofy; not an insult.",N/A,Vv,ʋ,"100,000s",-yhk,\r\nLo laht malar la?,A challenge.,will you fight me?,Hh,ɦ,"100,000,000s",-ux,\r\nLo laht malar lu la?,A call to arms.,will you fight with me?,Oo,¤,,,\r\nLye ukh,‘Let’s go [together]’. Literally ‘we go’.,we go,Nn,ռ,,,\r\nMaehr,"How many dark elves self-identify; a less literal label for ‘proper’ dark elves (all maehr are malyker, not all malyker are maehr). ‘maly’ elf and ‘ker’ dark are loaned from ancient elven.",N/A,Ss,ʂ,,,\r\nMal’baryl,Insult for a once-maehr who accepted a bashkymyr’s advances; strips the title of maehr.,N/A,,,,,\r\nNardo,"The current matriarch or sometimes patriarch of a Tribe, Clan or House.",chief,,,,,\r\nNumuda-hru,"Conservative expression of matriarchal values for a male maehr who strives beyond his station: boisterous, arrogant or free-spirited. Literally ‘unmanlike’.",unmanlike,,,,,\r\nOkerymaana (fem) | Ulathokeryma (masc),An exalted elder who was once High Priestess/Priest and advises the current one.,N/A,,,,,\r\nSka’at tul,‘come here’. ‘Ska’at’ alone means ‘come’.,come here,,,,,\r\nThet’uzhel kix,Refusal/dismissal of a challenge; also used to defuse one or to recognise peace. Literally ‘the tide sleeps’.,the tide sleeps,,,,,\r\nThrom-kah,Interpreted as ‘be well’ and ‘well met’; a greeting or farewell.,well met,,,,,\r\nUkh,"‘Go’, as a dismissal.",go,,,,,\r\nUkh bo bashuk,"A dismissal, ‘go in shame’. ‘Bashuk’ (honour, from mori’quessir) is a hurtful term.",go in shame,,,,,\r\nUkh lu velulael,"A fond farewell blessing, ‘go with the moon’.",go with the Moon,,,,,\r\nUrdaano,Title for the husband of the Primarch; an elevated ‘patriarch’.,N/A,,,,,\r\nUrve / Vule / Lyle,"Sir / Ma’am / gender-neutral form. A respectful address, not a knightly styling.",N/A,,,,,\r\nVanayal,A corruption of ancient elven ‘farewell’.,farewell,,,,,\r\nVelel,"‘Lunar’; a full moon cycle, used with numbers for months (OOC days), e.g. az-velel = one month.",lunar,,,,,\r\nVelelana,"‘High lunar’: seven moon cycles, used with numbers for years (OOC weeks), e.g. az-velelana = one year.",high lunar,,,,,\r\nVelulaeyael kee,"Issuing a formal challenge (duel, contest, dispute). Literally ‘the moon calls/pulls’.",the moon pull,,,,,\r\nVrax,"Ceremonious greeting for superiors, with a salute or bow; also a holy word from teachers to disciples.",N/A,,,,,\r\nVrax-maehr,"Formal greeting exclusive to dark elves, for respect or familial love; taboo for non-dark elves.",N/A,,,,,\r\nVraz,"An informal greeting, ‘hi’ or ‘hello’. Literally ‘good’.",good,,,,,\r\nVulyzaana,Title for the wife of the Primarch; an elevated ‘matriarch’.,N/A,,,,,\r\nXabyth-exan,"Sacred: the moon visible in daylight, ‘pale day’ (written with holy x’s, from zabyth + ezan); also days of religious observation.",N/A,,,,,\r\nXabyth-thet’uxh,"Sacred: the moon setting over the ocean, ‘pale tide’; seen as an omen or blessing (from zabyth + thet’uzh).",N/A,,,,,\r\nYnx labah mabas,A sincere thanks for significant gifts or favours. Literally ‘bless yourself after’.,bless yourself after,,,,,\r\nYo’ros,"Closest word to ‘please?’, but it means begging and is humiliating; very insulting to a maehr. Loaned from mori’quessir ‘joros’ (to ask).",N/A,,,,,\r\nYthael,"A tenacious warrior fighting for own passions and pragmatism; also mercenary, bandit, assassin when a dark elf. Neutral.",N/A,,,,,\r\nYthaen,"A righteous warrior pledged to an ideal; also city guard, paladin or templar when a dark elf. Neutral.",N/A,,,,,\r\nYyrel vex!,Accepting a challenge. Literally ‘the ocean pushes!’ / ‘the sea answers!’.,the ocean push,,,,,\r\nZkabra,"Very derogatory, ‘mud ear’: an elf or part-elf with no culture or who emulates heartlander or highlander cultures; like ‘mongrel’.",mud ear,,,,,\r\n',
    'maparonnarn_dark_grammar_snapshot.csv': '"Vel’luah\nVel’luah, sometimes called ‘Night Elven’, ‘Vulgar Drow’, ‘Greyspeak’ or ‘Moontongue’ is the modern language of the dark elves, derived from the race’s mother and holy tongues, Ancient Elven and Old Blah respectively, as well as sparse corruptions and loaned words from the vile verbiages of Mori’quessir and even - rarer still - sterilized mortal iterations of Al’tahrn-Durngo.\nVel’luah is no mere dialect of the aforementioned, however; as the official language of many clans and cultures across the broader dark elven diaspora (including those with no reverence for the Spirits nor historic subjugation at the hands of the mori’quessir), contemporary vel’luah speakers retain only a modicum of lexical similarity with the aforementioned. That is to say, as a distinct neo-elven language in its own right, the average Vel’luah speaker would not be conversationally understood by another that knew only Ancient Elven or Old Blah; nor would a monolinguistic Vel’luah speaker possess the ability to comprehend these without conscious efforts made to learn them from scratch."\r\n"Grammar:\n-Suffixes and prefixes immediately latch onto the word they correspond to. If a word already ends with the letter the suffix begins with, that letter is skipped. For example, ‘memnu’ meaning ‘to do’ and the ‘-ule’ suffix would combine as ‘memnule’ (‘doing’), as opposed to ‘memnuule’.\n-The predicate comes after the subject. (ex. \'was learned\', \'ran away\', \'ate them\')\n-Adjectives and adverbs are attached to the back of the word they describe with a hyphen\n-Plural is denoted by adding a –zh to the back of the noun\n-Articles attach themselves to the backs of nouns they affect, after any suffixes. For example, ‘the dark elves’ includes a noun [maehr] that is plural [zh] with ‘the’ as an article [el], so it translates to ‘maehrzhel’.\n-Past tense is denoted by adding an a\' to the front of the verb, before prefixes.\n-Future tense is denoted by adding an e\' to the front of the verb, before prefixes.\n-Present tense is defaulted to without either prefix.\n-Possession is denoted by prefixing uhv’ to a pronoun or noun. For instance yours or your is ‘uhv’laht’\n-To denote possession that belongs to someone else you will attach the suffix ‘uhn to the name of the thing or person who is possessing the object: Laevaelyn’s book becomes ‘Lavealyn’uhn olanu.’\n-Apostrophes are only grammatically relevant to the above tense and possession prefixes. All other uses merely denote a short pause in that word’s pronunciation.\n-Compound words are always hyphenated. There are no open or closed compounds. For example, the open compound word ‘full moon’ in this case combines the adjective [vyl] and the noun [velulaeya], so it translates to ‘vyl-velulaeya’."\r\n"Alphabet:\nUnlike the longer Common alphabet, Vel’luah only utilizes 19 letters consistently, and it also does not contain any diacritics. However inappropriate for Vel’luah words themselves, it is not unheard of for some dark elves to source additional letters from other tongues for their forenames and occasionally even family names. This remains controversial to some clans.\nVel’luah also utilizes its own script derived from Flexio, though many amongst the younger generations of dark elves tend to use it interchangeably with its Common alphabet equivalents.\nThere is no concept of uppercase nor lowercase in the Vel’luah script, though Flexio letters obey the same capitalisation rules as Common.\nɱ չ ȶ ʊ ɮ ɠ ɛ ʅ ӄ\nM Z T U B G E L K\nð ψ ᵲ α ᛪ ʋ ɦ ¤ ռ ʂ\nD Y R A X V H O N S\n-’X’ and ‘Z’ are interchangeable in spellings, though ‘X’ is typically reserved for nouns intended to appear formal and/or spiritually significant.\n-Like Common and unlike most other descendant languages, Vel’luah occasionally pairs ‘T’ and ‘H’ to form dental fricatives, the likes of which may be heard in Common words like ‘there’ and Vel’luah words like ‘kathir’"\r\n"Numbers:\nVel’luah has no numerical symbols. Instead, the names of numbers and equations are always written as full words:\n0 - sly\n1 - az 6 - vho\n2 - nyt 7 - reu\n3 - hek 8 - xyn\n4 - zag 9 - bex\n5 - kru 10 - unz\nNumber factors are determined by suffixing them accordingly:\n10s -ah\n100s -ee\n1000s -he\n100,000s -yhk\n100,000,000s -ux\nWhen described figuratively, these factors are written as if beginning with 1, and are suffixed again as plurals. A dark elf exaggerating with the word ‘hundreds’ would say ‘azahzh’.\nUnlike the Qalasheen Numerals used in Common, Vel’luah’s 0 (‘sly’) is never used to indicate a decimal place. It is less a number and more an indication of nothing; “less than one”.\nEach factor is written in descending order, connected with hyphens.\nFor example, 99 is ‘bexah-bex’. 1,203 is ‘azhe-nytee-hek’ (notably NOT ‘azhe-nytee-sly-hek’)."\r\n',
}

if __name__ == "__main__":
    # Render/other hosts set PORT; locally this falls back to 7860 (same as before)
    demo.launch(server_name="0.0.0.0", server_port=int(os.environ.get("PORT", 7860)))
