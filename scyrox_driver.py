"""
Scyrox V8 / V6 Hardware Driver for Windows
Communicates directly with Scyrox mice via USB HID endpoints (wired or 2.4G 8K Dongle).
Uses realistic Coulomb/voltage charge smoothing matching the official S-Center web app.
"""

import json
import math
import os
import sys
import time
from pathlib import Path
from typing import Optional, Dict, Any
import hid


def get_base_dir() -> Path:
    if getattr(sys, "frozen", False):
        exe_dir = Path(sys.executable).resolve().parent
        if exe_dir.name.lower() == "scyroxwidget" and exe_dir.parent.name.lower() == "dist":
            return exe_dir.parent.parent
        return exe_dir
    return Path(__file__).resolve().parent

VENDOR_ID = 0x3554
PID_WIRELESS = 0xF5F7  # 8K Wireless Dongle
PID_WIRED = 0xF5F6     # USB Type-C Cable

USAGE_PAGE = 0xFF02
USAGE = 0x0002

REPORT_ID = 8
ONLINE_COMMAND = 3
BATTERY_COMMAND = 4
REPORT_LENGTH = 17
EXPECTED_CHECKSUM = 0x55

# S-Center official voltage threshold table (millivolts)
VOLTAGE_THRESHOLDS_MV = (
    3050, 3420, 3480, 3540, 3600, 3660, 3720, 3760, 3800, 3840,
    3880, 3920, 3940, 3960, 3980, 4000, 4020, 4040, 4060, 4080, 4110
)


def build_packet(cmd: int, data: Optional[list[int]] = None) -> bytes:
    """Builds a 17-byte HID report adhering to the S-Center CRC algorithm."""
    wn = 8
    t = [cmd] + [0] * 15
    t[14] = 239  # 0xEF
    if data:
        t[4] = len(data)
        for i, val in enumerate(data):
            t[5 + i] = val
    else:
        t[4] = 0

    s = sum(t[:15]) & 0xFF
    chk = (85 - s) & 0xFF
    t[15] = (chk - wn) & 0xFF
    return bytes([wn] + t)


def voltage_to_level(voltage_mv: int, charging: bool) -> int:
    """Calculates smoothed battery percentage from cell voltage matching S-Center web driver."""
    if voltage_mv <= 0:
        return 0
    if voltage_mv >= VOLTAGE_THRESHOLDS_MV[-1]:
        return 99 if charging else 100

    for index, upper_bound in enumerate(VOLTAGE_THRESHOLDS_MV):
        if voltage_mv >= upper_bound:
            continue
        if index == 0:
            return 1
        lower_bound = VOLTAGE_THRESHOLDS_MV[index - 1]
        segment_size = (upper_bound - lower_bound) / 5.0
        interpolated = (voltage_mv - lower_bound) / segment_size + (index - 1) * 5.0
        level = round(interpolated)
        if level in (0, 15):
            level += 1
        return max(0, min(100, level))
    return 100


def pg(r: int, ca: int, l: float) -> int:
    """Exact Coulomb estimator bounds matching Scyrox S-Center index-DUfu8aky.js."""
    if l > 1800:
        return ca
    if l < 60:
        return r
    r_val = 0.028 * l + r
    r_val = 100.0 if r_val > 100.0 else r_val
    o_val = 0.014 * l
    o_val = 0.0 if o_val > r else max(0.0, r - o_val)
    if ca > r_val:
        a_val = r_val
    elif ca < o_val:
        a_val = o_val
    else:
        a_val = r
    return round(a_val)


