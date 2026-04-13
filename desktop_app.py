"""
desktop_app.py
==============
Windows desktop launcher for the Furnace Charge Calculator.

Starts Flask on a free local port, then opens a native Windows
window via pywebview. Everything runs offline — no browser needed.

Build to .exe:
    pip install pyinstaller pywebview
    pyinstaller desktop_app.spec

Or quick test:
    pip install pywebview
    python desktop_app.py
"""

import sys
import os
import threading
import socket
import time
import logging
import webview

# ── Silence Flask startup noise in the .exe ───────────────────
log = logging.getLogger('werkzeug')
log.setLevel(logging.ERROR)

# ── Resolve paths whether running as .py or frozen .exe ───────
def resource_path(rel):
    """Get absolute path to resource — works for dev + PyInstaller."""
    base = getattr(sys, '_MEIPASS', os.path.dirname(os.path.abspath(__file__)))
    return os.path.join(base, rel)

# ── Change working dir so Flask finds database.xlsm ──────────
os.chdir(resource_path('.'))

# ── Import the Flask app ──────────────────────────────────────
from app import app as flask_app


def find_free_port():
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind(('127.0.0.1', 0))
        return s.getsockname()[1]


def start_flask(port):
    flask_app.run(host='127.0.0.1', port=port, debug=False, use_reloader=False)


def wait_for_server(port, timeout=10):
    """Block until Flask is accepting connections."""
    deadline = time.time() + timeout
    while time.time() < deadline:
        try:
            with socket.create_connection(('127.0.0.1', port), timeout=0.5):
                return True
        except OSError:
            time.sleep(0.1)
    return False


def main():
    port = find_free_port()

    # Start Flask in a daemon thread
    t = threading.Thread(target=start_flask, args=(port,), daemon=True)
    t.start()

    # Wait until Flask is ready
    if not wait_for_server(port):
        import tkinter as tk
        from tkinter import messagebox
        root = tk.Tk(); root.withdraw()
        messagebox.showerror("Startup Error", "Flask server failed to start.")
        sys.exit(1)

    url = f'http://127.0.0.1:{port}'

    # Open native window
    window = webview.create_window(
        title      = 'Furnace Charge Calculator',
        url        = url,
        width      = 1400,
        height     = 900,
        min_size   = (1100, 700),
        resizable  = True,
    )

    webview.start(debug=False)


if __name__ == '__main__':
    main()
