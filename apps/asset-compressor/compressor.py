import eel
import os
import subprocess
import json
import bottle
import threading
import tempfile
import glob
import shutil
import re

# Initialize Eel
eel.init('web')

# ─── Video Serving ───────────────────────────────────────────────────────
_current_video_path = None
_serve_port = 8089

video_app = bottle.Bottle()

@video_app.route('/stream')
def stream_video():
    if not _current_video_path or not os.path.isfile(_current_video_path):
        bottle.abort(404, "No video loaded")
    return bottle.static_file(
        os.path.basename(_current_video_path),
        root=os.path.dirname(_current_video_path),
        mimetype='video/mp4'
    )

def _start_video_server():
    video_app.run(host='127.0.0.1', port=_serve_port, quiet=True)

# ─── Native macOS File Dialogs ───────────────────────────────────────────

@eel.expose
def select_video():
    global _current_video_path
    script = '''
    set theFile to choose file with prompt "Select Video File" of type {"com.apple.quicktime-movie", "public.mpeg-4", "public.movie"}
    return POSIX path of theFile
    '''
    result = subprocess.run(['osascript', '-e', script], capture_output=True, text=True)
    if result.returncode == 0:
        path = result.stdout.strip()
        _current_video_path = path
        return path
    return None

@eel.expose
def select_output_folder():
    script = '''
    set theFolder to choose folder with prompt "Select Output Folder"
    return POSIX path of theFolder
    '''
    result = subprocess.run(['osascript', '-e', script], capture_output=True, text=True)
    if result.returncode == 0:
        return result.stdout.strip()
    return None

@eel.expose
def get_video_serve_url():
    return f'http://127.0.0.1:{_serve_port}/stream'

# ─── YouTube Download via yt-dlp ─────────────────────────────────────────

@eel.expose
def download_youtube(url):
    global _current_video_path
    try:
        # Check yt-dlp exists
        if not shutil.which('yt-dlp'):
            return {"success": False, "error": "yt-dlp not found. Install via: brew install yt-dlp"}

        # Create a persistent temp directory for downloads
        dl_dir = os.path.join(tempfile.gettempdir(), 'asset_comp_yt')
        os.makedirs(dl_dir, exist_ok=True)

        eel.update_yt_status("⏳ Fetching video info…")()

        # Get the video title first for display
        title_cmd = ['yt-dlp', '--print', 'title', '--no-warnings', url]
        title_result = subprocess.run(title_cmd, capture_output=True, text=True, timeout=30)
        video_title = title_result.stdout.strip() or "youtube_video"

        # Clean filename
        safe_title = re.sub(r'[^\w\s-]', '', video_title)[:60].strip()

        eel.update_yt_status(f"⬇️ Downloading: {safe_title}…")()

        output_template = os.path.join(dl_dir, f'{safe_title}.%(ext)s')

        # Download best mp4 (h264) video+audio merged
        cmd = [
            'yt-dlp',
            '-f', 'bestvideo[ext=mp4]+bestaudio[ext=m4a]/best[ext=mp4]/best',
            '--merge-output-format', 'mp4',
            '-o', output_template,
            '--no-playlist',
            '--no-warnings',
            url
        ]

        process = subprocess.Popen(
            cmd, stderr=subprocess.PIPE, stdout=subprocess.PIPE,
            universal_newlines=True, bufsize=1
        )

        # Read stdout for download progress
        for line in process.stdout:
            line = line.strip()
            if '[download]' in line and '%' in line:
                eel.update_yt_status(f"⬇️ {line}")()

        process.wait()

        if process.returncode != 0:
            stderr = process.stderr.read() if process.stderr else ""
            return {"success": False, "error": f"yt-dlp failed: {stderr[:200]}"}

        # Find the downloaded file
        downloaded = glob.glob(os.path.join(dl_dir, f'{safe_title}.*'))
        mp4_files = [f for f in downloaded if f.endswith('.mp4')]

        if not mp4_files:
            return {"success": False, "error": "Download completed but no MP4 file found."}

        dl_path = mp4_files[0]
        _current_video_path = dl_path

        return {
            "success": True,
            "path": dl_path,
            "title": safe_title
        }

    except subprocess.TimeoutExpired:
        return {"success": False, "error": "Download timed out."}
    except Exception as e:
        return {"success": False, "error": str(e)}

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
    result = subprocess.run(['ffmpeg', '-encoders'], capture_output=True, text=True)
    return 'libwebp' in result.stdout

