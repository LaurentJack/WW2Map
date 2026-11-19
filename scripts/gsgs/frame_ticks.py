"""Calage des feuilles France 1:250 000 (GSGS 4042) sur les graduations d'une minute du cadre.

Le cadre de ces feuilles est un rectangle du quadrillage Lambert, pas un méridien ni un parallèle : chaque
graduation ne donne donc qu'une coordonnée (longitude en haut et en bas, latitude à gauche et à droite).
  1. minute_bars.py relève les transitions de minute sur les 4 bords ;
  2. on les numérote d'après l'emprise approximative (identifiant AMS, juste à ±6′ près), corrigée par
     "tick_corr" : décalage en minutes lu sur une étiquette imprimée (« 1°30′ », « 47°0′ »…) en haut et à gauche ;
  3. ajustement conique conforme + affine sur ces points partiels (l'autre coordonnée est résolue par
     itérations) ; la numérotation des bords bas et droit est déduite du premier ajustement ;
  4. le modèle est écrit dans sheets.json ("model") et utilisé par build.py.

Usage : scripts/.venv/Scripts/python scripts/gsgs/frame_ticks.py [--only 14,24]
"""
import argparse
import json
import math
import sys
from pathlib import Path

import cv2
import numpy as np

HERE = Path(__file__).resolve().parent
CACHE = HERE.parent / ".cache" / "gsgs"
sys.path.insert(0, str(HERE))
sys.path.insert(0, str(HERE.parent / "sitmaps"))
from georef import lcc  # noqa: E402
from minute_bars import edge_minutes_v3 as edge_minutes  # noqa: E402

PARIS = 2.33722917


def numbering(P, c0, c1, v0, v1):
    L = np.hypot(*np.subtract(c1, c0))
    u = np.subtract(c1, c0) / L
    t = ((P - np.array(c0)) @ u) / L
    v = (v0 + t * (v1 - v0)) * 60
    j = np.arange(len(P))
    sgn = 1 if v[-1] > v[0] else -1
    m0 = np.round(np.median(v - sgn * j))
    return m0 + sgn * j, t


def project(lat, lon, p):
    """Variables explicatives du modèle : [x, y, 1] (affine) ou + termes quadratiques (feuille déformée)."""
    x, y = lcc(lat, lon, p["p1"], p["p2"], p["lat0"], p["lon0"])
    x, y = np.atleast_1d(x), np.atleast_1d(y)
    cols = [x, y, np.ones(np.size(x))]
    if p.get("order", 1) == 2:
        cols += [x * x / 1e3, x * y / 1e3, y * y / 1e3]
    return np.column_stack(cols)


def solve(lat, lon, P, w, p, A=None, iters=10, init=None, fit_A=True, diag=False):
    """lat/lon : NaN pour la coordonnée inconnue. Retourne A (3x2), lat/lon complétées, résidus."""
    kl, ko = np.isnan(lat), np.isnan(lon)
    lat, lon = np.where(kl, init[0], lat), np.where(ko, init[1], lon)
    if A is None:
        raise ValueError("A initial requis")
    for _ in range(iters):
        # compléter la coordonnée manquante : Newton 1D sur la distance pixel
        for _ in range(3):
            for miss, h in ((kl, 1e-4), (ko, 1e-4)):
                if not miss.any():
                    continue
                la, lo = lat[miss], lon[miss]
                f = project(la, lo, p) @ A
                if miss is kl:
                    df = (project(la + h, lo, p) @ A - f) / h
                else:
                    df = (project(la, lo + h, p) @ A - f) / h
                step = np.sum((P[miss] - f) * df, 1) / np.sum(df * df, 1)
                if miss is kl:
                    lat[miss] = la + step
                else:
                    lon[miss] = lo + step
        if not fit_A:
            continue
        X = project(lat, lon, p)
        sw = np.sqrt(w)[:, None]
        if diag:  # quadrillage Lambert aligné sur le cadre : x_px = a·x + c, y_px = b·y + d
            ax, *_ = np.linalg.lstsq(X[:, [0, 2]] * sw, P[:, 0] * sw[:, 0], rcond=None)
            ay, *_ = np.linalg.lstsq(X[:, [1, 2]] * sw, P[:, 1] * sw[:, 0], rcond=None)
            A = np.array([[ax[0], 0.0], [0.0, ay[0]], [ax[1], ay[1]]])
        else:
            A, *_ = np.linalg.lstsq(X * sw, P * sw, rcond=None)
    res = project(lat, lon, p) @ A - P
    # résidu utile : composante perpendiculaire au méridien/parallèle n'est pas séparable simplement ;
    # la composante le long du bord est l'erreur sur la coordonnée connue
    return A, lat, lon, res


