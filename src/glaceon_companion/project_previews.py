"""Read-only project catalogue and limited, short-lived preview capabilities."""
from __future__ import annotations

import hashlib
import html
import mimetypes
import os
import re
import secrets
import threading
import time
from pathlib import Path, PurePosixPath
from urllib.parse import quote

from .workspace import workspace_root

SKIP = {'.git', '.venv', 'venv', 'node_modules', '__pycache__', '.expo'}
PRIVATE = {'secrets.json', 'authorization.json', 'config.json', 'work-tasks.json', 'companion.sqlite3'}
TEXT = {'.txt', '.md', '.py', '.ts', '.tsx', '.jsx', '.js', '.mjs', '.css', '.json', '.csv'}
IMAGES = {'.png', '.jpg', '.jpeg', '.webp', '.gif', '.svg'}
ENTRIES = {'.html', '.htm', '.pdf'} | IMAGES | TEXT
ASSETS = ENTRIES | {'.glb', '.gltf', '.bin', '.woff', '.woff2', '.ttf', '.ico', '.mp3', '.mp4', '.ogg', '.wav'}
MAX_BYTES = 50 * 1024 * 1024
CDNS = 'https://unpkg.com https://cdn.jsdelivr.net https://cdnjs.cloudflare.com'
CSP = ("sandbox allow-scripts; default-src 'none'; "
       f"script-src 'self' 'unsafe-inline' 'unsafe-eval' {CDNS}; "
       f"style-src 'self' 'unsafe-inline' {CDNS}; img-src 'self' data: blob: {CDNS}; "
       f"font-src 'self' data: {CDNS}; connect-src 'self' {CDNS}; "
       "media-src 'self' blob:; worker-src 'self' blob:; frame-src 'none'; "
       "object-src 'none'; base-uri 'none'; form-action 'none'; frame-ancestors 'self'")

# A local display-only error reporter. No credential, native message bridge,
# network request or PC action is exposed to generated JavaScript.
ERROR_REPORTER = '''<script>(function(){let shown=false;function report(value){if(shown)return;shown=true;function display(){const banner=document.createElement('div');banner.setAttribute('role','alert');banner.style.cssText='position:fixed;bottom:12px;left:12px;right:12px;z-index:2147483647;background:#381d2a;color:#fff;padding:14px;border:1px solid #ee7c9b;border-radius:10px;font:14px system-ui;white-space:pre-wrap;max-height:35vh;overflow:auto';banner.textContent='Error del proyecto: '+String(value).slice(0,1200)+'\\nPide a Arfoxia que lo corrija y pulsa Recargar.';document.body.appendChild(banner);}if(document.body)display();else document.addEventListener('DOMContentLoaded',display,{once:true});}window.addEventListener('error',event=>report(event.message||'No se pudo cargar un recurso del proyecto.'),true);window.addEventListener('unhandledrejection',event=>report(event.reason&&event.reason.message||event.reason||'Promesa rechazada.'));})();</script>'''


def html_with_error_reporter(text):
    match = re.search(r'<head(?:\s[^>]*)?>', text, re.IGNORECASE)
    if match:
        return text[:match.end()] + ERROR_REPORTER + text[match.end():]
    # Keep a doctype first, including HTML documents without an explicit head.
    match = re.match(r'\s*<!doctype[^>]*>', text, re.IGNORECASE)
    pos = match.end() if match else 0
    return text[:pos] + ERROR_REPORTER + text[pos:]


