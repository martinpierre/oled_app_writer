#!/usr/bin/env python3
"""
oled_server.py - Pont entre le front web (oled_front.html) et l'Arduino.

    navigateur  --WebSocket-->  ce serveur  --série-->  Arduino + OLED

Installation :  pip install -r requirements.txt
Lancement    :  python oled_server.py                 (choix du port dans l'interface)
                python oled_server.py --serial COM3   (ouverture automatique)
Puis ouvrir sur le téléphone l'adresse affichée (ex. http://192.168.1.20:8000).

Protocole navigateur -> serveur :
  - messages BINAIRES : octets bruts du protocole OLED (identiques à l'Arduino)
        2 octets par pixel : [1 C yyyyyy] [0 xxxxxxx]   ;  0x7F seul = effacer
  - messages TEXTE (JSON) : {"cmd":"open","port":"COM3"} | {"cmd":"close"}
Serveur -> navigateur :
  - JSON {"type":"status","connected":bool,"port":str|null,"ports":[...],"error":str|null}
  - BINAIRE : état de l'écran (au chargement) ou dessin d'un autre client
"""
import argparse
import asyncio
import json
import pathlib
import queue
import socket
import threading
import time

import serial
import serial.tools.list_ports
from aiohttp import WSMsgType, web

W, H = 128, 64
BAUD = 115200
CHUNK = 60                      # octets envoyés entre deux accusés (buffer Uno = 63)
CLEAR = 0x7F
FRONT = pathlib.Path(__file__).with_name("oled_front.html")


# --------------------------------------------------------------------------
#  Liaison série avec contrôle de flux (accusé 'K' de l'Arduino)
# --------------------------------------------------------------------------
class SerialLink:
    def __init__(self):
        self.ser = None
        self.port = None
        self.q = queue.Queue()
        self.ack = threading.Event()
        self.ack.set()
        threading.Thread(target=self._tx_loop, daemon=True).start()

    @property
    def connected(self):
        return self.ser is not None

    def open(self, port):
        self.close()
        ser = serial.Serial(port, BAUD, timeout=0.05)
        time.sleep(2)                       # l'Uno reboote à l'ouverture du port
        ser.reset_input_buffer()
        self.ser, self.port = ser, port
        self.ack.set()
        threading.Thread(target=self._rx_loop, args=(ser,), daemon=True).start()

    def close(self):
        ser, self.ser, self.port = self.ser, None, None
        if ser:
            try:
                ser.close()
            except Exception:
                pass
        while not self.q.empty():
            self.q.get_nowait()

    def send(self, data):
        if self.ser and data:
            self.q.put(bytes(data))

    def _rx_loop(self, ser):
        while self.ser is ser:
            try:
                if ser.read(64):
                    self.ack.set()
            except Exception:               # câble débranché
                if self.ser is ser:
                    self.ser, self.port = None, None
                break

    def _tx_loop(self):
        pending = bytearray()
        while True:
            pending += self.q.get()
            try:
                while True:
                    pending += self.q.get_nowait()
            except queue.Empty:
                pass
            while pending:
                ser = self.ser
                if ser is None:
                    pending.clear()
                    break
                self.ack.wait(0.3)          # timeout : jamais bloqué
                self.ack.clear()
                chunk = bytes(pending[:CHUNK])
                del pending[:CHUNK]
                try:
                    ser.write(chunk)
                except Exception:
                    self.ser, self.port = None, None
                    pending.clear()


# --------------------------------------------------------------------------
#  État de l'écran (pour resynchroniser un nouveau client / l'Arduino)
# --------------------------------------------------------------------------
def apply_to_grid(grid, data):
    hi = None
    for b in data:
        if b & 0x80:
            hi = b
        elif hi is not None:
            grid[(hi & 0x3F) * W + b] = (hi >> 6) & 1
            hi = None
        elif b == CLEAR:
            grid[:] = bytes(W * H)


