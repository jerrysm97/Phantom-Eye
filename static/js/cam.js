const socket = io();
const camGrid = document.getElementById('cam-grid');
const camList = document.getElementById('cam-list');
const scanLog = document.getElementById('scan-log');
const scanProgress = document.getElementById('scan-progress');
let activeCams = {};
let pendingFrames = {};  // Frame gating: skip if previous frame not painted

function startScan() {
    const btn = document.getElementById('btn-scan');
    btn.disabled = true;
    btn.textContent = '⏳ Scanning...';
    scanProgress.style.width = '10%';
    scanLog.innerHTML = '';
    camList.innerHTML = '<tr><td colspan="6" class="status-waiting">Scanning network...</td></tr>';
    activeCams = {};

    fetch('/api/cam/scan', { method: 'POST' })
        .then(r => r.json())
        .then(data => {
            console.log('Scan started:', data);
        });
}

// Socket events for real-time scan updates
socket.on('cam_scan_status', (data) => {
    const log = document.createElement('div');
    log.textContent = `[${new Date().toLocaleTimeString()}] ${data.msg}`;
    scanLog.appendChild(log);
    scanLog.scrollTop = scanLog.scrollHeight;

    if (data.phase === 'arp') scanProgress.style.width = '30%';
    if (data.phase === 'probe') scanProgress.style.width = '60%';
});

socket.on('cam_found', (cam) => {
    console.log('Camera found:', cam);
    activeCams[cam.ip] = cam;
    renderCamTable();
    scanProgress.style.width = '80%';
});

socket.on('cam_scan_complete', (data) => {
    const btn = document.getElementById('btn-scan');
    btn.disabled = false;
    btn.textContent = '🔍 Scan Network';
    scanProgress.style.width = '100%';

    const log = document.createElement('div');
    log.textContent = `[${new Date().toLocaleTimeString()}] Scan complete. ${data.total} cameras found.`;
    log.style.color = '#34c759';
    scanLog.appendChild(log);

    setTimeout(() => { scanProgress.style.width = '0%'; }, 2000);
});

socket.on('cam_scan_error', (data) => {
    const btn = document.getElementById('btn-scan');
    btn.disabled = false;
    btn.textContent = '🔍 Scan Network';

    const log = document.createElement('div');
    log.textContent = `[ERROR] ${data.msg}`;
    log.style.color = '#ff3b30';
    scanLog.appendChild(log);
});

function renderCamTable() {
    const cams = Object.values(activeCams);
    if (cams.length === 0) {
        camList.innerHTML = '<tr><td colspan="6" class="status-waiting">No cameras found</td></tr>';
        return;
    }

    camList.innerHTML = cams.map(cam => `
        <tr>
            <td class="mac">${cam.ip}</td>
            <td>${cam.vendor}</td>
            <td>${cam.ports.join(', ')}</td>
            <td>${cam.rtsp_url ? '<span class="cam-status open">OPEN</span>' : '<span class="cam-status closed">N/A</span>'}</td>
            <td><span class="cam-status ${cam.status === 'stream_found' || cam.status === 'manual' ? 'open' : 'closed'}">${cam.status}</span></td>
            <td>
                <button class="btn-small" onclick="viewCam('${cam.ip}')" ${!cam.rtsp_url && !cam.http_url ? 'disabled' : ''}>View</button>
                <button class="btn-small" style="background:rgba(255,255,255,0.2);color:#fff;" onclick="showCamInfo('${cam.ip}')">Info</button>
                <button class="btn-small" onclick="snapCam('${cam.ip}')">Snap</button>
            </td>
        </tr>
    `).join('');
}