def _run_ffmpeg_with_progress(cmd, duration_sec, step_num, total_steps, label):
    """
    Run an FFmpeg command via Popen, parse stderr in real-time for
    time= progress, and push percentage updates to the JS frontend.
    """
    process = subprocess.Popen(
        cmd, stderr=subprocess.PIPE, stdout=subprocess.PIPE,
        universal_newlines=True, bufsize=1
    )

    # FFmpeg writes progress to stderr in lines like:
    #   frame=   45 fps= 30 ... time=00:00:03.00 ...
    # We parse out the time= value and compare to total duration.
    time_pattern = re.compile(r'time=(\d+):(\d+):(\d+\.\d+)')
    stderr_lines = []

    for line in process.stderr:
        stderr_lines.append(line)
        match = time_pattern.search(line)
        if match:
            h, m, s = int(match.group(1)), int(match.group(2)), float(match.group(3))
            current_time = h * 3600 + m * 60 + s
            if duration_sec > 0:
                pct = min(current_time / duration_sec, 1.0)
                eel.update_progress(step_num, total_steps, f'{label} — {pct*100:.0f}%')()

    process.wait()
    return process.returncode, "".join(stderr_lines)

def _generate_webp_via_img2webp(input_file, t_in, t_out, crop_w, crop_h, crop_x, crop_y,
                                 fps, quality, output_path, step_num, total_steps):
    """
    Generate animated WebP via frame extraction + img2webp.
    Uses -lossy and -m 4 (good balance of speed vs compression).
    Shows frame extraction progress.
    """
    tmpdir = tempfile.mkdtemp(prefix='asset_comp_')
    duration = t_out - t_in
    try:
        frame_pattern = os.path.join(tmpdir, 'frame_%05d.png')
        cmd_frames = [
            'ffmpeg', '-y',
            '-i', input_file,
            '-ss', str(t_in), '-to', str(t_out),
            '-vf', f'crop={crop_w}:{crop_h}:{crop_x}:{crop_y},scale=360:540,fps={fps}',
            '-an',
            frame_pattern
        ]

        # Run frame extraction with progress
        _run_ffmpeg_with_progress(cmd_frames, duration, step_num, total_steps, 'WebP: extracting frames')

        frames = sorted(glob.glob(os.path.join(tmpdir, 'frame_*.png')))
        if not frames:
            return False, "No frames were extracted."

        total_frames = len(frames)
        delay_ms = int(round(1000.0 / fps))

        eel.update_progress(step_num, total_steps, f'WebP: combining {total_frames} frames…')()

        # -lossy is CRITICAL for small file size
        # -m 4 = good compression speed (6 is best but very slow)
        cmd_webp = ['img2webp', '-loop', '0', '-lossy', '-q', str(quality), '-m', '4']
        for f in frames:
            cmd_webp.extend(['-d', str(delay_ms), f])
        cmd_webp.extend(['-o', output_path])

        res2 = subprocess.run(cmd_webp, capture_output=True, text=True)
        if res2.returncode != 0:
            return False, f"img2webp failed: {res2.stderr}"

        size_kb = os.path.getsize(output_path) / 1024
        return True, f"{size_kb:.0f} KB"
    finally:
        shutil.rmtree(tmpdir, ignore_errors=True)

# ─── Static PNG Capture ──────────────────────────────────────────────────

