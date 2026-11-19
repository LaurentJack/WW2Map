"""Calage (géoréférencement) d'une carte de référence à partir de points de calage.

Modèle : projection conique (sphère) suivie d'une transformation affine (pixel = A · [x, y, 1]).
Par défaut conique conforme de Lambert, dont les parallèles standard sont ajustés par recherche sur grille.
Si le fichier indique "kind": "albers" avec "p1"/"p2", on utilise la conique équivalente d'Albers
avec ces parallèles standard imposés (cas des cartes de 1945 dont la légende les précise).
Usage : python georef.py gcps_1M.json   → affiche les résidus et écrit gcps_1M.fit.json
"""
import json
import math
import sys
from pathlib import Path

import numpy as np

R = 6371.0  # km


def albers(lat, lon, p1, p2, lat0, lon0):
    """Conique équivalente d'Albers sur la sphère → (x, y) en km."""
    f1, f2, f0 = map(math.radians, (p1, p2, lat0))
    n = (math.sin(f1) + math.sin(f2)) / 2
    C = math.cos(f1) ** 2 + 2 * n * math.sin(f1)
    rho0 = R * math.sqrt(C - 2 * n * math.sin(f0)) / n
    lat = np.radians(np.asarray(lat, float))
    th = n * np.radians(np.asarray(lon, float) - lon0)
    rho = R * np.sqrt(C - 2 * n * np.sin(lat)) / n
    return rho * np.sin(th), rho0 - rho * np.cos(th)


def lcc(lat, lon, p1, p2, lat0=50.0, lon0=6.0, kind="lcc"):
    """Projection du fond → (x, y) en km. kind = "lcc" (Lambert conique conforme) ou "albers"."""
    if kind == "albers":
        return albers(lat, lon, p1, p2, lat0, lon0)
    f1, f2, f0 = map(math.radians, (p1, p2, lat0))
    n = math.log(math.cos(f1) / math.cos(f2)) / math.log(math.tan(math.pi / 4 + f2 / 2) / math.tan(math.pi / 4 + f1 / 2)) \
        if abs(p1 - p2) > 1e-6 else math.sin(f1)
    F = math.cos(f1) * math.tan(math.pi / 4 + f1 / 2) ** n / n
    rho0 = R * F / math.tan(math.pi / 4 + f0 / 2) ** n
    lat = np.radians(np.asarray(lat, float))
    dl = np.radians(np.asarray(lon, float) - lon0)
    rho = R * F / np.tan(np.pi / 4 + lat / 2) ** n
    return rho * np.sin(n * dl), rho0 - rho * np.cos(n * dl)


KIND = "lcc"


def _fit_full(lat, lon, P, w, p1, p2, lat0, lon0):
    x, y = lcc(lat, lon, p1, p2, lat0, lon0, KIND)
    X = np.column_stack([x, y, np.ones_like(x)])
    sw = np.sqrt(w)[:, None]
    A, *_ = np.linalg.lstsq(X * sw, P * sw, rcond=None)  # 3x2
    return A, X @ A - P


def fit(points, p1, p2, lat0=50.0, lon0=6.0):
    """Ajuste l'affine. Les points peuvent n'avoir qu'une coordonnée connue (repère de carroyage
    sur un bord de carte qui n'est ni un méridien ni un parallèle) : « lat » seule ou « lon » seule.
    L'autre coordonnée est alors estimée par itérations (point du parallèle/méridien le plus proche)."""
    P = np.array([p["px"] for p in points], float)
    w = np.array([p.get("weight", 1.0) for p in points])
    lat = np.array([p.get("lat", np.nan) for p in points], float)
    lon = np.array([p.get("lon", np.nan) for p in points], float)
    full = ~np.isnan(lat) & ~np.isnan(lon)
    if full.all():
        return _fit_full(lat, lon, P, w, p1, p2, lat0, lon0)
    A, _ = _fit_full(lat[full], lon[full], P[full], w[full], p1, p2, lat0, lon0)
    lat_f, lon_f = lat.copy(), lon.copy()
    for _ in range(8):
        for i in np.where(~full)[0]:
            if np.isnan(lat[i]):   # longitude connue : on cherche la latitude
                cand = np.linspace(40, 58, 1801)
                x, y = lcc(cand, np.full_like(cand, lon[i]), p1, p2, lat0, lon0, KIND)
            else:                  # latitude connue : on cherche la longitude
                cand = np.linspace(-10, 20, 3001)
                x, y = lcc(np.full_like(cand, lat[i]), cand, p1, p2, lat0, lon0, KIND)
            q = np.column_stack([x, y, np.ones_like(x)]) @ A
            k = int(np.argmin(np.hypot(*(q - P[i]).T)))
            if np.isnan(lat[i]):
                lat_f[i] = cand[k]
            else:
                lon_f[i] = cand[k]
        A, res = _fit_full(lat_f, lon_f, P, w, p1, p2, lat0, lon0)
    return A, res


def main():
    path = Path(sys.argv[1])
    cfg = json.loads(path.read_text(encoding="utf-8"))
    pts = cfg["points"]
    lat0, lon0 = cfg.get("lat0", 50.0), cfg.get("lon0", 6.0)
    global KIND
    KIND = cfg.get("kind", "lcc")
    if KIND == "albers":
        grid = [(cfg["p1"], cfg["p2"])]
    else:
        grid = [(a, b) for a in np.arange(20, 56, 2.0) for b in np.arange(a, 66, 2.0)]
    best = None
    for p1, p2 in grid:
        if True:
            A, res = fit(pts, p1, p2, lat0, lon0)
            rms = math.sqrt(np.mean(np.sum(res ** 2, axis=1)))
            if best is None or rms < best[0]:
                best = (rms, p1, p2, A, res)
    rms, p1, p2, A, res = best
    used = np.array([p.get("weight", 1.0) > 0 for p in pts])
    rms = math.sqrt(np.mean(np.sum(res[used] ** 2, axis=1)))
    # échelle : km par pixel
    kmpx = 1 / math.sqrt(abs(np.linalg.det(A[:2, :])))
    print(f"Projection {KIND}, parallèles standard : {p1:.2f}° / {p2:.2f}°   échelle ≈ {kmpx * 1000:.0f} m/pixel")
    print(f"Erreur quadratique moyenne : {rms:.1f} px ≈ {rms * kmpx:.1f} km\n")
    for p, r in sorted(zip(pts, res), key=lambda t: -np.hypot(*t[1])):
        d = math.hypot(*r)
        print(f"   {p['name']:12s} écart {d:6.1f} px  ≈ {d * kmpx:5.1f} km")
    out = {"kind": KIND, "p1": p1, "p2": p2, "lat0": lat0, "lon0": lon0, "A": A.tolist(), "rms_px": rms, "km_per_px": kmpx,
           "reference_width": cfg["reference_width"]}
    path.with_suffix(".fit.json").write_text(json.dumps(out, indent=1), encoding="utf-8")


if __name__ == "__main__":
    main()
