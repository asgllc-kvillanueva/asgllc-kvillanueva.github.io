// ─── Element References ──────────────────────────────────────────────────
const btnBrowse = document.getElementById('btn-browse');
const filenameDisplay = document.getElementById('input-filename');
const btnOutput = document.getElementById('btn-output');
const outputDisplay = document.getElementById('output-foldername');
const btnExport = document.getElementById('btn-export');
const statusMsg = document.getElementById('status-message');

const ytUrlInput = document.getElementById('yt-url');
const btnYtDownload = document.getElementById('btn-yt-download');
const ytStatusDisplay = document.getElementById('yt-status');

const video = document.getElementById('source-video');
const cropContainer = document.getElementById('crop-container');

const inputCropW = document.getElementById('crop-width');
const inputCropH = document.getElementById('crop-height');
const btnLinkRatio = document.getElementById('btn-link-ratio');
const presetMotion = document.getElementById('preset-motion');
const presetStatic = document.getElementById('preset-static');
const presetNative = document.getElementById('preset-native');

const fpsInput = document.getElementById('fps');
const webpQualityInput = document.getElementById('webp-quality');
const webpVal = document.getElementById('webp-val');
const gifColorsInput = document.getElementById('gif-colors');
const gifScaleInput = document.getElementById('export-scale'); // Was nativeScaleInput
const gifDitherInput = document.getElementById('gif-dither');

const timelineSlider = document.getElementById('timeline-slider');
const btnPlayPause = document.getElementById('btn-play-pause');
const timeInInput = document.getElementById('time-in');
const timeOutInput = document.getElementById('time-out');
const durationDisplay = document.getElementById('time-duration');
const btnCaptureFrame = document.getElementById('btn-capture-frame');
const staticFrameTimeDisplay = document.getElementById('static-frame-time');

const progressContainer = document.getElementById('progress-container');
const progressLabel = document.getElementById('progress-label');
const progressFill = document.getElementById('progress-fill');

// Asset selection checkboxes
const chkWebP = document.getElementById('chk-webp');
const chkGIF = document.getElementById('chk-gif');
const chkMOV = document.getElementById('chk-mov');
const chkPNG = document.getElementById('chk-png');

// ─── Eel Callback: Python calls this to report per-asset progress ────────
eel.expose(update_progress);
function update_progress(current, total, label) {
    progressContainer.style.display = 'block';
    progressLabel.textContent = `${current}/${total} — ${label}`;
    progressFill.style.width = `${(current / total) * 100}%`;
}

// ─── Eel Callback: Python calls this for YT download status ──────────────
eel.expose(update_yt_status);
function update_yt_status(msg) {
    ytStatusDisplay.textContent = msg;
}

// ─── App State ───────────────────────────────────────────────────────────
let inputFile = null;
let outputFolder = null;
let videoNativeWidth = 0;
let videoNativeHeight = 0;
let isSeeking = false;
let isAspectRatioLinked = true;

// The logical dimensions the user wants to export (e.g. 1080x1920)
let targetW = 0;
let targetH = 0;

// The actual pixels the crop container takes up on screen
let containerDisplayW = 0;
let containerDisplayH = 0;

// The unified transform state for the video
let state = {
    scale: 1,
    tx: 0,
    ty: 0
};

let staticCaptureTime = 0;
// ─── WebP Quality Display ────────────────────────────────────────────────
webpQualityInput.addEventListener('input', (e) => {
    webpVal.textContent = e.target.value;
});

// ─── Timeline Slider ─────────────────────────────────────────────────────
noUiSlider.create(timelineSlider, {
    start: [0, 100],
    connect: true,
    range: { 'min': 0, 'max': 100 }
});

// ─── Drag to Pan ─────────────────────────────────────────────────────────
let isDragging = false;
let startX, startY;

cropContainer.addEventListener('mousedown', (e) => {
    if (!inputFile) return;
    isDragging = true;
    startX = e.clientX - state.tx;
    startY = e.clientY - state.ty;
});

window.addEventListener('mouseup', () => { isDragging = false; });

window.addEventListener('mousemove', (e) => {
    if (!isDragging || !inputFile) return;
    e.preventDefault();
    state.tx = e.clientX - startX;
    state.ty = e.clientY - startY;
    applyTransform();
});

// ─── Scroll to Zoom ──────────────────────────────────────────────────────
cropContainer.addEventListener('wheel', (e) => {
    if (!inputFile) return;
    e.preventDefault();

    const rect = cropContainer.getBoundingClientRect();
    const mouseX = e.clientX - rect.left;
    const mouseY = e.clientY - rect.top;

    const sx = (mouseX - state.tx) / state.scale;
    const sy = (mouseY - state.ty) / state.scale;

    const zoomFactor = 1.05;
    state.scale *= (e.deltaY < 0) ? zoomFactor : (1 / zoomFactor);

    const minScale = Math.max(
        containerDisplayW / videoNativeWidth,
        containerDisplayH / videoNativeHeight
    );
    if (state.scale < minScale) state.scale = minScale;

    state.tx = mouseX - sx * state.scale;
    state.ty = mouseY - sy * state.scale;

    applyTransform();
}, { passive: false });

