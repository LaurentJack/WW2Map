"""Extraction des lignes de front (trait noir épais) des cartes de situation calées (data/sitmaps/*/*.webp).

Les images sont déjà reprojetées en Web Mercator avec leurs bornes : pixel → (lat, lon) est direct.
1. masque des pixels sombres et peu saturés (encre noire ; les routes grises et l'hydrographie bleue sont exclues) ;
2. on ne garde que les traits épais (ouverture morphologique), ce qui élimine écritures, symboles d'unités,
   limites d'armées (traits fins) et dents de la ligne de front ;
3. composantes trop courtes ou trop compactes écartées, squelette, graphe, élagage des petites branches ;
4. polylignes simplifiées → GeoJSON MultiLineString.
"""
import math
import cv2
import numpy as np


def load(path):
    im = cv2.imread(str(path), cv2.IMREAD_UNCHANGED)
    alpha = im[..., 3] if im.shape[2] == 4 else np.full(im.shape[:2], 255, np.uint8)
    return im[..., :3], alpha


def ink_mask(bgr, alpha, vmax=105, smax=120):
    hsv = cv2.cvtColor(bgr, cv2.COLOR_BGR2HSV)
    m = (hsv[..., 2] < vmax) & (hsv[..., 1] < smax) & (alpha > 0)
    return m.astype(np.uint8) * 255


def thick_strokes(mask, r):
    k = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (2 * r + 1, 2 * r + 1))
    core = cv2.morphologyEx(mask, cv2.MORPH_OPEN, k)
    return core


def skeletonize(mask):
    """Amincissement de Zhang-Suen (vectorisé numpy) → squelette 8-connexe d'épaisseur 1."""
    img = (mask > 0).astype(np.uint8)
    ys, xs = np.nonzero(img)
    if len(ys) == 0:
        return img
    y0, y1, x0, x1 = max(ys.min() - 2, 0), ys.max() + 3, max(xs.min() - 2, 0), xs.max() + 3
    I = np.pad(img[y0:y1, x0:x1], 1)
    while True:
        changed = False
        for step in (0, 1):
            P2, P3, P4, P5 = I[:-2, 1:-1], I[:-2, 2:], I[1:-1, 2:], I[2:, 2:]
            P6, P7, P8, P9 = I[2:, 1:-1], I[2:, :-2], I[1:-1, :-2], I[:-2, :-2]
            seq = [P2, P3, P4, P5, P6, P7, P8, P9, P2]
            B = sum(seq[:-1])
            A = sum(((seq[k] == 0) & (seq[k + 1] == 1)).astype(np.uint8) for k in range(8))
            if step == 0:
                c = (P2 * P4 * P6 == 0) & (P4 * P6 * P8 == 0)
            else:
                c = (P2 * P4 * P8 == 0) & (P2 * P6 * P8 == 0)
            rm = (I[1:-1, 1:-1] == 1) & (B >= 2) & (B <= 6) & (A == 1) & c
            if rm.any():
                I[1:-1, 1:-1][rm] = 0
                changed = True
        if not changed:
            break
    out = np.zeros_like(img)
    out[y0:y1, x0:x1] = I[1:-1, 1:-1]
    return out


_NB = [(-1, -1), (-1, 0), (-1, 1), (0, -1), (0, 1), (1, -1), (1, 0), (1, 1)]


def branches(sk):
    """Nombre de branches autour de chaque pixel (transitions 0→1 sur le cercle des 8 voisins)."""
    I = np.pad(sk.astype(np.uint8), 1)
    P = [I[:-2, 1:-1], I[:-2, 2:], I[1:-1, 2:], I[2:, 2:], I[2:, 1:-1], I[2:, :-2], I[1:-1, :-2], I[:-2, :-2]]
    A = sum(((P[k] == 0) & (P[(k + 1) % 8] == 1)).astype(np.uint8) for k in range(8))
    return A


