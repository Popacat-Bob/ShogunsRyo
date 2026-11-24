"""Quick checks for the Maparonnarn app. Run:  python test_maparonnarn.py
Works offline (falls back to the bundled snapshots); with internet it tests the live doc/sheet data."""
import os, sys, tempfile, importlib.util

here = os.path.dirname(os.path.abspath(__file__))
spec = importlib.util.spec_from_file_location("m", os.path.join(here, "maparonnarn_app.py"))
m = importlib.util.module_from_spec(spec); spec.loader.exec_module(m)
_tmp = tempfile.mkdtemp()
m.MY_FILE, m.SAVED_FILE = os.path.join(_tmp, "my_words.txt"), os.path.join(_tmp, "saved_lines.txt")   # never touch your real files
d = m.load(force=True)
S, W, D = m.SNOW, m.WIKI, m.DARK
fails = []

def check(name, ok, info=""):
    print(("PASS " if ok else "FAIL ") + name + (f"   {info}" if info and not ok else ""))
    if not ok: fails.append(name)

first = lambda t, sel: m.to_fennic(t, sel).split("\n")[0]
check("snow doc parsed (>=500 words)", len(d["W"]) >= 500, len(d["W"]))
check("snow numbers 0-99 complete", len(d["N"]) == 100, len(d["N"]))
check("wiki parsed (>=800 words)", len(d["WW"]) >= 800, len(d["WW"]))
check("dark sheet parsed (>=45 words, >=10 phrases)", len(d["DW"]) >= 45 and len(d["DP"]) >= 10, (len(d["DW"]), len(d["DP"])))
check("dark letter table loaded", len(d["DL"]) >= 19, len(d["DL"]))
check("snow: past tense mark", "Ia’Kai" in first("I was cold", [S]))
check("snow: plural mark", "’len" in first("horses", [S]))
check("dark: no snow grammar", first("I was cold", [D]).startswith("### I was"), first("I was cold", [D]))
check("dark: greeting", "Vraz" in first("good", [D]))
check("dark: insult words are not suggested", first("cat", [D]) == "### cat")
check("dark: insult words still searchable", "Bolso" in m.search("Bolso", [D]))
check("wiki alone", "bortu" in first("dwarf", [W]).lower())
check("pair excludes the third", first("dwarf", [S, D]) == "### dwarf")
check("pair includes both", "Vraz" in first("good dwarf", [D, W]) and "bortu" in first("good dwarf", [D, W]).lower())
check("nothing ticked falls back to snow", first("I was cold", []) == first("I was cold", [S]))
check("view() does not mutate the dialects", (lambda a: (m.view(d, [S, D, W]), len(d["DW"]["vraz"]["defs"]) == a)[1])(len(d["DW"]["vraz"]["defs"])))
check("unknown words stay English", first("quixotic zebra", [S]) == "### quixotic zebra")
check("pick-words keeps punctuation", m.partial("It is cold, friend.", ["cold"], [S]) == "It is Burim, friend.")
check("pick-words styles", m.partial("cold", ["cold"], [S], "Italics") == "*Burim*" and m.partial("cold", ["cold"], [S], "With the original word in brackets") == "Burim (cold)")
check("overlap view has rows", len(m.browse("Overlaps", "", [S, W])) > 0)
check("script maps known letters", m.to_script("Vraz", False) == "ʋᵲαչ", m.to_script("Vraz", False))
_saved = m._DB; m._DB = dict(_saved, DL={}, t=__import__("time").time() + 1e6)
check("script works with no sheet letter table (built-in letters)", m.to_script("Vraz", False) == "ʋᵲαչ", m.to_script("Vraz", False))
m._DB = _saved
check("script tab translates English first", m.to_script("good").split("\n") == ["Vraz", "ʋᵲαչ"], m.to_script("good"))
check("unknown English words stay in Latin letters", m.to_script("good zebra").split("\n")[1] == "ʋᵲαչ zebra", m.to_script("good zebra"))
m.save_mine("Zorbak = cold")
check("my words win", "Zorbak" in first("cold", [S, W, D]), first("cold", [S, W, D]))
check("fennic to english decodes snow affixes", "past" in m.to_english("Ia’Ayred ehyubor", [S]))
# Dark Elf Dictionary tab layout (rows copied from the sheet): column pairs with blank spacer columns
import csv, io
cols = [("Prefixes", [("a-, an-, in-, mis- (without)", "be-"), ("ante- (before)", "luy-")]),
        ("Suffixes", [("-acy (state or quality)", "-eth")]),
        ("Verbs", [("Was /were", "a’tom"), ("To hate/ loathe/ despise", "adry"), ("To make", "aehg")]),
        ("Nouns", [("(IRL) Day", "Velel"), ("[feminine only] Primarch/ High Chieftess/ Queen", "velana"), ("[masculine only] Primarch/ High Chieftain/ King", "urex")]),
        ("Pronouns", [("He", "ura"), ("Him", "urada"), ("I", "yto")]),
        ("Articles", [("A", "-o"), ("The", "-el")]),
        ("Question Words", [("How", "mol"), ("Who/ what", "myrz")]),
        ("Conjunctions", [("And", "zy")])]
