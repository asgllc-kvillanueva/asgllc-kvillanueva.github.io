import os
import re
import json
import glob
import queue
import tempfile
import threading
import subprocess
import webbrowser

from flask import Flask, render_template, request, jsonify, Response, send_file

app = Flask(__name__)
PORT = 5002

# ffmpeg is on PATH (the hub puts the shared bin/ directory there).
FFMPEG = "ffmpeg"

# Human-readable list of what you can load (shown in the UI).
ALLOWED_DESC = "MP4, MOV, M4V, WebM, AVI, and more"

# Server-side state. Single user, single window.
SELECTED = []          # list of absolute video paths
OUTPUT_DIR = None
progress_q = queue.Queue()


# ─── Helpers ─────────────────────────────────────────────────────────────
def _next_version(filepath):
    base, ext = os.path.splitext(filepath)
    v = 1
    while True:
        candidate = f"{base}_v{v}{ext}"
        if not os.path.exists(candidate):
            return candidate
        v += 1


def _has_libwebp():
    try:
        r = subprocess.run([FFMPEG, "-hide_banner", "-encoders"],
                           capture_output=True, text=True)
        return "libwebp" in r.stdout
    except Exception:
        return False


def _ffmpeg_with_progress(cmd, duration_sec, on_pct):
    """Run ffmpeg, parse time= from stderr, call on_pct(fraction 0..1)."""
    process = subprocess.Popen(cmd, stderr=subprocess.PIPE, stdout=subprocess.PIPE,
                               universal_newlines=True, bufsize=1)
    time_re = re.compile(r'time=(\d+):(\d+):(\d+\.\d+)')
    errbuf = []
    for line in process.stderr:
        errbuf.append(line)
        m = time_re.search(line)
        if m and duration_sec > 0:
            h, mn, s = int(m.group(1)), int(m.group(2)), float(m.group(3))
            cur = h * 3600 + mn * 60 + s
            on_pct(min(cur / duration_sec, 1.0))
    process.wait()
    return process.returncode, "".join(errbuf)


def _even(n):
    n = int(n)
    return n if n % 2 == 0 else n + 1


# ─── Routes: file + folder selection ─────────────────────────────────────
@app.route('/')
def index():
    return render_template('compressor.html', allowed=ALLOWED_DESC)


@app.route('/select-files', methods=['POST'])
def select_files():
    """Native macOS multi-file picker. Accepts any common video container."""
    global SELECTED
    script = (
        'set theFiles to choose file with prompt "Select one or more videos" '
        'of type {"public.movie","public.mpeg-4","com.apple.quicktime-movie","public.audiovisual-content"} '
        'with multiple selections allowed\n'
        'set out to ""\n'
        'repeat with f in theFiles\n'
        '  set out to out & POSIX path of f & linefeed\n'
        'end repeat\n'
        'return out'
    )
    try:
        r = subprocess.run(['osascript', '-e', script], capture_output=True, text=True)
        if r.returncode != 0:
            return jsonify({'files': _file_list()})  # user cancelled
        paths = [p for p in r.stdout.strip().splitlines() if p.strip()]
        for p in paths:
            if p not in SELECTED:
                SELECTED.append(p)
        return jsonify({'files': _file_list()})
    except Exception as e:
        return jsonify({'error': str(e)}), 400


@app.route('/clear-files', methods=['POST'])
def clear_files():
    global SELECTED
    SELECTED = []
    return jsonify({'files': []})


@app.route('/remove-file', methods=['POST'])
def remove_file():
    idx = (request.json or {}).get('index')
    if isinstance(idx, int) and 0 <= idx < len(SELECTED):
        SELECTED.pop(idx)
    return jsonify({'files': _file_list()})


@app.route('/select-output', methods=['POST'])
def select_output():
    global OUTPUT_DIR
    script = ('set theFolder to choose folder with prompt "Select Output Folder"\n'
              'return POSIX path of theFolder')
    try:
        r = subprocess.run(['osascript', '-e', script], capture_output=True, text=True)
        if r.returncode == 0:
            OUTPUT_DIR = r.stdout.strip()
            return jsonify({'path': OUTPUT_DIR})
        return jsonify({'path': OUTPUT_DIR})
    except Exception as e:
        return jsonify({'error': str(e)}), 400


@app.route('/video/<int:idx>')
def video(idx):
    if 0 <= idx < len(SELECTED) and os.path.isfile(SELECTED[idx]):
        return send_file(SELECTED[idx], conditional=True)
    return "Not found", 404


def _file_list():
    return [{'index': i, 'name': os.path.basename(p)} for i, p in enumerate(SELECTED)]


