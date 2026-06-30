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
import shutil
import hashlib
import webbrowser
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

HUB_PORT = 8765

# A stable marker the /hub-id endpoint returns, so a second launch (or the
# launcher itself) can confirm the thing already on the port is OUR hub —
# not some unrelated local service — before reopening the browser to it.
HUB_MARKER = "playground-tools-hub"

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
        "url": "http://127.0.0.1:5002",
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

        # A marker stores the requirements signature of a SUCCESSFUL install.
        # Rebuild cleanly if it's missing (failed/partial) or requirements changed.
        marker = os.path.join(venv, ".setup_ok")
        try:
            with open(reqs, "rb") as f:
                cur_sig = hashlib.sha1(f.read()).hexdigest()
        except OSError:
            cur_sig = ""
        stored_sig = ""
        if os.path.exists(marker):
            try:
                with open(marker) as f:
                    stored_sig = f.read().strip()
            except OSError:
                pass
        if not os.path.exists(vpy) or not os.path.exists(marker) or stored_sig != cur_sig:
            if os.path.isdir(venv):
                shutil.rmtree(venv, ignore_errors=True)
            _set(aid, "installing", "Setting up — about a minute the first time…")
            subprocess.run(["python3", "-m", "venv", ".venv"], cwd=app_dir, check=True)
            subprocess.run([pip, "install", "--upgrade", "pip", "-q", *PIP_INDEX],
                           cwd=app_dir, check=True)
            if os.path.exists(reqs):
                # Force prebuilt wheels so NOTHING compiles on the machine. Building
                # C extensions (e.g. gevent) runs ./configure test binaries that a
                # corporate binary-authorization tool (Santa) blocks.
                subprocess.run([pip, "install", "--only-binary=:all:", "-r", "requirements.txt", *PIP_INDEX],
                               cwd=app_dir, check=True)
            with open(marker, "w") as f:
                f.write(cur_sig)
        else:
            # Keep yt-dlp current each launch (both apps rely on it).
            _set(aid, "starting", "Checking for updates…")
            try:
                subprocess.run([pip, "install", "--upgrade", "yt-dlp", "-q", "--only-binary=:all:", *PIP_INDEX],
                               cwd=app_dir, timeout=90)
            except Exception:
                pass

        # Launch the app in its own venv. PATH order: the app's venv, then the
        # trusted system locations (Homebrew/usr-local) where an IT-approved ffmpeg
        # lives, then our own bin/ as a fallback, then the inherited PATH.
        _set(aid, "starting", "Opening…")
        env = dict(os.environ)
        env["PATH"] = os.pathsep.join([
            os.path.join(venv, "bin"),
            "/opt/homebrew/bin", "/usr/local/bin",
            BIN_DIR, env.get("PATH", ""),
        ])
        proc = subprocess.Popen([vpy] + app["start"][1:], cwd=app_dir, env=env)
        procs[aid] = proc

        time.sleep(2)
        if proc.poll() is not None:
            _set(aid, "error", "The app closed unexpectedly on startup.")
            return
        _set(aid, "running", "Open in its own window")
    except subprocess.CalledProcessError as e:
        _set(aid, "error", "Setup failed — see the Terminal window for details.")
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
        elif self.path == "/hub-id":
            self._json(200, {"app": HUB_MARKER})
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


def _existing_hub_is_ours():
    """True if something already on HUB_PORT identifies itself as our hub."""
    import urllib.request
    try:
        with urllib.request.urlopen("http://127.0.0.1:%d/hub-id" % HUB_PORT, timeout=2) as r:
            return HUB_MARKER in r.read().decode("utf-8", "replace")
    except Exception:
        return False


def main():
    url = "http://127.0.0.1:%d/" % HUB_PORT
    try:
        httpd = ThreadingHTTPServer(("127.0.0.1", HUB_PORT), Handler)
    except OSError:
        # Port is taken. If it's our own hub already running, just reopen it.
        if _existing_hub_is_ours():
            print("Playground Tools is already open — reopened it in your browser.")
            webbrowser.open(url)
            return
        print("Port %d is being used by something else, so Playground Tools" % HUB_PORT)
        print("can't start. Close whatever is using it and try again.")
        return
    threading.Timer(1.0, lambda: webbrowser.open(url)).start()
    print("Playground Tools is running at %s" % url)
    print("Keep this window open while you work. Close it to stop everything.")
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        pass


if __name__ == "__main__":
    main()
