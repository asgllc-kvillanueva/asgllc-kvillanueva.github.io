import os
import sys
import subprocess
import threading
import webbrowser
import queue
import uuid
import json
from flask import Flask, render_template, request, jsonify, Response
import yt_dlp

app = Flask(__name__)
active_downloads = {}

@app.after_request
def add_cors_headers(response):
    response.headers['Access-Control-Allow-Origin'] = '*'
    response.headers['Access-Control-Allow-Headers'] = 'Content-Type'
    response.headers['Access-Control-Allow-Methods'] = 'GET, POST, OPTIONS'
    return response

# Configure settings file
SETTINGS_FILE = os.path.join(os.path.expanduser('~'), '.yt_downloader_settings.json')

def load_settings():
    if os.path.exists(SETTINGS_FILE):
        try:
            with open(SETTINGS_FILE, 'r') as f:
                return json.load(f)
        except:
            pass
    return {}

def save_settings(settings):
    try:
        with open(SETTINGS_FILE, 'w') as f:
            json.dump(settings, f)
    except Exception as e:
        print(f"Could not save settings: {e}")

# ── Machine mode: "corp" (locked-down, Santa-safe) vs "personal" (full quality).
# Shared with the Asset Compressor via one settings file under Playground Tools,
# so flipping it in either app carries over. Default is the SAFE "corp".
_PG_DIR = os.path.join(os.path.expanduser('~'), 'Library', 'Application Support', 'Playground Tools')
_MODE_SETTINGS = os.path.join(_PG_DIR, 'settings.json')

def load_mode():
    try:
        with open(_MODE_SETTINGS) as f:
            m = json.load(f).get('machine_mode')
        if m in ('corp', 'personal'):
            return m
    except Exception:
        pass
    return 'corp'

def save_mode(mode):
    if mode not in ('corp', 'personal'):
        return
    data = {}
    try:
        with open(_MODE_SETTINGS) as f:
            data = json.load(f)
    except Exception:
        pass
    data['machine_mode'] = mode
    try:
        os.makedirs(_PG_DIR, exist_ok=True)
        with open(_MODE_SETTINGS, 'w') as f:
            json.dump(data, f)
    except Exception as e:
        print(f"Could not save machine mode: {e}")

# Corp mode: a single pre-muxed/progressive MP4 (no ffmpeg merge) — `18` (360p)
# is the reliable fallback that's virtually always present.
CORP_VIDEO_FORMAT = ('best[ext=mp4][vcodec!=none][acodec!=none]/'
                     '18/best[vcodec!=none][acodec!=none]/best')

def _sanitized_path():
    """PATH with Homebrew/usr-local removed so yt-dlp can't spawn the Santa-blocked
    Deno (JS challenge) or ffmpeg (merge) on the corp Mac — it degrades gracefully."""
    return os.pathsep.join([os.path.dirname(sys.executable), '/usr/bin', '/bin', '/usr/sbin', '/sbin'])

# Apply loaded settings
HOME = os.path.expanduser('~')
user_settings = load_settings()
DOWNLOAD_FOLDER = user_settings.get('download_folder', os.path.join(HOME, 'Downloads'))
FFMPEG_PATH = "ffmpeg" # Default to system PATH if not frozen

if getattr(sys, 'frozen', False):
    # If the application is run as a bundle, the PyInstaller bootloader
    # extends the sys module by a flag frozen=True and sets the app 
    # path into variable _MEIPASS'.
    
    # Locate the embedded ffmpeg binary inside the app bundle
    bundled_ffmpeg = os.path.join(sys._MEIPASS, 'bin', 'ffmpeg')
    if os.path.exists(bundled_ffmpeg):
        FFMPEG_PATH = bundled_ffmpeg
else:
    # If running locally from source, prioritize the /bin/ffmpeg folder if downloaded
    local_ffmpeg = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'bin', 'ffmpeg')
    if os.path.exists(local_ffmpeg):
        FFMPEG_PATH = local_ffmpeg

if not os.path.exists(DOWNLOAD_FOLDER):
    os.makedirs(DOWNLOAD_FOLDER)

def open_folder_dialog():
    """Opens the native macOS folder chooser (no Automation permission needed)."""
    try:
        script = 'POSIX path of (choose folder with prompt "Choose where to save downloads")'
        result = subprocess.run(['osascript', '-e', script], capture_output=True, text=True, check=True)
        folder_path = result.stdout.strip()
        return folder_path or None
    except subprocess.CalledProcessError:
        return None  # user canceled
    except Exception as e:
        print(f"Error opening folder dialog: {e}")
        return None