function showCamInfo(ip) {
    const cam = activeCams[ip];
    if (!cam) return;

    const content = `
        <p><strong>IP Address:</strong> <span style="color:#00c6ff">${cam.ip}</span></p>
        <p><strong>Vendor:</strong> ${cam.vendor || 'Unknown'}</p>
        <p><strong>Open Ports:</strong> ${cam.ports && cam.ports.length > 0 ? cam.ports.join(', ') : 'None'}</p>
        <p><strong>RTSP Support:</strong> ${cam.has_rtsp ? '<span style="color:#34c759">Yes</span>' : '<span style="color:#ff3b30">No</span>'}</p>
        <p><strong>HTTP URL:</strong> ${cam.http_url ? `<a href="${cam.http_url}" target="_blank" style="color:#00c6ff">${cam.http_url}</a>` : 'N/A'}</p>
        <p><strong>RTSP URL:</strong> <span style="word-break:break-all;color:#ff9f0a;">${cam.rtsp_url || 'N/A'}</span></p>
        <p><strong>Authenticated:</strong> ${cam.authenticated ? '<span style="color:#34c759">Yes</span>' : '<span style="color:#ff3b30">No</span>'}</p>
        <p><strong>Credentials:</strong> <span style="color:#34c759">${cam.creds || 'None found/needed'}</span></p>
    `;

    document.getElementById('cam-info-content').innerHTML = content;
    document.getElementById('cam-info-modal').style.display = 'flex';
}

function viewCam(ip) {
    const cam = activeCams[ip];
    if (!cam) return;

    fetch('/api/cam/stream', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(cam)
    }).then(r => r.json()).then(data => {
        console.log('Stream started:', data);
        addCamFeed(ip);
    });
}

function addCamFeed(ip) {
    // Check if already added
    if (document.getElementById(`cam-feed-${ip}`)) return;

    // Clear placeholder
    if (camGrid.querySelector('div[style*="grid-column"]')) {
        camGrid.innerHTML = '';
    }

    const feed = document.createElement('div');
    feed.className = 'cam-feed';
    feed.id = `cam-feed-${ip}`;
    feed.innerHTML = `
        <div class="cam-overlay">
            <span class="cam-label">${ip}</span>
            <div style="display:flex;gap:8px;align-items:center;">
                <span class="cam-fps" id="cam-fps-${ip.replace(/\./g, '-')}">0 fps</span>
                <span class="cam-live-dot"></span>
                <button onclick="toggleAudio('${ip}')" id="audio-btn-${ip.replace(/\./g, '-')}" style="background:rgba(255,255,255,0.2);border:none;color:white;padding:4px 10px;border-radius:6px;cursor:pointer;font-size:0.75rem;" title="Toggle Audio">🔇</button>
                <button onclick="toggleMjpeg('${ip}')" id="mjpeg-btn-${ip.replace(/\./g, '-')}" style="background:rgba(0,114,255,0.6);border:none;color:white;padding:4px 10px;border-radius:6px;cursor:pointer;font-size:0.7rem;">MJPEG</button>
                <button onclick="stopCam('${ip}')" style="background:rgba(255,0,0,0.6);border:none;color:white;padding:4px 10px;border-radius:6px;cursor:pointer;font-size:0.75rem;">Stop</button>
                <button onclick="fullscreen('${ip}')" style="background:rgba(255,255,255,0.2);border:none;color:white;padding:4px 10px;border-radius:6px;cursor:pointer;font-size:0.75rem;">⛶</button>
            </div>
        </div>
        <img id="cam-img-${ip}" src="" alt="Connecting..." style="min-height:200px;background:#111;">
        <audio id="cam-audio-${ip}" style="display:none;" preload="none"></audio>
    `;
    camGrid.appendChild(feed);
    pendingFrames[ip] = false;
}

// FPS tracking
let fpsCounters = {};

