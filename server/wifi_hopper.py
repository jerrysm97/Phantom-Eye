import subprocess
import re
import time
import platform


class WiFiHopper:
    """Manages WiFi connections for network hopping — scan, connect, disconnect"""

    def __init__(self, interface="wlan0"):
        self.interface = interface
        self.original_ssid = None
        self.original_password = None
        self._is_macos = platform.system() == "Darwin"

    def scan_networks(self):
        """List all visible WiFi networks with signal strength and security"""
        networks = []

        if self._is_macos:
            networks = self._scan_macos()
        else:
            networks = self._scan_linux()

        # Sort by signal strength (strongest first), deduplicate
        seen = set()
        unique = []
        for n in sorted(networks, key=lambda x: x.get("signal", 0), reverse=True):
            if n["ssid"] and n["ssid"] not in seen:
                seen.add(n["ssid"])
                unique.append(n)

        return unique

    def _scan_linux(self):
        """Scan using nmcli or iwlist"""
        networks = []

        # Try nmcli first
        try:
            out = subprocess.check_output(
                ["nmcli", "-t", "-f", "SSID,SIGNAL,SECURITY,BSSID", "dev", "wifi", "list",
                 "--rescan", "yes"],
                timeout=15, stderr=subprocess.DEVNULL
            ).decode(errors="ignore")

            for line in out.strip().split("\n"):
                parts = line.split(":")
                if len(parts) >= 3:
                    ssid = parts[0].strip()
                    signal = int(parts[1]) if parts[1].isdigit() else 0
                    security = parts[2].strip()
                    bssid = parts[3].strip() if len(parts) > 3 else ""
                    if ssid:
                        networks.append({
                            "ssid": ssid,
                            "signal": signal,
                            "security": security,
                            "bssid": bssid,
                            "connected": False
                        })
        except (subprocess.CalledProcessError, FileNotFoundError, subprocess.TimeoutExpired):
            pass

        # Fallback to iwlist
        if not networks:
            try:
                out = subprocess.check_output(
                    ["sudo", "iwlist", self.interface, "scan"],
                    timeout=20, stderr=subprocess.DEVNULL
                ).decode(errors="ignore")

                cells = out.split("Cell ")
                for cell in cells[1:]:
                    ssid_match = re.search(r'ESSID:"([^"]*)"', cell)
                    signal_match = re.search(r'Signal level[=:](-?\d+)', cell)
                    enc_match = re.search(r'Encryption key:(\w+)', cell)
                    wpa_match = re.search(r'WPA', cell)

                    ssid = ssid_match.group(1) if ssid_match else ""
                    signal_dbm = int(signal_match.group(1)) if signal_match else -100
                    # Convert dBm to percentage (rough)
                    signal_pct = max(0, min(100, 2 * (signal_dbm + 100)))
                    encrypted = enc_match and enc_match.group(1) == "on"
                    security = "WPA/WPA2" if wpa_match else ("WEP" if encrypted else "Open")

                    if ssid:
                        networks.append({
                            "ssid": ssid,
                            "signal": signal_pct,
                            "security": security,
                            "bssid": "",
                            "connected": False
                        })
            except (subprocess.CalledProcessError, FileNotFoundError, subprocess.TimeoutExpired):
                pass

        # Mark current network
        current = self.get_current()
        if current:
            for n in networks:
                if n["ssid"] == current.get("ssid"):
                    n["connected"] = True

        return networks

    def _scan_macos(self):
        """Scan using macOS airport utility"""
        networks = []
        airport = "/System/Library/PrivateFrameworks/Apple80211.framework/Versions/Current/Resources/airport"

        try:
            out = subprocess.check_output(
                [airport, "-s"], timeout=15, stderr=subprocess.DEVNULL
            ).decode(errors="ignore")

            for line in out.strip().split("\n")[1:]:  # skip header
                parts = line.split()
                if len(parts) >= 7:
                    ssid = parts[0]
                    rssi = int(parts[1]) if parts[1].lstrip("-").isdigit() else -100
                    signal_pct = max(0, min(100, 2 * (rssi + 100)))
                    security = " ".join(parts[6:])
                    networks.append({
                        "ssid": ssid,
                        "signal": signal_pct,
                        "security": security,
                        "bssid": parts[2] if len(parts) > 2 else "",
                        "connected": False
                    })
        except (subprocess.CalledProcessError, FileNotFoundError, subprocess.TimeoutExpired):
            pass

        return networks

    def auto_connect(self, ssid):
        """Auto-connect without user prompt by trying Open or common passwords"""
        # Determine if it's open
        networks = self.scan_networks()
        target = next((n for n in networks if n["ssid"] == ssid), None)
        
        if target and target["security"].lower() in ["open", "none"]:
            return self.connect(ssid, "")
            
        common_passwords = ["", "admin", "default", "12345678", "password", "shresh11", "thaxaina@123", "123456789"]
        
        for pwd in common_passwords:
            print(f"[*] Auto-connect: Trying password '{pwd}' for {ssid}...")
            res = self.connect(ssid, pwd)
            if res.get("ok"):
                return res
                
        return {"ok": False, "error": "Auto-connect failed with all common passwords"}

    def connect(self, ssid, password=""):
        """Connect to a WiFi network"""
        # Save current network for reconnection
        current = self.get_current()
        if current and current.get("ssid"):
            self.original_ssid = current["ssid"]

        if self._is_macos:
            return self._connect_macos(ssid, password)
        else:
            return self._connect_linux(ssid, password)

    def _connect_linux(self, ssid, password):
        """Connect on Linux using nmcli or wpa_supplicant"""
        # Try nmcli first
        try:
            cmd = ["sudo", "nmcli", "dev", "wifi", "connect", ssid]
            if password:
                cmd += ["password", password]
            cmd += ["ifname", self.interface]

            result = subprocess.run(cmd, capture_output=True, text=True, timeout=30)
            if result.returncode == 0:
                time.sleep(2)
                info = self.get_current()
                return {"ok": True, "ssid": ssid, "ip": info.get("ip", "Obtaining...")}
        except (subprocess.TimeoutExpired, FileNotFoundError):
            pass

        # Fallback to wpa_supplicant
        try:
            # Kill existing wpa_supplicant
            subprocess.run(["sudo", "killall", "wpa_supplicant"], capture_output=True)
            time.sleep(1)

            # Create config
            conf = f'network={{\n  ssid="{ssid}"\n'
            if password:
                conf += f'  psk="{password}"\n'
            else:
                conf += '  key_mgmt=NONE\n'
            conf += '}\n'

            conf_path = f"/tmp/wpa_{ssid.replace(' ', '_')}.conf"
            with open(conf_path, "w") as f:
                f.write(conf)

            subprocess.run(
                ["sudo", "wpa_supplicant", "-B", "-i", self.interface, "-c", conf_path],
                capture_output=True, timeout=10
            )
            time.sleep(3)

            subprocess.run(
                ["sudo", "dhclient", self.interface],
                capture_output=True, timeout=15
            )
            time.sleep(2)

            info = self.get_current()
            return {"ok": True, "ssid": ssid, "ip": info.get("ip", "Obtaining...")}
        except Exception as e:
            return {"ok": False, "error": str(e)}

    def _connect_macos(self, ssid, password):
        """Connect on macOS using networksetup"""
        try:
            cmd = ["networksetup", "-setairportnetwork", "en0", ssid]
            if password:
                cmd.append(password)

            result = subprocess.run(cmd, capture_output=True, text=True, timeout=30)
            if result.returncode == 0:
                time.sleep(3)
                info = self.get_current()
                return {"ok": True, "ssid": ssid, "ip": info.get("ip", "Obtaining...")}
            else:
                return {"ok": False, "error": result.stderr.strip() or "Connection failed"}
        except Exception as e:
            return {"ok": False, "error": str(e)}

    def disconnect(self):
        """Disconnect from current WiFi"""
        if self._is_macos:
            subprocess.run(
                ["networksetup", "-setairportpower", "en0", "off"],
                capture_output=True
            )
            time.sleep(1)
            subprocess.run(
                ["networksetup", "-setairportpower", "en0", "on"],
                capture_output=True
            )
        else:
            subprocess.run(
                ["sudo", "nmcli", "dev", "disconnect", self.interface],
                capture_output=True
            )
        return {"ok": True}

    def reconnect_original(self):
        """Reconnect to the original WiFi network"""
        if self.original_ssid:
            return self.connect(self.original_ssid, self.original_password or "")
        return {"ok": False, "error": "No original network saved"}

    def get_current(self):
        """Get current WiFi connection info"""
        result = {"ssid": None, "ip": None, "interface": self.interface}

        if self._is_macos:
            try:
                out = subprocess.check_output(
                    ["networksetup", "-getairportnetwork", "en0"],
                    timeout=5, stderr=subprocess.DEVNULL
                ).decode(errors="ignore")
                match = re.search(r"Current Wi-Fi Network: (.+)", out)
                if match:
                    result["ssid"] = match.group(1).strip()

                out = subprocess.check_output(
                    ["ipconfig", "getifaddr", "en0"],
                    timeout=5, stderr=subprocess.DEVNULL
                ).decode(errors="ignore")
                result["ip"] = out.strip()
            except:
                pass
        else:
            try:
                out = subprocess.check_output(
                    ["iwconfig", self.interface],
                    timeout=5, stderr=subprocess.DEVNULL
                ).decode(errors="ignore")
                match = re.search(r'ESSID:"([^"]*)"', out)
                if match:
                    result["ssid"] = match.group(1)

                out = subprocess.check_output(
                    ["ip", "-4", "addr", "show", self.interface],
                    timeout=5, stderr=subprocess.DEVNULL
                ).decode(errors="ignore")
                match = re.search(r"inet (\d+\.\d+\.\d+\.\d+)", out)
                if match:
                    result["ip"] = match.group(1)
            except:
                pass

        return result
