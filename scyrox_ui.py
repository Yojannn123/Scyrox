"""
Scyrox V8 / V6 Desktop Floating Widget & System Tray Application.
Enhanced with Gaming Overlay (Topmost), Live Cable Charging Monitor,
and Real-Time Battery Time Estimator (Charging / Discharge).
"""

import ctypes
from ctypes import wintypes
import os
import sys
import threading
import time
import tkinter as tk
from tkinter import Menu
from typing import Dict, Any, Optional
from PIL import Image, ImageDraw, ImageFont
import pystray

from scyrox_driver import ScyroxDriver, voltage_to_level
from scyrox_config import ConfigManager
import scyrox_autostart

GA_ROOT = 2
GWL_EXSTYLE = -20
WS_EX_TRANSPARENT = 0x00000020
WS_EX_LAYERED = 0x00080000
WS_EX_NOACTIVATE = 0x08000000
DWMWA_WINDOW_CORNER_PREFERENCE = 33
DWMWCP_ROUND = 2


def get_charge_time_estimate(percent: int) -> str:
    """Estimates time remaining to reach 100% full charge on Scyrox V8 (250mAh)."""
    if percent >= 100:
        return "Batería completa"
    # CC phase up to 80%: ~1.05 min per 1%
    # CV phase 80% to 100%: ~1.6 min per 1%
    if percent < 80:
        mins = int((80 - percent) * 1.05 + 32)
    else:
        mins = int((100 - percent) * 1.6)

    mins = max(1, mins)
    if mins >= 60:
        h = mins // 60
        m = mins % 60
        return f"{h}h {m}m" if m > 0 else f"{h}h"
    return f"{mins} min"


def get_discharge_time_estimate(percent: int) -> str:
    """Estimates remaining battery life during wireless usage."""
    if percent <= 0:
        return "0 min"
    # ~40 hours of active gaming on 100% charge (~0.40 h per 1%)
    total_hours = percent * 0.40
    if total_hours >= 1.0:
        h = int(total_hours)
        m = int((total_hours - h) * 60)
        return f"{h}h {m}m" if m > 0 else f"{h}h"
    mins = max(5, int(percent * 24))
    return f"{mins} min"


