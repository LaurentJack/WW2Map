"""Planches de lecture des identifiants AMS (coin bas-droit de chaque feuille), 6 feuilles par image.
Usage : python stamps.py <dossier de sortie> [série]"""
import json
import sys
from pathlib import Path

from PIL import Image, ImageDraw

HERE = Path(__file__).resolve().parent
CACHE = HERE.parent / ".cache" / "gsgs"
out = Path(sys.argv[1])
series = sys.argv[2] if len(sys.argv) > 2 else None
sheets = json.loads((HERE / "sheets_raw.json").read_text(encoding="utf-8"))
sheets = [s for s in sheets if not series or s["series"] == series]
crops = []
for s in sheets:
    im = Image.open(CACHE / s["cache"]).convert("L")
    w, h = im.size
    c = im.crop((int(w * 0.70), int(h * 0.90), w, h))
    c = c.resize((900, int(900 * c.height / c.width)))
    lab = Image.new("L", (900, c.height + 28), 255)
    lab.paste(c, (0, 28))
    ImageDraw.Draw(lab).text((6, 6), f"{s['series']} {s['sheet']} {s['name']}", fill=0)
    crops.append(lab)
for k in range(0, len(crops), 6):
    group = crops[k:k + 6]
    H = sum(g.height for g in group) + 6 * len(group)
    M = Image.new("L", (900, H), 200)
    y = 0
    for g in group:
        M.paste(g, (0, y))
        y += g.height + 6
    M.save(out / f"stamps_{series or 'all'}_{k // 6:02d}.jpg", quality=85)
print(len(crops), "feuilles,", (len(crops) + 5) // 6, "planches")
