"""Calage des feuilles France 1:100 000 (GSGS 4249, AMS M661) sur leur quadrillage kilométrique.

Le cadre de ces feuilles est un rectangle du quadrillage Lambert zone I (NTF, méridien de Paris, EPSG:27561),
tracé en noir tous les kilomètres et numéroté en violet. Pour chaque feuille :
  1. détection des lignes noires verticales et horizontales (profils par bandes, période ≈ 1 km) ;
  2. numérotation : la première ligne verticale du cadre vaut "e0" km, la première horizontale "n0" km
     (lus sur les étiquettes violettes du coin haut-gauche, sheets100k.json) ;
  3. intersections → ajustement polynomial de degré 2 (E, N) → pixel, robuste aux déformations du scan ;
  4. reprojection en Web Mercator (pyproj : WGS84 → Lambert I), masque = intérieur du cadre.

Usage : scripts/.venv/Scripts/python scripts/gsgs/grid100k.py [--only 6F] [--debug DIR]
"""
import argparse
import json
import math
import sys
from pathlib import Path

import cv2
import numpy as np
from pyproj import Transformer

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent.parent
RAW = HERE.parent / ".cache" / "gsgs" / "raw100k"
OUT = ROOT / "data" / "gsgs" / "normandy100k"
SERIES = "normandy100k"
LABEL = "Normandie 1:100 000 — GSGS 4249 (AMS M661, 1943)"
M_PER_PX = 25.0
# quadrillage noir : Lambert zone I (NTF, Paris) à l'ouest, « Nord de Guerre » (ATF) à l'est de la Normandie
CRS = {"L1": "EPSG:27561", "NDG": "EPSG:27500"}
FWD = {k: Transformer.from_crs("EPSG:4326", v, always_xy=True) for k, v in CRS.items()}
INV = {k: Transformer.from_crs(v, "EPSG:4326", always_xy=True) for k, v in CRS.items()}


def line_mask(bgr):
    hsv = cv2.cvtColor(bgr, cv2.COLOR_BGR2HSV)
    return ((hsv[..., 2] < 150) & (hsv[..., 1] < 90)).astype(np.uint8)


def peaks_1d(prof, period, x0=None):
    """Positions des maxima d'un profil quasi périodique (une ligne de grille par période)."""
    n = len(prof)
    sm = cv2.GaussianBlur(prof.astype(np.float32)[None], (0, 0), 1.2)[0]
    k = np.arange(n)
    best = None
    for P in np.linspace(period * 0.93, period * 1.07, 141):
        c, s = np.cos(2 * np.pi * k / P), np.sin(2 * np.pi * k / P)
        a = np.hypot(sm @ c, sm @ s)
        if best is None or a > best[0]:
            best = (a, P, math.atan2(sm @ s, sm @ c))
    _, P, ph = best
    first = (ph / (2 * np.pi)) * P % P
    out = []
    x = first
    while x < n:
        lo, hi = int(max(0, x - P * 0.3)), int(min(n, x + P * 0.3))
        if hi > lo:
            j = lo + int(np.argmax(sm[lo:hi]))
            # sous-pixel (parabole)
            if 0 < j < n - 1:
                y0, y1, y2 = sm[j - 1], sm[j], sm[j + 1]
                d = (y0 - y2) / (2 * (y0 - 2 * y1 + y2) + 1e-9)
                out.append((j + float(np.clip(d, -0.5, 0.5)), float(sm[j])))
        x += P
    return out, P


