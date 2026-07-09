#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Festival della Pallamano 2026 - aggiornatore per PYDROID 3 (Android) - v3
--------------------------------------------------------------------------
1. scarica calendario.json dal GitHub Pages
2. legge le 4 pagine /programma-e-risultati (tutte le partite, concluse e "VS")
3. sincronizza il calendario (rinvii / cambi orario; mai aggiunge o toglie)
4. scrive risultati.json (e calendario.json se cambiato) accanto allo script
5. (opzionale) con token GitHub committa da solo

v3: parser tollerante (punteggi in riga unica, righe separate o spezzati),
gestione gzip, e AUTODIAGNOSI: se una pagina da' 0 partite salva l'HTML
in <cat>_pagina.html e stampa un estratto da mandare per la correzione.
"""

import json, re, time, unicodedata, urllib.request, base64, os, gzip

# ================== CONFIG ==================
REPO   = "SharkenCode80/FestivalDellaPallamano26"
BRANCH = "main"
CAL_URL = "https://sharkencode80.github.io/FestivalDellaPallamano26/calendario.json"
GITHUB_TOKEN = ""   # token fine-grained (Contents: RW) - vuoto = solo file locali
# ============================================

PAGES = {
    "u14m": "https://www.federhandball.it/competizione/under-14-maschile/programma-e-risultati",
    "u14f": "https://www.federhandball.it/competizione/under-14-femminile/programma-e-risultati",
    "u13":  "https://www.federhandball.it/competizione/under-13-misto/programma-e-risultati",
    "u911": "https://www.federhandball.it/competizione/under-11-misto/programma-e-risultati",
}
UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/124.0 Safari/537.36")

DT_RE  = re.compile(r"(\d{2})\.(\d{2})\s*-\s*(\d{2})/(\d{2})/(\d{4})")   # HH.MM - GG/MM/AAAA
DT2_RE = re.compile(r"(\d{2})/(\d{2})/(\d{4})\s*-\s*(\d{2})\.(\d{2})")   # GG/MM/AAAA - HH.MM
SC_RE  = re.compile(r"(?<![\d./])(\d{1,3})\s*-\s*(\d{1,3})(?![\d./])")
VS_RE  = re.compile(r"\bVS\b", re.I)
INLINE_TAGS = r"(?:span|a|b|strong|em|i|u|small|img|br)"

def http_get(url, cache_bust=True):
    if cache_bust:
        url = url + ("&" if "?" in url else "?") + "_cb=" + str(int(time.time()))
    req = urllib.request.Request(url, headers={
        "User-Agent": UA, "Cache-Control": "no-cache",
        "Accept": "text/html,application/xhtml+xml,application/json;q=0.9,*/*;q=0.8",
        "Accept-Encoding": "identity", "Accept-Language": "it-IT,it;q=0.9"})
    with urllib.request.urlopen(req, timeout=30) as r:
        data = r.read()
    if data[:2] == b"\x1f\x8b":           # gzip nonostante 'identity'
        data = gzip.decompress(data)
    return data.decode("utf-8", "replace")

def to_lines(html):
    html = re.sub(r"(?is)<script.*?</script>", " ", html)
    html = re.sub(r"(?is)<style.*?</style>", " ", html)
    html = re.sub(r"(?is)</?%s[^>]*>" % INLINE_TAGS, " ", html)  # inline -> spazio
    html = re.sub(r"(?is)<[^>]+>", "\n", html)                    # il resto -> a capo
    html = (html.replace("&nbsp;", " ").replace("&amp;", "&")
                .replace("&#8217;", "'").replace("&egrave;", "e"))
    lines = [re.sub(r"\s+", " ", x).strip() for x in html.split("\n")]
    lines = [x for x in lines if x]
    # ricompone punteggi spezzati:  "13" / "-" / "15"  ->  "13 - 15"
    out, i = [], 0
    while i < len(lines):
        if (i + 2 < len(lines) and lines[i].isdigit() and lines[i+1] == "-" and lines[i+2].isdigit()):
            out.append(f"{lines[i]} - {lines[i+2]}"); i += 3
        else:
            out.append(lines[i]); i += 1
    return out

def _clean_team(s):
    s = re.sub(r"Match report", " ", s, flags=re.I)
    s = DT_RE.sub(" ", s); s = DT2_RE.sub(" ", s)
    s = re.sub(r"\s+", " ", s).strip(" -|·")
    return s.strip()

def _is_team(s):
    return bool(s) and bool(re.search(r"[A-Za-zÀ-ü]", s)) and len(s) <= 60 \
           and s.upper() not in {"VS", "MATCH REPORT"} and not s.upper().startswith("GIORNATA")

def parse(html):
    lines = to_lines(html)
    for k, L in enumerate(lines):
        if L.upper().startswith("RESTA AGGIORNATO"):
            lines = lines[:k]; break

    # indicizza le righe-data: tipo 'prima' (HH.MM - GG/MM/AAAA) e 'dopo' (GG/MM/AAAA - HH.MM)
    date_at = {}   # idx riga -> (date, time, tipo)
    for i, L in enumerate(lines):
        m = None
        for mm in DT_RE.finditer(L): m = mm
        if m:
            date_at[i] = (f"{m.group(3)}/{m.group(4)}", f"{m.group(1)}.{m.group(2)}", "prima")
            continue
        m2 = None
        for mm in DT2_RE.finditer(L): m2 = mm
        if m2:
            date_at[i] = (f"{m2.group(1)}/{m2.group(2)}", f"{m2.group(4)}.{m2.group(5)}", "dopo")

    def date_for(i):
        """Data per la partita alla riga i: stessa riga, poi header 'prima' nelle
        4 precedenti, poi riga 'dopo' nelle 6 successive, poi l'ultima vista."""
        if i in date_at:
            return date_at[i]
        for j in range(i - 1, max(-1, i - 5), -1):
            if j in date_at and date_at[j][2] == "prima":
                return date_at[j]
        for j in range(i + 2, min(len(lines), i + 8)):
            if j in date_at and date_at[j][2] == "dopo":
                return date_at[j]
        for j in range(i - 1, -1, -1):
            if j in date_at:
                return date_at[j]
        return None

    out = []
    for i, L in enumerate(lines):
        body = DT_RE.sub(" ", L); body = DT2_RE.sub(" ", body)
        sc, vs = SC_RE.search(body), VS_RE.search(body)
        if not (sc or vs):
            continue
        dt = date_for(i)
        if not dt:
            continue
        mk = sc or vs
        left  = _clean_team(body[:mk.start()])
        right = _clean_team(body[mk.end():])
        home = left  if _is_team(left)  else _clean_team(lines[i-1]) if i > 0 else ""
        away = right if _is_team(right) else _clean_team(lines[i+1]) if i+1 < len(lines) else ""
        if not (_is_team(home) and _is_team(away)):
            continue
        rec = {"date": dt[0], "time": dt[1], "home": home, "away": away}
        if sc:
            hs, as_ = int(sc.group(1)), int(sc.group(2))
            if hs == 0 and as_ == 0:
                rec.update(played=False, hs=None, **{"as": None})
            else:
                rec.update(played=True, hs=hs, **{"as": as_})
        else:
            rec.update(played=False, hs=None, **{"as": None})
        out.append(rec)
    seen, ded = set(), []
    for r in out:
        k = (r["date"], frozenset({r["home"].upper(), r["away"].upper()}))
        if k in seen: continue
        seen.add(k); ded.append(r)
    return ded

