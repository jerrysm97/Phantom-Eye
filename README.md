# 👁️ Phantom-Eye v2.0

**Advanced Network Recon & CCTV Access Platform**

Phantom-Eye is a self-contained offensive security tool for discovering, accessing, and streaming CCTV cameras across WiFi networks — with one-click WiFi hopping, audio extraction, and cross-platform support.

![Dashboard](https://img.shields.io/badge/Status-Active-brightgreen) ![Python](https://img.shields.io/badge/Python-3.10+-blue) ![Platform](https://img.shields.io/badge/Platform-Linux%20%7C%20macOS-orange)

---

## 🚀 Features

| Feature | Description |
|---------|-------------|
| **📹 CCTV Scanner** | Auto-discovers cameras on any network via nmap + RTSP probing |
| **🎥 Live Streaming** | 30fps MJPEG + Socket.IO dual-mode with FPS counter |
| **🔊 Audio Streaming** | FFmpeg-based audio extraction from RTSP cameras |
| **📡 WiFi Hopping** | Scan nearby networks, connect, and discover cameras — all from the UI |
| **🚀 Hop & Scan** | One-click: connect to WiFi → scan subnet → find cameras |
| **⚡ Auto-Connect** | Dictionary attack with common passwords (no manual input needed) |
| **📷 Camera Details** | Full info modal: IP, vendor, ports, RTSP URL, credentials |
| **➕ Manual Add** | Add cameras from any network by IP address |
| **🍎 macOS Support** | Native macOS launcher with Homebrew dependency management |
| **🔒 HTTPS** | Self-signed SSL certs, auto-generated on first run |

---

## 📦 Quick Start

### Linux (Kali/Ubuntu/Debian)

```bash
git clone https://github.com/jerrysm97/Phantom-Eye.git
cd Phantom-Eye
sudo bash launch.sh
```

### macOS

```bash
git clone https://github.com/jerrysm97/Phantom-Eye.git
cd Phantom-Eye
sudo bash launch_mac.sh
```

> **Prerequisites (macOS):** Install [Homebrew](https://brew.sh), then the script auto-installs `nmap`, `python3`, and `ffmpeg`.

The dashboard opens automatically at **https://localhost:7443/cam**

---

## 🖥️ Usage

### Camera Discovery
1. Open `https://localhost:7443/cam`
2. Click **🔍 Scan Network** — discovers cameras on your current subnet
3. Found cameras appear with **View**, **Info**, and **Snap** buttons

### WiFi Hopping (Multi-Network)
1. Click **📡 Scan WiFi** to list nearby networks
2. For each network you get three options:
   - 🚀 **Hop & Scan** — connects + scans for cameras automatically
   - ⚡ **Connect** — auto-connect using common passwords
   - 🔑 **Manual** — enter password yourself
3. Cameras from the new network auto-populate the list

### Live Streaming
- Click **View** on any discovered camera
- Toggle **MJPEG** for lowest-latency direct streaming
- Click 🔇 to enable **audio** from the camera mic
- Click ⛶ for **fullscreen** mode

### Manual Camera Addition
- Scroll to **"Add Camera Manually"**
- Enter IP, port, username, password, and RTSP path
- Works for cameras on **any reachable network**

---

## 📁 Project Structure

```
Phantom-Eye/
├── launch.sh              # Linux launcher (sudo required)
├── launch_mac.sh          # macOS launcher
├── requirements.txt       # Python dependencies
├── server/
│   ├── app.py             # Flask + Socket.IO server & API routes
│   ├── cam_scanner.py     # Network camera discovery (nmap + RTSP)
│   ├── cam_streamer.py    # MJPEG/Socket.IO video streaming
│   ├── audio_streamer.py  # FFmpeg audio extraction
│   ├── wifi_hopper.py     # WiFi scan/connect/hop (Linux + macOS)
│   ├── scanner.py         # Device scanner
│   ├── config.py          # Configuration
│   └── ...
├── static/
│   ├── css/style.css
│   └── js/cam.js          # Camera UI logic
└── templates/
    ├── cam.html            # Camera discovery page
    ├── index.html          # Dashboard
    └── ...
```

---

## 🔧 Dependencies

**System:** `nmap`, `python3`, `ffmpeg` (optional, for audio)

**Python (auto-installed via pip):**
- Flask, Flask-SocketIO, gevent
- OpenCV (headless), python-nmap
- Scapy, netifaces, PyYAML

---

## ⚠️ Disclaimer

This tool is intended for **authorized security testing and educational purposes only**. Unauthorized access to computer networks and surveillance systems is illegal. Always obtain proper authorization before testing.

---

## 📜 License

MIT License — see [LICENSE](LICENSE) for details.