@app.route('/')
def index():
    return render_template('downloader.html', current_folder=DOWNLOAD_FOLDER)

@app.route('/change-folder', methods=['POST'])
def change_folder():
    global DOWNLOAD_FOLDER
    new_folder = open_folder_dialog()
    if new_folder:
        DOWNLOAD_FOLDER = new_folder
        settings = load_settings()
        settings['download_folder'] = DOWNLOAD_FOLDER
        save_settings(settings)
        return jsonify({'success': True, 'path': DOWNLOAD_FOLDER})
    return jsonify({'success': False, 'path': DOWNLOAD_FOLDER})

@app.route('/mode')
def get_mode():
    return jsonify({'mode': load_mode()})

@app.route('/set-mode', methods=['POST'])
def set_mode():
    mode = (request.json or {}).get('mode')
    if mode not in ('corp', 'personal'):
        return jsonify({'success': False, 'error': 'bad mode'}), 400
    save_mode(mode)
    return jsonify({'success': True, 'mode': mode})

@app.route('/shutdown', methods=['POST'])
def shutdown():
    """Shuts down the Flask server"""
    def kill_server():
        os._exit(0)
    
    # Schedule the shutdown to give time for the response to return to UI
    threading.Timer(0.5, kill_server).start()
    return jsonify({'success': True, 'message': 'Sever shutting down...'})

def process_download(job_id, urls, media_type, media_quality, download_folder):
    q = active_downloads[job_id]
    
    def my_hook(d):
        if d['status'] == 'downloading':
            downloaded = d.get('downloaded_bytes', 0)
            total = d.get('total_bytes') or d.get('total_bytes_estimate', 0)
            percent = (downloaded / total) * 100 if total > 0 else 0
            filename = os.path.basename(d.get('filename', 'Unknown'))
            q.put({'type': 'progress', 'percent': f'{percent:.1f}', 'filename': filename})

    mode = load_mode()  # 'corp' = Santa-safe / ~360p, 'personal' = full quality

    # Options base
    ydl_opts_base = {
        'noplaylist': True,
        'quiet': True,
        'no_warnings': True,
        'progress_hooks': [my_hook],
        # Bypass 403 Forbidden errors (YouTube anti-bot countermeasures)
        'nocheckcertificate': True,
        'legacyserverconnect': True,
        'http_headers': {
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
            'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8',
            'Accept-Language': 'en-us,en;q=0.5',
            'Sec-Fetch-Mode': 'navigate',
        },
    }

    if mode == 'corp':
        # Android client returns pre-deciphered URLs (no Deno JS challenge), and
        # we never merge — so no blocked binary is ever spawned on the corp Mac.
        ydl_opts_base['extractor_args'] = {'youtube': {'player_client': ['android']}}
    else:
        # Full quality: let yt-dlp use its default clients and the real ffmpeg.
        ydl_opts_base['ffmpeg_location'] = FFMPEG_PATH

    # Configure yt-dlp based on user selection
    if media_type == 'audio':
        ydl_opts_base['format'] = 'bestaudio/best'
        if mode == 'personal':
            # Convert to MP3 (needs ffmpeg). Corp mode keeps the native audio
            # container (usually .m4a) so no blocked binary is ever run.
            ydl_opts_base['postprocessors'] = [{
                'key': 'FFmpegExtractAudio',
                'preferredcodec': 'mp3',
                'preferredquality': '192',
            }]
    else:
        # Video / Video + Transcript.
        # Prefer H.264 mp4 (best QuickTime compatibility) and YouTube-style separate
        # streams, then fall back to combined single-file sources like TikTok and
        # Instagram, which serve one progressive file rather than split streams.
        if mode == 'corp':
            # Progressive only — no merge, so no ffmpeg. Caps at ~360p; the quality
            # dropdown can't raise this on a locked-down Mac.
            ydl_opts_base['format'] = CORP_VIDEO_FORMAT
        else:
            if media_quality in ('1080', '720', '480'):
                h = media_quality
                ydl_opts_base['format'] = (
                    f'bestvideo[height<={h}][ext=mp4][vcodec^=avc1]+bestaudio[ext=m4a]/'
                    f'bestvideo[height<={h}][ext=mp4]+bestaudio[ext=m4a]/'
                    f'bestvideo[height<={h}]+bestaudio/'
                    f'best[height<={h}][ext=mp4]/best[height<={h}]/best'
                )
            else:
                ydl_opts_base['format'] = (
                    'bestvideo[ext=mp4][vcodec^=avc1]+bestaudio[ext=m4a]/'
                    'bestvideo[ext=mp4]+bestaudio[ext=m4a]/'
                    'bestvideo+bestaudio/'
                    'best[ext=mp4]/best'
                )
            ydl_opts_base['merge_output_format'] = 'mp4'
            ydl_opts_base['postprocessors'] = [{
                'key': 'FFmpegVideoConvertor',
                'preferedformat': 'mp4',
            }]

        if media_type == 'video_transcript':
            ydl_opts_base['writesubtitles'] = True
            ydl_opts_base['writeautomaticsub'] = True
            ydl_opts_base['subtitlesformat'] = 'vtt/best'
        else:
            # Explicitly disable subtitles to prevent bleed-over logic from caching
            ydl_opts_base['writesubtitles'] = False
            ydl_opts_base['writeautomaticsub'] = False

    # In corp mode, hide Deno/ffmpeg from yt-dlp's child processes for the duration
    # of the download so Santa never sees a blocked binary launched. Restored after.
    saved_path = os.environ.get('PATH', '')
    if mode == 'corp':
        os.environ['PATH'] = _sanitized_path()
    try:
        for url in urls:
            try:
                current_opts = ydl_opts_base.copy()
                current_opts['outtmpl'] = os.path.join(download_folder, '%(title)s.%(ext)s')

                with yt_dlp.YoutubeDL(current_opts) as ydl:
                    q.put({'type': 'starting', 'url': url})
                    info = ydl.extract_info(url, download=True)
                    title = info.get('title', 'Video')
                    q.put({'type': 'success', 'title': title, 'url': url})
            except Exception as e:
                q.put({'type': 'error', 'error': str(e), 'url': url})
    finally:
        os.environ['PATH'] = saved_path

    q.put({'type': 'complete'})

