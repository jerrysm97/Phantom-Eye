import cv2
import base64
import time
import threading


class CamStreamer:
    """Streams RTSP/HTTP camera feeds to browser via Socket.IO + MJPEG"""

    def __init__(self, socketio):
        self.socketio = socketio
        self.active_streams = {}  # ip -> thread
        self._running = {}
        self._captures = {}      # ip -> cv2.VideoCapture (shared for MJPEG)
        self._latest_frame = {}  # ip -> (jpeg_bytes, timestamp)
        self._frame_lock = threading.Lock()

    def start_stream(self, camera_info):
        """Start streaming from a camera"""
        ip = camera_info["ip"]

        if ip in self.active_streams:
            self.stop_stream(ip)

        url = camera_info.get("rtsp_url")
        if not url:
            url = camera_info.get("http_url", f"http://{ip}")

        self._running[ip] = True
        t = threading.Thread(target=self._stream_loop, args=(ip, url), daemon=True)
        t.start()
        self.active_streams[ip] = t
        return True

    def _open_capture(self, url):
        """Open a VideoCapture with optimized settings for low latency"""
        cap = cv2.VideoCapture(url, cv2.CAP_FFMPEG)
        if not cap.isOpened():
            cap = cv2.VideoCapture(url)

        if cap.isOpened():
            # Minimize internal buffer to always get the latest frame
            cap.set(cv2.CAP_PROP_BUFFERSIZE, 1)
            # Prefer TCP for RTSP (more reliable, avoids UDP packet loss)
            cap.set(cv2.CAP_PROP_OPEN_TIMEOUT_MSEC, 5000)
            # Lower resolution if camera supports it
            cap.set(cv2.CAP_PROP_FRAME_WIDTH, 640)
            cap.set(cv2.CAP_PROP_FRAME_HEIGHT, 480)

        return cap

    def _stream_loop(self, ip, url):
        """Capture frames and emit to clients with low latency"""
        print(f"[*] Starting stream from {url}")
        cap = self._open_capture(url)

        if not cap.isOpened():
            print(f"[!] Cannot open stream: {url}")
            self.socketio.emit("cam_error", {"ip": ip, "error": "Cannot connect to camera"})
            self._running[ip] = False
            return

        self._captures[ip] = cap
        self.socketio.emit("cam_connected", {"ip": ip})

        fps_target = 30
        frame_interval = 1.0 / fps_target
        fail_count = 0

        while self._running.get(ip, False):
            start = time.time()

            # Grab + retrieve pattern: grab() discards stale buffered frames
            # Then retrieve() only the latest one
            grabbed = cap.grab()
            if not grabbed:
                fail_count += 1
                if fail_count > 15:
                    print(f"[!] Lost stream from {ip}, reconnecting...")
                    cap.release()
                    time.sleep(1)
                    cap = self._open_capture(url)
                    if not cap.isOpened():
                        break
                    self._captures[ip] = cap
                    fail_count = 0
                continue

            fail_count = 0
            ret, frame = cap.retrieve()
            if not ret:
                continue

            # Resize to 640px width for bandwidth efficiency
            h, w = frame.shape[:2]
            if w > 640:
                scale = 640 / w
                frame = cv2.resize(frame, (640, int(h * scale)), interpolation=cv2.INTER_NEAREST)

            # Encode as JPEG with lower quality for speed
            _, buffer = cv2.imencode(".jpg", frame, [cv2.IMWRITE_JPEG_QUALITY, 50])
            jpg_bytes = buffer.tobytes()

            # Store latest frame for MJPEG endpoint
            with self._frame_lock:
                self._latest_frame[ip] = (jpg_bytes, time.time())

            # Emit base64 for Socket.IO grid thumbnails
            jpg_b64 = base64.b64encode(jpg_bytes).decode()
            self.socketio.emit("cam_frame", {
                "ip": ip,
                "frame": jpg_b64,
                "timestamp": time.time()
            })

            # Rate limit
            elapsed = time.time() - start
            if elapsed < frame_interval:
                time.sleep(frame_interval - elapsed)

        cap.release()
        self._captures.pop(ip, None)
        with self._frame_lock:
            self._latest_frame.pop(ip, None)
        print(f"[*] Stream stopped for {ip}")

    def mjpeg_generator(self, ip):
        """Yield MJPEG frames for zero-overhead HTTP streaming"""
        while self._running.get(ip, False):
            with self._frame_lock:
                data = self._latest_frame.get(ip)

            if data:
                jpg_bytes, ts = data
                yield (b"--frame\r\n"
                       b"Content-Type: image/jpeg\r\n"
                       b"Content-Length: " + str(len(jpg_bytes)).encode() + b"\r\n"
                       b"\r\n" + jpg_bytes + b"\r\n")

            time.sleep(0.06)  # ~16fps max for MJPEG
        # Final boundary
        yield b"--frame--\r\n"

    def stop_stream(self, ip):
        """Stop streaming from a camera"""
        self._running[ip] = False
        if ip in self.active_streams:
            del self.active_streams[ip]
        self.socketio.emit("cam_stopped", {"ip": ip})

    def stop_all(self):
        for ip in list(self._running.keys()):
            self._running[ip] = False
        self.active_streams.clear()

    def snapshot(self, camera_info):
        """Take a single snapshot from camera"""
        url = camera_info.get("rtsp_url") or camera_info.get("http_url")
        if not url:
            return None

        cap = self._open_capture(url)
        if not cap.isOpened():
            return None

        ret, frame = cap.read()
        cap.release()

        if ret:
            _, buffer = cv2.imencode(".jpg", frame, [cv2.IMWRITE_JPEG_QUALITY, 85])
            return base64.b64encode(buffer).decode()
        return None

    def is_streaming(self, ip):
        return self._running.get(ip, False)
