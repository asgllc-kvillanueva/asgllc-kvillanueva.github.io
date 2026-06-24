async function startDownload() {
    const urlInput = document.getElementById('urlInput');
    const mediaType = document.getElementById('mediaType').value;
    const mediaQuality = document.getElementById('mediaQuality').value;

    const rawUrl = urlInput.value.trim();

    if (!rawUrl) {
        showStatus('Please paste at least one valid URL.', 'error');
        return;
    }

    // Reset UI
    showStatus('Preparing download...', '');
    document.getElementById('resultsList').innerHTML = '';

    // reset progress bar
    const progressContainer = document.getElementById('progressContainer');
    const progressFill = document.getElementById('progressFill');
    const progressText = document.getElementById('progressText');

    progressContainer.style.display = 'block';
    progressFill.style.width = '0%';
    progressText.textContent = 'Starting...';

    setLoading(true);

    try {
        const response = await fetch('/start_download', {
            method: 'POST',
            headers: {
                'Content-Type': 'application/json',
            },
            body: JSON.stringify({
                url: rawUrl,
                type: mediaType,
                quality: mediaQuality
            }),
        });

        const data = await response.json();

        if (response.ok && data.job_id) {
            setupEventSource(data.job_id);
            urlInput.value = ''; // Clear input
        } else {
            showStatus(data.error || 'Something went wrong starting the job.', 'error');
            setLoading(false);
            progressContainer.style.display = 'none';
        }
    } catch (error) {
        showStatus('Network error or server unavailable.', 'error');
        console.error('Error:', error);
        setLoading(false);
        progressContainer.style.display = 'none';
    }
}

function setupEventSource(jobId) {
    const progressContainer = document.getElementById('progressContainer');
    const progressFill = document.getElementById('progressFill');
    const progressText = document.getElementById('progressText');
    const resultsList = document.getElementById('resultsList');

    const eventSource = new EventSource(`/stream/${jobId}`);

    eventSource.onmessage = function (event) {
        const data = JSON.parse(event.data);

        switch (data.type) {
            case 'starting':
                progressText.textContent = `Preparing: ${data.url}`;
                break;
            case 'progress':
                progressFill.style.width = `${data.percent}%`;
                progressText.textContent = `Downloading: ${data.percent}%`;
                break;
            case 'success':
                const item = document.createElement('div');
                item.className = 'result-item success';
                item.innerHTML = `<span class="result-icon">✅</span> <span>${data.title}</span>`;
                resultsList.appendChild(item);
                break;
            case 'error':
                const errItem = document.createElement('div');
                errItem.className = 'result-item error';
                errItem.innerHTML = `<span class="result-icon">❌</span> <span>Failed: ${data.error || 'Unknown error'}</span>`;
                resultsList.appendChild(errItem);
                break;
            case 'complete':
                showStatus('Batch processing complete.', 'success');
                progressText.textContent = 'Complete!';
                progressFill.style.width = '100%';
                setTimeout(() => {
                    progressContainer.style.display = 'none';
                }, 3000);
                setLoading(false);
                eventSource.close();
                break;
        }
    };

    eventSource.onerror = function () {
        showStatus('Lost connection to server.', 'error');
        setLoading(false);
        eventSource.close();
    };
}

async function changeFolder() {
    try {
        const response = await fetch('/change-folder', { method: 'POST' });
        const data = await response.json();

        if (data.success) {
            document.getElementById('currentFolder').textContent = `Save to: ${data.path}`;
        }
    } catch (error) {
        console.error("Failed to change folder:", error);
    }
}

function setLoading(isLoading) {
    const btn = document.getElementById('downloadBtn');
    if (isLoading) {
        btn.classList.add('loading');
        btn.disabled = true;
    } else {
        btn.classList.remove('loading');
        btn.disabled = false;
    }
}

function showStatus(message, type) {
    const el = document.getElementById('statusMessage');
    el.textContent = message;
    el.className = 'status-message ' + type;
    if (message) {
        el.classList.add('show');
    } else {
        el.classList.remove('show');
    }
}

async function quitBackend() {
    if (confirm("Are you sure you want to stop the downloader server? You will need to restart the app to download again.")) {
        try {
            await fetch('/shutdown', { method: 'POST' });
            document.body.innerHTML = `
                <div class="container" style="display: flex; flex-direction: column; justify-content: center; align-items: center; height: 100vh;">
                    <h1 style="color: #55efc4; margin-bottom: 20px;">Server Stopped</h1>
                    <p style="color: white; text-align: center;">The background process has been killed successfully.</p>
                    <p style="color: rgba(255,255,255,0.6); margin-top: 10px;">You can now safely close this browser window.</p>
                </div>
            `;
        } catch (error) {
            console.error("Failed to shutdown:", error);
            showStatus('Failed to send shutdown signal.', 'error');
        }
    }
}