@eel.expose
def capture_static_png(params_json):
    try:
        params = json.loads(params_json)
        input_file = params.get('inputFile')
        output_dir = params.get('outputDir')
        static_time = params.get('staticTime', 0)
        mode = params.get('mode', 'custom')
        cx, cy, cw, ch = params.get('cropX'), params.get('cropY'), params.get('cropW'), params.get('cropH')
        export_scale_pct = params.get('exportScalePct', 100)

        if not input_file or not output_dir:
            return {"success": False, "error": "Select a video and output folder first."}

        base_name = os.path.splitext(os.path.basename(input_file))[0]
        png_out = _next_version(os.path.join(output_dir, f"{base_name}_custom_static.png"))

        base_w = int(cw * (export_scale_pct / 100.0))
        base_h = int(ch * (export_scale_pct / 100.0))

        # Ensure even dimensions
        base_w = base_w if base_w % 2 == 0 else base_w + 1
        base_h = base_h if base_h % 2 == 0 else base_h + 1

        cmd = [
            "ffmpeg", "-y",
            "-ss", str(static_time), "-i", input_file,
            "-frames:v", "1",
            "-vf", f"crop={cw}:{ch}:{cx}:{cy},scale={base_w}:{base_h}:flags=lanczos",
            "-update", "1",
            png_out
        ]
        r = subprocess.run(cmd, capture_output=True, text=True)
        if r.returncode != 0:
            return {"success": False, "error": f"PNG failed: {r.stderr}"}

        size_kb = os.path.getsize(png_out) / 1024
        return {"success": True, "message": f"Saved: {os.path.basename(png_out)} ({size_kb:.0f} KB) [{base_w}×{base_h}]"}

    except Exception as e:
        return {"success": False, "error": str(e)}

# ─── Main Export ─────────────────────────────────────────────────────────

