"""Importe depuis Wikidata (données publiques CC0) les lieux liés à la Seconde Guerre mondiale
situés en Belgique, France et Allemagne, et génère data/wikidata.js pour la carte.

Usage :  python scripts/fetch_wikidata.py
Aucune dépendance externe (bibliothèque standard uniquement).

Fonctionnement en deux temps, pour ménager le service public Wikidata :
  1. des requêtes SPARQL légères listent les éléments liés à la 2e GM qui ont des coordonnées ;
  2. l'API wbgetentities récupère par lots de 50 les noms, descriptions, types, dates, pays et articles.
"""
import json
import re
import sys
import time
import urllib.parse
import urllib.request
from collections import Counter
from pathlib import Path

SPARQL = "https://query.wikidata.org/sparql"
API = "https://www.wikidata.org/w/api.php"
USER_AGENT = "WW2Map/0.2 (carte historique locale; python-urllib)"
OUT = Path(__file__).resolve().parent.parent / "data" / "wikidata.js"

COUNTRIES = {"Q31": "BE", "Q142": "FR", "Q183": "DE"}
# Boîte englobante large (Belgique + France métropolitaine + Allemagne) pour un premier tri.
BBOX = (41.0, -5.5, 55.2, 15.2)  # lat_min, lon_min, lat_max, lon_max

SELECTORS = {
    "conflit = 2e GM (P607)": "?item wdt:P607 wd:Q362 .",
    "partie de la 2e GM (P361)": "?item wdt:P361 wd:Q362 .",
    "partie de… (2 niveaux)": "?item wdt:P361/wdt:P361 wd:Q362 .",
    "partie de… (3 niveaux)": "?item wdt:P361/wdt:P361/wdt:P361 wd:Q362 .",
    "commémore la 2e GM (P547)": "?item wdt:P547 wd:Q362 .",
    "camp de concentration nazi": "?item wdt:P31 wd:Q328468 .",
    "commémore un camp nazi": "?item wdt:P547 ?x . ?x wdt:P31 wd:Q328468 .",
    "commémore un événement de la 2e GM": "?item wdt:P547 ?x . ?x wdt:P361 ?y . ?y wdt:P361 wd:Q362 .",
}

# Classement par mots-clés sur le type Wikidata (P31, libellé anglais). L'ordre compte.
RULES = [
    ("skip",     r"stolperstein|^human$|film|book|painting|ship|watercraft|barque|steamboat|icebreaker|^tug$|aircraft|vehicle|locomotive|military unit|division|regiment|squadron|geschwader|^wing$|^squad$|organi[sz]ation|^war$|theatre|front$"),
    ("massacre", r"massacre|war crime|mass murder|atrocity|shooting|reprisal|pogrom"),
    ("museum",   r"museum"),
    ("memorial", r"cemetery|grave|memorial|monument|commemorat|plaque|necropolis|ossuary|cenotaph|sculpture|statue|stele|stela"),
    ("camp",     r"camp|ghetto|prison|stalag|oflag|internment|detention|forced labo|lager"),
    ("battle",   r"battle|siege|military operation|offensive|invasion|raid|landing|assault|campaign|airborne|skirmish|engagement|military action|combat|amphibious|maquis|pocket|dogfight"),
    ("event",    r"bombing|bombardment|air raid|liberation|deportation|round-?up|explosion|event|uprising|strike|execution|shipwreck|crash|conference|trial|surrender|armistice|occurrence"),
    ("military", r"bunker|fort|fortification|battery|base|airfield|air ?field|aerodrome|pillbox|casemate|blockhouse|submarine|shelter|barracks|flak|bridge|headquarters|tunnel|wall|line\b|military|launch|depot|radar|redoubt|strongpoint|gun emplacement"),
]


def http_json(url, data=None, accept="application/json"):
    req = urllib.request.Request(url, data=data, headers={"User-Agent": USER_AGENT, "Accept": accept})
    for attempt in range(4):
        try:
            with urllib.request.urlopen(req, timeout=70) as r:
                return json.load(r)
        except Exception as exc:  # noqa: BLE001
            print(f"   tentative {attempt + 1} échouée : {exc}", file=sys.stderr)
            time.sleep(10 * (attempt + 1))
    return None


def sparql(selector):
    q = f"SELECT DISTINCT ?item ?coord WHERE {{ {selector} ?item wdt:P625 ?coord . }}"
    data = urllib.parse.urlencode({"query": q, "format": "json"}).encode()
    res = http_json(SPARQL, data, "application/sparql-results+json")
    return res["results"]["bindings"] if res else []


def entities(ids, props):
    """wbgetentities par lots de 50."""
    out, ids = {}, list(ids)
    for i in range(0, len(ids), 50):
        params = {"action": "wbgetentities", "ids": "|".join(ids[i:i + 50]), "props": props,
                  "languages": "fr|en", "sitefilter": "frwiki|enwiki", "format": "json"}
        res = http_json(API + "?" + urllib.parse.urlencode(params))
        if res and "entities" in res:
            out.update(res["entities"])
        time.sleep(0.3)
    return out


def claim_ids(ent, prop):
    vals = []
    for c in ent.get("claims", {}).get(prop, []):
        v = c.get("mainsnak", {}).get("datavalue", {}).get("value")
        if isinstance(v, dict) and "id" in v:
            vals.append(v["id"])
    return vals


