wr"""
Windows Autostart Manager for Scyrox Battery Monitor.
Handles HKCU\Software\Microsoft\Windows\CurrentVersion\Run registry keys.
"""

import os
import sys
import winreg
from pathlib import Path
import shutil

RUN_KEY = r"Software\Microsoft\Windows\CurrentVersion\Run"
APP_NAME = "ScyroxBatteryWidget"


def get_startup_command() -> str:
    """Returns the exact launch command line for Windows Startup."""
    if getattr(sys, "frozen", False):
        # Running as compiled PyInstaller executable
        return f'"{sys.executable}"'
    else:
        # Check if compiled executable exists on disk
        exe_path = Path(__file__).resolve().parent / "dist" / "ScyroxWidget" / "ScyroxWidget.exe"
        if exe_path.exists():
            return f'"{exe_path}"'
        # Fallback to pythonw with main.py
        pythonw = shutil.which("pythonw") or sys.executable
        main_script = Path(__file__).resolve().parent / "main.py"
        return f'"{pythonw}" "{main_script}"'


def is_autostart_enabled() -> bool:
    """Checks whether the application is registered in Windows Startup."""
    try:
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, RUN_KEY, 0, winreg.KEY_READ) as key:
            val, _ = winreg.QueryValueEx(key, APP_NAME)
            return bool(val)
    except FileNotFoundError:
        return False
    except Exception:
        return False


def set_autostart(enable: bool) -> bool:
    """Enables or disables Windows Startup for the application."""
    try:
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, RUN_KEY, 0, winreg.KEY_SET_VALUE) as key:
            if enable:
                cmd = get_startup_command()
                winreg.SetValueEx(key, APP_NAME, 0, winreg.REG_SZ, cmd)
            else:
                try:
                    winreg.DeleteValue(key, APP_NAME)
                except FileNotFoundError:
                    pass
        return True
    except Exception as e:
        print(f"Error modifying startup registry: {e}")
        return False
