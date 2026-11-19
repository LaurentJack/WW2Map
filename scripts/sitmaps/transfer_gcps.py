"""Crée automatiquement les points de calage d'un nouveau fond de carte à partir d'un fond déjà calé.

Principe : la carte de référence du nouveau fond et celle d'un fond déjà calé représentent en partie
la même région (routes, rivières, villes). On apparie leurs détails (SIFT + RANSAC, échelles libres),
puis chaque détail apparié reçoit les coordonnées géographiques déduites du fond déjà calé.
Ces points servent ensuite à ajuster la projection du nouveau fond (georef.py), ce qui permet
d'extrapoler au-delà de la zone commune. Le résultat doit être contrôlé sur des villes hors de la zone commune.

Usage :
  scripts/.venv/Scripts/python scripts/sitmaps/transfer_gcps.py <date de référence du nouveau fond> <série nouvelle> \
      <série source> [<série source> ...] [--lat0 49 --lon0 1 --neatline x0,y0,x1,y1]
"""
import argparse
import json
import sys
from pathlib import Path

import cv2
import numpy as np

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import build_sitmaps as b  # noqa: E402


CHANNEL = 2  # 0 bleu, 1 vert, 2 rouge (OpenCV : BGR) ; « gray » = niveaux de gris


def prep(color, small):
    red = cv2.cvtColor(color, cv2.COLOR_BGR2GRAY) if CHANNEL == "gray" else color[..., CHANNEL]
    s = cv2.resize(red, None, fx=small, fy=small, interpolation=cv2.INTER_AREA)
    return cv2.createCLAHE(3.0, (8, 8)).apply(s)


SMALL_T, SMALL_S = 0.5, 0.5  # réductions appliquées à la carte cible et à la carte source


def match(target, source, max_points=250):
    """Points (pixels cible, pixels source) appariés, filtrés par une homographie RANSAC."""
    sift = cv2.SIFT_create(nfeatures=20000)
    kt, dt_ = sift.detectAndCompute(prep(target, SMALL_T), None)
    ks, ds = sift.detectAndCompute(prep(source, SMALL_S), None)
    pairs = cv2.BFMatcher(cv2.NORM_L2).knnMatch(dt_, ds, k=2)
    good = [m for m, n in (p for p in pairs if len(p) == 2) if m.distance < 0.75 * n.distance]
    if len(good) < 30:
        return None, None, len(good)
    pt = np.float32([kt[m.queryIdx].pt for m in good]) / SMALL_T
    ps = np.float32([ks[m.trainIdx].pt for m in good]) / SMALL_S
    H, mask = cv2.findHomography(pt, ps, cv2.RANSAC, 8.0, maxIters=20000)
    if H is None:
        return None, None, 0
    keep = mask.ravel().astype(bool)
    pt, ps = pt[keep], ps[keep]
    # répartir les points : un par case d'une grille 12×12 sur la carte cible
    h, w = target.shape[:2]
    cells = {}
    for a, c in zip(pt, ps):
        cells.setdefault((int(a[0] * 12 / w), int(a[1] * 12 / h)), (a, c))
    sel = list(cells.values())[:max_points]
    return np.float32([a for a, _ in sel]), np.float32([c for _, c in sel]), int(keep.sum())


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("ref_date")
    ap.add_argument("series")
    ap.add_argument("sources", nargs="+")
    ap.add_argument("--lat0", type=float, default=48.5)
    ap.add_argument("--lon0", type=float, default=1.0)
    ap.add_argument("--neatline", default="")
    ap.add_argument("--label", default="")
    ap.add_argument("--scale-target", type=float, default=0.5, help="réduction de la carte cible (1 = pleine résolution)")
    ap.add_argument("--scale-source", type=float, default=0.5, help="réduction des cartes sources")
    ap.add_argument("--channel", default="2", help="canal utilisé pour l'appariement : 0, 1, 2 ou gray")
    args = ap.parse_args()
    global CHANNEL, SMALL_T, SMALL_S
    SMALL_T, SMALL_S = args.scale_target, args.scale_source
    CHANNEL = "gray" if args.channel == "gray" else int(args.channel)

    maps = b.list_maps()
    target = b.load_scan(args.ref_date, args.series)
    points = []
    for src in args.sources:
        cfg = json.loads(b.SERIES[src]["gcps"].read_text(encoding="utf-8"))
        fit = json.loads(b.SERIES[src]["gcps"].with_suffix(".fit.json").read_text(encoding="utf-8"))
        source = b.load_scan(cfg["reference_date"], src)
        pt, ps, n = match(target, source)
        if pt is None or n < 60:
            # trop peu de correspondances : appariement probablement fortuit, source ignorée
            print(f"   {src} : pas assez de correspondances fiables ({n}), source ignorée")
            continue
        w = b.Warper()
        w._f, w.A = fit, np.array(fit["A"])
        poly = np.array(cfg["neatline_px"], np.float32).reshape(-1, 1, 2)
        kept = 0
        for a, c in zip(pt, ps):
            if cv2.pointPolygonTest(poly, (float(c[0]), float(c[1])), False) < 0:
                continue  # hors du cadre calé de la source
            lat, lon = w._invert(float(c[0]), float(c[1]))
            points.append({"name": f"auto:{src}", "px": [round(float(a[0]), 1), round(float(a[1]), 1)],
                           "lat": round(lat, 5), "lon": round(lon, 5), "weight": 0.5})
            kept += 1
        print(f"   {src} : {n} correspondances cohérentes, {kept} points de calage retenus")
    h, wd = target.shape[:2]
    if args.neatline:
        x0, y0, x1, y1 = map(int, args.neatline.split(","))
        neat = [[x0, y0], [x1, y0], [x1, y1], [x0, y1]]
    else:
        neat = [[0, 0], [wd, 0], [wd, h], [0, h]]
    out = {
        "description": f"Points de calage créés automatiquement par transfer_gcps.py depuis {', '.join(args.sources)}. {args.label}",
        "reference_date": args.ref_date, "reference_width": wd, "lat0": args.lat0, "lon0": args.lon0,
        "projection": "Lambert conique conforme (« Europe (Air) Conical Orthomorphic »)",
        "points": points, "neatline_px": neat,
    }
    path = HERE / f"gcps_{args.series}.json"
    path.write_text(json.dumps(out, ensure_ascii=False, indent=1), encoding="utf-8")
    print(f"{len(points)} points écrits dans {path.name}")


if __name__ == "__main__":
    main()