// Receive frames via Socket.IO — use Blob URL for better performance
socket.on('cam_frame', (data) => {
    const ip = data.ip;
    const img = document.getElementById(`cam-img-${ip}`);
    if (!img) return;

    // Skip if in MJPEG mode
    if (img.dataset.mjpeg === 'true') return;

    // Frame gating: skip if previous frame hasn't painted yet
    if (pendingFrames[ip]) return;
    pendingFrames[ip] = true;

    // Convert base64 to Blob for faster rendering
    const binary = atob(data.frame);
    const bytes = new Uint8Array(binary.length);
    for (let i = 0; i < binary.length; i++) bytes[i] = binary.charCodeAt(i);
    const blob = new Blob([bytes], { type: 'image/jpeg' });
    const url = URL.createObjectURL(blob);

    // Revoke previous URL to avoid memory leak
    if (img._prevUrl) URL.revokeObjectURL(img._prevUrl);
    img._prevUrl = url;

    requestAnimationFrame(() => {
        img.src = url;
        pendingFrames[ip] = false;

        // FPS counter
        if (!fpsCounters[ip]) fpsCounters[ip] = { count: 0, lastTime: Date.now() };
        fpsCounters[ip].count++;
        const elapsed = (Date.now() - fpsCounters[ip].lastTime) / 1000;
        if (elapsed >= 1) {
            const fps = Math.round(fpsCounters[ip].count / elapsed);
            const el = document.getElementById(`cam-fps-${ip.replace(/\./g, '-')}`);
            if (el) el.textContent = `${fps} fps`;
            fpsCounters[ip] = { count: 0, lastTime: Date.now() };
        }
    });

    // Update fullscreen viewer if active
    const fullViewer = document.getElementById('full-viewer');
    if (fullViewer.style.display === 'flex' && fullViewer.dataset.ip === ip) {
        const fullImg = document.getElementById('full-viewer-img');
        if (fullImg._prevUrl) URL.revokeObjectURL(fullImg._prevUrl);
        fullImg._prevUrl = url;
        fullImg.src = url;
    }
});

// Toggle between Socket.IO and direct MJPEG streaming
function toggleMjpeg(ip) {
    const img = document.getElementById(`cam-img-${ip}`);
    const btn = document.getElementById(`mjpeg-btn-${ip.replace(/\./g, '-')}`);
    if (!img) return;

    if (img.dataset.mjpeg === 'true') {
        // Switch back to Socket.IO
        img.dataset.mjpeg = 'false';
        img.src = '';
        btn.textContent = 'MJPEG';
        btn.style.background = 'rgba(0,114,255,0.6)';
    } else {
        // Switch to MJPEG direct stream — lowest latency
        img.dataset.mjpeg = 'true';
        img.src = `/api/cam/mjpeg/${ip}`;
        btn.textContent = 'WS';
        btn.style.background = 'rgba(52,199,89,0.6)';
    }
}

socket.on('cam_connected', (data) => {
    console.log('Camera connected:', data.ip);
});

socket.on('cam_error', (data) => {
    console.error('Camera error:', data);
    const img = document.getElementById(`cam-img-${data.ip}`);
    if (img) {
        img.alt = `Error: ${data.error}`;
        img.style.minHeight = '100px';
    }
});

function stopCam(ip) {
    fetch('/api/cam/stop', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ ip: ip })
    });
    const feed = document.getElementById(`cam-feed-${ip}`);
    if (feed) feed.remove();

    if (camGrid.children.length === 0) {
        camGrid.innerHTML = '<div style="grid-column:1/-1;text-align:center;padding:40px;color:var(--muted);">No active streams.</div>';
    }
}

function snapCam(ip) {
    fetch('/api/cam/snapshot', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ ip: ip })
    }).then(r => r.json()).then(data => {
        if (data.frame) {
            const w = window.open();
            w.document.write(`<img src="data:image/jpeg;base64,${data.frame}" style="max-width:100%">`);
        } else {
            alert('Snapshot failed: ' + (data.error || 'Unknown error'));
        }
    });
}

function fullscreen(ip) {
    const viewer = document.getElementById('full-viewer');
    viewer.style.display = 'flex';
    viewer.dataset.ip = ip;
    document.getElementById('full-viewer-label').textContent = `LIVE — ${ip}`;

    // Use MJPEG in fullscreen for lowest latency
    const fullImg = document.getElementById('full-viewer-img');
    fullImg.src = `/api/cam/mjpeg/${ip}`;
}

function closeFullViewer() {
    const viewer = document.getElementById('full-viewer');
    viewer.style.display = 'none';
    const fullImg = document.getElementById('full-viewer-img');
    fullImg.src = '';
}

// Keyboard shortcut: Escape to close fullscreen
document.addEventListener('keydown', (e) => {
    if (e.key === 'Escape') closeFullViewer();
});

