"""
Configuration manager for Scyrox Battery Monitor.
Persists settings such as widget position, appearance, and alerts to JSON.
"""

import json
import sys
from pathlib import Path
from typing import Any, Dict


def get_base_dir() -> Path:
    if getattr(sys, "frozen", False):
        exe_dir = Path(sys.executable).resolve().parent
        if exe_dir.name.lower() == "scyroxwidget" and exe_dir.parent.name.lower() == "dist":
            return exe_dir.parent.parent
        return exe_dir
    return Path(__file__).resolve().parent


DEFAULT_CONFIG: Dict[str, Any] = {
    "pos_x": 884,
    "pos_y": 11,
    "show_widget": True,
    "compact_mode": True,
    "always_on_top": True,
    "gaming_mode": True,     # Gaming mode: lock in place + 100% click-through (pass clicks to game)
    "lock_position": True,
    "opacity": 0.95,
    "low_battery_threshold": 20,
    "enable_notifications": True,
    "cable_connected_alert": True,
    "charge_full_alert": True,
    "autostart": True,
}


class ConfigManager:
    def __init__(self, config_dir: Path | None = None):
        if config_dir is None:
            config_dir = get_base_dir() / "data"
        self.config_dir = config_dir
        self.config_file = self.config_dir / "config.json"
        self.config_dir.mkdir(parents=True, exist_ok=True)
        self.settings: Dict[str, Any] = self.load()

    def load(self) -> Dict[str, Any]:
        cfg = dict(DEFAULT_CONFIG)
        if self.config_file.exists():
            try:
                loaded = json.loads(self.config_file.read_text(encoding="utf-8"))
                cfg.update(loaded)
            except Exception:
                pass
        return cfg

    def save(self):
        try:
            self.config_file.write_text(json.dumps(self.settings, indent=2), encoding="utf-8")
        except Exception:
            pass

    def get(self, key: str, default: Any = None) -> Any:
        return self.settings.get(key, default)

    def set(self, key: str, value: Any):
        self.settings[key] = value
        self.save()