# ─── YouTube download (adds one video to the list) ───────────────────────
@app.route('/download-youtube', methods=['POST'])
def download_youtube():
    url = (request.json or {}).get('url', '').strip()
    if not url:
        return jsonify({'success': False, 'error': 'No URL.'})
    try:
        dl_dir = os.path.join(tempfile.gettempdir(), 'asset_comp_yt')
        os.makedirs(dl_dir, exist_ok=True)
        title_r = subprocess.run(['yt-dlp', '--print', 'title', '--no-warnings', url],
                                 capture_output=True, text=True, timeout=40)
        title = (title_r.stdout.strip() or 'video')
        safe = re.sub(r'[^\w\s-]', '', title)[:60].strip() or 'video'
        out_tmpl = os.path.join(dl_dir, f'{safe}.%(ext)s')
        cmd = ['yt-dlp', '-f', 'bestvideo[ext=mp4]+bestaudio[ext=m4a]/best[ext=mp4]/best',
               '--merge-output-format', 'mp4', '-o', out_tmpl, '--no-playlist', '--no-warnings', url]
        r = subprocess.run(cmd, capture_output=True, text=True)
        if r.returncode != 0:
            return jsonify({'success': False, 'error': r.stderr[-200:] if r.stderr else 'Download failed.'})
        files = [f for f in glob.glob(os.path.join(dl_dir, f'{safe}.*')) if f.endswith('.mp4')]
        if not files:
            return jsonify({'success': False, 'error': 'No MP4 produced.'})
        SELECTED.append(files[0])
        return jsonify({'success': True, 'index': len(SELECTED) - 1,
                        'name': os.path.basename(files[0]), 'files': _file_list()})
    except subprocess.TimeoutExpired:
        return jsonify({'success': False, 'error': 'Timed out fetching info.'})
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)})


# ─── Static PNG capture (single, from the previewed file) ────────────────
@app.route('/capture-png', methods=['POST'])
def capture_png():
    p = request.json or {}
    if not SELECTED or OUTPUT_DIR is None:
        return jsonify({'success': False, 'error': 'Select a video and output folder first.'})
    idx = p.get('index', 0)
    if not (0 <= idx < len(SELECTED)):
        idx = 0
    input_file = SELECTED[idx]
    cx, cy, cw, ch = p.get('cropX'), p.get('cropY'), p.get('cropW'), p.get('cropH')
    base_w = _even(cw * (p.get('exportScalePct', 100) / 100.0))
    base_h = _even(ch * (p.get('exportScalePct', 100) / 100.0))
    base_name = os.path.splitext(os.path.basename(input_file))[0]
    png_out = _next_version(os.path.join(OUTPUT_DIR, f"{base_name}_custom_static.png"))
    cmd = [FFMPEG, "-y", "-ss", str(p.get('staticTime', 0)), "-i", input_file,
           "-frames:v", "1",
           "-vf", f"crop={cw}:{ch}:{cx}:{cy},scale={base_w}:{base_h}:flags=lanczos",
           "-update", "1", png_out]
    r = subprocess.run(cmd, capture_output=True, text=True)
    if r.returncode != 0:
        return jsonify({'success': False, 'error': f"PNG failed: {r.stderr[-200:]}"})
    size_kb = os.path.getsize(png_out) / 1024
    return jsonify({'success': True,
                    'message': f"Saved: {os.path.basename(png_out)} ({size_kb:.0f} KB) [{base_w}×{base_h}]"})


# ─── Batch export (universal settings across every selected file) ────────
@app.route('/process', methods=['POST'])
def process():
    params = request.json or {}
    threading.Thread(target=_run_batch, args=(params,), daemon=True).start()
    return jsonify({'ok': True})


@app.route('/progress')
def progress():
    def gen():
        while True:
            item = progress_q.get()
            yield f"data: {json.dumps(item)}\n\n"
            if item.get('type') in ('done', 'error'):
                break
    return Response(gen(), mimetype='text/event-stream')


