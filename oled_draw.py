#!/usr/bin/env python3
"""
oled_draw.py - Dessin en direct sur un OLED SSD1306 128x64 via Arduino.

Dépendance :  pip install pyserial
Lancer     :  python oled_draw.py

Protocole série (115200 bauds, binaire, 2 octets par pixel) :
    octet 1 : 1 C yyyyyy   (bit7 = 1, C = couleur 1=blanc/0=noir, y = 0..63)
    octet 2 : 0 xxxxxxx    (x = 0..127)
    octet seul 0x7F        : efface tout l'écran
L'Arduino répond 'K' après chaque rafraîchissement (contrôle de flux).
"""
import queue
import threading
import time
import tkinter as tk
from tkinter import ttk

import serial
import serial.tools.list_ports

W, H, Z = 128, 64, 6          # taille OLED et facteur de zoom à l'écran
BAUD = 115200   
CHUNK = 60                    # octets envoyés entre deux accusés (buffer Uno = 63)
CLEAR_CMD = b"\x7f"
ON, OFF = "#f5f5f5", "#0a0a0a"


# --------------------------------------------------------------------------
#  Liaison série avec contrôle de flux
# --------------------------------------------------------------------------
class SerialLink:
    def __init__(self):
        self.ser = None
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
        time.sleep(2)                      # l'Arduino Uno reboote à l'ouverture
        ser.reset_input_buffer()
        self.ser = ser
        self.ack.set()
        threading.Thread(target=self._rx_loop, args=(ser,), daemon=True).start()

    def close(self):
        ser, self.ser = self.ser, None
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
            except Exception:
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
                self.ack.wait(0.3)         # timeout : on ne se bloque jamais
                self.ack.clear()
                chunk = bytes(pending[:CHUNK])
                del pending[:CHUNK]
                try:
                    ser.write(chunk)
                except Exception:
                    self.ser = None
                    pending.clear()


# --------------------------------------------------------------------------
#  Rastérisation des formes (renvoie des listes de points)
# --------------------------------------------------------------------------
def line(x0, y0, x1, y1):
    pts = []
    dx, dy = abs(x1 - x0), -abs(y1 - y0)
    sx = 1 if x0 < x1 else -1
    sy = 1 if y0 < y1 else -1
    err = dx + dy
    while True:
        pts.append((x0, y0))
        if x0 == x1 and y0 == y1:
            break
        e2 = 2 * err
        if e2 >= dy:
            err += dy
            x0 += sx
        if e2 <= dx:
            err += dx
            y0 += sy
    return pts


def circle(cx, cy, r):
    if r == 0:
        return [(cx, cy)]
    pts = set()
    x, y, d = r, 0, 1 - r
    while x >= y:
        for px, py in ((x, y), (y, x), (-x, y), (-y, x),
                       (x, -y), (y, -x), (-x, -y), (-y, -x)):
            pts.add((cx + px, cy + py))
        y += 1
        if d < 0:
            d += 2 * y + 1
        else:
            x -= 1
            d += 2 * (y - x) + 1
    return list(pts)


def square(x0, y0, x1, y1):
    s = max(abs(x1 - x0), abs(y1 - y0))
    x1 = x0 + s * (1 if x1 >= x0 else -1)
    y1 = y0 + s * (1 if y1 >= y0 else -1)
    corners = [(x0, y0), (x1, y0), (x1, y1), (x0, y1)]
    pts = set()
    for i in range(4):
        a, b = corners[i], corners[(i + 1) % 4]
        pts.update(line(a[0], a[1], b[0], b[1]))
    return list(pts)


