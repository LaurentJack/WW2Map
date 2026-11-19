"""Cale et reprojette les feuilles topographiques GSGS (éditions US Army Map Service, domaine public).

Pour chaque feuille de scripts/gsgs/sheets.json (emprise lue sur l'identifiant AMS imprimé en bas
à droite de la feuille, par ex. « N5000-E820/100x200 ») :
  1. détection automatique du cadre intérieur (neatline.py), contrôlée par les proportions attendues ;
  2. calage : les 4 coins du cadre correspondent aux coins géographiques de la feuille ; on ajuste une
     projection conique conforme locale + transformation affine (résidu affiché : qualité du cadre) ;
  3. reprojection en Web Mercator, découpe au cadre, export WebP dans data/gsgs/<série>/ ;
  4. index data/gsgs.js lu par l'application.

Usage : scripts/.venv/Scripts/python scripts/gsgs/build.py [--only Frankfurt,Rennes] [--check]
"""
import argparse
import json
import math
import sys
from pathlib import Path

import cv2
import numpy as np

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent.parent
CACHE = HERE.parent / ".cache" / "gsgs"
OUT = ROOT / "data" / "gsgs"
sys.path.insert(0, str(HERE))
sys.path.insert(0, str(HERE.parent / "sitmaps"))
from georef import lcc  # noqa: E402
from neatline import detect  # noqa: E402
from frame_ticks import project  # noqa: E402

SERIES = {
    "france250k": {"label": "France 1:250 000 — GSGS 4042 (AMS M561, 1943)", "m_per_px": 90.0},
    "germany250k": {"label": "Allemagne 1:250 000 — GSGS 4346 (AMS M501, 1943-44)", "m_per_px": 90.0},
    "belgium100k": {"label": "Belgique et NE de la France 1:100 000 — GSGS 2364 (révisée 1943)", "m_per_px": 40.0},
}


def merc(lat, lon):
    return np.radians(lon) * 6378137.0, np.log(np.tan(np.pi / 4 + np.radians(lat) / 2)) * 6378137.0


def inv_merc(x, y):
    return np.degrees(2 * np.arctan(np.exp(y / 6378137.0)) - np.pi / 2), np.degrees(x / 6378137.0)


def expected_aspect(e):
    mid = math.radians((e["lat_s"] + e["lat_n"]) / 2)
    return (e["lon_e"] - e["lon_w"]) * math.cos(mid) / (e["lat_n"] - e["lat_s"])


def georef(e, corners):
    """Affine (3x2) : coordonnées LCC locales (km) → pixels, ajustée sur les 4 coins ; + résidu max (px)."""
    p = dict(p1=e["lat_s"], p2=e["lat_n"], lat0=(e["lat_s"] + e["lat_n"]) / 2, lon0=(e["lon_w"] + e["lon_e"]) / 2)
    geo = [(e["lat_n"], e["lon_w"]), (e["lat_n"], e["lon_e"]), (e["lat_s"], e["lon_e"]), (e["lat_s"], e["lon_w"])]
    x, y = lcc([g[0] for g in geo], [g[1] for g in geo], p["p1"], p["p2"], p["lat0"], p["lon0"])
    X = np.column_stack([x, y, np.ones(4)])
    P = np.array(corners, float)
    A, *_ = np.linalg.lstsq(X, P, rcond=None)
    res = float(np.max(np.hypot(*(X @ A - P).T)))
    return A, p, res


