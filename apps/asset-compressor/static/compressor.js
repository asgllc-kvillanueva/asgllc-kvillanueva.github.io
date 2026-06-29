// ─── Element References ──────────────────────────────────────────────────
const btnBrowse = document.getElementById('btn-browse');
const btnOutput = document.getElementById('btn-output');
const outputDisplay = document.getElementById('output-foldername');
const btnExport = document.getElementById('btn-export');
const statusMsg = document.getElementById('status-message');

const ytUrlInput = document.getElementById('yt-url');
const btnYtDownload = document.getElementById('btn-yt-download');
const ytStatusDisplay = document.getElementById('yt-status');

const fileListEl = document.getElementById('file-list');
const fileEmptyEl = document.getElementById('file-empty');
const btnClear = document.getElementById('btn-clear');
const previewName = document.getElementById('preview-name');

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
const gifScaleInput = document.getElementById('export-scale');
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

const chkWebP = document.getElementById('chk-webp');
const chkGIF = document.getElementById('chk-gif');
const chkMOV = document.getElementById('chk-mov');
const chkPNG = document.getElementById('chk-png');

// ─── App State ───────────────────────────────────────────────────────────
let files = [];          // [{index, name}] mirrored from the server
let activeIndex = 0;     // which file is shown in the cropper
let inputFile = null;    // truthy when a preview video is loaded (cropper guard)
let outputFolder = null;
let videoNativeWidth = 0;
let videoNativeHeight = 0;
let isSeeking = false;
let isAspectRatioLinked = true;
let targetW = 0;
let targetH = 0;
let containerDisplayW = 0;
let containerDisplayH = 0;
let state = { scale: 1, tx: 0, ty: 0 };
let staticCaptureTime = 0;
let progressES = null;

// ─── Helpers ─────────────────────────────────────────────────────────────
async function postJSON(url, body) {
    const r = await fetch(url, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: body ? JSON.stringify(body) : '{}'
    });
    return r.json();
}

webpQualityInput.addEventListener('input', (e) => { webpVal.textContent = e.target.value; });

// ─── Timeline Slider ─────────────────────────────────────────────────────
noUiSlider.create(timelineSlider, {
    start: [0, 100], connect: true, range: { 'min': 0, 'max': 100 }
});

// ─── Drag to Pan ─────────────────────────────────────────────────────────
let isDragging = false, startX, startY;
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
    const minScale = Math.max(containerDisplayW / videoNativeWidth, containerDisplayH / videoNativeHeight);
    if (state.scale < minScale) state.scale = minScale;
    state.tx = mouseX - sx * state.scale;
    state.ty = mouseY - sy * state.scale;
    applyTransform();
}, { passive: false });

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

