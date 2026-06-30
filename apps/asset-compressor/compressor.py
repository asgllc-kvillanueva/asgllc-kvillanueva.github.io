import os
import re
import json
import glob
import queue
import tempfile
import threading
import subprocess
import webbrowser

import av
from PIL import Image
from flask import Flask, render_template, request, jsonify, Response, send_file

app = Flask(__name__)
PORT = 5002

# All video processing is done in-process with PyAV (the ffmpeg libraries as a
# Python library) and Pillow — no external ffmpeg binary is called. On the
# locked-down corporate Mac, Santa blocks unknown binaries but allows these
# prebuilt wheels to load as in-process libraries.

# Human-readable list of what you can load (shown in the UI).
ALLOWED_DESC = "MP4, MOV, M4V, WebM, AVI, and more"

# Extra yt-dlp flags for the YouTube path. The Android player client returns
# pre-deciphered stream URLs, so yt-dlp never runs YouTube's JavaScript "nsig"
# challenge — the step that otherwise tries to execute a JS runtime like Deno,
# which Santa blocks on the corporate Mac. (The Universal Downloader uses the
# same Android client; this keeps the two YouTube paths consistent.)
YT_COMPAT = ['--extractor-args', 'youtube:player_client=android',
             '--no-check-certificate', '--legacy-server-connect']

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


def _even(n):
    n = int(round(n))
    return n if n % 2 == 0 else n + 1


def _crop_scale(img, crop, size):
    """Crop (cx, cy, cw, ch) out of a PIL image, then resize to size (w, h)."""
    cx, cy, cw, ch = (int(round(v)) for v in crop)
    W, H = img.size
    cx = max(0, min(cx, max(W - 1, 0)))
    cy = max(0, min(cy, max(H - 1, 0)))
    cw = max(1, min(cw, W - cx))
    ch = max(1, min(ch, H - cy))
    img = img.crop((cx, cy, cx + cw, cy + ch))
    if img.size != tuple(size):
        img = img.resize(tuple(size), Image.LANCZOS)
    return img


def _grab_frame(input_file, t_sec, crop, size):
    """Return one cropped+scaled PIL image at (about) t_sec."""
    container = av.open(input_file)
    try:
        stream = container.streams.video[0]
        stream.thread_type = "AUTO"
        if t_sec > 0 and stream.time_base:
            try:
                container.seek(int(t_sec / stream.time_base), stream=stream, backward=True)
            except Exception:
                pass
        chosen = None
        for frame in container.decode(stream):
            chosen = frame
            if frame.time is not None and frame.time >= t_sec:
                break
        if chosen is None:
            raise RuntimeError("no frames decoded")
        return _crop_scale(chosen.to_image().convert("RGB"), crop, size)
    finally:
        container.close()


def _collect_frames(input_file, t_in, t_out, fps, crop, size, on_pct):
    """Decode the [t_in, t_out] window and return PIL frames sampled at `fps`.

    Uses the last decoded frame at or before each sample time, so output runs at
    a steady fps regardless of the source frame rate. `on_pct` gets 0..1.
    """
    interval = 1.0 / float(fps)
    sample_times = []
    t = t_in
    while t <= t_out + 1e-9:
        sample_times.append(t)
        t += interval
    total = max(len(sample_times), 1)

    frames = []
    si = 0
    prev_img = None

    container = av.open(input_file)
    try:
        stream = container.streams.video[0]
        stream.thread_type = "AUTO"
        if t_in > 0 and stream.time_base:
            try:
                container.seek(int(t_in / stream.time_base), stream=stream, backward=True)
            except Exception:
                pass
        for frame in container.decode(stream):
            ts = frame.time
            if ts is None:
                continue
            if ts < t_in:
                prev_img = frame  # keep the most recent frame before the window
                continue
            if ts > t_out:
                break
            # Emit every sample time that falls before this frame, using the frame
            # that was on screen at that moment (the previous one).
            while si < len(sample_times) and sample_times[si] < ts - 1e-9:
                src = prev_img if prev_img is not None else frame
                frames.append(_crop_scale(src.to_image().convert("RGB"), crop, size))
                si += 1
                on_pct(min(len(frames) / total, 0.99))
            prev_img = frame
        # Flush any remaining sample times with the last frame we saw.
        while si < len(sample_times) and prev_img is not None:
            frames.append(_crop_scale(prev_img.to_image().convert("RGB"), crop, size))
            si += 1
            on_pct(min(len(frames) / total, 0.99))
    finally:
        container.close()

    if not frames and prev_img is not None:
        frames.append(_crop_scale(prev_img.to_image().convert("RGB"), crop, size))
    on_pct(1.0)
    return frames


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
        title_r = subprocess.run(['yt-dlp', '--print', 'title', '--no-warnings', *YT_COMPAT, url],
                                 capture_output=True, text=True, timeout=40)
        title = (title_r.stdout.strip() or 'video')
        safe = re.sub(r'[^\w\s-]', '', title)[:60].strip() or 'video'
        out_tmpl = os.path.join(dl_dir, f'{safe}.%(ext)s')
        cmd = ['yt-dlp', '-f', 'bestvideo[ext=mp4]+bestaudio[ext=m4a]/best[ext=mp4]/best',
               '--merge-output-format', 'mp4', '-o', out_tmpl, '--no-playlist', '--no-warnings',
               *YT_COMPAT, url]
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
    try:
        img = _grab_frame(input_file, float(p.get('staticTime', 0)),
                          (cx, cy, cw, ch), (base_w, base_h))
        img.save(png_out, "PNG")
    except Exception as e:
        return jsonify({'success': False, 'error': f"PNG failed: {e}"})
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