def warp(color, e, corners, A, p, m_per_px, mask_px=None):
    margin = 0.01
    s, n, w, ea = e["lat_s"] - margin, e["lat_n"] + margin, e["lon_w"] - margin, e["lon_e"] + margin
    x0, y1 = merc(n, w)
    x1, y0 = merc(s, ea)
    W, H = int((x1 - x0) / m_per_px), int((y1 - y0) / m_per_px)
    xs = x0 + (np.arange(W) + 0.5) * (x1 - x0) / W
    ys = y1 - (np.arange(H) + 0.5) * (y1 - y0) / H
    X, Y = np.meshgrid(xs, ys)
    lat, lon = inv_merc(X, Y)
    lx, ly = lcc(lat, lon, p["p1"], p["p2"], p["lat0"], p["lon0"])
    P = np.stack([lx, ly, np.ones_like(lx)], -1) @ A
    mx, my = P[..., 0].astype(np.float32), P[..., 1].astype(np.float32)
    out = cv2.remap(color, mx, my, cv2.INTER_AREA if m_per_px > 60 else cv2.INTER_LINEAR, borderMode=cv2.BORDER_CONSTANT)
    # masque : intérieur de l'emprise géographique de la feuille
    inside = ((lat >= e["lat_s"]) & (lat <= e["lat_n"]) & (lon >= e["lon_w"]) & (lon <= e["lon_e"])).astype(np.uint8) * 255
    if mask_px:  # partie utile de la feuille (ex. bande blanche « couverte par une autre feuille » exclue)
        src = np.zeros(color.shape[:2], np.uint8)
        cv2.fillPoly(src, [np.round(np.array(mask_px)).astype(np.int32)], 255)
        inside &= cv2.remap(src, mx, my, cv2.INTER_NEAREST, borderMode=cv2.BORDER_CONSTANT)
    bounds = [[float(inv_merc(0, y0)[0]), w], [float(inv_merc(0, y1)[0]), ea]]
    return np.dstack([out, inside]), [[round(bounds[0][0], 6), round(bounds[0][1], 6)], [round(bounds[1][0], 6), round(bounds[1][1], 6)]]


