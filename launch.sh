#!/bin/bash
set -e

# Change to script directory to ensure relative paths work
cd "$(dirname "$0")"

RED='\033[0;31m'
GREEN='\033[0;32m'
CYAN='\033[0;36m'
NC='\033[0m'

echo -e "${CYAN}"
echo "  ╔═══════════════════════════════════════╗"
echo "  ║       PHANTOM EYE v2.0                ║"
echo "  ║   Advanced Recon & Access Platform    ║"
echo "  ╚═══════════════════════════════════════╝"
echo -e "${NC}"

# 1. Privilege Validation
if [ "$EUID" -ne 0 ]; then
  echo -e "${RED}[-] Fatal Error: Phantom-Eye requires root privileges to manipulate raw sockets.${NC}"
  echo -e "    Usage: sudo bash launch.sh [--monitor]"
  exit 1
fi

echo -e "${GREEN}=== Phantom-Eye: Automated Deployment Sequence ===${NC}"

# Detect wireless interface (optional — server works without WiFi for manual cameras)
WLAN=$(iw dev 2>/dev/null | awk '$1=="Interface"{print $2}' | head -1)
if [ -z "$WLAN" ]; then
    echo -e "${CYAN}[*] No wireless interface found. Camera scanner will use wired interface.${NC}"
    # Fall back to first non-loopback interface
    WLAN=$(ip -o link show up | awk -F': ' '!/lo/{print $2; exit}')
    if [ -z "$WLAN" ]; then
        WLAN="eth0"
    fi
fi
echo -e "${GREEN}[+] Target Interface: $WLAN${NC}"

# Parse Arguments
MODE="MANAGED"
if [ "$1" == "--monitor" ]; then
    # Only allow monitor mode if interface actually supports it
    if iw dev "$WLAN" info 2>/dev/null | grep -qi "type"; then
        MODE="MONITOR"
    else
        echo -e "${CYAN}[*] Interface $WLAN does not support monitor mode. Running in managed mode.${NC}"
    fi
fi

# 2. Graceful Teardown Protocol
cleanup() {
    echo -e "\n${RED}[!] Teardown initiated. Halting operations...${NC}"
    
    echo -e "${CYAN}[*] Clearing Port 7443...${NC}"
    fuser -k 7443/tcp > /dev/null 2>&1 || true
    
    if [ "$MODE" == "MONITOR" ]; then
        echo -e "${CYAN}[*] Reverting $WLAN to Layer 3 Managed Mode...${NC}"
        airmon-ng stop "${WLAN}mon" > /dev/null 2>&1 || true
        ip link set $WLAN down
        iw dev $WLAN set type managed
        ip link set $WLAN up
        
        echo -e "${CYAN}[*] Restoring OS network managers...${NC}"
        systemctl start NetworkManager 2>/dev/null || true
        systemctl start wpa_supplicant 2>/dev/null || true
    fi
    
    echo -e "${GREEN}[+] Environment normalized. Goodbye.${NC}"
    exit 0
}

# Bind the cleanup function to termination signals (Ctrl+C)
trap cleanup SIGINT SIGTERM

# Clear port 7443 if already in use before starting
if lsof -Pi :7443 -sTCP:LISTEN -t >/dev/null ; then
    echo -e "${CYAN}[*] Port 7443 already in use. Clearing...${NC}"
    fuser -k 7443/tcp > /dev/null 2>&1 || true
    sleep 1
fi

# Install dependencies if missing
echo -e "${CYAN}[*] Checking system dependencies...${NC}"
dpkg -s aircrack-ng tshark &> /dev/null || {
    echo -e "${CYAN}[*] Installing system deps (aircrack-ng, tshark, etc)...${NC}"
    apt-get update -qq
    apt-get install -y -qq aircrack-ng bluez python3-pip tshark hostapd dnsmasq openssl > /dev/null 2>&1
}

# Generate self-signed cert for HTTPS (needed for WebRTC)
if [ ! -f server/cert.pem ]; then
    echo -e "${CYAN}[*] Generating SSL cert...${NC}"
    openssl req -x509 -newkey rsa:2048 -keyout server/key.pem -out server/cert.pem \
        -days 365 -nodes -subj "/CN=phantom.local" 2>/dev/null
fi

MON_IF="$WLAN"

if [ "$MODE" == "MONITOR" ]; then
    # 3. Process Isolation
    echo -e "${CYAN}[*] Phase 1: Neutralizing background network interference...${NC}"
    systemctl stop NetworkManager 2>/dev/null || true
    systemctl stop wpa_supplicant 2>/dev/null || true

    # 4. Hardware Configuration
    echo -e "${CYAN}[*] Phase 2: Forcing $WLAN into raw Monitor Mode...${NC}"
    airmon-ng check kill > /dev/null 2>&1
    airmon-ng start "$WLAN" > /dev/null 2>&1
    
    MON_IF="${WLAN}mon"
    if ! iw dev | grep -q "$MON_IF"; then
        MON_IF="$WLAN"
    fi
else
    echo -e "${CYAN}[*] Phase 1/2: Bypassed. Keeping $WLAN in basic Managed Mode.${NC}"
fi

echo "$MON_IF" > /tmp/phantom_interface

# Python environment setup
if [ ! -d "venv" ]; then
    echo -e "${CYAN}[*] Creating virtual environment...${NC}"
    python3 -m venv venv
fi

echo -e "${CYAN}[*] Phase 3: Synchronizing WAL Database & Python dependencies...${NC}"
./venv/bin/pip install -q --upgrade pip
./venv/bin/pip install -q -r requirements.txt

# 5. Concurrency Initialization
echo -e "${CYAN}[*] Phase 4: Launching decoupled execution engines...${NC}"
echo -e "${GREEN}[+] C2 Dashboard [Active] -> Binding to https://0.0.0.0:7443${NC}"
echo -e "${GREEN}[+] Sensor Interface: $MON_IF${NC}"
echo -e "${RED}[!] Press Ctrl+C to safely shut down both systems and restore Wi-Fi.${NC}"
echo "------------------------------------------------------------------"

# Launch Flask in the foreground
./venv/bin/python server/app.py