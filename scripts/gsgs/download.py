"""Télécharge depuis Wikimedia Commons les feuilles GSGS (éditions US Army Map Service, domaine public,
collection Perry-Castañeda de l'université du Texas) retenues pour la carte, en 3840 px de large.
Écrit la liste dans scripts/gsgs/sheets_raw.json. Cache : scripts/.cache/gsgs/.

Séries :
  france250k : France 1:250 000, AMS M561 = GSGS 4042 (1943)
  germany250k : Allemagne 1:250 000, AMS M501 = GSGS 4346, colonnes K à N (Benelux-Rhin → Elbe)
  belgium100k : Belgique et nord-est de la France 1:100 000, GSGS 2364 (1937, révisée 1943)
"""
import json
import re
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

HERE = Path(__file__).resolve().parent
CACHE = HERE.parent / ".cache" / "gsgs"
API = "https://commons.wikimedia.org/w/api.php"
UA = {"User-Agent": "WW2Map/0.3 (local research tool; python-urllib)"}
SERIES = {"france 250k": "france250k", "central europe 250k": "germany250k", "belgium 100k": "belgium100k"}


def get(url, binary=False):
    for a in range(6):
        try:
            with urllib.request.urlopen(urllib.request.Request(url, headers=UA), timeout=300) as r:
                data = r.read()
                return data if binary else json.loads(data)
        except urllib.error.HTTPError as e:
            if e.code not in (429, 500, 502, 503, 504):
                raise
            w = int(e.headers.get("Retry-After") or 30 * (a + 1))
            print(f"   HTTP {e.code}, attente {w} s", flush=True)
            time.sleep(w)
    raise RuntimeError(url)


def api(**p):
    return get(API + "?" + urllib.parse.urlencode({**p, "format": "json", "maxlag": 5}))


def main():
    CACHE.mkdir(parents=True, exist_ok=True)
    titles, off = set(), 0
    while True:
        d = api(action="query", list="search", srnamespace=6, srlimit=500, sroffset=off,
                srsearch='intitle:"Map by the US Army Map Service" txu-pclmaps')
        titles |= {x["title"] for x in d["query"]["search"]}
        if "continue" not in d:
            break
        off = d["continue"]["sroffset"]
        time.sleep(5)
    sheets = []
    for t in sorted(titles):
        m = re.match(r"File:Map by the US Army Map Service - (.+?) - (france 250k|central europe 250k|belgium 100k) - (.+)\.jpg$", t)
        if not m:
            continue
        name, ser, slug = m.groups()
        series = SERIES[ser]
        sid = re.search(r"-([a-z]?-?\d+[a-z]?(?:-[a-z])?)$", slug).group(1)
        if series == "germany250k":
            col = sid.split("-")[0]
            if col not in ("k", "l", "m", "n"):
                continue
        sheets.append({"series": series, "name": name, "sheet": sid.upper(), "title": t,
                       "page": "https://commons.wikimedia.org/wiki/" + urllib.parse.quote(t.replace(" ", "_")),
                       "cache": f"{series}_{re.sub(r'[^A-Za-z0-9]+', '_', name)}_{sid}.jpg"})
    print(f"{len(sheets)} feuilles retenues", flush=True)
    for i, s in enumerate(sheets, 1):
        f = CACHE / s["cache"]
        if not (f.exists() and f.stat().st_size > 100_000):
            d = api(action="query", titles=s["title"], prop="imageinfo", iiprop="url|size", iiurlwidth=3840)
            ii = list(d["query"]["pages"].values())[0]["imageinfo"][0]
            f.write_bytes(get(ii["thumburl"], binary=True))
            s["orig_size"] = [ii["width"], ii["height"]]
            time.sleep(4)
        print(f"   [{i}/{len(sheets)}] {s['series']} {s['sheet']} {s['name']}", flush=True)
    (HERE / "sheets_raw.json").write_text(json.dumps(sheets, ensure_ascii=False, indent=1), encoding="utf-8")


if __name__ == "__main__":
    main()