def detect_lines(mask, frame, axis, period, nbands=16):
    """Lignes de grille parallèles à un axe (axis=0 : verticales, x = f(y)) dans le cadre.
    Retourne {indice: (a, b)} avec x = a + b*y (ou y = a + b*x), indice 0 = bord gauche/haut du cadre."""
    x0, y0, x1, y1 = frame
    pts = []
    span = (y0, y1) if axis == 0 else (x0, x1)
    edges = np.linspace(span[0] + 20, span[1] - 20, nbands + 1).astype(int)
    for b0, b1 in zip(edges[:-1], edges[1:]):
        if axis == 0:
            prof = mask[b0:b1, x0 - 15:x1 + 15].sum(0)
            off = x0 - 15
        else:
            prof = mask[y0 - 15:y1 + 15, b0:b1].sum(1)
            off = y0 - 15
        pk, P = peaks_1d(prof, period)
        thr = np.percentile([v for _, v in pk], 30) * 0.5
        for p, v in pk:
            if v > thr:
                pts.append(((b0 + b1) / 2, off + p))
    pts = np.array(pts)
    ref = x0 if axis == 0 else y0
    # numérotation globale (le quadrillage a été redressé au préalable)
    idx = np.round((pts[:, 1] - ref) / period).astype(int)
    lines = {}
    for k in np.unique(idx):
        sel = pts[idx == k]
        if len(sel) < nbands * 0.5:
            continue
        A = np.column_stack([np.ones(len(sel)), sel[:, 0]])
        w = np.ones(len(sel))
        for _ in range(3):
            c, *_ = np.linalg.lstsq(A * w[:, None], sel[:, 1] * w, rcond=None)
            r = sel[:, 1] - A @ c
            w = (np.abs(r) < max(2.0, 3 * np.median(np.abs(r)))).astype(float)
        lines[int(k)] = (float(c[0]), float(c[1]), float(np.sqrt(np.mean(r[w > 0] ** 2))) if w.any() else 99.0)
    return lines


def poly2(E, N):
    E, N = np.asarray(E, float), np.asarray(N, float)
    return np.column_stack([np.ones_like(E), E, N, E * E, E * N, N * N])


