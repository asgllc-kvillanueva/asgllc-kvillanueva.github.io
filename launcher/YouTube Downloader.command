#!/bin/bash
# ─────────────────────────────────────────────
#   YouTube Downloader
#   Double-click to open. It installs itself the
#   first time and keeps itself up to date after.
#   Close the window to stop everything.
# ─────────────────────────────────────────────

REPO_ZIP="https://github.com/asgllc-kvillanueva/asgllc-kvillanueva.github.io/archive/refs/heads/main.zip"
INSTALL_DIR="$HOME/Library/Application Support/Playground Tools"

mkdir -p "$INSTALL_DIR"
cd "$INSTALL_DIR" || exit 1

# 1. Need a WORKING Python 3. Fresh Macs ship a stub that triggers Apple's
#    Command Line Developer Tools installer the first time it runs.
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

# 2. Pull the latest hub + apps from GitHub. App code is refreshed, but each
#    app's .venv is preserved so we don't reinstall every launch.
echo "Getting the latest version…"
TMP="$(mktemp -d)"
if curl -fsSL -o "$TMP/repo.zip" "$REPO_ZIP" && unzip -q -o "$TMP/repo.zip" -d "$TMP/x"; then
  SRC="$(ls -d "$TMP/x"/*/ 2>/dev/null | head -1)"
  if [ -n "$SRC" ] && [ -d "${SRC}hub" ]; then
    rm -rf "$INSTALL_DIR/hub"
    cp -R "${SRC}hub" "$INSTALL_DIR/hub"
    mkdir -p "$INSTALL_DIR/apps"
    for appdir in "${SRC}apps"/*/; do
      name="$(basename "$appdir")"
      mkdir -p "$INSTALL_DIR/apps/$name"
      # Sync code, never touch the app's installed environment.
      rsync -a --delete --exclude '.venv' "$appdir" "$INSTALL_DIR/apps/$name/"
    done
  fi
else
  echo "Couldn't reach GitHub — using the version already installed."
fi
rm -rf "$TMP"

if [ ! -d "$INSTALL_DIR/hub" ]; then
  echo
  echo "Nothing is installed yet and GitHub couldn't be reached."
  echo "Connect to the internet, then double-click YouTube Downloader again."
  read -n 1 -s -r -p "Press any key to close this window."
  exit 1
fi

# 3. Shared ffmpeg (built with libwebp, used by every app). Installed once.
if [ ! -f "$INSTALL_DIR/bin/ffmpeg" ]; then
  echo "Downloading ffmpeg (one time)…"
  mkdir -p "$INSTALL_DIR/bin"
  curl -sL -o "$INSTALL_DIR/bin/ffmpeg.zip" https://evermeet.cx/ffmpeg/getrelease/zip
  unzip -q -o "$INSTALL_DIR/bin/ffmpeg.zip" -d "$INSTALL_DIR/bin/"
  rm -f "$INSTALL_DIR/bin/ffmpeg.zip"
  chmod +x "$INSTALL_DIR/bin/ffmpeg" 2>/dev/null || true
fi

# 4. Run the hub (standard-library Python — no setup needed). It opens your
#    browser to the home page; each app installs itself the first time you pick it.
echo
echo "Starting…"
echo
cd "$INSTALL_DIR/hub"
python3 hub_server.py
