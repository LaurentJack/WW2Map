"""Construit les calques des cartes de situation quotidiennes du 12th Army Group (1944-1945).

Source : Library of Congress, « World War II Military Situation Maps », copies Wikimedia Commons
(domaine public, œuvres du gouvernement fédéral américain).

Pour chaque date :
  1. télécharge la carte (3840 px) depuis Wikimedia Commons (cache : scripts/.cache/sitmaps/) ;
  2. l'aligne automatiquement sur la carte de référence calée (OpenCV, points ORB + RANSAC) ;
     les cartes qui ne correspondent pas au fond de référence sont ignorées ;
  3. la reprojette en Web Mercator, découpe le cadre et l'enregistre en WebP transparent
     dans data/sitmaps/<série>/<date>.webp ;
  4. met à jour data/sitmaps_<série>.js (liste lue par l'application).

Usage (avec l'environnement du projet, qui contient numpy, Pillow et OpenCV) :
  scripts/.venv/Scripts/python scripts/sitmaps/build_sitmaps.py --series 1M --from 1944-09-01 --to 1945-03-31
  options : --step 7 (une carte tous les 7 jours), --dates 1944-12-16,1944-12-26
"""
import argparse
import datetime as dt
import json
import math
import re
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

import cv2
import numpy as np
from PIL import Image

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent.parent
CACHE = HERE.parent / ".cache" / "sitmaps"
OUT_DIR = ROOT / "data" / "sitmaps"
sys.path.insert(0, str(HERE))
from georef import lcc  # noqa: E402

API = "https://commons.wikimedia.org/w/api.php"
UA = {"User-Agent": "WW2Map/0.3 (local research tool; python-urllib)"}
WIDTH = 3840          # largeur des images téléchargées (vignette standard Wikimedia)
MIN_INLIERS = 120

# Scans atypiques : (date, fond) → zone (x0, y0, x1, y1) de l'image 3840 px contenant la carte de ce fond.
# Le 10 septembre 1944, la Library of Congress a numérisé deux feuilles côte à côte (Bretagne à gauche,
# front principal à droite).
SCAN_CROPS = {
    ("1944-09-10", "1M"): (1900, 0, 3840, 1753),
    ("1944-09-10", "bzh_0910"): (0, 0, 1900, 1753),
}

# m_per_px : résolution de sortie en mètres Web Mercator (≈ 0,65 × cette valeur en mètres réels vers 50°N)
SERIES = {
    "1M": {"gcps": HERE / "gcps_1M.json", "label": "1:1 000 000 — France, Belgique, Rhénanie", "m_per_px": 230.0},
    "500k_s3": {"gcps": HERE / "gcps_500k_s3.json", "label": "1:500 000 — Normandie (feuille 3)", "m_per_px": 115.0},
    "500k_bzh": {"gcps": HERE / "gcps_500k_bzh.json", "label": "1:500 000 — Bretagne, Maine, Anjou", "m_per_px": 115.0},
    "500k_mo": {"gcps": HERE / "gcps_500k_mo.json", "label": "1:500 000 — Maine, Orléanais (poche de Falaise)", "m_per_px": 115.0},
    "750k_a": {"gcps": HERE / "gcps_750k_a.json", "label": "1:750 000 — Normandie, Loire, Paris", "m_per_px": 150.0},
    "750k_b": {"gcps": HERE / "gcps_750k_b.json", "label": "1:750 000 — Seine, Paris, Champagne", "m_per_px": 150.0},
    "750k_c": {"gcps": HERE / "gcps_750k_c.json", "label": "Début septembre 1944 — nord de la France, Belgique", "m_per_px": 150.0},
    "500k_am": {"gcps": HERE / "gcps_500k_am.json", "label": "1:500 000 — Avranches, Le Mans", "m_per_px": 115.0},
    "500k_sp": {"gcps": HERE / "gcps_500k_sp.json", "label": "Seine, Paris (libération de Paris)", "m_per_px": 115.0},
    "1M_rh": {"gcps": HERE / "gcps_1M_rh.json", "label": "1:1 000 000 — Rhénanie, Allemagne de l'Ouest", "m_per_px": 230.0},
    "1400k_de": {"gcps": HERE / "gcps_1400k_de.json", "label": "1:1 400 000 — Allemagne entière", "m_per_px": 320.0},
    "1000k_avr": {"gcps": HERE / "gcps_1000k_avr.json", "label": "Mi-avril 1945 — Allemagne centrale", "m_per_px": 230.0},
    "bzh_0910": {"gcps": HERE / "gcps_bzh_0910.json", "label": "1:1 000 000 — Bretagne (siège de Brest)", "m_per_px": 150.0},
    "1400k_occ": {"gcps": HERE / "gcps_1400k_occ.json", "label": "1:1 500 000 — Allemagne, zones d'occupation (Albers)", "m_per_px": 320.0},
}