// Manual camera add
function addManualCam() {
    const ip = document.getElementById('manual-ip').value.trim();
    const port = document.getElementById('manual-port').value || '554';
    const user = document.getElementById('manual-user').value || 'admin';
    const password = document.getElementById('manual-pass').value || '';
    const path = document.getElementById('manual-path').value || '/';

    if (!ip) { alert('Enter camera IP'); return; }

    fetch('/api/cam/add', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ ip, port, user, password, path })
    }).then(r => r.json()).then(data => {
        if (data.ok) {
            activeCams[ip] = data.camera;
            renderCamTable();
            // Clear form
            document.getElementById('manual-ip').value = '';
            document.getElementById('manual-pass').value = '';
            const log = document.createElement('div');
            log.textContent = `[${new Date().toLocaleTimeString()}] Camera ${ip} added manually`;
            log.style.color = '#34c759';
            scanLog.appendChild(log);
        } else {
            alert('Error: ' + (data.error || 'Unknown'));
        }
    });
}

// Load any previously found cameras
fetch('/api/cam/list')
    .then(r => r.json())
    .then(cams => {
        cams.forEach(cam => { activeCams[cam.ip] = cam; });
        renderCamTable();
    });

// ──────────── Audio Toggle ────────────

function toggleAudio(ip) {
    const audio = document.getElementById(`cam-audio-${ip}`);
    const btn = document.getElementById(`audio-btn-${ip.replace(/\./g, '-')}`);
    if (!audio) return;

    if (audio.paused || !audio.src) {
        audio.src = `/api/cam/audio/${ip}`;
        audio.play().catch(e => console.warn('Audio play failed:', e));
        btn.textContent = '🔊';
        btn.style.background = 'rgba(52,199,89,0.6)';
    } else {
        audio.pause();
        audio.src = '';
        btn.textContent = '🔇';
        btn.style.background = 'rgba(255,255,255,0.2)';
        fetch(`/api/cam/audio/stop/${ip}`, { method: 'POST' });
    }
}

// ──────────── WiFi Hopping ────────────

