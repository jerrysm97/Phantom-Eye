import subprocess
import threading
import time


class AudioStreamer:
    """Extracts audio from RTSP camera feeds using FFmpeg and streams as MP3"""

    def __init__(self):
        self._processes = {}   # ip -> subprocess.Popen
        self._running = {}     # ip -> bool

    def start_audio(self, ip, rtsp_url):
        """Start extracting audio from an RTSP stream"""
        if ip in self._processes:
            self.stop_audio(ip)
        self._running[ip] = True

    def audio_generator(self, ip, rtsp_url):
        """Yield MP3 audio chunks from RTSP stream via FFmpeg"""
        cmd = [
            "ffmpeg",
            "-rtsp_transport", "tcp",
            "-i", rtsp_url,
            "-vn",                    # no video
            "-acodec", "libmp3lame",  # encode to MP3
            "-ab", "64k",            # 64kbps bitrate (low latency)
            "-ar", "22050",           # 22kHz sample rate
            "-ac", "1",              # mono
            "-f", "mp3",             # output format
            "-fflags", "nobuffer",   # minimize buffering
            "-flags", "low_delay",
            "pipe:1"                 # pipe to stdout
        ]

        try:
            proc = subprocess.Popen(
                cmd,
                stdout=subprocess.PIPE,
                stderr=subprocess.DEVNULL,
                bufsize=1024
            )
            self._processes[ip] = proc
            self._running[ip] = True
            print(f"[*] Audio stream started for {ip}")

            while self._running.get(ip, False):
                chunk = proc.stdout.read(4096)
                if not chunk:
                    break
                yield chunk

        except FileNotFoundError:
            print("[!] FFmpeg not found. Install ffmpeg for audio support.")
            yield b""
        except Exception as e:
            print(f"[!] Audio error for {ip}: {e}")
        finally:
            self._cleanup(ip)

    def stop_audio(self, ip):
        """Stop audio stream"""
        self._running[ip] = False
        self._cleanup(ip)

    def _cleanup(self, ip):
        proc = self._processes.pop(ip, None)
        if proc:
            try:
                proc.terminate()
                proc.wait(timeout=3)
            except:
                try:
                    proc.kill()
                except:
                    pass
        print(f"[*] Audio stopped for {ip}")

    def stop_all(self):
        for ip in list(self._running.keys()):
            self.stop_audio(ip)

    def is_streaming(self, ip):
        return self._running.get(ip, False)