// ─── Apply Transform + Clamp ─────────────────────────────────────────────
function applyTransform() {
    if (!inputFile) return;

    const scaledW = videoNativeWidth * state.scale;
    const scaledH = videoNativeHeight * state.scale;

    const minTx = containerDisplayW - scaledW;
    const minTy = containerDisplayH - scaledH;

    if (state.tx > 0) state.tx = 0;
    if (state.ty > 0) state.ty = 0;
    if (state.tx < minTx) state.tx = minTx;
    if (state.ty < minTy) state.ty = minTy;

    video.style.transform = `translate(${state.tx}px, ${state.ty}px) scale(${state.scale})`;
}

// ─── Cropper Sizing & Presets ─────────────────────────────────────────────
function updateDisplayBounds(forceZoomFit = false) {
    if (!targetW || !targetH) return;

    // Max constraints for the visual editor (roughly mimicking the old heights)
    const MAX_DISP_H = 540;
    // Calculate the visual aspect ratio
    const ratio = targetW / targetH;

    // Scale container down to fit screen while maintaining accurate aspect ratio
    if (targetH > MAX_DISP_H) {
        containerDisplayH = MAX_DISP_H;
        containerDisplayW = MAX_DISP_H * ratio;
    } else {
        containerDisplayH = targetH;
        containerDisplayW = targetW;
    }

    cropContainer.style.width = containerDisplayW + 'px';
    cropContainer.style.height = containerDisplayH + 'px';

    if (inputFile && videoNativeWidth > 0) {
        const minScale = Math.max(
            containerDisplayW / videoNativeWidth,
            containerDisplayH / videoNativeHeight
        );
        // Force the zoom to fit the new bounds if instructed, or if it's currently too small
        if (forceZoomFit || state.scale < minScale) {
            state.scale = minScale;

            // Center it
            const scaledW = videoNativeWidth * state.scale;
            const scaledH = videoNativeHeight * state.scale;
            state.tx = (containerDisplayW - scaledW) / 2;
            state.ty = (containerDisplayH - scaledH) / 2;
        }
    }
    applyTransform();
}

function loadPreset(presetName) {
    presetMotion.classList.remove('active');
    presetStatic.classList.remove('active');
    presetNative.classList.remove('active');

    if (presetName === 'motion') {
        presetMotion.classList.add('active');
        inputCropW.value = 360;
        inputCropH.value = 540;
    } else if (presetName === 'static') {
        presetStatic.classList.add('active');
        inputCropW.value = 682;
        inputCropH.value = 1024;
    } else if (presetName === 'native') {
        presetNative.classList.add('active');
        if (videoNativeWidth > 0) {
            inputCropW.value = videoNativeWidth;
            inputCropH.value = videoNativeHeight;
        } else {
            // Default empty state before video loads
            inputCropW.value = 1920;
            inputCropH.value = 1080;
        }
    }

    targetW = parseInt(inputCropW.value);
    targetH = parseInt(inputCropH.value);
    updateDisplayBounds(true);
}

presetMotion.addEventListener('click', () => loadPreset('motion'));
presetStatic.addEventListener('click', () => loadPreset('static'));
presetNative.addEventListener('click', () => loadPreset('native'));

inputCropW.addEventListener('change', (e) => {
    presetMotion.classList.remove('active');
    presetStatic.classList.remove('active');
    presetNative.classList.remove('active');

    let w = parseInt(e.target.value);
    if (!w || w < 10) { w = 10; e.target.value = w; }

    if (isAspectRatioLinked && targetW > 0) {
        const ratio = targetH / targetW;
        inputCropH.value = Math.round(w * ratio);
        targetH = parseInt(inputCropH.value);
    }
    targetW = w;
    updateDisplayBounds(true);
});

inputCropH.addEventListener('change', (e) => {
    presetMotion.classList.remove('active');
    presetStatic.classList.remove('active');
    presetNative.classList.remove('active');

    let h = parseInt(e.target.value);
    if (!h || h < 10) { h = 10; e.target.value = h; }

    if (isAspectRatioLinked && targetH > 0) {
        const ratio = targetW / targetH;
        inputCropW.value = Math.round(h * ratio);
        targetW = parseInt(inputCropW.value);
    }
    targetH = h;
    updateDisplayBounds(true);
});

