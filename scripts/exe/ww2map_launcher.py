"""Lanceur Windows de la carte WW2 (compilé par build_exe.py).

Deux formes :
  - exe autonome (dist/WW2Map.exe) : toute l'application (index.html, css, js, vendor, data) est une archive ZIP
    collée à la fin de l'exe ; les fichiers sont servis directement depuis l'archive, sans rien extraire ;
  - exe léger (WW2Map.exe à la racine du projet) : sert le dossier dans lequel il se trouve.
Au lancement :
  1. un petit serveur HTTP local (127.0.0.1, port libre) sert le dossier de l'exe : nécessaire car les navigateurs
     bloquent les données chargées depuis file:// ;
  2. la carte s'ouvre dans une fenêtre native (Edge WebView2, présent sur Windows 10/11) ;
     à défaut, dans le navigateur par défaut, avec une petite fenêtre « Fermer » pour arrêter le serveur.
Les fonds de carte et couches en ligne (OSM, IGN, LIDAR, satellite) demandent toujours une connexion internet.
"""
import functools
import http.server
import mimetypes
import shutil
import socket
import sys
import threading
import urllib.parse
import webbrowser
import zipfile
from pathlib import Path

TITLE = "Carte de la Seconde Guerre mondiale"


def app_dir() -> Path:
    if getattr(sys, "frozen", False):          # exe PyInstaller : dossier de l'exe
        return Path(sys.executable).resolve().parent
    return Path(__file__).resolve().parents[2]  # script : racine du projet


def embedded_zip():
    """Archive de l'application collée à la fin de l'exe (None si absente)."""
    if not getattr(sys, "frozen", False):
        return None
    try:
        z = zipfile.ZipFile(sys.executable)
        z.getinfo("index.html")
        return z
    except (zipfile.BadZipFile, KeyError, OSError):
        return None


class ZipHandler(http.server.BaseHTTPRequestHandler):
    """Sert les fichiers depuis l'archive ZIP (lecture directe, sans extraction)."""
    zf = None

    def log_message(self, *args):
        pass

    def _send(self, head_only=False):
        name = urllib.parse.unquote(urllib.parse.urlsplit(self.path).path).lstrip("/") or "index.html"
        try:
            info = self.zf.getinfo(name)
        except KeyError:
            self.send_error(404)
            return
        self.send_response(200)
        self.send_header("Content-Type", mimetypes.guess_type(name)[0] or "application/octet-stream")
        self.send_header("Content-Length", str(info.file_size))
        self.send_header("Cache-Control", "max-age=86400")
        self.end_headers()
        if not head_only:
            with self.zf.open(info) as f:
                shutil.copyfileobj(f, self.wfile, 1 << 20)

    def do_GET(self):
        try:
            self._send()
        except OSError:  # fenêtre fermée pendant un transfert
            pass

    def do_HEAD(self):
        self._send(head_only=True)


class QuietHandler(http.server.SimpleHTTPRequestHandler):
    def log_message(self, *args):  # pas de console : on ne journalise pas
        pass

    def end_headers(self):
        self.send_header("Cache-Control", "no-cache")
        super().end_headers()


def free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def error_box(msg: str):
    try:
        import ctypes
        ctypes.windll.user32.MessageBoxW(None, msg, TITLE, 0x10)
    except Exception:  # noqa: BLE001
        print(msg)


def main():
    mimetypes.add_type("image/webp", ".webp")
    mimetypes.add_type("text/javascript", ".js")
    zf = embedded_zip()
    root = app_dir()
    if zf is not None:
        ZipHandler.zf = zf
        handler = ZipHandler
    elif (root / "index.html").exists():
        handler = functools.partial(QuietHandler, directory=str(root))
    else:
        error_box(f"index.html introuvable dans :\n{root}\n\nCet exe léger doit rester dans le dossier de la carte, "
                  "à côté de index.html et des dossiers css, js et data (ou utilisez l'exe autonome).")
        return
    port = free_port()
    server = http.server.ThreadingHTTPServer(("127.0.0.1", port), handler)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    url = f"http://127.0.0.1:{port}/index.html"
    try:
        import webview  # pywebview → Edge WebView2
        webview.create_window(TITLE, url, width=1400, height=900, min_size=(800, 600))
        webview.start(private_mode=False)
    except Exception:  # noqa: BLE001  WebView2 absent : navigateur par défaut
        webbrowser.open(url)
        import tkinter as tk
        w = tk.Tk()
        w.title(TITLE)
        tk.Label(w, text="La carte est ouverte dans votre navigateur.\nFermez cette fenêtre pour arrêter la carte.",
                 padx=20, pady=15).pack()
        tk.Button(w, text="Fermer", command=w.destroy, padx=12).pack(pady=(0, 12))
        w.mainloop()
    finally:
        server.shutdown()


if __name__ == "__main__":
    main()