function updateDisplayBounds(forceZoomFit = false) {
    if (!targetW || !targetH) return;
    const MAX_DISP_H = 540;
    const ratio = targetW / targetH;
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
        const minScale = Math.max(containerDisplayW / videoNativeWidth, containerDisplayH / videoNativeHeight);
        if (forceZoomFit || state.scale < minScale) {
            state.scale = minScale;
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
        inputCropW.value = 360; inputCropH.value = 540;
    } else if (presetName === 'static') {
        presetStatic.classList.add('active');
        inputCropW.value = 682; inputCropH.value = 1024;
    } else if (presetName === 'native') {
        presetNative.classList.add('active');
        if (videoNativeWidth > 0) {
            inputCropW.value = videoNativeWidth; inputCropH.value = videoNativeHeight;
        } else {
            inputCropW.value = 1920; inputCropH.value = 1080;
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
    presetMotion.classList.remove('active'); presetStatic.classList.remove('active'); presetNative.classList.remove('active');
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
    presetMotion.classList.remove('active'); presetStatic.classList.remove('active'); presetNative.classList.remove('active');
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

// ─── File list (multi-select) ────────────────────────────────────────────
function renderFileList(list) {
    files = list || [];
    fileListEl.innerHTML = '';
    fileEmptyEl.style.display = files.length ? 'none' : 'block';
    btnClear.style.display = files.length ? 'block' : 'none';
    files.forEach((f, i) => {
        const item = document.createElement('div');
        item.className = 'file-item' + (i === activeIndex ? ' active' : '');
        const name = document.createElement('span');
        name.className = 'file-item__name';
        name.textContent = f.name;
        name.addEventListener('click', () => loadPreview(i));
        const x = document.createElement('button');
        x.className = 'file-item__x';
        x.textContent = '×';
        x.title = 'Remove';
        x.addEventListener('click', (e) => { e.stopPropagation(); removeFile(i); });
        item.appendChild(name);
        item.appendChild(x);
        fileListEl.appendChild(item);
    });
    checkReady();
}

function clearPreview() {
    video.src = '';
    inputFile = null;
    videoNativeWidth = videoNativeHeight = 0;
    previewName.textContent = '';
}

function loadPreview(idx) {
    if (!files[idx]) return;
    activeIndex = idx;
    [...fileListEl.children].forEach((el, k) => el.classList.toggle('active', k === idx));
    previewName.textContent = '· ' + files[idx].name;
    inputFile = files[idx].name;
    video.src = `/video/${idx}?t=` + Date.now();
    video.onloadedmetadata = () => {
        videoNativeWidth = video.videoWidth;
        videoNativeHeight = video.videoHeight;
        loadPreset('native');
        const dur = video.duration || 1;
        timelineSlider.noUiSlider.updateOptions({ range: { 'min': 0, 'max': dur }, start: [0, Math.min(dur, 5)] });
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
}

async function removeFile(i) {
    const r = await postJSON('/remove-file', { index: i });
    const list = r.files || [];
    if (list.length === 0) {
        activeIndex = 0;
        clearPreview();
        renderFileList([]);
        return;
    }
    if (activeIndex >= list.length) activeIndex = list.length - 1;
    renderFileList(list);
    loadPreview(activeIndex);
}

btnBrowse.addEventListener('click', async () => {
    const wasEmpty = files.length === 0;
    const r = await postJSON('/select-files');
    renderFileList(r.files || []);
    if (wasEmpty && files.length > 0) loadPreview(0);
});

btnClear.addEventListener('click', async () => {
    await postJSON('/clear-files');
    activeIndex = 0;
    clearPreview();
    renderFileList([]);
});

// ─── YouTube Download (adds a file) ──────────────────────────────────────
btnYtDownload.addEventListener('click', async () => {
    const url = ytUrlInput.value.trim();
    if (!url) { ytStatusDisplay.textContent = '⚠️ Paste a YouTube URL first.'; return; }
    btnYtDownload.disabled = true;
    btnYtDownload.textContent = '⏳';
    ytStatusDisplay.textContent = '⏳ Downloading…';
    try {
        const result = await postJSON('/download-youtube', { url });
        if (result.success) {
            ytStatusDisplay.textContent = '✅ Added!';
            ytUrlInput.value = '';
            renderFileList(result.files || []);
            loadPreview(result.index);
        } else {
            ytStatusDisplay.textContent = '❌ ' + result.error;
        }
    } catch (err) {
        ytStatusDisplay.textContent = '❌ ' + err;
    }
    btnYtDownload.disabled = false;
    btnYtDownload.textContent = '⬇️';
});

// ─── Output Folder ───────────────────────────────────────────────────────
btnOutput.addEventListener('click', async () => {
    const r = await postJSON('/select-output');
    if (r.path) {
        outputFolder = r.path;
        outputDisplay.textContent = r.path;
        checkReady();
    }
});

function checkReady() {
    btnExport.disabled = !(files.length > 0 && outputFolder);
}

// ─── Timeline ────────────────────────────────────────────────────────────
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
timeInInput.addEventListener('change', () => { if (inputFile) timelineSlider.noUiSlider.set([timeInInput.value, null]); });
timeOutInput.addEventListener('change', () => { if (inputFile) timelineSlider.noUiSlider.set([null, timeOutInput.value]); });
timelineSlider.noUiSlider.on('end', () => { isSeeking = false; });

video.addEventListener('timeupdate', () => {
    if (isSeeking) return;
    const outVal = parseFloat(timelineSlider.noUiSlider.get()[1]);
    const inVal = parseFloat(timelineSlider.noUiSlider.get()[0]);
    if (video.currentTime >= outVal) video.currentTime = inVal;
});

btnPlayPause.addEventListener('click', () => {
    if (video.paused) { video.play(); btnPlayPause.textContent = '⏸ Pause'; }
    else { video.pause(); btnPlayPause.textContent = '▶ Play'; }
});

// ─── MATH: CSS Transform → FFmpeg Native Crop ───────────────────────────
function getNativeCrop() {
    if (!inputFile || videoNativeWidth === 0) return { x: 0, y: 0, w: 0, h: 0 };
    const s = state.scale;
    let nH = Math.round(targetH / s);
    let nW = Math.round(targetW / s);
    nH = Math.min(nH, videoNativeHeight);
    nW = Math.min(nW, videoNativeWidth);
    nW -= nW % 2;
    nH -= nH % 2;
    let xOffset = Math.round(Math.abs(state.tx) / s);
    let yOffset = Math.round(Math.abs(state.ty) / s);
    if (xOffset + nW > videoNativeWidth) xOffset = videoNativeWidth - nW;
    if (yOffset + nH > videoNativeHeight) yOffset = videoNativeHeight - nH;
    return { x: xOffset, y: yOffset, w: nW, h: nH };
}

// ─── Static PNG capture (single, the previewed file) ────────────────────
btnCaptureFrame.addEventListener('click', async () => {
    if (!inputFile || !outputFolder) {
        statusMsg.className = 'status-error';
        statusMsg.textContent = 'Select a video and output folder first.';
        return;
    }
    staticCaptureTime = video.currentTime;
    staticFrameTimeDisplay.textContent = staticCaptureTime.toFixed(2) + 's';
    const crop = getNativeCrop();
    const params = {
        index: activeIndex,
        staticTime: staticCaptureTime,
        cropX: crop.x, cropY: crop.y, cropW: crop.w, cropH: crop.h,
        exportScalePct: parseInt(gifScaleInput.value) || 100
    };
    btnCaptureFrame.disabled = true;
    btnCaptureFrame.textContent = '⏳ Saving…';
    try {
        const response = await postJSON('/capture-png', params);
        statusMsg.className = response.success ? 'status-success' : 'status-error';
        statusMsg.textContent = response.success ? response.message : response.error;
    } catch (err) {
        statusMsg.className = 'status-error';
        statusMsg.textContent = 'PNG capture failed.';
    }
    btnCaptureFrame.disabled = false;
    btnCaptureFrame.textContent = '📸 Capture PNG Now';
});

// ─── Batch Export (universal settings across every file) ─────────────────
function startProgressStream() {
    if (progressES) progressES.close();
    progressES = new EventSource('/progress');
    progressES.onmessage = (e) => {
        const d = JSON.parse(e.data);
        if (d.type === 'progress') {
            const overall = ((d.current - 1) + (d.pct || 0)) / d.total;
            progressFill.style.width = `${Math.max(0, Math.min(1, overall)) * 100}%`;
            progressLabel.textContent = `${d.current}/${d.total} · ${d.file} — ${d.fmt} ${Math.round((d.pct || 0) * 100)}%`;
        } else if (d.type === 'done') {
            progressES.close(); progressES = null;
            progressContainer.style.display = 'none';
            statusMsg.className = d.success ? 'status-success' : 'status-error';
            statusMsg.textContent = d.message;
            btnExport.disabled = false;
        } else if (d.type === 'error') {
            progressES.close(); progressES = null;
            progressContainer.style.display = 'none';
            statusMsg.className = 'status-error';
            statusMsg.textContent = d.message;
            btnExport.disabled = false;
        }
    };
    progressES.onerror = () => {
        if (progressES) { progressES.close(); progressES = null; }
        progressContainer.style.display = 'none';
        statusMsg.className = 'status-error';
        statusMsg.textContent = 'Lost connection to the app. Is the Terminal window still open?';
        btnExport.disabled = false;
    };
}

btnExport.addEventListener('click', async () => {
    btnExport.disabled = true;
    statusMsg.className = 'status-processing';
    statusMsg.textContent = '';
    progressContainer.style.display = 'block';
    progressLabel.textContent = 'Starting…';
    progressFill.style.width = '0%';

    const crop = getNativeCrop();
    const vals = timelineSlider.noUiSlider.get();
    const params = {
        timeIn: parseFloat(vals[0]),
        timeOut: parseFloat(vals[1]),
        cropX: crop.x, cropY: crop.y, cropW: crop.w, cropH: crop.h,
        exportScalePct: parseInt(gifScaleInput.value) || 100,
        staticTime: staticCaptureTime,
        fps: parseInt(fpsInput.value),
        webpQuality: parseInt(webpQualityInput.value),
        gifColors: parseInt(gifColorsInput.value),
        gifDither: gifDitherInput.value,
        doWebP: chkWebP.checked, doGIF: chkGIF.checked, doMOV: chkMOV.checked, doPNG: chkPNG.checked
    };

    startProgressStream();
    try {
        await postJSON('/process', params);
    } catch (err) {
        if (progressES) { progressES.close(); progressES = null; }
        progressContainer.style.display = 'none';
        statusMsg.className = 'status-error';
        statusMsg.textContent = 'Could not start export.';
        btnExport.disabled = false;
    }
});