# ---------------------------------------------------------------- Wikimedia Commons
def http(url, binary=False, tries=6):
    for a in range(tries):
        try:
            with urllib.request.urlopen(urllib.request.Request(url, headers=UA), timeout=300) as r:
                data = r.read()
                return data if binary else json.loads(data)
        except urllib.error.HTTPError as e:
            if e.code not in (429, 500, 502, 503, 504):
                raise
            wait = int(e.headers.get("Retry-After") or 20 * (a + 1))
            print(f"      HTTP {e.code}, nouvelle tentative dans {wait} s", flush=True)
            time.sleep(wait)
    raise RuntimeError(f"échec du téléchargement : {url}")


def list_maps():
    """{date ISO: {title, page}} pour toute la série, mis en cache."""
    CACHE.mkdir(parents=True, exist_ok=True)
    cache = CACHE / "list.json"
    if cache.exists():
        return json.loads(cache.read_text(encoding="utf-8"))
    titles, off = set(), 0
    while True:
        q = {"action": "query", "list": "search", "srnamespace": 6, "srlimit": 500, "sroffset": off,
             "srsearch": 'intitle:"Twelfth Army Group situation map"', "format": "json"}
        d = http(API + "?" + urllib.parse.urlencode(q))
        titles |= {x["title"] for x in d["query"]["search"]}
        if "continue" not in d:
            break
        off = d["continue"]["sroffset"]
        time.sleep(3)
    by_date = {}
    for t in sorted(titles):
        m = re.match(r"File:\((\w+ \d+, 194\d)\)", t)
        if not m:
            continue
        day = dt.datetime.strptime(m.group(1), "%B %d, %Y").date().isoformat()
        # préférer le JPEG (plus léger) au TIFF quand les deux existent
        if day not in by_date or (t.endswith(".jpg") and not by_date[day]["title"].endswith(".jpg")):
            by_date[day] = {"title": t, "page": "https://commons.wikimedia.org/wiki/" + urllib.parse.quote(t.replace(" ", "_"))}
    cache.write_text(json.dumps(by_date, indent=0), encoding="utf-8")
    return by_date


def download(day, title):
    f = CACHE / f"{day}.jpg"
    if f.exists() and f.stat().st_size > 100_000:
        return f
    q = {"action": "query", "titles": title, "prop": "imageinfo", "iiprop": "url", "iiurlwidth": WIDTH, "format": "json"}
    info = list(http(API + "?" + urllib.parse.urlencode(q))["query"]["pages"].values())[0]["imageinfo"][0]
    f.write_bytes(http(info["thumburl"], binary=True))
    time.sleep(3)  # politesse envers Wikimedia
    return f


def load_scan(day, series):
    """Image BGR de la carte du jour. Si le scan contient plusieurs feuilles (SCAN_CROPS),
    on isole celle du fond demandé et on la remet à la largeur standard."""
    color = cv2.imread(str(download(day, list_maps()[day]["title"])), cv2.IMREAD_COLOR)
    crop = SCAN_CROPS.get((day, series))
    if crop:
        x0, y0, x1, y1 = crop
        color = color[y0:y1, x0:x1]
        k = WIDTH / color.shape[1]
        color = cv2.resize(color, None, fx=k, fy=k, interpolation=cv2.INTER_CUBIC)
    return color