def diagnose(cat, html, here):
    """Chiamata quando una pagina da' 0 partite: salva l'HTML e stampa indizi."""
    print(f"   [DIAGNOSI {cat}] html: {len(html)} caratteri, "
          f"'referto': {html.lower().count('referto')}, "
          f"'VS': {len(VS_RE.findall(html))}, "
          f"date trovate: {len(DT_RE.findall(html)) + len(DT2_RE.findall(html))}")
    path = os.path.join(here, f"{cat}_pagina.html")
    try:
        with open(path, "w", encoding="utf-8") as f: f.write(html)
        print(f"   [DIAGNOSI {cat}] HTML salvato in: {path}")
    except Exception as e:
        print(f"   [DIAGNOSI {cat}] salvataggio fallito: {e}")
    lines = to_lines(html)
    anchor = next((i for i, L in enumerate(lines)
                   if "referto" in L.lower() or DT_RE.search(L) or DT2_RE.search(L)), None)
    if anchor is None:
        print(f"   [DIAGNOSI {cat}] nessuna data/referto nel testo: probabile pagina di blocco/challenge.")
        print("   Prime righe ricevute:")
        for L in lines[:12]: print("      |", L[:100])
    else:
        a, b = max(0, anchor-6), min(len(lines), anchor+14)
        print(f"   [DIAGNOSI {cat}] estratto attorno alla riga {anchor}:")
        for L in lines[a:b]: print("      |", L[:100])
    print("   -> incolla questo output in chat per far correggere il parser.")


