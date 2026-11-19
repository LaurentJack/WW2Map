"""Détection des graduations d'une minute (barres alternées noir/blanc) imprimées sur le cadre des
feuilles GSGS 4042 (France 1:250 000).

Pour un bord de la feuille (segment entre deux coins du cadre), on cherche, dans une bande de ±R pixels
perpendiculaire au trait détecté, la ligne de pixels où le profil alterne le plus nettement avec une période
proche de la minute attendue ; on binarise ce profil et on relève les transitions clair/sombre, qui tombent
sur les minutes entières. Retourne une liste de positions (x, y) en pixels, ordonnées le long du bord,
régularisées par un ajustement linéaire (une transition par minute, sans trou).
"""
import numpy as np
import cv2


def _sample(gray, p0, p1, offsets, step=0.5):
    p0, p1 = np.asarray(p0, float), np.asarray(p1, float)
    L = np.hypot(*(p1 - p0))
    t = np.arange(0, L, step) / L
    u = (p1 - p0) / L
    n = np.array([-u[1], u[0]])
    out = []
    for o in offsets:
        pts = p0[None] + t[:, None] * (p1 - p0)[None] + o * n[None]
        out.append(cv2.remap(gray, pts[:, 0].astype(np.float32)[None], pts[:, 1].astype(np.float32)[None], cv2.INTER_LINEAR)[0])
    return np.array(out, float), t * L, u, n


def edge_minutes(gray, p0, p1, px_per_min, radius=14, extend=40):
    """Transitions d'une minute le long du segment p0→p1 (prolongé de `extend` px de chaque côté)."""
    p0, p1 = np.asarray(p0, float), np.asarray(p1, float)
    u = (p1 - p0) / np.hypot(*(p1 - p0))
    a, b = p0 - extend * u, p1 + extend * u
    offs = np.arange(-radius, radius + 0.5, 1.0)
    prof, s, u, n = _sample(gray, a, b, offs)
    step = s[1] - s[0]
    per = 2 * px_per_min / step  # période (2 minutes : une barre noire + une blanche) en échantillons
    best = None
    for i, row in enumerate(prof):
        r = row - cv2.GaussianBlur(row[None], (1, 0), sigmaX=per)[0] if False else row - np.convolve(row, np.ones(int(per)) / int(per), "same")
        # énergie à la période attendue (± 15 %)
        F = np.abs(np.fft.rfft(r * np.hanning(len(r))))
        f = np.fft.rfftfreq(len(r))
        band = (f > 1 / (per * 1.15)) & (f < 1 / (per * 0.85))
        e = F[band].max() / (np.median(F) + 1e-9)
        if best is None or e > best[0]:
            best = (e, i, r, f[band][np.argmax(F[band])])
    score, i, r, fpk = best
    period = 1 / fpk  # en échantillons (2 minutes)
    # phase par régression sinusoïdale : r ≈ A cos(2π k/period) + B sin(...)
    k = np.arange(len(r))
    # affiner la période localement
    best2 = None
    for P in np.linspace(period * 0.97, period * 1.03, 121):
        c, sn = np.cos(2 * np.pi * k / P), np.sin(2 * np.pi * k / P)
        A = np.dot(r, c) / np.dot(c, c); B = np.dot(r, sn) / np.dot(sn, sn)
        amp = np.hypot(A, B)
        if best2 is None or amp > best2[0]:
            best2 = (amp, P, np.arctan2(B, A))
    amp, P, ph = best2
    # les transitions sont aux zéros du cosinus : 2πk/P - ph = π/2 + mπ
    # → k = (ph + π/2 + mπ) P / (2π)
    m0 = int(np.floor(-(ph + np.pi / 2) / np.pi)) - 1
    ks = []
    m = m0
    while True:
        kk = (ph + np.pi / 2 + m * np.pi) * P / (2 * np.pi)
        if kk > len(r):
            break
        if kk >= 0:
            ks.append(kk)
        m += 1
    ks = np.array(ks)
    # passages par zéro réels du profil (bord des barres), appariés à la grille sinusoïdale
    sm = cv2.GaussianBlur(r[None], (0, 0), sigmaX=1.0)[0]
    zc = np.where(np.sign(sm[:-1]) != np.sign(sm[1:]))[0]
    zc = zc + sm[zc] / (sm[zc] - sm[zc + 1])  # interpolation linéaire
    idx = np.arange(len(ks)); pred = ks.copy()
    for it in range(5):
        loc = np.full(len(ks), np.nan)
        for j, kk in enumerate(pred):
            if len(zc) == 0:
                break
            d = np.abs(zc - kk); q = int(np.argmin(d))
            if d[q] < P / (6 if it else 4):
                loc[j] = zc[q]
        ok = ~np.isnan(loc)
        w = np.ones(ok.sum())
        for _ in range(4):
            c = np.polyfit(idx[ok], loc[ok], 2, w=w)
            res = loc[ok] - np.polyval(c, idx[ok])
            sig = 1.4826 * np.median(np.abs(res)) + 0.3
            w = (np.abs(res) < 3 * sig).astype(float) + 1e-3
        pred = np.polyval(c, idx)
    kfit = np.polyval(c, idx)
    pos = a[None] + (kfit * step)[:, None] * u[None] + offs[i] * n[None]
    # dark/light : signe du profil juste après chaque transition
    after = [np.sign(r[min(len(r) - 1, int(kk + P / 4))]) for kk in kfit]
    return {"points": pos, "score": float(score), "offset": float(offs[i]), "px_per_min": float(P * step / 2),
            "rms": float(np.sqrt(np.mean(res[w > 0.5] ** 2)) * step), "matched": int(ok.sum()), "n": int(len(ks)), "dark_after": after}


