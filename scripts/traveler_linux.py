"""Lightweight Linux display client; no model, chats, shell tools or owner token.

Run inside the logged-in graphical user's session (not as root). GTK3,
PyGObject, Pillow and gtk-layer-shell are required on KDE Wayland.
"""
from __future__ import annotations

import argparse
import json
import math
import os
import queue
import random
import signal
import subprocess
import sys
import threading
import time
import urllib.request
from pathlib import Path

from traveler_geometry import Drag, anchored_rect, clamp_anchor, context_actions


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", type=Path, required=True)
    args = parser.parse_args()
    root = args.root.resolve()
    sys.path.insert(0, str(root / "lib"))
    from sprites import SpriteLibrary
    from pet_motion import EXPRESSION_LABELS, direction_for_delta, step_towards
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
            self.wakeup = threading.Event()
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
            self.fetch_home = None
            self.fetch_returning = False
            self.gesture_until = 0.0
            self.drag = None
            self.painted = 0
            self.x, self.y = 100, 300
            self.props = {}
            self.objects = {}
            self.menu = None
            self.dialog = None
            self.sound_enabled = True
            self.last_sound = 0.0
            self.last_rects = []
            self.monitor = display.get_primary_monitor() or display.get_monitor(0)
            geometry = self.monitor.get_geometry()
            self.max_width = max(library.specs[n].width * 3 for n in available)
            self.max_height = max(library.specs[n].height * 3 for n in available)
            self.window = Gtk.Window(title="Arfoxia · Paseo")
            self.window.set_decorated(False)
            self.window.set_accept_focus(False)
            self.window.set_skip_taskbar_hint(True)
            self.window.set_skip_pager_hint(True)
            self.window.set_app_paintable(True)
            # Never move the input surface while dragging. GDK x/y remain in one
            # stable logical coordinate system, including fractional display scaling.
            self.window.set_default_size(geometry.width, geometry.height)
            visual = self.window.get_screen().get_rgba_visual()
            if visual:
                self.window.set_visual(visual)
            if layer:
                layer.init_for_window(self.window)
                layer.set_namespace(self.window, "arfoxia-traveler")
                layer.set_layer(self.window, layer.Layer.OVERLAY)
                layer.set_keyboard_mode(self.window, layer.KeyboardMode.NONE)
                layer.set_exclusive_zone(self.window, -1)
                layer.set_monitor(self.window, self.monitor)
                for edge in (layer.Edge.LEFT, layer.Edge.RIGHT, layer.Edge.TOP, layer.Edge.BOTTOM):
                    layer.set_anchor(self.window, edge, True)
            else:
                self.window.set_keep_above(True)
                self.window.move(geometry.x, geometry.y)
            self.canvas = Gtk.DrawingArea()
            self.canvas.set_size_request(1, 1)
            self.window.add(self.canvas)
            self.canvas.add_events(Gdk.EventMask.BUTTON_PRESS_MASK | Gdk.EventMask.BUTTON_RELEASE_MASK
                                   | Gdk.EventMask.POINTER_MOTION_MASK)
            self.canvas.connect("draw", self.draw)
            self.canvas.connect("button-press-event", self.press)
            self.canvas.connect("button-release-event", self.release)
            self.canvas.connect("motion-notify-event", self.motion)
            self.window.connect("delete-event", lambda *_: self.quit())
            self.choose_animation("Idle")
            self.set_position(geometry.width - 180, geometry.height - 100)
            for name, scale in (("bed", 2), ("lemon", 2)):
                path = root / "props" / (name + ".png")
                if path.is_file():
                    image = GdkPixbuf.Pixbuf.new_from_file(str(path))
                    self.props[name] = image.scale_simple(image.get_width() * scale,
                        image.get_height() * scale, GdkPixbuf.InterpType.NEAREST)
            self.load_preferences()
            GLib.timeout_add(35, self.tick)
            GLib.timeout_add_seconds(12, self.wander)
            threading.Thread(target=self.network, daemon=True, name="display-heartbeat").start()

        def bounds(self):
            rect = self.monitor.get_geometry()
            width, height = self.canvas.get_allocated_width(), self.canvas.get_allocated_height()
            return (width if width > 1 else rect.width, height if height > 1 else rect.height)

        def set_position(self, x, y):
            self.x, self.y = clamp_anchor(x, y, *self.bounds(), self.max_width, self.max_height)
            self.damage()

        def items(self):
            for name, point in self.objects.items():
                img = self.props[name]
                yield name, img, anchored_rect(*point, img.get_width(), img.get_height())
            img = self.frames[self.index]
            yield "pet", img, anchored_rect(self.x, self.y, img.get_width(), img.get_height())

        def damage(self):
            rects = [rect for _, _, rect in self.items()]
            for x, y, w, h in self.last_rects + rects:
                self.canvas.queue_draw_area(x - 2, y - 2, w + 4, h + 4)
            self.last_rects = rects

        def load_preferences(self):
            path = root / "display.json"
            try:
                if path.is_symlink() or path.stat().st_size > 4096:
                    return
                value = json.loads(path.read_text())
                if not isinstance(value, dict) or not isinstance(value.get("objects", {}), dict):
                    return
                self.sound_enabled = value.get("sound", True) is True
                self.set_position(float(value["x"]), float(value["y"]))
                for name, point in value.get("objects", {}).items():
                    if name in self.props and len(point) == 2 and all(math.isfinite(float(v)) for v in point):
                        img = self.props[name]
                        self.objects[name] = clamp_anchor(*point, *self.bounds(), img.get_width(), img.get_height())
            except (OSError, ValueError, TypeError, KeyError):
                pass

        def save_preferences(self):
            path = root / "display.json"
            temp = root / "display.new"
            if path.is_symlink() or temp.is_symlink():
                return
            try:
                fd = os.open(temp, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
                with os.fdopen(fd, "w") as stream:
                    json.dump({"x": self.x, "y": self.y, "sound": self.sound_enabled,
                               "objects": self.objects}, stream)
                temp.replace(path)
            except OSError:
                self.info("No se pudo guardar la posición local.")

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
            self.damage()

        def draw(self, widget, cr):
            cr.set_operator(cairo.OPERATOR_SOURCE)
            cr.set_source_rgba(0, 0, 0, 0)
            cr.paint()
            cr.set_operator(cairo.OPERATOR_OVER)
            region = cairo.Region()
            for _, img, (x, y, w, h) in self.items():
                Gdk.cairo_set_source_pixbuf(cr, img, x, y)
                cr.paint()
                region.union(cairo.RectangleInt(x, y, w, h))
            # Only sprites/props take input; all other pixels pass to the OS.
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
            if self.drag or (self.menu and self.menu.get_visible()):
                return True
            name = "Sleep" if self.pet.get("asleep") else "Sit" if self.pet.get("seated") else None
            if name:
                self.target = None
                self.fetch_home = None
                self.fetch_returning = False
                self.choose_animation(name)
            elif self.target and not self.drag:
                dx, dy = self.target[0] - self.x, self.target[1] - self.y
                self.choose_animation("Walk", direction_for_delta(dx, dy))
                self.set_position(*step_towards(self.x, self.y, *self.target))
                if self.fetch_returning and "lemon" in self.objects:
                    img = self.props["lemon"]
                    self.objects["lemon"] = clamp_anchor(self.x + 35, self.y - 20,
                        *self.bounds(), img.get_width(), img.get_height())
                    self.damage()
                if math.hypot(dx, dy) < 5:
                    if self.fetch_home and not self.fetch_returning:
                        self.target = self.fetch_home
                        self.fetch_returning = True
                    else:
                        self.target = self.fetch_home = None
                        self.fetch_returning = False
                        self.choose_animation("Pose")
                        self.gesture_until = now + 2
                        self.save_preferences()
            elif now > self.gesture_until and self.animation not in {"Idle", "Walk"}:
                self.choose_animation("Idle")
            if now >= self.next_at:
                self.index = (self.index + 1) % len(self.frames)
                self.next_at = now + self.durations[self.index] / 1000
                self.damage()
            return True

        def wander(self):
            if (self.active and not self.drag and not self.target and not (self.menu and self.menu.get_visible())
                    and not self.pet.get("asleep") and not self.pet.get("seated")):
                if random.random() < 0.6:
                    self.target = clamp_anchor(self.x + random.randint(-220, 220),
                        self.y + random.randint(-170, 170), *self.bounds(), self.max_width, self.max_height)
                else:
                    self.choose_animation(random.choice([n for n in ("Nod", "Hop", "Pose", "LookUp", "TailWhip") if n in available]))
                    self.gesture_until = time.monotonic() + 2
            return True

        def press(self, widget, event):
            if event.button == 1:
                self.target = None
                self.fetch_home = None
                self.fetch_returning = False
                # Pet is painted over props, so hit-test in reverse paint order.
                for name, _, (x, y, w, h) in reversed(list(self.items())):
                    if x <= event.x < x + w and y <= event.y < y + h:
                        point = (self.x, self.y) if name == "pet" else self.objects[name]
                        self.drag = Drag(event.x, event.y, *point, subject=name)
                        break
            elif event.button == 3:
                self.menu = menu = Gtk.Menu()
                for label, action in context_actions(self.pet.get("asleep"), self.pet.get("seated"),
                                                    "bed" in self.objects, "lemon" in self.objects):
                    item = Gtk.MenuItem(label=label)
                    item.set_sensitive(action not in {"bed", "lemon"} or action in self.props)
                    item.connect("activate", lambda _, value=action: self.action(value))
                    menu.append(item)
                expressions = Gtk.MenuItem(label="Expresiones")
                submenu = Gtk.Menu()
                for name, label in EXPRESSION_LABELS.items():
                    if name in available:
                        item = Gtk.MenuItem(label=label)
                        item.connect("activate", lambda _, value=name: self.expression(value))
                        submenu.append(item)
                expressions.set_submenu(submenu)
                expressions.set_sensitive(not self.pet.get("asleep") and not self.pet.get("seated"))
                menu.insert(expressions, 6)
                sound = Gtk.CheckMenuItem(label="Sonidos de Arfoxia")
                sound.set_active(self.sound_enabled)
                sound.connect("toggled", self.toggle_sound)
                menu.insert(sound, 7)
                menu.show_all()
                anchor = Gdk.Rectangle()
                anchor.x, anchor.y = round(event.x), round(event.y)
                anchor.width = anchor.height = 1
                # Anchor to this fixed surface, not synthetic global pointer coords.
                menu.popup_at_rect(self.canvas.get_window(), anchor,
                                   Gdk.Gravity.SOUTH_EAST, Gdk.Gravity.NORTH_WEST, event)
            return True

        def motion(self, widget, event):
            if self.drag:
                self.move_drag(event.x, event.y)
            return True

        def move_drag(self, x, y):
            point = self.drag.move(x, y)
            if self.drag.subject == "pet":
                self.set_position(*point)
            else:
                img = self.props[self.drag.subject]
                self.objects[self.drag.subject] = clamp_anchor(*point, *self.bounds(), img.get_width(), img.get_height())
                self.damage()

        def release(self, widget, event):
            if event.button == 1 and self.drag:
                self.move_drag(event.x, event.y)
                clicked, subject = self.drag.clicked, self.drag.subject
                self.drag = None
                self.save_preferences()
                if clicked and subject == "pet":
                    self.action("pet")
                elif subject == "lemon":
                    self.start_fetch()
            return True

        def send(self, action):
            self.actions.put(action)
            self.wakeup.set()

        def expression(self, name):
            if not self.pet.get("asleep") and not self.pet.get("seated"):
                self.target = None
                self.fetch_home = None
                self.fetch_returning = False
                self.choose_animation(name)
                self.gesture_until = time.monotonic() + max(2, sum(self.durations) / 1000)

        def play_sound(self):
            path = root / "sounds" / "cry.ogg"
            now = time.monotonic()
            if self.sound_enabled and path.is_file() and now - self.last_sound > 3:
                self.last_sound = now
                try:
                    subprocess.Popen(["pw-play", str(path)], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
                except OSError:
                    pass

        def toggle_sound(self, item):
            self.sound_enabled = item.get_active()
            self.save_preferences()
            self.play_sound()

        def info(self, text=None):
            if self.dialog:
                self.dialog.destroy()
            if text is None:
                text = (f"{self.pet.get('name', 'Arfoxia')} · {self.last_response}\n"
                        f"Hambre: {self.pet.get('hunger', '?')} · Energía: {self.pet.get('energy', '?')}\n"
                        f"Felicidad: {self.pet.get('happiness', '?')}\n\n"
                        "Arrastra a Arfoxia, la cama o el limón. Clic derecho: opciones.\n"
                        "La IA, el chat y las GPU continúan en el PC Windows.\n"
                        "Este cliente no tiene permisos de administrador del PC.")
            self.dialog = Gtk.MessageDialog(message_type=Gtk.MessageType.INFO,
                buttons=Gtk.ButtonsType.CLOSE, text="Arfoxia · Paseo")
            self.dialog.format_secondary_text(text)
            self.dialog.connect("response", lambda dialog, *_: dialog.destroy())
            self.dialog.show_all()

        def start_fetch(self):
            if "lemon" in self.objects and not self.pet.get("asleep") and not self.pet.get("seated"):
                self.fetch_home = (self.x, self.y)
                self.fetch_returning = False
                self.target = clamp_anchor(*self.objects["lemon"], *self.bounds(), self.max_width, self.max_height)
                self.send("play")

        def action(self, action):
            if action in {"bed", "lemon"}:
                if action not in self.objects:
                    img = self.props[action]
                    self.objects[action] = clamp_anchor(self.x + 150, self.y, *self.bounds(),
                                                        img.get_width(), img.get_height())
                if action == "lemon":
                    self.start_fetch()
                self.damage()
                self.save_preferences()
            elif action.startswith("remove-"):
                if action == "remove-lemon":
                    self.target = self.fetch_home = None
                    self.fetch_returning = False
                self.objects.pop(action[7:], None)
                self.damage()
                self.save_preferences()
            elif action == "capture":
                path = Path.home() / "Pictures" / "Arfoxia"
                try:
                    path.mkdir(parents=True, exist_ok=True)
                    subprocess.Popen(["spectacle", "-b", "-n", "-f", "-o",
                        str(path / (time.strftime("%Y%m%d-%H%M%S") + ".png"))])
                except OSError:
                    self.info("No se pudo iniciar Spectacle o guardar la captura en Pictures/Arfoxia.")
            elif action == "status":
                self.info()
            else:
                self.send(action)
                if action in {"pet", "feed", "wake"}:
                    self.expression("Pose" if action == "pet" else "Nod")
                    self.play_sound()

        def hide(self):
            self.active = self.shown = self.ready = False
            self.window.hide()
            self.target = self.drag = None
            self.fetch_home = None
            self.fetch_returning = False
            if self.menu:
                self.menu.popdown()
            if self.dialog:
                self.dialog.destroy()
                self.dialog = None

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
                "stationary_surface": True, "objects": self.objects,
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
                self.wakeup.wait(2)
                self.wakeup.clear()

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
