"""
Tools del prototipo.

Implementaciones mínimas para que el agente pueda actuar sobre el escritorio.
Esta es la versión desechable; la real vivirá en agent/tools/ con sandbox,
capability system y audit log (fase Link).
"""

from __future__ import annotations

import io
import os
import shutil
import subprocess
import time
from dataclasses import dataclass
from pathlib import Path

import mss
import pyautogui
from PIL import Image

# pyautogui defaults peligrosos: deshabilitamos failsafe en esquina
# (pero conservamos pausa entre acciones para estabilidad).
pyautogui.FAILSAFE = False
pyautogui.PAUSE = 0.05


@dataclass
class Screenshot:
    image: Image.Image
    width: int
    height: int

    def to_png_bytes(self) -> bytes:
        buf = io.BytesIO()
        self.image.save(buf, format="PNG")
        return buf.getvalue()

    def save(self, path: Path) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        self.image.save(path)


def screenshot() -> Screenshot:
    """Captura la pantalla principal."""
    with mss.mss() as sct:
        monitor = sct.monitors[1]  # primary
        raw = sct.grab(monitor)
        img = Image.frombytes("RGB", raw.size, raw.bgra, "raw", "BGRX")
        return Screenshot(image=img, width=img.width, height=img.height)


def mouse_move(x: int, y: int, duration: float = 0.15) -> None:
    pyautogui.moveTo(x, y, duration=duration)


def mouse_click(x: int, y: int, button: str = "left", clicks: int = 1) -> None:
    pyautogui.click(x=x, y=y, button=button, clicks=clicks, interval=0.05)


def mouse_drag(x1: int, y1: int, x2: int, y2: int, duration: float = 0.3) -> None:
    pyautogui.moveTo(x1, y1)
    pyautogui.dragTo(x2, y2, duration=duration, button="left")


def mouse_scroll(amount: int) -> None:
    pyautogui.scroll(amount)


def keyboard_type(text: str, interval: float = 0.02) -> None:
    pyautogui.write(text, interval=interval)


def keyboard_key(key: str) -> None:
    pyautogui.press(key)


def keyboard_shortcut(*keys: str) -> None:
    pyautogui.hotkey(*keys)


def app_launch(name: str) -> dict:
    """Lanza una aplicación.

    Estrategia: si existe gtk-launch + .desktop, úsalo. Si no, ejecutable directo.
    """
    if shutil.which("gtk-launch") and _desktop_file_exists(name):
        proc = subprocess.Popen(
            ["gtk-launch", name], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL
        )
    else:
        proc = subprocess.Popen(
            [name], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL
        )
    return {"pid": proc.pid, "name": name}


def _desktop_file_exists(name: str) -> bool:
    candidates = [
        Path(f"/usr/share/applications/{name}.desktop"),
        Path(f"/var/lib/flatpak/exports/share/applications/{name}.desktop"),
        Path.home() / f".local/share/applications/{name}.desktop",
    ]
    return any(p.exists() for p in candidates)


def shell_run(cmd: str, timeout: float = 30.0) -> dict:
    """Ejecuta un comando de shell. PROTOTIPO: sin sandbox.

    En la versión real, esto va dentro de bubblewrap con seccomp.
    """
    started = time.monotonic()
    try:
        result = subprocess.run(
            cmd,
            shell=True,
            capture_output=True,
            text=True,
            timeout=timeout,
            check=False,
        )
        return {
            "exit_code": result.returncode,
            "stdout": result.stdout[-4000:],
            "stderr": result.stderr[-2000:],
            "duration_s": round(time.monotonic() - started, 3),
        }
    except subprocess.TimeoutExpired:
        return {
            "exit_code": -1,
            "stdout": "",
            "stderr": f"timeout after {timeout}s",
            "duration_s": timeout,
        }


def get_screen_size() -> tuple[int, int]:
    return pyautogui.size()


def wait(seconds: float) -> None:
    time.sleep(seconds)