def snapshot(grid):
    out = bytearray([CLEAR])
    for i, v in enumerate(grid):
        if v:
            out += bytes((0xC0 | (i // W), i % W))
    return bytes(out)


def list_ports():
    return [{"device": p.device, "desc": p.description} for p in serial.tools.list_ports.comports()]


def status(app):
    link = app["link"]
    return {"type": "status", "connected": link.connected, "port": link.port,
            "ports": list_ports(), "error": app["error"]}


async def broadcast(app, *, text=None, data=None, skip=None):
    for ws in list(app["clients"]):
        if ws is skip or ws.closed:
            continue
        try:
            if text is not None:
                await ws.send_str(text)
            else:
                await ws.send_bytes(data)
        except Exception:
            pass


async def open_serial(app, port):
    loop = asyncio.get_running_loop()
    app["error"] = None
    try:
        await loop.run_in_executor(None, app["link"].open, port)
        app["link"].send(snapshot(app["grid"]))     # remet l'écran dans l'état courant
    except Exception as e:
        app["error"] = str(e).split(":")[0][:60] or "Ouverture impossible"


# --------------------------------------------------------------------------
#  Routes
# --------------------------------------------------------------------------
async def index(request):
    return web.FileResponse(FRONT)


async def ws_handler(request):
    app = request.app
    ws = web.WebSocketResponse(heartbeat=20, max_msg_size=1 << 20)
    await ws.prepare(request)
    app["clients"].add(ws)
    await ws.send_str(json.dumps(status(app)))
    await ws.send_bytes(snapshot(app["grid"]))
    try:
        async for msg in ws:
            if msg.type == WSMsgType.BINARY:
                apply_to_grid(app["grid"], msg.data)
                app["link"].send(msg.data)
                await broadcast(app, data=msg.data, skip=ws)
            elif msg.type == WSMsgType.TEXT:
                try:
                    cmd = json.loads(msg.data)
                except ValueError:
                    continue
                if cmd.get("cmd") == "open" and cmd.get("port"):
                    await open_serial(app, cmd["port"])
                elif cmd.get("cmd") == "close":
                    app["link"].close()
                    app["error"] = None
                await broadcast(app, text=json.dumps(status(app)))
    finally:
        app["clients"].discard(ws)
    return ws


async def watcher(app):
    """Diffuse l'état (branchement/débranchement, perte du câble) quand il change."""
    last = None
    while True:
        await asyncio.sleep(1)
        cur = json.dumps(status(app))
        if cur != last:
            last = cur
            await broadcast(app, text=cur)


async def on_startup(app):
    app["watch"] = asyncio.create_task(watcher(app))
    if app["auto_port"]:
        await open_serial(app, app["auto_port"])


def local_ip():
    try:
        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as s:
            s.connect(("10.255.255.255", 1))
            return s.getsockname()[0]
    except Exception:
        return "127.0.0.1"


def main():
    ap = argparse.ArgumentParser(description="Pont WebSocket -> série pour l'OLED")
    ap.add_argument("--host", default="0.0.0.0", help="interface d'écoute (défaut : toutes)")
    ap.add_argument("--http-port", type=int, default=8000)
    ap.add_argument("--serial", help="port série à ouvrir au démarrage (ex. COM3, /dev/ttyACM0)")
    args = ap.parse_args()

    app = web.Application()
    app.update(link=SerialLink(), grid=bytearray(W * H), clients=set(),
               error=None, auto_port=args.serial)
    app.router.add_get("/", index)
    app.router.add_get("/ws", ws_handler)
    app.on_startup.append(on_startup)

    print(f"Sur ce PC       : http://localhost:{args.http_port}")
    print(f"Sur le téléphone: http://{local_ip()}:{args.http_port}  (même Wi-Fi)")
    web.run_app(app, host=args.host, port=args.http_port, print=None)


if __name__ == "__main__":
    main()