def calibrate(s, debug=None, pkm=82.7):
    """Lignes de grille détectées sur toute la carte ; on ne garde que celles présentes sur presque toute la
    hauteur/largeur (le quadrillage s'arrête au cadre). Indice 0 = ligne la plus proche du coin haut-gauche."""
    bgr = cv2.imread(str(RAW / s["file"]))
    h, w = bgr.shape[:2]
    mask = line_mask(bgr)
    # "fix" : décalage d'indice constaté en comparant la numérotation du modèle aux numéros imprimés
    # en marge (le trait du cadre peut prendre la place de la première ligne)
    tx, ty = s["tl_px"]
    region = (int(max(tx - 30, w * s.get("left_frac", 0))), int(ty - 30), int(w * s.get("right_frac", 0.86)), int(h - 40))
    nb = 16
    # inclinaison du quadrillage (Nord de Guerre : ≈ 4° par rapport au cadre) : angle qui rend les profils
    # de colonnes et de lignes les plus contrastés (recherche sur une version réduite)
    x0r, y0r, x1r, y1r = region
    small = cv2.resize(mask[y0r:y1r, x0r:x1r].astype(np.float32), None, fx=0.25, fy=0.25, interpolation=cv2.INTER_AREA)
    sh, sw = small.shape
    def sharp(a):
        R = cv2.getRotationMatrix2D((sw / 2, sh / 2), a, 1.0)
        r = cv2.warpAffine(small, R, (sw, sh))
        c, l = r.sum(0), r.sum(1)
        return float(np.var(np.diff(c)) + np.var(np.diff(l)))
    angs = np.arange(-6, 6.01, 0.1)
    best = max(angs, key=sharp)
    fine = np.arange(best - 0.12, best + 0.121, 0.02)
    best = max(fine, key=sharp)
    theta = -float(best)  # convention : Rm = rotation de -theta
    Rm = cv2.getRotationMatrix2D((float(tx), float(ty)), -theta, 1.0)  # autour du coin : la zone utile reste en place
    Ri = cv2.invertAffineTransform(Rm)
    if abs(theta) > 0.02:
        mask = (cv2.warpAffine(mask * 255, Rm, (w, h), flags=cv2.INTER_LINEAR) > 100).astype(np.uint8)
        tx, ty = (Rm @ [tx, ty, 1]).tolist()
    else:
        Rm = Ri = np.array([[1, 0, 0], [0, 1, 0]], float)
    V = detect_lines(mask, region, 0, pkm, nbands=nb)
    H = detect_lines(mask, region, 1, pkm, nbands=nb)
    def support(lines, axis):
        out = {}
        for k, (a_, b_, r) in lines.items():
            out[k] = (a_, b_, r)
        return out
    # renumérotation de proche en proche : l'écartement réel (px/km) varie d'une feuille à l'autre (81,5–83) ;
    # un pas fixe ferait dériver la numérotation d'une ligne sur 70 km
    def renum(lines, ref, other_ref):
        L = sorted(((a_ + b_ * other_ref, a_, b_, r) for a_, b_, r in lines.values() if r < 5.0), key=lambda z: z[0])
        L = [z for z in L if abs(z[0] - ref) >= 14]  # trait épais du cadre
        if len(L) < 3:
            return {}, pkm
        gaps = np.diff([z[0] for z in L])
        step = float(np.median(gaps[(gaps > 0.85 * pkm) & (gaps < 1.15 * pkm)]))
        # élimine les lignes parasites (écart ≈ demi-pas) : on garde la mieux ajustée
        keep = [L[0]]
        for z in L[1:]:
            g = (z[0] - keep[-1][0]) / step
            if g < 0.6:
                if z[3] < keep[-1][3]:
                    keep[-1] = z
                continue
            keep.append(z)
        res = {}
        k = int(round((keep[0][0] - ref) / step))
        res[k] = keep[0][1:]
        for z0, z in zip(keep[:-1], keep[1:]):
            k += int(round((z[0] - z0[0]) / step))
            res[k] = z[1:]
        return res, step
    V, sv = renum(V, tx, ty)
    H, sh_ = renum(H, ty, tx)
    pkm = (sv + sh_) / 2
    pts, geo = [], []
    for i, (a_, b_, _) in V.items():
        for j, (c_, d_, _) in H.items():
            y = (c_ + d_ * a_) / (1 - d_ * b_)
            x = a_ + b_ * y
            pts.append((x, y))
            geo.append((s["e0"] + s.get("fix", [0, 0])[0] + i, s["n0"] + s.get("fix", [0, 0])[1] - j))
    pts, geo = np.array(pts), np.array(geo, float) * 1000
    if not len(pts):
        raise RuntimeError("aucune intersection")
    # on ne garde que les intersections où les deux lignes sont réellement tracées (contrôle local du masque)
    ok = []
    for (x, y) in pts:
        xi, yi = int(round(x)), int(round(y))
        if 3 <= xi < w - 3 and 3 <= yi < h - 3:
            win = mask[yi - 3:yi + 4, xi - 3:xi + 4]
            ok.append(win[3, :].sum() + win[:, 3].sum() >= 6)
        else:
            ok.append(False)
    ok = np.array(ok, bool)
    pts, geo = pts[ok], geo[ok]
    pts = np.column_stack([pts, np.ones(len(pts))]) @ Ri.T  # retour aux pixels du scan d'origine
    E0, N0 = geo[:, 0].mean(), geo[:, 1].mean()
    X = poly2((geo[:, 0] - E0) / 1e4, (geo[:, 1] - N0) / 1e4)
    wgt = np.ones(len(pts))
    for _ in range(5):
        C, *_ = np.linalg.lstsq(X * wgt[:, None], pts * wgt[:, None], rcond=None)
        r = np.hypot(*(X @ C - pts).T)
        wgt = (r < max(1.5, 4 * np.median(r))).astype(float)
    rms = float(np.sqrt(np.mean(r[wgt > 0] ** 2)))
    # correction locale : résidus aux nœuds du quadrillage (1 par km), lissés et complétés par diffusion,
    # interpolés bilinéairement au moment de la reprojection (pliures et déformations du papier)
    gi = np.round(geo / 1000).astype(int)
    emin, nmin = gi[:, 0].min(), gi[:, 1].min()
    GW, GH = gi[:, 0].max() - emin + 1, gi[:, 1].max() - nmin + 1
    RX = np.full((GH, GW), np.nan, np.float32); RY = RX.copy()
    dres = pts - X @ C
    for (e, n), (dx, dy), g in zip(gi, dres, wgt):
        if g:
            RX[n - nmin, e - emin], RY[n - nmin, e - emin] = dx, dy
    def fill(A):
        known = ~np.isnan(A)
        B = np.where(known, A, 0).astype(np.float32)
        Kn = known.astype(np.float32)
        med = cv2.medianBlur(np.where(known, A, 0).astype(np.float32), 3)
        B = np.where(known, med * 0 + B, 0)
        for _ in range(200):
            num = cv2.blur(B * Kn, (3, 3)); den = cv2.blur(Kn, (3, 3))
            upd = np.where(den > 0, num / np.maximum(den, 1e-6), 0)
            B = np.where(known, B, upd)
            Kn = np.maximum(Kn, (den > 0).astype(np.float32) * 0.999)
        return B
    RXf, RYf = fill(RX), fill(RY)
    after = np.hypot(*(dres[wgt > 0] - np.column_stack([RXf[gi[wgt > 0, 1] - nmin, gi[wgt > 0, 0] - emin],
                                                        RYf[gi[wgt > 0, 1] - nmin, gi[wgt > 0, 0] - emin]])).T)
    good = geo[wgt > 0] / 1000
    ext = [float(good[:, 0].min()), float(good[:, 1].max()), float(good[:, 0].max()), float(good[:, 1].min())]
    # zone de validité : enveloppe convexe des intersections retenues, élargie de 0,6 km
    hull = cv2.convexHull(np.round(geo[wgt > 0] / 100).astype(np.int32))  # unité : 100 m
    model_hull = hull.reshape(-1, 2).tolist()
    model = {"region": [int(v) for v in region], "hull_hm": model_hull, "mesh": {"emin": int(emin), "nmin": int(nmin), "RX": RXf, "RY": RYf}, "rms_raw_px": round(rms, 2), "rms_mesh_px": round(float(np.sqrt(np.mean(after ** 2))), 2),
             "theta": round(theta, 3), "E0": E0, "N0": N0, "C": C.tolist(), "rms_px": round(rms, 2), "n": int(wgt.sum()),
             "nv": len(V), "nh": len(H), "pkm": pkm, "ext_km": ext}
    if debug:
        v = (bgr * 0.6 + 100).astype(np.uint8)
        P = X @ C
        for (x, y), (qx, qy), g in zip(P, pts, wgt):
            cv2.circle(v, (int(qx), int(qy)), 6, (0, 0, 255) if g else (255, 0, 0), 3)
            cv2.line(v, (int(qx), int(qy)), (int(qx + 10 * (x - qx)), int(qy + 10 * (y - qy))), (0, 140, 0), 4)
        cv2.imwrite(str(Path(debug) / f"g100_{s['sheet']}.jpg"), cv2.resize(v, None, fx=0.2, fy=0.2))
    return bgr, model


