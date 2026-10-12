"""Lightweight Linux display client; no model, chats, shell tools or owner token.

Run inside the logged-in graphical user's session (not as root). GTK3,
PyGObject, Pillow and gtk-layer-shell are required on KDE Wayland.
"""
from __future__ import annotations

import argparse
import json
import math
import queue
import random
import signal
import sys
import threading
import time
import urllib.request
from pathlib import Path


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", type=Path, required=True)
    args = parser.parse_args()
    root = args.root.resolve()
    sys.path.insert(0, str(root / "lib"))
    from sprites import SpriteLibrary
    from pet_motion import direction_for_delta, step_towards
    import cairo
    import gi

    gi.require_version("Gtk", "3.0")
    gi.require_version("Gdk", "3.0")
    gi.require_version("GdkPixbuf", "2.0")
    from gi.repository import Gdk, GdkPixbuf, GLib, Gtk

    config_path = root / "client.json"
    if config_path.stat().st_mode & 0o077:
        raise RuntimeError("client.json debe ser privado (chmod 600)")
    config = json.loads(config_path.read_text())
    # A reverse OpenSSH tunnel is mandatory; never send the credential via raw LAN HTTP.
    url = config["url"]
    if url != "http://127.0.0.1:18842":
        raise RuntimeError("El cliente solo utiliza el túnel SSH local en 18842")
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
    library = SpriteLibrary(root / "sprites")
    available = set(library.available())
    if not {"Idle", "Walk", "Sleep", "Sit"}.issubset(available):
        raise RuntimeError("Faltan animaciones necesarias")
    ok, _ = Gtk.init_check()
    if not ok:
        raise RuntimeError("No hay una sesión gráfica disponible")
    display = Gdk.Display.get_default()
    is_wayland = "Wayland" in type(display).__name__
    layer = None
    if is_wayland:
        gi.require_version("GtkLayerShell", "0.1")
        from gi.repository import GtkLayerShell
        if not GtkLayerShell.is_supported():
            raise RuntimeError("El compositor no soporta una superposición Layer Shell")
        layer = GtkLayerShell

    class Traveler:
        def __init__(self):
            self.stop = threading.Event()
            self.actions = queue.Queue()
            self.ready = False
            self.shown = False
            self.active = False
            self.deadline = 0.0
            self.pet = {}
            self.last_response = "esperando túnel SSH"
            self.frames = []
            self.durations = ()
            self.index = 0
            self.next_at = 0.0
            self.animation = ""
            self.direction = 0
            self.cache = {}
            self.target = None
            self.gesture_until = 0.0
            self.drag = None
            self.painted = 0
            self.x, self.y = 100, 100
            self.window = Gtk.Window(title="Arfoxia · Paseo")
            self.window.set_decorated(False)
            self.window.set_accept_focus(False)
            self.window.set_skip_taskbar_hint(True)
            self.window.set_skip_pager_hint(True)
            self.window.set_app_paintable(True)
            self.window.set_default_size(260, 260)
            visual = self.window.get_screen().get_rgba_visual()
            if visual:
                self.window.set_visual(visual)
            if layer:
                layer.init_for_window(self.window)
                layer.set_namespace(self.window, "arfoxia-traveler")
                layer.set_layer(self.window, layer.Layer.OVERLAY)
                layer.set_keyboard_mode(self.window, layer.KeyboardMode.NONE)
                layer.set_exclusive_zone(self.window, -1)
                layer.set_anchor(self.window, layer.Edge.LEFT, True)
                layer.set_anchor(self.window, layer.Edge.TOP, True)
            else:
                self.window.set_keep_above(True)
            self.canvas = Gtk.DrawingArea()
            self.canvas.set_size_request(260, 260)
            self.window.add(self.canvas)
            self.canvas.add_events(Gdk.EventMask.BUTTON_PRESS_MASK | Gdk.EventMask.BUTTON_RELEASE_MASK
                                   | Gdk.EventMask.POINTER_MOTION_MASK)
            self.canvas.connect("draw", self.draw)
            self.canvas.connect("button-press-event", self.press)
            self.canvas.connect("button-release-event", self.release)
            self.canvas.connect("motion-notify-event", self.motion)
            self.window.connect("delete-event", lambda *_: self.quit())
            self.choose_animation("Idle")
            self.set_position(*self.bounds()[2:])
            GLib.timeout_add(35, self.tick)
            GLib.timeout_add_seconds(12, self.wander)
            threading.Thread(target=self.network, daemon=True, name="display-heartbeat").start()

        def bounds(self):
            monitor = display.get_primary_monitor() or display.get_monitor(0)
            rect = monitor.get_geometry()
            return rect.x, rect.y, max(0, rect.width - 268), max(0, rect.height - 268)

        def set_position(self, x, y):
            left, top, right, bottom = self.bounds()
            self.x, self.y = max(8, min(right, int(x))), max(8, min(bottom, int(y)))
            if layer:
                layer.set_margin(self.window, layer.Edge.LEFT, self.x)
                layer.set_margin(self.window, layer.Edge.TOP, self.y)
            else:
                self.window.move(left + self.x, top + self.y)

        def choose_animation(self, name, direction=0):
            name = name if name in available else "Idle"
            if (name, direction) == (self.animation, self.direction):
                return
            key = (name, direction)
            if key not in self.cache:
                images, durations = library.frames(name, direction)
                result = []
                for img in images:
                    # Pixel-perfect nearest-neighbour, same PMD assets as the Windows pet.
                    from PIL import Image
                    img = img.resize((img.width * 3, img.height * 3), Image.Resampling.NEAREST)
                    data = GLib.Bytes.new(img.tobytes())
                    pixbuf = GdkPixbuf.Pixbuf.new_from_bytes(data, GdkPixbuf.Colorspace.RGB,
                        True, 8, img.width, img.height, img.width * 4)
                    result.append(pixbuf)
                self.cache[key] = result, durations
            self.frames, self.durations = self.cache[key]
            self.animation, self.direction = key
            self.index = 0
            self.next_at = time.monotonic() + self.durations[0] / 1000

        def draw(self, widget, cr):
            cr.set_operator(cairo.OPERATOR_SOURCE)
            cr.set_source_rgba(0, 0, 0, 0)
            cr.paint()
            cr.set_operator(cairo.OPERATOR_OVER)
            img = self.frames[self.index]
            x, y = (260 - img.get_width()) // 2, 260 - img.get_height()
            Gdk.cairo_set_source_pixbuf(cr, img, x, y)
            cr.paint()
            # Only the sprite's rectangle takes mouse input; the rest passes through.
            region = cairo.Region(cairo.RectangleInt(max(0, x), max(0, y),
                min(260, img.get_width()), min(260, img.get_height())))
            self.window.input_shape_combine_region(region)
            self.ready = True
            self.painted += 1
            return False

        def tick(self):
            now = time.monotonic()
            if self.shown and now > self.deadline:
                self.hide()
            if not self.shown:
                return True
            name = "Sleep" if self.pet.get("asleep") else "Sit" if self.pet.get("seated") else None
            if name:
                self.target = None
                self.choose_animation(name)
            elif self.target and not self.drag:
                dx, dy = self.target[0] - self.x, self.target[1] - self.y
                self.choose_animation("Walk", direction_for_delta(dx, dy))
                self.set_position(*step_towards(self.x, self.y, *self.target))
                if math.hypot(dx, dy) < 5:
                    self.target = None
                    self.choose_animation("Idle")
            elif now > self.gesture_until and self.animation not in {"Idle", "Walk"}:
                self.choose_animation("Idle")
            if now >= self.next_at:
                self.index = (self.index + 1) % len(self.frames)
                self.next_at = now + self.durations[self.index] / 1000
                self.canvas.queue_draw()
            return True

        def wander(self):
            if self.active and not self.drag and not self.pet.get("asleep") and not self.pet.get("seated"):
                if random.random() < 0.6:
                    self.target = (max(8, min(self.bounds()[2], self.x + random.randint(-220, 220))),
                                   max(8, min(self.bounds()[3], self.y + random.randint(-170, 170))))
                else:
                    self.choose_animation(random.choice([n for n in ("Nod", "Hop", "Pose", "LookUp", "TailWhip") if n in available]))
                    self.gesture_until = time.monotonic() + 2
            return True

        def press(self, widget, event):
            if event.button == 1:
                self.drag = (event.x_root, event.y_root, self.x, self.y)
                self.target = None
                self.choose_animation("Idle")
            elif event.button == 3:
                menu = Gtk.Menu()
                for label, action in [("Acariciar", "pet"), ("Dar baya", "feed"),
                    ("Despertar", "wake"), ("Sentarse", "sit"), ("Pasear", "resume"),
                    ("Volver al PC", "return")]:
                    item = Gtk.MenuItem(label=label)
                    item.connect("activate", lambda _, value=action: self.actions.put(value))
                    menu.append(item)
                menu.show_all()
                menu.popup_at_pointer(event)
            return True

        def motion(self, widget, event):
            if self.drag:
                dx, dy = event.x_root - self.drag[0], event.y_root - self.drag[1]
                self.set_position(self.drag[2] + dx, self.drag[3] + dy)
            return True

        def release(self, widget, event):
            if self.drag and abs(self.x - self.drag[2]) + abs(self.y - self.drag[3]) < 6:
                self.actions.put("pet")
                self.choose_animation("Pose")
                self.gesture_until = time.monotonic() + 2
            self.drag = None
            return True

        def hide(self):
            self.active = self.shown = self.ready = False
            self.window.hide()
            self.target = self.drag = None

        def apply(self, result, started):
            if time.monotonic() - started > 5:
                self.hide()
                return False
            self.pet = result["pet"]
            self.active = result["active"]
            self.deadline = started + 5
            if self.active or result.get("requested"):
                self.shown = True
                self.window.show_all()
            else:
                self.hide()
            self.last_response = "conectado"
            self.health()
            return False

        def health(self):
            path = root / "status.json"
            temp = path.with_suffix(".tmp")
            temp.write_text(json.dumps({"active": self.active, "shown": self.shown,
                "ready": self.ready, "frames_painted": self.painted, "animation": self.animation,
                "x": self.x, "y": self.y, "wayland_layer": bool(layer),
                "connection": self.last_response, "updated": time.time()}))
            temp.replace(path)

        def failed(self):
            self.hide()
            self.last_response = "sin conexión"
            self.health()
            return False

        def post(self, path, body):
            request = urllib.request.Request(url + "/api/travel/client/" + path,
                data=json.dumps(body).encode(), method="POST",
                headers={"Authorization": "Bearer " + config["token"], "Content-Type": "application/json"})
            with opener.open(request, timeout=3) as response:
                return json.loads(response.read(65536))

        def network(self):
            while not self.stop.is_set():
                try:
                    while not self.actions.empty():
                        action = self.actions.get_nowait()
                        self.post("return" if action == "return" else "interact",
                                  {} if action == "return" else {"kind": action})
                    started = time.monotonic()
                    result = self.post("heartbeat", {"ready": self.ready})
                    GLib.idle_add(self.apply, result, started)
                except (OSError, ValueError):
                    GLib.idle_add(self.failed)
                self.stop.wait(2)

        def quit(self):
            self.stop.set()
            Gtk.main_quit()
            return True

    traveler = Traveler()
    GLib.unix_signal_add(GLib.PRIORITY_DEFAULT, signal.SIGTERM, traveler.quit)
    GLib.unix_signal_add(GLib.PRIORITY_DEFAULT, signal.SIGINT, traveler.quit)
    Gtk.main()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
