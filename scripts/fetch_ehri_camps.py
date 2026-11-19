"""Importe les camps et sous-camps (Außenlager / Kommandos) du jeu de données
« Concentration camps » de l'EHRI (European Holocaust Research Infrastructure)
et génère data/ehri_camps.js pour la carte.

Usage :  python scripts/fetch_ehri_camps.py
Aucune dépendance externe (bibliothèque standard uniquement).

Sources :
  - camps : couche WFS ehri:EHRI-camps-2022, https://geodata.ehri-project.eu
    (fiche : https://geodata.ehri-project.eu/geonetwork/srv/eng/catalog.search#/metadata/52302460-13fd-4914-b496-2f0230e996e1)
  - frontières actuelles : Natural Earth (domaine public), pour attribuer le pays.
"""
import json
import math
import re
import time
import urllib.parse
import urllib.request
from collections import Counter
from pathlib import Path

USER_AGENT = "WW2Map/0.2 (carte historique locale; python-urllib)"
ROOT = Path(__file__).resolve().parent.parent
OUT = ROOT / "data" / "ehri_camps.js"

WFS = "https://geodata.ehri-project.eu/geoserver/ows?" + urllib.parse.urlencode({
    "service": "WFS", "version": "2.0.0", "request": "GetFeature",
    "typeNames": "ehri:EHRI-camps-2022", "outputFormat": "application/json", "srsName": "EPSG:4326",
})
BORDERS = "https://raw.githubusercontent.com/nvkelso/natural-earth-vector/v5.1.2/geojson/ne_50m_admin_0_countries.geojson"
COUNTRIES = {"BEL": "BE", "FRA": "FR", "DEU": "DE"}


def get_json(url):
    req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    for attempt in range(4):
        try:
            with urllib.request.urlopen(req, timeout=120) as r:
                return json.load(r)
        except Exception as exc:  # noqa: BLE001
            print(f"   tentative {attempt + 1} échouée : {exc}")
            time.sleep(10 * (attempt + 1))
    raise SystemExit(f"Impossible de télécharger {url}")


# ---------- point dans un polygone (frontières Natural Earth) ----------
def ring_contains(ring, x, y):
    inside = False
    j = len(ring) - 1
    for i in range(len(ring)):
        xi, yi = ring[i][0], ring[i][1]
        xj, yj = ring[j][0], ring[j][1]
        if (yi > y) != (yj > y) and x < (xj - xi) * (y - yi) / (yj - yi) + xi:
            inside = not inside
        j = i
    return inside


def polygons(geom):
    if geom["type"] == "Polygon":
        return [geom["coordinates"]]
    if geom["type"] == "MultiPolygon":
        return geom["coordinates"]
    return []


def load_borders():
    print("→ frontières Natural Earth …")
    shapes = []
    for f in get_json(BORDERS)["features"]:
        code = COUNTRIES.get(f["properties"].get("ADM0_A3"))
        if code:
            for poly in polygons(f["geometry"]):
                xs = [p[0] for p in poly[0]]
                ys = [p[1] for p in poly[0]]
                shapes.append((code, (min(xs), min(ys), max(xs), max(ys)), poly))
    return shapes


def country_of(shapes, lon, lat):
    for code, (x0, y0, x1, y1), poly in shapes:
        if x0 <= lon <= x1 and y0 <= lat <= y1 and ring_contains(poly[0], lon, lat) \
                and not any(ring_contains(h, lon, lat) for h in poly[1:]):
            return code
    return None


# ---------- doublons avec les autres sources ----------
def norm(s):
    s = s.lower()
    for a, b in (("ä", "a"), ("ö", "o"), ("ü", "u"), ("ß", "ss"), ("é", "e"), ("è", "e"), ("ë", "e")):
        s = s.replace(a, b)
    return re.sub(r"[^a-z0-9 ]", " ", s)


STOP = {"camp", "de", "du", "des", "la", "le", "concentration", "kz", "konzentrationslager", "lager", "fort", "the", "of", "d"}


