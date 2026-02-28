import os

class Config:
    HOST = "0.0.0.0"
    PORT = 7443
    SECRET_KEY = os.urandom(32).hex()
    INTERFACE = "wlan0mon"
    CERTFILE = "server/cert.pem"
    KEYFILE = "server/key.pem"
    IMPLANT_PORT = 7443
    CAPTURE_DIR = "/tmp/phantom_captures"

    @classmethod
    def load_interface(cls):
        try:
            with open("/tmp/phantom_interface") as f:
                cls.INTERFACE = f.read().strip()
        except FileNotFoundError:
            pass

    @classmethod
    def init(cls):
        cls.load_interface()
        os.makedirs(cls.CAPTURE_DIR, exist_ok=True)