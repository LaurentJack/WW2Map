"""Vidéo de démonstration (docs/video/demo.mp4) : visite automatique de l'application, filmée avec Edge
piloté par Playwright, légendes en surimpression, conversion en MP4 (H.264) par ffmpeg.

Prérequis : serveur local (python -m http.server 8765 à la racine), ffmpeg dans le PATH, et
  scripts/.venv-exe/Scripts/python -m pip install playwright
Usage : scripts/.venv-exe/Scripts/python scripts/exe/demo_video.py
"""
import shutil
import subprocess
import sys
from pathlib import Path

from playwright.sync_api import sync_playwright

sys.path.insert(0, str(Path(__file__).resolve().parent))
from screenshots import HOOK, JS_HELPERS, URL  # noqa: E402

ROOT = Path(__file__).resolve().parents[2]
OUT = ROOT / "docs" / "video"
W, H = 1280, 720

OVERLAY = """
window.$cap = (txt) => {
  let d = document.getElementById('demo-cap');
  if (!d) { d = document.createElement('div'); d.id = 'demo-cap'; document.body.appendChild(d);
    Object.assign(d.style, {position: 'fixed', left: '50%', bottom: '34px', transform: 'translateX(-50%)', zIndex: 10000,
      background: 'rgba(20,24,16,.86)', color: '#fff', font: '600 22px/1.35 system-ui, sans-serif', padding: '12px 22px',
      borderRadius: '10px', maxWidth: '78%', textAlign: 'center', boxShadow: '0 4px 18px rgba(0,0,0,.35)',
      transition: 'opacity .4s', pointerEvents: 'none'}); }
  d.style.opacity = txt ? 1 : 0; if (txt) d.innerHTML = txt;
};
window.$title = (html) => {
  let d = document.getElementById('demo-title');
  if (!d) { d = document.createElement('div'); d.id = 'demo-title'; document.body.appendChild(d);
    Object.assign(d.style, {position: 'fixed', inset: 0, zIndex: 10001, background: 'rgba(28,33,22,.94)', color: '#fff',
      display: 'flex', flexDirection: 'column', alignItems: 'center', justifyContent: 'center', textAlign: 'center',
      font: '400 26px/1.5 system-ui, sans-serif', transition: 'opacity .6s'}); }
  d.style.opacity = html ? 1 : 0; d.style.pointerEvents = 'none'; if (html) d.innerHTML = html;
};
window.$idx = (txt) => { const s = document.getElementById('sitmap-slider');
  for (let i = 0; i <= +s.max; i++) { s.value = i; s.dispatchEvent(new Event('input'));
    if (document.getElementById('sitmap-label').textContent.includes(txt)) return i; } return -1; };
window.$at = (i) => { const s = document.getElementById('sitmap-slider'); s.value = i; s.dispatchEvent(new Event('input')); };
"""