btnLinkRatio.addEventListener('click', () => {
    isAspectRatioLinked = !isAspectRatioLinked;
    btnLinkRatio.classList.toggle('active', isAspectRatioLinked);
    btnLinkRatio.style.opacity = isAspectRatioLinked ? '1' : '0.5';
});

// ─── Browse Video ────────────────────────────────────────────────────────
btnBrowse.addEventListener('click', async () => {
    const filePath = await eel.select_video()();
    if (!filePath) return;

    inputFile = filePath;
    filenameDisplay.textContent = filePath.split('/').pop();

    const streamURL = await eel.get_video_serve_url()();
    video.src = streamURL + '?t=' + Date.now();

    video.onloadedmetadata = () => {
        videoNativeWidth = video.videoWidth;
        videoNativeHeight = video.videoHeight;

        loadPreset('native');

        const dur = video.duration;
        timelineSlider.noUiSlider.updateOptions({
            range: { 'min': 0, 'max': dur },
            start: [0, Math.min(dur, 5)]
        });
        staticCaptureTime = 0;
        staticFrameTimeDisplay.textContent = '0.00s';

        video.play();
        btnPlayPause.textContent = '⏸ Pause';
        checkReady();
    };

    video.onerror = () => {
        statusMsg.className = 'status-error';
        statusMsg.textContent = 'Cannot load video for preview.';
    };
});

// ─── YouTube Download ────────────────────────────────────────────────────
btnYtDownload.addEventListener('click', async () => {
    const url = ytUrlInput.value.trim();
    if (!url) {
        ytStatusDisplay.textContent = '⚠️ Paste a YouTube URL first.';
        return;
    }

    btnYtDownload.disabled = true;
    btnYtDownload.textContent = '⏳';
    ytStatusDisplay.textContent = '⏳ Starting download…';

    try {
        const result = await eel.download_youtube(url)();
        if (result.success) {
            inputFile = result.path;
            filenameDisplay.textContent = result.title + '.mp4';
            ytStatusDisplay.textContent = '✅ Downloaded! Loading preview…';

            // Load the downloaded video into the player
            const streamURL = await eel.get_video_serve_url()();
            video.src = streamURL + '?t=' + Date.now();

            video.onloadedmetadata = () => {
                videoNativeWidth = video.videoWidth;
                videoNativeHeight = video.videoHeight;

                loadPreset('native');
                const dur = video.duration;
                timelineSlider.noUiSlider.updateOptions({
                    range: { 'min': 0, 'max': dur },
                    start: [0, Math.min(dur, 5)]
                });
                staticCaptureTime = 0;
                staticFrameTimeDisplay.textContent = '0.00s';
                video.play();
                btnPlayPause.textContent = '⏸ Pause';
                ytStatusDisplay.textContent = '✅ Ready!';
                checkReady();
            };
        } else {
            ytStatusDisplay.textContent = '❌ ' + result.error;
        }
    } catch (err) {
        ytStatusDisplay.textContent = '❌ ' + err;
    }

    btnYtDownload.disabled = false;
    btnYtDownload.textContent = '⬇️';
});

// ─── Browse Output Folder ────────────────────────────────────────────────
btnOutput.addEventListener('click', async () => {
    const folderPath = await eel.select_output_folder()();
    if (folderPath) {
        outputFolder = folderPath;
        outputDisplay.textContent = folderPath;
        checkReady();
    }
});

function checkReady() {
    btnExport.disabled = !(inputFile && outputFolder);
}

// ─── Timeline Scrubbing ──────────────────────────────────────────────────
timelineSlider.noUiSlider.on('update', (values, handle) => {
    isSeeking = true;
    const inVal = parseFloat(values[0]);
    const outVal = parseFloat(values[1]);

    timeInInput.value = inVal.toFixed(2);
    timeOutInput.value = outVal.toFixed(2);
    durationDisplay.textContent = '(' + (outVal - inVal).toFixed(2) + 's)';

    if (handle === 0) video.currentTime = inVal;
    else if (handle === 1) video.currentTime = outVal;
});

timeInInput.addEventListener('change', () => {
    if (!inputFile) return;
    timelineSlider.noUiSlider.set([timeInInput.value, null]);
});

timeOutInput.addEventListener('change', () => {
    if (!inputFile) return;
    timelineSlider.noUiSlider.set([null, timeOutInput.value]);
});

timelineSlider.noUiSlider.on('end', () => { isSeeking = false; });

video.addEventListener('timeupdate', () => {
    if (isSeeking) return;
    const outVal = parseFloat(timelineSlider.noUiSlider.get()[1]);
    const inVal = parseFloat(timelineSlider.noUiSlider.get()[0]);
    if (video.currentTime >= outVal) video.currentTime = inVal;
});

btnPlayPause.addEventListener('click', () => {
    if (video.paused) {
        video.play();
        btnPlayPause.textContent = '⏸ Pause';
    } else {
        video.pause();
        btnPlayPause.textContent = '▶ Play';
    }
});