function loadNetworks() {
    const tbody = document.getElementById('wifi-list');
    const btn = document.getElementById('btn-wifi-scan');
    if (btn) { btn.disabled = true; btn.textContent = '⏳ Scanning...'; }
    tbody.innerHTML = '<tr><td colspan="4" class="status-waiting">Scanning nearby networks...</td></tr>';

    fetch('/api/wifi/networks')
        .then(r => r.json())
        .then(networks => {
            if (btn) { btn.disabled = false; btn.textContent = '📡 Scan WiFi'; }
            if (networks.length === 0) {
                tbody.innerHTML = '<tr><td colspan="4" class="status-waiting">No networks found</td></tr>';
                return;
            }
            tbody.innerHTML = networks.map(n => `
                <tr>
                    <td>${n.ssid} ${n.connected ? '<span class="cam-status open">Connected</span>' : ''}</td>
                    <td>${n.signal}%</td>
                    <td>${n.security}</td>
                    <td>
                        ${n.connected ? '<button class="btn-small" disabled>Connected</button>' :
                    `<button class="btn-small" style="background:linear-gradient(135deg,#ff9f0a,#ff6b2c); color:white; margin-right:4px;" onclick="hopAndScan('${n.ssid.replace(/'/g, "\\\'")}')">🚀 Hop & Scan</button>
                     <button class="btn-small" style="background:#00c6ff; color:white; margin-right:4px;" onclick="autoConnectWifi('${n.ssid.replace(/'/g, "\\\'")}')">⚡ Connect</button>
                     <button class="btn-small" style="background:rgba(255,255,255,0.2); color:white;" onclick="promptConnect('${n.ssid.replace(/'/g, "\\\'")}')">🔑 Manual</button>`}
                    </td>
                </tr>
            `).join('');
        })
        .catch(e => {
            if (btn) { btn.disabled = false; btn.textContent = '📡 Scan WiFi'; }
            tbody.innerHTML = `<tr><td colspan="4" style="color:#ff3b30;">Error: ${e.message}</td></tr>`;
        });
}

function autoConnectWifi(ssid) {
    const log = document.getElementById('scan-log');
    const entry = document.createElement('div');
    entry.textContent = `[${new Date().toLocaleTimeString()}] 🚀 Initiating Auto-Connect to ${ssid} (trying common passwords)...`;
    entry.style.color = '#ff9f0a';
    log.appendChild(entry);

    fetch('/api/wifi/autoconnect', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ ssid })
    }).then(r => r.json()).then(data => {
        const msg = document.createElement('div');
        if (data.ok) {
            msg.textContent = `[${new Date().toLocaleTimeString()}] ✅ Auto-Connected to ${ssid} — IP: ${data.ip}`;
            msg.style.color = '#34c759';
            loadNetworks();
            updateWifiStatus();
        } else {
            msg.textContent = `[${new Date().toLocaleTimeString()}] ❌ Auto-Connect failed: ${data.error}`;
            msg.style.color = '#ff3b30';
        }
        log.appendChild(msg);
        log.scrollTop = log.scrollHeight;
    });
}

function hopAndScan(ssid) {
    const log = document.getElementById('scan-log');
    const entry = document.createElement('div');
    entry.textContent = `[${new Date().toLocaleTimeString()}] 🚀 Hop & Scan: Connecting to ${ssid} and scanning for cameras...`;
    entry.style.color = '#ff9f0a';
    log.appendChild(entry);
    log.scrollTop = log.scrollHeight;

    // Update progress bar
    const progress = document.getElementById('scan-progress');
    if (progress) { progress.style.width = '30%'; progress.style.transition = 'width 10s'; }

    fetch('/api/wifi/hopandscan', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ ssid })
    }).then(r => r.json()).then(data => {
        if (progress) { progress.style.width = '100%'; }

        const msg = document.createElement('div');
        if (data.ok) {
            msg.innerHTML = `[${new Date().toLocaleTimeString()}] ✅ Hopped to <strong>${ssid}</strong> (${data.ip}) — Subnet: ${data.subnet} — Found <strong>${data.cameras_found}</strong> camera(s)`;
            msg.style.color = '#34c759';

            // Update camera list with discoveries
            if (data.cameras && data.cameras.length > 0) {
                data.cameras.forEach(cam => { activeCams[cam.ip] = cam; });
                renderCamTable();
            }

            // Refresh WiFi status
            loadNetworks();
            updateWifiStatus();
        } else {
            msg.textContent = `[${new Date().toLocaleTimeString()}] ❌ Hop & Scan failed: ${data.error}`;
            msg.style.color = '#ff3b30';
        }
        log.appendChild(msg);
        log.scrollTop = log.scrollHeight;

        setTimeout(() => { if (progress) progress.style.width = '0%'; }, 2000);
    }).catch(e => {
        const msg = document.createElement('div');
        msg.textContent = `[${new Date().toLocaleTimeString()}] ❌ Network error: ${e.message}`;
        msg.style.color = '#ff3b30';
        log.appendChild(msg);
        if (progress) progress.style.width = '0%';
    });
}

function promptConnect(ssid) {
    const password = prompt(`Enter password for "${ssid}"\n(leave blank for open networks)`, '');
    if (password === null) return; // cancelled
    connectWifi(ssid, password);
}

function connectWifi(ssid, password) {
    const log = document.getElementById('scan-log');
    const entry = document.createElement('div');
    entry.textContent = `[${new Date().toLocaleTimeString()}] Connecting to ${ssid}...`;
    entry.style.color = '#00c6ff';
    log.appendChild(entry);

    fetch('/api/wifi/connect', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ ssid, password })
    }).then(r => r.json()).then(data => {
        const msg = document.createElement('div');
        if (data.ok) {
            msg.textContent = `[${new Date().toLocaleTimeString()}] ✅ Connected to ${ssid} — IP: ${data.ip}`;
            msg.style.color = '#34c759';
            loadNetworks();
            updateWifiStatus();
        } else {
            msg.textContent = `[${new Date().toLocaleTimeString()}] ❌ Failed: ${data.error}`;
            msg.style.color = '#ff3b30';
        }
        log.appendChild(msg);
        log.scrollTop = log.scrollHeight;
    });
}

function disconnectWifi() {
    fetch('/api/wifi/disconnect', { method: 'POST' })
        .then(r => r.json())
        .then(data => {
            loadNetworks();
            updateWifiStatus();
        });
}

function updateWifiStatus() {
    fetch('/api/wifi/current')
        .then(r => r.json())
        .then(info => {
            const el = document.getElementById('wifi-current');
            if (el) {
                el.textContent = info.ssid
                    ? `${info.ssid} (${info.ip || 'no IP'})`
                    : 'Not connected';
            }
        });
}

// Load WiFi status on page load
updateWifiStatus();