def edge_minutes_v2(gray, p0, p1, px_per_min, radius=14, extend=40, tol=0.12):
    """Variante robuste : passages par zéro réels, chaînés de proche en proche (écart ≈ n minutes entières)."""
    p0, p1 = np.asarray(p0, float), np.asarray(p1, float)
    u = (p1 - p0) / np.hypot(*(p1 - p0))
    a, b = p0 - extend * u, p1 + extend * u
    offs = np.arange(-radius, radius + 0.5, 1.0)
    prof, s, u, n = _sample(gray, a, b, offs)
    step = s[1] - s[0]
    win = int(2 * px_per_min / step)
    best = None
    for i, row in enumerate(prof):
        r = row - np.convolve(row, np.ones(win) / win, "same")
        sm = cv2.GaussianBlur(r[None], (0, 0), sigmaX=1.0)[0]
        z = np.where(np.sign(sm[:-1]) != np.sign(sm[1:]))[0]
        z = (z + sm[z] / (sm[z] - sm[z + 1])) * step  # en pixels
        if len(z) < 10:
            continue
        d = np.diff(z)
        cand = d[(d > 0.88 * px_per_min) & (d < 1.12 * px_per_min)]
        if len(cand) < 10:
            continue
        ppm = float(np.median(cand))
        good = np.abs(d - ppm) < tol * ppm
        # amplitude du contraste : préférer la rangée des barres
        score = good.sum() * good.mean()
        if best is None or score > best[0]:
            best = (score, i, z, ppm)
    score, i, z, ppm = best
    # chaînage : on part de la plus longue suite régulière
    d = np.diff(z)
    good = np.abs(d - ppm) < tol * ppm
    run, bestrun, start = 0, (0, 0), 0
    for k, g in enumerate(good):
        if g:
            run += 1
            if run > bestrun[0]:
                bestrun = (run, k - run + 1)
        else:
            run = 0
    k0 = bestrun[1]
    idx = {k0: 0}
    for direction in (1, -1):
        last_k, last_i = k0, 0
        k = k0 + direction
        while 0 <= k < len(z):
            gap = (z[k] - z[last_k]) * direction
            nn = round(gap / ppm)
            if nn >= 1 and abs(gap - nn * ppm) < tol * ppm * (1 + 0.3 * (nn - 1)) and nn <= 6:
                last_i += direction * nn
                idx[k] = last_i
                last_k = k
            k += direction
    ks = np.array(sorted(idx)); I = np.array([idx[k] for k in ks], float); Z = z[ks]
    w = np.ones_like(Z)
    for _ in range(5):
        c = np.polyfit(I, Z, 2, w=w)
        res = Z - np.polyval(c, I)
        sig = 1.4826 * np.median(np.abs(res[w > 0.5])) + 0.3
        w = (np.abs(res) < 3 * sig).astype(float) + 1e-3
    grid = np.arange(I.min(), I.max() + 1)
    pos = np.polyval(c, grid)
    pts = a[None] + pos[:, None] * u[None] + offs[i] * n[None]
    return {"points": pts, "score": float(score), "offset": float(offs[i]), "px_per_min": float(c[1] + 2 * c[0] * grid.mean()),
            "rms": float(np.sqrt(np.mean(res[w > 0.5] ** 2))), "matched": int((w > 0.5).sum()), "n": int(len(grid))}