def claim_time(ent, prop):
    for c in ent.get("claims", {}).get(prop, []):
        v = c.get("mainsnak", {}).get("datavalue", {}).get("value")
        if isinstance(v, dict) and "time" in v:
            m = re.match(r"^\+?(\d{4})-(\d\d)-(\d\d)", v["time"])
            if not m:
                continue
            y, mo, d = m.groups()
            prec = v.get("precision", 11)  # 9 = année, 10 = mois, 11 = jour
            if prec <= 9 or mo == "00":
                return y
            if prec == 10 or d == "00":
                return f"{y}-{mo}"
            return f"{y}-{mo}-{d}"
    return None


def label(ent, kind="labels"):
    d = ent.get(kind, {})
    return (d.get("fr") or d.get("en") or {}).get("value")


def classify(type_labels):
    for cat, pattern in RULES:
        if any(re.search(pattern, t, re.I) for t in type_labels):
            return cat
    return None


def main():
    # 1. Recherche des éléments
    coords = {}
    for name, sel in SELECTORS.items():
        print(f"→ {name} …", flush=True)
        rows = sparql(sel)
        kept = 0
        for r in rows:
            m = re.match(r"Point\(([-\d.eE]+) ([-\d.eE]+)\)", r["coord"]["value"])
            if not m:
                continue
            lon, lat = float(m.group(1)), float(m.group(2))
            if BBOX[0] <= lat <= BBOX[2] and BBOX[1] <= lon <= BBOX[3]:
                coords.setdefault(r["item"]["value"].rsplit("/", 1)[-1], (lat, lon))
                kept += 1
        print(f"   {len(rows)} résultats, {kept} dans la zone", flush=True)
        time.sleep(3)
    print(f"\n{len(coords)} éléments uniques — récupération des détails…", flush=True)

    # 2. Détails
    ents = entities(coords, "labels|descriptions|claims|sitelinks/urls")

    # Pays : P17 direct, sinon via le lieu (P276) ou la commune (P131)
    need_place = set()
    for e in ents.values():
        if not claim_ids(e, "P17"):
            need_place.update(claim_ids(e, "P276")[:1] + claim_ids(e, "P131")[:1])
    places = entities(need_place, "claims") if need_place else {}

    type_ids = {t for e in ents.values() for t in claim_ids(e, "P31")}
    print(f"   {len(type_ids)} types à nommer…", flush=True)
    type_labels = {}
    for tid, te in entities(type_ids, "labels").items():
        type_labels[tid] = (te.get("labels", {}).get("en") or te.get("labels", {}).get("fr") or {}).get("value", "")

    out, unmatched, no_country = [], Counter(), 0
    for qid, e in ents.items():
        if "missing" in e:
            continue
        ccs = [COUNTRIES[c] for c in claim_ids(e, "P17") if c in COUNTRIES]
        if not claim_ids(e, "P17"):
            for p in claim_ids(e, "P276")[:1] + claim_ids(e, "P131")[:1]:
                ccs += [COUNTRIES[c] for c in claim_ids(places.get(p, {}), "P17") if c in COUNTRIES]
        if not ccs:
            no_country += 1
            continue
        types = {type_labels.get(t, "") for t in claim_ids(e, "P31")} - {""}
        cat = classify(types)
        if cat is None:
            unmatched.update(types or {"(sans type)"})
            continue
        if cat == "skip":
            continue
        name = label(e)
        if not name:
            continue
        sl = e.get("sitelinks", {})
        url = (sl.get("frwiki") or sl.get("enwiki") or {}).get("url")
        lat, lon = coords[qid]
        rec = {
            "n": name, "c": cat, "sub": ", ".join(sorted(types))[:80] or None, "cc": ccs[0],
            "lat": round(lat, 5), "lon": round(lon, 5),
            "s": claim_time(e, "P580") or claim_time(e, "P585") or claim_time(e, "P571"),
            "e": claim_time(e, "P582"),
            "d": label(e, "descriptions"), "url": url, "qid": qid,
        }
        out.append({k: v for k, v in rec.items() if v is not None})

    out.sort(key=lambda r: (r["cc"], r["c"], r["n"]))
    OUT.write_text(
        "// Généré automatiquement par scripts/fetch_wikidata.py — ne pas modifier à la main.\n"
        f"// Source : Wikidata (CC0), {time.strftime('%Y-%m-%d')}. {len(out)} lieux.\n"
        "window.WW2_WIKIDATA = " + json.dumps(out, ensure_ascii=False, separators=(",", ":")).replace("},{", "},\n{") + ";\n",
        encoding="utf-8",
    )
    stats = Counter((r["cc"], r["c"]) for r in out)
    print(f"\n{len(out)} lieux écrits dans {OUT} ({no_country} hors BE/FR/DE ignorés)")
    for (cc, c), n in sorted(stats.items()):
        print(f"   {cc} {c:9s} {n}")
    if unmatched:
        print("\nTypes non classés (les plus fréquents) — à ajouter dans RULES si pertinent :")
        for t, n in unmatched.most_common(30):
            print(f"   {n:4d}  {t}")


if __name__ == "__main__":
    main()
