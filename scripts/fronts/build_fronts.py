"""Extrait la ligne de front de chaque carte de situation calée et écrit data/fronts.js.

Usage : scripts/.venv/Scripts/python scripts/fronts/build_fronts.py [--jobs 6] [--only 1944-12-24] [--force]
Résultats intermédiaires (une carte = un fichier) : scripts/.cache/fronts/<série>_<date>.json
"""
import argparse
import json
import sys
from multiprocessing import Pool
from pathlib import Path

import cv2
import numpy as np

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent.parent
CACHE = HERE.parent / ".cache" / "fronts"
sys.path.insert(0, str(HERE))
from extract import extract_front, merc_to_latlon  # noqa: E402

SKIP_SERIES = {"1400k_occ"}  # après la capitulation : zones d'occupation, plus de front
OVERRIDES = HERE / "overrides.json"  # corrections manuelles éventuelles (paramètres, zones exclues)


def header_text(line, bounds):
    """Court trait situé dans le bandeau du titre (« SECRET » barré, « COPY NO. » souligné) : pas un front."""
    (s, w), (n, e) = bounds
    lats = [p[0] for p in line]; lons = [p[1] for p in line]
    top = min(lats) > n - 0.10 * (n - s)
    small = (max(lons) - min(lons)) < 0.10 * (e - w) and (max(lats) - min(lats)) < 0.05 * (n - s)
    return top and small


def entries():
    out = []
    for f in sorted((ROOT / "data").glob("sitmaps_*.js")):
        t = f.read_text(encoding="utf-8")
        out += json.loads(t[t.index("concat(") + 7:t.rindex(")")])
    return [e for e in out if e["series"] not in SKIP_SERIES]


def job(args):
    e, ov, force = args
    key = f"{e['series']}_{e['date']}"
    cf = CACHE / f"{key}.json"
    if cf.exists() and not force:
        return key, "cache"
    keep, rej, info = extract_front(ROOT / e["file"], ov.get("params"))
    lines = []
    for p in keep:
        a = np.array(p)[:, ::-1].reshape(-1, 1, 2).astype(np.float32)
        s = cv2.approxPolyDP(a, 1.2, False).reshape(-1, 2)
        lat, lon = merc_to_latlon(s[:, 1], s[:, 0], e["bounds"], info["shape"])
        pts = [[round(float(la), 4), round(float(lo), 4)] for la, lo in zip(lat, lon)]
        bad = False
        for x0, y0, x1, y1 in ov.get("exclude", []):  # rectangles lon/lat exclus
            if all(x0 <= q[1] <= x1 and y0 <= q[0] <= y1 for q in pts):
                bad = True
        if not bad and len(pts) >= 2:
            lines.append(pts)
    cf.write_text(json.dumps({"date": e["date"], "series": e["series"], "W0": info["W0"], "lines": lines}), encoding="utf-8")
    return key, f"{len(lines)} traits"


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--jobs", type=int, default=6)
    ap.add_argument("--only", default="")
    ap.add_argument("--force", action="store_true")
    a = ap.parse_args()
    CACHE.mkdir(parents=True, exist_ok=True)
    ovs = json.loads(OVERRIDES.read_text(encoding="utf-8")) if OVERRIDES.exists() else {}
    E = entries()
    only = {x for x in a.only.split(",") if x}
    todo = [(e, ovs.get(f"{e['series']}_{e['date']}", {}), a.force or bool(only)) for e in E if not only or e["date"] in only or f"{e['series']}_{e['date']}" in only]
    with Pool(a.jobs) as pool:
        for i, (k, msg) in enumerate(pool.imap_unordered(job, todo), 1):
            print(f"{i}/{len(todo)} {k} {msg}", flush=True)
    res = []
    for e in E:
        cf = CACHE / f"{e['series']}_{e['date']}.json"
        if cf.exists():
            d = json.loads(cf.read_text(encoding="utf-8"))
            if ovs.get(f"{e['series']}_{e['date']}", {}).get("drop"):
                continue
            lines = [ln for ln in d["lines"] if not header_text(ln, e["bounds"])]
            if lines:
                res.append({"date": d["date"], "series": d["series"], "lines": lines})
    res.sort(key=lambda r: (r["date"], r["series"]))
    (ROOT / "data" / "fronts.js").write_text(
        "// Généré par scripts/fronts/build_fronts.py — lignes de front extraites automatiquement des cartes de situation\n"
        "// du 12th Army Group (domaine public). Vectorisation automatique : tracé à ±1–2 km, possibles lacunes.\n"
        "window.WW2_FRONTS = " + json.dumps(res, separators=(",", ":")) + ";\n", encoding="utf-8")
    print(f"{len(res)} cartes avec front → data/fronts.js")


if __name__ == "__main__":
    main()