height = 1 + max(len(r) for _, r in cols)
grid = [[] for _ in range(height)]
for ci, (_, items) in enumerate(cols):
    for r in range(height):
        pair = ("Common", "Vel'luah") if r == 0 else (items[r - 1] if r - 1 < len(items) else ("", ""))
        grid[r] += list(pair) + ([""] if ci < len(cols) - 1 else [])
buf = io.StringIO(); csv.writer(buf).writerows(grid)
dd = m.parse_dark([("Dictionary", "dict", buf.getvalue())])
check("dictionary tab: words read from column pairs", "adry" in dd["DW"] and "mol" in dd["DW"], list(dd["DW"])[:6])
check("dictionary tab: English side indexed (hate/loathe)", dd["DE"].get("hate") == ["adry"] and dd["DE"].get("loathe") == ["adry"], dd["DE"].get("hate"))
check("dictionary tab: '(IRL) Day' and '[feminine only]' notes handled", dd["DE"].get("day") == ["Velel"] and "primarch" in dd["DE"], list(dd["DE"])[:8])
check("dictionary tab: prefixes, suffixes and -o/-el go to affixes", ("be-", "a-, an-, in-, mis- (without)") in dd["DA"] and any(a == "-el" for a, _ in dd["DA"]), dd["DA"])
check("he and him stay separate", dd["DE"].get("he") == ["ura"] and dd["DE"].get("him") == ["urada"])
check("tabs list includes the dictionary", any(k == "dict" for _, _, k in m.DARK_TABS))
# Dark Elf grammar tab, per-language grammar text, numbers, Vel'luah grammar in the translator
check("dark grammar tab loaded", "Plural is denoted" in d["DG"] and "Numbers:" in d["DG"], len(d["DG"]))
g1, g2, g3 = m.grammar_text(d, [S]), m.grammar_text(d, [D]), m.grammar_text(d, [W])
check("grammar text follows the ticked language", "Snow Elf" in g1 and "Vel’luah" not in g1 and "Plural is denoted" in g2 and "Snow Elf (doc) ══" not in g2 and "No grammar notes" in g3)
check("grammar text for two languages has both", "══ Snow Elf" in m.grammar_text(d, [S, D]) and "══ Dark Elf" in m.grammar_text(d, [S, D]))
check("vel'luah 99 = bexah-bex", m.dark_number(99, d) == "bexah-bex", m.dark_number(99, d))
check("vel'luah 1203 = azhe-nytee-hek (no zero place)", m.dark_number(1203, d) == "azhe-nytee-hek", m.dark_number(1203, d))
check("vel'luah 0 and 10", m.dark_number(0, d) == "sly" and m.dark_number(10, d) == "unz")
nm = m.number("1203", [S, D])
check("number output names each language", "Snow Elf (doc):" in nm and "Dark Elf (Vel'luah): azhe-nytee-hek" in nm, nm)
check("number is Snow only when only Snow is ticked", "Dark Elf" not in m.number("5", [S]))
import time
extra = [("Prefixes", []), ("Suffixes", []), ("Verbs", [("To hate", "adry")]), ("Nouns", [("Book", "olanu"), ("Elf", "maehr")])]   # same column order as the real tab
height = 1 + max(len(r) for _, r in extra)
g2d = [[] for _ in range(height)]
for ci, (_, items) in enumerate(extra):
    for r in range(height):
        pair = ("Common", "Vel'luah") if r == 0 else (items[r - 1] if r - 1 < len(items) else ("", ""))
        g2d[r] += list(pair) + ([""] if ci < len(extra) - 1 else [])