def warp_model(color, model, frame, m_per_px):
    """Reprojection d'une feuille calée sur ses graduations (frame_ticks.py) : le modèle donne directement
    pixel = f(lat, lon) ; le masque est l'intérieur du cadre (quadrilatère en pixels)."""
    s, w, n, ea = model["bbox"]
    margin = 0.005
    s, n, w, ea = s - margin, n + margin, w - margin, ea + margin
    x0, y1 = merc(n, w)
    x1, y0 = merc(s, ea)
    W, H = int((x1 - x0) / m_per_px), int((y1 - y0) / m_per_px)
    xs = x0 + (np.arange(W) + 0.5) * (x1 - x0) / W
    ys = y1 - (np.arange(H) + 0.5) * (y1 - y0) / H
    X, Y = np.meshgrid(xs, ys)
    lat, lon = inv_merc(X, Y)
    A = np.array(model["A"])
    P = (project(lat.ravel(), lon.ravel(), model) @ A).reshape(H, W, 2)
    mx, my = P[..., 0].astype(np.float32), P[..., 1].astype(np.float32)
    out = cv2.remap(color, mx, my, cv2.INTER_AREA if m_per_px > 60 else cv2.INTER_LINEAR, borderMode=cv2.BORDER_CONSTANT)
    src_mask = np.zeros(color.shape[:2], np.uint8)
    cv2.fillPoly(src_mask, [np.round(np.array(frame)).astype(np.int32)], 255)
    inside = cv2.remap(src_mask, mx, my, cv2.INTER_NEAREST, borderMode=cv2.BORDER_CONSTANT)
    bounds = [[round(float(inv_merc(0, y0)[0]), 6), round(w, 6)], [round(float(inv_merc(0, y1)[0]), 6), round(ea, 6)]]
    return np.dstack([out, inside]), bounds


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--only", default="")
    args = ap.parse_args()
    sheets = json.loads((HERE / "sheets.json").read_text(encoding="utf-8"))
    if args.only:
        keep = {s.strip().lower() for s in args.only.split(",")}
        sheets = [s for s in sheets if s["name"].lower() in keep or s["sheet"].lower() in keep]
    idx_path = ROOT / "data" / "gsgs.js"
    index = {}
    if idx_path.exists():
        txt = idx_path.read_text(encoding="utf-8")
        index = {(e["series"], e["sheet"]): e for e in json.loads(txt[txt.index("["):txt.rindex("]") + 1])}
    report = []
    for s in sheets:
        cfg = SERIES[s["series"]]
        if s.get("model"):  # France : calage sur les graduations du cadre (frame_ticks.py)
            m = s["model"]
            color = cv2.imread(str(CACHE / s["cache"]), cv2.IMREAD_COLOR)
            frame = s.get("corners_fix") or s["frame_auto"]
            rgba, bounds = warp_model(color, m, frame, cfg["m_per_px"])
            d = OUT / s["series"]
            d.mkdir(parents=True, exist_ok=True)
            f = d / f"{s['sheet']}.webp"
            ok, buf = cv2.imencode(".webp", rgba, [cv2.IMWRITE_WEBP_QUALITY, 70])
            f.write_bytes(buf.tobytes())
            bb = m["bbox"]
            index[(s["series"], s["sheet"])] = {
                "series": s["series"], "label": cfg["label"], "sheet": s["sheet"], "name": s["name"],
                "file": f"data/gsgs/{s['series']}/{s['sheet']}.webp", "bounds": bounds, "source": s["page"],
                "extent": {"lat_s": bb[0], "lon_w": bb[1], "lat_n": bb[2], "lon_e": bb[3]}, "corners_px": frame,
                "residual_px": m["rms_px"], "km_per_px": m["km_per_px"],
            }
            report.append((s, f"✓ graduations : résidu {m['rms_px']:.1f} px ({m['rms_px'] * m['km_per_px'] * 1000:.0f} m), {f.stat().st_size // 1024} Ko"))
            print(f"   {s['series']:12s} {s['sheet']:6s} {s['name']:22s} {report[-1][1]}", flush=True)
            continue
        e = s.get("extent")
        if not e:
            report.append((s, "emprise inconnue"))
            continue
        color = cv2.imread(str(CACHE / s["cache"]), cv2.IMREAD_COLOR)
        if s.get("corners_px"):  # coins relevés à la main sur les coordonnées imprimées du cadre
            corners, info = s["corners_px"], {"aspect_err": 0.0}
        else:
            corners, info = detect(color, expected_aspect(e), debug=True, zone=s.get("zone_hint"))
        if not corners:
            report.append((s, "cadre non détecté"))
            continue
        A, p, res = georef(e, corners)
        km_px = 1 / math.sqrt(abs(np.linalg.det(A[:2, :])))
        if info["aspect_err"] > 0.03 or res > 25:
            report.append((s, f"cadre douteux (proportions {info['aspect_err']:.1%}, résidu {res:.0f} px)"))
            continue
        rgba, bounds = warp(color, e, corners, A, p, cfg["m_per_px"], s.get("mask_px"))
        d = OUT / s["series"]
        d.mkdir(parents=True, exist_ok=True)
        f = d / f"{s['sheet']}.webp"
        ok, buf = cv2.imencode(".webp", rgba, [cv2.IMWRITE_WEBP_QUALITY, 70])
        f.write_bytes(buf.tobytes())
        index[(s["series"], s["sheet"])] = {
            "series": s["series"], "label": cfg["label"], "sheet": s["sheet"], "name": s["name"],
            "file": f"data/gsgs/{s['series']}/{s['sheet']}.webp", "bounds": bounds, "source": s["page"],
            "extent": e, "corners_px": corners, "residual_px": round(res, 1), "km_per_px": round(km_px, 4),
        }
        report.append((s, f"✓ résidu {res:.1f} px ({res * km_px * 1000:.0f} m), proportions {info['aspect_err']:.1%}, {f.stat().st_size // 1024} Ko"))
        print(f"   {s['series']:12s} {s['sheet']:6s} {s['name']:22s} {report[-1][1]}", flush=True)
    entries = sorted(index.values(), key=lambda e: (e["series"], e["sheet"]))
    idx_path.write_text("// Généré par scripts/gsgs/build.py — feuilles GSGS (US Army Map Service, domaine public) via Wikimedia Commons.\n"
                        "window.WW2_GSGS = " + json.dumps(entries, ensure_ascii=False, indent=0) + ";\n", encoding="utf-8")
    bad = [(s, r) for s, r in report if not r.startswith("✓")]
    print(f"\n{len(report) - len(bad)} feuilles calées, {len(bad)} à revoir :")
    for s, r in bad:
        print(f"   {s['series']} {s['sheet']} {s['name']} : {r}")


if __name__ == "__main__":
    main()
