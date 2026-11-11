"""
Main entry point for Scyrox V8 Battery Widget & Tray Monitor.
Manages single instance lifecycle gracefully (restarts cleanly if already running).
"""

import os
import sys
import psutil
from pathlib import Path
from scyrox_config import get_base_dir
from scyrox_ui import ScyroxApp

PID_FILE = get_base_dir() / "data" / "widget.pid"


def ensure_single_instance():
    """If an existing instance is running, terminates it so this new launch takes over."""
    current_pid = os.getpid()
    if PID_FILE.exists():
        try:
            old_pid = int(PID_FILE.read_text(encoding="utf-8").strip())
            if old_pid != current_pid and psutil.pid_exists(old_pid):
                try:
                    p = psutil.Process(old_pid)
                    pname = p.name().lower()
                    if "python" in pname or "scyrox" in pname:
                        p.terminate()
                        p.wait(timeout=1.5)
                except Exception:
                    pass
        except Exception:
            pass

    # Save current PID
    PID_FILE.parent.mkdir(parents=True, exist_ok=True)
    try:
        PID_FILE.write_text(str(current_pid), encoding="utf-8")
    except Exception:
        pass


def main():
    ensure_single_instance()
    app = ScyroxApp()
    app.run()


if __name__ == "__main__":
    main()
