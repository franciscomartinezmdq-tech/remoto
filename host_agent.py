"""
Remote Desktop — Host Agent (silent + autostart)
=================================================
- Corre sin ventana ni consola.
- Al primer arranque se registra en el inicio de Windows (sin admin).
- El viewer se conecta directo, sin PIN.
- Log en: %LOCALAPPDATA%\\RemoteDesktopHost\\host.log

Build:
    pip install pyinstaller aiortc mss pyautogui python-socketio aiohttp pillow numpy av
    pyinstaller --onefile --noconsole --name RemoteDesktopHost host_agent.py
"""

import asyncio
import logging
import pathlib
import sys

import mss
import pyautogui
import numpy
from PIL import Image
import socketio
from aiortc import RTCPeerConnection, RTCSessionDescription, VideoStreamTrack
from av import VideoFrame

# ── Config ────────────────────────────────────────────────────────────────────
SIGNAL_URL = "https://remoto-6lit.onrender.com"   # <-- reemplazar
APP_NAME   = "RemoteDesktopHost"
FPS        = 20
pyautogui.FAILSAFE = False
pyautogui.PAUSE    = 0

# ── Log a archivo (sin consola) ───────────────────────────────────────────────
LOG_PATH = pathlib.Path.home() / "AppData" / "Local" / APP_NAME / "host.log"
LOG_PATH.parent.mkdir(parents=True, exist_ok=True)

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%H:%M:%S",
    handlers=[logging.FileHandler(LOG_PATH, encoding="utf-8")],
)
log = logging.getLogger("host")
logging.getLogger("aiortc").setLevel(logging.WARNING)
logging.getLogger("aioice").setLevel(logging.WARNING)


# ── Autostart via registro de Windows ────────────────────────────────────────
def register_autostart():
    """
    Agrega el .exe al registro de Windows (HKCU) para que arranque con el
    sistema sin necesitar permisos de administrador.
    Se ejecuta solo en Windows; se ignora en otros OS.
    """
    if sys.platform != "win32":
        return

    try:
        import winreg

        # Ruta del ejecutable: sys.executable si es .py, sys.argv[0] si es .exe
        exe_path = str(
            pathlib.Path(
                sys.executable if getattr(sys, "frozen", False) else sys.argv[0]
            ).resolve()
        )

        reg_path = r"Software\Microsoft\Windows\CurrentVersion\Run"
        key = winreg.OpenKey(
            winreg.HKEY_CURRENT_USER,
            reg_path,
            0,
            winreg.KEY_READ | winreg.KEY_WRITE,
        )

        # Verificar si ya está registrado con el mismo path
        try:
            current, _ = winreg.QueryValueEx(key, APP_NAME)
        except FileNotFoundError:
            current = None

        if current != exe_path:
            winreg.SetValueEx(key, APP_NAME, 0, winreg.REG_SZ, exe_path)
            log.info(f"Autostart registrado: {exe_path}")
        else:
            log.info("Autostart ya estaba configurado.")

        winreg.CloseKey(key)

    except Exception as e:
        log.warning(f"No se pudo registrar autostart: {e}")


# ── Screen capture ────────────────────────────────────────────────────────────
class ScreenTrack(VideoStreamTrack):
    kind = "video"

    def __init__(self):
        super().__init__()
        self._sct     = mss.mss()
        self._monitor = self._sct.monitors[1]

    async def recv(self):
        pts, time_base = await self.next_timestamp()
        loop = asyncio.get_event_loop()
        arr  = await loop.run_in_executor(None, self._capture)
        frame           = VideoFrame.from_ndarray(arr, format="rgb24")
        frame.pts       = pts
        frame.time_base = time_base
        return frame

    def _capture(self):
        raw = self._sct.grab(self._monitor)
        img = Image.frombytes("RGB", (raw.width, raw.height), raw.rgb)
        return numpy.array(img)


# ── Input ─────────────────────────────────────────────────────────────────────
KEY_MAP = {
    "ArrowLeft":"left","ArrowRight":"right","ArrowUp":"up","ArrowDown":"down",
    "Enter":"enter","Backspace":"backspace","Delete":"delete","Escape":"esc",
    "Tab":"tab","CapsLock":"capslock","Home":"home","End":"end",
    "PageUp":"pageup","PageDown":"pagedown","Insert":"insert"," ":"space",
    "F1":"f1","F2":"f2","F3":"f3","F4":"f4","F5":"f5","F6":"f6",
    "F7":"f7","F8":"f8","F9":"f9","F10":"f10","F11":"f11",
    "Control":"ctrl","Shift":"shift","Alt":"alt","Meta":"win",
    "PrintScreen":"printscreen",
}
_pressed = set()


