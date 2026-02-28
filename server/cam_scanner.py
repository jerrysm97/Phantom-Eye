import nmap
import socket
import threading
import time
import re

# Common RTSP paths for various camera brands
RTSP_PATHS = [
    "/media/video1",
    "/unicast/c1/s0/live",
    "/",
    "/live",
    "/live/ch0",
    "/live/ch00_0",
    "/cam/realmonitor",
    "/h264Preview_01_main",
    "/Streaming/Channels/101",
    "/stream1",
    "/video1",
    "/1",
    "/11",
    "/MediaInput/h264",
    "/user=admin&password=&channel=1&stream=0.sdp",
]

# Default credentials to try
DEFAULT_CREDS = [
    ("admin", "123456"),
    ("admin", "admin"),
    ("admin", "12345"),
    ("admin", ""),
    ("root", "root"),
    ("admin", "password"),
    ("admin", "admin123"),
    ("admin", "888888"),
    ("user", "user"),
    ("", ""),
]

CAMERA_PORTS = [554, 8554, 80, 8080, 8888, 443, 9000, 37777, 34567, 5000, 7000, 8000, 8443, 10554]


class CamScanner:
    def __init__(self, subnet=None):
        self.subnet = subnet or self._detect_subnet()
        self.cameras = {}  # ip -> camera info
        self.lock = threading.Lock()
        self._scanning = False

    def _detect_subnet(self):
        """Auto-detect the local subnet, preferring the wireless interface"""
        try:
            import netifaces

            # Priority 1: Use the configured interface from /tmp/phantom_interface
            preferred_iface = None
            try:
                with open("/tmp/phantom_interface") as f:
                    preferred_iface = f.read().strip()
            except FileNotFoundError:
                pass

            # Priority 2: Prefer wlan* interfaces over eth*
            ifaces = netifaces.interfaces()
            ordered = []
            if preferred_iface and preferred_iface in ifaces:
                ordered.append(preferred_iface)
            ordered += [i for i in ifaces if i.startswith("wlan") and i not in ordered]
            ordered += [i for i in ifaces if i not in ordered]

            for iface in ordered:
                addrs = netifaces.ifaddresses(iface)
                if 2 in addrs:
                    for addr in addrs[2]:
                        ip = addr["addr"]
                        mask = addr.get("netmask", "255.255.255.0")
                        if not ip.startswith("127."):
                            # Simple /24 assumption
                            parts = ip.split(".")
                            return f"{parts[0]}.{parts[1]}.{parts[2]}.0/24"
        except:
            pass
        return "192.168.100.0/24"

    def scan_network(self, callback=None):
        """Full network scan for cameras"""
        self._scanning = True
        results = []

        try:
            nm = nmap.PortScanner()
            ports = ",".join(str(p) for p in CAMERA_PORTS)

            if callback:
                callback("status", {"msg": "ARP scanning subnet...", "phase": "arp"})

            # Host discovery + port scan (use ARP discovery when running as root for better results)
            import os
            priv_flag = '' if os.geteuid() == 0 else '--unprivileged'
            nm.scan(hosts=self.subnet, arguments=f"-sT -p {ports} --open -T4 --min-rate=300 {priv_flag}".strip())

            hosts = nm.all_hosts()
            if callback:
                callback("status", {"msg": f"Found {len(hosts)} hosts. Probing for cameras...", "phase": "probe"})

            for host in hosts:
                if not self._scanning:
                    break

                open_ports = []
                try:
                    for proto in nm[host].all_protocols():
                        for port in nm[host][proto]:
                            if nm[host][proto][port]["state"] == "open":
                                open_ports.append(port)
                except:
                    continue

                if not open_ports:
                    continue

                # Check for camera-related ports (expanded RTSP ports)
                rtsp_ports = {554, 8554, 5000, 7000, 9000, 10554}
                has_rtsp = bool(rtsp_ports & set(open_ports))
                has_http = 80 in open_ports or 8080 in open_ports or 443 in open_ports or 8888 in open_ports or 8443 in open_ports

                if has_rtsp or has_http:
                    cam_info = {
                        "ip": host,
                        "ports": open_ports,
                        "has_rtsp": has_rtsp,
                        "has_http": has_http,
                        "rtsp_url": None,
                        "http_url": None,
                        "authenticated": False,
                        "creds": None,
                        "vendor": self._get_vendor(host),
                        "status": "discovered",
                    }

                    # Probe RTSP on all open RTSP-capable ports
                    if has_rtsp:
                        active_rtsp_ports = sorted(rtsp_ports & set(open_ports))
                        is_airtunes = False
                        for rp in active_rtsp_ports:
                            # Quick AirPlay/AirTunes filter
                            try:
                                _s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
                                _s.settimeout(3)
                                _s.connect((host, rp))
                                _s.send(f"OPTIONS rtsp://{host}:{rp}/ RTSP/1.0\r\nCSeq: 1\r\n\r\n".encode())
                                _resp = _s.recv(1024).decode(errors='ignore')
                                _s.close()
                                if 'AirTunes' in _resp or 'AirPlay' in _resp:
                                    is_airtunes = True
                                    break
                            except:
                                pass
                        
                        if is_airtunes:
                            continue  # Skip AirPlay devices
                        
                        rtsp_result = self._probe_rtsp(host, active_rtsp_ports[0])
                        if rtsp_result:
                            cam_info["rtsp_url"] = rtsp_result["url"]
                            cam_info["authenticated"] = rtsp_result["auth"]
                            cam_info["creds"] = rtsp_result.get("creds")
                            cam_info["status"] = "stream_found"
                        else:
                            # Try other RTSP ports
                            for rp in active_rtsp_ports[1:]:
                                rtsp_result = self._probe_rtsp(host, rp)
                                if rtsp_result:
                                    cam_info["rtsp_url"] = rtsp_result["url"]
                                    cam_info["authenticated"] = rtsp_result["auth"]
                                    cam_info["creds"] = rtsp_result.get("creds")
                                    cam_info["status"] = "stream_found"
                                    break

                    # HTTP probe
                    if has_http:
                        http_port = 80 if 80 in open_ports else (8080 if 8080 in open_ports else 443)
                        scheme = "https" if http_port == 443 else "http"
                        cam_info["http_url"] = f"{scheme}://{host}:{http_port}"

                    with self.lock:
                        self.cameras[host] = cam_info

                    if callback:
                        callback("camera_found", cam_info)

        except Exception as e:
            print(f"[!] Scan error: {e}")
            if callback:
                callback("error", {"msg": str(e)})
        finally:
            self._scanning = False
            if callback:
                callback("scan_complete", {"total": len(self.cameras)})

        return list(self.cameras.values())

    def _probe_rtsp(self, ip, port):
        """Try to find a working RTSP stream"""
        for path in RTSP_PATHS:
            # Try without auth first
            url = f"rtsp://{ip}:{port}{path}"
            if self._test_rtsp(url):
                return {"url": url, "auth": False}

            # Try with default creds (both URL-embedded and Digest auth)
            for user, passwd in DEFAULT_CREDS:
                auth_url = f"rtsp://{user}:{passwd}@{ip}:{port}{path}"
                if self._test_rtsp(auth_url):
                    return {"url": auth_url, "auth": True, "creds": f"{user}:{passwd}"}

                # Try proper RTSP Digest authentication
                digest_result = self._test_rtsp_digest(ip, port, path, user, passwd)
                if digest_result:
                    # Build URL with embedded creds for OpenCV compatibility
                    return {"url": auth_url, "auth": True, "creds": f"{user}:{passwd}"}

        return None

    def _test_rtsp_digest(self, ip, port, path, user, passwd):
        """Test RTSP with Digest Authentication (RFC 2617) on same TCP connection"""
        import hashlib as _hashlib
        url = f"rtsp://{ip}:{port}{path}"
        sock = None
        try:
            sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            sock.settimeout(5)
            sock.connect((ip, port))

            # First DESCRIBE without auth to get the challenge
            req = f"DESCRIBE {url} RTSP/1.0\r\nCSeq: 1\r\nAccept: application/sdp\r\n\r\n"
            sock.send(req.encode())
            resp = sock.recv(4096).decode(errors="ignore")

            if "200 OK" in resp:
                return True
            if "401" not in resp:
                return False

            # Extract Digest challenge
            realm_match = re.search(r'realm="([^"]+)"', resp)
            nonce_match = re.search(r'nonce="([^"]+)"', resp)
            if not realm_match or not nonce_match:
                return False

            realm = realm_match.group(1)
            nonce = nonce_match.group(1)

            # Calculate Digest response
            ha1 = _hashlib.md5(f"{user}:{realm}:{passwd}".encode()).hexdigest()
            ha2 = _hashlib.md5(f"DESCRIBE:{url}".encode()).hexdigest()
            response_hash = _hashlib.md5(f"{ha1}:{nonce}:{ha2}".encode()).hexdigest()

            # Send authenticated DESCRIBE on SAME connection (camera rejects reconnection)
            auth_header = (
                f'Digest username="{user}", realm="{realm}", '
                f'nonce="{nonce}", uri="{url}", response="{response_hash}"'
            )
            req = (
                f"DESCRIBE {url} RTSP/1.0\r\n"
                f"CSeq: 2\r\n"
                f"Accept: application/sdp\r\n"
                f"Authorization: {auth_header}\r\n"
                f"\r\n"
            )
            sock.send(req.encode())
            resp = sock.recv(8192).decode(errors="ignore")

            return "200 OK" in resp
        except:
            return False
        finally:
            try:
                if sock:
                    sock.close()
            except:
                pass

    def _test_rtsp(self, url):
        """Test if RTSP URL responds with a valid stream"""
        try:
            # Parse host/port from URL
            match = re.match(r"rtsp://(?:[^@]+@)?([^:/]+):?(\d+)?(/.+)?", url)
            if not match:
                return False
            host = match.group(1)
            port = int(match.group(2) or 554)
            path = match.group(3) or "/"

            sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            sock.settimeout(3)
            sock.connect((host, port))

            # Send RTSP DESCRIBE
            cseq = 1
            request = (
                f"DESCRIBE {url} RTSP/1.0\r\n"
                f"CSeq: {cseq}\r\n"
                f"Accept: application/sdp\r\n"
                f"\r\n"
            )
            sock.send(request.encode())
            response = sock.recv(4096).decode(errors="ignore")
            sock.close()

            # 200 OK = stream exists
            if "200 OK" in response:
                return True
            # 401 = stream exists but needs auth
            if "401" in response:
                return False
            return False
        except:
            return False

    def _get_vendor(self, ip):
        """Try to identify camera vendor via HTTP"""
        import urllib.request
        import ssl
        ctx = ssl.create_default_context()
        ctx.check_hostname = False
        ctx.verify_mode = ssl.CERT_NONE

        for port in [80, 8080]:
            try:
                req = urllib.request.Request(
                    f"http://{ip}:{port}/",
                    headers={"User-Agent": "Mozilla/5.0"}
                )
                resp = urllib.request.urlopen(req, timeout=2, context=ctx)
                html = resp.read(2048).decode(errors="ignore").lower()
                server = resp.headers.get("Server", "").lower()

                for brand in ["hikvision", "dahua", "axis", "reolink", "amcrest",
                              "foscam", "tp-link", "wyze", "ring", "nest"]:
                    if brand in html or brand in server:
                        return brand.capitalize()
                return "IP Camera"
            except:
                continue
        return "Unknown"

    def get_cameras(self):
        with self.lock:
            return list(self.cameras.values())

    def stop(self):
        self._scanning = False