def _track_band(prof, step, px_per_min, chunk_px=320):
    """Rangée de la bande graduée le long du bord, tronçon par tronçon (le trait n'est pas toujours droit)."""
    nrow, L = prof.shape
    ch = int(max(chunk_px, 12 * px_per_min) / step)
    per = 2 * px_per_min / step
    cen, off = [], []
    for s0 in range(0, L - ch + 1, ch // 2):
        seg = prof[:, s0:s0 + ch]
        seg = seg - seg.mean(1, keepdims=True)
        F = np.abs(np.fft.rfft(seg * np.hanning(ch)[None], axis=1))
        f = np.fft.rfftfreq(ch)
        band = (f > 1 / (per * 1.15)) & (f < 1 / (per * 0.87))
        e = F[:, band].max(1) / (np.median(F, 1) + 1e-9)
        k = int(np.argmax(e))
        if e[k] > 6:
            # barycentre local pour une position sub-pixel
            lo, hi = max(0, k - 1), min(nrow, k + 2)
            cen.append(s0 + ch / 2); off.append(np.average(np.arange(lo, hi), weights=e[lo:hi]))
    cen, off = np.array(cen), np.array(off)
    if len(cen) < 3:
        return None
    w = np.ones_like(off)
    for _ in range(4):
        c = np.polyfit(cen, off, 2, w=w)
        r = off - np.polyval(c, cen)
        w = (np.abs(r) < max(1.5, 3 * 1.4826 * np.median(np.abs(r)))).astype(float) + 1e-3
    return np.polyval(c, np.arange(L))


def edge_minutes_v3(gray, p0, p1, px_per_min, radius=14, extend=40, tol=0.12):
    """Comme v2, mais la rangée suit la bande graduée (offset variable le long du bord) et le profil est lissé."""
    p0, p1 = np.asarray(p0, float), np.asarray(p1, float)
    u = (p1 - p0) / np.hypot(*(p1 - p0))
    a, b = p0 - extend * u, p1 + extend * u
    offs = np.arange(-radius, radius + 0.5, 1.0)
    prof, s, u, n = _sample(gray, a, b, offs)
    step = s[1] - s[0]
    tr = _track_band(prof, step, px_per_min)
    if tr is None:
        return None
    rows = np.clip(tr, 0, len(offs) - 1)
    jj = np.arange(prof.shape[1])
    row = np.mean([prof[np.clip(np.round(rows + dd).astype(int), 0, len(offs) - 1), jj] for dd in (-1, 0, 1)], 0)
    win = int(2 * px_per_min / step)
    r = row - np.convolve(row, np.ones(win) / win, "same")
    sm = cv2.GaussianBlur(r[None], (0, 0), sigmaX=2.5)[0]
    z = np.where(np.sign(sm[:-1]) != np.sign(sm[1:]))[0]
    z = (z + sm[z] / (sm[z] - sm[z + 1])) * step
    d = np.diff(z)
    cand = d[(d > 0.85 * px_per_min) & (d < 1.15 * px_per_min)]
    ppm = float(np.median(cand))
    good = np.abs(d - ppm) < tol * ppm
    run, bestrun = 0, (0, 0)
    for k, g in enumerate(good):
        run = run + 1 if g else 0
        if run > bestrun[0]:
            bestrun = (run, k - run + 1)
    k0 = bestrun[1]
    idx = {k0: 0}
    for direction in (1, -1):
        last_k, last_i = k0, 0
        k = k0 + direction
        while 0 <= k < len(z):
            gap = (z[k] - z[last_k]) * direction
            nn = round(gap / ppm)
            if 1 <= nn <= 6 and abs(gap - nn * ppm) < tol * ppm * (1 + 0.3 * (nn - 1)):
                last_i += direction * nn
                idx[k] = last_i
                last_k = k
            k += direction
    ks = np.array(sorted(idx)); I = np.array([idx[k] for k in ks], float); Z = z[ks]
    w = np.ones_like(Z)
    for _ in range(5):
        c = np.polyfit(I, Z, 2, w=w)
        res = Z - np.polyval(c, I)
        sig = 1.4826 * np.median(np.abs(res[w > 0.5])) + 0.3
        w = (np.abs(res) < 3 * sig).astype(float) + 1e-3
    grid = np.arange(I.min(), I.max() + 1)
    pos = np.polyval(c, grid)
    o = np.interp(pos / step, jj, offs[0] + rows)
    pts = a[None] + pos[:, None] * u[None] + o[:, None] * n[None]
    return {"points": pts, "score": float(good.mean()), "offset": float(np.median(o)), "px_per_min": float(c[1]),
            "rms": float(np.sqrt(np.mean(res[w > 0.5] ** 2))), "matched": int((w > 0.5).sum()), "n": int(len(grid))}


def _line_fit(pts):
    m = pts.mean(0)
    _, _, vt = np.linalg.svd(pts - m)
    return m, vt[0]


def _intersect(l1, l2):
    (p, d), (q, e) = l1, l2
    A = np.array([d, -e]).T
    t = np.linalg.solve(A, q - p)
    return p + t[0] * d


def refine_frame(gray, corners, ppm_lon, ppm_lat, radius=60):
    """Affine les coins du cadre : on suit la bande graduée de chaque bord (±radius px autour du bord
    approximatif), on ajuste une droite, puis on intersecte les bords adjacents."""
    c = [np.asarray(q, float) for q in corners]
    segs = {"top": (c[0], c[1], ppm_lon), "right": (c[1], c[2], ppm_lat), "bottom": (c[3], c[2], ppm_lon), "left": (c[0], c[3], ppm_lat)}
    lines = {}
    for name, (p0, p1, ppm) in segs.items():
        offs = np.arange(-radius, radius + 0.5, 1.0)
        prof, s, u, n = _sample(gray, p0, p1, offs)
        step = s[1] - s[0]
        tr = _track_band(prof, step, ppm)
        if tr is None:
            return None
        jj = np.arange(prof.shape[1])[::20]
        pts = p0[None] + (jj * step)[:, None] * u[None] + (offs[0] + tr[jj])[:, None] * n[None]
        lines[name] = _line_fit(pts)
    out = [_intersect(lines["top"], lines["left"]), _intersect(lines["top"], lines["right"]),
           _intersect(lines["bottom"], lines["right"]), _intersect(lines["bottom"], lines["left"])]
    return [[round(float(q[0]), 1), round(float(q[1]), 1)] for q in out]