def main():
    OUT.mkdir(parents=True, exist_ok=True)
    raw = OUT / "raw"
    shutil.rmtree(raw, ignore_errors=True)
    with sync_playwright() as p:
        browser = p.chromium.launch(channel="msedge")
        ctx = browser.new_context(viewport={"width": W, "height": H}, record_video_dir=str(raw),
                                  record_video_size={"width": W, "height": H})
        pg = ctx.new_page()
        pg.add_init_script(HOOK)
        pg.goto(URL, wait_until="networkidle")
        ev = lambda js: pg.evaluate(f"(() => {{ {js} }})()")  # noqa: E731
        wait = pg.wait_for_timeout
        ev(JS_HELPERS)
        ev(OVERLAY)

        # 1. Titre
        ev("$title('<div style=\"font-size:44px;font-weight:700\">Carte de la Seconde Guerre mondiale</div>"
           "<div style=\"margin-top:10px;opacity:.85\">Belgique · France · Allemagne — à partir d\\'archives publiques</div>');")
        wait(3500)
        ev("$title('');")
        wait(800)

        # 2. Les lieux
        ev("$cap('Près de 5 000 lieux : batailles, camps, massacres, bunkers, cimetières, musées');")
        wait(3500)
        ev("_m.flyTo([50.2, 5.4], 8, {duration: 2.5});")
        wait(3500)
        ev("$cap('Filtres par catégorie, pays, période et source');")
        for sel in ["Site militaire", "Cimetière"]:
            ev(f"[...document.querySelectorAll('#cat-filters label')].find(l => l.textContent.includes('{sel}')).querySelector('input').click();")
            wait(1300)
        ev("$cap('Recherche plein texte, puis fiche du lieu');")
        pg.fill("#search", "Bastogne")
        wait(1800)
        pg.click("#result-list li")
        wait(4500)
        ev("_m.closePopup(); document.getElementById('search').value=''; document.getElementById('search').dispatchEvent(new Event('input'));")
        ev("$cats(false);")

        # 3. Cartes de situation, Normandie
        ev("$cap('419 cartes de situation alliées de 1944-1945, calées sur la carte actuelle');")
        ev("document.getElementById('sitmap-on').click();")
        i0 = ev("return $idx('6 juin 1944');")
        ev("_m.setView([49.15, -0.6], 9, {animate:false});")
        wait(3500)
        ev("$cap('Jour après jour : de la tête de pont du 6 juin à la percée d\\'août 1944');")
        for i in [i0 + d for d in (0, 6, 14, 24, 34, 44, 52, 56)]:
            ev(f"$at({i});")
            wait(1300)

        # 4. Ligne de front animée
        ev("document.getElementById('sitmap-on').click(); document.getElementById('front-on').click();")
        ev("_m.setView([50.3, 5.8], 6, {animate:false});")
        ev("$cap('La ligne de front, extraite des cartes et animée — octobre 1944 à mai 1945');")
        a, b = ev("return $idx('15 octobre 1944');"), ev("return $idx('8 mai 1945');")
        wait(1200)
        for i in range(a, b + 1, 3):
            ev(f"$at({i});")
            wait(220)
        wait(1500)

        # 5. Ardennes : carte d'époque + front
        ev("document.getElementById('sitmap-on').click();")
        ev("$idx('24 décembre 1944'); _m.setView([50.15, 5.9], 9, {animate:false});")
        ev("$cap('24 décembre 1944 : la bataille des Ardennes sur la carte du 12th Army Group');")
        wait(5500)
        ev("document.getElementById('sitmap-on').click(); document.getElementById('front-on').click();")

        # 6. Cartes militaires GSGS + rideau
        ev("$gsgs('Normandie');")
        wait(1500)
        ev("_m.setView([49.183, -0.37], 13, {animate:false});")
        ev("$cap('83 cartes militaires britanniques de 1943, calées au mètre près — ici Caen');")
        wait(4500)
        ev("document.querySelector('.swipe-toggle').click();")
        ev("$cap('Le rideau « Comparer » : 1943 à gauche, aujourd\\'hui à droite');")
        wait(1200)
        x0 = 340 + (W - 340) // 2
        pg.mouse.move(x0, H // 2)
        pg.mouse.down()
        for x in list(range(x0, W - 120, 12)) + list(range(W - 120, 420, -12)) + list(range(420, x0, 12)):
            pg.mouse.move(x, H // 2)
            wait(16)
        pg.mouse.up()
        wait(1200)
        ev("document.querySelector('.swipe-toggle').click(); $gsgs('Normandie');")
        ev("const b=[...document.querySelectorAll('#gsgs-series input')].find(x=>x.parentElement.textContent.includes('Normandie')); if (b.checked) b.click();")

        # 7. LiDAR | satellite
        ev("$layer('Satellite');")
        ev("_m.setView([49.3955, -0.9890], 17, {animate:false});")
        wait(800)
        ev("$layer('France : relief LiDAR'); document.querySelector('.swipe-toggle').click();")
        ev("$cap('Relief LiDAR et satellite : les cratères de la pointe du Hoc (6 juin 1944)');")
        wait(6000)
        pg.mouse.move(x0, H // 2)
        pg.mouse.down()
        for x in list(range(x0, W - 100, 10)) + list(range(W - 100, x0, -10)):
            pg.mouse.move(x, H // 2)
            wait(16)
        pg.mouse.up()
        wait(2000)

        # 8. Fin
        ev("$cap('');")
        ev("$title('<div style=\"font-size:36px;font-weight:700\">Application Windows et code source</div>"
           "<div style=\"margin-top:14px;font-size:30px\">github.com/LaurentJack/WW2Map</div>"
           "<div style=\"margin-top:14px;opacity:.75;font-size:20px\">Données : archives publiques (Library of Congress, War Office, IGN, SPW, Wikidata, EHRI, OpenStreetMap)</div>');")
        wait(4500)
        video = pg.video.path()
        ctx.close()
        browser.close()
    mp4 = OUT / "demo.mp4"
    subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-i", str(video), "-c:v", "libx264", "-preset", "slow",
                    "-crf", "23", "-pix_fmt", "yuv420p", "-movflags", "+faststart", "-an", str(mp4)], check=True)
    shutil.rmtree(raw, ignore_errors=True)
    print(f"-> {mp4} ({mp4.stat().st_size / 1e6:.1f} Mo)")


if __name__ == "__main__":
    main()
