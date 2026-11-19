"""Construit les deux formes du lanceur Windows :
  - WW2Map.exe à la racine du projet : exe léger qui sert le dossier où il se trouve ;
  - dist/WW2Map.exe : exe autonome, avec toute l'application (index.html, css, js, vendor, data) dans une
    archive ZIP collée à sa fin. Le lanceur lit cette archive directement, sans rien extraire ; le démarrage
    reste donc immédiat malgré la taille (≈ 700 Mo).

Environnement de construction (Python 3.11, PyInstaller n'existant pas encore pour 3.15) :
  py -3.11 -m venv scripts/.venv-exe
  scripts/.venv-exe/Scripts/python -m pip install pyinstaller pywebview pillow
  scripts/.venv-exe/Scripts/python scripts/exe/build_exe.py
"""
import shutil
import subprocess
import zipfile
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
WORK = ROOT / "scripts" / ".cache" / "exe_build"


def make_icon(path: Path):
    """Icône : épingle rouge sur un rond kaki (la couleur d'accent de l'application)."""
    from PIL import Image, ImageDraw
    S = 256
    im = Image.new("RGBA", (S, S), (0, 0, 0, 0))
    d = ImageDraw.Draw(im)
    d.ellipse((8, 8, S - 8, S - 8), fill=(91, 107, 58, 255))
    d.ellipse((78, 40, 178, 140), fill=(192, 57, 43, 255))
    d.polygon([(86, 112), (170, 112), (128, 214)], fill=(192, 57, 43, 255))
    d.ellipse((108, 70, 148, 110), fill=(255, 255, 255, 255))
    im.save(path, sizes=[(16, 16), (32, 32), (48, 48), (64, 64), (128, 128), (256, 256)])


def main():
    WORK.mkdir(parents=True, exist_ok=True)
    ico = WORK / "ww2map.ico"
    make_icon(ico)
    cmd = [sys.executable, "-m", "PyInstaller", "--noconfirm", "--clean", "--onefile", "--windowed",
           "--name", "WW2Map", "--icon", str(ico),
           "--distpath", str(WORK / "out"), "--workpath", str(WORK / "build"), "--specpath", str(WORK),
           str(HERE / "ww2map_launcher.py")]
    subprocess.run(cmd, check=True)
    light = WORK / "out" / "WW2Map.exe"
    try:
        shutil.copyfile(light, ROOT / "WW2Map.exe")
        print("->", ROOT / "WW2Map.exe")
    except PermissionError:
        print("!! WW2Map.exe est ouvert : l'exe léger à la racine n'a pas été remplacé (fermez-le et relancez)")
    standalone(light, ROOT / "dist" / "WW2Map.exe")


APP = ["index.html", "css", "js", "vendor", "data"]
STORED = {".webp", ".png", ".jpg", ".jpeg", ".gif"}  # déjà compressés : stockés tels quels (lecture directe)


def standalone(light: Path, out: Path):
    """Copie l'exe léger et colle l'application à sa fin (ZipFile en mode « a » sur un fichier qui n'est pas un ZIP
    ajoute l'archive en queue ; Python sait la relire malgré l'exe placé devant)."""
    out.parent.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(light, out)
    n = 0
    with zipfile.ZipFile(out, "a") as z:
        for item in APP:
            src = ROOT / item
            files = [src] if src.is_file() else sorted(f for f in src.rglob("*") if f.is_file())
            for f in files:
                arc = f.relative_to(ROOT).as_posix()
                comp = zipfile.ZIP_STORED if f.suffix.lower() in STORED else zipfile.ZIP_DEFLATED
                z.write(f, arc, compress_type=comp)
                n += 1
    print(f"-> {out} ({n} fichiers, {out.stat().st_size / 1e6:.0f} Mo)")


if __name__ == "__main__":
    main()
