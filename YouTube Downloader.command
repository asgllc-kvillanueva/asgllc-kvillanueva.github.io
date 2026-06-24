#!/bin/bash
# ─────────────────────────────────────────────
#   YouTube Downloader
#   Double-click to open. It installs itself the
#   first time and keeps itself up to date after.
#   Close the window to stop.
# ─────────────────────────────────────────────

REPO_ZIP="https://github.com/asgllc-kvillanueva/asgllc-kvillanueva.github.io/archive/refs/heads/main.zip"
APP_DIR="$HOME/Library/Application Support/YouTube Downloader"

mkdir -p "$APP_DIR"
cd "$APP_DIR" || exit 1

# 1. Need a WORKING Python 3. Fresh Macs ship a stub that triggers Apple's
#    Command Line Developer Tools installer the first time it runs. Trigger
#    that, then WAIT and continue on our own.
if ! python3 -c "" >/dev/null 2>&1; then
  echo "One-time setup: macOS needs Apple's Command Line Developer Tools."
  echo "  1. Click Install on the popup that appears"
  echo "  2. Agree to the license"
  echo
  echo "Leave this window open — it continues by itself once that finishes."
  xcode-select --install 2>/dev/null
  printf "Waiting for the install to finish"
  tries=0
  until python3 -c "" >/dev/null 2>&1; do
    printf "."
    sleep 5
    tries=$((tries + 1))
    if [ "$tries" -ge 360 ]; then
      echo
      echo "Taking a while. Once it's installed, double-click YouTube Downloader again."
      read -n 1 -s -r -p "Press any key to close this window."
      exit 0
    fi
  done
  echo
  echo "Python is ready — continuing…"
fi

# 2. Pull the latest app from GitHub. If offline, use the copy already here.
echo "Getting the latest version…"
TMP="$(mktemp -d)"
if curl -fsSL -o "$TMP/repo.zip" "$REPO_ZIP" && unzip -q -o "$TMP/repo.zip" -d "$TMP/x"; then
  SRC="$(ls -d "$TMP/x"/*/ 2>/dev/null | head -1)"
  if [ -n "$SRC" ] && [ -f "${SRC}app.py" ]; then
    cp "${SRC}app.py" "$APP_DIR/app.py"
    rm -rf "$APP_DIR/templates" "$APP_DIR/static"
    cp -R "${SRC}templates" "$APP_DIR/templates" 2>/dev/null
    cp -R "${SRC}static" "$APP_DIR/static" 2>/dev/null
  fi
else
  echo "Couldn't reach GitHub — using the version already installed."
fi
rm -rf "$TMP"

if [ ! -f "$APP_DIR/app.py" ]; then
  echo
  echo "Nothing is installed yet and GitHub couldn't be reached."
  echo "Connect to the internet, then double-click YouTube Downloader again."
  read -n 1 -s -r -p "Press any key to close this window."
  exit 1
fi

# 3. Python environment + dependencies (first run installs; later runs refresh yt-dlp).
if [ ! -d venv ]; then
  echo "First-time setup — about a minute…"
  python3 -m venv venv
  # shellcheck disable=SC1091
  source venv/bin/activate
  python3 -m pip install --upgrade pip >/dev/null 2>&1
  python3 -m pip install flask yt-dlp -i https://pypi.org/simple/
else
  # shellcheck disable=SC1091
  source venv/bin/activate
  python3 -m pip install --upgrade yt-dlp -i https://pypi.org/simple/ >/dev/null 2>&1 || true
fi

# 4. ffmpeg.
if [ ! -f bin/ffmpeg ]; then
  echo "Downloading ffmpeg…"
  mkdir -p bin
  curl -sL -o ffmpeg.zip https://evermeet.cx/ffmpeg/getrelease/zip
  unzip -q -o ffmpeg.zip -d bin/
  rm -f ffmpeg.zip
  chmod +x bin/ffmpeg
fi

# 5. Launch. app.py opens your browser at http://127.0.0.1:5001 itself.
echo
echo "Starting… your browser will open in a moment."
echo "Keep this window open while you work — closing it stops the app."
echo
python3 app.py