# ---------------------------------------------------------------- alignement
class Reference:
    def __init__(self, series):
        cfg = json.loads(SERIES[series]["gcps"].read_text(encoding="utf-8"))
        fit = json.loads(SERIES[series]["gcps"].with_suffix(".fit.json").read_text(encoding="utf-8"))
        self.series, self.m_per_px = series, SERIES[series]["m_per_px"]
        self.fit, self.neatline = fit, np.array(cfg["neatline_px"], np.float32)
        color = load_scan(cfg["reference_date"], series)
        self.img = color
        self.small = 0.5
        self.orb = cv2.ORB_create(nfeatures=12000)
        self.sift = cv2.SIFT_create(nfeatures=15000)
        self.prep_ref = self.prep(color)
        self.kp, self.des = self.orb.detectAndCompute(self.prep_ref, None)
        self._sift_ref = None

    def prep(self, color):
        """Image de travail : canal rouge (les traits gris, bleus et noirs y sont tous sombres,
        le papier crème y est clair), réduite de moitié, contraste égalisé localement.
        Cela rend l'alignement insensible aux tirages en bleu pâle ou en gris."""
        red = color[..., 2]
        s = cv2.resize(red, None, fx=self.small, fy=self.small, interpolation=cv2.INTER_AREA)
        return cv2.createCLAHE(3.0, (8, 8)).apply(s)

    @staticmethod
    def plausible(H):
        """Une carte du même fond ne diffère que par un léger décalage, une rotation et une échelle proche de 1."""
        if H is None:
            return False
        sx, sy = math.hypot(H[0, 0], H[1, 0]), math.hypot(H[0, 1], H[1, 1])
        return 0.85 < sx < 1.15 and 0.85 < sy < 1.15 and 0.95 < sx / sy < 1.05 \
            and abs(H[2, 0]) < 2e-5 and abs(H[2, 1]) < 2e-5

    def _match(self, kp, des, kp_ref, des_ref, norm, min_inliers):
        if des is None or des_ref is None:
            return None, 0
        matches = cv2.BFMatcher(norm).knnMatch(des, des_ref, k=2)
        good = [m for m, n in (p for p in matches if len(p) == 2) if m.distance < 0.75 * n.distance]
        if len(good) < min_inliers:
            return None, len(good)
        src = np.float32([kp[m.queryIdx].pt for m in good]) / self.small
        dst = np.float32([kp_ref[m.trainIdx].pt for m in good]) / self.small
        H, mask = cv2.findHomography(src, dst, cv2.RANSAC, 6.0, maxIters=8000)
        inliers = int(mask.sum()) if mask is not None else 0
        if inliers < min_inliers or not self.plausible(H):
            return None, inliers
        return H, inliers

    def coverage(self, H, shape):
        """Part du cadre de la référence couverte par la carte du jour une fois alignée (0 à 1).
        Une feuille voisine qui ne partage qu'une bande de recouvrement donne une valeur faible."""
        h, w = shape[:2]
        corners = cv2.perspectiveTransform(np.float32([[[0, 0]], [[w, 0]], [[w, h]], [[0, h]]]), H)
        k = 0.1
        size = (int(self.img.shape[1] * k), int(self.img.shape[0] * k))
        a = np.zeros(size[::-1], np.uint8)
        b = np.zeros(size[::-1], np.uint8)
        cv2.fillPoly(a, [(self.neatline * k).astype(np.int32)], 1)
        cv2.fillPoly(b, [(corners.reshape(-1, 2) * k).astype(np.int32)], 1)
        return float((a & b).sum()) / max(1, a.sum())

    def register(self, color):
        """Homographie pixels de la carte du jour → pixels de la référence, ou (None, nb de correspondances).
        ORB d'abord (rapide) ; en cas d'échec, SIFT (plus robuste aux différences de tirage)."""
        img = self.prep(color)
        kp, des = self.orb.detectAndCompute(img, None)
        H, n = self._match(kp, des, self.kp, self.des, cv2.NORM_HAMMING, MIN_INLIERS)
        if H is not None:
            return H, n
        if self._sift_ref is None:
            self._sift_ref = self.sift.detectAndCompute(self.prep_ref, None)
        kp2, des2 = self.sift.detectAndCompute(img, None)
        H, n2 = self._match(kp2, des2, *self._sift_ref, cv2.NORM_L2, 100)
        return H, (n2 if H is not None else max(n, n2))


