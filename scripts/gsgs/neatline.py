"""Détection automatique du cadre intérieur (neatline) d'une feuille topographique scannée.

Les feuilles GSGS / AMS ont deux cadres : une bordure extérieure et, environ 1 cm plus à l'intérieur,
le cadre de la carte proprement dite, aux coins duquel sont inscrites les coordonnées. C'est ce cadre
intérieur qu'il faut trouver.

1. Zone de la carte : la carte est encrée et dense (teintes, bois, routes : densité 0,6–0,8), les marges
   et la légende beaucoup moins (0,3–0,4). On mesure la densité d'encre colonne par colonne et ligne par
   ligne, et on retient le plus long intervalle au-dessus de 60 % de la densité médiane de la carte.
2. Recalage : chaque bord est recalé sur le trait sombre le plus proche (± 30 px), mesuré séparément
   sur deux tranches pour tenir compte d'un léger biais du scan.
3. Coins : intersection des quatre droites. Contrôle : les proportions doivent correspondre à
   l'emprise géographique attendue (identifiant AMS).
"""
import cv2
import numpy as np

SPAN = 30  # fenêtre de recalage (± px) ; élargie quand la zone est donnée à la main


def _longest_run(mask_1d):
    best, cur, start = (0, 0, 0), 0, 0
    for i, v in enumerate(mask_1d):
        if v:
            if cur == 0:
                start = i
            cur += 1
            if cur > best[0]:
                best = (cur, start, i)
        else:
            cur = 0
    return best[1], best[2]


def ink(color):
    """Pixels qui ne sont pas du papier : écart à la couleur du papier (estimée dans les coins)."""
    m = int(min(color.shape[:2]) * 0.02)
    paper = np.median(np.concatenate([color[:m, :m].reshape(-1, 3), color[:m, -m:].reshape(-1, 3),
                                      color[-m:, :m].reshape(-1, 3), color[-m:, -m:].reshape(-1, 3)]), axis=0)
    d = np.abs(color.astype(np.int16) - paper.astype(np.int16)).sum(axis=2)
    return (d > 60).astype(np.uint8)


def _profile(dark, axis, lo, hi, part):
    h, w = dark.shape
    if axis == 0:
        a, b = int(h * part[0]), int(h * part[1])
        return dark[a:b, lo:hi].sum(axis=0).astype(float) / (b - a)
    a, b = int(w * part[0]), int(w * part[1])
    return dark[lo:hi, a:b].sum(axis=1).astype(float) / (b - a)


def _snap(dark, axis, pos, part, inward, span=None, inkmap=None, dense=None):
    """Trait sombre le plus proche de pos (axis 0 : trait vertical, position en x ; 1 : horizontal, en y).
    inward = +1 si l'intérieur de la carte est du côté des coordonnées croissantes, -1 sinon.
    Si un autre trait aussi long court parallèlement 20 à 75 px plus à l'intérieur, le premier est la
    bordure extérieure : on retient le trait intérieur (le cadre de la carte)."""
    n = dark.shape[1] if axis == 0 else dark.shape[0]
    span = span or SPAN
    lo, hi = max(0, pos - span), min(n, pos + span + 1)
    prof = _profile(dark, axis, lo, hi, part)
    if prof.max() < 0.25:
        return None
    idx = np.arange(lo, hi)
    sel = prof >= 0.6 * prof.max()
    j = idx[sel][np.argmin(np.abs(idx[sel] - pos))]
    near = (np.abs(idx - j) <= 3) & sel
    found = float(np.average(idx[near], weights=prof[near]))
    strength = prof[near].max()
    # Si la bande juste à l'intérieur du trait est du papier (densité d'encre faible), ce trait est la
    # bordure extérieure : on cherche le cadre de la carte 20 à 75 px plus à l'intérieur.
    outer = False
    if inkmap is not None and dense is not None:
        ba, bb = (int(found) + 6, int(found) + 26) if inward > 0 else (int(found) - 25, int(found) - 5)
        ba, bb = max(0, ba), min(n, bb)
        outer = bb > ba and _profile(inkmap, axis, ba, bb, part).mean() < 0.5 * dense
    a, b = (int(found) + 20, int(found) + 76) if inward > 0 else (int(found) - 75, int(found) - 19)
    a, b = max(0, a), min(n, b)
    if outer and b - a > 5:
        p2 = _profile(dark, axis, a, b, part)
        if p2.max() >= 0.5 * strength:
            i2 = np.arange(a, b)
            s2 = p2 >= 0.6 * p2.max()
            k = i2[s2].max() if inward > 0 else i2[s2].min()
            nr = (np.abs(i2 - k) <= 3) & s2
            found = float(np.average(i2[nr], weights=p2[nr]))
    return found


