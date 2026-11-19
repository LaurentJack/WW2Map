"""Importe depuis OpenStreetMap (ODbL) les bunkers, fortifications et champs de bataille
de la Seconde Guerre mondiale en Belgique, France et Allemagne, et génère data/osm.js.

Usage :  python scripts/fetch_osm.py            (réutilise le dernier téléchargement mis en cache)
         python scripts/fetch_osm.py --refresh  (retélécharge)

Les données viennent du service SPARQL QLever (université de Fribourg, copie complète d'OSM) :
deux requêtes suffisent (tags, puis géométries), et le pays est donné directement par les relations
frontières que l'objet intersecte. Les serveurs Overpass publics, utilisés au départ, étaient trop
souvent saturés pour une extraction sur trois pays.

OSM ne précise presque jamais l'époque d'un bunker : un élément n'est retenu que s'il est
explicitement rattaché à 1939-1945 (date de construction, nom, description, ligne défensive :
Atlantikwall, Westwall, Maginot, ligne KW…). Les éléments de 1914-1918 sont écartés.
"""
import csv
import io
import json
import re
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from collections import Counter
from pathlib import Path

from geo_utils import DATA, USER_AGENT, existing_places, is_duplicate, key_words, write_js

QLEVER = "https://qlever.dev/api/osm-planet"
CACHE = Path(__file__).resolve().parent / ".cache" / "osm"
OUT = DATA / "osm.js"
COUNTRY_RELATIONS = {"52411": "BE", "2202162": "FR", "51477": "DE"}  # relations OSM des frontières nationales

PREFIXES = """PREFIX osmkey: <https://www.openstreetmap.org/wiki/Key:>
PREFIX ogc: <http://www.opengis.net/rdf#>
PREFIX geo: <http://www.opengis.net/ont/geosparql#>
PREFIX osmrel: <https://www.openstreetmap.org/relation/>
"""
SELECTION = """{ SELECT DISTINCT ?o ?c WHERE {
    VALUES ?c { osmrel:52411 osmrel:2202162 osmrel:51477 }
    { ?o osmkey:military "bunker" } UNION { ?o osmkey:historic "bunker" } UNION { ?o osmkey:building "bunker" }
    UNION { ?o osmkey:historic "fort" } UNION { ?o osmkey:historic "battlefield" }
    ?o ogc:sfIntersects ?c .
  } }"""
QUERY_TAGS = PREFIXES + "SELECT ?o ?c ?k ?v WHERE { " + SELECTION + """
  ?o ?k ?v . FILTER(STRSTARTS(STR(?k), "https://www.openstreetmap.org/wiki/Key:")) }"""
QUERY_GEOM = PREFIXES + "SELECT ?o ?w WHERE { " + SELECTION + " ?o geo:hasGeometry ?g . ?g geo:asWKT ?w . }"

TEXT_KEYS = ("name", "name:fr", "name:de", "name:en", "name:nl", "alt_name", "old_name", "description",
             "description:fr", "description:de", "inscription", "note", "wikipedia", "part_of", "line",
             "defensive_line", "historic:period", "historic:civilization", "operator", "subject", "website")

WW1 = re.compile(r"191[4-8]|(?<![a-z])ww ?(?:i|1)(?![i\d])|(?<![a-z])wo ?(?:i|1)(?![i\d])|premi[eè]re guerre|grande guerre|"
                 r"great war|erste[nr]? weltkrieg|1\. ?weltkrieg|eerste wereldoorlog", re.I)
LINES = [
    ("Mur de l'Atlantique", re.compile(r"atlanti(?:k|c|que)[ -]?wall|mur de l.atlantique|atlantikwal", re.I)),
    ("Westwall (ligne Siegfried)", re.compile(r"westwall|siegfried", re.I)),
    ("Ligne Maginot", re.compile(r"maginot", re.I)),
    ("Ligne KW (Belgique)", re.compile(r"kw[- ]?(?:lini|stelling|line)|ligne k\.?w|stelling antwerpen", re.I)),
    ("Position fortifiée de Liège", re.compile(r"position fortifi[ée]e de li[eè]ge|\bpfl\b", re.I)),
    ("Abri antiaérien", re.compile(r"luftschutz|hochbunker|tiefbunker|r[oö]hrenbunker|abri anti.?a[ée]rien|air.?raid", re.I)),
    ("Site V1 / V2", re.compile(r"\bv-?[12]\b|vergeltungswaffe|ramp(?:e)? de lancement|blockhaus d.[ée]perlecques|coupole", re.I)),
]
WW2 = re.compile(r"ww ?ii|ww ?2|wo ?ii|wo ?2|world war (?:ii|2|two)|2e guerre|seconde guerre|deuxi[eè]me guerre|"
                 r"zweite[nr]? weltkrieg|2\. ?weltkrieg|tweede wereldoorlog|39-45|1939|194[0-5]|d-day|overlord|"
                 r"ardenne|bulge|airborne|bodenplatte|foxhole|wehrmacht|kriegsmarine|luftwaffe|todt|regelbau|"
                 r"widerstandsnest|st[uü]tzpunkt|\bwn ?\d|\bstp ?\d|flak|u-?boot|sous-marin|marinepeilstand|"
                 r"lib[ée]ration|d[ée]barquement|kampfgruppe|occupation allemande", re.I)
