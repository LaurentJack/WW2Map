"""Captures d'écran du README GitHub (docs/img/), prises avec Edge piloté par Playwright.

Prérequis : serveur local (python -m http.server 8765 à la racine) et
  scripts/.venv-exe/Scripts/python -m pip install playwright pillow
Usage : scripts/.venv-exe/Scripts/python scripts/exe/screenshots.py [nom ...]
"""
import sys
from pathlib import Path

from PIL import Image
from playwright.sync_api import sync_playwright

ROOT = Path(__file__).resolve().parents[2]
OUT = ROOT / "docs" / "img"
URL = "http://localhost:8765/index.html"

# Récupère l'instance de carte Leaflet (variable locale de app.js) dès sa création
HOOK = """
Object.defineProperty(window, 'L', { configurable: true,
  get() { return this.__L; },
  set(v) { this.__L = v; const o = v.Map.prototype.initialize;
           v.Map.prototype.initialize = function (...a) { window._m = this; return o.apply(this, a); }; } });
"""

JS_HELPERS = """
window.$cats = (on) => document.querySelectorAll('#cat-filters input').forEach(c => { if (c.checked !== on) c.click(); });
window.$layer = (txt) => { const i = [...document.querySelectorAll('.leaflet-control-layers label')]
   .find(l => l.textContent.includes(txt)).querySelector('input'); for (let k = 0; k < 3 && !i.checked; k++) i.click(); };
window.$date = (txt) => { const s = document.getElementById('sitmap-slider');
   for (let i = 0; i <= +s.max; i++) { s.value = i; s.dispatchEvent(new Event('input'));
     if (document.getElementById('sitmap-label').textContent.includes(txt)) return true; } return false; };
window.$gsgs = (txt) => { const b = [...document.querySelectorAll('#gsgs-series input')].find(x => x.parentElement.textContent.includes(txt));
   if (!b.checked) b.click(); };
"""

SHOTS = {
    # nom: (préparation JS, vue [lat, lon, zoom], JS après la vue, attente en ms)
    # la vue est appliquée après la préparation (cocher une série GSGS recentre la carte de façon animée)
    "apercu": ("", [50.3, 5.2, 6], "", 4000),
    "ardennes-1944": ("$cats(false); document.getElementById('sitmap-on').click(); document.getElementById('front-on').click(); $date('24 décembre 1944');",
                      [50.15, 5.9, 9], "", 7000),
    "ligne-de-front": ("$cats(false); document.getElementById('front-on').click(); $date('24 décembre 1944');", [50.1, 5.6, 7], "", 5000),
    "normandie-1943-comparaison": ("$cats(false); $gsgs('Normandie');", [49.183, -0.37, 13],
                                   "document.querySelector('.swipe-toggle').click();", 8000),
    # la case LIDAR est désactivée par Leaflet sous son zoom minimal (9) : on la coche après le zoom
    "lidar-satellite-bastogne": ("$cats(false); $layer('Satellite');", [50.037, 5.736, 16],
                                 "$layer('Wallonie : relief'); document.querySelector('.swipe-toggle').click();", 10000),
    "gsgs-france-1943": ("$cats(false); $gsgs('France 1:250');", [48.85, -0.9, 10], "", 8000),
}


def main():
    OUT.mkdir(parents=True, exist_ok=True)
    only = set(sys.argv[1:])
    with sync_playwright() as p:
        browser = p.chromium.launch(channel="msedge")
        for name, (setup, view, after, wait) in SHOTS.items():
            if only and name not in only:
                continue
            page = browser.new_page(viewport={"width": 1440, "height": 860}, device_scale_factor=1)
            page.add_init_script(HOOK)
            page.goto(URL, wait_until="networkidle")
            page.evaluate(f"(() => {{ {JS_HELPERS} }})()")  # IIFE : sinon Playwright appelle la dernière fonction
            page.evaluate(f"(() => {{ {setup} }})()")
            page.wait_for_timeout(1500)
            page.evaluate(f"_m.setView([{view[0]}, {view[1]}], {view[2]}, {{animate: false}})")
            page.wait_for_timeout(500)
            page.evaluate(f"(() => {{ {after} }})()")
            page.wait_for_timeout(wait)
            page.wait_for_load_state("networkidle")
            png = OUT / f"{name}.png"
            page.screenshot(path=str(png), timeout=120000)
            page.close()
            jpg = png.with_suffix(".jpg")
            Image.open(png).convert("RGB").save(jpg, quality=82, optimize=True, progressive=True)
            png.unlink()
            print(f"{jpg.name} {jpg.stat().st_size // 1024} Ko", flush=True)
        browser.close()


if __name__ == "__main__":
    main()