def trace(skel):
    """Squelette → liste de chemins (listes de (y, x)) entre extrémités/jonctions.
    Les nœuds sont définis par le nombre de branches (et non le nombre de voisins), pour que les
    « marches d'escalier » d'un squelette 8-connexe ne coupent pas les traits."""
    sk = skel.astype(bool)
    A = branches(sk)
    pts = set(zip(*np.nonzero(sk)))
    nodes = {p for p in pts if A[p] != 2}
    def nbrs(p):
        y, x = p
        return [(y + dy, x + dx) for dy, dx in _NB if (y + dy, x + dx) in pts]
    visited = set()
    paths = []

    def walk(start, first):
        path = [start, first]
        prev, cur = start, first
        while cur not in nodes:
            visited.add(cur)
            cand = [r for r in nbrs(cur) if r != prev and r not in visited and r not in path[-3:]]
            if not cand:
                break
            nd = [r for r in cand if r in nodes]
            if nd:
                nxt = nd[0]
            else:
                nxt = max(cand, key=lambda r: (r[0] - prev[0]) ** 2 + (r[1] - prev[1]) ** 2)
            prev, cur = cur, nxt
            path.append(cur)
        return path

    for n in nodes:
        for q in nbrs(n):
            if q in visited or (q in nodes and (q, n) in visited):
                continue
            if q in nodes:
                visited.add((n, q))
                paths.append([n, q])
                continue
            paths.append(walk(n, q))
    for s in pts - visited - nodes:  # boucles sans nœud
        if s in visited:
            continue
        nb = nbrs(s)
        if nb:
            visited.add(s)
            p = walk(s, nb[0])
            paths.append(p + [s])
    return paths, A


def path_len(p):
    a = np.array(p, float)
    return float(np.sum(np.hypot(*np.diff(a, axis=0).T))) if len(a) > 1 else 0.0


def prune(paths, deg, min_spur):
    """Retire itérativement les petites branches pendantes (dents, bouts de symboles)."""
    for _ in range(4):
        cnt = {}
        for p in paths:
            for e in (p[0], p[-1]):
                cnt[e] = cnt.get(e, 0) + 1
        keep = []
        for p in paths:
            dangling = cnt.get(p[0], 0) == 1 or cnt.get(p[-1], 0) == 1
            bridge = cnt.get(p[0], 0) > 1 and cnt.get(p[-1], 0) > 1
            if dangling and not bridge and path_len(p) < min_spur:
                continue
            keep.append(p)
        if len(keep) == len(paths):
            break
        paths = merge(keep)
    return paths


def merge(paths):
    """Fusionne les chemins qui se touchent par une extrémité de degré 2 (après élagage)."""
    paths = [list(p) for p in paths]
    changed = True
    while changed:
        changed = False
        ends = {}
        for i, p in enumerate(paths):
            for e in (p[0], p[-1]):
                ends.setdefault(e, []).append(i)
        for e, idx in ends.items():
            idx = list(dict.fromkeys(idx))
            if len(idx) == 2:
                i, j = idx
                a, b = paths[i], paths[j]
                if a[0] == e: a = a[::-1]
                if b[-1] == e: b = b[::-1]
                if a[-1] != e or b[0] != e or a is b:
                    continue
                paths[i] = a + b[1:]
                paths.pop(j)
                changed = True
                break
    return paths


def features(paths, ink, core, scale, ink_loose=None):
    """Par chemin : longueur, demi-largeur médiane du trait, densité de « dents », rectitude."""
    dt = cv2.distanceTransform(ink, cv2.DIST_L2, cv2.DIST_MASK_PRECISE)
    resid = ((ink_loose if ink_loose is not None else ink) > 0) & ~(cv2.dilate(core, np.ones((5, 5), np.uint8)) > 0)
    out = []
    H, W = ink.shape
    for p in paths:
        a = np.array(p)
        L = path_len(p)
        w = float(np.mean(dt[a[:, 0], a[:, 1]]))
        r_out, r_in = int(round(12 * scale + w)), int(round(w + 2))
        y0, x0 = max(a[:, 0].min() - r_out - 2, 0), max(a[:, 1].min() - r_out - 2, 0)
        y1, x1 = min(a[:, 0].max() + r_out + 3, H), min(a[:, 1].max() + r_out + 3, W)
        m = np.zeros((y1 - y0, x1 - x0), np.uint8)
        cv2.polylines(m, [(a[:, ::-1] - [x0, y0]).reshape(-1, 1, 2).astype(np.int32)], False, 255, 1)
        band = cv2.dilate(m, cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (2 * r_out + 1,) * 2)) > 0
        band &= ~(cv2.dilate(m, cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (2 * r_in + 1,) * 2)) > 0)
        teeth = float((resid[y0:y1, x0:x1] & band).sum()) / max(L, 1)
        chord = float(np.hypot(*(a[-1] - a[0])))
        ap = cv2.approxPolyDP(a[:, ::-1].reshape(-1, 1, 2).astype(np.int32), 3.0 * scale, False)
        out.append({"len": L, "w": w, "teeth": teeth, "straight": chord / max(L, 1), "vpk": 100.0 * len(ap) / max(L, 1)})
    return out