class ProjectPreviews:
    TTL = 1800

    def __init__(self, config, clock=time.monotonic):
        self.config, self.clock = config, clock
        self.lock = threading.Lock()
        self.tickets = {}

    @property
    def root(self):
        return workspace_root(self.config.workspace_directory)

    def _safe_path(self, relative: str):
        if not isinstance(relative, str) or '\\' in relative or '\0' in relative:
            raise ValueError('Ruta de proyecto no válida.')
        parts = relative.split('/')
        if not parts or any(not p or p in {'.', '..'} or ':' in p or p.startswith('.') or p.casefold() in SKIP | PRIVATE for p in parts):
            raise ValueError('Ruta de proyecto no permitida.')
        root = self.root
        path = root
        for part in parts:
            path = path / part
            if path.is_symlink() or (hasattr(path, 'is_junction') and path.is_junction()):
                raise ValueError('Los enlaces y uniones no se publican en el visualizador.')
        if not path.resolve().is_relative_to(root) or not path.is_file() or path.suffix.lower() not in ASSETS or path.stat().st_size > MAX_BYTES or path.stat().st_nlink > 1:
            raise ValueError('Ese resultado no está disponible en el visualizador.')
        return path

    @staticmethod
    def _id(relative):
        return hashlib.sha256(relative.encode('utf-8')).hexdigest()[:32]

    def catalogue(self):
        root = self.root
        grouped = {}
        visited = 0
        if not root.is_dir():
            return []
        for directory, dirs, files in os.walk(root, followlinks=False):
            dirs[:] = sorted(d for d in dirs if not d.startswith('.') and d.casefold() not in SKIP and
                             not (Path(directory) / d).is_symlink() and not (hasattr(Path, 'is_junction') and (Path(directory) / d).is_junction()))
            for name in sorted(files):
                visited += 1
                if visited > 5000:
                    break
                path = Path(directory) / name
                if path.suffix.lower() not in ENTRIES:
                    continue
                relative = path.relative_to(root).as_posix()
                try:
                    safe = self._safe_path(relative)
                    group = relative.split('/')[0] if '/' in relative else '(carpeta base)'
                    kind = 'html' if safe.suffix.lower() in {'.html', '.htm'} else 'image' if safe.suffix.lower() in IMAGES else 'pdf' if safe.suffix.lower() == '.pdf' else 'text'
                    grouped.setdefault(group, []).append(dict(id=self._id(relative), title=group if group != '(carpeta base)' else name,
                        entry=relative, kind=kind, modified_at=safe.stat().st_mtime, size=safe.stat().st_size))
                except (ValueError, OSError):
                    continue
            if visited > 5000:
                break
        output = []
        for entries in grouped.values():
            entries.sort(key=lambda e: (e['kind'] != 'html', PurePosixPath(e['entry']).name.casefold() != 'index.html', -e['modified_at']))
            output.append({**entries[0], 'entries': entries[:100]})
        return sorted(output, key=lambda p: p['modified_at'], reverse=True)[:200]

    def related(self, results, *, since=None, catalogue=None):
        paths = []
        commands = False
        for result in results:
            if not isinstance(result, dict) or not result.get('success'):
                continue
            data = result.get('data') or {}
            if not isinstance(data, dict):
                continue
            for key in ('path', 'destination', 'working_directory'):
                value = data.get(key)
                if isinstance(value, str):
                    try:
                        path = Path(value)
                        paths.append((path if path.is_absolute() else self.root / path).resolve())
                    except OSError:
                        pass
            commands |= result.get('action') in {'run_python', 'run_powershell'}
        output = []
        root = self.root
        for project in self.catalogue() if catalogue is None else catalogue:
            entry = root / project['entry']
            related = any(p == entry or (p != root and entry.is_relative_to(p)) or
                          (p.parent == entry.parent and p != root) for p in paths)
            changed = commands and since is not None and any(e['modified_at'] >= since for e in project['entries'])
            if related or changed:
                output.append({k: v for k, v in project.items() if k != 'entries'})
        return output[:12]

    def issue(self, project_id):
        entry = next((e for p in self.catalogue() for e in p['entries'] if e['id'] == project_id), None)
        if entry is None:
            raise ValueError('El proyecto no existe o ya no está disponible.')
        with self.lock:
            now = self.clock()
            self.tickets = {t: row for t, row in self.tickets.items() if row['expires'] > now}
            if len(self.tickets) >= 128:
                raise ValueError('Hay demasiadas vistas abiertas; cierra una o espera a que caduque.')
            token = secrets.token_urlsafe(32)
            self.tickets[token] = {'entry': entry['entry'], 'expires': now + self.TTL, 'root': str(self.root)}
        filename = PurePosixPath(entry['entry']).name
        return {'path': f'/project-preview/{token}/{quote(filename, safe="")}', 'title': entry['title'],
                'entry': entry['entry'], 'kind': entry['kind'], 'expires_in': self.TTL}

    def resource(self, ticket, asset):
        with self.lock:
            row = self.tickets.get(ticket)
            if row is None or row['expires'] <= self.clock() or row['root'] != str(self.root):
                self.tickets.pop(ticket, None)
                raise ValueError('La vista ha caducado. Vuelve a abrirla desde el visualizador.')
            row = dict(row)
        if not asset or '\\' in asset or any(not p or p in {'.', '..'} or ':' in p for p in asset.split('/')):
            raise ValueError('Recurso de proyecto no permitido.')
        relative = (PurePosixPath(row['entry']).parent / asset).as_posix()
        path = self._safe_path(relative)
        is_text_entry = relative == row['entry'] and path.suffix.lower() in TEXT
        mime = {'.js': 'text/javascript', '.mjs': 'text/javascript', '.gltf': 'model/gltf+json', '.glb': 'model/gltf-binary'}.get(path.suffix.lower(), mimetypes.guess_type(path.name)[0] or 'application/octet-stream')
        if is_text_entry:
            if path.stat().st_size > 2 * 1024 * 1024:
                raise ValueError('El archivo es demasiado grande para la vista de texto.')
            text = html.escape(path.read_text(encoding='utf-8-sig', errors='replace'))
            return path, 'text/html', ('<!doctype html><meta name="viewport" content="width=device-width,initial-scale=1">'
                '<style>body{background:#061522;color:#edfaff;padding:16px}pre{white-space:pre-wrap;overflow-wrap:anywhere}</style><pre>' + text + '</pre>')
        if path.suffix.lower() in {'.html', '.htm'}:
            return path, 'text/html', html_with_error_reporter(path.read_text(encoding='utf-8-sig', errors='replace'))
        return path, mime, None