class ScyroxDriver:
    def __init__(self, cache_dir: Optional[Path] = None):
        if cache_dir is None:
            cache_dir = get_base_dir() / "data"
        self.cache_dir = cache_dir
        self.cache_file = self.cache_dir / "state_cache.json"
        self.cache_dir.mkdir(parents=True, exist_ok=True)
        self.Wt: int = 92
        self.Kr: bool = True
        self.Wr: bool = False
        self.last_ug_time: float = time.time()
        self.last_cg_time: float = time.time()
        self.full_counter: int = 0
        self._last_state: Dict[str, Any] = self._load_cache()

    def _load_cache(self) -> Dict[str, Any]:
        now = time.time()
        if self.cache_file.exists():
            try:
                data = json.loads(self.cache_file.read_text(encoding="utf-8"))
                saved_level = int(data.get("percent", 92))
                saved_time = float(data.get("timestamp", now))
                l = now - saved_time
                v = int(data.get("voltage_mv", 4070))
                c = bool(data.get("charging", False))
                if not c and v > 4080:
                    v = 4070
                ca = voltage_to_level(v, c)
                self.Wt = pg(saved_level, ca, l)
                if self.Wt >= 85 and c:
                    self.Wr = True
                    self.Kr = False
                else:
                    self.Kr = True
                    self.Wr = False
                return data
            except Exception:
                pass
        self.Wt = 92
        self.Wr = False
        self.Kr = True
        return {
            "percent": 92,
            "raw_level": 92,
            "voltage_mv": 4070,
            "charging": False,
            "mac": "da:cc:54",
            "timestamp": now,
        }

    def _save_cache(self, state: Dict[str, Any]):
        try:
            self.cache_file.write_text(json.dumps(state, indent=2), encoding="utf-8")
        except Exception:
            pass

    def find_device_path(self) -> tuple[Optional[bytes], str]:
        """Finds the HID device path for Scyrox V8/V6.
        Prioritizes wired USB cable (0xF5F6) over wireless dongle (0xF5F7).
        """
        try:
            devs = hid.enumerate(VENDOR_ID, 0)
        except Exception:
            return None, "none"

        # Check wired first
        for d in devs:
            if d.get("product_id") == PID_WIRED:
                if d.get("usage_page") == USAGE_PAGE and d.get("usage") == USAGE:
                    return d["path"], "wired"

        # Fall back to wireless
        for d in devs:
            if d.get("product_id") == PID_WIRELESS:
                if d.get("usage_page") == USAGE_PAGE and d.get("usage") == USAGE:
                    return d["path"], "wireless"

        return None, "none"

    def query(self) -> Dict[str, Any]:
        """Queries the mouse state. Returns accurate smoothed battery metrics."""
        path, mode = self.find_device_path()
        now = time.time()

        if not path:
            return {
                "connected": False,
                "online": False,
                "mode": "none",
                "status": "disconnected",
                "percent": self._last_state.get("percent", 92),
                "voltage_mv": self._last_state.get("voltage_mv", 0),
                "charging": False,
                "mac": self._last_state.get("mac", "unknown"),
            }

        dev = hid.device()
        try:
            dev.open_path(path)
            dev.set_nonblocking(False)

            is_online = False
            mac = self._last_state.get("mac", "da:cc:54")
            raw_level = self._last_state.get("raw_level", 92)
            voltage_mv = self._last_state.get("voltage_mv", 4070)

            if mode == "wireless":
                # 1. Notify dongle that PC driver is active
                dev.write(build_packet(2, [1]))
                dev.read(REPORT_LENGTH, timeout_ms=80)

                # 2. Flush leftover input reports from Windows buffer
                dev.set_nonblocking(True)
                while dev.read(REPORT_LENGTH):
                    pass
                dev.set_nonblocking(False)

                # 3. Check online status (CMD 3)
                dev.write(build_packet(ONLINE_COMMAND))
                res = dev.read(REPORT_LENGTH, timeout_ms=250)
                if res and len(res) >= 10 and res[0] == REPORT_ID and res[1] == ONLINE_COMMAND:
                    is_online = (res[6] == 1)
                    mac = ":".join(f"{x:02x}" for x in res[7:10])

                # 4. Query battery level (CMD 4)
                dev.write(build_packet(BATTERY_COMMAND))
                b = dev.read(REPORT_LENGTH, timeout_ms=300)
                dev.close()

                if b and len(b) >= 10 and b[0] == REPORT_ID and b[1] == BATTERY_COMMAND:
                    is_online = True
                    raw_level = b[6]
                    voltage_mv = (b[8] << 8) | b[9]

                    # Scyrox V8 wireless cannot charge wirelessly
                    ca = voltage_to_level(voltage_mv, charging=False)

                    # Transition or update
                    if self._last_state.get("charging", False) or self.Wt > ca:
                        self.Wt = ca
                        self.Kr = True
                        self.Wr = False
                    else:
                        if now - self.last_ug_time >= 10.0:
                            self.last_ug_time = now
                            if ca < self.Wt and self.Wt > 0:
                                self.Wt -= 1

                    percent = max(0, min(100, self.Wt))
                    state = {
                        "connected": True,
                        "online": True,
                        "mode": "wireless",
                        "status": "active",
                        "percent": percent,
                        "raw_level": raw_level,
                        "voltage_mv": voltage_mv,
                        "charging": False,
                        "mac": mac,
                        "timestamp": now,
                    }
                    self._last_state = state
                    self._save_cache(state)
                    return state

                else:
                    # Mouse RF is currently idle/sleep
                    # Check if transitioning from cable to wireless
                    if self._last_state.get("charging", False) or self._last_state.get("mode") == "wired":
                        prev_v = self._last_state.get("voltage_mv", 4070)
                        if prev_v > 4080:
                            prev_v = 4070  # Open-circuit cell relaxation voltage
                        self.Wt = voltage_to_level(prev_v, False)  # 92%
                        self.Kr = True
                        self.Wr = False
                        self._last_state["charging"] = False
                        self._last_state["mode"] = "wireless"
                        self._last_state["voltage_mv"] = prev_v
                        self._last_state["percent"] = self.Wt
                        self._save_cache(self._last_state)

                    percent = max(0, min(100, self.Wt))
                    return {
                        "connected": True,
                        "online": is_online,
                        "mode": "wireless",
                        "status": "active" if is_online else "asleep",
                        "percent": percent,
                        "raw_level": raw_level,
                        "voltage_mv": self._last_state.get("voltage_mv", 4070),
                        "charging": False,
                        "mac": mac,
                        "timestamp": now,
                    }

            else:
                # Wired USB mode (0xF5F6)
                dev.write(build_packet(BATTERY_COMMAND))
                b = dev.read(REPORT_LENGTH, timeout_ms=350)
                dev.close()

                if b and len(b) >= 10 and b[0] == REPORT_ID and b[1] == BATTERY_COMMAND:
                    raw_level = b[6]
                    voltage_mv = (b[8] << 8) | b[9]
                    charging = True
                    ca = voltage_to_level(voltage_mv, charging=True)

                    if self.Wt >= 85 and ca >= 95:
                        self.Kr = False
                        self.Wr = True
                    elif self.Wt < 85:
                        self.Kr = True
                        self.Wr = False

                    if now - self.last_ug_time >= 10.0:
                        self.last_ug_time = now
                        if self.Kr and ca > self.Wt and ca < 100:
                            if ca - 10 > self.Wt:
                                self.Wt += 1
                            if self.Wt >= 85:
                                self.Kr = False
                                self.Wr = True

                    if now - self.last_cg_time >= 60.0:
                        self.last_cg_time = now
                        if self.Wr and self.Wt < 99:
                            self.Wt += 1

                    if raw_level == 100:
                        self.full_counter += 1
                        if self.full_counter >= 8:
                            self.Wt = 100
                    else:
                        self.full_counter = 0

                    percent = max(0, min(100, self.Wt))
                    state = {
                        "connected": True,
                        "online": True,
                        "mode": "wired",
                        "status": "charging",
                        "percent": percent,
                        "raw_level": raw_level,
                        "voltage_mv": voltage_mv,
                        "charging": True,
                        "mac": mac,
                        "timestamp": now,
                    }
                    self._last_state = state
                    self._save_cache(state)
                    return state
                else:
                    percent = max(0, min(100, self.Wt))
                    return {
                        "connected": True,
                        "online": True,
                        "mode": "wired",
                        "status": "charging",
                        "percent": percent,
                        "raw_level": raw_level,
                        "voltage_mv": self._last_state.get("voltage_mv", 4130),
                        "charging": True,
                        "mac": mac,
                        "timestamp": now,
                    }

        except Exception as e:
            try:
                dev.close()
            except Exception:
                pass
            return {
                "connected": False,
                "online": False,
                "mode": mode,
                "status": "error",
                "error": str(e),
                "percent": self._last_state.get("percent", 92),
                "voltage_mv": self._last_state.get("voltage_mv", 0),
                "charging": False,
                "mac": self._last_state.get("mac", "unknown"),
            }