def detect(color, aspect=None, debug=False, zone=None):
    """Coins [HG, HD, BD, BG] du cadre intérieur, en pixels, ou None.
    zone : boîte approximative (x0, y0, x1, y1) fournie à la main pour les feuilles atypiques
    (côtes, frontières : la densité d'encre n'y délimite pas la carte) ; le recalage fait le reste."""
    h, w = color.shape[:2]
    k = ink(color)
    col = np.convolve(k[int(h * 0.2):int(h * 0.8)].mean(axis=0), np.ones(15) / 15, mode="same")
    row = np.convolve(k[:, int(w * 0.2):int(w * 0.6)].mean(axis=1), np.ones(15) / 15, mode="same")
    thr_c = 0.6 * np.median(col[int(w * 0.3):int(w * 0.6)])
    thr_r = 0.6 * np.median(row[int(h * 0.3):int(h * 0.7)])
    x0, x1 = _longest_run(col > thr_c)
    y0, y1 = _longest_run(row > thr_r)
    global SPAN
    SPAN = 60 if zone else 30
    if zone:
        x0, y0, x1, y1 = zone
    dark = (color.max(axis=2) < 150).astype(np.uint8)
    dense = float(np.median(col[int(w * 0.3):int(w * 0.6)]))
    res = _corners(dark, (x0, y0, x1, y1), h, w, aspect, k, dense)
    if aspect and res and res[1] > 0.03:
        # proportions incorrectes : un des bords est mal placé (légende dense, zone pâle…).
        # On recalcule tour à tour chaque bord à partir des trois autres et on garde le meilleur.
        alt = [(x0, y0, int(round(x0 + aspect * (y1 - y0))), y1),
               (int(round(x1 - aspect * (y1 - y0))), y0, x1, y1),
               (x0, y0, x1, int(round(y0 + (x1 - x0) / aspect))),
               (x0, int(round(y1 - (x1 - x0) / aspect)), x1, y1)]
        # parmi les corrections qui rétablissent les proportions (< 2 %), on garde celle qui déplace
        # le moins son bord ; à défaut, celle qui donne les meilleures proportions.
        z0 = (x0, y0, x1, y1)
        cands = []
        for z in alt:
            r = _corners(dark, z, h, w, aspect, k, dense)
            if r:
                cands.append((max(abs(a - b) for a, b in zip(z, z0)), r))
        good = [c for c in cands if c[1][1] < 0.02]
        if good:
            res = min(good, key=lambda c: c[0])[1]
        elif cands and min(c[1][1] for c in cands) < res[1]:
            res = min(cands, key=lambda c: c[1][1])[1]
    if not res:
        return (None, {"zone": (x0, y0, x1, y1)}) if debug else None
    c, err = res
    return (c, {"zone": (x0, y0, x1, y1), "aspect_err": err}) if debug else c


def _corners(dark, zone, h, w, aspect, inkmap=None, dense=None):
    x0, y0, x1, y1 = zone
    if not (0 < x0 < x1 < w and 0 < y0 < y1 < h):
        return None
    A, B = (0.20, 0.45), (0.55, 0.80)
    kw = {"inkmap": inkmap, "dense": dense}
    L = (_snap(dark, 0, x0, A, +1, **kw), _snap(dark, 0, x0, B, +1, **kw))
    R = (_snap(dark, 0, x1, A, -1, **kw), _snap(dark, 0, x1, B, -1, **kw))
    T = (_snap(dark, 1, y0, A, +1, **kw), _snap(dark, 1, y0, B, +1, **kw))
    Bt = (_snap(dark, 1, y1, A, -1, **kw), _snap(dark, 1, y1, B, -1, **kw))
    if any(v is None for side in (L, R, T, Bt) for v in side):
        return None

    def coherent(side, est, tol):
        # Au-delà de la tolérance, une des deux mesures a accroché un autre trait : on garde la plus
        # proche de l'estimation pour tout le côté. Les côtés horizontaux, mesurés symétriquement
        # autour du centre, ne varient que par le biais du scan (tolérance 12 px) ; les côtés verticaux
        # s'inclinent en plus à cause de la convergence des méridiens (tolérance 60 px).
        if abs(side[0] - side[1]) <= tol:
            return side
        v = side[0] if abs(side[0] - est) <= abs(side[1] - est) else side[1]
        return (v, v)

    L, R = coherent(L, x0, 60), coherent(R, x1, 60)
    T, Bt = coherent(T, y0, 12), coherent(Bt, y1, 12)
    ya, yb = h * (A[0] + A[1]) / 2, h * (B[0] + B[1]) / 2
    xa, xb = w * (A[0] + A[1]) / 2, w * (B[0] + B[1]) / 2

    def corner(v, hl):
        x = v[0]
        for _ in range(20):
            y = hl[0] + (x - xa) * (hl[1] - hl[0]) / (xb - xa)
            x = v[0] + (y - ya) * (v[1] - v[0]) / (yb - ya)
        return [round(x, 1), round(y, 1)]

    c = [corner(L, T), corner(R, T), corner(R, Bt), corner(L, Bt)]
    err = 0.0
    if aspect:
        r = (np.hypot(c[1][0] - c[0][0], c[1][1] - c[0][1]) + np.hypot(c[2][0] - c[3][0], c[2][1] - c[3][1])) /             (np.hypot(c[3][0] - c[0][0], c[3][1] - c[0][1]) + np.hypot(c[2][0] - c[1][0], c[2][1] - c[1][1]))
        err = float(abs(r - aspect) / aspect)
    return c, err