def handle_input(data: dict):
    try:
        t = data.get("type")
        if t == "mousemove":
            pyautogui.moveTo(data["x"], data["y"], duration=0)
        elif t in ("mousedown", "mouseup", "click"):
            btn = {0:"left",1:"middle",2:"right"}.get(data.get("button", 0), "left")
            if   t == "mousedown": pyautogui.mouseDown(data["x"], data["y"], button=btn)
            elif t == "mouseup":   pyautogui.mouseUp(data["x"], data["y"], button=btn)
            else:                  pyautogui.click(data["x"], data["y"], button=btn)
        elif t == "dblclick":
            pyautogui.doubleClick(data["x"], data["y"])
        elif t == "contextmenu":
            pyautogui.rightClick(data["x"], data["y"])
        elif t == "scroll":
            clicks = int(-data.get("deltaY", 0) / 120)
            if clicks: pyautogui.scroll(clicks)
        elif t == "keydown":
            key = _resolve_key(data)
            if key and key not in _pressed:
                _pressed.add(key)
                pyautogui.keyDown(key)
        elif t == "keyup":
            key = _resolve_key(data)
            if key and key in _pressed:
                _pressed.discard(key)
                pyautogui.keyUp(key)
    except Exception as e:
        log.warning(f"Input error ({data.get('type')}): {e}")


def _resolve_key(data):
    raw = data.get("key", "")
    if raw in KEY_MAP: return KEY_MAP[raw]
    if len(raw) == 1:  return raw
    return None


# ── Main ──────────────────────────────────────────────────────────────────────
async def run():
    pc  = None
    sio = socketio.AsyncClient(reconnection=True, reconnection_attempts=10)

    @sio.event
    async def connect():
        log.info("Conectado al servidor.")
        await sio.emit("host:register")

    @sio.event
    async def disconnect():
        log.warning("Desconectado. Reconectando…")

    @sio.on("host:viewer-joined")
    async def on_viewer_joined():
        nonlocal pc
        log.info("Viewer conectado — iniciando WebRTC…")

        pc = RTCPeerConnection()
        pc.addTrack(ScreenTrack())

        @pc.on("icecandidate")
        async def on_ice(candidate):
            if candidate:
                await sio.emit("signal:ice", {"candidate": {
                    "candidate":     candidate.candidate,
                    "sdpMid":        candidate.sdpMid,
                    "sdpMLineIndex": candidate.sdpMLineIndex,
                }})

        @pc.on("connectionstatechange")
        async def on_state():
            log.info(f"WebRTC: {pc.connectionState}")

        offer = await pc.createOffer()
        await pc.setLocalDescription(offer)
        await sio.emit("signal:offer", {"offer": {"type": offer.type, "sdp": offer.sdp}})

    @sio.on("signal:answer")
    async def on_answer(data):
        if pc:
            await pc.setRemoteDescription(RTCSessionDescription(**data["answer"]))

    @sio.on("signal:ice")
    async def on_ice_remote(data):
        if not pc or not data.get("candidate"): return
        from aiortc import RTCIceCandidate
        c = data["candidate"]
        try:
            cand = RTCIceCandidate(
                component=1, foundation="0", ip="0.0.0.0",
                port=0, priority=0, protocol="udp", type="host",
                sdpMid=c.get("sdpMid"), sdpMLineIndex=c.get("sdpMLineIndex"),
            )
            cand.candidate = c["candidate"]
            await pc.addIceCandidate(cand)
        except Exception as e:
            log.warning(f"ICE error: {e}")

    @sio.on("input:event")
    async def on_input(data):
        loop = asyncio.get_event_loop()
        await loop.run_in_executor(None, handle_input, data)

    @sio.on("host:viewer-left")
    async def on_viewer_left():
        nonlocal pc
        log.info("Viewer desconectado.")
        if pc:
            await pc.close()
            pc = None

    @sio.on("error")
    async def on_error(data):
        log.error(f"Error: {data.get('message')}")

    try:
        await sio.connect(SIGNAL_URL, transports=["websocket"])
        await sio.wait()
    except Exception as e:
        log.error(f"Conexión fallida: {e}")
    finally:
        if pc: await pc.close()
        await sio.disconnect()


# ── Entry point ───────────────────────────────────────────────────────────────
if __name__ == "__main__":
    # 1. Registrar autostart en Windows (solo la primera vez o si cambió de lugar)
    register_autostart()

    # 2. Arrancar el agente
    try:
        asyncio.run(run())
    except Exception as e:
        log.error(f"Error fatal: {e}")