def out_dir():
    """Cartella di output visibile: prova Download, poi cartella script, poi cwd."""
    cands = ["/storage/emulated/0/Download", "/sdcard/Download",
             os.path.dirname(os.path.abspath(__file__)), os.getcwd()]
    for d in cands:
        try:
            t = os.path.join(d, ".test_scrittura")
            with open(t, "w") as f: f.write("ok")
            os.remove(t)
            return d
        except Exception:
            continue
    return os.getcwd()

def norm(s):
    s = unicodedata.normalize("NFKD", s or "").encode("ascii", "ignore").decode()
    return re.sub(r"\s+", " ", s).strip().upper()
def nd(s): return (s or "")[:5]

def sync_calendar(cal, pages_data):
    pair_map = {}
    for mt in cal["matches"]:
        pair_map.setdefault((mt["cat"], frozenset({norm(mt["home"]), norm(mt["away"])})), []).append(mt)
    changes, unknown = [], []
    for cat, plist in pages_data.items():
        for pm in plist:
            key = (cat, frozenset({norm(pm["home"]), norm(pm["away"])}))
            cands = pair_map.get(key, [])
            if not cands:
                unknown.append(f"{cat} {pm['date']} {pm['home']} - {pm['away']}")
                continue
            exact = [c for c in cands if nd(c["date"]) == pm["date"]]
            if exact:
                c = exact[0]
                if c["time"] != pm["time"]:
                    changes.append(f"{cat} {c['home']}-{c['away']} {c['date']}: ora {c['time']} -> {pm['time']}")
                    c["time"] = pm["time"]
            elif len(cands) == 1:
                c = cands[0]
                changes.append(f"{cat} {c['home']}-{c['away']}: RINVIO {c['date']} {c['time']} -> {pm['date']} {pm['time']}")
                c["date"], c["time"] = pm["date"], pm["time"]
            else:
                unknown.append(f"{cat} {pm['date']} {pm['home']} - {pm['away']} (coppia doppia, non tocco)")
    return changes, unknown

def github_commit(path, content_bytes, message):
    api = f"https://api.github.com/repos/{REPO}/contents/{path}"
    hdr = {"Authorization": "Bearer " + GITHUB_TOKEN,
           "Accept": "application/vnd.github+json", "User-Agent": UA}
    sha = None
    try:
        req = urllib.request.Request(api + "?ref=" + BRANCH, headers=hdr)
        with urllib.request.urlopen(req, timeout=30) as r:
            sha = json.load(r).get("sha")
    except Exception:
        pass
    body = {"message": message, "branch": BRANCH,
            "content": base64.b64encode(content_bytes).decode()}
    if sha: body["sha"] = sha
    req = urllib.request.Request(api, data=json.dumps(body).encode(),
                                 headers={**hdr, "Content-Type": "application/json"},
                                 method="PUT")
    with urllib.request.urlopen(req, timeout=30) as r:
        return r.status in (200, 201)