// ─── Static Frame Capture (instant, versioned) ──────────────────────────
// Each click immediately generates a PNG with _v1, _v2, etc.
btnCaptureFrame.addEventListener('click', async () => {
    if (!inputFile || !outputFolder) {
        statusMsg.className = 'status-error';
        statusMsg.textContent = 'Select a video and output folder first.';
        return;
    }

    staticCaptureTime = video.currentTime;
    staticFrameTimeDisplay.textContent = staticCaptureTime.toFixed(2) + 's';

    // Get the crop coordinates
    const crop = getNativeCrop();

    const params = {
        inputFile: inputFile,
        outputDir: outputFolder,
        staticTime: staticCaptureTime,
        cropX: crop.x,
        cropY: crop.y,
        cropW: crop.w,
        cropH: crop.h,
        exportScalePct: parseInt(gifScaleInput.value) || 100
    };

    btnCaptureFrame.disabled = true;
    btnCaptureFrame.textContent = '⏳ Saving…';

    try {
        const response = await eel.capture_static_png(JSON.stringify(params))();
        if (response.success) {
            statusMsg.className = 'status-success';
            statusMsg.textContent = response.message;
        } else {
            statusMsg.className = 'status-error';
            statusMsg.textContent = response.error;
        }
    } catch (err) {
        statusMsg.className = 'status-error';
        statusMsg.textContent = 'PNG capture failed.';
    }

    btnCaptureFrame.disabled = false;
    btnCaptureFrame.textContent = '📸 Capture PNG Now';
});

// ─── MATH: CSS Transform → FFmpeg Native Crop ───────────────────────────
function getNativeCrop() {
    if (!inputFile || videoNativeWidth === 0) return { x: 0, y: 0, w: 0, h: 0 };

    // The scale of the video relative to the original file
    const s = state.scale;

    // We divide by 's' to map our screen-space dimensions back to native-space
    let nH = Math.round(targetH / s);
    let nW = Math.round(targetW / s);

    // Ensure we don't accidentally ask FFmpeg for more pixels than exist
    nH = Math.min(nH, videoNativeHeight);
    nW = Math.min(nW, videoNativeWidth);

    // Ensure width and height are even (for yuv420p / H.264)
    nW -= nW % 2;
    nH -= nH % 2;

    // Absolute value of tx / ty gives the pixel offset into the video
    // Divide by 's' to map that screen-space offset back to native pixels
    let xOffset = Math.round(Math.abs(state.tx) / s);
    let yOffset = Math.round(Math.abs(state.ty) / s);

    // Keep the entire box within bounds
    if (xOffset + nW > videoNativeWidth) xOffset = videoNativeWidth - nW;
    if (yOffset + nH > videoNativeHeight) yOffset = videoNativeHeight - nH;

    return { x: xOffset, y: yOffset, w: nW, h: nH };
}

// ─── Export (selective) ──────────────────────────────────────────────────
btnExport.addEventListener('click', async () => {
    btnExport.disabled = true;
    statusMsg.className = 'status-processing';
    statusMsg.textContent = '';
    progressContainer.style.display = 'block';
    progressLabel.textContent = 'Starting…';
    progressFill.style.width = '0%';

    const crop = getNativeCrop();

    const vals = timelineSlider.noUiSlider.get();
    const tIn = parseFloat(vals[0]);
    const tOut = parseFloat(vals[1]);

    const params = {
        inputFile: inputFile,
        outputDir: outputFolder,
        timeIn: tIn,
        timeOut: tOut,

        cropX: crop.x,
        cropY: crop.y,
        cropW: crop.w,
        cropH: crop.h,
        exportScalePct: parseInt(gifScaleInput.value) || 100,

        staticTime: staticCaptureTime,

        fps: parseInt(fpsInput.value),
        webpQuality: parseInt(webpQualityInput.value),
        gifColors: parseInt(gifColorsInput.value),
        gifDither: gifDitherInput.value,

        // Which assets to generate
        doWebP: chkWebP.checked,
        doGIF: chkGIF.checked,
        doMOV: chkMOV.checked,
        doPNG: chkPNG.checked
    };

    try {
        const response = await eel.process_assets(JSON.stringify(params))();
        progressContainer.style.display = 'none';
        if (response.success) {
            statusMsg.className = 'status-success';
            statusMsg.textContent = response.message;
        } else {
            statusMsg.className = 'status-error';
            statusMsg.textContent = response.error;
            console.error(response.error);
        }
    } catch (err) {
        progressContainer.style.display = 'none';
        statusMsg.className = 'status-error';
        statusMsg.textContent = 'Unexpected error communicating with backend.';
        console.error(err);
    }

    btnExport.disabled = false;
});