def warp(bgr, s, m):
    e0, n0, e1, n1 = (v * 1000 for v in m["ext_km"])
    corners = [INV[s["crs"]].transform(x, y) for x, y in ((e0, n0), (e1, n0), (e1, n1), (e0, n1))]
    lons, lats = [c[0] for c in corners], [c[1] for c in corners]
    s_, n_, w_, ea = min(lats) - 0.003, max(lats) + 0.003, min(lons) - 0.003, max(lons) + 0.003
    merc = lambda la, lo: (math.radians(lo) * 6378137.0, math.log(math.tan(math.pi / 4 + math.radians(la) / 2)) * 6378137.0)
    x0, y1 = merc(n_, w_)
    x1, y0 = merc(s_, ea)
    W, Hh = int((x1 - x0) / M_PER_PX), int((y1 - y0) / M_PER_PX)
    xs = x0 + (np.arange(W) + 0.5) * (x1 - x0) / W
    ys = y1 - (np.arange(Hh) + 0.5) * (y1 - y0) / Hh
    X, Y = np.meshgrid(xs, ys)
    lat = np.degrees(2 * np.arctan(np.exp(Y / 6378137.0)) - np.pi / 2)
    lon = np.degrees(X / 6378137.0)
    E, N = FWD[s["crs"]].transform(lon.ravel(), lat.ravel())
    E, N = np.asarray(E), np.asarray(N)
    P = poly2((E - m["E0"]) / 1e4, (N - m["N0"]) / 1e4) @ np.array(m["C"])
    ms = m["mesh"]
    gx = (E / 1000 - ms["emin"]).astype(np.float32).reshape(Hh, W)
    gy = (N / 1000 - ms["nmin"]).astype(np.float32).reshape(Hh, W)
    P[:, 0] += cv2.remap(ms["RX"], gx, gy, cv2.INTER_LINEAR, borderMode=cv2.BORDER_REPLICATE).ravel()
    P[:, 1] += cv2.remap(ms["RY"], gx, gy, cv2.INTER_LINEAR, borderMode=cv2.BORDER_REPLICATE).ravel()
    mx = P[:, 0].reshape(Hh, W).astype(np.float32)
    my = P[:, 1].reshape(Hh, W).astype(np.float32)
    out = cv2.remap(bgr, mx, my, cv2.INTER_AREA, borderMode=cv2.BORDER_CONSTANT)
    hull = np.array(m["hull_hm"], np.int32)
    hx0, hy0 = hull[:, 0].min() - 10, hull[:, 1].min() - 10
    raster = np.zeros((hull[:, 1].max() - hy0 + 11, hull[:, 0].max() - hx0 + 11), np.uint8)
    cv2.fillPoly(raster, [hull - [hx0, hy0]], 255)
    raster = cv2.dilate(raster, cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (13, 13)))  # +0,6 km
    inside = cv2.remap(raster, (E / 100 - hx0).astype(np.float32).reshape(Hh, W), (N / 100 - hy0).astype(np.float32).reshape(Hh, W),
                       cv2.INTER_NEAREST, borderMode=cv2.BORDER_CONSTANT)
    # et jamais hors du cadre de la carte (le pixel source doit tomber dans l'image)
    x0r, y0r, x1r, y1r = m["region"]
    inside[(mx < max(0, x0r)) | (my < max(0, y0r)) | (mx >= min(bgr.shape[1], x1r)) | (my >= min(bgr.shape[0], y1r))] = 0
    bounds = [[round(s_, 6), round(w_, 6)], [round(n_, 6), round(ea, 6)]]
    return np.dstack([out, inside]), bounds


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--only", default="")
    ap.add_argument("--debug", default="")
    a = ap.parse_args()
    sheets = json.loads((HERE / "sheets100k.json").read_text(encoding="utf-8"))
    keep = {x.strip().upper() for x in a.only.split(",") if x.strip()}
    idx_path = ROOT / "data" / "gsgs.js"
    txt = idx_path.read_text(encoding="utf-8")
    index = {(e["series"], e["sheet"]): e for e in json.loads(txt[txt.index("["):txt.rindex("]") + 1])}
    OUT.mkdir(parents=True, exist_ok=True)
    for s in sheets:
        if keep and s["sheet"] not in keep:
            continue
        try:
            bgr, m = calibrate(s, a.debug or None)
        except Exception as ex:  # noqa: BLE001
            print(f"   {s['sheet']:3s} {s['name']:28s} ÉCHEC : {ex}", flush=True)
            continue
        rgba, bounds = warp(bgr, s, m)
        f = OUT / f"{s['sheet']}.webp"
        ok, buf = cv2.imencode(".webp", rgba, [cv2.IMWRITE_WEBP_QUALITY, 72])
        f.write_bytes(buf.tobytes())
        index[(SERIES, s["sheet"])] = {
            "series": SERIES, "label": LABEL, "sheet": s["sheet"], "name": s["name"],
            "file": f"data/gsgs/{SERIES}/{s['sheet']}.webp", "bounds": bounds, "source": s["page"],
            "residual_px": m["rms_px"], "km_per_px": round(1 / m["pkm"], 5),
        }
        print(f"   {s['sheet']:3s} {s['name']:28s} rot {m['theta']:+.2f}°, lignes {m['nv']}×{m['nh']}, {m['n']} intersections, "
              f"résidu {m['rms_px']:.1f} px ({m['rms_px'] / m['pkm'] * 1000:.0f} m), {f.stat().st_size // 1024} Ko", flush=True)
    entries = sorted(index.values(), key=lambda e: (e["series"], e["sheet"]))
    idx_path.write_text("// Généré par scripts/gsgs/build.py et grid100k.py — feuilles GSGS (domaine public).\n"
                        "window.WW2_GSGS = " + json.dumps(entries, ensure_ascii=False, indent=0) + ";\n", encoding="utf-8")


if __name__ == "__main__":
    main()
