#!/usr/bin/env python3
"""
Playground Tools — hub server.

Pure standard library (no pip install needed) so the landing page opens
instantly. Each app gets its OWN virtual environment, created the first time
someone actually launches it. ffmpeg is shared across apps via PATH.
"""
import os
import sys
import json
import time
import threading
import subprocess
import webbrowser
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

HUB_PORT = 8765

HERE = os.path.dirname(os.path.abspath(__file__))        # .../Playground Tools/hub
INSTALL_DIR = os.path.dirname(HERE)                       # .../Playground Tools
APPS_DIR = os.path.join(INSTALL_DIR, "apps")
BIN_DIR = os.path.join(INSTALL_DIR, "bin")               # shared ffmpeg lives here
WEB_DIR = os.path.join(HERE, "web")

# Public PyPI directly + trusted hosts, so corporate SSL inspectors don't break pip.
PIP_INDEX = ["-i", "https://pypi.org/simple/",
             "--trusted-host", "pypi.org",
             "--trusted-host", "files.pythonhosted.org"]

# Registry of available apps. `start` is the command run inside the app's venv.
# `url` is opened on a repeat click (the app opens itself on first launch).
APPS = {
    "universal-downloader": {
        "name": "Universal Downloader",
        "start": ["python3", "downloader.py"],
        "url": "http://127.0.0.1:5001",
    },
    "asset-compressor": {
        "name": "Asset Compressor",
        "start": ["python3", "compressor.py"],
        "url": None,  # Eel opens its own window
    },
}

status = {aid: {"state": "idle", "message": ""} for aid in APPS}
procs = {}


def _set(aid, state, message=""):
    status[aid] = {"state": state, "message": message}


def ensure_and_launch(aid):
    app = APPS[aid]
    app_dir = os.path.join(APPS_DIR, aid)
    venv = os.path.join(app_dir, ".venv")
    vpy = os.path.join(venv, "bin", "python3")
    pip = os.path.join(venv, "bin", "pip")
    reqs = os.path.join(app_dir, "requirements.txt")

    try:
        # Already running? Re-open its URL if it has one.
        p = procs.get(aid)
        if p and p.poll() is None:
            _set(aid, "running", "Already open")
            if app["url"]:
                webbrowser.open(app["url"])
            return

        # First-time environment setup (isolated per app).
        if not os.path.exists(vpy):
            _set(aid, "installing", "Setting up — about a minute the first time…")
            subprocess.run(["python3", "-m", "venv", ".venv"], cwd=app_dir, check=True)
            subprocess.run([pip, "install", "--upgrade", "pip", "-q", *PIP_INDEX],
                           cwd=app_dir, check=True)
            if os.path.exists(reqs):
                subprocess.run([pip, "install", "-r", "requirements.txt", *PIP_INDEX],
                               cwd=app_dir, check=True)
        else:
            # Keep yt-dlp current each launch (both apps rely on it).
            _set(aid, "starting", "Checking for updates…")
            try:
                subprocess.run([pip, "install", "--upgrade", "yt-dlp", "-q", *PIP_INDEX],
                               cwd=app_dir, timeout=90)
            except Exception:
                pass

        # Launch the app in its own venv, with the shared bin/ on PATH for ffmpeg.
        _set(aid, "starting", "Opening…")
        env = dict(os.environ)
        env["PATH"] = os.pathsep.join([os.path.join(venv, "bin"), BIN_DIR, env.get("PATH", "")])
        proc = subprocess.Popen([vpy] + app["start"][1:], cwd=app_dir, env=env)
        procs[aid] = proc

        time.sleep(2)
        if proc.poll() is not None:
            _set(aid, "error", "The app closed unexpectedly on startup.")
            return
        _set(aid, "running", "Open in its own window")
    except subprocess.CalledProcessError as e:
        _set(aid, "error", "Setup failed. Check your internet and try again.")
        print("Setup error for %s: %s" % (aid, e))
    except Exception as e:
        _set(aid, "error", str(e))
        print("Launch error for %s: %s" % (aid, e))


class Handler(BaseHTTPRequestHandler):
    def log_message(self, *args):
        pass  # keep the Terminal window quiet

    def _json(self, code, obj):
        body = json.dumps(obj).encode()
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        if self.path in ("/", "/index.html"):
            try:
                with open(os.path.join(WEB_DIR, "hub.html"), "rb") as f:
                    body = f.read()
                self.send_response(200)
                self.send_header("Content-Type", "text/html; charset=utf-8")
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)
            except OSError:
                self._json(500, {"error": "landing page missing"})
        elif self.path.startswith("/status/"):
            aid = self.path[len("/status/"):]
            self._json(200, status.get(aid, {"state": "unknown", "message": ""}))
        else:
            self._json(404, {"error": "not found"})

    def do_POST(self):
        if self.path.startswith("/launch/"):
            aid = self.path[len("/launch/"):]
            if aid in APPS:
                threading.Thread(target=ensure_and_launch, args=(aid,), daemon=True).start()
                self._json(200, {"ok": True})
            else:
                self._json(404, {"error": "unknown app"})
        else:
            self._json(404, {"error": "not found"})


def main():
    httpd = ThreadingHTTPServer(("127.0.0.1", HUB_PORT), Handler)
    url = "http://127.0.0.1:%d/" % HUB_PORT
    threading.Timer(1.0, lambda: webbrowser.open(url)).start()
    print("Playground Tools is running at %s" % url)
    print("Keep this window open while you work. Close it to stop everything.")
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        pass


if __name__ == "__main__":
    main()
