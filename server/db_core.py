import sqlite3
import json
import os

DB_PATH = os.path.join(os.path.dirname(__file__), "phantom.db")

def init_db():
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    # Devices table
    c.execute('''
        CREATE TABLE IF NOT EXISTS devices (
            mac TEXT PRIMARY KEY,
            vendor TEXT,
            type TEXT,
            ip TEXT,
            os_guess TEXT,
            signal INTEGER,
            first_seen REAL,
            last_seen REAL,
            packets INTEGER,
            implant_status TEXT,
            associated_ap TEXT,
            ssids TEXT, -- JSON array
            open_ports TEXT, -- JSON array
            access TEXT -- JSON object
        )
    ''')
    # Networks table
    c.execute('''
        CREATE TABLE IF NOT EXISTS networks (
            bssid TEXT PRIMARY KEY,
            ssid TEXT,
            vendor TEXT,
            signal INTEGER,
            first_seen REAL
        )
    ''')
    conn.commit()
    conn.close()

def upsert_device(dev):
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute('''
        INSERT INTO devices (
            mac, vendor, type, ip, os_guess, signal, first_seen, last_seen, 
            packets, implant_status, associated_ap, ssids, open_ports, access
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        ON CONFLICT(mac) DO UPDATE SET
            vendor=excluded.vendor,
             type=excluded.type,
             ip=COALESCE(excluded.ip, ip),
             os_guess=CASE WHEN excluded.os_guess != 'Unknown' THEN excluded.os_guess ELSE os_guess END,
             signal=excluded.signal,
             last_seen=excluded.last_seen,
             packets=excluded.packets,
             implant_status=excluded.implant_status,
             associated_ap=COALESCE(excluded.associated_ap, associated_ap),
             ssids=excluded.ssids,
             open_ports=CASE WHEN excluded.open_ports != '[]' THEN excluded.open_ports ELSE open_ports END,
             access=excluded.access
    ''', (
        dev['mac'], dev['vendor'], dev['type'], dev.get('ip'), dev.get('os_guess', 'Unknown'), 
        dev['signal'], dev['first_seen'], dev['last_seen'], dev['packets'], 
        dev['implant_status'], dev.get('associated_ap'), json.dumps(list(dev.get('ssids', []))), 
        json.dumps(dev.get('open_ports', [])), json.dumps(dev.get('access', {}))
    ))
    conn.commit()
    conn.close()

def get_all_devices():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    c = conn.cursor()
    c.execute('SELECT * FROM devices')
    rows = c.fetchall()
    conn.close()
    
    devices = []
    for r in rows:
        d = dict(r)
        d['ssids'] = json.loads(d['ssids'])
        d['open_ports'] = json.loads(d['open_ports'])
        d['access'] = json.loads(d['access'])
        devices.append(d)
    return devices

def upsert_network(net):
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute('''
        INSERT INTO networks (bssid, ssid, vendor, signal, first_seen)
        VALUES (?, ?, ?, ?, ?)
        ON CONFLICT(bssid) DO UPDATE SET
            ssid=excluded.ssid,
            signal=excluded.signal
    ''', (net['bssid'], net['ssid'], net['vendor'], net['signal'], net['first_seen']))
    conn.commit()
    conn.close()

if __name__ == "__main__":
    init_db()
    print("[+] Database initialized.")
