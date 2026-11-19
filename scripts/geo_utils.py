"""Outils partagés par les scripts d'import : téléchargement, pays d'un point, doublons."""
import json
import math
import re
import time
import urllib.request
from pathlib import Path

USER_AGENT = "WW2Map/0.3 (carte historique locale; python-urllib)"
ROOT = Path(__file__).resolve().parent.parent
DATA = ROOT / "data"

BORDERS = "https://raw.githubusercontent.com/nvkelso/natural-earth-vector/v5.1.2/geojson/ne_50m_admin_0_countries.geojson"
COUNTRIES = {"BEL": "BE", "FRA": "FR", "DEU": "DE"}


def get_json(url, data=None, timeout=120, tries=4):
    req = urllib.request.Request(url, data=data, headers={"User-Agent": USER_AGENT})
    for attempt in range(tries):
        try:
            with urllib.request.urlopen(req, timeout=timeout) as r:
                return json.load(r)
        except Exception as exc:  # noqa: BLE001
            print(f"   tentative {attempt + 1} échouée : {exc}", flush=True)
            time.sleep(15 * (attempt + 1))
    return None


# ---------- pays d'un point (frontières Natural Earth, domaine public) ----------
def _ring_contains(ring, x, y):
    inside = False
    j = len(ring) - 1
    for i in range(len(ring)):
        xi, yi = ring[i][0], ring[i][1]
        xj, yj = ring[j][0], ring[j][1]
        if (yi > y) != (yj > y) and x < (xj - xi) * (y - yi) / (yj - yi) + xi:
            inside = not inside
        j = i
    return inside


class Borders:
    def __init__(self):
        print("→ frontières Natural Earth …", flush=True)
        geo = get_json(BORDERS)
        if not geo:
            raise SystemExit("Impossible de télécharger les frontières Natural Earth")
        self.shapes = []
        for f in geo["features"]:
            code = COUNTRIES.get(f["properties"].get("ADM0_A3"))
            if not code:
                continue
            g = f["geometry"]
            polys = [g["coordinates"]] if g["type"] == "Polygon" else g["coordinates"]
            for poly in polys:
                xs = [p[0] for p in poly[0]]
                ys = [p[1] for p in poly[0]]
                self.shapes.append((code, (min(xs), min(ys), max(xs), max(ys)), poly))

    def _exact(self, lon, lat):
        for code, (x0, y0, x1, y1), poly in self.shapes:
            if x0 <= lon <= x1 and y0 <= lat <= y1 and _ring_contains(poly[0], lon, lat) \
                    and not any(_ring_contains(h, lon, lat) for h in poly[1:]):
                return code
        return None

    def country(self, lon, lat):
        """Pays BE/FR/DE du point, avec une tolérance d'environ 4 km pour le littoral
        (les frontières au 1:50 000 000 sont simplifiées et coupent les bunkers côtiers)."""
        c = self._exact(lon, lat)
        if c:
            return c
        d = 0.05
        for dx, dy in ((d, 0), (-d, 0), (0, d), (0, -d), (d, d), (-d, d), (d, -d), (-d, -d)):
            c = self._exact(lon + dx, lat + dy)
            if c:
                return c
        return None


# ---------- doublons entre sources ----------
_STOP = {"camp", "de", "du", "des", "la", "le", "les", "concentration", "kz", "konzentrationslager", "lager",
         "fort", "the", "of", "bataille", "battle", "slag", "schlacht", "bunker", "ouvrage", "von", "der", "die"}


def key_words(s):
    s = (s or "").lower()
    for a, b in (("ä", "a"), ("ö", "o"), ("ü", "u"), ("ß", "ss"), ("é", "e"), ("è", "e"), ("ë", "e"), ("â", "a")):
        s = s.replace(a, b)
    return {w for w in re.sub(r"[^a-z0-9 ]", " ", s).split() if len(w) > 2 and w not in _STOP}


def existing_places(categories, files=("sites.js", "wikidata.js", "ehri_camps.js")):
    """(lat, lon, mots du nom) des lieux déjà présents dans les autres sources, pour les catégories données."""
    cats = "|".join(categories)
    pts = []
    for name in files:
        path = DATA / name
        if not path.exists():
            continue
        for m in re.finditer(r'\{[^{}]*?\bc\W+\s*:?\s*"(?:%s)"[^{}]*\}' % cats, path.read_text(encoding="utf-8")):
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


def is_duplicate(lat, lon, words, others, radius_km=3):
    return bool(words) and any(km(lat, lon, o_lat, o_lon) < radius_km and words & o_words
                               for o_lat, o_lon, o_words in others)


def write_js(path, var, records, header):
    path.write_text(
        f"// Généré automatiquement — ne pas modifier à la main.\n// {header} {time.strftime('%Y-%m-%d')}. {len(records)} lieux.\n"
        f"window.{var} = " + json.dumps(records, ensure_ascii=False, separators=(",", ":")).replace("},{", "},\n{") + ";\n",
        encoding="utf-8",
    )