def _export_one(input_file, p, step, total):
    """Render the selected formats for a single file. Returns list of (fmt, ok, detail)."""
    out = []
    base_name = os.path.splitext(os.path.basename(input_file))[0]
    t_in, t_out = float(p.get('timeIn', 0)), float(p.get('timeOut', 1))
    nx, ny, nw, nh = p.get('cropX', 0), p.get('cropY', 0), p.get('cropW', 0), p.get('cropH', 0)
    base_w = _even(nw * (p.get('exportScalePct', 100) / 100.0))
    base_h = _even(nh * (p.get('exportScalePct', 100) / 100.0))
    fps = int(p.get('fps', 15))
    frame_ms = max(int(round(1000.0 / fps)), 1)
    fname = os.path.basename(input_file)

    def push(fmt, pct):
        progress_q.put({'type': 'progress', 'current': step[0], 'total': total,
                        'file': fname, 'fmt': fmt, 'pct': pct})

    # The animated formats (WebP/GIF/MOV) share one decode pass over the window;
    # frames are decoded the first time one is needed and reused after that.
    frames = None

    def get_frames(fmt):
        nonlocal frames
        if frames is None:
            frames = _collect_frames(input_file, t_in, t_out, fps,
                                     (nx, ny, nw, nh), (base_w, base_h),
                                     lambda pc: push(fmt, pc))
        return frames

    # WebP (animated, via Pillow)
    if p.get('doWebP'):
        step[0] += 1
        push('WebP', 0.0)
        webp_out = _next_version(os.path.join(OUTPUT_DIR, f"{base_name}_custom.webp"))
        try:
            fr = get_frames('WebP')
            if not fr:
                raise RuntimeError("no frames in range")
            fr[0].save(webp_out, "WEBP", save_all=True, append_images=fr[1:],
                       duration=frame_ms, loop=0, lossless=False,
                       quality=int(p.get('webpQuality', 60)), method=4)
            push('WebP', 1.0)
            kb = os.path.getsize(webp_out) / 1024
            out.append(('WebP', True, f"{os.path.basename(webp_out)} ({kb:.0f} KB)"))
        except Exception as e:
            out.append(('WebP', False, f"WebP encode failed: {e}"))

    # GIF (animated, via Pillow palette quantize)
    if p.get('doGIF'):
        step[0] += 1
        push('GIF', 0.0)
        gif_out = _next_version(os.path.join(OUTPUT_DIR, f"{base_name}_custom.gif"))
        colors = min(int(p.get('gifColors', 128)), 256)
        dither = Image.Dither.NONE if p.get('gifDither') == 'none' else Image.Dither.FLOYDSTEINBERG
        try:
            fr = get_frames('GIF')
            if not fr:
                raise RuntimeError("no frames in range")
            pal = [im.quantize(colors=colors, dither=dither) for im in fr]
            pal[0].save(gif_out, "GIF", save_all=True, append_images=pal[1:],
                        duration=frame_ms, loop=0, disposal=2, optimize=True)
            push('GIF', 1.0)
            kb = os.path.getsize(gif_out) / 1024
            out.append(('GIF', True, f"{os.path.basename(gif_out)} ({kb:.0f} KB)"))
        except Exception as e:
            out.append(('GIF', False, f"GIF generation failed: {e}"))

    # MOV (H.264 / yuv420p, encoded with PyAV — video only)
    if p.get('doMOV'):
        step[0] += 1
        push('MOV', 0.0)
        mov_out = _next_version(os.path.join(OUTPUT_DIR, f"{base_name}_custom.mov"))
        try:
            fr = get_frames('MOV')
            if not fr:
                raise RuntimeError("no frames in range")
            container = av.open(mov_out, mode='w', options={'movflags': '+faststart'})
            try:
                vstream = container.add_stream('libx264', rate=fps)
                vstream.width = base_w
                vstream.height = base_h
                vstream.pix_fmt = 'yuv420p'
                n = len(fr)
                for i, im in enumerate(fr):
                    vframe = av.VideoFrame.from_image(im)
                    for packet in vstream.encode(vframe):
                        container.mux(packet)
                    if i % 5 == 0:
                        push('MOV', min((i + 1) / n, 0.99))
                for packet in vstream.encode():
                    container.mux(packet)
            finally:
                container.close()
            push('MOV', 1.0)
            kb = os.path.getsize(mov_out) / 1024
            out.append(('MOV', True, f"{os.path.basename(mov_out)} ({kb:.0f} KB)"))
        except Exception as e:
            out.append(('MOV', False, f"MOV generation failed: {e}"))

    # PNG (single still frame, via PyAV → Pillow)
    if p.get('doPNG'):
        step[0] += 1
        push('PNG', 0.0)
        png_out = _next_version(os.path.join(OUTPUT_DIR, f"{base_name}_custom_static.png"))
        try:
            img = _grab_frame(input_file, float(p.get('staticTime', t_in)),
                              (nx, ny, nw, nh), (base_w, base_h))
            img.save(png_out, "PNG")
            push('PNG', 1.0)
            kb = os.path.getsize(png_out) / 1024
            out.append(('PNG', True, f"{os.path.basename(png_out)} ({kb:.0f} KB)"))
        except Exception as e:
            out.append(('PNG', False, f"PNG failed: {e}"))

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

        total = len(SELECTED) * n_fmts
        step = [0]
        lines = []
        any_fail = False
        for f in list(SELECTED):
            results = _export_one(f, p, step, total)
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
