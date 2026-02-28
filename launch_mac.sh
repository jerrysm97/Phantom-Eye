#!/bin/bash
# ══════════════════════════════════════════
#  PHANTOM EYE v2.0 — macOS Launcher
#  Compatible with macOS 12+ (Monterey+)
# ══════════════════════════════════════════

set -e

RED='\033[0;31m'
GREEN='\033[0;32m'
CYAN='\033[0;36m'
NC='\033[0m'

echo -e "${CYAN}"
cat << 'BANNER'
  ╔═══════════════════════════════════════╗
  ║       PHANTOM EYE v2.0                ║
  ║   Advanced Recon & Access Platform    ║
  ║         macOS Edition                 ║
  ╚═══════════════════════════════════════╝
BANNER
echo -e "${NC}"

# Check for root/sudo
if [ "$EUID" -ne 0 ]; then
    echo -e "${RED}[!] Please run with sudo: sudo bash launch_mac.sh${NC}"
    exit 1
fi

echo -e "${GREEN}=== Phantom-Eye: macOS Deployment ===${NC}"

# Detect WiFi interface (macOS uses en0 for WiFi typically)
WLAN="en0"
CURRENT_SSID=$(networksetup -getairportnetwork "$WLAN" 2>/dev/null | awk -F': ' '{print $2}')
if [ -n "$CURRENT_SSID" ]; then
    echo -e "${GREEN}[+] WiFi Interface: $WLAN (Connected to: $CURRENT_SSID)${NC}"
else
    echo -e "${CYAN}[*] WiFi not connected. Camera scanner will work with manual camera entry.${NC}"
fi

# Save interface
echo "$WLAN" > /tmp/phantom_interface

# Check dependencies
echo -e "${CYAN}[*] Checking dependencies...${NC}"

if ! command -v python3 &> /dev/null; then
    echo -e "${RED}[!] Python3 not found. Install with: brew install python3${NC}"
    exit 1
fi

if ! command -v nmap &> /dev/null; then
    echo -e "${CYAN}[*] nmap not found. Installing via Homebrew...${NC}"
    if command -v brew &> /dev/null; then
        brew install nmap
    else
        echo -e "${RED}[!] Homebrew not found. Install nmap manually: brew install nmap${NC}"
        exit 1
    fi
fi

if ! command -v ffmpeg &> /dev/null; then
    echo -e "${CYAN}[*] ffmpeg not found (needed for audio). Install with: brew install ffmpeg${NC}"
fi

# Setup Python virtual environment
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
cd "$SCRIPT_DIR"

if [ ! -d "venv" ]; then
    echo -e "${CYAN}[*] Creating Python virtual environment...${NC}"
    python3 -m venv venv
fi

echo -e "${CYAN}[*] Installing Python dependencies...${NC}"
./venv/bin/pip install -q -r requirements.txt 2>/dev/null

# Generate SSL certificates if not present
if [ ! -f "server/cert.pem" ] || [ ! -f "server/key.pem" ]; then
    echo -e "${CYAN}[*] Generating SSL certificates...${NC}"
    openssl req -x509 -newkey rsa:2048 -keyout server/key.pem -out server/cert.pem \
        -days 365 -nodes -subj "/CN=phantom-eye" 2>/dev/null
fi

# Kill any existing instance
lsof -ti:7443 2>/dev/null | xargs kill -9 2>/dev/null || true
sleep 1

# Teardown handler
cleanup() {
    echo -e "\n${CYAN}[!] Shutting down Phantom Eye...${NC}"
    lsof -ti:7443 2>/dev/null | xargs kill -9 2>/dev/null || true
    echo -e "${GREEN}[+] Shutdown complete.${NC}"
    exit 0
}
trap cleanup INT TERM

echo -e "${GREEN}[+] C2 Dashboard [Active] -> Binding to https://0.0.0.0:7443${NC}"
echo -e "${GREEN}[+] WiFi Interface: $WLAN${NC}"
echo -e "${RED}[!] Press Ctrl+C to shut down.${NC}"
echo "------------------------------------------------------------------"

# Open browser automatically
(sleep 3 && open "https://localhost:7443/cam" 2>/dev/null) &

# Start server
cd "$SCRIPT_DIR"
exec ./venv/bin/python server/app.py
