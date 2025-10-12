import os
import qrcode
import webbrowser
from pathlib import Path
import uvicorn
import socket
import requests

def _local_ip() -> str:
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.connect(("8.8.8.8", 80))
        ip = s.getsockname()[0]
        s.close()
        return ip
    except Exception:
        return "127.0.0.1"

def _public_ip():
    try:
        return requests.get("https://api.ipify.org", timeout=2).text
    except Exception:
        return _local_ip()

def main():
    host = "0.0.0.0"
    port = int(os.environ.get("PORT", "49100"))
    url = f"http://{_public_ip()}:{port}/"
    print(f"\nOpen on your phone: {url}\n")

    out = Path("upload_page_qr.png")
    img = qrcode.make(url)
    img.save(out)
    print(f"Saved QR code: {out.resolve()}")

    try:
        webbrowser.open(url)
    except Exception:
        pass

    uvicorn.run("app.server:app", host=host, port=port, reload=False, access_log=False)

if __name__ == "__main__":
    main()