# ---------------------------------------------------------------- reprojection
def merc(lat, lon):
    x = np.radians(lon) * 6378137.0
    y = np.log(np.tan(np.pi / 4 + np.radians(lat) / 2)) * 6378137.0
    return x, y


def inv_merc(x, y):
    return np.degrees(2 * np.arctan(np.exp(y / 6378137.0)) - np.pi / 2), np.degrees(x / 6378137.0)


class Warper:
    """Grille Web Mercator couvrant le cadre de la carte de référence (construite par make_warper)."""

    def _invert(self, px, py):
        """Pixel de la référence → (lat, lon), par inversion de l'affine puis Newton sur la LCC."""
        f, A = self._f, self.A
        lx, ly = np.linalg.solve(A[:2, :].T, np.array([px, py]) - A[2, :])
        lat, lon, d = f["lat0"], f["lon0"], 1e-4
        args = (f["p1"], f["p2"], f["lat0"], f["lon0"], f.get("kind", "lcc"))
        for _ in range(30):
            x, y = lcc([lat], [lon], *args)
            xa, ya = lcc([lat + d], [lon], *args)
            xb, yb = lcc([lat], [lon + d], *args)
            J = np.array([[(xa[0] - x[0]) / d, (xb[0] - x[0]) / d], [(ya[0] - y[0]) / d, (yb[0] - y[0]) / d]])
            step = np.linalg.solve(J, np.array([x[0] - lx, y[0] - ly]))
            lat, lon = lat - step[0], lon - step[1]
            if abs(step).max() < 1e-9:
                break
        return float(lat), float(lon)

    def warp(self, color, H):
        """color : image BGR de la carte du jour ; H : homographie jour → référence. Renvoie BGRA."""
        Hinv = np.linalg.inv(H)
        X, Y = self.ref_x, self.ref_y
        den = Hinv[2, 0] * X + Hinv[2, 1] * Y + Hinv[2, 2]
        mx = ((Hinv[0, 0] * X + Hinv[0, 1] * Y + Hinv[0, 2]) / den).astype(np.float32)
        my = ((Hinv[1, 0] * X + Hinv[1, 1] * Y + Hinv[1, 2]) / den).astype(np.float32)
        out = cv2.remap(color, mx, my, cv2.INTER_LINEAR, borderMode=cv2.BORDER_CONSTANT)
        # transparent hors du cadre de la référence ET hors de l'image scannée
        h, w = color.shape[:2]
        valid = ((mx >= 0) & (mx <= w - 1) & (my >= 0) & (my <= h - 1)).astype(np.uint8) * 255
        return np.dstack([out, self.mask & valid])


def make_warper(ref):
    w = Warper()
    w._f = ref.fit
    w.A = np.array(ref.fit["A"])
    corners = [w._invert(*p) for p in ref.neatline]
    lats, lons = [c[0] for c in corners], [c[1] for c in corners]
    s, n, wl, e = min(lats) - 0.05, max(lats) + 0.05, min(lons) - 0.1, max(lons) + 0.1
    x0, y1 = merc(n, wl)
    x1, y0 = merc(s, e)
    w.W, w.H = int((x1 - x0) / ref.m_per_px), int((y1 - y0) / ref.m_per_px)
    # les bornes publiées doivent correspondre exactement à la grille
    w.bounds = [[round(float(inv_merc(0, y0)[0]), 6), round(wl, 6)], [round(float(inv_merc(0, y1)[0]), 6), round(e, 6)]]
    xs = x0 + (np.arange(w.W) + 0.5) * (x1 - x0) / w.W
    ys = y1 - (np.arange(w.H) + 0.5) * (y1 - y0) / w.H
    X, Y = np.meshgrid(xs, ys)
    lat, lon = inv_merc(X, Y)
    f = ref.fit
    lx, ly = lcc(lat, lon, f["p1"], f["p2"], f["lat0"], f["lon0"], f.get("kind", "lcc"))
    P = np.stack([lx, ly, np.ones_like(lx)], -1) @ w.A
    w.ref_x, w.ref_y = P[..., 0].astype(np.float32), P[..., 1].astype(np.float32)
    # masque du cadre, rastérisé dans l'espace de la référence puis rééchantillonné
    frame = np.zeros(ref.img.shape[:2], np.uint8)
    cv2.fillPoly(frame, [ref.neatline.astype(np.int32)], 255)
    w.mask = cv2.remap(frame, w.ref_x, w.ref_y, cv2.INTER_NEAREST, borderValue=0)
    return w