def triangle(x0, y0, x1, y1):
    apex = ((x0 + x1) // 2, y0)
    bl, br = (x0, y1), (x1, y1)
    pts = set()
    for a, b in ((apex, br), (br, bl), (bl, apex)):
        pts.update(line(a[0], a[1], b[0], b[1]))
    return list(pts)


# --------------------------------------------------------------------------
#  Application
# --------------------------------------------------------------------------
class App:
    def __init__(self, root):
        self.root = root
        root.title("OLED 128x64 - dessin en direct")
        self.link = SerialLink()
        self.grid = [[0] * W for _ in range(H)]
        self.tool = tk.StringVar(value="crayon")
        self.color = tk.IntVar(value=1)
        self.start = self.last = None

        self._build_toolbar()
        self.canvas = tk.Canvas(root, width=W * Z, height=H * Z,
                                bg="black", highlightthickness=0, cursor="crosshair")
        self.canvas.pack(padx=8, pady=8)
        self.cells = [[self.canvas.create_rectangle(
            x * Z, y * Z, (x + 1) * Z, (y + 1) * Z, fill=OFF, outline="#161616")
            for x in range(W)] for y in range(H)]

        self.canvas.bind("<ButtonPress-1>", self.on_press)
        self.canvas.bind("<B1-Motion>", self.on_drag)
        self.canvas.bind("<ButtonRelease-1>", self.on_release)
        self.refresh_ports()

    # ---- interface -------------------------------------------------------
    def _build_toolbar(self):
        bar = ttk.Frame(self.root)
        bar.pack(fill="x", padx=8, pady=(8, 0))

        self.port_box = ttk.Combobox(bar, width=14, state="readonly")
        self.port_box.pack(side="left")
        ttk.Button(bar, text="↻", width=3, command=self.refresh_ports).pack(side="left")
        self.btn_conn = ttk.Button(bar, text="Connecter", command=self.toggle_conn)
        self.btn_conn.pack(side="left", padx=(4, 12))

        for label, val in (("Crayon", "crayon"), ("Ligne", "ligne"), ("Cercle", "cercle"),
                           ("Carré", "carre"), ("Triangle", "triangle")):
            ttk.Radiobutton(bar, text=label, value=val, variable=self.tool).pack(side="left", padx=2)

        ttk.Separator(bar, orient="vertical").pack(side="left", fill="y", padx=8)
        ttk.Radiobutton(bar, text="Blanc", value=1, variable=self.color).pack(side="left")
        ttk.Radiobutton(bar, text="Noir (gomme)", value=0, variable=self.color).pack(side="left")
        ttk.Button(bar, text="Effacer", command=self.clear).pack(side="left", padx=12)

        self.status = ttk.Label(bar, text="Hors ligne (simulation)")
        self.status.pack(side="right")

    def refresh_ports(self):
        ports = [p.device for p in serial.tools.list_ports.comports()]
        self.port_box["values"] = ports
        if ports and not self.port_box.get():
            self.port_box.set(ports[0])

    def toggle_conn(self):
        if self.link.connected:
            self.link.close()
            self.btn_conn.config(text="Connecter")
            self.status.config(text="Hors ligne (simulation)")
            return
        port = self.port_box.get()
        if not port:
            return
        self.status.config(text="Connexion…")
        self.root.update()
        try:
            self.link.open(port)
        except Exception as e:
            self.status.config(text=f"Erreur : {e}")
            return
        self.btn_conn.config(text="Déconnecter")
        self.status.config(text=f"Connecté {port} @ {BAUD}")
        self.clear()

    # ---- dessin ---------------------------------------------------------
    def apply(self, pts, c):
        out = bytearray()
        for x, y in pts:
            if 0 <= x < W and 0 <= y < H and self.grid[y][x] != c:
                self.grid[y][x] = c
                self.canvas.itemconfig(self.cells[y][x], fill=ON if c else OFF)
                out += bytes((0x80 | (c << 6) | y, x))
        self.link.send(out)

    def clear(self):
        self.grid = [[0] * W for _ in range(H)]
        for row in self.cells:
            for cell in row:
                self.canvas.itemconfig(cell, fill=OFF)
        self.link.send(CLEAR_CMD)

    def pos(self, e):
        return (max(0, min(W - 1, e.x // Z)), max(0, min(H - 1, e.y // Z)))

    def shape(self, a, b):
        t = self.tool.get()
        if t == "ligne":
            return line(*a, *b)
        if t == "cercle":
            r = int(round(((b[0] - a[0]) ** 2 + (b[1] - a[1]) ** 2) ** 0.5))
            return circle(a[0], a[1], r)
        if t == "carre":
            return square(*a, *b)
        if t == "triangle":
            return triangle(*a, *b)
        return []

    def on_press(self, e):
        self.start = self.last = self.pos(e)
        if self.tool.get() == "crayon":
            self.apply([self.start], self.color.get())

    def on_drag(self, e):
        cur = self.pos(e)
        if self.tool.get() == "crayon":
            self.apply(line(*self.last, *cur), self.color.get())
            self.last = cur
        else:
            self.canvas.delete("preview")
            for x, y in self.shape(self.start, cur):
                if 0 <= x < W and 0 <= y < H:
                    self.canvas.create_rectangle(x * Z, y * Z, (x + 1) * Z, (y + 1) * Z,
                                                 fill="#ff5050", outline="", tags="preview")

    def on_release(self, e):
        if self.tool.get() != "crayon" and self.start:
            self.canvas.delete("preview")
            self.apply(self.shape(self.start, self.pos(e)), self.color.get())
        self.start = self.last = None

    
if __name__ == "__main__":
    root = tk.Tk()
    App(root)
    root.mainloop()