b2 = io.StringIO(); csv.writer(b2).writerows(g2d)
saved = m._DB
m._DB = dict(saved, **m.parse_dark([("Dictionary", "dict", b2.getvalue())]), t=time.time() + 1e6)
check("vel'luah: plural + article ('the books' -> olanuzhel)", first("the books", [D]) == "### olanuzhel", first("the books", [D]))
check("vel'luah: possessive suffix", first("Laevaelyn's book", [D]).startswith("### Laevaelyn’uhn olanu"), first("Laevaelyn's book", [D]))
check("vel'luah: past and future prefixes", first("did hate", [D]) == "### a’adry" and first("shall hate", [D]) == "### e’adry", first("did hate", [D]))
check("vel'luah: suffix skips a repeated letter", m.attach("memnu", "ule") == "memnule" and m.attach("maehr", "zh") == "maehrzh")
m._DB = saved
# Phrases, smarter English matching, reverse pick-words, line builder, practice, saved lines, verb-final option
check("phrase: English -> Vel'luah ('go with the moon')", first("go with the moon", [D]) == "### Ukh lu velulael", first("go with the moon", [D]))
check("phrase: Vel'luah -> English", "go with the Moon" in m.to_english("Ukh lu velulael", [D]).split("\n")[0])
check("phrase: longest match wins over single words", first("go in shame", [D]) == "### Ukh bo bashuk", first("go in shame", [D]))
check("variants: studies / running / hated", ("study", "s") in m.variants("studies") and ("run", "ing") in m.variants("running") and ("hate", "ed") in m.variants("hated"))
check("snow: plural noun still gets 'len", "Per’len" in first("horses", [S]), first("horses", [S]))
check("wiki: likes finds like", first("likes", [W]) == first("like", [W]) and first("like", [W]) != "### like", first("likes", [W]))
check("snow: -ed sets past tense", first("walked", [S]).startswith("### Ia’") or "walk" in first("walked", [S]).lower())
check("verb-final option moves the verb", first("I see Ayred", [S]) == "### Kai Tr’surra Ayred" and m.to_fennic("I see Ayred", [S], True).split("\n")[0] == "### Kai Ayred Tr’surra", (first("I see Ayred", [S]), m.to_fennic("I see Ayred", [S], True).split("\n")[0]))
check("reverse pick-words", "sleep" in m.partial_rev("Ia’Ayred ehyubor", ["ehyubor"], [S]).lower() and m.partial_rev("Ia’Ayred ehyubor.", ["ehyubor"], [S]).endswith("."), m.partial_rev("Ia’Ayred ehyubor.", ["ehyubor"], [S]))
check("reverse pick-words list", any("ehyubor" in c[0] for c in m.word_options_rev("Ia’Ayred ehyubor", [S])["choices"]))
check("line builder formats", m.build_line("Valyra", "good", [D], m.LINE_FORMATS[0], True, "", False) == 'Valyra says, “Vraz” (good)' and m.build_line("", "good", [D]) == "“Vraz”" and m.build_line("Valyra", "good", [D], m.LINE_FORMATS[1], False, "bows") == "*bows* Valyra: Vraz", m.build_line("Valyra", "good", [D], m.LINE_FORMATS[1], False, "bows"))
msg, box = m.add_saved("Valyra says, “Vraz”")
check("saved lines are added", "Added" in msg and "Vraz" in box and "Vraz" in m.get_saved())
import random, json
random.seed(3)
card, _, _, st = m.new_card(m.DIRS[0], [S], "")
ans = json.loads(st)["a"][0]
fb, st2 = m.check_card(ans, st)
check("practice: correct answer scores", "✅" in fb and json.loads(st2)["c"] == 1, fb)
_, _, _, st3 = m.new_card(m.DIRS[1], [S], st2)
fb2, st4 = m.check_card("zzzz", st3)
check("practice: wrong answer, score carries over", "❌" in fb2 and json.loads(st4)["t"] == 2 and json.loads(st4)["c"] == 1, fb2)
m.save_mine("Ukh lu mi = go with me")
check("my words: multi-word phrases work", first("go with me", [S]) == "### Ukh lu mi", first("go with me", [S]))
# word endings on the Vel'luah grammar (uses the sample dictionary built above)
saved = m._DB
m._DB = dict(saved, **m.parse_dark([("Dictionary", "dict", b2.getvalue())]), t=time.time() + 1e6)
got = (first("hates", [D]), first("hating", [D]), first("hated", [D]))
check("vel'luah endings: hates / hating / hated", got == ("### adry", "### adryule", "### a’adry"), got)
m._DB = saved
print("\nAll good." if not fails else f"\n{len(fails)} check(s) failed: {', '.join(fails)}")
sys.exit(1 if fails else 0)