# ---------------------------------------------------------------- index pour l'application
def index_path(series):
    return ROOT / "data" / f"sitmaps_{series}.js"


def write_index(series, entries):
    """Un fichier d'index par fond de carte ; chacun complète la liste window.WW2_SITMAPS."""
    entries = sorted(entries, key=lambda e: e["date"])
    index_path(series).write_text(
        "// Généré par scripts/sitmaps/build_sitmaps.py — ne pas modifier à la main.\n"
        "// Cartes de situation du 12th Army Group (Library of Congress, domaine public), via Wikimedia Commons.\n"
        "window.WW2_SITMAPS = (window.WW2_SITMAPS || []).concat(" + json.dumps(entries, ensure_ascii=False, indent=0) + ");\n",
        encoding="utf-8")


def read_index(series):
    p = index_path(series)
    if not p.exists():
        return {}
    m = re.search(r"concat\((\[.*\])\);", p.read_text(encoding="utf-8"), re.S)
    return {(e["series"], e["date"]): e for e in json.loads(m.group(1))} if m else {}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--series", default="1M", choices=SERIES)
    ap.add_argument("--from", dest="start", default="1944-06-06")
    ap.add_argument("--to", dest="end", default="1945-07-31")
    ap.add_argument("--step", type=int, default=1)
    ap.add_argument("--dates", default="")
    args = ap.parse_args()

    maps = list_maps()
    print(f"{len(maps)} cartes disponibles sur Commons ({min(maps)} → {max(maps)})")
    if args.dates:
        days = [d.strip() for d in args.dates.split(",") if d.strip() in maps]
    else:
        days = sorted(d for d in maps if args.start <= d <= args.end)[::args.step]

    ref = Reference(args.series)
    warper = make_warper(ref)
    print(f"Calque : {warper.W}×{warper.H} px, emprise {warper.bounds}")

    old = read_index(args.series)

    out_dir = OUT_DIR / args.series
    out_dir.mkdir(parents=True, exist_ok=True)
    done, skipped = 0, []
    for i, day in enumerate(days, 1):
        try:
            path = download(day, maps[day]["title"])
        except Exception as exc:  # noqa: BLE001
            print(f"   [{i}/{len(days)}] {day} téléchargement impossible : {exc}")
            skipped.append(day)
            continue
        color = load_scan(day, args.series)
        H, inl = ref.register(color)
        if H is None:
            print(f"   [{i}/{len(days)}] {day} ignorée (autre fond de carte, {inl} correspondances)", flush=True)
            skipped.append(day)
            continue
        cov = ref.coverage(H, color.shape)
        if cov < 0.85:  # les feuilles voisines ne dépassent pas ~75 %
            print(f"   [{i}/{len(days)}] {day} ignorée (feuille voisine : ne couvre que {cov:.0%} du cadre)", flush=True)
            skipped.append(day)
            continue
        bgra = warper.warp(color, H)
        f = out_dir / f"{day}.webp"
        # Encodage WebP par OpenCV : l'encodeur de Pillow plante par intermittence sous Windows
        # (« access violation » dans libwebp) sur ces grandes images transparentes.
        ok, buf = cv2.imencode(".webp", bgra, [cv2.IMWRITE_WEBP_QUALITY, 72])
        if not ok:
            raise RuntimeError(f"échec de l'encodage WebP pour {day}")
        f.write_bytes(buf.tobytes())
        old[(args.series, day)] = {
            "date": day, "series": args.series, "label": SERIES[args.series]["label"],
            "file": f"data/sitmaps/{args.series}/{day}.webp", "bounds": warper.bounds,
            "source": maps[day]["page"], "inliers": inl,
        }
        done += 1
        print(f"   [{i}/{len(days)}] {day} ✓ {inl} points d'alignement, {f.stat().st_size // 1024} Ko", flush=True)
        if done % 10 == 0:
            write_index(args.series, list(old.values()))
    write_index(args.series, list(old.values()))
    print(f"\n{done} calques créés, {len(skipped)} ignorés : {skipped}")


if __name__ == "__main__":
    main()