@app.route('/start_download', methods=['POST', 'OPTIONS'])
def start_download():
    if request.method == 'OPTIONS':
        return '', 204
    data = request.json
    raw_urls = data.get('url', '')
    media_type = data.get('type') or 'video_transcript'
    media_quality = data.get('quality') or 'best'
    
    urls = [line.strip() for line in raw_urls.split('\n') if line.strip()]
    if not urls:
        return jsonify({'error': 'No URLs provided'}), 400

    # Ensure the parent folder exists and is writable before starting
    try:
        if not os.path.exists(DOWNLOAD_FOLDER):
            os.makedirs(DOWNLOAD_FOLDER, exist_ok=True)
    except OSError as e:
        if e.errno == 13: # Permission denied
            return jsonify({'error': f"Permission denied to create or access '{DOWNLOAD_FOLDER}'. macOS may be blocking the app's access to the external drive. Please grant 'Full Disk Access' or 'Removable Volumes' permission to the app in System Preferences -> Privacy & Security."}), 400
        return jsonify({'error': f"Failed to access folder '{DOWNLOAD_FOLDER}': {str(e)}"}), 400

    if not os.access(DOWNLOAD_FOLDER, os.W_OK):
        return jsonify({'error': f"Cannot write to '{DOWNLOAD_FOLDER}'. The volume might be read-only, or macOS is blocking access. Check System Preferences -> Privacy & Security -> Files and Folders."}), 400

    job_id = str(uuid.uuid4())
    active_downloads[job_id] = queue.Queue()

    # Pass DOWNLOAD_FOLDER to the thread so we don't hit global scoping issues
    threading.Thread(target=process_download, args=(job_id, urls, media_type, media_quality, DOWNLOAD_FOLDER)).start()
    
    return jsonify({'job_id': job_id})

@app.route('/stream/<job_id>')
def stream(job_id):
    def event_stream():
        q = active_downloads.get(job_id)
        if not q:
            yield f"data: {json.dumps({'type': 'error', 'error': 'Invalid Job'})}\n\n"
            return
            
        while True:
            msg = q.get()
            yield f"data: {json.dumps(msg)}\n\n"
            if msg.get('type') == 'complete':
                break
                
        # Cleanup
        if job_id in active_downloads:
            del active_downloads[job_id]
            
    return Response(event_stream(), mimetype='text/event-stream')

if __name__ == '__main__':
    # Start a timer to open the browser 1.25 seconds after the app starts
    threading.Timer(1.25, lambda: webbrowser.open("http://127.0.0.1:5001")).start()
    # Debug must be False to allow the server to be killed cleanly or run properly in pyinstaller
    app.run(debug=False, port=5001)