class ScyroxApp:
    def __init__(self):
        self.config = ConfigManager()
        self.driver = ScyroxDriver()

        self.root = tk.Tk()
        self.root.title("Scyrox Battery Overlay")

        # Configure frameless window & topmost
        self.root.overrideredirect(True)
        self.root.attributes("-alpha", float(self.config.get("opacity", 0.95)))
        self.root.attributes("-topmost", True)
        self.root.configure(bg="#09090b")

        # State tracking
        self.current_state: Dict[str, Any] = self.driver.query()
        self.is_running = True
        self.last_low_alert_time = 0.0
        self.last_charging_state = self.current_state.get("charging", False)
        self.last_charged_alert = False

        # Drag tracking
        self.drag_start_x = 0
        self.drag_start_y = 0

        # UI Dimensions
        self.normal_w, self.normal_h = 240, 70
        self.compact_w, self.compact_h = 120, 36

        # Setup Canvas with modern border
        self.canvas = tk.Canvas(
            self.root,
            bg="#121214",
            highlightthickness=1,
            highlightbackground="#3f3f46",
            cursor="fleur" if not self.config.get("lock_position", False) else "arrow",
        )
        self.canvas.pack(fill="both", expand=True)

        # Context Menu
        self.menu = Menu(
            self.root,
            tearoff=0,
            bg="#18181b",
            fg="#f4f4f5",
            activebackground="#27272a",
            activeforeground="#ffffff",
        )
        self.menu.add_command(label="Ocultar a la bandeja", command=self.hide_widget)
        self.menu.add_command(
            label="Modo compacto" if not self.config.get("compact_mode", False) else "Modo detallado",
            command=self.toggle_compact_mode,
        )
        self.menu.add_command(
            label="🎮 Activar Modo Gaming" if not self.config.get("gaming_mode", False) else "🎮 Desactivar Modo Gaming",
            command=self.toggle_gaming_mode,
        )
        self.menu.add_separator()
        self.menu.add_command(
            label="Bloquear posición" if not self.config.get("lock_position", False) else "Desbloquear posición",
            command=self.toggle_lock_position,
        )
        self.menu.add_command(
            label="Siempre visible" if self.config.get("always_on_top", True) else "No siempre visible",
            command=self.toggle_always_on_top,
        )
        self.menu.add_command(
            label="Iniciar con Windows" if not scyrox_autostart.is_autostart_enabled() else "Desactivar inicio con Windows",
            command=self.toggle_autostart,
        )
        self.menu.add_separator()
        self.menu.add_command(label="Salir", command=self.quit_app)

        # Event bindings
        self.canvas.bind("<ButtonPress-1>", self.on_drag_start)
        self.canvas.bind("<B1-Motion>", self.on_drag_motion)
        self.canvas.bind("<ButtonRelease-1>", self.on_drag_release)
        self.canvas.bind("<Button-3>", self.show_context_menu)
        self.canvas.bind("<Double-Button-1>", lambda e: self.toggle_compact_mode())

        # Initialize Position, Shape & Gaming Mode
        self.init_position()
        self.apply_window_shape()
        self.apply_gaming_mode()

        # Initial render before showing
        self.render_widget()

        # Ensure window is mapped and visible on desktop
        if self.config.get("show_widget", True):
            self.root.deiconify()
            self.root.lift()
            self.root.focus_force()
        else:
            self.root.withdraw()

        # Initialize System Tray
        self.tray_icon: Optional[pystray.Icon] = None
        self.setup_tray()

        # Synchronize Autostart setting
        if self.config.get("autostart", True) and not scyrox_autostart.is_autostart_enabled():
            scyrox_autostart.set_autostart(True)

        # Start background worker thread
        self.poll_thread = threading.Thread(target=self.poll_worker, daemon=True)
        self.poll_thread.start()

    def get_root_hwnd(self) -> int:
        """Finds the top-level Win32 HWND for the Tkinter window."""
        self.root.update_idletasks()
        wid = self.root.winfo_id()
        try:
            hwnd = ctypes.windll.user32.GetAncestor(wid, GA_ROOT)
            return hwnd if hwnd else wid
        except Exception:
            return wid

    def init_position(self):
        screen_w = self.root.winfo_screenwidth()
        screen_h = self.root.winfo_screenheight()

        pos_x = self.config.get("pos_x", -1)
        pos_y = self.config.get("pos_y", -1)

        # Default position: Top-Right corner of screen (standard HUD overlay position)
        if pos_x < 0 or pos_y < 0 or pos_x >= screen_w or pos_y >= screen_h:
            pos_x = screen_w - self.normal_w - 40
            pos_y = 50
            self.config.set("pos_x", pos_x)
            self.config.set("pos_y", pos_y)

        self.root.geometry(f"+{pos_x}+{pos_y}")

    def apply_window_shape(self):
        is_compact = self.config.get("compact_mode", False)
        w = self.compact_w if is_compact else self.normal_w
        h = self.compact_h if is_compact else self.normal_h

        self.root.geometry(f"{w}x{h}")
        self.root.update_idletasks()

        hwnd = self.get_root_hwnd()
        if hwnd:
            try:
                # Native Windows 11 rounded corners via DWM
                pref = ctypes.c_int(DWMWCP_ROUND)
                ctypes.windll.dwmapi.DwmSetWindowAttribute(
                    hwnd,
                    DWMWA_WINDOW_CORNER_PREFERENCE,
                    ctypes.byref(pref),
                    ctypes.sizeof(pref),
                )
            except Exception:
                pass

    def reassert_topmost(self):
        """Ensures the window stays on top of borderless full-screen games."""
        if self.config.get("always_on_top", True) and self.root.winfo_viewable():
            try:
                self.root.lift()
                self.root.attributes("-topmost", True)
                if self.config.get("gaming_mode", False):
                    self.apply_gaming_mode()
            except Exception:
                pass

    def apply_gaming_mode(self):
        """Enables true click-through overlay (WS_EX_TRANSPARENT | WS_EX_NOACTIVATE)."""
        hwnd = self.get_root_hwnd()
        is_gaming = self.config.get("gaming_mode", False)
        if hwnd:
            try:
                style = ctypes.windll.user32.GetWindowLongW(hwnd, GWL_EXSTYLE)
                if is_gaming:
                    new_style = style | WS_EX_TRANSPARENT | WS_EX_LAYERED | WS_EX_NOACTIVATE
                else:
                    new_style = (style & ~WS_EX_TRANSPARENT)
                ctypes.windll.user32.SetWindowLongW(hwnd, GWL_EXSTYLE, new_style)
            except Exception:
                pass

        if is_gaming:
            self.canvas.config(cursor="arrow")
        else:
            is_locked = self.config.get("lock_position", False)
            self.canvas.config(cursor="arrow" if is_locked else "fleur")

    def toggle_gaming_mode(self):
        new_val = not self.config.get("gaming_mode", False)
        self.config.set("gaming_mode", new_val)
        self.apply_gaming_mode()
        self.update_tray_menu()
        if new_val and self.tray_icon:
            try:
                self.tray_icon.notify(
                    "Modo Gaming activado. Los clics atravesarán el widget directamente hacia el juego. Para desactivarlo, haz clic en este icono en la barra oculta.",
                    title="🎮 Scyrox V8: Modo Gaming Activado",
                )
            except Exception:
                pass
        elif not new_val and self.tray_icon:
            try:
                self.tray_icon.notify(
                    "Modo Gaming desactivado. Ahora puedes mover o interactuar con el widget normalmente.",
                    title="🎮 Scyrox V8: Modo Normal",
                )
            except Exception:
                pass

    def on_drag_start(self, event):
        if self.config.get("gaming_mode", False) or self.config.get("lock_position", False):
            return
        self.drag_start_x = event.x
        self.drag_start_y = event.y

    def on_drag_motion(self, event):
        if self.config.get("gaming_mode", False) or self.config.get("lock_position", False):
            return
        dx = event.x - self.drag_start_x
        dy = event.y - self.drag_start_y
        x = self.root.winfo_x() + dx
        y = self.root.winfo_y() + dy
        self.root.geometry(f"+{x}+{y}")

    def on_drag_release(self, event):
        if self.config.get("gaming_mode", False) or self.config.get("lock_position", False):
            return
        self.config.set("pos_x", self.root.winfo_x())
        self.config.set("pos_y", self.root.winfo_y())

    def show_context_menu(self, event):
        if self.config.get("gaming_mode", False):
            return
        self.menu.entryconfig(
            1,
            label="Modo compacto" if not self.config.get("compact_mode", False) else "Modo detallado",
        )
        self.menu.entryconfig(
            2,
            label="🎮 Activar Modo Gaming" if not self.config.get("gaming_mode", False) else "🎮 Desactivar Modo Gaming",
        )
        self.menu.entryconfig(
            4,
            label="Bloquear posición" if not self.config.get("lock_position", False) else "Desbloquear posición",
        )
        self.menu.entryconfig(
            5,
            label="Siempre visible" if self.config.get("always_on_top", True) else "No siempre visible",
        )
        self.menu.entryconfig(
            6,
            label="Iniciar con Windows" if not scyrox_autostart.is_autostart_enabled() else "Desactivar inicio con Windows",
        )
        self.menu.tk_popup(event.x_root, event.y_root)

    def toggle_compact_mode(self):
        new_val = not self.config.get("compact_mode", False)
        self.config.set("compact_mode", new_val)
        self.apply_window_shape()
        self.render_widget()
        self.update_tray_menu()

    def toggle_lock_position(self):
        new_val = not self.config.get("lock_position", False)
        self.config.set("lock_position", new_val)
        self.canvas.config(cursor="arrow" if new_val else "fleur")
        self.update_tray_menu()

    def toggle_always_on_top(self):
        new_val = not self.config.get("always_on_top", True)
        self.config.set("always_on_top", new_val)
        self.root.attributes("-topmost", new_val)
        self.update_tray_menu()

    def toggle_autostart(self):
        currently_enabled = scyrox_autostart.is_autostart_enabled()
        scyrox_autostart.set_autostart(not currently_enabled)
        self.config.set("autostart", not currently_enabled)
        self.update_tray_menu()

    def toggle_widget(self):
        if self.root.winfo_viewable():
            self.hide_widget()
        else:
            self.show_widget()

    def hide_widget(self):
        self.root.withdraw()
        self.config.set("show_widget", False)
        self.update_tray_menu()

    def show_widget(self):
        self.root.deiconify()
        self.root.lift()
        self.reassert_topmost()
        self.config.set("show_widget", True)
        self.update_tray_menu()

    def get_status_details(self) -> tuple[str, str, str]:
        """Returns (accent_color, badge_text, status_text) based on device state."""
        state = self.current_state
        charging = state.get("charging", False)
        online = state.get("online", False)
        connected = state.get("connected", False)
        percent = max(0, min(100, state.get("percent", 35)))
        mode = state.get("mode", "wireless")

        if not connected:
            return "#64748b", "Off", "Desconectado"

        # CHARGING / CABLE CONNECTED
        if charging:
            badge = "Cable ⚡" if mode == "wired" else "Cargando ⚡"
            if percent >= 100:
                return "#22c55e", badge, "100% Batería llena"
            else:
                return "#06b6d4", badge, f"Cargando: {percent}%"

        # WIRELESS & SLEEP
        if not online:
            return "#94a3b8", "8K 2.4G", f"{percent}% • En reposo"

        # WIRELESS & ACTIVE
        badge = "8K 2.4G"
        if percent >= 40:
            return "#22c55e", badge, f"{percent}% • En uso"
        elif percent >= 20:
            return "#eab308", badge, f"{percent}% • Batería media"
        else:
            return "#ef4444", badge, f"{percent}% • ¡Batería baja!"

    def get_time_estimate(self) -> tuple[str, str]:
        """Calculates row 3 display: charging time to 100% or battery life remaining."""
        state = self.current_state
        connected = state.get("connected", False)
        online = state.get("online", False)
        charging = state.get("charging", False)
        percent = max(0, min(100, state.get("percent", 35)))

        if not connected:
            return "Mouse apagado o desconectado", "#71717a"

        if charging:
            if percent >= 100:
                return "🟢 ¡Batería completa! Desconectar", "#22c55e"
            t_est = get_charge_time_estimate(percent)
            return f"⏱️ Carga completa: ~{t_est}", "#38bdf8"

        if not online:
            return "💤 En reposo • Modo ahorro de batería", "#71717a"

        t_est = get_discharge_time_estimate(percent)
        return f"⏱️ Batería restante: ~{t_est}", "#a1a1aa"

    def render_widget(self):
        self.canvas.delete("all")
        is_compact = self.config.get("compact_mode", False)
        w = self.compact_w if is_compact else self.normal_w
        h = self.compact_h if is_compact else self.normal_h

        accent_color, badge_text, status_text = self.get_status_details()
        time_text, time_color = self.get_time_estimate()
        percent = max(0, min(100, self.current_state.get("percent", 35)))
        charging = self.current_state.get("charging", False)
        voltage = self.current_state.get("voltage_mv", 0)
        volt_str = f"{voltage/1000.0:.2f}V" if voltage > 0 else ""

        if is_compact:
            # Compact Mode (120x36)
            bx, by, bw, bh = 10, 10, 32, 16
            self.canvas.create_rectangle(bx, by, bx + bw, by + bh, outline="#71717a", width=1)
            self.canvas.create_rectangle(bx + bw, by + 4, bx + bw + 3, by + bh - 4, fill="#71717a", outline="")
            fill_w = max(2, int((bw - 4) * (percent / 100.0)))
            self.canvas.create_rectangle(bx + 2, by + 2, bx + 2 + fill_w, by + bh - 2, fill=accent_color, outline="")

            display_txt = f"⚡ {percent}%" if charging else f"{percent}%"
            self.canvas.create_text(
                bx + bw + 10,
                by + (bh // 2),
                text=display_txt,
                anchor="w",
                fill=accent_color,
                font=("Segoe UI", 10, "bold"),
            )
        else:
            # Normal Detailed Mode (240x70)
            # Battery Icon on Left
            bx, by, bw, bh = 14, 25, 34, 18
            self.canvas.create_rectangle(bx, by, bx + bw, by + bh, outline="#71717a", width=1)
            self.canvas.create_rectangle(bx + bw, by + 4, bx + bw + 3, by + bh - 4, fill="#71717a", outline="")
            fill_w = max(2, int((bw - 4) * (percent / 100.0)))
            self.canvas.create_rectangle(bx + 2, by + 2, bx + 2 + fill_w, by + bh - 2, fill=accent_color, outline="")

            # Row 1 (y = 16): Device Name + Badge
            self.canvas.create_text(
                58,
                16,
                text="Scyrox V8",
                anchor="w",
                fill="#f4f4f5",
                font=("Segoe UI", 10, "bold"),
            )
            self.canvas.create_text(
                w - 12,
                16,
                text=badge_text,
                anchor="e",
                fill=accent_color if charging else "#a1a1aa",
                font=("Segoe UI", 8, "bold" if charging else "normal"),
            )

            # Row 2 (y = 35): Percentage / Charging state + Voltage
            self.canvas.create_text(
                58,
                35,
                text=status_text,
                anchor="w",
                fill=accent_color,
                font=("Segoe UI", 9, "bold" if charging else "normal"),
            )
            if volt_str:
                self.canvas.create_text(
                    w - 12,
                    35,
                    text=volt_str,
                    anchor="e",
                    fill="#71717a",
                    font=("Segoe UI", 8),
                )

            # Row 3 (y = 53): Estimated Charging Time or Remaining Battery Life
            self.canvas.create_text(
                58,
                53,
                text=time_text,
                anchor="w",
                fill=time_color,
                font=("Segoe UI", 8),
            )

    def create_tray_image(self) -> Image.Image:
        img = Image.new("RGBA", (64, 64), (0, 0, 0, 0))
        draw = ImageDraw.Draw(img)

        draw.rounded_rectangle((2, 2, 61, 61), radius=16, fill=(18, 18, 22, 245), outline=(70, 70, 80, 255), width=2)

        percent = max(0, min(100, self.current_state.get("percent", 35)))
        charging = self.current_state.get("charging", False)
        online = self.current_state.get("online", False)
        connected = self.current_state.get("connected", False)

        if not connected:
            color = (100, 116, 139, 255)
            text = "—"
        elif charging:
            color = (34, 197, 94, 255) if percent >= 100 else (6, 182, 212, 255)
            text = f"{percent}"
        elif not online:
            color = (148, 163, 184, 255)
            text = f"{percent}"
        elif percent >= 40:
            color = (34, 197, 94, 255)
            text = f"{percent}"
        elif percent >= 20:
            color = (234, 179, 8, 255)
            text = f"{percent}"
        else:
            color = (239, 68, 68, 255)
            text = f"{percent}"

        bar_w = int(48 * (percent / 100.0))
        draw.rectangle((8, 52, 56, 55), fill=(40, 40, 48, 255))
        if bar_w > 0:
            draw.rectangle((8, 52, 8 + bar_w, 55), fill=color)

        try:
            font = ImageFont.truetype("segoeuib.ttf", 26 if len(text) <= 2 else 20)
        except Exception:
            font = ImageFont.load_default()

        bbox = draw.textbbox((0, 0), text, font=font)
        tw = bbox[2] - bbox[0]
        th = bbox[3] - bbox[1]
        tx = (64 - tw) // 2
        ty = (48 - th) // 2 - 2
        draw.text((tx, ty), text, font=font, fill=color)

        if charging:
            draw.text((4, 4), "⚡", fill=color)

        return img

    def setup_tray(self):
        menu = self.build_tray_menu()
        initial_img = self.create_tray_image()
        self.tray_icon = pystray.Icon("ScyroxBattery", initial_img, "Scyrox V8", menu)
        self.tray_icon.run_detached()

    def build_tray_menu(self) -> pystray.Menu:
        state = self.current_state
        percent = max(0, min(100, state.get("percent", 35)))
        charging = state.get("charging", False)
        online = state.get("online", False)
        time_text, _ = self.get_time_estimate()

        if charging:
            if percent >= 100:
                header = "Scyrox V8: 100% Completo (¡Desconectar cable!)"
            else:
                header = f"Scyrox V8: {percent}% ⚡ ({time_text})"
        elif not online:
            header = f"Scyrox V8: {percent}% (En reposo 💤)"
        else:
            header = f"Scyrox V8: {percent}% ({time_text})"

        return pystray.Menu(
            pystray.MenuItem(header, None, enabled=False),
            pystray.Menu.SEPARATOR,
            pystray.MenuItem(
                "Mostrar Widget en pantalla",
                lambda: self.root.after(0, self.toggle_widget),
                checked=lambda item: bool(self.config.get("show_widget", True)),
            ),
            pystray.MenuItem(
                "Modo compacto (Mini píldora)",
                lambda: self.root.after(0, self.toggle_compact_mode),
                checked=lambda item: bool(self.config.get("compact_mode", False)),
            ),
            pystray.MenuItem(
                "🎮 Modo Gaming (Clics transparentes)",
                lambda: self.root.after(0, self.toggle_gaming_mode),
                checked=lambda item: bool(self.config.get("gaming_mode", False)),
            ),
            pystray.MenuItem(
                "Bloquear posición",
                lambda: self.root.after(0, self.toggle_lock_position),
                checked=lambda item: bool(self.config.get("lock_position", False)),
            ),
            pystray.MenuItem(
                "Iniciar con Windows",
                lambda: self.root.after(0, self.toggle_autostart),
                checked=lambda item: scyrox_autostart.is_autostart_enabled(),
            ),
            pystray.Menu.SEPARATOR,
            pystray.MenuItem("Actualizar ahora", lambda: self.force_refresh()),
            pystray.MenuItem("Salir", lambda: self.root.after(0, self.quit_app)),
        )

    def update_tray_menu(self):
        if self.tray_icon:
            try:
                self.tray_icon.menu = self.build_tray_menu()
            except Exception:
                pass

    def force_refresh(self):
        threading.Thread(target=self.poll_once, daemon=True).start()

    def check_notifications(self, new_state: Dict[str, Any]):
        if not self.config.get("enable_notifications", True) or not self.tray_icon:
            return

        percent = max(0, min(100, new_state.get("percent", 35)))
        charging = new_state.get("charging", False)
        online = new_state.get("online", False)
        connected = new_state.get("connected", False)

        threshold = self.config.get("low_battery_threshold", 20)
        now = time.time()

        # 1. Cable plugged in notification
        if charging and not self.last_charging_state and self.config.get("cable_connected_alert", True):
            t_est = get_charge_time_estimate(percent)
            try:
                self.tray_icon.notify(
                    f"Cargando mouse al {percent}%. Tiempo para 100%: ~{t_est}.",
                    title="🔌 Cable conectado - Scyrox V8",
                )
            except Exception:
                pass

        # 2. Fully charged notification
        if charging and percent >= 100 and not self.last_charged_alert:
            self.last_charged_alert = True
            try:
                self.tray_icon.notify(
                    "¡Carga completada al 100%! Ya puedes desconectar el cable de tu mouse.",
                    title="⚡ Scyrox V8: Batería Completa",
                )
            except Exception:
                pass
        elif not charging:
            self.last_charged_alert = False

        # 3. Low battery alert
        if connected and online and not charging and percent <= threshold:
            if now - self.last_low_alert_time > 2700:
                self.last_low_alert_time = now
                t_est = get_discharge_time_estimate(percent)
                try:
                    self.tray_icon.notify(
                        f"Batería restante: {percent}% (~{t_est} de uso). Recuerda conectar el cable.",
                        title="⚠️ Scyrox V8: Batería Baja",
                    )
                except Exception:
                    pass

        self.last_charging_state = charging

    def poll_once(self):
        new_state = self.driver.query()
        self.check_notifications(new_state)
        self.current_state = new_state
        self.root.after(0, self.on_state_updated)

    def on_state_updated(self):
        self.render_widget()
        self.reassert_topmost()
        if self.tray_icon:
            try:
                self.tray_icon.icon = self.create_tray_image()
                time_text, _ = self.get_time_estimate()
                percent = max(0, min(100, self.current_state.get("percent", 35)))
                charging = self.current_state.get("charging", False)
                if charging:
                    self.tray_icon.title = f"Scyrox V8: {percent}% ⚡ • {time_text}"[:120]
                else:
                    self.tray_icon.title = f"Scyrox V8: {percent}% • {time_text}"[:120]
                self.update_tray_menu()
            except Exception:
                pass

    def poll_worker(self):
        while self.is_running:
            try:
                self.poll_once()
            except Exception as e:
                print(f"Poll error: {e}")

            if self.current_state.get("charging", False):
                time.sleep(1.5)
            elif self.current_state.get("online", False):
                time.sleep(3.5)
            else:
                time.sleep(4.0)

    def quit_app(self):
        self.is_running = False
        if self.tray_icon:
            try:
                self.tray_icon.stop()
            except Exception:
                pass
        self.root.destroy()
        sys.exit(0)

    def run(self):
        self.root.mainloop()