def calibrate(s, verbose=True):
    e = s["extent_approx"]
    c = s.get("corners_fix") or s["frame_auto"]
    corr = s.get("tick_corr", {})
    g = cv2.imread(str(CACHE / s["cache"]), cv2.IMREAD_GRAYSCALE)
    wpx = np.hypot(c[1][0] - c[0][0], c[1][1] - c[0][1])
    hpx = np.hypot(c[3][0] - c[0][0], c[3][1] - c[0][1])
    ppm_lon = wpx / ((e["lon_e"] - e["lon_w"]) * 60)
    ppm_lat = hpx / ((e["lat_n"] - e["lat_s"]) * 60)
    edges = {"top": (c[0], c[1], ppm_lon, "lon", e["lon_w"], e["lon_e"]),
             "bottom": (c[3], c[2], ppm_lon, "lon", e["lon_w"], e["lon_e"]),
             "left": (c[0], c[3], ppm_lat, "lat", e["lat_n"], e["lat_s"]),
             "right": (c[1], c[2], ppm_lat, "lat", e["lat_n"], e["lat_s"])}
    det = {}
    for name, (a, b, ppm, kind, v0, v1) in edges.items():
        r = edge_minutes(g, a, b, ppm)
        m, t = numbering(r["points"], a, b, v0, v1)
        keep = (t > -0.002) & (t < 1.002)
        det[name] = (r["points"][keep], m[keep], kind, r)
    p = dict(p1=e["lat_s"], p2=e["lat_n"], lat0=(e["lat_s"] + e["lat_n"]) / 2, lon0=PARIS)
    # affine initiale : coins du cadre ↔ coins de l'emprise approximative
    geo = [(e["lat_n"], e["lon_w"]), (e["lat_n"], e["lon_e"]), (e["lat_s"], e["lon_e"]), (e["lat_s"], e["lon_w"])]
    X0 = project(np.array([q[0] for q in geo]), np.array([q[1] for q in geo]), p)
    C = np.array(c, float)
    ax, *_ = np.linalg.lstsq(X0[:, [0, 2]], C[:, 0], rcond=None)
    ay, *_ = np.linalg.lstsq(X0[:, [1, 2]], C[:, 1], rcond=None)
    A = np.array([[ax[0], 0.0], [0.0, ay[0]], [ax[1], ay[1]]])

    side_init = {"top": e["lat_n"], "bottom": e["lat_s"], "left": e["lon_w"], "right": e["lon_e"]}

    def gather(names, shifts):
        L, O, P, W, tag, I = [], [], [], [], [], []
        for n in names:
            pts, m, kind, _ = det[n]
            v = (m + shifts.get(n, 0)) / 60.0
            for q, val in zip(pts, v):
                L.append(np.nan if kind == "lon" else val)
                O.append(val if kind == "lon" else np.nan)
                P.append(q); W.append(1.0); tag.append(n); I.append(side_init[n])
        I = np.array(I)
        gather.init = (np.where(np.isnan(L), I, 0), np.where(np.isnan(O), I, 0))
        return np.array(L), np.array(O), np.array(P, float), np.array(W), np.array(tag)

    shifts = {"top": corr.get("top", 0), "left": corr.get("left", 0)}
    # 1er ajustement : bords haut et gauche (numérotation lue sur les étiquettes)
    lat, lon, P, w, tag = gather(["top", "left"], shifts)
    A1, *_ = solve(lat, lon, P, w, p, A, init=gather.init, diag=True)
    # numérotation des bords bas et droit : décalage entier qui colle le mieux au 1er modèle
    for n in ("bottom", "right"):
        if n in corr:  # numérotation lue sur une étiquette du bord
            shifts[n] = corr[n]
            continue
        best = None
        for k in range(-12, 13):
            la, lo, Pn, wn, _ = gather([n], {n: k})
            _, _, _, res = solve(la, lo, Pn, wn, p, A1, iters=3, init=gather.init, fit_A=False)
            # pas de ré-ajustement de A1 significatif avec iters=1 ? on mesure seulement l'écart
            d = float(np.median(np.hypot(*res.T)))
            if best is None or d < best[0]:
                best = (d, k)
        shifts[n] = best[1]
    lat, lon, P, w0, tag = gather(["top", "bottom", "left", "right"], shifts)
    init_all = gather.init

    def final(order, A_start):
        q = dict(p, order=order)
        A_ = A_start if order == 1 else np.vstack([A_start, np.zeros((3, 2))])
        w = w0.copy()
        for _ in range(3):
            A_, la_f, lo_f, res = solve(lat, lon, P, w, q, A_, init=init_all)
            d = np.hypot(*res.T)
            sig = 1.4826 * np.median(d) + 0.5
            w = (d < 4 * sig).astype(float) + 1e-4
        return q, A_, la_f, lo_f, d, w

    p, A, lat_f, lon_f, d, w = final(1, A1)
    rms1 = float(np.sqrt(np.mean(d[w > 0.5] ** 2)))
    if rms1 > 2.5:
        alt = final(2, A)
        rms2 = float(np.sqrt(np.mean(alt[4][alt[5] > 0.5] ** 2)))
        if rms2 < 0.7 * rms1 and (alt[5] > 0.5).sum() >= (w > 0.5).sum() * 0.95:
            p, A, lat_f, lon_f, d, w = alt
    stats = {n: (float(np.sqrt(np.mean(d[(tag == n) & (w > 0.5)] ** 2))), int(((tag == n) & (w > 0.5)).sum())) for n in edges}
    rms = float(np.sqrt(np.mean(d[w > 0.5] ** 2)))
    km_px = 1 / math.sqrt(abs(np.linalg.det(A[:2, :])))
    model = {"kind": "lcc", **{k: (round(v, 8) if isinstance(v, float) else v) for k, v in p.items()}, "A": np.round(A, 6).tolist(),
             "rms_px": round(rms, 2), "km_per_px": round(km_px, 5), "shifts": shifts,
             "bbox": [round(float(np.nanmin(lat_f)), 5), round(float(np.nanmin(lon_f)), 5),
                      round(float(np.nanmax(lat_f)), 5), round(float(np.nanmax(lon_f)), 5)]}
    if verbose:
        print(f"   {s['sheet']:4s} {s['name']:20s} rms {rms:5.2f} px ({rms * km_px * 1000:4.0f} m)  décalages {shifts}  "
              + "  ".join(f"{n} {v[0]:.1f}/{v[1]}" for n, v in stats.items()), flush=True)
    return model


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--only", default="")
    ap.add_argument("--dry", action="store_true")
    args = ap.parse_args()
    path = HERE / "sheets.json"
    sheets = json.loads(path.read_text(encoding="utf-8"))
    keep = {x.strip() for x in args.only.split(",") if x.strip()}
    for s in sheets:
        if s["series"] != "france250k" or "tick_corr" not in s or (keep and s["sheet"] not in keep):
            continue
        s["model"] = calibrate(s)
    if not args.dry:
        path.write_text(json.dumps(sheets, ensure_ascii=False, indent=1), encoding="utf-8")


if __name__ == "__main__":
    main()