def main():
    here = out_dir()
    print("Cartella di output:", here)
    print("1) Scarico calendario.json ...")
    cal = json.loads(http_get(CAL_URL))
    print(f"   ok, {len(cal['matches'])} partite a calendario")

    pages_data = {}
    for cat, url in PAGES.items():
        print(f"2) Leggo {cat} ...")
        try:
            html = http_get(url)
        except Exception as e:
            print(f"   [ATTENZIONE] {cat}: pagina non raggiungibile ({e})")
            pages_data[cat] = []; continue
        pages_data[cat] = parse(html)
        n_fin = sum(1 for x in pages_data[cat] if x["played"])
        print(f"   {len(pages_data[cat])} partite ({n_fin} concluse)")
        if not pages_data[cat]:
            diagnose(cat, html, here)

    print("3) Sincronizzo il calendario ...")
    import copy
    cal_backup = copy.deepcopy(cal)
    changes, unknown = sync_calendar(cal, pages_data)
    MAX_MODIFICHE = 12
    if len(changes) > MAX_MODIFICHE:
        cal = cal_backup
        print(f"   [SICUREZZA] {len(changes)} modifiche al calendario: troppe, probabile errore di lettura.")
        print("   Calendario NON modificato. Incolla questo log in chat per verifica.")
        for c in changes[:15]: print("     ?", c)
        changes = []
    for c in changes: print("   *", c)
    if not changes: print("   nessuna modifica")
    for u in unknown: print("   [nota] non a calendario:", u)

    by = {}
    for mt in cal["matches"]:
        by[(nd(mt["date"]), mt["cat"], frozenset({norm(mt["home"]), norm(mt["away"])}))] = mt

    store = {}
    for cat, plist in pages_data.items():
        for pm in plist:
            if not pm["played"]:
                continue
            a, b = norm(pm["home"]), norm(pm["away"])
            mt = by.get((pm["date"], cat, frozenset({a, b})))
            if not mt:
                continue
            hs, as_ = (pm["hs"], pm["as"]) if norm(mt["home"]) == a else (pm["as"], pm["hs"])
            store[(nd(mt["date"]), cat, norm(mt["home"]), norm(mt["away"]))] = {
                "date": mt["date"], "cat": cat, "home": mt["home"], "away": mt["away"],
                "hs": hs, "as": as_, "status": "FINE"}

    def tkey(r):
        mt = by.get((nd(r["date"]), r["cat"], frozenset({norm(r["home"]), norm(r["away"])})))
        return (nd(r["date"]), mt["time"] if mt else "99.99", r["cat"], norm(r["home"]))
    results = sorted(store.values(), key=tkey)

    now = time.strftime("%d/%m/%Y %H:%M")
    ris = {"updated": now, "source": "federhandball.it (programma-e-risultati)", "results": results}
    ris_bytes = (json.dumps(ris, ensure_ascii=False, indent=2) + "\n").encode()
    ris_path = os.path.join(here, "risultati.json")
    with open(ris_path, "wb") as f:
        f.write(ris_bytes)
    per_cat = {}
    for r in results: per_cat[r["cat"]] = per_cat.get(r["cat"], 0) + 1
    print(f"4) Scritto {ris_path}: {len(results)} partite | {per_cat}")

    cal_bytes = None
    if changes:
        cal["event"]["updated"] = now
        cal_bytes = (json.dumps(cal, ensure_ascii=False, indent=2) + "\n").encode()
        cal_path = os.path.join(here, "calendario.json")
        with open(cal_path, "wb") as f:
            f.write(cal_bytes)
        print(f"   Scritto {cal_path} ({len(changes)} modifiche)")

    if GITHUB_TOKEN:
        print("5) Commit su GitHub ...")
        ok = github_commit("risultati.json", ris_bytes, "Aggiornamento risultati (" + now + ")")
        print("   risultati.json: " + ("ok" if ok else "FALLITO"))
        if cal_bytes:
            ok2 = github_commit("calendario.json", cal_bytes, "Aggiornamento calendario (" + now + ")")
            print("   calendario.json: " + ("ok" if ok2 else "FALLITO"))
        print("   Il sito si aggiorna in 1-2 minuti.")
    else:
        files = "risultati.json" + (" e calendario.json" if cal_bytes else "")
        print(f"5) Nessun token: carica {files} su GitHub a mano.")

if __name__ == "__main__":
    main()