def key_words(s):
    return {w for w in norm(s).split() if len(w) > 2 and w not in STOP}


def existing_camps():
    pts = []
    for name in ("sites.js", "wikidata.js"):
        path = ROOT / "data" / name
        if not path.exists():
            continue
        text = path.read_text(encoding="utf-8")
        for m in re.finditer(r'\{[^{}]*?\bc\W+\s*:?\s*"camp"[^{}]*\}', text):
            block = m.group(0)
            n = re.search(r'\bn"?\s*:\s*"((?:[^"\\]|\\.)*)"', block)
            lat = re.search(r'\blat"?\s*:\s*(-?[\d.]+)', block)
            lon = re.search(r'\blon"?\s*:\s*(-?[\d.]+)', block)
            if n and lat and lon:
                pts.append((float(lat.group(1)), float(lon.group(1)), key_words(n.group(1))))
    return pts


def km(a_lat, a_lon, b_lat, b_lon):
    dx = (b_lon - a_lon) * 111.32 * math.cos(math.radians((a_lat + b_lat) / 2))
    dy = (b_lat - a_lat) * 110.57
    return math.hypot(dx, dy)


def clean(name):
    return re.sub(r"\s+concentration camp$", "", name or "").strip()


def main():
    shapes = load_borders()
    print("→ camps EHRI …")
    feats = get_json(WFS)["features"]
    by_url = {f["properties"]["URL"]: f["properties"] for f in feats}
    print(f"   {len(feats)} camps, dont {sum(1 for f in feats if f['geometry'])} géolocalisés")

    others = existing_camps()
    print(f"   {len(others)} camps déjà présents dans les autres sources (pour dédoublonnage)")

    out, dupes, outside = [], 0, Counter()
    for f in feats:
        if not f["geometry"]:
            continue
        p = f["properties"]
        lon, lat = f["geometry"]["coordinates"][:2]
        cc = country_of(shapes, lon, lat)
        if not cc:
            outside["hors BE/FR/DE"] += 1
            continue
        name = clean(p.get("name"))
        name_de = (p.get("name_DE") or "").strip()
        words = key_words(name) | key_words(name_de)
        if any(km(lat, lon, o_lat, o_lon) < 3 and words & o_words for o_lat, o_lon, o_words in others):
            dupes += 1
            continue
        parent = by_url.get(p.get("broader_UR") or "")
        parent_name = clean(parent["name"]) if parent else None
        if parent_name:
            sub = f"Sous-camp (Außenlager) de {parent_name}"
            n = f"{name} — sous-camp de {parent_name}"
        else:
            sub = "Camp de concentration / internement"
            n = name
        d = name_de if name_de and name_de.lower() != (p.get("name") or "").lower() else None
        rec = {"n": n, "c": "camp", "sub": sub, "cc": cc, "lat": round(lat, 5), "lon": round(lon, 5),
               "d": f"Nom allemand : {d}" if d else None, "url": p["URL"], "parent": parent_name}
        out.append({k: v for k, v in rec.items() if v is not None})

    out.sort(key=lambda r: (r["cc"], r.get("parent") or "", r["n"]))
    OUT.write_text(
        "// Généré automatiquement par scripts/fetch_ehri_camps.py — ne pas modifier à la main.\n"
        f"// Source : EHRI, jeu de données « Concentration camps » (EHRI-camps-2022), {time.strftime('%Y-%m-%d')}. {len(out)} lieux.\n"
        "window.WW2_EHRI = " + json.dumps(out, ensure_ascii=False, separators=(",", ":")).replace("},{", "},\n{") + ";\n",
        encoding="utf-8",
    )
    print(f"\n{len(out)} camps écrits dans {OUT}")
    print(f"   {dupes} doublons ignorés (déjà dans la sélection manuelle ou Wikidata), {outside['hors BE/FR/DE']} hors BE/FR/DE")
    for (cc, parent), n in sorted(Counter((r["cc"], r.get("parent") or "(camp principal / autonome)") for r in out).items()):
        print(f"   {cc}  {n:4d}  {parent}")


if __name__ == "__main__":
    main()