REGELBAU = re.compile(r"\b(?:R|H|M|FL|L|V)\s?\d{3}[a-z]?\b")  # types de bunker Regelbau (sensible à la casse)

BUNKER_TYPES = {
    "pillbox": "Casemate / pillbox", "gun_emplacement": "Emplacement de canon", "munitions": "Soute à munitions",
    "personnel_shelter": "Abri pour le personnel", "troops_crew_bunker": "Abri pour la troupe",
    "observation": "Poste d'observation", "command": "Poste de commandement", "casemate": "Casemate",
    "mg_nest": "Nid de mitrailleuse", "bomb_shelter": "Abri antiaérien", "technical": "Bunker technique",
    "hardened_aircraft_shelter": "Abri d'avion", "blockhouse": "Blockhaus", "radar": "Bunker radar",
}


def year_of(v):
    m = re.search(r"(1[89]\d\d|20\d\d)", v or "")
    return int(m.group(1)) if m else None


def classify(tags):
    """Renvoie (est_2e_GM, ligne défensive ou None)."""
    text = " ".join(tags.get(k, "") for k in TEXT_KEYS)
    y = year_of(tags.get("start_date") or tags.get("date") or tags.get("construction_date"))
    line = next((label for label, rx in LINES if rx.search(text)), None)
    if y is not None and (y < 1928 or y > 1945):
        return False, line  # construit avant ou après la période (14-18, guerre froide…)
    explicit = bool(WW2.search(text)) or tags.get("historic:period", "").lower() in ("wwii", "ww2")
    regelbau = bool(REGELBAU.search(tags.get("name", "") + " " + tags.get("ref", "")))
    dated = y is not None  # 1928-1945 : ligne Maginot, ligne KW… construites pour la guerre à venir
    if WW1.search(text) and not (explicit or line or dated):
        return False, line
    return bool(line or explicit or regelbau or dated), line


def qlever(query, cache_name, refresh):
    """Résultat TSV de QLever (liste de lignes), mis en cache dans scripts/.cache/osm/."""
    CACHE.mkdir(parents=True, exist_ok=True)
    f = CACHE / cache_name
    if f.exists() and not refresh:
        text = f.read_text(encoding="utf-8")
    else:
        data = urllib.parse.urlencode({"query": query}).encode()
        req = urllib.request.Request(QLEVER, data=data, headers={"User-Agent": USER_AGENT, "Accept": "text/tab-separated-values"})
        for attempt in range(4):
            try:
                with urllib.request.urlopen(req, timeout=600) as r:
                    text = r.read().decode("utf-8")
                break
            except (urllib.error.URLError, TimeoutError) as exc:
                print(f"   tentative {attempt + 1} échouée : {exc}", flush=True)
                time.sleep(20 * (attempt + 1))
        else:
            raise SystemExit("QLever injoignable")
        f.write_text(text, encoding="utf-8")
    rows = list(csv.reader(io.StringIO(text), delimiter="\t", quoting=csv.QUOTE_NONE))
    return rows[1:]


def term(v):
    """Valeur TSV QLever → chaîne : <iri> ou "littéral"(@langue|^^type)."""
    if v.startswith("<") and v.endswith(">"):
        return v[1:-1]
    m = re.match(r'^"(.*)"(?:@[\w-]+|\^\^<[^>]+>)?$', v, re.S)
    s = m.group(1) if m else v
    return s.replace(r"\t", "\t").replace(r"\n", "\n").replace(r'\"', '"').replace("\\\\", "\\")


NUM = re.compile(r"-?\d+(?:\.\d+)?")


