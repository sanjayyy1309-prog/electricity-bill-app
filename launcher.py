"""Starts the app and opens the browser. Run with pythonw / the .exe for no console window."""
import socket
import threading
import urllib.request
import webbrowser

import uvicorn

from main import app

PORT = 8000


def already_running(port):
    try:
        urllib.request.urlopen(f"http://127.0.0.1:{port}/api/tariff", timeout=1)
        return True
    except Exception:
        return False


def port_free(port):
    with socket.socket() as s:
        return s.connect_ex(("127.0.0.1", port)) != 0


def main():
    port = PORT
    if already_running(port):            # second double-click: just open the browser
        webbrowser.open(f"http://127.0.0.1:{port}")
        return
    while not port_free(port):
        port += 1
    threading.Timer(1.5, lambda: webbrowser.open(f"http://127.0.0.1:{port}")).start()
    uvicorn.run(app, host="127.0.0.1", port=port, log_config=None)


if __name__ == "__main__":
    main()