@eel.expose
def process_assets(params_json):
    try:
        params = json.loads(params_json)
        input_file = params.get('inputFile')
        output_dir = params.get('outputDir')

        if not input_file or not output_dir:
            return {"success": False, "error": "Missing input or output paths."}

        do_webp = params.get('doWebP', True)
        do_gif  = params.get('doGIF', True)
        do_mov  = params.get('doMOV', True)
        do_png  = params.get('doPNG', True)

        selected = [do_webp, do_gif, do_mov, do_png]
        total = sum(selected)
        if total == 0:
            return {"success": False, "error": "No assets selected."}

        t_in = params.get('timeIn', 0)
        t_out = params.get('timeOut', 1)
        duration = t_out - t_in

        # The target coordinates and dimensions
        nx = params.get('cropX', 0)
        ny = params.get('cropY', 0)
        nw = params.get('cropW', 0)
        nh = params.get('cropH', 0)
        
        # Scaling is now applied uniformly to the output dimensions
        export_scale_pct = params.get('exportScalePct', 100)

        # Base Crop string
        crop_str = f"crop={nw}:{nh}:{nx}:{ny}"
        base_w = int(nw * (export_scale_pct / 100.0))
        base_h = int(nh * (export_scale_pct / 100.0))

        # Ensure even dimensions (FFmpeg requirement for some codecs like H.264)
        base_w = base_w if base_w % 2 == 0 else base_w + 1
        base_h = base_h if base_h % 2 == 0 else base_h + 1

        scale_str = f"scale={base_w}:{base_h}"
        vf_base = f"{crop_str},{scale_str}"

        static_time = params.get('staticTime', t_in)
        fps = params.get('fps', 15)
        webp_q = params.get('webpQuality', 60)
        gif_colors = params.get('gifColors', 128)
        gif_dither = params.get('gifDither', 'sierra2_4a')

        base_name = os.path.splitext(os.path.basename(input_file))[0]
        results = {}
        step = 0

        # ── WebP ─────────────────────────────────────────────────────
        if do_webp:
            step += 1
            webp_out = _next_version(os.path.join(output_dir, f"{base_name}_custom.webp"))

            if _has_libwebp():
                cmd = [
                    "ffmpeg", "-y", "-i", input_file,
                    "-ss", str(t_in), "-to", str(t_out),
                    "-vf", f"{vf_base},fps={fps}",
                    "-vcodec", "libwebp", "-lossless", "0",
                    "-q:v", str(webp_q), "-loop", "0", "-an",
                    webp_out
                ]
                rc, _ = _run_ffmpeg_with_progress(cmd, duration, step, total, 'WebP')
                if rc == 0:
                    size_kb = os.path.getsize(webp_out) / 1024
                    results['WebP'] = (True, f"{os.path.basename(webp_out)} ({size_kb:.0f} KB) [{base_w}×{base_h}]")
                else:
                    results['WebP'] = (False, "FFmpeg libwebp encode failed")
            else:
                ok, detail = _generate_webp_via_img2webp(
                    input_file, t_in, t_out, nw, nh, nx, ny, 
                    fps, webp_q, webp_out, step, total, base_w, base_h
                )
                if ok:
                    results['WebP'] = (True, f"{os.path.basename(webp_out)} ({detail}) [{base_w}×{base_h}]")
                else:
                    results['WebP'] = (False, detail)

        # ── GIF ──────────────────────────────────────────────────────
        if do_gif:
            step += 1
            gif_out = _next_version(os.path.join(output_dir, f"{base_name}_custom.gif"))

            if gif_colors > 256:
                palette_str = "palettegen=stats_mode=single"
                paletteuse_str = f"paletteuse=new=1:dither={gif_dither}"
            else:
                palette_str = f"palettegen=max_colors={gif_colors}"
                paletteuse_str = f"paletteuse=dither={gif_dither}"

            # We use the global `vf_base` which includes the crop and global scale
            vf_gif = (
                f"{vf_base},fps={fps},"
                f"split[s0][s1];[s0]{palette_str}[p];"
                f"[s1][p]{paletteuse_str}"
            )

            cmd = [
                "ffmpeg", "-y", "-i", input_file,
                "-ss", str(t_in), "-to", str(t_out),
                "-vf", vf_gif,
                "-loop", "0", "-an",
                gif_out
            ]
            rc, _ = _run_ffmpeg_with_progress(cmd, duration, step, total, 'GIF')
            if rc == 0:
                size_kb = os.path.getsize(gif_out) / 1024
                results['GIF'] = (True, f"{os.path.basename(gif_out)} ({size_kb:.0f} KB) [{base_w}×{base_h}]")
            else:
                results['GIF'] = (False, "GIF generation failed")

        # ── MOV ──────────────────────────────────────────────────────
        if do_mov:
            step += 1
            mov_out = _next_version(os.path.join(output_dir, f"{base_name}_custom.mov"))

            cmd = [
                "ffmpeg", "-y", "-i", input_file,
                "-ss", str(t_in), "-to", str(t_out),
                "-vf", f"{vf_base},fps={fps}",
                "-c:v", "libx264", "-pix_fmt", "yuv420p",
                "-c:a", "aac", "-movflags", "+faststart",
                mov_out
            ]
            rc, _ = _run_ffmpeg_with_progress(cmd, duration, step, total, 'MOV')
            if rc == 0:
                size_kb = os.path.getsize(mov_out) / 1024
                results['MOV'] = (True, f"{os.path.basename(mov_out)} ({size_kb:.0f} KB) [{base_w}×{base_h}]")
            else:
                results['MOV'] = (False, "MOV generation failed")

        # ── PNG ──────────────────────────────────────────────────────
        if do_png:
            step += 1
            eel.update_progress(step, total, 'PNG — capturing…')()
            png_out = _next_version(os.path.join(output_dir, f"{base_name}_{mode}.png"))

            cmd = [
                "ffmpeg", "-y",
                "-ss", str(static_time), "-i", input_file,
                "-frames:v", "1",
                "-vf", f"{vf_base}:flags=lanczos",
                "-pix_fmt", "rgb24",
                "-update", "1",
                png_out
            ]
            r = subprocess.run(cmd, capture_output=True, text=True)
            if r.returncode == 0:
                size_kb = os.path.getsize(png_out) / 1024
                results['PNG'] = (True, f"{os.path.basename(png_out)} ({size_kb:.0f} KB)")
            else:
                results['PNG'] = (False, r.stderr)

        # ── Summary ──────────────────────────────────────────────────
        succeeded = sum(1 for ok, _ in results.values() if ok)
        lines = []
        for name in ['WebP', 'GIF', 'MOV', 'PNG']:
            if name in results:
                ok, detail = results[name]
                icon = '✅' if ok else '❌'
                lines.append(f"{icon} {name}: {detail}")

        summary = "\n".join(lines)
        if succeeded == total:
            return {"success": True, "message": summary}
        else:
            return {"success": False, "error": summary}

    except Exception as e:
        return {"success": False, "error": str(e)}

if __name__ == '__main__':
    server_thread = threading.Thread(target=_start_video_server, daemon=True)
    server_thread.start()
    eel.start('compressor.html', size=(1200, 800), position=(100, 100))