def centroid(wkt):
    """Centre approximatif (moyenne des sommets) d'une géométrie WKT → (lat, lon)."""
    nums = [float(x) for x in NUM.findall(wkt)]
    xs, ys = nums[0::2], nums[1::2]
    if not xs:
        return None
    return sum(ys) / len(ys), sum(xs) / len(xs)


def fetch_qlever(refresh):
    print("→ QLever : tags…", flush=True)
    elements = {}
    for o, c, k, v in qlever(QUERY_TAGS, "qlever_tags.tsv", refresh):
        url = term(o)
        typ, oid = url.rsplit("/", 2)[-2:]
        el = elements.setdefault(url, {"type": typ, "id": oid, "tags": {}, "cc": None})
        el["tags"][term(k).rsplit("Key:", 1)[-1]] = term(v)
        cc = COUNTRY_RELATIONS.get(term(c).rsplit("/", 1)[-1])
        if cc and not el["cc"]:
            el["cc"] = cc
    print(f"   {len(elements)} objets", flush=True)
    print("→ QLever : géométries…", flush=True)
    for o, w in qlever(QUERY_GEOM, "qlever_geom.tsv", refresh):
        el = elements.get(term(o))
        if el is not None and "lat" not in el:
            c = centroid(term(w))
            if c:
                el["lat"], el["lon"] = c
    return elements


def main():
    refresh = "--refresh" in sys.argv
    elements = fetch_qlever(refresh)

    known_qids = set(re.findall(r'"qid":"(Q\d+)"', (DATA / "wikidata.js").read_text(encoding="utf-8"))) \
        if (DATA / "wikidata.js").exists() else set()
    others = existing_places(["battle", "military"])

    out, stats = [], Counter()
    for el in elements.values():
        typ, oid = el["type"], el["id"]
        tags = el.get("tags", {})
        lat, lon = el.get("lat"), el.get("lon")
        if lat is None:
            continue
        cc = el["cc"]
        # la relation « France » inclut l'outre-mer : on ne garde que l'Europe occidentale
        if not cc or not (41.0 <= lat <= 55.5 and -5.5 <= lon <= 15.5):
            stats["hors BE/FR/DE (métropole)"] += 1
            continue
        ww2, line = classify(tags)
        if not ww2:
            stats["époque non 39-45 ou inconnue"] += 1
            continue
        if tags.get("wikidata") in known_qids:
            stats["déjà dans Wikidata"] += 1
            continue
        battle = tags.get("historic") == "battlefield"
        name = tags.get("name:fr") or tags.get("name")
        if not battle and tags.get("building") == "bunker" and not tags.get("military") and not line and not name:
            stats["abri sans information"] += 1
            continue
        if is_duplicate(lat, lon, key_words(name), others):
            stats["doublon"] += 1
            continue
        btype = BUNKER_TYPES.get(tags.get("bunker_type", ""), None)
        if battle:
            sub = "Champ de bataille"
        elif tags.get("historic") == "fort":
            sub = "Fort / ouvrage" + (f" — {line}" if line else "")
        else:
            sub = (btype or "Bunker") + (f" — {line}" if line and line != btype else "")
        if not name:
            name = sub
            if tags.get("ref"):
                name += f" ({tags['ref']})"
        y = year_of(tags.get("start_date") or tags.get("date"))
        rec = {
            "n": name, "c": "battle" if battle else "military", "sub": sub, "cc": cc,
            "lat": round(lat, 5), "lon": round(lon, 5),
            "s": str(y) if y and 1928 <= y <= 1946 else None,
            "d": tags.get("description:fr") or tags.get("description"),
            "url": f"https://www.openstreetmap.org/{typ}/{oid}",
            "qid": tags.get("wikidata") if re.fullmatch(r"Q\d+", tags.get("wikidata", "")) else None,
        }
        out.append({k: v for k, v in rec.items() if v is not None})
        stats[f"{cc} {'champ de bataille' if battle else (line or 'autre site 39-45')}"] += 1

    out.sort(key=lambda r: (r["cc"], r["c"], r["n"]))
    write_js(OUT, "WW2_OSM", out, "Source : © contributeurs OpenStreetMap (ODbL), via QLever (osm-planet),")
    print(f"\n{len(out)} lieux écrits dans {OUT}")
    for k, v in sorted(stats.items()):
        print(f"   {v:6d}  {k}")


if __name__ == "__main__":
    main()