def _export_one(input_file, p, step, total, libwebp):
    """Render the selected formats for a single file. Returns list of (fmt, ok, detail)."""
    out = []
    base_name = os.path.splitext(os.path.basename(input_file))[0]
    t_in, t_out = p.get('timeIn', 0), p.get('timeOut', 1)
    duration = max(t_out - t_in, 0.01)
    nx, ny, nw, nh = p.get('cropX', 0), p.get('cropY', 0), p.get('cropW', 0), p.get('cropH', 0)
    base_w = _even(nw * (p.get('exportScalePct', 100) / 100.0))
    base_h = _even(nh * (p.get('exportScalePct', 100) / 100.0))
    vf_base = f"crop={nw}:{nh}:{nx}:{ny},scale={base_w}:{base_h}"
    fps = p.get('fps', 15)
    fname = os.path.basename(input_file)

    def push(fmt, pct):
        progress_q.put({'type': 'progress', 'current': step[0], 'total': total,
                        'file': fname, 'fmt': fmt, 'pct': pct})

    # WebP
    if p.get('doWebP'):
        step[0] += 1
        push('WebP', 0.0)
        webp_out = _next_version(os.path.join(OUTPUT_DIR, f"{base_name}_custom.webp"))
        if libwebp:
            cmd = [FFMPEG, "-y", "-i", input_file, "-ss", str(t_in), "-to", str(t_out),
                   "-vf", f"{vf_base},fps={fps}", "-vcodec", "libwebp", "-lossless", "0",
                   "-q:v", str(p.get('webpQuality', 60)), "-loop", "0", "-an", webp_out]
            rc, _ = _ffmpeg_with_progress(cmd, duration, lambda pc: push('WebP', pc))
            if rc == 0:
                kb = os.path.getsize(webp_out) / 1024
                out.append(('WebP', True, f"{os.path.basename(webp_out)} ({kb:.0f} KB)"))
            else:
                out.append(('WebP', False, "libwebp encode failed"))
        else:
            out.append(('WebP', False, "this ffmpeg has no libwebp"))

    # GIF
    if p.get('doGIF'):
        step[0] += 1
        push('GIF', 0.0)
        gif_out = _next_version(os.path.join(OUTPUT_DIR, f"{base_name}_custom.gif"))
        colors = p.get('gifColors', 128)
        dither = p.get('gifDither', 'sierra2_4a')
        if colors > 256:
            pg, pu = "palettegen=stats_mode=single", f"paletteuse=new=1:dither={dither}"
        else:
            pg, pu = f"palettegen=max_colors={colors}", f"paletteuse=dither={dither}"
        vf_gif = f"{vf_base},fps={fps},split[s0][s1];[s0]{pg}[p];[s1][p]{pu}"
        cmd = [FFMPEG, "-y", "-i", input_file, "-ss", str(t_in), "-to", str(t_out),
               "-vf", vf_gif, "-loop", "0", "-an", gif_out]
        rc, _ = _ffmpeg_with_progress(cmd, duration, lambda pc: push('GIF', pc))
        if rc == 0:
            kb = os.path.getsize(gif_out) / 1024
            out.append(('GIF', True, f"{os.path.basename(gif_out)} ({kb:.0f} KB)"))
        else:
            out.append(('GIF', False, "GIF generation failed"))

    # MOV
    if p.get('doMOV'):
        step[0] += 1
        push('MOV', 0.0)
        mov_out = _next_version(os.path.join(OUTPUT_DIR, f"{base_name}_custom.mov"))
        cmd = [FFMPEG, "-y", "-i", input_file, "-ss", str(t_in), "-to", str(t_out),
               "-vf", f"{vf_base},fps={fps}", "-c:v", "libx264", "-pix_fmt", "yuv420p",
               "-c:a", "aac", "-movflags", "+faststart", mov_out]
        rc, _ = _ffmpeg_with_progress(cmd, duration, lambda pc: push('MOV', pc))
        if rc == 0:
            kb = os.path.getsize(mov_out) / 1024
            out.append(('MOV', True, f"{os.path.basename(mov_out)} ({kb:.0f} KB)"))
        else:
            out.append(('MOV', False, "MOV generation failed"))

    # PNG (same mechanism as the Capture button)
    if p.get('doPNG'):
        step[0] += 1
        push('PNG', 0.0)
        png_out = _next_version(os.path.join(OUTPUT_DIR, f"{base_name}_custom_static.png"))
        cmd = [FFMPEG, "-y", "-ss", str(p.get('staticTime', t_in)), "-i", input_file,
               "-frames:v", "1",
               "-vf", f"crop={nw}:{nh}:{nx}:{ny},scale={base_w}:{base_h}:flags=lanczos",
               "-update", "1", png_out]
        r = subprocess.run(cmd, capture_output=True, text=True)
        if r.returncode == 0:
            kb = os.path.getsize(png_out) / 1024
            out.append(('PNG', True, f"{os.path.basename(png_out)} ({kb:.0f} KB)"))
        else:
            out.append(('PNG', False, "PNG failed"))
    return out


def _run_batch(p):
    try:
        if not SELECTED:
            progress_q.put({'type': 'error', 'message': 'No videos selected.'})
            return
        if OUTPUT_DIR is None:
            progress_q.put({'type': 'error', 'message': 'No output folder selected.'})
            return
        n_fmts = sum(bool(p.get(k)) for k in ('doWebP', 'doGIF', 'doMOV', 'doPNG'))
        if n_fmts == 0:
            progress_q.put({'type': 'error', 'message': 'No formats selected.'})
            return

        libwebp = _has_libwebp()
        total = len(SELECTED) * n_fmts
        step = [0]
        lines = []
        any_fail = False
        for f in list(SELECTED):
            results = _export_one(f, p, step, total, libwebp)
            lines.append(os.path.basename(f))
            for fmt, ok, detail in results:
                icon = '✅' if ok else '❌'
                if not ok:
                    any_fail = True
                lines.append(f"   {icon} {fmt}: {detail}")

        progress_q.put({'type': 'done', 'success': not any_fail,
                        'message': "\n".join(lines)})
    except Exception as e:
        progress_q.put({'type': 'error', 'message': str(e)})


if __name__ == '__main__':
    threading.Timer(1.0, lambda: webbrowser.open(f'http://127.0.0.1:{PORT}/')).start()
    app.run(host='127.0.0.1', port=PORT, threaded=True)