def teeth_profile(path, ink_strict, w, scale=1.0, step=2.0):
    """Fraction des échantillons, de chaque côté du trait, où l'on trouve de l'encre juste au-delà du bord
    (les « dents » de la ligne de front sont d'un seul côté). Retourne (côté gauche, côté droit)."""
    a = np.array(path, float)
    if len(a) < 8:
        return 0.0, 0.0
    d = np.hypot(*np.diff(a, axis=0).T)
    s = np.concatenate([[0], np.cumsum(d)])
    ss = np.arange(0, s[-1], step)
    y = np.interp(ss, s, a[:, 0]); x = np.interp(ss, s, a[:, 1])
    k = max(2, int(4 * scale))
    ty = np.gradient(cv2.GaussianBlur(y[None], (0, 0), k)[0]); tx = np.gradient(cv2.GaussianBlur(x[None], (0, 0), k)[0])
    nn = np.hypot(ty, tx) + 1e-9
    ny, nx = tx / nn, -ty / nn
    H, W = ink_strict.shape
    res = []
    for sgn in (1, -1):
        hit = np.zeros(len(ss), bool)
        for dist in np.arange(w + 2.0, w + 2.0 + 6 * scale, 1.0):
            yy = np.clip(np.round(y + sgn * dist * ny).astype(int), 0, H - 1)
            xx = np.clip(np.round(x + sgn * dist * nx).astype(int), 0, W - 1)
            hit |= ink_strict[yy, xx] > 0
        res.append(float(hit.mean()))
    return tuple(res)


def merc_to_latlon(py, px, bounds, shape):
    (s, w), (n, e) = bounds
    H, W = shape
    my = lambda a: math.log(math.tan(math.pi / 4 + math.radians(a) / 2))
    yn, ys = my(n), my(s)
    lon = w + (np.asarray(px) + 0.5) / W * (e - w)
    yy = yn - (np.asarray(py) + 0.5) / H * (yn - ys)
    lat = np.degrees(2 * np.arctan(np.exp(yy)) - np.pi / 2)
    return lat, lon


def extract_front(path, params=None):
    """Retourne (lignes en pixels retenues, lignes rejetées, infos) pour une carte de situation.
    Critères : encre noire (médiane de V le long du trait < dmax), trait épais relativement aux autres
    traits noirs de la carte (limites d'armées plus fines), longueur minimale, pas de longue ligne droite fine."""
    P = dict(vmax=75, r=1, min_len=100, dmax=45, dw=0.5, straight_vpk=1.6, straight_len=150, min_box=70, short_len=200, short_vpk=1.5, ruler_vpk=1.0)
    P.update(params or {})
    bgr, alpha = load(path)
    ink = ink_mask(bgr, alpha, vmax=P["vmax"])
    core = thick_strokes(ink, P["r"])
    n, lab, st, _ = cv2.connectedComponentsWithStats(core, 8)
    lut = (np.maximum(st[:, 2], st[:, 3]) >= 40).astype(np.uint8) * 255
    lut[0] = 0
    core = lut[lab]
    sk = skeletonize(core)
    paths, A = trace(sk)
    paths = [p for p in prune(merge(paths), A, 30) if path_len(p) >= 30]
    F = features(paths, ink, core, 1.0)
    V = cv2.erode(cv2.cvtColor(bgr, cv2.COLOR_BGR2HSV)[..., 2], np.ones((3, 3), np.uint8))
    for p, f in zip(paths, F):
        q = np.array(p)
        f["dark"] = float(np.median(V[q[:, 0], q[:, 1]]))
    dark = [(f["w"], f["len"]) for f in F if f["len"] >= 150 and f["dark"] < P["dmax"]]
    info = {"shape": bgr.shape[:2], "img": bgr, "W0": None}
    if not dark:
        return [], paths, info
    ws = np.array([x[0] for x in dark]); ls = np.array([x[1] for x in dark])
    o = np.argsort(ws); cw = np.cumsum(ls[o]) / ls.sum()
    W0 = float(ws[o][min(np.searchsorted(cw, 0.5), len(o) - 1)])
    info["W0"] = W0
    keep, rej = [], []
    for p, f in zip(paths, F):
        ok = f["len"] >= P["min_len"] and f["dark"] < P["dmax"] and f["w"] >= W0 - P["dw"]
        if ok and f["vpk"] < P["straight_vpk"] and f["len"] > P["straight_len"] and f["w"] < W0:
            ok = False  # longue ligne droite plus fine que le front : limite d'armée
        q = np.array(p)
        if ok and max(np.ptp(q[:, 0]), np.ptp(q[:, 1])) < P["min_box"]:
            ok = False  # petite boucle : lettre, symbole
        if ok and f["len"] < P["short_len"] and f["vpk"] < P["short_vpk"]:
            ok = False  # court trait droit : échantillon de légende, soulignement
        if ok and f["vpk"] < P["ruler_vpk"]:
            ok = False  # tracé à la règle : limite, cadre
        (keep if ok else rej).append(p)
    return keep, rej, info
